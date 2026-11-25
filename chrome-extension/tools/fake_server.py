"""A tiny stand-in for jobwatch's /ext endpoints (see chrome-extension/API.md), for the end-to-end test.

Made-up data only. It remembers what the extension sent, so a test can look at it afterwards.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:  # report the real version, so the demo video never shows a stale one
    from jobwatch import __version__ as JOBWATCH_VERSION
except ImportError:
    JOBWATCH_VERSION = "0.7.0"
TOKEN = "test-token"
RESUME = b"%PDF-1.4\n% a made-up resume for Jordan Rivera\n%%EOF\n"

APPLICANT = {
    "first_name": "Jordan", "last_name": "Rivera", "preferred_name": "Jo", "email": "jordan@example.com",
    "phone": "+1 555 0100", "city": "Boulder", "state": "CO", "country": "United States", "postal_code": "80301",
    "linkedin": "https://www.linkedin.com/in/jordan-rivera-example", "github": "https://github.com/jordan-example",
    "website": "https://jordan.example.com", "work_authorized": "yes", "needs_sponsorship": "no", "relocate": "yes",
    "notice_period": "2 weeks", "salary": "180K-190K", "gender": "decline", "race": "decline", "hispanic": "decline",
    "veteran": "decline", "disability": "decline",
}

ANSWERS = [
    {"question": "Why do you want to work at Globex?", "answer": "I like small teams that own what they run.",
     "company": "Globex", "title": "SRE", "applied_at": "2026-09-14"},
    {"question": "Describe a time you handled a production incident.",
     "answer": "A bad deploy took checkout down; I rolled back in ten minutes and wrote the fix.",
     "company": "Umbrella", "title": "Platform Engineer", "applied_at": "2026-08-02"},
    {"question": "Describe a project you are most proud of and your role in it.",
     "answer": "I led the move of our nightly batch jobs onto a small queue-based system. I wrote the design, "
               "built the retry logic and trained two teammates to run it. Failed runs dropped by about "
               "eighty percent, and on-call pages for it nearly stopped.",
     "company": "Umbrella", "title": "Platform Engineer", "applied_at": "2026-08-02"},
    {"question": "What are your greatest strengths, and one area you are working on?",
     "answer": "I am good at turning a vague problem into a short written plan that a team can act on. "
               "I am working on delegating sooner: I tend to fix things myself, so I now hand them off "
               "with clear notes and check in a day later.",
     "company": "Globex", "title": "SRE", "applied_at": "2026-09-14"},
    {"question": "Tell us about a time you disagreed with a teammate and how you resolved it.",
     "answer": "A teammate wanted to ship a risky change on a Friday, and I wanted to wait. We wrote down "
               "what could go wrong and agreed on a staged rollout on Monday instead. It went out cleanly, "
               "and we kept the checklist for later launches.",
     "company": "Umbrella", "title": "Platform Engineer", "applied_at": "2026-08-02"},
    {"question": "How much notice do you need before starting?", "answer": "Two weeks.",
     "company": "Globex", "title": "SRE", "applied_at": "2026-09-14"},
]


# What the model would write from demo/resume.html (the made-up resume) for a question no earlier answer covers.
DRAFTS = {
    "kubernetes": "At Globex I ran 40 Kubernetes clusters serving 2M requests a minute. I owned the upgrades, "
                  "autoscaling and on-call, and right-sizing the nodes cut our compute bill by a quarter. "
                  "At Initech I now build the deploy pipeline that 30 teams use to ship onto those clusters.",
}


# A stand-in for jobwatch's Today page: a long list with a Read posting button on one card, speaking to the
# extension the way jobwatch/static/index.html does (window messages through page-bridge.js), and drawing only that
# card when it is read.
TODAY_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>jobwatch (demo)</title></head><body>
<div style="height:1500px">Cards above</div>
<div id="job-demo"><span id="state">no text</span> <button id="read">Read posting</button></div>
<div style="height:1500px">Cards below</div>
<script>
  window.answers = [];
  window.addEventListener('message', (e) => {
    if (e.source !== window || !e.data || e.data.type !== 'jobwatch:read-posting-done') return;
    window.answers.push(e.data);
    const word = e.data.closed ? 'closed' : 'read';
    document.getElementById('state').textContent = e.data.ok ? word : 'failed: ' + e.data.error;
  });
  const posting = new URLSearchParams(location.search).get('posting');
  document.getElementById('read').onclick = () => window.postMessage(
    { type: 'jobwatch:read-posting', key: 'demo', url: posting }, location.origin);
</script></body></html>"""

NOT_TRACKED = "jobwatch doesn't track this job yet: save the posting to jobwatch first"
# What jobwatch's ats.check answers for the demo job (autofill.ats_check adds matched_by and can_tailor)
ATS = {"key": "ashby:initech/4f1c", "company": "Initech", "title": "Platform Engineer", "file": "resume.pdf",
       "tailored": False, "read_with": "pdftotext", "chars": 2400, "score": 50,
       "found": [{"term": "Python", "kind": "must", "count": 3}, {"term": "Kubernetes", "kind": "must", "count": 2}],
       "missing": [{"term": "Terraform", "kind": "must", "count": 2}, {"term": "Kafka", "kind": "nice", "count": 1}],
       "checks": [], "matched_by": "link", "can_tailor": True}
COVER = ("Hello Initech team,\n\nAt Globex I ran 40 Kubernetes clusters and wrote the Python tooling the on-call "
         "rotation used. That is the platform work your posting asks for, and I would like to bring it to Initech.\n\n"
         "Thank you for your time.")


class State:
    def __init__(self) -> None:
        self.contexts: list[dict] = []  # /ext/context: the query of each call (url, company, title)
        self.ats_calls: list[dict] = []  # /ext/ats: what the extension sent
        self.covers: list[dict] = []  # /ext/cover: what the extension sent
        self.tailors: list[dict] = []  # /ext/tailor: what the extension sent
        self.tailored = False  # after /ext/tailor: the resume is the job's own, and the ATS check says so
        self.ats_answer: dict = {}  # /ext/ats: fields to change in the canned answer (score, checks, ...)
        self.cover_answer: dict = {}  # /ext/cover: fields to change in the canned answer (local, warnings, ...)
        self.cover_delay = 0.0  # /ext/cover: seconds to take before answering, to see the panel's working view
        self.submitted: list[dict] = []
        self.answers: list[dict] = []  # /ext/answers: a snapshot per Submit press
        self.drafts: list[dict] = []
        self.postings: list[dict] = []
        self.imports: list[dict] = []  # /ext/import-list: a snapshot per import
        self.imported: set[tuple[str, str]] = set()  # (site, id) of the jobs an earlier import added
        self.requests: list[tuple[str, str]] = []
        self.token = TOKEN
        self.know_every_page = False  # live_check.py: every page is a known job, with a resume
        # /ext/ping's features (web.EXT_FEATURES); an older jobwatch has none
        self.features = ["posting", "reply", "import-list", "ats", "cover"]
        self.replies: list[dict] = []  # /ext/reply: what the extension sent from a conversation
        self.reply_answer: dict = {}  # /ext/reply: fields to change in the canned answer (local, warnings, ...)
        self.reply_delay = 0.0  # /ext/reply: seconds to take before answering, to see the panel's working view
        self.reply_status = 200  # /ext/reply: an error status, to see how the panel words it
        self.draft_answer = ""  # store_assets.py: a draft that reads like one; else it names the question


def _handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, kind: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict):
            self._send(code, json.dumps(data).encode())

        def _allowed(self) -> bool:
            if self.headers.get("X-Jobwatch-Extension") == state.token:
                return True
            self._json(403, {"error": "bad token"})
            return False

        def do_GET(self):
            url = urlparse(self.path)
            state.requests.append(("GET", url.path))
            if url.path == "/demo/today":  # jobwatch's own page, standing in for its Today (no token: a browser asks)
                self._send(200, TODAY_PAGE.encode(), "text/html; charset=utf-8")
                return
            if not self._allowed():
                return
            page = parse_qs(url.query).get("url", [""])[0]
            known = state.know_every_page or "initech" in page
            if url.path == "/ext/ping":
                self._json(200, {"ok": True, "version": JOBWATCH_VERSION, "features": state.features})
            elif url.path == "/ext/context":
                state.contexts.append({k: v[0] for k, v in parse_qs(url.query).items()})
                job = {"key": "ashby:initech/4f1c", "title": "Platform Engineer", "company": "Initech",
                       "status": "queued", "url": page, "matched_by": "link"} if known else None
                self._json(200, {"job": job, "applicant": APPLICANT, "answers": ANSWERS,
                                 "resume": {"name": "resume.pdf", "type": "application/pdf",
                                            "tailored": state.tailored} if known else None})
            elif url.path == "/ext/resume" and known:
                self._send(200, RESUME, "application/pdf", {"Content-Disposition": 'attachment; filename="resume.pdf"'})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            state.requests.append(("POST", self.path))
            if not self._allowed():
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/ext/draft":
                state.drafts.append(body)
                # The real endpoint (autofill.draft) has the chat's model answer from the resume, stories and
                # posting; here a canned answer stands in for it, one that quotes demo/resume.html.
                canned = next((a for q, a in DRAFTS.items() if q in body["question"].lower()), None)
                answer = state.draft_answer or canned or f"A drafted answer to: {body['question']}"
                self._json(200, {"answer": answer, "model": "fake-model"})
            elif self.path in ("/ext/ats", "/ext/cover", "/ext/tailor"):
                feature = {"/ext/ats": "ats", "/ext/cover": "cover"}.get(self.path)
                if feature and feature not in state.features:  # an older jobwatch has no such call
                    return self._json(404, {"error": "not found"})
                if not (state.know_every_page or "initech" in str(body.get("url"))):
                    return self._json(404, {"error": NOT_TRACKED})
                if self.path == "/ext/tailor":
                    state.tailors.append(body)
                    state.tailored = True
                    return self._json(200, {"version": "initech-platform-engineer", "new": True, "pages": 2, "ok": True,
                                            "problems": [], "pdf": "Jordan_Rivera_Initech.pdf", "matched_by": "link",
                                            "resume": {"name": "Jordan_Rivera_Initech.pdf", "type": "application/pdf",
                                                       "tailored": True}})
                if self.path == "/ext/ats":
                    state.ats_calls.append(body)
                    file = "Jordan_Rivera_Initech.pdf" if state.tailored else "resume.pdf"
                    return self._json(200, {**ATS, "tailored": state.tailored, "file": file, **state.ats_answer})
                state.covers.append(body)
                if state.cover_delay:
                    time.sleep(state.cover_delay)
                # the real endpoint (autofill.cover_letter) has the local model write it and keeps it as a version
                self._json(200, {"key": "ashby:initech/4f1c", "company": "Initech", "title": "Platform Engineer",
                                 "tone": body.get("tone") or "direct", "emphasis": body.get("emphasis") or "",
                                 "letter": COVER, "warnings": [], "model": "fake-local-model", "local": True,
                                 "drafted": True, "version": len(state.covers), "path": "", "changes": "",
                                 "matched_by": "link", **state.cover_answer})
            elif self.path == "/ext/reply":
                state.replies.append(body)
                if state.reply_delay:
                    time.sleep(state.reply_delay)
                if state.reply_status != 200:
                    self._json(state.reply_status, {"error": "the model is not answering"})
                    return
                # the real endpoint (jobwatch/reply.py) has the local model answer; a canned draft stands in for it
                self._json(200, {"reply": "Thanks Dana. Happy to talk Thursday afternoon. Which client is it?",
                                 "notes": ["Check the range against what you want before you reply."], "warnings": [],
                                 "company": "Northwind Talent", "model": "fake-local-model", "local": True,
                                 "drafted": True, **state.reply_answer})
            elif self.path == "/ext/posting":
                state.postings.append(body)
                self._json(200, {"key": "greenhouse:initech/4001", "company": body.get("company") or "Initech",
                                 "title": body.get("title") or "Platform Engineer", "added": False,
                                 "has_text": True, "where": "queue", "said": "Filled in from Greenhouse; scoring now",
                                 **({"closed": True} if body.get("closed") else {})})
            elif self.path == "/ext/import-list":
                state.imports.append(body)
                records = body.get("records", [])
                # made-up coverage: half were already tracked; the others are added the first time, and the same
                # list again finds them already added by that earlier import (as jobwatch's joblist.py says it)
                fresh = [r for r in records if int(r["id"]) % 2 == 0 and (r["source"], r["id"]) not in state.imported]
                added = fresh
                by_source: dict = {}
                for r in records:
                    c = by_source.setdefault(r["source"], {"seen": 0, "tracked": 0, "earlier": 0, "added": 0,
                                                           "unplaced": 0, "coverage": 0.0, "note": None})
                    c["seen"] += 1
                    kind = ("added" if r in fresh else "earlier" if int(r["id"]) % 2 == 0 else "tracked")
                    c[kind] += 1
                for c in by_source.values():
                    c["coverage"] = c["tracked"] / c["seen"]
                    if c["earlier"] * 2 >= c["seen"]:
                        c["note"] = ("Same list as before: nothing new" if not c["added"]
                                     else f"Mostly the same list as before: {c['added']} new")
                state.imported.update((r["source"], r["id"]) for r in fresh)
                self._json(200, {"by_source": by_source, "added": added, "unplaced": [],
                                 "link": "http://127.0.0.1:8765/#today"})
            elif self.path == "/ext/answers":
                # The answers as they stood at the person's Submit; the job is not marked applied by this call.
                state.answers.append(body)
                self._json(200, {"saved": True, "key": "ashby:initech/4f1c", "status": "queued",
                                 "count": len(body.get("answers", []))})
            elif self.path == "/ext/submitted":
                state.submitted.append(body)
                self._json(200, {"key": "ashby:initech/4f1c", "status": "applied", "added": False})
            else:
                self._json(404, {"error": "not found"})

    return Handler


@contextmanager
def fake_jobwatch() -> Iterator[tuple[str, State]]:
    """Serve the endpoints on a free local port. Yields (base url, state)."""
    state = State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    finally:
        httpd.shutdown()
