"""A tiny stand-in for jobwatch's /ext endpoints (see chrome-extension/API.md), for the end-to-end test.

Made-up data only. It remembers what the extension sent, so a test can look at it afterwards.
"""

from __future__ import annotations

import json
import threading
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


class State:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.answers: list[dict] = []  # /ext/answers: a snapshot per Submit press
        self.drafts: list[dict] = []
        self.postings: list[dict] = []
        self.requests: list[tuple[str, str]] = []
        self.token = TOKEN
        self.know_every_page = False  # live_check.py: every page is a known job, with a resume
        self.features = ["posting"]  # /ext/ping's; an older jobwatch has none
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
            if not self._allowed():
                return
            page = parse_qs(url.query).get("url", [""])[0]
            known = state.know_every_page or "initech" in page
            if url.path == "/ext/ping":
                self._json(200, {"ok": True, "version": JOBWATCH_VERSION, "features": state.features})
            elif url.path == "/ext/context":
                job = {"key": "ashby:initech/4f1c", "title": "Platform Engineer", "company": "Initech",
                       "status": "queued", "url": page} if known else None
                self._json(200, {"job": job, "applicant": APPLICANT, "answers": ANSWERS,
                                 "resume": {"name": "resume.pdf", "type": "application/pdf"} if known else None})
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
            elif self.path == "/ext/posting":
                state.postings.append(body)
                self._json(200, {"key": "greenhouse:initech/4001", "company": body.get("company") or "Initech",
                                 "title": body.get("title") or "Platform Engineer", "added": False,
                                 "has_text": True, "where": "queue", "said": "Filled in from Greenhouse; scoring now"})
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
