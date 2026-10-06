"""What has been seen, shown, queued, applied to or skipped, how each application is going, and fit scores:
one SQLite file."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import Job
from .package import Package
from .sources import candidate_home
from .text import parse_salary

# queued: to apply to next. After applying: applied, then screening, interviewing, offer, or it ends.
STAGES = ("applied", "screening", "interviewing", "offer", "rejected", "withdrawn")
ENDED = ("rejected", "withdrawn")
STATUSES = ("new", "shown", "queued", *STAGES, "skipped")
MANUAL = "manual"  # the source of applications added by hand (found elsewhere, not on a watched board)

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
    follow_up TEXT
);
CREATE INDEX IF NOT EXISTS jobs_board ON jobs (source, company);
CREATE TABLE IF NOT EXISTS scores (
    key TEXT NOT NULL,
    resume TEXT NOT NULL,
    result TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (key, resume)
);
"""


# Columns added after the first release, and how to fill them in an older state file.
_ADDED = {"applied_at": "UPDATE jobs SET applied_at=substr(status_at, 1, 10) WHERE status='applied'",
          "next_step": None, "follow_up": None}


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
    def __init__(self, path: Path | str):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.packages = path.parent / "packages"  # what was sent with each application (see package.py)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        with self.db:
            for column, backfill in _ADDED.items():
                if column not in have:
                    self.db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
                    if backfill:
                        self.db.execute(backfill)

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

    def board_jobs(self, source: str, company: str) -> dict[str, Job]:
        """Every job ever seen on one board, open or closed, by key."""
        rows = self.db.execute("SELECT key, data FROM jobs WHERE source=? AND company=?", (source, company))
        return {r["key"]: Job.from_dict(json.loads(r["data"])) for r in rows}

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

    def applications(self) -> list[tuple[Job, dict]]:
        """Everything applied to. Open applications come first, those with the soonest follow-up day at the top,
        then the most recent; rejected and withdrawn ones last."""
        rows = self.jobs(STAGES, include_closed=True)
        rows.sort(key=lambda r: r[1]["applied_at"] or "", reverse=True)
        rows.sort(key=lambda r: (r[1]["status"] in ENDED, r[1]["follow_up"] is None, r[1]["follow_up"] or ""))
        return rows

    def find(self, key: str) -> tuple[Job, dict]:
        """A job by its full key, or by a unique ending of it (the posting id is enough)."""
        rows = self.db.execute("SELECT * FROM jobs WHERE key=? OR key LIKE ?", (key, f"%{key}")).fetchall()
        exact = [r for r in rows if r["key"] == key]
        rows = exact or rows
        if len(rows) != 1:
            raise KeyError(f"no job matches {key!r}" if not rows else
                           f"{key!r} matches {len(rows)} jobs: {', '.join(r['key'] for r in rows[:5])}")
        r = rows[0]
        return Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}

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

    def set_description(self, key: str, text: str):
        """Give an application added by hand the posting's text, pasted (found later, or from a copy once the
        posting is gone), so it can be scored and prepped. The pay is read from it if none is set, and the
        posting kept with the application is replaced: what was kept had no text to keep."""
        job, rec = self.find(key)
        if job.source != MANUAL:
            raise ValueError(f"{job.key} comes from its board, which sets its text")
        job.description = text.strip()
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
        row = self.db.execute("SELECT result FROM scores WHERE key=? AND resume=?", (key, resume)).fetchone()
        return json.loads(row["result"]) if row else None

    def save_score(self, key: str, resume: str, result: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                            (key, resume, json.dumps(result), _now()))
