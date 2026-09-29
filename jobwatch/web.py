"""`jobwatch ui`: the same watchlist, digest and queue in a browser page, served from this computer only.

The server listens on 127.0.0.1. Every API call must carry the token embedded in the page it served, and a
Host header naming this machine, so other websites open in the browser can't read or change anything.
"""

from __future__ import annotations

import json
import secrets
import socketserver
import sys
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import yaml

from . import __version__, chat, config, contacts, learn, prep, report, sources
from .config import ConfigError
from .package import Package
from .score import ScoringUnavailable, resume_id, score_jobs
from .store import MANUAL, STAGES, STATUSES, Store
from .watch import build_digest, fetch_all, load_contacts, queue

MAX_UPLOAD = 20 * 1024 * 1024
UPLOADS = {"resume": (".pdf", ".docx", ".txt", ".md"), "connections": (".csv", ".zip")}


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class App:
    """The API behind the page. Each method takes the request's query or JSON body and returns JSON data."""

    def __init__(self, config_path: Path):
        self.path = config_path
        self.lock = threading.Lock()  # one fetch or save at a time

    # -- helpers

    def _cfg(self) -> config.Config:
        if not self.path.is_file():
            raise ApiError("No watchlist yet. Add companies in Settings first.", HTTPStatus.CONFLICT)
        return config.load(self.path)

    def _with_store(self, fn):
        cfg = self._cfg()
        store = Store(cfg.state)
        try:
            return fn(cfg, store)
        finally:
            store.close()

    @staticmethod
    def _entry(e) -> dict:
        j = e.job
        return {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url,
                "locations": j.locations, "pay": j.pay(), "age_days": j.age_days(), "department": j.department,
                "status": e.record.get("status"), "note": e.record.get("note"), "closed": e.record.get("closed"),
                "status_at": e.record.get("status_at"), "relevance": e.relevance, "keywords": e.keywords,
                "fit": e.fit, "contacts": e.contacts, "same_title": len(e.same_title), "keys": e.keys,
                "find_referral": contacts.linkedin_search(j.display_company), "salary_max": j.salary_max}

    # -- endpoints

    def get_settings(self, q) -> dict:
        raw = (yaml.safe_load(self.path.read_text()) or {}) if self.path.is_file() else {}
        companies = []
        for c in raw.get("companies") or []:
            b = config._board(c, self.path)
            companies.append({"source": b.source, "board": b.board, "name": b.name})
        return {"path": str(self.path), "exists": self.path.is_file(), "version": __version__,
                "companies": companies, "filters": raw.get("filters") or {}, "keywords": raw.get("keywords") or {},
                "resume": raw.get("resume"), "connections": raw.get("connections"),
                "scoring": raw.get("scoring") or {}, "learning": raw.get("learning") or {},
                "display": raw.get("display") or {}}

    def post_settings(self, body) -> dict:
        settings = {k: v for k, v in body.items() if k in config.SETTINGS}
        if "companies" in settings:
            settings["companies"] = [
                {"source": c["source"], "board": c["board"], **({"name": c["name"]} if c.get("name") else {})}
                for c in settings["companies"]]
        with self.lock:
            cfg = config.save(self.path, settings)
        return {"saved": str(cfg.path), "companies": len(cfg.boards)}

    def post_find(self, body) -> list[dict]:
        query = (body.get("company") or "").strip()
        if not query:
            raise ApiError("Type a company name or paste a job link.")
        return [{"source": s, "board": b, "name": next((j.company_name for j in jobs if j.company_name), ""),
                 "open_roles": sources.open_roles(jobs), "careers": sources.careers_url(s, b),
                 "sample_titles": list(dict.fromkeys(j.title for j in jobs))[:5]}
                for s, b, jobs in sources.probe(query)]

    def post_fetch(self, body) -> dict:
        def run(cfg, store):
            r = fetch_all(cfg, store)
            return {"boards": r.boards, "jobs": r.jobs, "new": len(r.new), "errors": r.errors,
                    "summary": report.fetch_summary(r)}
        with self.lock:
            return self._with_store(run)

    def get_digest(self, q) -> dict:
        def run(cfg, store):
            d = build_digest(cfg, store, include_seen=True, score_top=0)
            out = {"jobs": [self._entry(e) for e in d.entries], "rejected": d.rejected,
                   "can_score": bool(cfg.resume and cfg.resume.is_file())}
            # "New" shows once: the next visit lists these as seen.
            store.set_status([k for e in d.entries if e.record.get("status") == "new" for k in e.keys], "shown")
            return out
        return self._with_store(run)

    def get_queue(self, q) -> list[dict]:
        return self._with_store(lambda cfg, store: [self._entry(e) for e in queue(cfg, store)])

    def get_jobs(self, q) -> list[dict]:
        status = (q.get("status") or [None])[0]
        if status and status not in STATUSES:
            raise ApiError(f"status must be one of {', '.join(STATUSES)}")

        def run(cfg, store):
            return [{"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
                     **{k: rec.get(k) for k in ("status", "status_at", "note", "closed", "first_seen")}}
                    for j, rec in store.jobs((status,) if status else None, include_closed=True)]
        return self._with_store(run)

    def get_applications(self, q) -> dict:
        def run(cfg, store):
            return {"stages": STAGES, "today": date.today().isoformat(), "applications": [
                {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
                 "manual": j.source == MANUAL, "due": report.due(rec),
                 "package": Package(store.packages, j.key).summary(),
                 **{k: rec.get(k) for k in ("status", "status_at", "applied_at", "next_step", "follow_up", "note",
                                            "closed")}}
                for j, rec in store.applications()]}
        return self._with_store(run)

    def post_add(self, body) -> dict:
        def run(cfg, store):
            status = body.get("status") or "applied"
            if status not in STAGES:
                raise ApiError(f"status must be one of {', '.join(STAGES)}")
            job = store.add(body.get("company") or "", body.get("title") or "", url=body.get("url") or "",
                            status=status, applied=body.get("applied_at") or None, note=body.get("note"),
                            next_step=body.get("next_step"), follow_up=body.get("follow_up"))
            return {"key": job.key}
        return self._with_store(run)

    def post_track(self, body) -> dict:
        """One application: a new stage and/or its note, next step, follow-up day and day applied."""
        status = body.get("status")
        if status is not None and status not in STATUSES:
            raise ApiError(f"status must be one of {', '.join(STATUSES)}")

        def run(cfg, store):
            key = store.find(body.get("key") or "")[0].key
            if status:
                store.set_status([key], status)
            store.track(key, note=body.get("note"), next_step=body.get("next_step"),
                        follow_up=body.get("follow_up"), applied=body.get("applied_at"))
            return {"key": key}
        return self._with_store(run)

    def get_job(self, q) -> dict:
        key = (q.get("key") or [""])[0]

        def run(cfg, store):
            job, rec = store.find(key)
            known = load_contacts(cfg)
            return {"key": job.key, "title": job.title, "company": job.display_company, "url": job.url,
                    "pay": job.pay(), "locations": job.locations, "text": job.to_text(),
                    "contacts": known.at(job.display_company, job.company) if known else [],
                    "find_referral": contacts.linkedin_search(job.display_company),
                    "package": Package(store.packages, job.key).data(),
                    "skills": learn.job_gaps(cfg, store, job),
                    **{k: rec.get(k) for k in ("status", "status_at", "note", "closed", "first_seen")}}
        return self._with_store(run)

    def get_prep(self, q) -> dict:
        key = (q.get("key") or [""])[0]

        def run(cfg, store):
            sheet = prep.build(cfg, store, key)
            return {**prep.to_dict(sheet), "markdown": prep.markdown(sheet)}
        return self._with_store(run)

    def get_skills(self, q) -> dict:
        timeline = (q.get("timeline") or [None])[0]
        if timeline and timeline not in config.TIMELINES:
            raise ApiError(f"timeline must be one of {', '.join(config.TIMELINES)}")
        return self._with_store(lambda cfg, store: learn.to_dict(learn.gather(cfg, store, timeline)))

    # -- what was sent with an application

    def post_package(self, body) -> dict:
        """Save the form answers and/or the note; returns the package."""
        def run(cfg, store):
            pkg = store.package(body.get("key") or "")
            pkg.write(answers=body.get("answers"), note=body.get("note"))
            return pkg.data()
        return self._with_store(run)

    def post_package_remove(self, body) -> dict:
        def run(cfg, store):
            pkg = store.package(body.get("key") or "")
            pkg.remove(body.get("name") or "")
            return pkg.data()
        return self._with_store(run)

    def attach(self, key: str, name: str, kind: str, data: bytes) -> dict:
        def run(cfg, store):
            pkg = store.package(key)
            pkg.attach(name, data, kind or None)
            return pkg.data()
        return self._with_store(run)

    def package_file(self, key: str, name: str) -> tuple[bytes, str, str]:
        """(bytes, content type, file name). PDFs, images and text open in the browser; anything else downloads,
        and nothing is ever served as a page that could run in this one's place."""
        path = self._with_store(lambda cfg, store: store.package(key).path(name))
        ctype = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}.get(
            path.suffix.lower(), "application/octet-stream")
        return path.read_bytes(), ctype, path.name

    def post_mark(self, body) -> dict:
        status, keys = body.get("status"), body.get("keys") or []
        if status not in STATUSES or not keys:
            raise ApiError(f"send keys and a status ({', '.join(STATUSES)})")

        def run(cfg, store):
            full = [store.find(k)[0].key for k in keys]
            store.set_status(full, status, body.get("note"))
            return {"keys": full, "status": status}
        return self._with_store(run)

    def post_score(self, body) -> dict:
        def run(cfg, store):
            job, _ = store.find(body.get("key") or "")
            if not (cfg.resume and cfg.resume.is_file()):
                raise ApiError("Add your resume in Settings to score fit.")
            rid = resume_id(cfg.resume)
            if cached := store.score(job.key, rid):
                return cached
            results, errors = score_jobs([job], cfg.resume, cfg.backend, cfg.cache)
            if job.key not in results:
                raise ApiError(errors.get(job.key, "scoring failed"), HTTPStatus.BAD_GATEWAY)
            store.save_score(job.key, rid, results[job.key])
            return results[job.key]
        return self._with_store(run)

    def get_chat(self, q) -> dict:
        return chat.where(self._cfg().backend)

    def chat(self, body) -> tuple[dict, object]:
        """({where replies come from}, the reply in pieces), about one job (`key`) or today's jobs and your
        applications. Everything that can fail does so here, before the reply starts streaming."""
        messages = chat.clean(body.get("messages"))
        return self._with_store(lambda cfg, store: chat.start(cfg, store, messages, body.get("key")))

    def upload(self, kind: str, filename: str, data: bytes) -> dict:
        """Save an uploaded resume or LinkedIn export next to the watchlist and point the watchlist at it."""
        suffix = Path(filename).suffix.lower()
        if kind not in UPLOADS:
            raise ApiError(f"can't upload {kind!r}")
        if suffix not in UPLOADS[kind]:
            raise ApiError(f"{kind} must be one of: {', '.join(UPLOADS[kind])}")
        if not data:
            raise ApiError("the file is empty")
        extra = {}
        if kind == "resume":
            target = self.path.parent / ("resume" + suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        elif suffix == ".zip":
            # The full archive: keep only Connections.csv and the tie counts, never the messages.
            try:
                target, people, known = contacts.import_archive(data, self.path.parent)
            except ValueError as e:
                raise ApiError(str(e)) from None
            extra = {"people": people, "known": known}
        else:
            try:
                people = len(contacts.parse_connections(data.decode("utf-8-sig", errors="replace"), filename))
            except ValueError as e:
                raise ApiError(str(e)) from None
            target = self.path.parent / "Connections.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            (self.path.parent / contacts.TIES_FILE).unlink(missing_ok=True)  # stale counts from an older archive
            extra = {"people": people}
        with self.lock:
            config.save(self.path, {kind: target.name})
        return {kind: target.name, **extra}


ROUTES = {
    ("GET", "/api/settings"): App.get_settings,
    ("POST", "/api/settings"): App.post_settings,
    ("POST", "/api/find"): App.post_find,
    ("POST", "/api/fetch"): App.post_fetch,
    ("GET", "/api/digest"): App.get_digest,
    ("GET", "/api/queue"): App.get_queue,
    ("GET", "/api/jobs"): App.get_jobs,
    ("GET", "/api/job"): App.get_job,
    ("POST", "/api/mark"): App.post_mark,
    ("GET", "/api/applications"): App.get_applications,
    ("POST", "/api/add"): App.post_add,
    ("POST", "/api/track"): App.post_track,
    ("POST", "/api/score"): App.post_score,
    ("GET", "/api/chat"): App.get_chat,
    ("GET", "/api/skills"): App.get_skills,
    ("GET", "/api/prep"): App.get_prep,
    ("POST", "/api/package"): App.post_package,
    ("POST", "/api/package/remove"): App.post_package_remove,
}


def page(token: str) -> bytes:
    html = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    return html.replace("__JOBWATCH_TOKEN__", token).encode()


def make_handler(app: App, token: str, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"jobwatch/{__version__}"

        def log_message(self, fmt, *args):  # quiet: the terminal shows only errors
            pass

        def _send(self, status: int, body: bytes, ctype: str, filename: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if filename:  # a stored file: named for saving, and sandboxed so it can't script this page's origin
                inline = ctype.startswith(("application/pdf", "image/", "text/plain"))
                self.send_header("Content-Disposition", f"{'inline' if inline else 'attachment'}; "
                                 f"filename*=UTF-8''{quote(filename)}")
                self.send_header("Content-Security-Policy", "sandbox")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self, info: dict, pieces):
            """A reply as it's written: one JSON object per line ({"info"}, {"text"}..., then {"done"} or
            {"error"}), each sent as soon as it's ready. The connection closes at the end."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True

            def line(obj):
                self.wfile.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
                self.wfile.flush()
            try:
                line({"info": info})
                for text in pieces:
                    line({"text": text})
                line({"done": True})
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page stopped the reply or went away
            except Exception as e:
                print(f"jobwatch ui: chat: {type(e).__name__}: {e}", file=sys.stderr)
                try:
                    line({"error": f"{type(e).__name__}: {e}"})
                except OSError:
                    pass
            finally:
                if hasattr(pieces, "close"):
                    pieces.close()  # stops generating and frees the model for the next question

        def _json(self, status: int, data):
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            # Blocks DNS rebinding: a page on evil.example resolving to 127.0.0.1 still sends its own Host.
            return self.headers.get("Host", "") in {f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"}

        def _handle(self, method: str):
            if not self._host_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "unexpected Host"})
            url = urlparse(self.path)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(HTTPStatus.OK, page(token), "text/html; charset=utf-8")
            if not url.path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Jobwatch-Token", ""), token):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token; reload the page"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_UPLOAD:
                    raise ApiError("that file is too large (20 MB at most)", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                raw = self.rfile.read(length) if length else b""
                q = parse_qs(url.query)
                arg = lambda name: (q.get(name) or [""])[0]  # noqa: E731
                if method == "POST" and url.path == "/api/upload":
                    data = app.upload(arg("kind"), arg("name"), raw)
                elif method == "POST" and url.path == "/api/package/file":
                    data = app.attach(arg("key"), arg("name"), arg("kind"), raw)
                elif method == "GET" and url.path == "/api/package/file":
                    body, ctype, name = app.package_file(arg("key"), arg("name"))
                    return self._send(HTTPStatus.OK, body, ctype, name)
                elif method == "POST" and url.path == "/api/chat":
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ApiError("send a JSON object")
                    return self._stream(*app.chat(body))
                elif (route := ROUTES.get((method, url.path))) is None:
                    raise ApiError("not found", HTTPStatus.NOT_FOUND)
                elif method == "POST":
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ApiError("send a JSON object")
                    data = route(app, body)
                else:
                    data = route(app, q)
                self._json(HTTPStatus.OK, data)
            except ApiError as e:
                self._json(e.status, {"error": str(e)})
            except KeyError as e:
                self._json(HTTPStatus.NOT_FOUND, {"error": e.args[0]})
            except (ConfigError, ScoringUnavailable, chat.ChatUnavailable, sources.SourceError, ValueError) as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            except Exception as e:  # show it in the page rather than hang the request
                print(f"jobwatch ui: {type(e).__name__}: {e}", file=sys.stderr)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer looks up the host's full DNS name here, which can take seconds; it isn't needed.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def serve(config_path: Path, port: int = 8765, open_browser: bool = True, token: str | None = None
          ) -> ThreadingHTTPServer:
    """Start the server (port 0 picks a free one). Call serve_forever() on the result."""
    token = token or secrets.token_urlsafe(24)
    port_ref = [port]
    server = _Server(("127.0.0.1", port), make_handler(App(config_path), token, port_ref))
    port_ref[0] = server.server_address[1]
    url = f"http://127.0.0.1:{port_ref[0]}/"
    print(f"jobwatch is running at {url}  (watchlist: {config_path}). Press Ctrl+C to stop.", file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    return server
