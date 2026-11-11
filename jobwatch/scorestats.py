"""Fit scoring's backend in effect and what it has cost, for Settings (and the page's /api/scoring/usage).

What the store records: every score's scored_by ("backend:model", so a fallback's score says who made it) and
when, which gives jobs scored today, this week and this month per backend; and, for Claude, the tokens each run
used (Store.add_score_cost, from the API replies). Claude scores made before tokens were recorded are priced as
an estimate: their count times the average cost of a recorded score."""

from __future__ import annotations

from datetime import date, timedelta

from .config import Config, fallback_entry
from .store import Store

# USD per million tokens (input, output) by Claude model id: Anthropic's list prices (docs, October 2026). A model
# not listed has no price here, so its cost shows as "not priced" with the tokens instead of a made-up number.
PRICES = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-5-5": (0.10, 0.50),   # up to 100K-token prompts
    "claude-haiku-4-5": (1.00, 5.00),
}
# Where a model's prompt-cache reads aren't a tenth of its input price (USD per million tokens).
CACHE_READ_PRICES = {"claude-opus-5-5": 0.20, "claude-fable-5-1": 0.25, "claude-fable-5": 0.25}
CACHE_WRITE = 1.25  # 5-minute cache writes, as a multiple of the input price
CACHE_READ = 0.10   # cache reads, as a multiple of the input price, unless CACHE_READ_PRICES says
BATCH = 0.5         # the Message Batches API charges half

COVERED = {"agy": "covered by subscription", "local": "$0 (runs on this computer)"}


def cost_usd(row: dict) -> float | None:
    """What a recorded run cost (a score_cost row), or None when its model has no price in PRICES."""
    if (price := PRICES.get(row["model"])) is None:
        return None
    price_in, price_out = price
    read = CACHE_READ_PRICES.get(row["model"], price_in * CACHE_READ)
    total = (row["input_tokens"] * price_in + row["output_tokens"] * price_out
             + row["cache_write_tokens"] * price_in * CACHE_WRITE + row["cache_read_tokens"] * read) / 1e6
    return total * (BATCH if row["batch"] else 1)


def default_model(backend: str) -> str:
    """The model shortlist-ai scores with on this backend when scoring.model isn't set ("" when it's not installed)."""
    try:
        from shortlist_ai import backends
    except ImportError:
        return ""
    return {"claude": backends.CLAUDE_MODEL, "local": backends.LOCAL_MODEL, "agy": backends.AGY_MODEL}.get(backend, "")


def _model(cfg: Config, entry: str, main: bool = False) -> dict:
    """The backend and model of scoring.backend (main) or a scoring.fallback entry (agy, agy:gemini-...)."""
    backend, named = fallback_entry(entry)
    set_by = cfg.score_model if main else named or (cfg.agy_model if backend == "agy" else "")
    return {"backend": backend, "model": set_by or default_model(backend), "default": not set_by}


def claude_cost(rows: list[dict], scored: int, average: float | None) -> dict:
    """The Claude API's cost over `rows` (recorded runs) for `scored` Claude scores in the same period:
    recorded dollars, and the scores with no recorded tokens priced at `average` per score (None: nothing recorded
    to average, so they're "not recorded"). unpriced: models in the rows that have no price."""
    priced = [(r, c) for r in rows if (c := cost_usd(r)) is not None]
    recorded_jobs = sum(r["jobs"] for r in rows)
    missing = max(scored - recorded_jobs, 0)
    recorded = sum(c for _, c in priced)
    estimated = round(missing * average, 4) if missing and average is not None else None
    return {"recorded_usd": round(recorded, 4), "recorded_jobs": recorded_jobs,
            "estimated_usd": estimated, "estimated_jobs": missing if estimated is not None else 0,
            "not_recorded_jobs": 0 if estimated is not None else missing,
            "total_usd": round(recorded + (estimated or 0), 4),
            "tokens": sum(r["input_tokens"] + r["output_tokens"] + r["cache_write_tokens"] + r["cache_read_tokens"]
                          for r in rows),
            "unpriced": sorted({r["model"] for r in rows if r["model"] not in PRICES})}


def summary(cfg: Config, store: Store, scoring: dict | None = None, today: date | None = None) -> dict:
    """Settings' Fit scoring panel: the backend in effect (model, fallbacks in order, daily cap and today's use,
    Batches API, background scoring from `scoring`, the Scorer's status), jobs scored per backend today, in the
    last 7 days and this calendar month, and the Claude cost this month."""
    today = today or date.today()
    month = today.replace(day=1)
    week = today - timedelta(days=6)
    counts = {b: {"today": 0, "week": 0, "month": 0} for b in cfg.backends}
    for day, scored_by in store.scored_by_day(min(month, week)):
        who = scored_by.partition(":")[0]
        if who not in counts:
            continue
        counts[who]["month"] += day >= month
        counts[who]["week"] += day >= week
        counts[who]["today"] += day == today
    everything = store.score_costs()
    priced = [(r["jobs"], c) for r in everything if (c := cost_usd(r)) is not None]
    recorded_jobs = sum(jobs for jobs, _ in priced)
    average = sum(c for _, c in priced) / recorded_jobs if recorded_jobs else None
    this_month = [r for r in everything if r["day"] >= month.isoformat()]
    used = store.score_usage(cfg.backend, today)
    chain = [cfg.backend, *(fallback_entry(e)[0] for e in cfg.score_fallback)]
    return {
        "backend": _model(cfg, cfg.backend, main=True), "fallback": [_model(cfg, e) for e in cfg.score_fallback],
        "daily": cfg.score_daily or None, "used_today": used,
        "left_today": max(cfg.score_daily - used, 0) if cfg.score_daily else None,
        "batch_api": cfg.score_batch_api, "auto": cfg.auto_score, "scoring": scoring,
        "backends": [{"backend": b, "role": "main" if b == cfg.backend else "fallback" if b in chain else "unused",
                      **counts[b], "cost": COVERED.get(b)} for b in cfg.backends],
        "claude": {**claude_cost(this_month, counts["claude"]["month"], average),
                   "average_usd": round(average, 4) if average is not None else None,
                   "since": month.isoformat()},
    }
