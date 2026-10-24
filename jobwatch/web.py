"""`jobwatch ui`: the same watchlist, digest and queue in a browser page, served from this computer only.

The server listens on 127.0.0.1. Every API call must carry the token embedded in the page it served, and a
Host header naming this machine, so other websites open in the browser can't read or change anything. The
exceptions are the calendar feed and the prep sheets folder, whose addresses hold a secret instead (a calendar
app, or a sheet opened in a tab of its own, can't send the token), and company logos, whose addresses hold the
token (an <img> can't send it as a header).
"""

from __future__ import annotations

import json
import re
import secrets
import socketserver
import sys
import threading
import time
import webbrowser
from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import yaml

from . import (
    __version__,
    advice,
    ai,
    chat,
    company,
    comps,
    config,
    contacts,
    dupes,
    ics,
    interviews,
    learn,
    levels,
    logos,
    mock,
    onboard,
    prep,
    quiet,
    referrals,
    report,
    sources,
    stories,
    storyfind,
    suggest,
)
from .config import ConfigError
from .filters import KINDS
from .package import Package
from .score import LOCAL, ScoringUnavailable, brief, prompt_info, resume_id, turn
from .store import COMP_FIELDS, ENDED, HEALTH_FIELDS, MANUAL, STAGES, STATUSES, Store
from .watch import (
    MANY_ROLES,
    Entry,
    build_digest,
    fetch_all,
    hidden,
    load_contacts,
    pace,
    plural,
    queue,
    save_job,
    scorable,
    score_entries,
    score_with_fallback,
    set_link,
    unscored,
    unscored_reason,
    unscored_reasons,
    watched_name,
)

MAX_UPLOAD = 20 * 1024 * 1024
IN_LINE = ("queued", "new", "shown")  # the statuses of the jobs the background scorer works through
UPLOADS = {"resume": (".pdf", ".docx", ".txt", ".md"), "connections": (".csv", ".zip")}


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class Scorer:
    """Scores queued and Today's jobs in the background, queued first, one at a time, so fit scores are there
    when you look. It runs when the page starts, after each check for new jobs and after a new resume, and
    saves each score as it lands. A chat reply or a Score fit click goes first (see score.ModelGate).

    It works in batches (scoring.batch jobs), then rests (scoring.rest minutes) so a long line of jobs doesn't
    keep the computer busy for hours, and the model leaves memory once it's idle (scoring.unload_after). With
    nothing left to score it stops: no thread, no timer, and the model isn't loaded until a job needs it."""

    def __init__(self, app: App):
        self.app = app
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._again = False  # asked to run again while running: new jobs may have come in
        self._rest: threading.Timer | None = None  # runs the next batch when the rest is over
        self._failed: dict[str, str] = {}  # job key -> why it failed to score (also kept in the store)
        self.done = 0
        self.left = 0
        self.current = ""
        self.current_key = ""
        self.error = ""
        self.stopped = ""  # why background scoring stopped short, until it runs again

    def reasons(self, cfg, store) -> dict[str, dict]:
        """Why each queued and Today's unscored job has no score yet, with what this scorer knows (see
        unscored_reasons)."""
        return unscored_reasons(cfg, store, self._failed, self.current_key, "" if self._thread else self.stopped)

    def status(self) -> dict:
        return {"running": self._thread is not None, "done": self.done, "left": self.left,
                "current": self.current, "error": self.error}

    def kick(self):
        with self._lock:
            if self._thread:
                self._again = True
                return
            self._stop_rest()  # something new came in: no need to wait out the rest
            self._thread = threading.Thread(target=self._run, name="jobwatch-scorer", daemon=True)
            self._thread.start()

    def wait(self, timeout: float | None = None):
        if t := self._thread:
            t.join(timeout)

    def _stop_rest(self):
        if self._rest:
            self._rest.cancel()
            self._rest = None

    def _run(self):
        while True:
            self.stopped = ""
            rest = 0  # seconds to rest before the rest of the line, when a batch ends with jobs left
            try:
                batch = self.app._cfg().score_batch
                steps = 0
                while self._step():
                    steps += 1
                    if batch and steps >= batch and self.left:
                        rest = self.app._cfg().score_rest * 60
                        break
            except Exception as e:  # never take the page down: say why scoring stopped
                self.error = f"{type(e).__name__}: {e}" if not isinstance(e, ScoringUnavailable) else str(e)
                self.stopped = self.error
                print(f"jobwatch: background scoring stopped: {self.error}", file=sys.stderr)
                self.app.log("score", "Background scoring stopped", ok=False, detail=[self.error], by="background",
                             notable=True)
            with self._lock:
                if not self._again:
                    left = self.left
                    self._thread, self.current, self.current_key, self.left = None, "", "", (left if rest else 0)
                    if rest:
                        self._rest = threading.Timer(rest, self.kick)
                        self._rest.daemon = True
                        self._rest.start()
                    return
                self._again = False

    def _step(self) -> bool:
        """Score the most relevant unscored job. False when there's nothing to do."""
        cfg = self.app._cfg()
        if not cfg.auto_score:
            return False
        store = Store(cfg.state)
        try:
            todo = unscored(cfg, store, self._failed)
            self.left = len(todo)
            if not todo:
                return False
            e = todo[0]
            self.current, self.current_key = f"{e.job.display_company}: {e.job.title}", e.job.key
            with turn(cfg.backend, background=True):
                scored, errors = score_entries(cfg, store, [e], progress=lambda m: None, background=True,
                                               by="background")
        finally:
            store.close()
        self.done += scored
        self.left -= 1
        self.current_key = ""
        if errors:
            self._failed[e.job.key] = next(iter(errors.values()))
            self.error = f"{self.current}: {self._failed[e.job.key]}"
        return True


def slot(times, now: datetime, after: bool = False) -> datetime:
    """The latest of these times of day (this computer's clock) at or before `now`, or with `after` the first
    one after it, as an aware datetime."""
    local = now.astimezone()
    days = (0, 1) if after else (0, -1)
    near = [datetime.combine(local.date() + timedelta(days=d), t, local.tzinfo) for d in days for t in times]
    return min(s for s in near if s > local) if after else max(s for s in near if s <= local)


class Refresher:
    """Checks the boards for new jobs in the background, on the watchlist's schedule (fetch_every: every 6 hours
    unless it says otherwise; off: only when asked), so Today doesn't go stale while nobody presses the button.
    When the page starts it checks if the last check (from the page, `jobwatch fetch` or MCP: see
    Store.last_fetch) is older than that, and then again each time that long has passed. It looks at the clock
    every `tick` seconds rather than sleeping the whole interval, so a computer that slept checks soon after it
    wakes, and a new fetch_every applies without a restart. A check where every board failed (no network) is
    tried again after RETRY.

    One check at a time: pressing the button while one runs (scheduled or not) waits for it and gets its counts,
    so no board is asked twice. Each check is the same as pressing the button, and the background scorer picks
    up its new jobs."""

    RETRY = timedelta(minutes=15)

    def __init__(self, app: App, tick: float = 60):
        self.app, self.tick = app, tick
        self._lock = threading.Lock()
        self._current: Future | None = None  # the check running now, which a second ask waits for
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.tried: datetime | None = None   # when the last scheduled check started
        self.error = ""                      # why the last scheduled check failed, until one works

    @property
    def running(self) -> bool:
        return self._current is not None

    def fetch(self, by: str = "page") -> dict:
        """Check every board now, or wait for the check already running; its counts, errors and summary. `by`:
        what started it, for the Activity log (page: the button; schedule)."""
        with self._lock:
            mine = self._current is None
            if mine:
                self._current = Future()
            current = self._current
        if not mine:
            return current.result()
        try:
            with self.app.lock:
                out = self.app._with_store(lambda cfg, store: self._fetch(cfg, store, by))
            current.set_result(out)
        except BaseException as e:
            current.set_exception(e)
            raise
        finally:
            with self._lock:
                self._current = None
        self.app.score_in_background()
        return out

    @staticmethod
    def _fetch(cfg, store, by: str = "") -> dict:
        r = fetch_all(cfg, store, by=by)
        return {"boards": r.boards, "jobs": r.jobs, "new": len(r.new), "errors": r.errors, "warnings": r.warnings,
                "summary": report.fetch_summary(r)}

    def due(self, now: datetime | None = None) -> bool:
        """Whether a scheduled check is due: fetch_every is on, there are boards, and the last check is older
        than fetch_every (or there's none), and no scheduled check started in the last RETRY. With times of day
        (fetch_at), it's due once the latest of them has passed with no check since: one missed while the
        computer slept is caught up once, and a check by hand after it counts."""
        now = now or datetime.now(timezone.utc)
        if not self.app.path.is_file():
            return False
        try:
            cfg = self.app._cfg()
        except ConfigError:  # the page shows what's wrong with the watchlist; check once it's fixed
            return False
        if (not (cfg.fetch_every or cfg.fetch_at) or not cfg.boards
                or (self.tried and now - self.tried < self.RETRY)):
            return False
        store = Store(cfg.state)
        try:
            last = store.last_fetch()
        finally:
            store.close()
        if cfg.fetch_at:
            return last is None or last["at"] < slot(cfg.fetch_at, now)
        return last is None or now - last["at"] >= cfg.fetch_every

    def status(self, cfg, store) -> dict:
        """For Today: when the boards were last checked (at, ISO), running, how often they're checked by
        themselves (every_hours; None: off, at set times, or no schedule running), the set times (times, "14:00";
        next, ISO), and the last check's new count, errors and warnings."""
        last = store.last_fetch()
        every = cfg.fetch_every if self._thread else None
        times = cfg.fetch_at if self._thread else ()
        return {"running": self.running, "at": last["at"].isoformat() if last else None,
                "every_hours": every.total_seconds() / 3600 if every else None,
                "times": [t.strftime("%H:%M") for t in times],
                "next": slot(times, datetime.now(timezone.utc), after=True).isoformat() if times else None,
                "new": last["new"] if last else 0, "errors": last["errors"] if last else {},
                "warnings": last["warnings"] if last else {}, "error": self.error}

    def start(self):
        with self._lock:
            if self._thread:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="jobwatch-refresher", daemon=True)
            self._thread.start()

    def stop(self, timeout: float | None = None):
        """Stop the schedule, waiting for a check that's running."""
        self._stop.set()
        if t := self._thread:
            t.join(timeout)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.due():
                    self.tried = datetime.now(timezone.utc)
                    out = self.fetch(by="schedule")
                    self.error = "" if out["boards"] or not out["errors"] else "every board failed"
            except Exception as e:  # never take the page down: say why, and try again later
                self.error = f"{type(e).__name__}: {e}"
                print(f"jobwatch: scheduled check for new jobs failed: {self.error}", file=sys.stderr)
            self._stop.wait(self.tick)


class PayLookup:
    """Looks up expected pay on Levels.fyi in the background for the jobs on the page (see levels.py), so the page
    never waits on it: up to levels.QUEUE pages a run, a couple of seconds apart. Only runs with pay.levels on."""

    def __init__(self, app: App):
        from .alerts import Robots
        self.app = app
        self.robots = Robots()  # Levels.fyi's robots.txt, read once
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._todo: list[str] = []

    @property
    def running(self) -> bool:
        return self._thread is not None

    def kick(self, keys: list[str]):
        with self._lock:
            self._todo = list(dict.fromkeys(self._todo + keys))
            if not self._thread:
                self._thread = threading.Thread(target=self._run, name="jobwatch-pay", daemon=True)
                self._thread.start()

    def wait(self, timeout: float | None = None):
        if t := self._thread:
            t.join(timeout)

    def _run(self):
        try:
            cfg = self.app._cfg()
            store = Store(cfg.state)
            looked, found = [], 0
            try:
                reader = levels.Reader(store, levels.QUEUE, robots=self.robots)
                while cfg.pay.levels and reader.budget > 0 and not reader.refused:
                    with self._lock:
                        if not self._todo:
                            break
                        key = self._todo.pop(0)
                    job = store.find(key)[0]
                    pay = levels.expected(cfg, store, job, reader=reader)
                    looked.append(f"{job.display_company}: {job.title}")
                    found += isinstance(pay, levels.Estimate)
                if looked:
                    store.log("pay", f"Looked up expected pay on Levels.fyi for {plural(len(looked), 'job')}: "
                              f"{found} found", detail=looked, by="background")
            finally:
                store.close()
        except Exception as e:  # never take the page down
            print(f"jobwatch: pay lookup stopped: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            with self._lock:
                self._thread, self._todo = None, []  # what's left is asked for on the page's next look


class LogoLookup:
    """Looks up company logos in the background (see logos.py) for the companies the page asked for and doesn't
    have yet, a second or so apart; the page shows them the next time it draws a company."""

    def __init__(self, app: App):
        self.app = app
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._todo: list[str] = []

    def kick(self, names: list[str]):
        with self._lock:
            self._todo = list(dict.fromkeys(self._todo + names))
            if not self._thread:
                self._thread = threading.Thread(target=self._run, name="jobwatch-logos", daemon=True)
                self._thread.start()

    def wait(self, timeout: float | None = None):
        if t := self._thread:
            t.join(timeout)

    def _run(self):
        from .alerts import Robots
        try:
            store = Store(self.app._cfg().state)
            try:
                jobs, robots = [j for j, _ in store.jobs(include_closed=True)], Robots()
                while True:
                    with self._lock:
                        names, self._todo = self._todo, []
                    if not names:
                        break
                    if found := logos.look_up(store, names, jobs, robots=robots):
                        store.log("logos", f"Found {plural(len(found), 'company logo')}", detail=found,
                                  by="background")
            finally:
                store.close()
        except Exception as e:  # never take the page down
            print(f"jobwatch: logo lookup stopped: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            with self._lock:
                self._thread, self._todo = None, []


class App:
    """The API behind the page. Each method takes the request's query or JSON body and returns JSON data.
    With `background`, fit scores are worked out behind the scenes (see Scorer), and so is expected pay (PayLookup).
    The boards are checked on a schedule once `refresher.start()` is called (serve does)."""

    def __init__(self, config_path: Path, background: bool = False):
        self.path = config_path
        self.lock = threading.Lock()  # one fetch or save at a time
        self.looking = threading.Lock()  # one look for suggested companies' boards at a time
        self.scorer = Scorer(self)
        self.pay = PayLookup(self)
        self.logos = LogoLookup(self)
        self.refresher = Refresher(self)
        self.background = background

    def score_in_background(self):
        if self.background:
            self.scorer.kick()

    # -- helpers

    def _cfg(self) -> config.Config:
        if not self.path.is_file():
            raise ApiError("No watchlist yet. Add companies in Settings first.", HTTPStatus.CONFLICT)
        cfg = config.load(self.path)
        LOCAL.idle_after = cfg.unload_after * 60 or None  # how long the local model stays loaded unused
        return cfg

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
        return {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "where": j.where,
                "locations": j.places, "pay": j.pay(), "age_days": j.age_days(), "department": j.department,
                "status": e.record.get("status"), "note": e.record.get("note"), "closed": e.record.get("closed"),
                "status_at": e.record.get("status_at"), "relevance": e.relevance, "keywords": e.keywords,
                "fit": e.fit, "contacts": e.contacts, "same_title": len(e.same_title), "keys": e.keys,
                "find_referral": contacts.linkedin_search(j.display_company), "salary_max": j.salary_max,
                "warnings": e.warnings, "link_note": j.link_note or None,
                "duplicate_of": e.duplicate.to_dict() if e.duplicate else None}

    def _pay(self, cfg, store, rows: list[tuple], most: int = 1000) -> dict[str, dict]:
        """{key: {"expected_pay": …}} for (job, result) pairs from what's kept, asking Levels.fyi for nothing here.
        A result of None is looked up now, from what's kept. The first `most` jobs still to be looked up are,
        in the background; the rest show nothing. Empty when pay.levels is off."""
        if not cfg.pay.levels:
            return {}
        out, waiting = {}, []
        for job, result in rows:
            result = result or levels.expected(cfg, store, job)
            if result == levels.PENDING:
                if len(waiting) >= most:
                    result = None
                else:
                    waiting.append(job.key)
            out[job.key] = {"expected_pay": levels.as_dict(result, job)}
        if waiting and self.background:
            self.pay.kick(waiting)
        return out

    @staticmethod
    def _advice(cfg, e, history, pay: dict[str, dict]) -> dict | None:
        """Queue or skip this job, and why (advice.py), with its expected pay from `pay` (see _pay) when known."""
        said = advice.advise(cfg, e, history, (pay.get(e.job.key) or {}).get("expected_pay"))
        return said.to_dict() if said else None

    # -- endpoints

    def get_settings(self, q) -> dict:
        raw = (yaml.safe_load(self.path.read_text()) or {}) if self.path.is_file() else {}
        companies = []
        for c in raw.get("companies") or []:
            # A source this version doesn't know shows as an error on that board, so it can be removed here.
            b = config._board(c, self.path, strict=False)
            companies.append({"source": b.source, "board": b.board, "name": b.name,
                              **({"careers": b.careers} if b.careers else {}),
                              **({"filters": b.filters} if b.filters else {}),
                              **({} if b.source in sources.SOURCES else {"error": config.UNKNOWN_SOURCE})})
        every = raw.get("fetch_every")
        scoring = raw.get("scoring") or {}
        talk = raw.get("chat") if isinstance(raw.get("chat"), dict) else {}
        return {"path": str(self.path), "exists": self.path.is_file(), "version": __version__,
                "companies": companies, "filters": raw.get("filters") or {}, "keywords": raw.get("keywords") or {},
                "resume": raw.get("resume"), "connections": raw.get("connections"),
                "scoring": scoring, "chat": talk, "learning": raw.get("learning") or {},
                "display": raw.get("display") or {}, "pace": raw.get("pace") or {}, "pay": raw.get("pay") or {},
                "alerts": raw.get("alerts") or {}, "goals": raw.get("goals") or {},
                "suggestions": raw.get("suggestions") or {}, "comps": raw.get("comps") or {},
                # where the history is kept: shown, changed only in the file (a new path starts an empty history)
                "state": raw.get("state"), "cache": raw.get("cache"),
                # what each setting left out is, for the page to show
                "defaults": config.defaults(),
                # the prompts fit scoring sends: shortlist-ai's, with the edited ones (scoring.prompts) in place
                "fit_prompts": prompt_info(scoring.get("prompts") if isinstance(scoring.get("prompts"), dict) else {}),
                # the chat's instructions: its own, or the edited one (chat.prompt)
                "chat_prompt": {"default": chat.SYSTEM, "text": talk.get("prompt") or chat.SYSTEM,
                                "edited": bool(talk.get("prompt")), "placeholders": list(config.CHAT_PLACEHOLDERS)},
                # as written (YAML reads a bare off as false); unset: the default
                "fetch_every": "off" if every is False else ", ".join(map(str, every)) if isinstance(every, list)
                else str(every) if every is not None else None}

    def post_settings(self, body) -> dict:
        settings = {k: v for k, v in body.items() if k in config.SETTINGS}
        if "companies" in settings:  # each board's name, careers link and filters are kept (see config._item)
            # filters are written in the file only: a board the page sends without them keeps the file's
            old = {(b.source, b.board): b.filters for c in config._companies(self.path)
                   for b in [config._board(c, self.path, strict=False)]}
            settings["companies"] = [config._item(config.Board(
                c["source"], c["board"], c.get("name") or "", (c.get("careers") or "").strip(),
                c["filters"] if isinstance(c.get("filters"), dict) else old.get((c["source"], c["board"]), {})))
                for c in settings["companies"]]
        talk = settings.get("chat")
        if isinstance(talk, dict) and str(talk.get("prompt") or "").strip() == chat.SYSTEM.strip():
            settings["chat"] = {k: v for k, v in talk.items() if k != "prompt"}  # only an edited one is kept
        with self.lock:
            cfg = config.save(self.path, settings)
        self.score_in_background()  # new filters, resume or scoring setting: maybe more to score
        return {"saved": str(cfg.path), "companies": len(cfg.boards)}

    def _keychain(self) -> str:
        raw = (yaml.safe_load(self.path.read_text()) or {}) if self.path.is_file() else {}
        scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
        return str(scoring.get("keychain") or "").strip()

    def get_ai(self, q) -> dict:
        """Where the AI can run on this computer: each choice, ready or what it still needs (see ai.py)."""
        return ai.status(self._keychain())

    def post_ai_test(self, body) -> dict:
        """One small call to the chosen backend, to show it answers (the local model loads first)."""
        return ai.test(str(body.get("backend") or ""), str(body.get("model") or "").strip(), self._keychain())

    def post_ai_key(self, body) -> dict:
        """Keeps an Anthropic API key in the macOS keychain and names that item in scoring.keychain: the key is
        never written to the watchlist."""
        try:
            item = ai.save_key(str(body.get("key") or ""), str(body.get("keychain") or "") or self._keychain())
        except ValueError as e:
            raise ApiError(str(e)) from None
        if item != self._keychain():
            raw = (yaml.safe_load(self.path.read_text()) or {}) if self.path.is_file() else {}
            scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
            with self.lock:
                config.save(self.path, {"scoring": {**scoring, "keychain": item}})
        self.score_in_background()
        return {"keychain": item}

    def get_onboarding(self, q) -> dict:
        """Whether first-run onboarding can offer "Suggest titles from my resume": ready, or why not, and where the
        resume would go. Looks at settings only; no model is called."""
        if not self.path.is_file():
            return {"ready": False, "why": "Add your resume first.", "where": None}
        try:
            cfg = config.load(self.path)
        except ConfigError as e:
            return {"ready": False, "why": str(e), "where": None}
        why = onboard.ready(cfg)
        return {"ready": not why, "why": why, "where": chat.where(cfg.chat.backend, cfg.chat.model)}

    def post_onboarding_titles(self, body) -> dict:
        """Job titles and keywords the chat's model proposes from the resume and goals saved so far: suggestions
        only, nothing is saved (see onboard.py)."""
        try:
            return onboard.suggest(self._cfg())
        except ValueError as e:
            raise ApiError(str(e)) from None

    def post_find(self, body) -> list[dict]:
        query = (body.get("company") or "").strip()
        if not query:
            raise ApiError("Type a company name or paste a job link.")
        return [{"source": s, "board": b, "name": next((j.company_name for j in jobs if j.company_name), ""),
                 "open_roles": sources.open_roles(jobs), "careers": sources.careers_url(s, b),
                 "sample_titles": list(dict.fromkeys(j.title for j in jobs))[:5]}
                for s, b, jobs in sources.probe(query)]

    def get_suggestions(self, q) -> dict:
        """Companies to watch (see suggest.py), the best `limit` (by default suggestions.limit, 5 at most: Today's
        panel). With lookup=1 the boards not looked for yet are looked for first: the page asks for that after
        showing what's known, so nothing waits on it."""
        look = (q.get("lookup") or [""])[0] == "1"

        def run(cfg, store):
            limit = int(q["limit"][0]) if q.get("limit") else min(5, cfg.suggest.limit)
            if not look:
                return {"companies": [s.to_dict() for s in suggest.suggestions(cfg, store, limit=limit)]}
            with self.looking:  # two pages open don't look for the same company's board twice
                return {"companies": [s.to_dict() for s in suggest.suggestions(cfg, store, limit=limit, look=True)]}
        return self._with_store(run)

    def post_suggestion_add(self, body) -> dict:
        """Watch a suggested company's board: added to the watchlist the way add_board does."""
        def run(cfg, store):
            with self.lock:
                cfg, s = suggest.accept(cfg, store, body.get("company") or "")
            return {"added": s.entry, "name": s.name, "companies": len(cfg.boards)}
        return self._with_store(run)

    def post_suggestion_dismiss(self, body) -> dict:
        def run(cfg, store):
            return {"dismissed": suggest.dismiss(store, body.get("company") or "").name}
        return self._with_store(run)

    def get_referrals(self, q) -> dict:
        """The people you know at companies with tracked jobs, and what you've said about each (see referrals.py)."""
        return self._with_store(lambda cfg, store: referrals.view(cfg, store))

    def get_comps(self, q) -> dict:
        """The Comps tab: open applications side by side (see comps.py). `stages` (comma-separated) picks which
        stages; the default is screening, interviewing and offer. Repeated `key` (jobs) and `company` (names, even
        ones with no job) parameters pick exactly what to compare instead."""
        stages = tuple(s for s in (q.get("stages") or [""])[0].split(",") if s) or comps.LIVE

        def run(cfg, store):
            try:
                return comps.view(cfg, store, stages, q.get("key"), q.get("company"))
            except KeyError as e:
                raise ApiError(e.args[0], HTTPStatus.NOT_FOUND) from None
            except ValueError as e:
                raise ApiError(str(e)) from None
        return self._with_store(run)

    def post_comp(self, body) -> dict:
        """What a recruiter said about pay for one job: any of base, bonus, equity, signon, asked, offered,
        note, role (product, customer or internal) and career_note; one left out stays, an empty one is cleared."""
        def run(cfg, store):
            try:
                store.set_comp(body.get("key") or "", **{f: body.get(f) for f in COMP_FIELDS})
            except ValueError as e:
                raise ApiError(str(e)) from None
            return {"key": store.find(body.get("key") or "")[0].key}
        return self._with_store(run)

    def post_health(self, body) -> dict:
        """What is known of one company's health (company: its name or a job's key): any of listing, stage, raised,
        revenue, headcount, layoffs, rating, risk, sources, as_of and kind (tech, consulting or
        enterprise); one left out stays, an empty one is cleared."""
        def run(cfg, store):
            name = comps.company_of(store, body.get("company") or "")
            try:
                store.set_health(name, **{f: body.get(f) for f in HEALTH_FIELDS})
            except ValueError as e:
                raise ApiError(str(e)) from None
            return {"company": name}
        return self._with_store(run)

    def post_referral_rate(self, body) -> dict:
        """Use or don't use a person (who: their name, link or key), or clear it; the note is kept with the verdict."""
        def run(cfg, store):
            try:
                p = referrals.rate(cfg, store, body.get("who") or "", body.get("verdict") or "", body.get("note") or "")
            except ValueError as e:
                raise ApiError(str(e)) from None
            return {"key": p["key"], "name": p["name"], "verdict": p["verdict"], "note": p["note"]}
        return self._with_store(run)

    def post_fetch(self, body) -> dict:
        """Check every board now; while a check is running already (the scheduled one), wait for it instead."""
        return self.refresher.fetch()

    def log(self, kind: str, text: str, ok: bool = True, detail: list[str] = (), by: str = "",
            notable: bool = False):
        """An Activity entry from the background work (see Store.log); never fails the work it's about."""
        try:
            self._with_store(lambda cfg, store: store.log(kind, text, ok, detail, by, notable))
        except Exception as e:
            print(f"jobwatch: activity not logged: {type(e).__name__}: {e}", file=sys.stderr)

    def get_activity(self, q) -> dict:
        """What jobwatch has been doing, newest first (kind: only one kind; since: only after that ISO time;
        notable: only what's worth a look, which the page tells you about), and what it's doing now."""
        def arg(name, default=""):
            return (q.get(name) or [default])[0]

        def run(cfg, store):
            return {"events": store.activity(int(arg("limit", "200")), arg("kind"), arg("since"),
                                             arg("notable") in ("1", "true")),
                    "now": {"boards": self.refresher.running, "score": self.scorer.status(),
                            "pay": self.pay.running}}
        return self._with_store(run)

    def get_checked(self, q) -> dict:
        """When the boards were last checked, and whether a check is running: see Refresher.status."""
        return self._with_store(self.refresher.status)

    def get_digest(self, q) -> dict:
        def run(cfg, store):
            d = build_digest(cfg, store, include_seen=True, score_top=0)
            why = self.scorer.reasons(cfg, store)
            pay = self._pay(cfg, store, [(e.job, None) for e in d.entries], most=cfg.pay.today)
            history = advice.History(store)
            worth = comps.worth(cfg, store, [(e.job, e.fit) for e in d.entries])
            out = {"jobs": [{**self._entry(e), "unscored": why.get(e.job.key), **pay.get(e.job.key, {}),
                             "worth": worth[e.job.key], "advice": self._advice(cfg, e, history, pay)}
                            for e in d.entries],
                   "rejected": d.rejected,
                   "can_score": bool(cfg.resume and cfg.resume.is_file()), "scoring": self.get_scoring({}),
                   "checked": self.refresher.status(cfg, store),
                   # Today leads with the top `picks` in the order picked (0: every match), and says the pace.
                   "picks": cfg.today, "pace": pace(cfg, store)}
            # "New" shows once: the next visit lists these as seen.
            store.set_status([k for e in d.entries if e.record.get("status") == "new" for k in e.keys], "shown")
            return out
        return self._with_store(run)

    def get_hidden(self, q) -> dict:
        """What the filters hide from Today: how many, by which filter (filters.KINDS), and with `kind`, those
        jobs, newest first (`limit` of them, 100 by default)."""
        kind = (q.get("kind") or [""])[0]
        if kind and kind not in KINDS:
            raise ApiError(f"kind must be one of {', '.join(KINDS)}")
        limit = int((q.get("limit") or ["100"])[0])
        return self._with_store(lambda cfg, store: hidden(cfg, store, kind, limit))

    def get_pace(self, q) -> dict:
        """Applications sent today against the watchlist's pace (see watch.pace); null when it's off."""
        return {"pace": self._with_store(pace)}

    def get_queue(self, q) -> list[dict]:
        def run(cfg, store):
            resume = bool(cfg.resume and cfg.resume.is_file())
            why = self.scorer.reasons(cfg, store)
            # A job added by hand can be scored once it has the posting's text.
            entries = queue(cfg, store)
            pay = self._pay(cfg, store, [(e.job, e.pay) for e in entries])
            history = advice.History(store)
            worth = comps.worth(cfg, store, [(e.job, e.fit) for e in entries])
            return [{**self._entry(e), "worth": worth[e.job.key],
                     "can_score": resume and scorable(e.job) and bool(e.job.description.strip()),
                     "unscored": None if e.fit else unscored_reason(cfg, store, e.job, why),
                     **pay.get(e.job.key, {}), "advice": self._advice(cfg, e, history, pay)} for e in entries]
        return self._with_store(run)

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
            rows = store.applications()
            found = quiet.find(rows, cfg.quiet, known=load_contacts(cfg))
            return {"stages": STAGES, "today": date.today().isoformat(), "applications": [
                {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
                 "manual": j.source == MANUAL, "due": report.due(rec), "quiet": found.get(j.key),
                 "package": Package(store.packages, j.key).summary(),
                 **{k: rec.get(k) for k in ("status", "status_at", "applied_at", "next_step", "follow_up", "note",
                                            "closed")}}
                for j, rec in quiet.order(rows, found)]}
        return self._with_store(run)

    def get_interviews(self, q) -> dict:
        """The Interviews tab: the interviews and calls coming up (see interviews.py)."""
        def run(cfg, store):
            folder = cfg.prep.sheets
            return {"today": date.today().isoformat(), "sheets_folder": str(folder) if folder else None,
                    "sheets_base": self._sheets_base(store),
                    "interviews": [interviews.to_dict(i, folder) for i in interviews.upcoming(store.applications())]}
        return self._with_store(run)

    @staticmethod
    def _sheets_base(store) -> str:
        """Where the prep sheets folder is served: a path with this install's secret in it, since a sheet opens in
        a tab of its own, which can't send the page's token (see prep_file)."""
        return f"/prep/{store.secret('prep')}/"

    def prep_file(self, secret: str, name: str) -> tuple[Path, str] | None:
        """(path, content type) of a file in the prep sheets folder when `secret` is this install's, else None."""
        def run(cfg, store):
            if not secrets.compare_digest(secret, store.secret("prep")):
                return None
            try:
                return interviews.sheet_file(cfg.prep.sheets, name)
            except FileNotFoundError:
                return None
        return self._with_store(run)

    def logo(self, name: str) -> tuple[bytes, str] | None:
        """A company's logo (see logos.py) as (image, content type); None when none is kept, and then, unless it
        was looked for lately, it's looked for in the background."""
        def run(cfg, store):
            kept = store.logo(logos.key(name))
            if kept and kept[2]:
                return kept[2], kept[1]
            if self.background and logos.due(kept):
                self.logos.kick([name])
            return None
        return self._with_store(run)

    def get_calendar(self, q) -> dict:
        """Where the follow-up and interview feed is served: a path with this install's secret in it, for a
        calendar app that can't send the page's token to subscribe to (see calendar_feed)."""
        return {"path": self._with_store(lambda cfg, store: f"/calendar/{store.secret('calendar')}.ics")}

    def calendar_feed(self, secret: str) -> bytes | None:
        """The feed (see ics.py) when `secret` is this install's, else None."""
        def run(cfg, store):
            if secrets.compare_digest(secret, store.secret("calendar")):
                return ics.calendar(store.applications(), remind=cfg.calendar.remind).encode()
        return self._with_store(run)

    def post_add(self, body) -> dict:
        def run(cfg, store):
            status = body.get("status") or "applied"
            if status not in ("queued", *STAGES):
                raise ApiError(f"status must be queued or one of {', '.join(STAGES)}")
            try:
                link = body.get("url") or ""
                job, read = save_job(store, link, body.get("company") or watched_name(cfg, link),
                                     body.get("title") or "", body.get("text") or "", status=status,
                                     note=body.get("note"), applied=body.get("applied_at") or None,
                                     boards=cfg.boards)
            except sources.SourceError as e:
                raise ApiError(f"couldn't read that posting: {e}") from None
            store.track(job.key, next_step=body.get("next_step"), follow_up=body.get("follow_up"))
            return {"key": job.key, "company": job.display_company, "title": job.title, "read": read}
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
            if body.get("add_note"):
                store.add_note(key, body["add_note"])
            return {"key": key}
        return self._with_store(run)

    def post_snooze(self, body) -> dict:
        """One open application's follow-up pushed `days` out (7 if left out); its stage stays, and the note says so."""
        days = body.get("days", 7)
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ApiError("days must be a whole number, 1 or more")

        def run(cfg, store):
            try:
                return {"follow_up": store.snooze(body.get("key") or "", days)}
            except ValueError as e:
                raise ApiError(str(e)) from None
        return self._with_store(run)

    def get_job(self, q) -> dict:
        key = (q.get("key") or [""])[0]

        def run(cfg, store):
            job, rec = store.find(key)
            known = load_contacts(cfg)
            resume = bool(cfg.resume and cfg.resume.is_file())
            fit = store.score(job.key, resume_id(cfg.resume, cfg.prompts)) if resume else None
            return {"key": job.key, "title": job.title, "company": job.display_company, "url": job.url,
                    "link_note": job.link_note or None,
                    "pay": job.pay(), "locations": job.places, "text": job.to_text(),
                    "contacts": known.at(job.display_company, job.company) if known else [],
                    "find_referral": contacts.linkedin_search(job.display_company),
                    "candidate_home": store.candidate_home(job),
                    "package": Package(store.packages, job.key).data(),
                    "skills": learn.job_gaps(cfg, store, job), "fit": fit,
                    "can_score": resume and scorable(job) and bool(job.description.strip()),
                    # Only queued and Today's jobs are in the scorer's line: working it out for any other (an
                    # application) reads every job through the filters and tells nothing more.
                    "unscored": None if fit else unscored_reason(
                        cfg, store, job, self.scorer.reasons(cfg, store) if rec.get("status") in IN_LINE else {}),
                    "manual": job.source == MANUAL,
                    "duplicate_of": (same := dupes.check(store, job.key)) and same.to_dict(),
                    "sheets": interviews.sheets(cfg.prep.sheets, job.display_company, job.company),
                    "sheets_base": self._sheets_base(store),
                    "meeting": None if rec.get("status") in ENDED else interviews.meeting_dict(rec.get("next_step")),
                    **self._pay(cfg, store, [(job, None)]).get(job.key, {}),
                    **{k: rec.get(k) for k in ("status", "status_at", "note", "closed", "first_seen", "next_step",
                                               "follow_up", "applied_at")}}
        return self._with_store(run)

    def get_companies(self, q) -> list[dict]:
        """The companies a name (or part of one, or a domain) matches among all tracked jobs, for the search box."""
        text = (q.get("q") or [""])[0]
        return self._with_store(lambda cfg, store: company.search(store, text))

    def get_company(self, q) -> dict:
        """One company's page: every tracked job there whatever its status (see company.view)."""
        text, every = (q.get("q") or [""])[0], (q.get("all") or [""])[0] == "1" or None

        def run(cfg, store):
            if not (v := company.view(cfg, store, text, every)):
                raise ApiError(f"no tracked job is at a company matching {text!r}", HTTPStatus.NOT_FOUND)
            return v
        return self._with_store(run)

    def post_posting(self, body) -> dict:
        """A job added by hand gets its posting: a link (read when it's to one job on a supported board) and/or
        the text, pasted. Says what happened, and whether the job now has text to score."""
        def run(cfg, store):
            key = store.find(body.get("key") or "")[0].key
            said = []
            try:
                if (text := (body.get("text") or "").strip()):
                    store.set_description(key, text)
                    said.append("text saved")
                if (url := (body.get("url") or "").strip()):
                    said.append(set_link(store, key, url))
            except ValueError as e:
                raise ApiError(str(e)) from None
            if not said:
                raise ApiError("send a link to the posting, or its text")
            job, _ = store.find(key)
            self.score_in_background()  # it may have text to score now
            return {"key": key, "said": "; ".join(said), "has_text": bool(job.description.strip())}
        return self._with_store(run)

    def post_pay(self, body) -> dict:
        """Expected pay for these jobs (`keys`) from what's kept, while the ones not known yet are looked up in
        the background (`running`). The page asks again until none is pending. Each job found has its advice
        again (`advice`), now that its expected pay may be known."""
        def run(cfg, store):
            if not cfg.pay.levels:
                return {"enabled": False, "running": False, "pay": {}}
            found = []
            for k in (body.get("keys") or [])[:cfg.pay.today]:
                try:
                    found.append(store.find(k))
                except KeyError:
                    continue
            pay = self._pay(cfg, store, [(j, None) for j, _ in found])
            rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
            known, index, history = load_contacts(cfg), dupes.Index(store), advice.History(store)
            said = {}
            for job, rec in found:
                if ((pay.get(job.key) or {}).get("expected_pay") or {}).get("pending"):
                    continue
                e = Entry(job, rec, 0, [], fit=brief(store.score(job.key, rid)) if rid else None,
                          contacts=known.at(job.display_company, job.company) if known else [],
                          duplicate=index.match(job, rec))
                said[job.key] = self._advice(cfg, e, history, pay)
            return {"enabled": True, "running": self.pay.running,
                    "pay": {k: v["expected_pay"] for k, v in pay.items()}, "advice": said}
        return self._with_store(run)

    def get_prep(self, q) -> dict:
        key = (q.get("key") or [""])[0]
        draft = (q.get("draft") or [""])[0] == "1"  # the model drafts questions from the stories (slow once)
        questions = (q.get("questions") or [""])[0] == "1"  # the model writes questions from the posting's asks

        def run(cfg, store):
            sheet = prep.build(cfg, store, key, draft=draft, questions=questions)
            return {**prep.to_dict(sheet), "markdown": prep.markdown(sheet), "html": prep.html(sheet)}
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
            # Queued all the same, with a word when it's (maybe) the same opening as one acted on.
            same = dupes.check(store, full[0]) if status == "queued" else None
            if status == "queued":
                self.score_in_background()  # queued jobs are scored first
            return {"keys": full, "status": status, "warning": same.line if same else None}
        return self._with_store(run)

    def post_score(self, body) -> dict:
        def run(cfg, store):
            job, _ = store.find(body.get("key") or "")
            if not scorable(job):
                raise ApiError(MANY_ROLES[1] + ".")
            if not (cfg.resume and cfg.resume.is_file()):
                raise ApiError("Add your resume in Settings to score fit.")
            rid = resume_id(cfg.resume, cfg.prompts)
            if cached := store.score(job.key, rid):
                return cached
            with turn(cfg.backend):  # ahead of background scoring
                results, errors = score_with_fallback(cfg, store, [job])
            if job.key not in results:
                raise ApiError(errors.get(job.key, "scoring failed"), HTTPStatus.BAD_GATEWAY)
            store.save_score(job.key, rid, results[job.key])
            return results[job.key]
        return self._with_store(run)

    def get_scoring(self, q) -> dict:
        """Background fit scoring: running, how many done and left, the job being scored, the last error."""
        return {**self.scorer.status(), "enabled": self.background}

    def get_chat(self, q) -> dict:
        c = self._cfg().chat
        return chat.where(c.backend, c.model)

    def chat(self, body) -> tuple[dict, object]:
        """({where replies come from}, the reply in pieces), about one job (`key`) or today's jobs and your
        applications. Everything that can fail does so here, before the reply starts streaming."""
        def run(cfg, store):
            messages = chat.clean(body.get("messages"), cfg.chat.max_turns)
            return chat.start(cfg, store, messages, body.get("key"))
        return self._with_store(run)

    def get_mock(self, q) -> dict:
        """A mock interview for one job (`key`): its questions, where feedback comes from, and the answers kept."""
        key = (q.get("key") or [""])[0]

        def run(cfg, store):
            session = mock.start(cfg, store, key)
            return {"key": session.key, "questions": session.questions, "where": session.where,
                    "saved": store.package(session.key).practised()}
        return self._with_store(run)

    def mock_feedback(self, body) -> tuple[dict, object]:
        """({where feedback comes from}, the feedback in pieces) on one answer (`answer`) to one question
        (`question`) for a job (`key`). The last piece reports {improved, note}: the tightened answer, vetted."""
        def run(cfg, store):
            session = mock.start(cfg, store, str(body.get("key") or ""))
            question = str(body.get("question") or "").strip()
            if not question:
                raise ApiError("send the question being answered")
            return session.where, mock.feedback(session, question, str(body.get("answer") or ""))
        return self._with_store(run)

    def post_mock_save(self, body) -> dict:
        """Keep a tightened answer on the job's prep sheet; returns every answer kept for it."""
        def run(cfg, store):
            key = store.find(str(body.get("key") or ""))[0].key
            mock.save(store, key, str(body.get("question") or ""), str(body.get("answer") or ""),
                      str(body.get("improved") or ""))
            return {"saved": store.package(key).practised()}
        return self._with_store(run)

    def get_storyfind(self, q) -> dict:
        """Find a story for one job (`key`): what a story would help with on its prep sheet, where the interview's
        replies come from, and the story file (with how many stories it has)."""
        key = (q.get("key") or [""])[0]

        def run(cfg, store):
            sheet = prep.build(cfg, store, key)
            c = cfg.chat
            return {"key": sheet.key, "title": sheet.title, "company": sheet.company, "gaps": storyfind.gaps(sheet),
                    "nothing": storyfind.NOTHING, "where": chat.where(c.backend, c.model),
                    "file": str(storyfind.story_file(cfg)), "stories": len(stories.load(cfg.stories))}
        return self._with_store(run)

    def storyfind_talk(self, body) -> tuple[dict, object]:
        """({where replies come from}, the reply in pieces) in an interview about one gap (`gap`) of a job (`key`),
        given the conversation so far (`messages`, none at the start). The last piece reports {story, note}: the
        story proposed, checked, or None and why."""
        def run(cfg, store):
            session = storyfind.start(cfg, store, str(body.get("key") or ""), str(body.get("gap") or ""))
            return session.where, storyfind.talk(session, body.get("messages") or [])
        return self._with_store(run)

    def post_story(self, body) -> dict:
        """Add a story you've checked (`story`: id, title, did, hard, result, optional skills and avoid) to your
        story file; returns it as saved, the file and how many stories it now has."""
        cfg = self._cfg()
        with self.lock:  # the watchlist may be written too, when it names no story file yet
            saved, path = storyfind.save(cfg, body.get("story"))
        return {"story": saved.to_dict(), "file": str(path), "stories": len(stories.load(path))}

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
        if kind == "resume":
            self.score_in_background()  # scores belong to a resume: a new one is scored afresh
        return {kind: target.name, **extra}


ROUTES = {
    ("GET", "/api/settings"): App.get_settings,
    ("POST", "/api/settings"): App.post_settings,
    ("GET", "/api/ai"): App.get_ai,
    ("POST", "/api/ai/test"): App.post_ai_test,
    ("POST", "/api/ai/key"): App.post_ai_key,
    ("GET", "/api/onboarding"): App.get_onboarding,
    ("POST", "/api/onboarding/titles"): App.post_onboarding_titles,
    ("POST", "/api/find"): App.post_find,
    ("GET", "/api/suggestions"): App.get_suggestions,
    ("POST", "/api/suggestions/add"): App.post_suggestion_add,
    ("POST", "/api/suggestions/dismiss"): App.post_suggestion_dismiss,
    ("GET", "/api/referrals"): App.get_referrals,
    ("POST", "/api/referrals/rate"): App.post_referral_rate,
    ("GET", "/api/comps"): App.get_comps,
    ("POST", "/api/comp"): App.post_comp,
    ("POST", "/api/health"): App.post_health,
    ("POST", "/api/fetch"): App.post_fetch,
    ("GET", "/api/checked"): App.get_checked,
    ("GET", "/api/activity"): App.get_activity,
    ("GET", "/api/digest"): App.get_digest,
    ("GET", "/api/hidden"): App.get_hidden,
    ("GET", "/api/queue"): App.get_queue,
    ("GET", "/api/pace"): App.get_pace,
    ("GET", "/api/jobs"): App.get_jobs,
    ("GET", "/api/job"): App.get_job,
    ("GET", "/api/companies"): App.get_companies,
    ("GET", "/api/company"): App.get_company,
    ("POST", "/api/mark"): App.post_mark,
    ("GET", "/api/applications"): App.get_applications,
    ("GET", "/api/calendar"): App.get_calendar,
    ("GET", "/api/interviews"): App.get_interviews,
    ("POST", "/api/add"): App.post_add,
    ("POST", "/api/track"): App.post_track,
    ("POST", "/api/snooze"): App.post_snooze,
    ("POST", "/api/score"): App.post_score,
    ("POST", "/api/posting"): App.post_posting,
    ("POST", "/api/pay"): App.post_pay,
    ("GET", "/api/scoring"): App.get_scoring,
    ("GET", "/api/chat"): App.get_chat,
    ("GET", "/api/skills"): App.get_skills,
    ("GET", "/api/prep"): App.get_prep,
    ("GET", "/api/mock"): App.get_mock,
    ("POST", "/api/mock/save"): App.post_mock_save,
    ("GET", "/api/storyfind"): App.get_storyfind,
    ("POST", "/api/stories/add"): App.post_story,
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

        def _send_logo(self, body: bytes, ctype: str):
            """A logo: cached a day by the browser, and sandboxed (an SVG opened on its own can't run scripts)."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=86400")
            self.send_header("Content-Security-Policy", "sandbox")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, ctype: str):
            """A file from disk, whole or the one byte range asked for (a video player seeks with ranges).
            Sandboxed: a page served this way can't run scripts or read this page's origin."""
            size, start, end = path.stat().st_size, 0, None
            if m := re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip()):
                if m.group(1):
                    start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
                elif m.group(2):  # the last n bytes
                    start, end = max(0, size - int(m.group(2))), size - 1
                if start >= size or (end is not None and end < start):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            end = min(size - 1, end if end is not None else size - 1)
            with path.open("rb") as f:
                f.seek(start)
                body = f.read(end - start + 1) if size else b""
            self.send_response(HTTPStatus.PARTIAL_CONTENT if m and (m.group(1) or m.group(2)) else HTTPStatus.OK)
            if m and (m.group(1) or m.group(2)):
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Security-Policy", "sandbox")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self, info: dict, pieces):
            """A reply as it's written: one JSON object per line ({"info"}, {"text"}..., then {"done", "stats"}
            or {"error"}), each sent as soon as it's ready. The connection closes at the end. stats: the model,
            seconds taken, seconds to the first words, and what the model reports (tokens, speed)."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True

            def line(obj):
                self.wfile.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
                self.wfile.flush()
            start, first, stats = time.monotonic(), None, {"model": info.get("model")}
            try:
                line({"info": info})
                for piece in pieces:
                    if isinstance(piece, dict):  # what it's waiting for, or what the model reports at the end
                        if "status" in piece:
                            line({"status": piece["status"]})
                        else:
                            stats.update(piece)
                        continue
                    first = first if first is not None else time.monotonic() - start
                    line({"text": piece})
                took = time.monotonic() - start
                stats.update(seconds=round(took, 1), first_seconds=round(first or 0, 1))
                if stats.get("output_tokens") and "tokens_per_sec" not in stats and took > (first or 0):
                    stats["tokens_per_sec"] = round(stats["output_tokens"] / (took - (first or 0)), 1)
                line({"done": True, "stats": stats})
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
            if method == "GET" and url.path.startswith("/calendar/") and url.path.endswith(".ics"):
                # A calendar app can't send the token header: the secret in the address stands in for it.
                feed = app.calendar_feed(url.path[len("/calendar/"):-len(".ics")])
                if feed is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return self._send(HTTPStatus.OK, feed, "text/calendar; charset=utf-8")
            if method == "GET" and url.path.startswith("/prep/"):
                # A prep sheet opened in its own tab, or the stylesheet or video beside it: the secret in the
                # address stands in for the token, which a tab can't send.
                secret, _, name = url.path[len("/prep/"):].partition("/")
                found = app.prep_file(secret, unquote(name))
                if found is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return self._send_file(*found)
            if method == "GET" and url.path.startswith("/logo/"):
                # A company's logo for an <img>, which can't send the token header: the token is in the address.
                tok, _, name = url.path[len("/logo/"):].partition("/")
                if not secrets.compare_digest(tok, token):
                    return self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token; reload the page"})
                found = app.logo(unquote(name))
                if found is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "no logo"})
                return self._send_logo(*found)
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
                elif method == "POST" and url.path == "/api/mock/feedback":
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ApiError("send a JSON object")
                    return self._stream(*app.mock_feedback(body))
                elif method == "POST" and url.path == "/api/storyfind":
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ApiError("send a JSON object")
                    return self._stream(*app.storyfind_talk(body))
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
    """Start the server (port 0 picks a free one), and the background work: fit scores, and checking the boards
    on the watchlist's schedule (see Refresher). Call serve_forever() on the result; its `app` is the App."""
    token = token or secrets.token_urlsafe(24)
    port_ref = [port]
    app = App(config_path, background=True)
    server = _Server(("127.0.0.1", port), make_handler(app, token, port_ref))
    server.app = app
    port_ref[0] = server.server_address[1]
    url = f"http://127.0.0.1:{port_ref[0]}/"
    print(f"jobwatch is running at {url}  (watchlist: {config_path}). Press Ctrl+C to stop.", file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    if config_path.is_file():
        app.score_in_background()  # catch up on jobs fetched while the page was down
    app.refresher.start()  # checks at once if the last check is older than fetch_every
    return server
