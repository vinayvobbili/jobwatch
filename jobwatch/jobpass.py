"""The filter pass: every open job Today could list (status new or shown), judged once by the filters.

Judging the whole table (63,000 jobs and their postings' text) takes seconds, and Today, the page's "hidden" count,
the scorer's line, Skills and Referrals all start from it. Each used to run it on its own, on every request. Here it
runs once and is remembered until something changes: a write to the state file (Store.stamp: a new job, a status, a
score), the watchlist file or the filters in it, the resume, or the hour (a job's age in days turns over then).

What's kept per job is small (a Verdict: why it was rejected, and what listing it needs), not the posting: the few
jobs a caller wants in full are read by key (Store.rows).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import NamedTuple

from .config import Config
from .filters import excluded_company, rejection
from .models import Job
from .store import Store

STATUSES = ("new", "shown")  # what Today lists, see watch.build_digest


class Verdict(NamedTuple):
    key: str
    status: str
    source: str
    first_seen: str
    age_days: int | None
    kind: str | None       # the filter that rejected it (filters.KINDS), None: it passes
    why: str | None        # and why, in words: "title matches 'manager'", "posted 45 days ago"
    company: str | None    # for kind "company": the exclude_companies entry that matched
    alone: bool            # for kind "company": nothing else rejects it, so dropping that entry brings it back


class Pass(NamedTuple):
    verdicts: list[Verdict]   # newest first, as Store.iter_jobs lists them

    def in_status(self, statuses: Iterable[str]) -> list[Verdict]:
        """The verdicts of jobs with one of these statuses."""
        statuses = set(statuses)
        return [v for v in self.verdicts if v.status in statuses]


def judge_rows(cfg: Config, fits: dict[str, dict], rows: Iterable[tuple[Job, dict]]) -> list[Verdict]:
    """Run every filter over these jobs, one at a time (the postings are never all in memory)."""
    out = []
    for job, rec in rows:
        f, fit = cfg.filters_for(job), fits.get(job.key)
        r = rejection(job, f, fit)
        name = alone = None
        if r and r[0] == "company":
            name = excluded_company(job, f.exclude_companies)
            alone = not rejection(job, replace(f, exclude_companies=[]), fit)
        out.append(Verdict(job.key, rec["status"], job.source, rec["first_seen"], job.age_days(),
                           r[0] if r else None, r[1] if r else None, name, bool(alone)))
    return out


def judge(cfg: Config, store: Store, fits: dict[str, dict]) -> Pass:
    """Every open new or shown job judged (closed ones are no part of Today)."""
    return Pass(judge_rows(cfg, fits, store.iter_jobs(STATUSES)))


def config_stamp(cfg: Config) -> tuple:
    """What in the watchlist decides a job's verdict: the file's time and size, and the filters as loaded (a
    caller that built a Config in memory changes them without touching the file)."""
    try:
        st = cfg.path.stat()
        file = (st.st_mtime_ns, st.st_size)
    except OSError:
        file = None
    shape = repr((cfg.filters, sorted(cfg.board_filters.items(), key=lambda kv: kv[0]), cfg.tracks))
    return file, hashlib.sha256(shape.encode()).hexdigest()


_kept: dict[tuple, tuple[tuple, object]] = {}   # (state file, name, variant) -> (what it was made from, the work)
_guard = threading.Lock()
_making: dict[tuple, threading.Lock] = {}


def remembered(store: Store, name: str, made_from: tuple, make: Callable[[], object], variant: tuple = ()):
    """make()'s result, made again only when the state file was written or `made_from` changed since. Callers at
    the same moment (two tabs loading together) wait for one run instead of each making it. The stamp is read
    before the work starts, so a write during it leaves the result marked older than the file and it is made
    again next time, never served stale."""
    where = (str(store.path), name, variant)
    hour = datetime.now(UTC).strftime("%Y%m%d%H")  # a job's age in days turns over on the hour, near enough
    stamp = (store.stamp(), made_from, hour)
    with _guard:
        if (got := _kept.get(where)) and got[0] == stamp:
            return got[1]
        lock = _making.setdefault(where, threading.Lock())
    with lock:
        with _guard:
            if (got := _kept.get(where)) and got[0] == stamp:
                return got[1]
        value = make()
        with _guard:
            _kept[where] = (stamp, value)
        return value


def forget():
    """Drop everything remembered (for tests: a state file that is deleted and made again)."""
    with _guard:
        _kept.clear()


def acted_index(store: Store):
    """dupes.Index over the jobs acted on, built once while the state file stays as it is: the queue, Today, a
    company's page and the scorer's line each built their own (every acted-on job read in full, 0.3 s)."""
    from .dupes import Index
    return remembered(store, "acted", (), lambda: Index(store))


def judged(cfg: Config, store: Store, rid: str | None, fits: Callable[[], dict[str, dict]]) -> Pass:
    """The pass over the store's new and shown jobs, scored by the resume `rid` (None: no resume)."""
    return remembered(store, "pass", (config_stamp(cfg), rid), lambda: judge(cfg, store, fits() if rid else {}))
