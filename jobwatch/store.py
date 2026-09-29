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
        """Move jobs to a status. Moving to an application stage records the day applied, once (`on`, default
        today), and saves the posting as it reads then; moving back before applying clears the day."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        applied = day(on) or date.today().isoformat()
        with self.db:
            for key in keys:
                self.db.execute("UPDATE jobs SET status=?, status_at=?, note=COALESCE(?, note), applied_at="
                                "CASE WHEN ? THEN COALESCE(applied_at, ?) END WHERE key=?",
                                (status, _now(), note, status in STAGES, applied, key))
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

    def add_note(self, key: str, text: str):
        """Add a dated line to the note, keeping what's there (the recruiter's name, what was said before)."""
        text = text.strip()
        if not text:
            return
        _, rec = self.find(key)
        line = f"{date.today().isoformat()}: {text}"
        self.track(key, note=f"{rec['note']} {line}" if rec.get("note") else line)

    def add(self, company: str, title: str, url: str = "", status: str = "applied", applied: str | None = None,
            location: str = "", note: str | None = None, next_step: str | None = None,
            follow_up: str | None = None) -> Job:
        """Track an application found somewhere jobwatch doesn't watch (a referral, a recruiter, LinkedIn...)."""
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
                  locations=[location.strip()] if location.strip() else [])
        now = _now()
        with self.db:
            self.db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen) VALUES "
                            "(?, ?, ?, ?, ?, ?)", (job.key, MANUAL, board, json.dumps(job.to_dict()), now, now))
        self.set_status([job.key], status, note, on=applied)
        self.track(job.key, next_step=next_step, follow_up=follow_up)
        return job

    def score(self, key: str, resume: str) -> dict | None:
        row = self.db.execute("SELECT result FROM scores WHERE key=? AND resume=?", (key, resume)).fetchone()
        return json.loads(row["result"]) if row else None

    def save_score(self, key: str, resume: str, result: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                            (key, resume, json.dumps(result), _now()))
