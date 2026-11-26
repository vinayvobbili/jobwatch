"""What has been seen, shown, queued, applied to or skipped, how each application is going, and fit scores:
one SQLite file."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import actjobs, linkedin, rounds, scorestate
from .contacts import company_key
from .degrees import reconcile
from .models import Job
from .package import POSTING, Package
from .score import resume_family, unjudged
from .sources import SOURCES, candidate_home
from .text import names_one_role, parse_pay

# queued: to apply to next. After applying: applied, then screening, interviewing, offer, or it ends: rejected (they
# said no), withdrawn (you ended it) or closed (the company took the posting down: "Closed by company").
STAGES = ("applied", "screening", "interviewing", "offer", "rejected", "withdrawn", "closed")
ENDED = ("rejected", "withdrawn", "closed")
OPEN = ("applied", "screening", "interviewing")
IN_PROGRESS = tuple(s for s in STAGES if s not in ENDED)
# snoozed: wanted, but waiting for the application in progress at its company to end. It's queued again then, or
# after SNOOZE_DAYS (its follow_up day), since many companies never say no (wake_snoozed).
STATUSES = ("new", "shown", "queued", *STAGES, "skipped", "snoozed")
SNOOZE_DAYS = 21
VERDICTS = ("use", "skip")  # what can be said of a person to ask for a referral
# What a recruiter said about pay, then what the job is for your career: its role (ROLES) and a few words on why.
COMP_FIELDS = ("base", "bonus", "equity", "signon", "asked", "offered", "note", "role", "career_note",
               "glassdoor")  # glassdoor: a figure typed in by hand, never fetched
ROLES = ("product", "customer", "internal")  # builds the company's product; customer-facing engineering; internal tools
# What is known of a company's health, per company: public or private, stage and last round, total raised, revenue
# or growth, headcount trend, recent layoffs, employee rating, a risk note, source links, and the day it was true;
# and the kind of company it is (COMPANY_KINDS), for the career part of the Comps suggestion.
HEALTH_FIELDS = ("listing", "stage", "raised", "revenue", "headcount", "layoffs", "rating", "risk", "sources", "as_of",
                 "kind")
LISTINGS = ("public", "private")
# a technology company; consulting; a non-tech business whose IT builds for itself
COMPANY_KINDS = ("tech", "consulting", "enterprise")
MANUAL = "manual"  # the source of applications added by hand (found elsewhere, not on a watched board)
# A post listing several roles in a thread of many companies' posts (HN's Who is hiring) isn't fit-scored (see
# watch.scorable): a score saved for one before that is left out when scores are read (it stays in the file, unused).
# A post for one role is scored, so its score counts. one_role is names_one_role, added to each connection.
_SCORED = ("key NOT IN (SELECT key FROM jobs WHERE source IN ({}) "
           "AND NOT one_role(json_extract(data, '$.title')))").format(
    ", ".join(f"'{s.name}'" for s in SOURCES.values() if s.posts) or "''")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    data TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    closed TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    status_at TEXT,
    note TEXT,
    applied_at TEXT,
    next_step TEXT,
    follow_up TEXT,
    round TEXT,
    via TEXT,
    duplicate_of TEXT
);
CREATE INDEX IF NOT EXISTS jobs_board ON jobs (source, company);
CREATE TABLE IF NOT EXISTS scores (
    key TEXT NOT NULL,
    resume TEXT NOT NULL,
    result TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (key, resume)
);
CREATE TABLE IF NOT EXISTS score_failures (
    key TEXT NOT NULL,
    resume TEXT NOT NULL,
    model TEXT NOT NULL,
    error TEXT NOT NULL,
    failed_at TEXT NOT NULL,
    PRIMARY KEY (key, resume)
);
CREATE TABLE IF NOT EXISTS score_usage (
    day TEXT NOT NULL,
    backend TEXT NOT NULL,
    jobs INTEGER NOT NULL,
    PRIMARY KEY (day, backend)
);
CREATE TABLE IF NOT EXISTS company_usage (
    day TEXT NOT NULL,
    company TEXT NOT NULL,
    jobs INTEGER NOT NULL,
    PRIMARY KEY (day, company)
);
CREATE TABLE IF NOT EXISTS scorer_down (
    scorer TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    since TEXT NOT NULL,
    until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_cost (
    day TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT NOT NULL,
    batch INTEGER NOT NULL,
    jobs INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    PRIMARY KEY (day, backend, model, batch)
);
CREATE TABLE IF NOT EXISTS credit_spend (
    day TEXT NOT NULL,
    model TEXT NOT NULL,
    jobs INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    usd REAL NOT NULL,
    PRIMARY KEY (day, model)
);
CREATE TABLE IF NOT EXISTS pay_pages (
    url TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    gone INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fetches (
    at TEXT NOT NULL,
    boards INTEGER NOT NULL,
    jobs INTEGER NOT NULL,
    new INTEGER NOT NULL,
    errors TEXT NOT NULL,
    warnings TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hosted_pages (
    source TEXT NOT NULL,
    board TEXT NOT NULL,
    up INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (source, board)
);
CREATE TABLE IF NOT EXISTS unwatched (
    company TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entry TEXT,
    found_by TEXT,
    found_at TEXT,
    dismissed_at TEXT,
    looked_at TEXT
);
CREATE TABLE IF NOT EXISTS board_checks (
    entry TEXT PRIMARY KEY,
    read_at TEXT,
    seconds REAL NOT NULL DEFAULT 0,
    quiet INTEGER NOT NULL DEFAULT 0,
    told INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS unwatched_jobs (
    company TEXT NOT NULL,
    key TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (company, key)
);
CREATE TABLE IF NOT EXISTS backfill_tried (
    key TEXT PRIMARY KEY,
    tried_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS list_unplaced (
    key TEXT PRIMARY KEY,
    why TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posting_checked (
    key TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS closed_notices (
    key TEXT PRIMARY KEY,
    closed TEXT NOT NULL,
    found_at TEXT NOT NULL,
    notified_at TEXT,
    dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS closed_confirmed (
    key TEXT PRIMARY KEY,
    closed TEXT NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    key TEXT NOT NULL,
    inputs TEXT NOT NULL,
    reply TEXT NOT NULL,
    made_at TEXT NOT NULL,
    PRIMARY KEY (key, inputs)
);
CREATE TABLE IF NOT EXISTS morning_digests (
    day TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    items TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS logos (
    company TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    ctype TEXT NOT NULL,
    body BLOB NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS referral_feedback (
    person TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comps (
    key TEXT PRIMARY KEY,
    base TEXT,
    bonus TEXT,
    equity TEXT,
    signon TEXT,
    asked TEXT,
    offered TEXT,
    note TEXT,
    role TEXT,
    career_note TEXT,
    glassdoor TEXT,
    set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_health (
    company TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    listing TEXT,
    stage TEXT,
    raised TEXT,
    revenue TEXT,
    headcount TEXT,
    layoffs TEXT,
    rating TEXT,
    risk TEXT,
    sources TEXT,
    as_of TEXT,
    kind TEXT,
    set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL,
    by TEXT NOT NULL,
    notable INTEGER NOT NULL DEFAULT 0,
    job_keys TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS note_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    note TEXT NOT NULL,
    replaced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS note_history_key ON note_history (key);
"""
FETCHES_KEPT = 200  # the checks for new jobs remembered (when, and what they found)
ACTIVITY_KEPT = 1000  # the things done in the background remembered, of each kind (see Store.log)
BUSY = 30  # seconds to wait for another thread or process writing the state file, instead of "database is locked"


def slimmed(data: dict) -> dict:
    """A job's stored data without its heavy parts (the posting's text, the boards an HN post links to): what is
    left still names and links the job, and lets a fetch see it as already seen."""
    return {**data, "description": "", "boards": []}


def _letters(text: str | None) -> str:
    """A company's name with only its letters and digits, in lower case, to match it however it's punctuated.
    "&" and the word "and" are left out, so "Pied & Piper", "Pied and Piper" and "Pied Piper" read the same."""
    return re.sub(r"[\W_]+", "", re.sub(r"&|\band\b", " ", (text or "").lower()))


# A job's record carries closed_confirmed: 1 when its closed mark was seen again by a later check (the second look
# a closed posting needs before it counts as closed: see closed_notices), else 0: the mark alone is still 'checking'.
_ROW = ("SELECT *, EXISTS (SELECT 1 FROM closed_confirmed c WHERE c.key=jobs.key AND c.closed=jobs.closed) "
        "AS closed_confirmed FROM jobs")
_ROW_ID = _ROW.replace("SELECT *,", "SELECT rowid AS rid, *,", 1)  # the same, with when it was recorded (the order)

def closed_state(rec: dict) -> str | None:
    """What a job's record says about its posting: 'closed' (the mark was confirmed by a second look), 'checking'
    (marked once, not yet confirmed: shown amber, not as closed) or None (open)."""
    return None if not rec.get("closed") else "closed" if rec.get("closed_confirmed") else "checking"


# Columns added after the first release, and how to fill them in an older state file.
_ADDED = {"applied_at": "UPDATE jobs SET applied_at=substr(status_at, 1, 10) WHERE status='applied'",
          "next_step": None, "follow_up": None, "round": None, "via": None, "duplicate_of": None,  # round: rounds.py
          "slim": None}  # '1': the posting's text was dropped to save space (prune.py), and a fetch keeps it dropped


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")  # orders actions within a second


# A role that first shows up on a board already read before, dated more than this many days back, was reposted:
# some boards (Avature's) keep a reopened req's first posting date, which would read it as months old.
REPOST_DAYS = 14


def day(value: str | date | None, today: date | None = None) -> str | None:
    """A calendar day as YYYY-MM-DD, from "2026-10-05", "today", "tomorrow", "yesterday", "+7" (days from today)
    or "-7" (days ago). Empty or "none" means none."""
    if value is None or isinstance(value, date):
        return value.isoformat() if value else None
    v, today = value.strip().lower(), today or date.today()
    if not v or v == "none":
        return None
    if v in ("today", "tomorrow", "yesterday"):
        return (today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[v])).isoformat()
    if m := re.fullmatch(r"([+-])(\d+)d?", v):
        return (today + timedelta(days=int(m.group(2)) * (1 if m.group(1) == "+" else -1))).isoformat()
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{value!r} isn't a date: use YYYY-MM-DD, today, tomorrow, yesterday, +N or -N "
                         "days") from None


def day_start(d: date) -> str:
    """The start of a local calendar day as the store's UTC timestamps write it, to compare them with."""
    return datetime.combine(d, datetime.min.time()).astimezone().astimezone(UTC).isoformat(
        timespec="microseconds")


# A requisition id: R0123456, REQ-4711, JR12345, WD00104836, Job 20769 (at least four digits).
_REQ = re.compile(r"(?<![a-z0-9])((?:req|jr|wd|job|r)?[-_ #]?\d{4,}(?:-\d{1,2})?)(?![a-z0-9])", re.I)


def _same_req(req: str, posting_id: str) -> bool:
    """Does a requisition id from a title name this posting? Letters and separators aside the numbers must match;
    a posting's copy suffix (R0123456-1) still counts."""
    a, b = re.sub(r"\D", "", req.split("-")[0] if re.search(r"\d-\d{1,2}$", req) else req), posting_id
    b = re.sub(r"-\d{1,2}$", "", b)
    return bool(a) and a == re.sub(r"\D", "", b) and len(re.sub(r"[^A-Za-z]", "", b)) <= 3


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "job"


class Scores(Mapping):
    """Fit scores by job key, kept as the stored JSON text and read when a key is asked for: a list of a hundred
    thousand jobs asks for a few hundred, and parsed they'd take several times the text's size in memory.

    Each job's newest score, whatever resume made it. One made under an older resume than `resume` (and not kept as
    the baseline), or marked stale, reads as stale (see scorestate.flag); it is a score all the same."""

    def __init__(self, raw: dict[str, tuple[str, str]] | None = None, education: tuple = (), resume: str = "",
                 kept: dict[str, str] | None = None, marks: dict[str, tuple[str, str]] | None = None):
        self._raw = raw or {}  # key -> (result JSON, the resume id it was made under)
        self._education = education  # degrees.reconcile's: met degree requirements leave the gaps
        self._current = resume_family(resume) if resume else ""
        self._kept, self._marks = kept or {}, marks or {}

    def __getitem__(self, key: str) -> dict:
        text, rid = self._raw[key]
        return scorestate.flag(reconcile(json.loads(text), self._education), rid, self._current, self._kept,
                               self._marks.get(key))

    def __iter__(self):
        return iter(self._raw)

    def __len__(self) -> int:
        return len(self._raw)


class KnownJobs(Mapping):
    """A board's stored jobs by key, each read from the database when asked for. A board's reads run in worker
    threads, so each thread reads through a connection of its own."""

    def __init__(self, path: Path, keys: set[str], board: tuple[str, str] = ("", "")):
        self._path, self._keys, self._board, self._local = path, keys, board, threading.local()

    def values(self):
        """Each job, one at a time, in one query (not a read per key)."""
        for row in self._db().execute("SELECT data FROM jobs WHERE source=? AND company=?", self._board):
            yield Job.from_dict(json.loads(row[0]))

    def _db(self) -> sqlite3.Connection:
        if (db := getattr(self._local, "db", None)) is None:
            db = self._local.db = sqlite3.connect(self._path, timeout=BUSY)
        return db

    def __getitem__(self, key: str) -> Job:
        if key not in self._keys:
            raise KeyError(key)
        row = self._db().execute("SELECT data FROM jobs WHERE key=?", (key,)).fetchone()
        if not row:
            raise KeyError(key)
        return Job.from_dict(json.loads(row[0]))

    def __contains__(self, key) -> bool:
        return key in self._keys

    def __iter__(self):
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class Store:
    def __init__(self, path: Path | str, read_only: bool = False, education: tuple = ()):
        """read_only opens an existing state file without changing it, not even to add a newer version's columns
        (`jobwatch dupes` reads with it). education: the profile's degrees (Config.education): a fit score read
        back has the degree requirements they meet taken out of its gaps (degrees.reconcile)."""
        path = Path(path).expanduser()
        self.path = path
        self.education = education
        self.packages = path.parent / "packages"  # what was sent with each application (see package.py)
        self._titles: dict[str, str | None] = {}  # titles() remembers what it resolved, until a job is written
        if read_only:
            self.db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            self.db.row_factory = sqlite3.Row
            self.db.create_function("one_role", 1, names_one_role, deterministic=True)
            if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='closed_confirmed'").fetchone():
                # an older file has no confirmations: an empty temp table (the file itself isn't touched) makes
                # every closed mark 'checking' for the _ROW queries
                self.db.execute("CREATE TEMP TABLE closed_confirmed (key TEXT, closed TEXT, confirmed_at TEXT)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=BUSY)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("one_role", 1, names_one_role, deterministic=True)
        # Write-ahead logging: a long read (the page drawing Today) and a write (a score, a logo) don't wait on
        # each other. Kept in the file, so this only changes it the first time.
        try:
            if self.db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:  # another connection is switching it, or using it: a later open will
            pass
        older = not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='unwatched_jobs'").fetchone()
        self.db.executescript(_SCHEMA + scorestate.SCHEMA)
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        with self.db:
            for column, backfill in _ADDED.items():
                if column not in have:
                    try:
                        self.db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
                    except sqlite3.OperationalError as e:  # another connection (a page's thread) added it just now
                        if "duplicate column" not in str(e):
                            raise
                        continue
                    if backfill:
                        self.db.execute(backfill)
            if "gone" not in {r["name"] for r in self.db.execute("PRAGMA table_info(pay_pages)")}:
                self.db.execute("ALTER TABLE pay_pages ADD COLUMN gone INTEGER NOT NULL DEFAULT 0")
            if "notable" not in {r["name"] for r in self.db.execute("PRAGMA table_info(activity)")}:
                try:
                    self.db.execute("ALTER TABLE activity ADD COLUMN notable INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError as e:  # another connection added it just now
                    if "duplicate column" not in str(e):
                        raise
            activity_keyless = "job_keys" not in {r["name"] for r in self.db.execute("PRAGMA table_info(activity)")}
            if activity_keyless:
                try:
                    self.db.execute("ALTER TABLE activity ADD COLUMN job_keys TEXT NOT NULL DEFAULT '[]'")
                except sqlite3.OperationalError as e:  # another connection added it just now
                    activity_keyless = False
                    if "duplicate column" not in str(e):
                        raise
            for table, column in (("comps", "role"), ("comps", "career_note"), ("comps", "glassdoor"),
                                  ("company_health", "kind"), ("unwatched", "looked_at")):
                if column not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    try:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                    except sqlite3.OperationalError as e:  # another connection added it just now
                        if "duplicate column" not in str(e):
                            raise
            if older:  # a state file from before suggestions: what alerts and `add` brought in so far counts
                self._backfill_unwatched()
        if activity_keyless:  # rows from before they kept their jobs: the ones they name, when one job matches
            try:
                actjobs.backfill(self.db)
            except Exception as e:  # a link missing from an old row is no reason to stop
                print(f"jobwatch: activity rows not linked to their jobs: {type(e).__name__}: {e}", file=sys.stderr)

        if self.db.execute("PRAGMA user_version").fetchone()[0] < 1:  # jobs from before pay kept its rate
            try:
                self.backfill_pay_per()
                self.db.execute("PRAGMA user_version=1")
            except Exception as e:  # a rate left unlabelled on an old job is no reason to stop
                print(f"jobwatch: hourly pay not labelled on older jobs: {type(e).__name__}: {e}", file=sys.stderr)

    def backfill_pay_per(self) -> int:
        """Mark the jobs whose posted pay was an hourly wage worked out as a year's, from before a job kept the rate
        (so the page said "$83K–$166K" for "$40 - $80 per hour"): the ones whose text still gives that wage.
        Returns how many were marked. A board's job gets its rate again from the board at its next fetch."""
        n = 0
        rows = self.db.execute("SELECT key, data FROM jobs WHERE data LIKE '%\"salary_min\": %' "
                               "AND data NOT LIKE '%\"salary_min\": null%'").fetchall()
        with self.db:
            for r in rows:
                job = Job.from_dict(json.loads(r["data"]))
                found = parse_pay(job.description) if job.description and not job.pay_per else None
                if found and found[2] and found[:2] == (job.salary_min, job.salary_max or job.salary_min):
                    job.pay_per = found[2]
                    self.db.execute("UPDATE jobs SET data=? WHERE key=?", (json.dumps(job.to_dict()), job.key))
                    n += 1
        return n

    def close(self):
        self.db.close()

    def stamp(self) -> tuple:
        """What changes whenever anything is written to the state file, by this process or another one, and
        nothing else: a cheap stamp (three stat calls and a 24-byte read) to key remembered work on, so it's
        used again until a write. It is the file's and the write-ahead log's size and time, and the commit
        counter in the log's index (SQLite bumps that on every commit, so two writes in one clock tick still
        differ). An empty log has no time: SQLite makes a new one each time the first connection opens, which
        isn't a write."""
        out = []
        for suffix in ("", "-wal"):
            try:
                st = Path(f"{self.path}{suffix}").stat()
                out += [st.st_mtime_ns if st.st_size or not suffix else None, st.st_size]
            except OSError:
                out += [None, 0]
        try:
            with open(f"{self.path}-shm", "rb") as f:
                out.append(f.read(24))
        except OSError:
            out.append(None)
        return tuple(out)

    def newest_first(self, statuses: tuple[str, ...]) -> list[str]:
        """The keys of the jobs with these statuses (closed ones too), in the order jobs() lists them: newest first
        seen, a tie by when it was recorded. Only keys are read, not the postings."""
        return [r[0] for r in self.db.execute(
            f"SELECT key FROM jobs WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY first_seen DESC",
            statuses)]

    def board_rows(self, boards, statuses: tuple[str, ...] | None = None, closed_only: bool = False,
                   title_ok: Callable[[str, str, str], bool] | None = None) -> list[tuple[Job, dict]]:
        """(job, record) for every job, closed ones too, on any of these (source, company) boards, in the order
        jobs() lists them (newest first seen, a tie by when it was recorded): each board is read by its index.
        statuses: only jobs with one of these; closed_only: only those marked closed; title_ok(source, company,
        title): only jobs it says yes to, decided in the query from the title alone, so a board's thousands of
        postings aren't each read in full to be turned away."""
        where, args = "", []
        if statuses:
            where += f" AND status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if closed_only:
            where += " AND closed IS NOT NULL"
        if title_ok:
            self.db.create_function("title_ok", 3, lambda *a: int(bool(title_ok(*a))))
            where += " AND title_ok(source, company, json_extract(data, '$.title'))"
        found = []
        for source, company in boards:
            for r in self.db.execute(f"{_ROW_ID} WHERE source=? AND company=?{where}", (source, company, *args)):
                found.append((r["first_seen"], r["rid"], Job.from_dict(json.loads(r["data"])),
                              {k: r[k] for k in r.keys() if k not in ("data", "rid")}))
        found.sort(key=lambda f: f[1])
        found.sort(key=lambda f: f[0], reverse=True)  # stable: a tie stays in the order recorded
        return [(job, rec) for _, _, job, rec in found]

    def rows(self, keys) -> dict[str, tuple[Job, dict]]:
        """{key: (job, record)} for the jobs with exactly these keys (those that exist), in the order the keys
        are given, a chunk of keys per query."""
        keys, got = list(dict.fromkeys(keys)), {}
        for i in range(0, len(keys), 500):  # SQLite's limit on query variables
            chunk = keys[i:i + 500]
            for r in self.db.execute(f"{_ROW} WHERE key IN ({','.join('?' * len(chunk))})", chunk):
                got[r["key"]] = Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}
        return {k: got[k] for k in keys if k in got}

    def sync(self, source: str, company: str, jobs: list[Job], close_missing: bool = True,
             spare: tuple[str, ...] = ()) -> list[str]:
        """Record one board's current roles; returns the keys seen for the first time.

        Roles that have disappeared from the board are marked closed (and reopened if they come back), unless
        `close_missing` is off: a board read only partway (sources.Partial) says nothing about the rest, and a
        board that listed no roles at all closes none. Roles with a status in `spare` are never closed by a
        listing: a searched board (Workday, a careers site's sitemap) lists only the roles matching the watchlist's
        words, up to a cap, so a role you follow that isn't in it may simply not match; the daily check of the
        posting itself decides (watch.check_postings)."""
        now, new = _now(), []
        self._titles.clear()
        with self.db:
            rows = self.db.execute("SELECT key, slim, status FROM jobs WHERE source=? AND company=?",
                                   (source, company)).fetchall()
            known = {r["key"] for r in rows}
            slim = {r["key"] for r in rows if r["slim"] and r["status"] == "new"}  # not acted on: text stays dropped
            for job in jobs:
                if known and job.key not in known and job.posted and \
                        (datetime.now(UTC) - job.posted).days > REPOST_DAYS:
                    job.posted = datetime.now(UTC)  # reposted: new to the board today, not months old
                data = json.dumps(slimmed(job.to_dict()) if job.key in slim else job.to_dict())
                try:
                    # The key is unique across the whole table, so a role already recorded is updated whoever
                    # recorded it: a key listed twice by one board, or one kept under another source or company
                    # (an alert's copy), is an update, never a second insert that fails the board's whole sync.
                    if job.key not in known and self.db.execute(
                            "INSERT OR IGNORE INTO jobs (key, source, company, data, first_seen, last_seen) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (job.key, source, company, data, now, now)).rowcount:
                        new.append(job.key)
                    else:
                        self.db.execute("UPDATE jobs SET data=?, last_seen=?, closed=NULL, slim=? WHERE key=?",
                                        (data, now, "1" if job.key in slim else None, job.key))
                    known.add(job.key)
                except sqlite3.Error as e:  # one bad role never fails the board's other roles, or the check
                    print(f"jobwatch: skipped {job.key}: {type(e).__name__}: {e}", file=sys.stderr)
            # a board that lists nothing at all is down or changed, not empty: it closes nothing (a posting that
            # really went is found by the daily check of the ones you follow)
            spared = {r["key"] for r in rows if r["status"] in spare}
            gone = (known - {j.key for j in jobs} - spared) if close_missing and jobs else set()
            self.db.executemany("UPDATE jobs SET closed=? WHERE key=? AND closed IS NULL", [(now, k) for k in gone])
        return new

    def keep(self, job: Job) -> bool:
        """Record one job read from its link, leaving the rest of its board alone (it may not be watched).
        Returns whether it's new."""
        now = _now()
        self._titles.clear()
        with self.db:
            new = self.db.execute("INSERT OR IGNORE INTO jobs (key, source, company, data, first_seen, last_seen) "
                                  "VALUES (?, ?, ?, ?, ?, ?)", (job.key, job.source, job.company,
                                                                json.dumps(job.to_dict()), now, now)).rowcount
            if not new:
                self.db.execute("UPDATE jobs SET data=?, last_seen=?, closed=NULL, slim=NULL WHERE key=?",
                                (json.dumps(job.to_dict()), now, job.key))
        return bool(new)

    def has(self, key: str) -> bool:
        """Whether a job with exactly this key is recorded."""
        return self.db.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone() is not None

    def first_seen(self, key: str) -> str | None:
        """When the job with exactly this key was first recorded (ISO, UTC), or None when it isn't."""
        row = self.db.execute("SELECT first_seen FROM jobs WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_via(self, key: str, via: str):
        """Record where a job was first found when it didn't come from a watched board ("linkedin-alert": a
        LinkedIn job-alert email). The first one recorded stays."""
        with self.db:
            self.db.execute("UPDATE jobs SET via=COALESCE(via, ?) WHERE key=?", (via or None, key))

    def textless_alert_jobs(self) -> list[tuple[Job, dict]]:
        """(job, record) pairs of the open jobs added from a job-alert email (via ends in "-alert") or a list of
        jobs LinkedIn showed (via ends in "-list") that are still kept as emailed or listed, with no posting text.
        Oldest tried first (never tried first); the record has tried_at, when the backfill (alerts.backfill) last
        looked for the job on its company's board."""
        rows = self.db.execute("SELECT j.*, t.tried_at FROM jobs j LEFT JOIN backfill_tried t ON t.key=j.key "
                               "WHERE j.source=? AND j.closed IS NULL AND (j.via LIKE '%-alert' OR j.via LIKE "
                               "'%-list') "
                               "ORDER BY t.tried_at IS NOT NULL, t.tried_at, j.first_seen DESC", (MANUAL,))
        out = []
        for r in rows:
            job = Job.from_dict(json.loads(r["data"]))
            if not job.description.strip():
                out.append((job, {k: r[k] for k in r.keys() if k != "data"}))
        return out

    def set_unplaced(self, key: str, why: str):
        """Note why an import-list job was tracked from the list's text alone (no board found under the company's
        name, or not on its board), as of the latest import."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO list_unplaced (key, why, at) VALUES (?, ?, ?)",
                            (key, why, _now()))

    def unplaced_list_jobs(self, since: str | None = None) -> list[tuple[Job, dict]]:
        """(job, record) pairs of the jobs a list import (via ends in "-list") tracked from the list's text alone:
        still kept as listed, with no posting text, closed ones too; newest first. since: only those first seen on
        or after that local day (YYYY-MM-DD). The record has why, when set_unplaced recorded one."""
        sql = ("SELECT j.*, u.why FROM jobs j LEFT JOIN list_unplaced u ON u.key=j.key WHERE j.source=? "
               "AND j.via LIKE '%-list'")
        args: list = [MANUAL]
        if since:
            sql += " AND j.first_seen >= ?"
            args.append(day_start(date.fromisoformat(since)))
        out = []
        for r in self.db.execute(sql + " ORDER BY j.first_seen DESC", args):
            job = Job.from_dict(json.loads(r["data"]))
            if not job.description.strip():
                out.append((job, {k: r[k] for k in r.keys() if k != "data"}))
        return out

    def set_backfill_tried(self, key: str):
        """Note that the backfill looked for this job on its company's board now."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO backfill_tried (key, tried_at) VALUES (?, ?)", (key, _now()))

    def posting_checked(self) -> dict[str, str]:
        """When each job's posting was last checked (watch.check_daily), by key."""
        return {r["key"]: r["checked_at"] for r in self.db.execute("SELECT key, checked_at FROM posting_checked")}

    def set_posting_checked(self, key: str):
        """Note that this job's posting was checked now."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO posting_checked (key, checked_at) VALUES (?, ?)", (key, _now()))

    # Closed-posting notices (closed_notice.py): a job you care about whose posting came down, kept until you
    # dismiss it, and told once in the daily popup. `closed` is the job's own closed stamp, so a posting that
    # reopens and closes again is a new notice.

    def record_closed_notices(self, statuses: tuple[str, ...], since: str) -> list[str]:
        """Note the jobs with one of these statuses whose posting closed at or after `since` (an ISO stamp) and
        have no notice yet; drop the notices of jobs that reopened or left these statuses. Returns the new keys."""
        marks = ",".join("?" * len(statuses))
        new = []
        with self.db:
            self.db.execute("DELETE FROM closed_notices WHERE key NOT IN (SELECT key FROM jobs WHERE closed IS NOT "
                            f"NULL AND status IN ({marks}))", statuses)
            have = {r["key"]: r["closed"] for r in self.db.execute("SELECT key, closed FROM closed_notices")}
            for r in self.db.execute(f"SELECT key, closed FROM jobs WHERE closed >= ? AND status IN ({marks})",
                                     (since, *statuses)).fetchall():
                if have.get(r["key"]) == r["closed"]:
                    continue
                self.db.execute("INSERT OR REPLACE INTO closed_notices (key, closed, found_at) VALUES (?, ?, ?)",
                                (r["key"], r["closed"], _now()))
                new.append(r["key"])
        return new

    def confirm_closed(self, keys: list[str]):
        """A second look found these postings still closed: the mark they have now counts as confirmed (see
        closed_notices). A job that reopens and closes again has a new mark, and needs confirming again."""
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO closed_confirmed (key, closed, confirmed_at) "
                "SELECT key, closed, ? FROM jobs WHERE key=? AND closed IS NOT NULL", [(_now(), k) for k in keys])

    def closed_notices(self, untold: bool = False, pending: bool = False) -> list[dict]:
        """The notices not dismissed (only those not yet told in the popup, if `untold`), newest closed first: key,
        closed (ISO), found_at, notified_at, status, company, title, url. Only confirmed ones (the closed mark was
        seen again by a later check: one blip never notifies), or with `pending`, the unconfirmed ones instead."""
        rows = self.db.execute(
            "SELECT n.key, n.closed, n.found_at, n.notified_at, j.status, j.data FROM closed_notices n "
            "JOIN jobs j ON j.key=n.key WHERE n.dismissed_at IS NULL AND "
            + ("NOT " if pending else "")
            + "EXISTS (SELECT 1 FROM closed_confirmed c WHERE c.key=n.key AND c.closed=n.closed)"
            + (" AND n.notified_at IS NULL" if untold else "") + " ORDER BY n.closed DESC")
        out = []
        for r in rows:
            job = Job.from_dict(json.loads(r["data"]))
            out.append({"key": r["key"], "closed": r["closed"], "found_at": r["found_at"],
                        "notified_at": r["notified_at"], "status": r["status"], "company": job.display_company,
                        "title": job.title, "url": job.url})
        return out

    def mark_closed_notified(self, keys: list[str]):
        """The popup told about these notices."""
        with self.db:
            self.db.executemany("UPDATE closed_notices SET notified_at=? WHERE key=?", [(_now(), k) for k in keys])

    def dismiss_closed_notices(self, keys: list[str] | None = None) -> int:
        """Dismiss these notices (every undismissed one, with no keys). Returns how many were."""
        with self.db:
            if keys is None:
                return self.db.execute("UPDATE closed_notices SET dismissed_at=? WHERE dismissed_at IS NULL",
                                       (_now(),)).rowcount
            return sum(self.db.execute("UPDATE closed_notices SET dismissed_at=? WHERE key=? AND dismissed_at IS "
                                       "NULL", (_now(), k)).rowcount for k in keys)

    def restore_closed_notices(self, keys: list[str]):
        """Bring cleared notices back (an undo)."""
        with self.db:
            self.db.executemany("UPDATE closed_notices SET dismissed_at=NULL WHERE key=?", [(k,) for k in keys])

    def set_duplicate(self, key: str, other: str):
        """Record that a job is the same opening as another one already acted on (see dupes.py), by its key."""
        with self.db:
            self.db.execute("UPDATE jobs SET duplicate_of=? WHERE key=?", (other or None, key))

    def board_jobs(self, source: str, company: str) -> dict[str, Job]:
        """Every job ever seen on one board, open or closed, by key."""
        rows = self.db.execute("SELECT key, data FROM jobs WHERE source=? AND company=?", (source, company))
        return {r["key"]: Job.from_dict(json.loads(r["data"])) for r in rows}

    def known_jobs(self, source: str, company: str) -> KnownJobs:
        """board_jobs, with each job read when it's asked for (from any thread): a check holds the keys of every
        searched board's jobs, not their postings' text."""
        keys = {r["key"] for r in self.db.execute("SELECT key FROM jobs WHERE source=? AND company=?",
                                                  (source, company))}
        return KnownJobs(self.path, keys, (source, company))

    def manual_jobs(self) -> list[Job]:
        """Every job added by hand or from an alert email (source MANUAL), at any status, open or closed."""
        rows = self.db.execute("SELECT data FROM jobs WHERE source=?", (MANUAL,))
        return [Job.from_dict(json.loads(r["data"])) for r in rows]

    def open_board_jobs(self, source: str, company: str) -> list[tuple[Job, str]]:
        """One board's jobs still open, newest first, each with when it was first seen."""
        rows = self.db.execute("SELECT data, first_seen FROM jobs WHERE source=? AND company=? AND closed IS NULL "
                               "ORDER BY first_seen DESC", (source, company))
        return [(Job.from_dict(json.loads(r["data"])), r["first_seen"]) for r in rows]

    def set_closed(self, key: str, closed: bool) -> bool:
        """Record whether a job's posting is gone, as found by checking it (`jobwatch check`); a watched board's
        jobs are also kept up to date by every fetch. Returns whether that changed anything."""
        with self.db:
            if closed:
                cur = self.db.execute("UPDATE jobs SET closed=? WHERE key=? AND closed IS NULL", (_now(), key))
            else:
                cur = self.db.execute("UPDATE jobs SET closed=NULL WHERE key=? AND closed IS NOT NULL", (key,))
            return bool(cur.rowcount)

    def jobs(self, statuses: tuple[str, ...] | None = None, include_closed: bool = False) -> list[tuple[Job, dict]]:
        """(job, record) pairs; the record has status, first_seen, closed, note, and for applications applied_at,
        next_step and follow_up."""
        return list(self.iter_jobs(statuses, include_closed))

    def job(self, key: str) -> Job | None:
        """The job with exactly this key, or None."""
        row = self.db.execute("SELECT data FROM jobs WHERE key=?", (key,)).fetchone()
        return Job.from_dict(json.loads(row["data"])) if row else None

    def titles(self, keys) -> dict[str, str]:
        """{key: title} for the jobs these keys name, as find() reads a key (the full key, else a unique ending):
        a key that names no job, or several, is left out. The full keys are read in one indexed query that skips
        the postings' text; only the rest go through find(). What was looked up stays for this connection, so a
        page of jobs resolves the same comp keys once, not once a job."""
        known = self._titles
        todo = [k for k in dict.fromkeys(keys) if k not in known]
        for i in range(0, len(todo), 500):  # SQLite's limit on query variables
            chunk = todo[i:i + 500]
            for r in self.db.execute(f"SELECT key, json_extract(data, '$.title') AS title FROM jobs WHERE key IN "
                                     f"({','.join('?' * len(chunk))})", chunk):
                known[r["key"]] = r["title"]
        for k in todo:
            if k not in known:
                try:
                    known[k] = self.find(k)[0].title
                except KeyError:
                    known[k] = None
        return {k: known[k] for k in keys if known[k] is not None}

    def iter_jobs(self, statuses: tuple[str, ...] | None = None, include_closed: bool = False
                  ) -> Iterator[tuple[Job, dict]]:
        """jobs(), one pair at a time: a caller that keeps only some of them (the filters pass a few hundred of a
        hundred thousand) never holds the rest, with their postings' text, in memory at once."""
        sql, args = _ROW + " WHERE 1=1", []
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if not include_closed:
            sql += " AND closed IS NULL"
        for r in self.db.execute(sql + " ORDER BY first_seen DESC", args):
            yield Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}

    def company_names(self, statuses: tuple[str, ...], include_closed: bool = False) -> list[tuple[str, str, str, str]]:
        """(key, source, board company, the company name its posting gives or "") of the jobs at these statuses,
        in iter_jobs' order, reading no posting's text: a caller that wants only the jobs at one company reads
        these, then jobs_with_keys for the few it keeps."""
        sql = ("SELECT key, source, company, COALESCE(json_extract(data, '$.company_name'), '') FROM jobs WHERE status "
               f"IN ({','.join('?' * len(statuses))})" + ("" if include_closed else " AND closed IS NULL") +
               " ORDER BY first_seen DESC")
        return [tuple(r) for r in self.db.execute(sql, statuses)]

    def jobs_with_keys(self, keys: list[str]) -> list[tuple[Job, dict]]:
        """(job, record) pairs for these full keys, in the order given (a key that names no job is left out)."""
        found: dict[str, tuple[Job, dict]] = {}
        for i in range(0, len(keys), 500):  # SQLite's limit on query variables
            chunk = keys[i:i + 500]
            for r in self.db.execute(f"{_ROW} WHERE key IN ({','.join('?' * len(chunk))})", chunk):
                found[r["key"]] = (Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"})
        return [found[k] for k in keys if k in found]

    def search(self, text: str) -> list[tuple[Job, dict]]:
        """Jobs at any status, closed too, whose note, next step, via, title, company, key or link contains the
        text (any case), newest first: "which application did the recruiter call about?", or a req id from a
        posting's link. instr, not LIKE: the text is taken literally ("$101/hr", "100%")."""
        text = text.strip().lower()
        if not text:
            return []
        fields = ("note", "next_step", "via", "json_extract(data, '$.title')", "company",
                  "json_extract(data, '$.company_name')", "key", "json_extract(data, '$.url')")
        rows = self.db.execute(f"{_ROW} WHERE {' OR '.join(f'instr(lower({f}), ?)' for f in fields)} "
                               "ORDER BY first_seen DESC", [text] * len(fields)).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

    def mentioning(self, text: str) -> list[tuple[Job, dict]]:
        """Jobs at any status, closed too, newest first, whose kept data (link included) or note holds this text
        exactly: a posting id or key to be checked by the caller. A plain substring test over the stored rows, which
        is much cheaper than search(): it reads no JSON fields and builds no Job but the few that match."""
        if not text:
            return []
        rows = self.db.execute(f"{_ROW} WHERE instr(data, ?) OR instr(COALESCE(note, ''), ?) "
                               "ORDER BY first_seen DESC", (text, text)).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

    def company_counts(self) -> list[dict]:
        """How many jobs each company has, by status and whether closed, without reading any posting: source,
        company (the board), name (what its jobs call it), status, closed (bool) and n."""
        return [dict(r) for r in self.db.execute(
            "SELECT source, company, json_extract(data, '$.company_name') AS name, status, closed IS NOT NULL AS "
            "closed, COUNT(*) AS n FROM jobs GROUP BY source, company, name, status, closed IS NOT NULL")]

    def applications(self) -> list[tuple[Job, dict]]:
        """Everything applied to. Open applications come first, those with the soonest follow-up day at the top,
        then the most recent; rejected, withdrawn and closed-by-company ones last."""
        rows = self.jobs(STAGES, include_closed=True)
        rows.sort(key=lambda r: r[1]["applied_at"] or "", reverse=True)
        rows.sort(key=lambda r: (r[1]["status"] in ENDED, r[1]["follow_up"] is None, r[1]["follow_up"] or ""))
        return rows

    def applied_on(self, on: str | date) -> int:
        """How many applications went out on this day, whatever stage they're at now. applied_at is the local
        calendar day (see set_status), so "today" is the day on this computer's clock, not UTC's."""
        return self.db.execute(f"SELECT COUNT(*) FROM jobs WHERE applied_at=? AND status IN "
                               f"({','.join('?' * len(STAGES))})", (day(on), *STAGES)).fetchone()[0]

    def find(self, key: str, prefer_open: bool = False) -> tuple[Job, dict]:
        """A job by its full key, by a unique ending of it (the posting id is enough), or else by its company's
        name or part of it, in any case, when that names one job: the one queued or applied to there, or the only
        one there at all. prefer_open: when a company still names several jobs, the one open application (applied,
        screening or interviewing) among them wins."""
        # The full key is one lookup in the key's index. Only a partial key (an ending, or a company's name) reads
        # every row for LIKE: an exact match always wins over the endings, so it never needs that scan.
        rows = self.db.execute(f"{_ROW} WHERE key=?", (key,)).fetchall()
        if not rows:
            rows = self.db.execute(f"{_ROW} WHERE key LIKE ?", (f"%{key}",)).fetchall()
        by_company = not rows
        if by_company:
            rows = self._at_company(key)
            if prefer_open and len(live := [r for r in rows if r["status"] in OPEN]) == 1:
                rows = live
        if by_company and len(rows) > 1:
            listed = "\n".join(f"  {r['key']}  {self._label(r)}" for r in rows[:10])
            more = f"\n  and {len(rows) - 10} more" if len(rows) > 10 else ""
            raise KeyError(f"{key!r} matches {len(rows)} jobs; give the key of one:\n{listed}{more}")
        if len(rows) != 1:
            raise KeyError(f"no job matches {key!r}" if not rows else
                           f"{key!r} matches {len(rows)} jobs: {', '.join(r['key'] for r in rows[:5])}")
        r = rows[0]
        return Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}

    def with_url(self, urls: list[str]) -> tuple[Job, dict] | None:
        """The job whose link is one of these, exactly as kept: the one queued or applied to when several are."""
        if not urls:
            return None
        rows = self.db.execute(f"{_ROW} WHERE json_extract(data, '$.url') IN ({','.join('?' * len(urls))})"
                               " ORDER BY key", urls).fetchall()
        rows = [r for r in rows if r["status"] in ("queued", *STAGES)] or rows
        if not rows:
            return None
        return Job.from_dict(json.loads(rows[0]["data"])), {k: rows[0][k] for k in rows[0].keys() if k != "data"}

    def open_at(self, name: str) -> list[tuple[Job, dict]]:
        """The open (not closed) jobs whose company's name or board holds `name`, spaces and punctuation aside, at any
        status: the candidates for telling which of a company's jobs a page is for."""
        bare = _letters(name)
        if not bare:
            return []
        self.db.create_function("letters", 1, _letters, deterministic=True)
        rows = self.db.execute(f"{_ROW} WHERE closed IS NULL AND (instr(letters(company), ?) "
                               "OR instr(letters(json_extract(data, '$.company_name')), ?)) ORDER BY key",
                               (bare, bare)).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

    def _at_company(self, name: str) -> list[sqlite3.Row]:
        """Jobs whose company name or board contains `name` (any case), or failing that, contains it once spaces
        and punctuation are ignored ("Smith Wesson" for Smith & Wesson): the ones queued or applied to, if any."""
        name = name.strip().lower()
        if not name:
            return []
        rows = self.db.execute(f"{_ROW} WHERE instr(lower(company), ?) "
                               "OR instr(lower(json_extract(data, '$.company_name')), ?) ORDER BY key",
                               (name, name)).fetchall()
        if not rows and (bare := _letters(name)):
            self.db.create_function("letters", 1, _letters, deterministic=True)
            rows = self.db.execute(f"{_ROW} WHERE instr(letters(company), ?) "
                                   "OR instr(letters(json_extract(data, '$.company_name')), ?) ORDER BY key",
                                   (bare, bare)).fetchall()
        return [r for r in rows if r["status"] in ("queued", *STAGES)] or rows

    @staticmethod
    def _label(row: sqlite3.Row) -> str:
        job = Job.from_dict(json.loads(row["data"]))
        return f"{job.display_company}: {job.title} ({row['status']})"

    def set_status(self, keys: list[str], status: str, note: str | None = None, on: str | None = None):
        """Move jobs to a status. Moving to an application stage records the day applied: `on` when given (it
        corrects an earlier day), else today unless a day is already recorded. It also saves the posting as it
        reads then; moving back before applying clears the day. Snoozing needs an application in progress at the
        job's company to wait for, and sets the day it comes back at the latest (see wake_snoozed)."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if status == "snoozed":
            for key in keys:
                job, _ = self.find(key)
                if not self.waiting_on(job):
                    raise ValueError(f"no application is in progress at {job.display_company}, so {job.key} has "
                                     "nothing to wait for: queue it or skip it")
        with self.db:
            for key in keys:
                self._keep_replaced(key, note)
                self.db.execute("UPDATE jobs SET follow_up=CASE WHEN ? THEN ? WHEN status='snoozed' THEN NULL "
                                "ELSE follow_up END, status=?, status_at=?, note=COALESCE(?, note), applied_at="
                                "CASE WHEN ? THEN COALESCE(?, applied_at, ?) END WHERE key=?",
                                (status == "snoozed", day(f"+{SNOOZE_DAYS}"), status, _now(), note, status in STAGES,
                                 day(on), date.today().isoformat(), key))
        if status in STAGES:
            for key in keys:
                job, _ = self.find(key)
                self.package(job.key).keep_posting(job)
        self.wake_snoozed()

    def in_progress(self) -> dict[str, list[dict]]:
        """The applications still open, by company (contacts.company_key): each one's key, title and status."""
        out: dict[str, list[dict]] = {}
        for job, rec in self.jobs(IN_PROGRESS, include_closed=True):  # a closed posting's application can go on
            out.setdefault(company_key(job.display_company), []).append(
                {"key": job.key, "title": job.title, "status": rec["status"]})
        return out

    def waiting_on(self, job: Job, open_now: dict[str, list[dict]] | None = None) -> list[dict]:
        """The other applications in progress at this job's company (pass `open_now` when you have in_progress())."""
        at = (self.in_progress() if open_now is None else open_now).get(company_key(job.display_company), [])
        return [a for a in at if a["key"] != job.key]

    def wake_snoozed(self) -> list[str]:
        """Queue the snoozed jobs whose company has no application in progress any more, or whose day to come back
        has come (many companies never say no), and note why. Returns their keys."""
        rows = self.jobs(("snoozed",), include_closed=True)
        if not rows:
            return []
        open_now, today = self.in_progress(), date.today().isoformat()
        why = {}
        for job, rec in rows:
            if not self.waiting_on(job, open_now):
                why[job.key] = "your application there ended"
            elif rec["follow_up"] and rec["follow_up"] <= today:
                why[job.key] = "its time was up, with no news from your application there"
        with self.db:
            for key in why:
                self.db.execute("UPDATE jobs SET status='queued', status_at=?, follow_up=NULL WHERE key=?",
                                (_now(), key))
        for key, reason in why.items():
            self.add_note(key, f"Back from snooze: {reason}, so it's in the queue again.")
        return list(why)

    def package(self, key: str) -> Package:
        """What was sent with the application for this job (key or posting id)."""
        return Package(self.packages, self.find(key)[0].key)

    def track(self, key: str, *, note: str | None = None, next_step: str | None = None,
              follow_up: str | None = None, applied: str | None = None, round: str | None = None):
        """Update an application's note, next step, follow-up day, day applied or interview round (an id in
        rounds.ROUNDS). None leaves a field as it is; an empty string clears it."""
        fields = {"note": note, "next_step": next_step, "round": None if round is None else rounds.check(round)}
        fields = {k: v.strip() or None for k, v in fields.items() if v is not None}
        if follow_up is not None:
            fields["follow_up"] = day(follow_up)
        if applied is not None:
            fields["applied_at"] = day(applied)
        if fields:
            with self.db:
                if note is not None:
                    self._keep_replaced(key, note)
                self.db.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in fields)} WHERE key=?",
                                (*fields.values(), key))

    def set_url(self, key: str, url: str):
        """Give an application added by hand its link: the posting, or the company's careers site once the posting
        is gone (a Workday site's link is enough for its sign-in page). A fetched posting keeps the board's link."""
        job, _ = self.find(key)
        if job.source != MANUAL:
            raise ValueError(f"{job.key} comes from its board, which sets its link")
        job.url = url.strip()
        with self.db:
            self.db.execute("UPDATE jobs SET data=? WHERE key=?", (json.dumps(job.to_dict()), job.key))

    def replace_text(self, key: str, text: str):
        """Replace the posting text kept for a job from its board with a fuller one read again (a text that was
        read while the page was only partly served), keeping everything else about it."""
        job, _ = self.find(key)
        job.description = text.strip()
        with self.db:
            self.db.execute("UPDATE jobs SET data=?, slim=NULL WHERE key=?", (json.dumps(job.to_dict()), job.key))

    def set_description(self, key: str, text: str, posting: Job | None = None):
        """Give an application added by hand the posting's text, pasted (found later, or from a copy once the
        posting is gone), so it can be scored and prepped. The pay is read from it if none is set, and the
        posting kept with the application is replaced: what was kept had no text to keep. With `posting` (the
        job read from its link later), its pay, places, remote flag, department and posted day fill in what
        the application has none of."""
        job, rec = self.find(key)
        if job.source != MANUAL:
            raise ValueError(f"{job.key} comes from its board, which sets its text")
        job.description = text.strip()
        if posting:
            if job.salary_min is None and posting.salary_min is not None:
                job.set_pay(posting.salary_min, posting.salary_max, posting.currency, posting.pay_per)
            job.locations = job.locations or list(posting.locations)
            job.remote = posting.remote if job.remote is None else job.remote
            job.department = job.department or posting.department
            job.posted = job.posted or posting.posted
        if job.salary_min is None and (pay := parse_pay(job.description)):
            job.set_pay(*pay[:2], "USD", pay[2])
        with self.db:
            self.db.execute("UPDATE jobs SET data=? WHERE key=?", (json.dumps(job.to_dict()), job.key))
        kept = self.package(job.key)
        if rec["status"] in STAGES or (kept.dir / POSTING).is_file():  # applied before, queued again for a reposting
            kept.keep_posting(job, again=True)

    def would_replace(self, key: str, new: str | None) -> int:
        """How many characters of the job's note setting it to `new` would drop: 0 when `new` is None (the note stays),
        when there's no note, or when `new` keeps it (add_note writes the note followed by a line)."""
        row = self.db.execute("SELECT note FROM jobs WHERE key=?", (key,)).fetchone()
        old = (row["note"] or "").strip() if row else ""
        return 0 if new is None or not old or new.strip().startswith(old) else len(old)

    def _keep_replaced(self, key: str, new: str | None):
        """Before a note is replaced (not added to), keep the one there in note_history, so `jobwatch notes KEY --undo`
        brings it back: `mark --note` once wiped four applications' long histories at once."""
        if self.would_replace(key, new):
            old = self.db.execute("SELECT note FROM jobs WHERE key=?", (key,)).fetchone()["note"]
            self.db.execute("INSERT INTO note_history (key, note, replaced_at) VALUES (?, ?, ?)", (key, old, _now()))

    def note_history(self, key: str) -> list[dict]:
        """The notes replaced on this job, newest first: id, note, replaced_at."""
        return [dict(r) for r in self.db.execute(
            "SELECT id, note, replaced_at FROM note_history WHERE key=? ORDER BY id DESC", (key,))]

    def undo_note(self, key: str) -> tuple[str, int]:
        """Bring back the note the last replacement dropped. The note there now goes into the history in its place, so
        undoing again goes back. Returns the note restored and the length of the note it replaced."""
        job, rec = self.find(key)
        if not (history := self.note_history(job.key)):
            raise ValueError(f"{job.key} has no replaced note to bring back")
        last = history[0]
        with self.db:
            self.db.execute("DELETE FROM note_history WHERE id=?", (last["id"],))
        self.track(job.key, note=last["note"])
        return last["note"], len((rec.get("note") or "").strip())

    def add_note(self, key: str, text: str):
        """Add a dated line to the note, keeping what's there (the recruiter's name, what was said before). A line
        that starts with its own date keeps that one: news recorded a few days late."""
        text = text.strip()
        if not text:
            return
        _, rec = self.find(key)
        line = text if re.match(r"\d{4}-\d{2}-\d{2}\b", text) else f"{date.today().isoformat()}: {text}"
        self.track(key, note=f"{rec['note']} {line}" if rec.get("note") else line)

    def snooze(self, key: str, days: int = 7) -> str:
        """Push an open application's follow-up day `days` out from today, leaving its stage alone, and note it
        ("Snoozed 7 days": quiet.py doesn't count that line as news, so a snoozed application stays quiet).
        Returns the new day."""
        job, rec = self.find(key, prefer_open=True)
        if rec["status"] not in STAGES or rec["status"] in ENDED:
            raise ValueError(f"{job.key} isn't an open application ({rec['status']})")
        if days < 1:
            raise ValueError("snooze for at least a day")
        until = day(f"+{days}")
        self.add_note(job.key, f"Snoozed {days} day{'s' * (days != 1)}: follow up {until}.")
        self.track(job.key, follow_up=until)
        return until

    def add(self, company: str, title: str, url: str = "", status: str = "applied", applied: str | None = None,
            location: str = "", note: str | None = None, next_step: str | None = None,
            follow_up: str | None = None, description: str = "") -> Job:
        """Track a job found somewhere jobwatch doesn't read (a referral, a recruiter, LinkedIn...): an application,
        or one to consider (status queued). description: the posting's text, pasted, so it can be scored."""
        company, title, url = company.strip(), title.strip(), url.strip()
        if not company or not title:
            raise ValueError("an application needs a company and a job title")
        self._titles.clear()
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if url and (row := self.db.execute("SELECT key FROM jobs WHERE json_extract(data, '$.url')=?",
                                            (url,)).fetchone()):
            raise ValueError(f"already tracked as {row['key']}: update that one instead")
        board, base = _slug(company), _slug(title)
        taken = {r["key"] for r in self.db.execute("SELECT key FROM jobs WHERE source=? AND company=?",
                                                    (MANUAL, board))}
        id_, n = base, 1
        while f"{MANUAL}:{board}:{id_}" in taken:
            n += 1
            id_ = f"{base}-{n}"
        job = Job(source=MANUAL, company=board, id=id_, title=title, url=url, company_name=company,
                  locations=[location.strip()] if location.strip() else [], description=description.strip())
        if job.description and (pay := parse_pay(job.description)):
            job.set_pay(*pay[:2], "USD", pay[2])
        now = _now()
        with self.db:
            self.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen) VALUES "
                            "(?, ?, ?, ?, ?, ?)", (job.key, MANUAL, board, json.dumps(job.to_dict()), now, now))
        self.set_status([job.key], status, note, on=applied)
        self.track(job.key, next_step=next_step, follow_up=follow_up)
        return job

    def linked(self, job: Job) -> Job | None:
        """For an application added by hand, the posting a watched board has for the same job: same company, and
        the requisition id in the title or link ("R0123456", "REQ-4711", "Job 20769") is the posting's id."""
        if job.source != MANUAL:
            return None
        found = {}
        for req in {m.group(1).upper() for m in _REQ.finditer(f"{job.title} {job.url} {job.id}")}:
            digits = re.sub(r"\D", "", req)
            rows = self.db.execute("SELECT data FROM jobs WHERE source!=? AND json_extract(data, '$.id') LIKE ?",
                                   (MANUAL, f"%{digits}%"))
            for r in rows:
                other = Job.from_dict(json.loads(r["data"]))
                same_company = job.company.replace("-", "") in (_slug(other.display_company).replace("-", "")
                                                                + other.company.replace("-", ""))
                if same_company and _same_req(req, other.id):
                    found[other.key] = other
        return next(iter(found.values())) if len(found) == 1 else None

    def candidate_home(self, job: Job) -> str | None:
        """The company's page for checking an application's status (Workday), from the job's link or, for one
        added by hand without a link, from the posting it's linked to by requisition id."""
        return candidate_home(job.url) or ((other := self.linked(job)) and candidate_home(other.url)) or None

    def score(self, key: str, resume: str) -> dict | None:
        """The job's newest fit score, whatever resume made it; stale (see scorestate.flag) when it was made under
        an older resume than `resume` or marked. A new resume doesn't hide it: scoring it again is a decision (see
        scorestate)."""
        row = self.db.execute(f"SELECT resume, result FROM scores WHERE key=? AND {_SCORED} "
                              "ORDER BY scored_at DESC LIMIT 1", (key,)).fetchone()
        if not row:
            return None
        return scorestate.flag(reconcile(json.loads(row["result"]), self.education), row["resume"],
                               resume_family(resume), scorestate.kept_map(self.db),
                               scorestate.marks(self.db, [key]).get(key))

    def scores(self, resume: str) -> Scores:
        """Every job's newest fit score by job key, one query for a whole list of jobs (see score)."""
        return Scores({r["key"]: (r["result"], r["resume"]) for r in self.newest_scores()}, self.education, resume,
                      scorestate.kept_map(self.db), scorestate.marks(self.db))

    def newest_scores(self) -> list[sqlite3.Row]:
        """Per job with a score, its newest: key, resume (the id it was made under), result (JSON), score and
        scored_at."""
        return self.db.execute(f"SELECT key, resume, result, json_extract(result, '$.score') AS score, "
                               f"MAX(scored_at) AS scored_at FROM scores WHERE {_SCORED} GROUP BY key").fetchall()

    def drop_incomplete_scores(self, resume: str) -> list[str]:
        """Remove this resume's current scores whose model left requirements unjudged (see score.unjudged), saved
        before such results counted as failures, so the jobs are scored again. Returns their keys."""
        return self._drop_scores(resume, lambda fit: bool(unjudged(fit.get("flags"))))

    def drop_kept_scores(self, resume: str) -> list[str]:
        """Remove this resume's current scores that keep_old_scores kept from an earlier scorer, so the jobs are
        scored by the one in use (until then their old score shows as stale). Returns their keys."""
        return self._drop_scores(resume, lambda fit: "kept_from" in fit)

    def _drop_scores(self, resume: str, drop: Callable[[dict], bool]) -> list[str]:
        keys = [r["key"] for r in self.db.execute("SELECT key, result FROM scores WHERE resume=?", (resume,))
                if drop(json.loads(r["result"]))]
        with self.db:
            self.db.executemany("DELETE FROM scores WHERE key=? AND resume=?", [(k, resume) for k in keys])
        return keys

    def keep_old_scores(self, resume: str, scorer: str = "") -> tuple[int, str]:
        """Make the scores one earlier scorer made for this resume and prompts current scores for `resume`, for a
        scorer change that doesn't change what a score means (a prompt reordered for caching): those jobs aren't
        scored again, and the rest are scored by the new scorer as usual. Only that one scorer's scores are kept,
        so ones from a scorer replaced on purpose stay set aside. `scorer` is its id (the 8 characters after
        "scorer-"); by default the one in use just before, which made the newest of the old scores. A kept score
        keeps the day it was made and says, under "kept_from", which resume id made it. Jobs already scored are
        left alone. Returns how many were kept, and the scorer they came from ("" when there was none)."""
        family = resume_family(resume)
        old = [dict(r) for r in self.db.execute(
            f"SELECT key, resume, result, scored_at FROM scores WHERE resume!=? AND resume LIKE ? AND {_SCORED} "
            f"ORDER BY scored_at", (resume, ":".join(family.split(":")[:2]) + "%"))
            if resume_family(r["resume"]) == family]
        if not scorer:
            ids = [m.group(1) for r in old if (m := re.search(r":scorer-([0-9a-f]{8})", r["resume"]))]
            scorer = ids[-1] if ids else ""
        if not scorer:
            return 0, ""
        current = {r["key"] for r in self.db.execute("SELECT key FROM scores WHERE resume=?", (resume,))}
        newest = {r["key"]: r for r in old if f":scorer-{scorer}" in r["resume"] and r["key"] not in current}
        kept = [(key, resume, json.dumps({**json.loads(r["result"]), "kept_from": r["resume"]}), r["scored_at"])
                for key, r in newest.items()]
        with self.db:
            self.db.executemany("INSERT INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)", kept)
        return len(kept), scorer

    def save_score(self, key: str, resume: str, result: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                            (key, resume, json.dumps(result), _now()))
            self.db.execute("DELETE FROM score_failures WHERE key=? AND resume=?", (key, resume))
            self.db.execute("DELETE FROM score_stale WHERE key=?", (key,))  # scored again: no longer marked

    def save_score_failure(self, key: str, resume: str, model: str, error: str):
        """A job that failed to score for this resume (and prompts) with this model, and why, so a restart doesn't
        try it again at once (see score_failures)."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO score_failures (key, resume, model, error, failed_at) "
                            "VALUES (?, ?, ?, ?, ?)", (key, resume, model, error, _now()))

    def score_failures(self, resume: str, model: str, within: timedelta) -> dict[str, str]:
        """{job key: error} for the jobs that failed to score for this resume with this model in the last `within`.
        A new resume, edited prompts, another model or the time passing leaves a job out: it's tried again."""
        since = (datetime.now(UTC) - within).isoformat(timespec="microseconds")
        return {r["key"]: r["error"] for r in self.db.execute(
            "SELECT key, error FROM score_failures WHERE resume=? AND model=? AND failed_at>=?",
            (resume, model, since))}

    def add_score_usage(self, backend: str, jobs: int, day: date | None = None):
        """Count jobs scored with this backend on this local day (default today), for scoring.daily."""
        if jobs:
            with self.db:
                self.db.execute("INSERT INTO score_usage (day, backend, jobs) VALUES (?, ?, ?) ON CONFLICT (day, "
                                "backend) DO UPDATE SET jobs = jobs + excluded.jobs",
                                ((day or date.today()).isoformat(), backend, jobs))

    def set_scorer_down(self, scorer: str, reason: str, until: datetime):
        """A scoring chain step ("backend:model") that can't score until `until` (out of credit or quota): it's
        skipped without a call until then, and Settings shows it paused, with why."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.db:
            self.db.execute("INSERT INTO scorer_down (scorer, reason, since, until) VALUES (?, ?, ?, ?) ON CONFLICT "
                            "(scorer) DO UPDATE SET reason = excluded.reason, until = excluded.until",
                            (scorer, reason, now, until.astimezone(UTC).isoformat(timespec="seconds")))

    def clear_scorer_down(self, scorer: str):
        with self.db:
            self.db.execute("DELETE FROM scorer_down WHERE scorer=?", (scorer,))

    def scorers_down(self, now: datetime | None = None) -> dict[str, dict]:
        """{scorer: {reason, since, until}} for the steps (and pools: pool:<name>) paused now, read from the state
        file at each call: a pause outlives a restart, and one whose time is up (the wall clock past its UTC `until`)
        is left out, so it is tried again with nothing to clear. A row whose time can't be read counts as no pause:
        the step is tried, and a refusal pauses it again properly."""
        now = now or datetime.now(UTC)
        down = {}
        for r in self.db.execute("SELECT * FROM scorer_down"):
            try:
                until = datetime.fromisoformat(r["until"])
                until = until if until.tzinfo else until.replace(tzinfo=UTC)
                if until > now:
                    down[r["scorer"]] = {"reason": r["reason"], "since": r["since"],
                                         "until": until.astimezone(UTC).isoformat(timespec="seconds")}
            except (TypeError, ValueError):
                continue
        return down

    def score_usage(self, backend: str, day: date | None = None) -> int:
        """Jobs scored with this backend on this local day (default today)."""
        row = self.db.execute("SELECT jobs FROM score_usage WHERE day=? AND backend=?",
                              ((day or date.today()).isoformat(), backend)).fetchone()
        return row["jobs"] if row else 0

    def add_company_usage(self, company: str, jobs: int, day: date | None = None):
        """Count jobs of this company the background scorer scored on this local day (default today), for
        scoring.per_company."""
        if jobs:
            with self.db:
                self.db.execute("INSERT INTO company_usage (day, company, jobs) VALUES (?, ?, ?) ON CONFLICT (day, "
                                "company) DO UPDATE SET jobs = jobs + excluded.jobs",
                                ((day or date.today()).isoformat(), company, jobs))

    def company_usage(self, day: date | None = None) -> dict[str, int]:
        """{company: jobs the background scorer scored} on this local day (default today)."""
        return {r["company"]: r["jobs"] for r in self.db.execute(
            "SELECT company, jobs FROM company_usage WHERE day=?", ((day or date.today()).isoformat(),))}

    def add_score_cost(self, backend: str, model: str, batch: bool, jobs: int, input_tokens: int, output_tokens: int,
                       cache_write_tokens: int = 0, cache_read_tokens: int = 0, day: date | None = None):
        """Tokens a scoring run used (from the API replies), by local day, backend, model and whether it went
        through the Batches API, with the jobs it scored. Prices are applied when read (see scorestats.py)."""
        with self.db:
            self.db.execute(
                "INSERT INTO score_cost (day, backend, model, batch, jobs, input_tokens, output_tokens, "
                "cache_write_tokens, cache_read_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (day, backend, model, batch) DO UPDATE SET jobs = jobs + excluded.jobs, "
                "input_tokens = input_tokens + excluded.input_tokens, "
                "output_tokens = output_tokens + excluded.output_tokens, "
                "cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens, "
                "cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens",
                ((day or date.today()).isoformat(), backend, model, int(batch), jobs, input_tokens, output_tokens,
                 cache_write_tokens, cache_read_tokens))

    def add_credit_spend(self, day: date, model: str, jobs: int, input_tokens: int, output_tokens: int,
                         cache_write_tokens: int, cache_read_tokens: int, usd: float):
        """What a dated Claude entry in scoring.fallback spent (see credit.py): tokens from the API replies and the
        dollars they come to at list price, by Eastern day and model. The caps are checked against this."""
        with self.db:
            self.db.execute(
                "INSERT INTO credit_spend (day, model, jobs, input_tokens, output_tokens, cache_write_tokens, "
                "cache_read_tokens, usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (day, model) DO UPDATE SET "
                "jobs = jobs + excluded.jobs, input_tokens = input_tokens + excluded.input_tokens, "
                "output_tokens = output_tokens + excluded.output_tokens, "
                "cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens, "
                "cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens, usd = usd + excluded.usd",
                (day.isoformat(), model, jobs, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens,
                 usd))

    def credit_spent(self, day: date) -> tuple[float, float]:
        """(dollars spent on this day, dollars spent in all) from the credit ledger, across models."""
        today = self.db.execute("SELECT COALESCE(SUM(usd), 0) AS n FROM credit_spend WHERE day=?",
                                (day.isoformat(),)).fetchone()["n"]
        total = self.db.execute("SELECT COALESCE(SUM(usd), 0) AS n FROM credit_spend").fetchone()["n"]
        return float(today), float(total)

    def credit_ledger(self) -> list[dict]:
        """The credit ledger's rows, oldest day first."""
        return [dict(r) for r in self.db.execute("SELECT * FROM credit_spend ORDER BY day, model")]

    def score_costs(self, since: date | None = None) -> list[dict]:
        """The recorded token usage (see add_score_cost) from this local day on (default: all of it)."""
        return [dict(r) for r in self.db.execute("SELECT * FROM score_cost WHERE day>=? ORDER BY day",
                                                 ((since or date.min).isoformat(),))]

    def scored_by_day(self, since: date) -> list[tuple[date, str]]:
        """(local day, scored_by) of every fit score made from this local day on, whatever the resume, for counting
        what each backend scored. Scores kept from an earlier scorer (keep_old_scores) aren't new work."""
        edge = (datetime.combine(since, datetime.min.time()).astimezone() - timedelta(hours=1)).astimezone(
            UTC).isoformat(timespec="microseconds")
        out = []
        for r in self.db.execute("SELECT result, scored_at FROM scores WHERE scored_at>=?", (edge,)):
            day = datetime.fromisoformat(r["scored_at"]).astimezone().date()
            fit = json.loads(r["result"])
            if day >= since and "kept_from" not in fit:
                out.append((day, str(fit.get("scored_by") or "")))
        return out

    def scored_since(self, resume: str, since: date) -> list[tuple[str, datetime, dict]]:
        """(job key, when in local time, the fit) of every score for this resume made from this local day on, the
        newest first; scores kept from an earlier scorer (keep_old_scores) aren't new and are left out."""
        rows = self.db.execute(f"SELECT key, result, scored_at FROM scores WHERE resume=? AND scored_at>=? AND "
                               f"{_SCORED} ORDER BY scored_at DESC", (resume, day_start(since)))
        return [(r["key"], datetime.fromisoformat(r["scored_at"]).astimezone(), fit) for r in rows
                if "kept_from" not in (fit := json.loads(r["result"]))]

    # Drafted prep-sheet answers (see drafts.py): the model's reply as it came, under a hash of everything it was
    # sent, so opening a sheet again doesn't ask again. It's checked again each time it's read.

    def secret(self, name: str) -> str:
        """A random string made the first time it's asked for and kept in this file: it stays the same for as long
        as the state does (the calendar feed's address, which an app subscribes to, relies on that)."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO secrets (name, value) VALUES (?, ?)",
                            (name, secrets.token_urlsafe(24)))
        return self.db.execute("SELECT value FROM secrets WHERE name=?", (name,)).fetchone()[0]

    def draft(self, key: str, inputs: str) -> str | None:
        row = self.db.execute("SELECT reply FROM drafts WHERE key=? AND inputs=?", (key, inputs)).fetchone()
        return row["reply"] if row else None

    def save_draft(self, key: str, inputs: str, reply: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO drafts (key, inputs, reply, made_at) VALUES (?, ?, ?, ?)",
                            (key, inputs, reply, _now()))

    def update(self, job: Job):
        """Save a recorded job's posting data as it is now (a fetch does this for a watched board's jobs)."""
        self._titles.clear()
        with self.db:
            self.db.execute("UPDATE jobs SET data=?, slim=NULL WHERE key=?", (json.dumps(job.to_dict()), job.key))

    # Checks for new jobs: when each ran and what it found, so the page can say when the boards were last checked
    # and the next check can be planned from it, whoever ran the last one (the page, `jobwatch fetch`, MCP).

    def record_fetch(self, boards: int, jobs: int, new: int, errors: dict[str, str], warnings: dict[str, str]):
        with self.db:
            self.db.execute("INSERT INTO fetches (at, boards, jobs, new, errors, warnings) VALUES (?, ?, ?, ?, ?, ?)",
                            (_now(), boards, jobs, new, json.dumps(errors), json.dumps(warnings)))
            self.db.execute("DELETE FROM fetches WHERE rowid NOT IN (SELECT rowid FROM fetches ORDER BY at DESC "
                            "LIMIT ?)", (FETCHES_KEPT,))

    # What jobwatch did on its own or when asked (checked the boards, read job-alert mail, scored jobs, looked up
    # pay), for the page's Activity tab: kind (boards, mail, score, pay), a line saying what happened, whether it
    # worked, detail lines, what started it (by: schedule, page, background; empty when not known), and whether
    # it's worth a look (notable: a strong fit, a mailbox it couldn't read...), which the page tells you about.
    # jobs: the keys of the jobs the entry is about, so the page links it to their cards (a prep sheet's entry,
    # with none given, is about the application its file belongs to: see actjobs.sheet_jobs).

    def log(self, kind: str, text: str, ok: bool = True, detail: list[str] | tuple[str, ...] = (), by: str = "",
            notable: bool = False, jobs: list[str] | tuple[str, ...] | None = None):
        if jobs is None:
            jobs = ()
            if kind == "prep":
                try:
                    rows = list(self.iter_jobs(actjobs.APPLIED, include_closed=True))
                    jobs = [k for s in actjobs.sheets_in(text) for k in actjobs.sheet_jobs(rows, s)]
                except Exception as e:  # a link is a nicety: the entry is still kept
                    print(f"jobwatch: activity not linked: {type(e).__name__}: {e}", file=sys.stderr)
        jobs = list(dict.fromkeys(jobs))[:actjobs.KEPT]
        with self.db:
            self.db.execute("INSERT INTO activity (at, kind, text, ok, detail, by, notable, job_keys) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (_now(), kind, text, int(ok), json.dumps(list(detail)), by, int(notable),
                             json.dumps(jobs)))
            # kept per kind, so hundreds of jobs scored don't push the board checks and emails out
            self.db.execute("DELETE FROM activity WHERE kind=? AND rowid NOT IN (SELECT rowid FROM activity "
                            "WHERE kind=? ORDER BY at DESC LIMIT ?)", (kind, kind, ACTIVITY_KEPT))

    def activity(self, limit: int = 200, kind: str = "", since: str = "", notable: bool = False) -> list[dict]:
        """The newest first: at (ISO), kind, text, ok, detail (lines), by, notable and jobs (the jobs it is about, each
        {key, company, title, status}; one that is gone from the store is left out). kind: only that kind, or those
        kinds ("score,pay"); since: only ones after that time (ISO); notable: only the ones worth a look."""
        kinds = [k for k in kind.split(",") if k]
        among = ",".join("?" * len(kinds)) or "NULL"
        rows = self.db.execute(f"SELECT * FROM activity WHERE (? OR kind IN ({among})) AND at>? AND notable>=? "
                               "ORDER BY at DESC LIMIT ?", (not kinds, *kinds, since, int(notable), limit)).fetchall()
        keys = [json.loads(r["job_keys"]) if "job_keys" in r.keys() else [] for r in rows]
        refs = self.job_refs([k for ks in keys for k in ks])
        return [{"at": r["at"], "kind": r["kind"], "text": r["text"], "ok": bool(r["ok"]),
                 "detail": json.loads(r["detail"]), "by": r["by"], "notable": bool(r["notable"]),
                 "jobs": [refs[k] for k in ks if k in refs]} for r, ks in zip(rows, keys, strict=True)]

    def job_refs(self, keys: list[str]) -> dict[str, dict]:
        """{key: {key, company, title, status}} for the jobs with these keys that are in the store, to name and link
        them (the page: which tab a job's card is on follows its status)."""
        out: dict[str, dict] = {}
        keys = list(dict.fromkeys(keys))
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            for r in self.db.execute("SELECT key, company, status, json_extract(data, '$.company_name') AS name, "
                                     f"json_extract(data, '$.title') AS title FROM jobs WHERE key IN "
                                     f"({','.join('?' * len(chunk))})", chunk):
                out[r["key"]] = {"key": r["key"], "company": r["name"] or r["company"], "title": r["title"],
                                 "status": r["status"]}
        return out

    def last_fetch(self) -> dict | None:
        """The last check that read at least one board: at (a datetime), boards, jobs, new, and errors and
        warnings (board -> text). One where every board failed (no network) doesn't count: nothing was checked."""
        row = self.db.execute("SELECT * FROM fetches WHERE boards > 0 ORDER BY at DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"at": datetime.fromisoformat(row["at"]), "boards": row["boards"], "jobs": row["jobs"],
                "new": row["new"], "errors": json.loads(row["errors"]), "warnings": json.loads(row["warnings"])}

    # Whether a board's hosted job pages are up (see sources.Hosted), as last found: (up, when it was checked).

    def hosted_page(self, source: str, board: str) -> tuple[bool, datetime] | None:
        row = self.db.execute("SELECT up, checked_at FROM hosted_pages WHERE source=? AND board=?",
                              (source, board)).fetchone()
        return (bool(row["up"]), datetime.fromisoformat(row["checked_at"])) if row else None

    def save_hosted_page(self, source: str, board: str, up: bool):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO hosted_pages (source, board, up, checked_at) VALUES (?, ?, ?, ?)",
                            (source, board, int(up), _now()))

    # Pay pages (see levels.py), kept on this computer only. An empty body records an empty answer; `gone`, that
    # there's no such page (or robots.txt says not to read it).

    def pay_page(self, url: str) -> tuple[str, datetime, bool] | None:
        row = self.db.execute("SELECT body, fetched_at, gone FROM pay_pages WHERE url=?", (url,)).fetchone()
        return (row["body"], datetime.fromisoformat(row["fetched_at"]), bool(row["gone"])) if row else None

    def save_pay_page(self, url: str, body: str, gone: bool = False):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO pay_pages (url, body, fetched_at, gone) VALUES (?, ?, ?, ?)",
                            (url, body, _now(), int(gone)))

    # Company logos (see logos.py) under logos.key of the company's name: the domain it came from, its content type
    # and its bytes. An empty body records a look that found none.

    def logo(self, company: str) -> tuple[str, str, bytes, datetime] | None:
        row = self.db.execute("SELECT site, ctype, body, fetched_at FROM logos WHERE company=?",
                              (company,)).fetchone()
        if not row:
            return None
        return row["site"], row["ctype"], bytes(row["body"]), datetime.fromisoformat(row["fetched_at"])

    def save_logo(self, company: str, site: str, ctype: str, body: bytes):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO logos (company, site, ctype, body, fetched_at) "
                            "VALUES (?, ?, ?, ?, ?)", (company, site, ctype, body, _now()))

    # Companies whose jobs came in from alerts, `add` or HN posts while their board isn't watched (see suggest.py),
    # one row each under the company's bare name ("umbrella" for "Umbrella LLC"). entry is its board, source:board,
    # once known; an empty one: looked for and none found; NULL: not looked for yet. found_by says how it's known:
    # posting (one of its jobs is on that board, or its HN post links to it) or name (a board found under its name).

    def note_unwatched(self, company: str, name: str, key: str, entry: str | None = None,
                       found_by: str | None = None, seen_at: str | None = None) -> bool:
        """Record a job that came in from a company whose board isn't watched (at seen_at, default now), and its
        board when known. Returns whether the job is newly recorded: one already recorded keeps when it came in."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO unwatched (company, name) VALUES (?, ?)", (company, name))
            self.db.execute("UPDATE unwatched SET name=? WHERE company=?", (name, company))
            new = self.db.execute("INSERT OR IGNORE INTO unwatched_jobs (company, key, seen_at) VALUES (?, ?, ?)",
                                  (company, key, seen_at or _now())).rowcount
        if entry is not None:
            self.set_unwatched_board(company, entry, found_by)
        return bool(new)

    def note_company(self, company: str, name: str):
        """Record a company named by the person (suggestions.watch_always) that no job of theirs has been recorded
        for, so that what's found of its board is kept. It isn't suggested until a job of theirs comes in."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO unwatched (company, name) VALUES (?, ?)", (company, name))

    def set_unwatched_board(self, company: str, entry: str, found_by: str | None = None):
        """Keep what's been found of a company's board: a board one of its jobs is on beats one found under its
        name, and either beats none found. A later find that's no better leaves it as it is."""
        def rank(e, by):
            return -1 if e is None else 0 if not e else 2 if by == "posting" else 1
        row = self.db.execute("SELECT entry, found_by FROM unwatched WHERE company=?", (company,)).fetchone()
        if row and rank(entry, found_by) > rank(row["entry"], row["found_by"]):
            with self.db:
                self.db.execute("UPDATE unwatched SET entry=?, found_by=?, found_at=? WHERE company=?",
                                (entry, found_by if entry else None, _now(), company))

    def unwatched(self, dismissed: bool = False) -> list[dict]:
        """The companies recorded (not the dismissed ones, unless asked): company, name, entry, found_by,
        dismissed_at, and jobs: (job, when it came in) pairs, newest first."""
        rows = [dict(r) for r in self.db.execute("SELECT * FROM unwatched" + ("" if dismissed else
                                                 " WHERE dismissed_at IS NULL"))]
        jobs: dict[str, list[tuple[Job, str]]] = {}
        for r in self.db.execute("SELECT u.company, u.seen_at, j.data FROM unwatched_jobs u JOIN jobs j "
                                 "ON j.key=u.key ORDER BY u.seen_at DESC"):
            jobs.setdefault(r["company"], []).append((Job.from_dict(json.loads(r["data"])), r["seen_at"]))
        return [{**r, "jobs": jobs.get(r["company"], [])} for r in rows]

    def dismiss_unwatched(self, company: str) -> bool:
        """Stop suggesting a company. Returns whether it was there."""
        with self.db:
            return bool(self.db.execute("UPDATE unwatched SET dismissed_at=COALESCE(dismissed_at, ?) "
                                        "WHERE company=?", (_now(), company)).rowcount)

    def set_unwatched_looked(self, company: str):
        """A check looked for which board this company's jobs are on (see suggest.auto_watch), found or not."""
        with self.db:
            self.db.execute("UPDATE unwatched SET looked_at=? WHERE company=?", (_now(), company))

    # How each watched board's reads go, for the check: when it last answered with jobs, how long that read took,
    # how many checks since found it failing or empty, and whether the person has been told it went quiet.

    def board_checks(self) -> dict[str, dict]:
        """{entry: {read_at (ISO, or None), seconds, quiet, told}}."""
        return {r["entry"]: {"read_at": r["read_at"], "seconds": r["seconds"], "quiet": r["quiet"],
                             "told": bool(r["told"])} for r in self.db.execute("SELECT * FROM board_checks")}

    def save_board_read(self, entry: str, seconds: float, jobs: int):
        """A read that came back with jobs clears what's held against the board; an empty one counts against it."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO board_checks (entry) VALUES (?)", (entry,))
            if jobs:
                self.db.execute("UPDATE board_checks SET read_at=?, seconds=?, quiet=0, told=0 WHERE entry=?",
                                (_now(), seconds, entry))
            else:
                self.db.execute("UPDATE board_checks SET seconds=?, quiet=quiet+1 WHERE entry=?", (seconds, entry))

    def save_board_failure(self, entry: str):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO board_checks (entry) VALUES (?)", (entry,))
            self.db.execute("UPDATE board_checks SET quiet=quiet+1 WHERE entry=?", (entry,))

    def set_board_told(self, entry: str):
        with self.db:
            self.db.execute("UPDATE board_checks SET told=1 WHERE entry=?", (entry,))

    # -- compensation details learned from recruiters, per job (see comps.py)

    def set_comp(self, key: str, **fields: str | None):
        """Keep what a recruiter said about pay for a job (base, bonus, equity, signon, asked, offered, note), as
        written ("165-195K", "10% target"), and what the job is for your career: its role (see ROLES) and a
        career_note. None leaves a field as it is; an empty string clears it."""
        if unknown := set(fields) - set(COMP_FIELDS):
            raise ValueError(f"unknown compensation field: {', '.join(sorted(unknown))}")
        if fields.get("role") and fields["role"].strip().lower() not in ROLES:
            raise ValueError(f"role must be {', '.join(ROLES[:-1])} or {ROLES[-1]}")
        key = self.find(key)[0].key
        given = {k: v.strip() or None for k, v in fields.items() if v is not None}
        if given.get("role"):
            given["role"] = given["role"].lower()
        have = self.comp(key) or {}
        merged = {k: given.get(k, have.get(k)) for k in COMP_FIELDS}
        with self.db:
            if any(merged.values()):
                self.db.execute(f"INSERT OR REPLACE INTO comps (key, {', '.join(COMP_FIELDS)}, set_at) "
                                f"VALUES (?, {', '.join('?' * len(COMP_FIELDS))}, ?)",
                                (key, *merged.values(), _now()))
            else:  # nothing left: forget the row
                self.db.execute("DELETE FROM comps WHERE key=?", (key,))

    def comp(self, key: str) -> dict | None:
        """The compensation details kept for a job (full key), or None."""
        r = self.db.execute("SELECT * FROM comps WHERE key=?", (key,)).fetchone()
        return {k: r[k] for k in (*COMP_FIELDS, "set_at")} if r else None

    def comps(self) -> dict[str, dict]:
        """{job key: details} for every job that has some."""
        return {r["key"]: {k: r[k] for k in (*COMP_FIELDS, "set_at")} for r in self.db.execute("SELECT * FROM comps")}

    # -- company health, per company (matched like contacts are: "Acme, Inc." and "acme" are one)

    def set_health(self, company: str, **fields: str | None):
        """Keep what is known of a company's health (see HEALTH_FIELDS), as written. None leaves a field as it is;
        an empty string clears it; as_of is a day (YYYY-MM-DD, today, +N), today when other fields change and it
        isn't given. Clearing the last field forgets the company. Nothing is looked up: the values come
        from the person, or from Claude through the set_company_health tool."""
        if unknown := set(fields) - set(HEALTH_FIELDS):
            raise ValueError(f"unknown company health field: {', '.join(sorted(unknown))}")
        if not (key := company_key(company)):
            raise ValueError("a company's health needs a company name")
        if fields.get("listing") and fields["listing"].strip().lower() not in LISTINGS:
            raise ValueError(f"listing must be {' or '.join(LISTINGS)}")
        if fields.get("kind") and fields["kind"].strip().lower() not in COMPANY_KINDS:
            raise ValueError(f"kind must be {', '.join(COMPANY_KINDS[:-1])} or {COMPANY_KINDS[-1]}")
        given = {k: v.strip() or None for k, v in fields.items() if v is not None}
        if given.get("listing"):
            given["listing"] = given["listing"].lower()
        if given.get("kind"):
            given["kind"] = given["kind"].lower()
        if "as_of" in given:
            given["as_of"] = day(given["as_of"])
        elif any(v for k, v in given.items() if k != "kind"):  # new facts are true as of today unless the person
            # says when they were read (what kind of company it is doesn't age)
            given["as_of"] = date.today().isoformat()
        have = self.health(company) or {}
        merged = {k: given.get(k, have.get(k)) for k in HEALTH_FIELDS}
        with self.db:
            if any(v for k, v in merged.items() if k != "as_of"):
                self.db.execute(f"INSERT OR REPLACE INTO company_health (company, name, "
                                f"{', '.join(HEALTH_FIELDS)}, set_at) VALUES (?, ?, "
                                f"{', '.join('?' * len(HEALTH_FIELDS))}, ?)",
                                (key, have.get("name") or company.strip(), *merged.values(), _now()))
            else:
                self.db.execute("DELETE FROM company_health WHERE company=?", (key,))

    def health(self, company: str) -> dict | None:
        """What is kept of this company's health (any spelling of its name), or None."""
        r = self.db.execute("SELECT * FROM company_health WHERE company=?", (company_key(company),)).fetchone()
        return {k: r[k] for k in ("name", *HEALTH_FIELDS)} if r else None

    def healths(self) -> dict[str, dict]:
        """{company key: health} for every company with some (company_key spells the key)."""
        return {r["company"]: {k: r[k] for k in ("name", *HEALTH_FIELDS)}
                for r in self.db.execute("SELECT * FROM company_health")}

    # -- the morning digest (see morning.py): one row a local day, with the matches it listed (none: a quiet day)

    def save_morning_digest(self, day: str, items: list[dict], total: int | None = None, at: datetime | None = None):
        """The matches a digest listed, and how many there were in all (`total`, default the ones listed)."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO morning_digests (day, at, items, total) VALUES (?, ?, ?, ?)",
                            (day, (at or datetime.now(UTC)).isoformat(), json.dumps(items),
                             len(items) if total is None else total))

    def morning_digest(self, day: str | None = None) -> dict | None:
        """The digest of that local day, else the latest one: {day, at (a datetime), items, total}."""
        row = self.db.execute("SELECT * FROM morning_digests WHERE day=?", (day,)).fetchone() if day else \
            self.db.execute("SELECT * FROM morning_digests ORDER BY day DESC LIMIT 1").fetchone()
        return {"day": row["day"], "at": datetime.fromisoformat(row["at"]), "items": json.loads(row["items"]),
                "total": row["total"]} if row else None

    # -- referral feedback: whom to use and whom not to, per person (contacts.person_key: profile slug, else name)

    def rate_contact(self, person: str, verdict: str, note: str = ""):
        """Use or skip a person when suggesting who to ask for a referral, with a short note ("doesn't check
        LinkedIn; reach on WhatsApp"). Setting it again replaces both."""
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO referral_feedback (person, verdict, note, set_at) "
                            "VALUES (?, ?, ?, ?)", (person, verdict, note.strip(), _now()))

    def clear_contact(self, person: str) -> bool:
        """Forget what was said about a person. Returns whether there was anything."""
        with self.db:
            return bool(self.db.execute("DELETE FROM referral_feedback WHERE person=?", (person,)).rowcount)

    def contact_feedback(self) -> dict[str, dict]:
        """{person: {verdict, note, set_at}} for everyone rated."""
        return {r["person"]: {"verdict": r["verdict"], "note": r["note"], "set_at": r["set_at"]}
                for r in self.db.execute("SELECT * FROM referral_feedback")}

    def _backfill_unwatched(self):
        """Fill in the companies from jobs recorded before there were suggestions: those from job-alert emails
        (via) or added by hand. Whether a company is watched is told when listing them."""
        for r in self.db.execute("SELECT key, source, company, data, first_seen FROM jobs "
                                 "WHERE via IS NOT NULL OR source=?", (MANUAL,)).fetchall():
            name = Job.from_dict(json.loads(r["data"])).display_company
            if not (company := linkedin._bare(name)):
                continue
            self.db.execute("INSERT OR IGNORE INTO unwatched (company, name) VALUES (?, ?)", (company, name))
            self.db.execute("INSERT OR IGNORE INTO unwatched_jobs (company, key, seen_at) VALUES (?, ?, ?)",
                            (company, r["key"], r["first_seen"]))
            if r["source"] != MANUAL:
                self.db.execute("UPDATE unwatched SET entry=?, found_by='posting', found_at=? WHERE company=? AND "
                                "(entry IS NULL OR found_by IS NOT 'posting')",
                                (f"{r['source']}:{r['company']}", r["first_seen"], company))
