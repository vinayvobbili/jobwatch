"""What has been seen, shown, queued, applied to or skipped, how each application is going, and fit scores:
one SQLite file."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import linkedin
from .contacts import company_key
from .models import Job
from .package import Package
from .score import resume_family, unjudged
from .sources import SOURCES, candidate_home
from .text import parse_salary

# queued: to apply to next. After applying: applied, then screening, interviewing, offer, or it ends.
STAGES = ("applied", "screening", "interviewing", "offer", "rejected", "withdrawn")
ENDED = ("rejected", "withdrawn")
STATUSES = ("new", "shown", "queued", *STAGES, "skipped")
VERDICTS = ("use", "skip")  # what can be said of a person to ask for a referral
# What a recruiter said about pay, then what the job is for your career: its role (ROLES) and a few words on why.
COMP_FIELDS = ("base", "bonus", "equity", "signon", "asked", "offered", "note", "role", "career_note")
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
# Posts from a thread of many companies' posts (HN's Who is hiring) aren't fit-scored (see watch.scorable): a
# score saved for one before that is left out when scores are read (it stays in the file, unused).
_SCORED = "key NOT IN (SELECT key FROM jobs WHERE source IN ({}))".format(
    ", ".join(f"'{s.name}'" for s in SOURCES.values() if s.many_companies) or "''")

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
    dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS unwatched_jobs (
    company TEXT NOT NULL,
    key TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (company, key)
);
CREATE TABLE IF NOT EXISTS drafts (
    key TEXT NOT NULL,
    inputs TEXT NOT NULL,
    reply TEXT NOT NULL,
    made_at TEXT NOT NULL,
    PRIMARY KEY (key, inputs)
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
    notable INTEGER NOT NULL DEFAULT 0
);
"""
FETCHES_KEPT = 200  # the checks for new jobs remembered (when, and what they found)
ACTIVITY_KEPT = 1000  # the things done in the background remembered, of each kind (see Store.log)
BUSY = 30  # seconds to wait for another thread or process writing the state file, instead of "database is locked"


# Columns added after the first release, and how to fill them in an older state file.
_ADDED = {"applied_at": "UPDATE jobs SET applied_at=substr(status_at, 1, 10) WHERE status='applied'",
          "next_step": None, "follow_up": None, "via": None, "duplicate_of": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")  # orders actions within a second


def day(value: str | date | None, today: date | None = None) -> str | None:
    """A calendar day as YYYY-MM-DD, from "2026-10-05", "today", "tomorrow" or "+7" (days from today).
    Empty means none."""
    if value is None or isinstance(value, date):
        return value.isoformat() if value else None
    v, today = value.strip().lower(), today or date.today()
    if not v:
        return None
    if v in ("today", "tomorrow"):
        return (today + timedelta(days=v == "tomorrow")).isoformat()
    if m := re.fullmatch(r"\+(\d+)d?", v):
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{value!r} isn't a date: use YYYY-MM-DD, today, tomorrow or +N days") from None


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


class Store:
    def __init__(self, path: Path | str, read_only: bool = False):
        """read_only opens an existing state file without changing it, not even to add a newer version's columns
        (`jobwatch dupes` reads with it)."""
        path = Path(path).expanduser()
        self.packages = path.parent / "packages"  # what was sent with each application (see package.py)
        if read_only:
            self.db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            self.db.row_factory = sqlite3.Row
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=BUSY)
        self.db.row_factory = sqlite3.Row
        # Write-ahead logging: a long read (the page drawing Today) and a write (a score, a logo) don't wait on
        # each other. Kept in the file, so this only changes it the first time.
        try:
            if self.db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:  # another connection is switching it, or using it: a later open will
            pass
        older = not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='unwatched_jobs'").fetchone()
        self.db.executescript(_SCHEMA)
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
            for table, column in (("comps", "role"), ("comps", "career_note"), ("company_health", "kind")):
                if column not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    try:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                    except sqlite3.OperationalError as e:  # another connection added it just now
                        if "duplicate column" not in str(e):
                            raise
            if older:  # a state file from before suggestions: what alerts and `add` brought in so far counts
                self._backfill_unwatched()

    def close(self):
        self.db.close()

    def sync(self, source: str, company: str, jobs: list[Job]) -> list[str]:
        """Record one board's current roles; returns the keys seen for the first time.

        Roles that have disappeared from the board are marked closed (and reopened if they come back)."""
        now, new = _now(), []
        with self.db:
            known = {r["key"] for r in self.db.execute("SELECT key FROM jobs WHERE source=? AND company=?",
                                                        (source, company))}
            for job in jobs:
                data = json.dumps(job.to_dict())
                if job.key in known:
                    self.db.execute("UPDATE jobs SET data=?, last_seen=?, closed=NULL WHERE key=?",
                                    (data, now, job.key))
                else:
                    self.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen) "
                                    "VALUES (?, ?, ?, ?, ?, ?)", (job.key, source, company, data, now, now))
                    new.append(job.key)
            gone = known - {j.key for j in jobs}
            self.db.executemany("UPDATE jobs SET closed=? WHERE key=? AND closed IS NULL", [(now, k) for k in gone])
        return new

    def keep(self, job: Job) -> bool:
        """Record one job read from its link, leaving the rest of its board alone (it may not be watched).
        Returns whether it's new."""
        now = _now()
        with self.db:
            new = self.db.execute("INSERT OR IGNORE INTO jobs (key, source, company, data, first_seen, last_seen) "
                                  "VALUES (?, ?, ?, ?, ?, ?)", (job.key, job.source, job.company,
                                                                json.dumps(job.to_dict()), now, now)).rowcount
            if not new:
                self.db.execute("UPDATE jobs SET data=?, last_seen=?, closed=NULL WHERE key=?",
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

    def set_duplicate(self, key: str, other: str):
        """Record that a job is the same opening as another one already acted on (see dupes.py), by its key."""
        with self.db:
            self.db.execute("UPDATE jobs SET duplicate_of=? WHERE key=?", (other or None, key))

    def board_jobs(self, source: str, company: str) -> dict[str, Job]:
        """Every job ever seen on one board, open or closed, by key."""
        rows = self.db.execute("SELECT key, data FROM jobs WHERE source=? AND company=?", (source, company))
        return {r["key"]: Job.from_dict(json.loads(r["data"])) for r in rows}

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
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if not include_closed:
            sql += " AND closed IS NULL"
        rows = self.db.execute(sql + " ORDER BY first_seen DESC", args).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

    def search(self, text: str) -> list[tuple[Job, dict]]:
        """Jobs at any status, closed too, whose note, next step, via, title or company contains the text (any
        case), newest first: "which application did the recruiter call about?". instr, not LIKE: the text is
        taken literally ("$101/hr", "100%")."""
        text = text.strip().lower()
        if not text:
            return []
        fields = ("note", "next_step", "via", "json_extract(data, '$.title')", "company",
                  "json_extract(data, '$.company_name')")
        rows = self.db.execute(f"SELECT * FROM jobs WHERE {' OR '.join(f'instr(lower({f}), ?)' for f in fields)} "
                               "ORDER BY first_seen DESC", [text] * len(fields)).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

    def company_counts(self) -> list[dict]:
        """How many jobs each company has, by status and whether closed, without reading any posting: source,
        company (the board), name (what its jobs call it), status, closed (bool) and n."""
        return [dict(r) for r in self.db.execute(
            "SELECT source, company, json_extract(data, '$.company_name') AS name, status, closed IS NOT NULL AS "
            "closed, COUNT(*) AS n FROM jobs GROUP BY source, company, name, status, closed IS NOT NULL")]

    def applications(self) -> list[tuple[Job, dict]]:
        """Everything applied to. Open applications come first, those with the soonest follow-up day at the top,
        then the most recent; rejected and withdrawn ones last."""
        rows = self.jobs(STAGES, include_closed=True)
        rows.sort(key=lambda r: r[1]["applied_at"] or "", reverse=True)
        rows.sort(key=lambda r: (r[1]["status"] in ENDED, r[1]["follow_up"] is None, r[1]["follow_up"] or ""))
        return rows

    def applied_on(self, on: str | date) -> int:
        """How many applications went out on this day, whatever stage they're at now. applied_at is the local
        calendar day (see set_status), so "today" is the day on this computer's clock, not UTC's."""
        return self.db.execute(f"SELECT COUNT(*) FROM jobs WHERE applied_at=? AND status IN "
                               f"({','.join('?' * len(STAGES))})", (day(on), *STAGES)).fetchone()[0]

    def find(self, key: str) -> tuple[Job, dict]:
        """A job by its full key, by a unique ending of it (the posting id is enough), or else by its company's
        name or part of it, in any case, when that names one job: the one queued or applied to there, or the only
        one there at all."""
        rows = self.db.execute("SELECT * FROM jobs WHERE key=? OR key LIKE ?", (key, f"%{key}")).fetchall()
        exact = [r for r in rows if r["key"] == key]
        rows = exact or rows
        if not rows and len(rows := self._at_company(key)) > 1:
            listed = "\n".join(f"  {r['key']}  {self._label(r)}" for r in rows[:10])
            more = f"\n  and {len(rows) - 10} more" if len(rows) > 10 else ""
            raise KeyError(f"{key!r} matches {len(rows)} jobs; give the key of one:\n{listed}{more}")
        if len(rows) != 1:
            raise KeyError(f"no job matches {key!r}" if not rows else
                           f"{key!r} matches {len(rows)} jobs: {', '.join(r['key'] for r in rows[:5])}")
        r = rows[0]
        return Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}

    def _at_company(self, name: str) -> list[sqlite3.Row]:
        """Jobs whose company name or board contains `name` (any case): the ones queued or applied to, if any."""
        name = name.strip().lower()
        if not name:
            return []
        rows = self.db.execute("SELECT * FROM jobs WHERE instr(lower(company), ?) "
                               "OR instr(lower(json_extract(data, '$.company_name')), ?) ORDER BY key",
                               (name, name)).fetchall()
        return [r for r in rows if r["status"] in ("queued", *STAGES)] or rows

    @staticmethod
    def _label(row: sqlite3.Row) -> str:
        job = Job.from_dict(json.loads(row["data"]))
        return f"{job.display_company}: {job.title} ({row['status']})"

    def set_status(self, keys: list[str], status: str, note: str | None = None, on: str | None = None):
        """Move jobs to a status. Moving to an application stage records the day applied: `on` when given (it
        corrects an earlier day), else today unless a day is already recorded. It also saves the posting as it
        reads then; moving back before applying clears the day."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        with self.db:
            for key in keys:
                self.db.execute("UPDATE jobs SET status=?, status_at=?, note=COALESCE(?, note), applied_at="
                                "CASE WHEN ? THEN COALESCE(?, applied_at, ?) END WHERE key=?",
                                (status, _now(), note, status in STAGES, day(on), date.today().isoformat(), key))
        if status in STAGES:
            for key in keys:
                job, _ = self.find(key)
                self.package(job.key).keep_posting(job)

    def package(self, key: str) -> Package:
        """What was sent with the application for this job (key or posting id)."""
        return Package(self.packages, self.find(key)[0].key)

    def track(self, key: str, *, note: str | None = None, next_step: str | None = None,
              follow_up: str | None = None, applied: str | None = None):
        """Update an application's note, next step, follow-up day or day applied. None leaves a field as it is;
        an empty string clears it."""
        fields = {"note": note, "next_step": next_step}
        fields = {k: v.strip() or None for k, v in fields.items() if v is not None}
        if follow_up is not None:
            fields["follow_up"] = day(follow_up)
        if applied is not None:
            fields["applied_at"] = day(applied)
        if fields:
            with self.db:
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
                job.salary_min, job.salary_max, job.currency = posting.salary_min, posting.salary_max, posting.currency
            job.locations = job.locations or list(posting.locations)
            job.remote = posting.remote if job.remote is None else job.remote
            job.department = job.department or posting.department
            job.posted = job.posted or posting.posted
        if job.salary_min is None and (pay := parse_salary(job.description)):
            job.salary_min, job.salary_max, job.currency = *pay, "USD"
        with self.db:
            self.db.execute("UPDATE jobs SET data=? WHERE key=?", (json.dumps(job.to_dict()), job.key))
        if rec["status"] in STAGES:
            self.package(job.key).keep_posting(job, again=True)

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
        job, rec = self.find(key)
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
        if job.description and (pay := parse_salary(job.description)):
            job.salary_min, job.salary_max, job.currency = *pay, "USD"
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
        row = self.db.execute(f"SELECT result FROM scores WHERE key=? AND resume=? AND {_SCORED}",
                              (key, resume)).fetchone()
        return json.loads(row["result"]) if row else None

    def scores(self, resume: str) -> dict[str, dict]:
        """Every stored fit score for this resume, by job key: one query for a whole list of jobs."""
        return {r["key"]: json.loads(r["result"])
                for r in self.db.execute(f"SELECT key, result FROM scores WHERE resume=? AND {_SCORED}", (resume,))}

    def stale_scores(self, resume: str) -> dict[str, dict]:
        """Per job key, the newest fit score made for the same resume content and prompts as `resume` by another
        scorer (see score.resume_family), marked "stale": true. For showing something until the job is scored
        afresh; never in place of a current score."""
        family = resume_family(resume)
        out = {}
        for r in self.db.execute(f"SELECT key, resume, result FROM scores WHERE resume!=? AND resume LIKE ? "
                                 f"AND {_SCORED} ORDER BY scored_at", (resume, ":".join(family.split(":")[:2]) + "%")):
            if resume_family(r["resume"]) == family:
                out[r["key"]] = {**json.loads(r["result"]), "stale": True}
        return out

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

    def save_score_failure(self, key: str, resume: str, model: str, error: str):
        """A job that failed to score for this resume (and prompts) with this model, and why, so a restart doesn't
        try it again at once (see score_failures)."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO score_failures (key, resume, model, error, failed_at) "
                            "VALUES (?, ?, ?, ?, ?)", (key, resume, model, error, _now()))

    def score_failures(self, resume: str, model: str, within: timedelta) -> dict[str, str]:
        """{job key: error} for the jobs that failed to score for this resume with this model in the last `within`.
        A new resume, edited prompts, another model or the time passing leaves a job out: it's tried again."""
        since = (datetime.now(timezone.utc) - within).isoformat(timespec="microseconds")
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

    def score_usage(self, backend: str, day: date | None = None) -> int:
        """Jobs scored with this backend on this local day (default today)."""
        row = self.db.execute("SELECT jobs FROM score_usage WHERE day=? AND backend=?",
                              ((day or date.today()).isoformat(), backend)).fetchone()
        return row["jobs"] if row else 0

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
        with self.db:
            self.db.execute("UPDATE jobs SET data=? WHERE key=?", (json.dumps(job.to_dict()), job.key))

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

    def log(self, kind: str, text: str, ok: bool = True, detail: list[str] | tuple[str, ...] = (), by: str = "",
            notable: bool = False):
        with self.db:
            self.db.execute("INSERT INTO activity (at, kind, text, ok, detail, by, notable) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (_now(), kind, text, int(ok), json.dumps(list(detail)), by, int(notable)))
            # kept per kind, so hundreds of jobs scored don't push the board checks and emails out
            self.db.execute("DELETE FROM activity WHERE kind=? AND rowid NOT IN (SELECT rowid FROM activity "
                            "WHERE kind=? ORDER BY at DESC LIMIT ?)", (kind, kind, ACTIVITY_KEPT))

    def activity(self, limit: int = 200, kind: str = "", since: str = "", notable: bool = False) -> list[dict]:
        """The newest first: at (ISO), kind, text, ok, detail (lines), by and notable. kind: only that kind, or
        those kinds ("score,pay"); since: only ones after that time (ISO); notable: only the ones worth a look."""
        kinds = [k for k in kind.split(",") if k]
        among = ",".join("?" * len(kinds)) or "NULL"
        rows = self.db.execute(f"SELECT * FROM activity WHERE (? OR kind IN ({among})) AND at>? AND notable>=? "
                               "ORDER BY at DESC LIMIT ?", (not kinds, *kinds, since, int(notable), limit))
        return [{"at": r["at"], "kind": r["kind"], "text": r["text"], "ok": bool(r["ok"]),
                 "detail": json.loads(r["detail"]), "by": r["by"], "notable": bool(r["notable"])} for r in rows]

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
