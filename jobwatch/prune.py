"""`jobwatch prune`: shrink the state file by dropping what old, never-acted-on jobs cost.

Most of a big state file is postings that never matched a filter and have sat as "new" for weeks. A job is "new"
when its key isn't in the file, so a posting still on its board can't just be deleted (the next check would report
it as new again). Two cases:

- gone from its board (closed) for a while: the row is deleted.
- still posted, or closed only lately (a board's blip may reopen it): the row stays, with the posting's text dropped
  (and marked `slim`, so a check keeps it dropped).

"Old" is posted more than DAYS ago (first seen that long ago when there's no posting date): a first check of a board
records its whole backlog at once, so first_seen alone says little.

Never touched: a job with any status but "new", from an alert or added by hand (source manual), with a note, a
next step, a follow-up, a round or a duplicate link, with a fit score, a drafted answer, pay notes, files kept in its
package, or one that a suggestion for an unwatched board points to.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .package import _safe
from .store import MANUAL, Store, slimmed

DAYS = 30  # a job first seen longer ago than this, and (if closed) closed this long ago, is old
BATCH = 2000

# Jobs with one of these never go: the ones a person acted on or kept something about.
_PROTECTED = f"""
    status != 'new' OR source = '{MANUAL}'
    OR COALESCE(note, '') != '' OR next_step IS NOT NULL OR follow_up IS NOT NULL OR round IS NOT NULL
    OR via IS NOT NULL OR applied_at IS NOT NULL OR duplicate_of IS NOT NULL
    OR key IN (SELECT duplicate_of FROM jobs WHERE duplicate_of IS NOT NULL)
    OR key IN (SELECT key FROM scores) OR key IN (SELECT key FROM drafts) OR key IN (SELECT key FROM comps)
    OR key IN (SELECT key FROM unwatched_jobs)
"""


@dataclass
class Plan:
    delete: list[str]
    slim: list[str]
    bytes_delete: int = 0
    bytes_slim: int = 0  # what dropping the text frees (the rows stay)
    kept: dict[str, int] = field(default_factory=dict)  # old new jobs left alone, by why

    @property
    def bytes(self) -> int:
        return self.bytes_delete + self.bytes_slim


def _iso(days: int, now: datetime | None = None) -> str:
    return ((now or datetime.now(UTC)) - timedelta(days=days)).isoformat(timespec="microseconds")


def _in_packages(store: Store, keys: list[str]) -> set[str]:
    """Of these jobs, the ones with files kept in their package (what was sent with an application)."""
    if not store.packages.is_dir():
        return set()
    have = {p.name for p in store.packages.iterdir()}
    return {k for k in keys if _safe(k) in have}


def plan(store: Store, days: int = DAYS, now: datetime | None = None) -> Plan:
    """What `prune` would do, changing nothing."""
    cutoff = _iso(days, now)
    # Old: posted before the cutoff, or (no posting date) first seen before it.
    old = ("(json_extract(data, '$.posted') < :c OR (json_extract(data, '$.posted') IS NULL AND first_seen < :c))")
    db = store.db
    kept = {"acted on or noted": db.execute(f"SELECT count(*) FROM jobs WHERE {old} AND ({_PROTECTED})",
                                            {"c": cutoff}).fetchone()[0]}
    rows = db.execute(f"SELECT key, closed, length(data) AS size, length(json_extract(data, '$.description')) AS text "
                      f"FROM jobs WHERE {old} AND NOT ({_PROTECTED}) AND slim IS NULL",
                      {"c": cutoff}).fetchall()
    packaged = _in_packages(store, [r["key"] for r in rows])
    out = Plan([], [])
    for r in rows:
        if r["key"] in packaged:
            kept["with a package"] = kept.get("with a package", 0) + 1
        elif r["closed"] and r["closed"] < cutoff:  # gone for a while: a board's blip would have healed by now
            out.delete.append(r["key"])
            out.bytes_delete += r["size"]
        else:
            out.slim.append(r["key"])
            out.bytes_slim += r["text"] or 0
    out.kept = kept
    return out


def apply(store: Store, p: Plan) -> None:
    """Do the plan, then give the freed pages back to the disk."""
    db = store.db
    for i in range(0, len(p.delete), BATCH):
        chunk = [(k,) for k in p.delete[i:i + BATCH]]
        with db:
            db.executemany("DELETE FROM jobs WHERE key=? AND status='new'", chunk)
            db.executemany("DELETE FROM posting_checked WHERE key=?", chunk)
            db.executemany("DELETE FROM backfill_tried WHERE key=?", chunk)
            db.executemany("DELETE FROM list_unplaced WHERE key=?", chunk)
    for i in range(0, len(p.slim), BATCH):
        keys = p.slim[i:i + BATCH]
        with db:
            for k in keys:
                row = db.execute("SELECT data FROM jobs WHERE key=? AND status='new'", (k,)).fetchone()
                if row:
                    db.execute("UPDATE jobs SET data=?, slim='1' WHERE key=?",
                               (json.dumps(slimmed(json.loads(row["data"]))), k))
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.execute("VACUUM")


def copy_before(store: Store) -> Path:
    """A whole copy of the state file, made with SQLite's own backup (safe while another process writes), next to
    it; returns where."""
    dest = store.path.with_name(store.path.name + ".before-prune")
    with sqlite3.connect(dest) as out:
        store.db.backup(out)
    out.close()
    return dest
