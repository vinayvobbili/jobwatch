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

TOKEN = "test-token"
RESUME = b"%PDF-1.4\n% a made-up resume for Jordan Rivera\n%%EOF\n"

APPLICANT = {
    "first_name": "Jordan", "last_name": "Rivera", "preferred_name": "Jo", "email": "jordan@example.com",
    "phone": "+1 555 0100", "city": "Boulder", "state": "CO", "country": "United States", "postal_code": "80301",
    "linkedin": "https://www.linkedin.com/in/jordan-rivera-example", "github": "https://github.com/jordan-example",
    "website": "https://jordan.example.com", "work_authorized": "yes", "needs_sponsorship": "no", "relocate": "yes",
    "notice_period": "2 weeks", "salary": "180K-200K", "gender": "decline", "race": "decline", "hispanic": "decline",
    "veteran": "decline", "disability": "decline",
}

ANSWERS = [
    {"question": "Why do you want to work at Globex?", "answer": "I like small teams that own what they run.",
     "company": "Globex", "title": "SRE", "applied_at": "2026-09-14"},
    {"question": "Describe a time you handled a production incident.",
     "answer": "A bad deploy took checkout down; I rolled back in ten minutes and wrote the fix.",
     "company": "Umbrella", "title": "Platform Engineer", "applied_at": "2026-08-02"},
    {"question": "How much notice do you need before starting?", "answer": "Two weeks.",
     "company": "Globex", "title": "SRE", "applied_at": "2026-09-14"},
]


class State:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.drafts: list[dict] = []
        self.requests: list[tuple[str, str]] = []
        self.token = TOKEN
        self.know_every_page = False  # live_check.py: every page is a known job, with a resume


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
                self._json(200, {"ok": True, "version": "0.7.0"})
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
                self._json(200, {"answer": f"A drafted answer to: {body['question']}", "model": "fake-model"})
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
