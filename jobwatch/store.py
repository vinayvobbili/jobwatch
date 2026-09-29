"""What has been seen, shown, queued, applied to or skipped, and fit scores: one SQLite file."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

STATUSES = ("new", "shown", "queued", "applied", "skipped")  # queued: to apply to next

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
    note TEXT
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")  # orders actions within a second


class Store:
    def __init__(self, path: Path | str):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

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
        """(job, record) pairs; the record has status, first_seen, closed and note."""
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if not include_closed:
            sql += " AND closed IS NULL"
        rows = self.db.execute(sql + " ORDER BY first_seen DESC", args).fetchall()
        return [(Job.from_dict(json.loads(r["data"])), {k: r[k] for k in r.keys() if k != "data"}) for r in rows]

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

    def set_status(self, keys: list[str], status: str, note: str | None = None):
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        with self.db:
            for key in keys:
                if note is None:
                    self.db.execute("UPDATE jobs SET status=?, status_at=? WHERE key=?", (status, _now(), key))
                else:
                    self.db.execute("UPDATE jobs SET status=?, status_at=?, note=? WHERE key=?",
                                    (status, _now(), note, key))

    def score(self, key: str, resume: str) -> dict | None:
        row = self.db.execute("SELECT result FROM scores WHERE key=? AND resume=?", (key, resume)).fetchone()
        return json.loads(row["result"]) if row else None

    def save_score(self, key: str, resume: str, result: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                            (key, resume, json.dumps(result), _now()))
