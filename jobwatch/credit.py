"""A dated, capped Claude step in the scoring chain, for an API credit that ends.

Fit scoring runs on free scorers (agy, then the local model). When there is promotional API credit to use up, a
`scoring.fallback` entry can name Claude with the day the credit ends:

    fallback: ["claude:claude-sonnet-5-5 until 2026-12-20", agy:gemini-4-argon-high, local]

A dated entry scores first, ahead of scoring.backend (the credit ends, the free scorers don't), until that day in
Eastern time (the credit's own clock): on the day itself and after, it is skipped, so the chain is the free
scorers again. While it runs, a ledger (Store.add_credit_spend) adds up what its calls cost at list price, from the
tokens the API reports, and it stops at a daily cap (scoring.credit.daily_usd, $3) for the day and a total cap
(scoring.credit.total_usd, $90) for good; either cap pauses the step in the store (cap_pause), as an exhausted quota
does, so Settings and `jobwatch scorers` say so. A failure of the account (no credit, a key refused, a rate limit) skips
it without marking any job failed: the next scorer takes the job.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from .config import Config, entry_until, fallback_entry, split_until
from .score import UNTIL_RESUMED
from .scorestats import PRICES, cost_usd
from .store import Store

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # no tz database (Windows without tzdata): a fixed offset, an hour off in summer at worst
    EASTERN = timezone(timedelta(hours=-5))

CHUNK = 5  # jobs scored between cap checks, so a run can pass a cap by one chunk's cost at most


def today_eastern(now: datetime | None = None) -> date:
    """The date in America/New_York (`now` given in any time zone; naive means UTC)."""
    now = now or datetime.now(UTC)
    return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(EASTERN).date()


def skip_reason(cfg: Config, store: Store, entry: str, now: datetime | None = None) -> str:
    """Why a dated entry isn't used now, or "" when it may score: its end day has come (on that day and after),
    its model has no list price (so its spend can't be capped), or a cap is reached."""
    _, model = fallback_entry(entry)
    until = _until(entry)
    today = today_eastern(now)
    if today >= until:
        return f"credit window ended ({until.isoformat()}): {entry.split(' until ')[0]} is skipped"
    if model not in PRICES:
        return f"no list price for {model} (scorestats.PRICES): its spend can't be capped, so it is skipped"
    day_usd, total_usd = store.credit_spent(today)
    if total_usd >= cfg.score_credit_total:
        return f"credit total cap ${cfg.score_credit_total:.2f} reached (${total_usd:.2f} spent): skipped for good"
    if day_usd >= cfg.score_credit_daily:
        return (f"credit daily cap ${cfg.score_credit_daily:.2f} reached (${day_usd:.2f} today): skipped until "
                "tomorrow")
    return ""


CAPS = ("daily cap", "total cap")  # how the reason of a pause cap_pause sets starts


def cap_pause(cfg: Config, store: Store, entry: str, now: datetime | None = None) -> tuple[str, datetime] | None:
    """The pause a reached cap puts on the entry's chain step (Store.set_scorer_down), so Settings and `jobwatch
    scorers` show it paused and no run calls it: the daily cap until the next midnight Eastern, the total cap until
    a human resumes it (UNTIL_RESUMED). None when no cap is reached."""
    day_usd, total_usd = store.credit_spent(today_eastern(now))
    if total_usd >= cfg.score_credit_total:
        return (f"total cap ${cfg.score_credit_total:.2f} reached (${total_usd:.2f} spent): until resumed "
                f"(jobwatch scorers --resume {entry.split(' until ')[0]})", UNTIL_RESUMED)
    if day_usd >= cfg.score_credit_daily:
        midnight = datetime.combine(today_eastern(now) + timedelta(days=1), datetime.min.time(), EASTERN)
        return (f"daily cap ${cfg.score_credit_daily:.2f} reached (${day_usd:.2f} today): back at midnight Eastern",
                midnight)
    return None


def _until(entry: str) -> date:
    until = entry_until(entry)
    if until is None:
        raise ValueError(f"{entry!r} has no end date")
    return until


def record(store: Store, usage: dict, now: datetime | None = None) -> float:
    """Add one run's token usage (a collecting_usage part) to the credit ledger at list price; the dollars."""
    row = {"batch": False, "jobs": 0, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
           "cache_read_tokens": 0, **usage}
    usd = cost_usd(row) or 0.0
    store.add_credit_spend(today_eastern(now), row["model"], row["jobs"], row["input_tokens"], row["output_tokens"],
                           row["cache_write_tokens"], row["cache_read_tokens"], usd)
    return usd


def status(cfg: Config, store: Store, now: datetime | None = None) -> list[dict]:
    """Each dated entry of scoring.fallback: entry, model, until, skipped (why it isn't used now, or ""), and the
    ledger's spend today and in all next to the caps."""
    today = today_eastern(now)
    day_usd, total_usd = store.credit_spent(today)
    return [{"entry": e, "model": fallback_entry(e)[1], "until": _until(e).isoformat(),
             "skipped": skip_reason(cfg, store, e, now), "spent_today": day_usd, "spent_total": total_usd,
             "daily_cap": cfg.score_credit_daily, "total_cap": cfg.score_credit_total}
            for e in cfg.score_fallback if is_dated(e)]


def is_dated(entry: str) -> bool:
    """A scoring.fallback entry that carries an end date (the credit step)."""
    return bool(split_until(entry)[1])
