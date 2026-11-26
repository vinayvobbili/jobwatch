"""Whether a fit score is stale is a decision, never a side effect of a new resume.

A score is kept under the resume id it was made with (score.resume_id: the resume's name and content, the scorer
and any edited prompts). A rebuilt resume gives every job a new id, but no score goes missing and none is asked for
again: each job keeps showing its newest score, flagged "stale" while that score was made under an older resume
(the scorer part of the id doesn't count: a shortlist-ai upgrade changes nothing here). Scoring again happens only
for what you decide:

  mark stale   the scores you pick (all, those at or above a fit, the queued ones) go in the scorer's line, to be
               scored again by the page's background scoring, the Score button or `jobwatch score --rescore`;
  keep         the current resume becomes the baseline: the scores made under older ones count as current, with
               no new score paid for.

Each decision is logged (`jobwatch scores --log`). The tables here hold the marks, what was kept and that log; the
scores themselves stay as they were, so nothing is lost by either choice."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from .score import resume_family, resume_id

if TYPE_CHECKING:
    from .config import Config
    from .store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS score_stale (
    key TEXT PRIMARY KEY,
    marked_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_kept (
    family TEXT PRIMARY KEY,
    adopted TEXT NOT NULL,
    kept_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    resume TEXT NOT NULL,
    scope TEXT NOT NULL,
    jobs INTEGER NOT NULL
);
"""
OPEN = "status IN ('new', 'shown', 'queued') AND closed IS NULL"  # what Today and the queue list

OLDER = "older_resume"
MARKED = "marked"


def older(family: str, current: str, kept: dict[str, str]) -> bool:
    """Was a score made under a resume (family) other than the current one, and not kept as the baseline?"""
    return bool(current) and family != current and kept.get(family) != current


def flag(fit: dict, rid: str, current: str, kept: dict[str, str], mark: tuple[str, str] | None) -> dict:
    """The fit with what makes it stale, when something does: stale (True), stale_why (OLDER or MARKED), which
    resume it was scored under (scored_under), and for a mark when (stale_at) and why (stale_reason). A mark
    comes first: it is the decision, and stays until the job is scored again."""
    family = resume_family(rid)
    if not mark and not older(family, current, kept):
        return fit
    out = {**fit, "stale": True, "stale_why": MARKED if mark else OLDER, "scored_under": family}
    if mark:
        out["stale_at"], out["stale_reason"] = mark
    return out


def marked(fit: dict | None) -> bool:
    """Was this score marked stale by a decision (so its job is scored again), not just made under an older
    resume?"""
    return bool(fit) and fit.get("stale_why") == MARKED


def wording(fit: dict) -> str:
    """Why a stale score is stale, in words for a tooltip or a line: "scored under an older resume" or "marked
    stale on 2026-11-26: bigger resume change"."""
    if fit.get("stale_why") == MARKED:
        day = str(fit.get("stale_at") or "")[:10]
        why = f": {fit['stale_reason']}" if fit.get("stale_reason") else ""
        return f"marked stale{f' on {day}' if day else ''}{why}"
    return "scored under an older resume"


def kept_map(db) -> dict[str, str]:
    return {r["family"]: r["adopted"] for r in db.execute("SELECT family, adopted FROM score_kept")}


def marks(db, keys=None) -> dict[str, tuple[str, str]]:
    """{job key: (when, why)} of the marked scores, or just these keys' (asked a few hundred at a time)."""
    if keys is None:
        return {r["key"]: (r["marked_at"], r["reason"]) for r in db.execute("SELECT * FROM score_stale")}
    out = {}
    keys = list(keys)
    for i in range(0, len(keys), 500):  # SQLite's limit on query variables
        chunk = keys[i:i + 500]
        for r in db.execute(f"SELECT * FROM score_stale WHERE key IN ({','.join('?' * len(chunk))})", chunk):
            out[r["key"]] = (r["marked_at"], r["reason"])
    return out


def _log(db, now: str, action: str, reason: str, resume: str, scope: str, jobs: int):
    db.execute("INSERT INTO score_decisions (at, action, reason, resume, scope, jobs) VALUES (?, ?, ?, ?, ?, ?)",
               (now, action, reason, resume, scope, jobs))


def decisions(db, limit: int = 20) -> list[dict]:
    """The stale/keep decisions made, newest first: {at, action, reason, resume, scope, jobs}."""
    return [dict(r) for r in db.execute("SELECT at, action, reason, resume, scope, jobs FROM score_decisions "
                                        "ORDER BY id DESC LIMIT ?", (limit,))]


def _current(cfg: Config) -> str:
    return resume_family(resume_id(cfg.resume, cfg.prompts))


def _has_resume(cfg: Config) -> bool:
    return bool(cfg.resume and cfg.resume.is_file())


def status(cfg: Config, store: Store) -> dict:
    """Where the scores stand against the resume now, for deciding what to do about a resume change: how many
    jobs have a score (`scored`), how many of those were made under an older resume (`older`) or marked (`marked`),
    and of the older ones how many are open (`older_open`: on Today or queued), queued (`older_queued`) or at least
    filters.min_fit (`older_min`); which resumes they were made under (`by_resume`), how many by another version
    of the scorer (`other_scorer`, nothing makes them stale) and the last decision (`last`). With no resume,
    `resume` is None."""
    if not _has_resume(cfg):
        return {"resume": None}
    rid = resume_id(cfg.resume, cfg.prompts)
    current = resume_family(rid)
    scorer = re.search(r":scorer-([0-9a-f]{8})", rid)[1]
    kept, marked_keys = kept_map(store.db), marks(store.db)
    open_keys = {r["key"]: r["status"] for r in store.db.execute(f"SELECT key, status FROM jobs WHERE {OPEN}")}
    cut = cfg.filters.min_fit or 0
    out = {"resume": current, "scored": 0, "older": 0, "marked": 0, "older_open": 0, "older_queued": 0,
           "older_min": 0, "min_fit": cut, "other_scorer": 0}
    by: dict[str, dict] = {}
    for r in store.newest_scores():
        out["scored"] += 1
        family = resume_family(r["resume"])
        if (made := re.search(r":scorer-([0-9a-f]{8})", r["resume"])) and made[1] != scorer:
            out["other_scorer"] += 1
        if r["key"] in marked_keys:
            out["marked"] += 1
        if not older(family, current, kept):
            continue
        out["older"] += 1
        out["older_open"] += r["key"] in open_keys
        out["older_queued"] += open_keys.get(r["key"]) == "queued"
        out["older_min"] += bool(cut) and (r["score"] or 0) >= cut
        b = by.setdefault(family, {"resume": family, "jobs": 0, "last": ""})
        b["jobs"] += 1
        b["last"] = max(b["last"], r["scored_at"])
    out["by_resume"] = sorted(({**b, "last": b["last"][:10]} for b in by.values()), key=lambda b: -b["jobs"])
    out["last"] = (decisions(store.db, 1) or [None])[0]
    return out


def pick(cfg: Config, store: Store, min_score: float | None = None, queued: bool = False) -> tuple[list[str], str]:
    """(the keys of the scored jobs to mark stale, how they were picked): all of them, or with min_score and/or
    queued the ones at or above that score and the ones queued."""
    rows = store.newest_scores()
    if min_score is None and not queued:
        return [r["key"] for r in rows], "all scores"
    in_queue = {r["key"] for r in store.db.execute("SELECT key FROM jobs WHERE status='queued' AND closed IS NULL")}
    keys = [r["key"] for r in rows if (queued and r["key"] in in_queue)
            or (min_score is not None and (r["score"] or 0) >= min_score)]
    scope = " and ".join([*([f"scoring {min_score:g}+"] if min_score is not None else []),
                          *(["queued"] if queued else [])])
    return keys, scope


def mark_stale(cfg: Config, store: Store, reason: str = "", min_score: float | None = None,
               queued: bool = False, now: str | None = None) -> int:
    """Decide that these scores (see pick) are stale: each job is scored again, by the page's background scoring
    when it is on, the Score button or `jobwatch score --rescore`. They go on showing, flagged, until then.
    Returns how many were marked."""
    if not _has_resume(cfg):
        return 0
    keys, scope = pick(cfg, store, min_score, queued)
    at = now or datetime.now().astimezone().isoformat(timespec="seconds")
    with store.db:
        store.db.executemany("INSERT OR REPLACE INTO score_stale (key, marked_at, reason) VALUES (?, ?, ?)",
                             [(k, at, reason) for k in keys])
        _log(store.db, at, "stale", reason, _current(cfg), scope, len(keys))
    return len(keys)


def keep(cfg: Config, store: Store, reason: str = "", now: str | None = None) -> int:
    """Decide that the scores made under older resumes still stand: the current resume is their baseline, so
    they stop being flagged and nothing is scored again. Marks already made stay (they were a decision too: see
    unmark). Returns how many scores this made current."""
    if not _has_resume(cfg):
        return 0
    current = _current(cfg)
    kept = kept_map(store.db)
    families = [resume_family(r["resume"]) for r in store.newest_scores()]
    adopt = {f for f in families if older(f, current, kept)}
    n = sum(older(f, current, kept) for f in families)
    at = now or datetime.now().astimezone().isoformat(timespec="seconds")
    with store.db:
        store.db.execute("UPDATE score_kept SET adopted=?, kept_at=? WHERE adopted!=?", (current, at, current))
        store.db.executemany("INSERT OR REPLACE INTO score_kept (family, adopted, kept_at) VALUES (?, ?, ?)",
                             [(f, current, at) for f in adopt])
        _log(store.db, at, "keep", reason, current, "scores made under older resumes", n)
    return n


def unmark(store: Store, now: str | None = None) -> int:
    """Take back the marks still waiting to be scored again: those jobs' scores stand as they are. Returns how
    many."""
    n = store.db.execute("SELECT COUNT(*) FROM score_stale").fetchone()[0]
    at = now or datetime.now().astimezone().isoformat(timespec="seconds")
    with store.db:
        store.db.execute("DELETE FROM score_stale")
        if n:
            _log(store.db, at, "unmark", "", "", "marked scores", n)
    return n
