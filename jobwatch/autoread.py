"""Reading LinkedIn and Indeed postings by itself, slowly: which jobs the browser extension may open.

jobwatch never reads linkedin.com or indeed.com itself (the pages need the person's sign-in), and the Read posting
button has the extension read one job's page in a background tab when the person presses it. With `autoread.enabled`
the extension does the same for the jobs worth it, with nobody pressing anything, under limits that exist to keep the
person's signed-in account from looking automated (see the "Reading postings by itself" guide):

- only jobs worth reading: the server decides (`queue`) and hands the extension a short list. A job on it has no
  posting text, comes from an alert or a list, passes every filter Today uses (title, place, pay, age, fit), isn't a
  duplicate of a job already acted on, isn't snoozed, skipped, closed or being checked, wasn't tried lately and
  doesn't belong to a company whose own board jobwatch watches (that board gives the text). The best come first.
- one job at a time, slowly and a few a day: the extension's scheduler (chrome-extension/auto-read.js) keeps the
  pace and the daily caps, and enforces the same hard ceilings as `limits` here, whatever any setting says.
- the text is stored exactly as Read posting stores it (POST /ext/posting, with `auto`), and scoring follows the
  scoring rules and caps as for any new text.

`report` takes what the extension says about a read that gave no text, a stop for the day and the person's own
pause or resume, and writes it in the Activity tab.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from . import dupes, filltext, jobpass
from .config import (
    AUTOREAD_DAILY_MAX,
    AUTOREAD_PAUSE_FLOOR,
    AUTOREAD_SPREAD,
    Config,
)
from .filters import relevance
from .store import MANUAL, Store
from .watch import Entry, _group, _matching, _ranker

RETRY = timedelta(days=3)  # a job the extension tried to read, in vain, is not handed to it again before this
QUEUE_MAX = 5              # the jobs handed over at once: the extension reads one, then asks again
SITE_LABELS = {"linkedin": "linkedin.com", "indeed": "indeed.com"}
OUTCOMES = ("no_text", "trouble", "cancelled")  # a read that gave no text, and why: all of them mark the job tried
EVENTS = ("paused", "resumed", "off", "on")      # what the person or a sign of trouble did to the extension's reading


def limits(cfg: Config) -> dict:
    """What the extension may do, from the settings, never past the hard ceilings (the config already refuses a
    setting beyond them; this holds even for a Config built by hand)."""
    a = cfg.autoread
    low = max(AUTOREAD_PAUSE_FLOOR, a.pause_min)
    return {"enabled": a.enabled, "per_day": max(1, min(a.per_day, AUTOREAD_DAILY_MAX)),
            "daily_max": AUTOREAD_DAILY_MAX, "pause_min": low, "pause_max": max(low + AUTOREAD_SPREAD, a.pause_max)}


def _own_boards(cfg: Config) -> set[str]:
    """The company names (see dupes.company_key) whose own board jobwatch watches: a job there gets its text from
    the board."""
    return {n for b in cfg.boards for n in dupes.company_names(b.source, b.board, b.name)}


def _recent(tried: dict[str, str], key: str, now: datetime) -> bool:
    when = tried.get(key)
    return bool(when) and now - datetime.fromisoformat(when) < RETRY


def candidates(cfg: Config, store: Store, now: datetime | None = None) -> list[Entry]:
    """The jobs worth reading, best first: the open queued ones (oldest first: they are about to be applied to), then
    Today's, most relevant first, one per company and title (the same role posted per region reads the same). Each
    has no posting text and a LinkedIn or Indeed job page, and none is a duplicate, closed or being checked, tried
    lately, or at a company whose own board is watched."""
    now = now or datetime.now(UTC)
    tried = store.read_tried()
    boards = _own_boards(cfg)
    index = jobpass.acted_index(store)
    queued = []
    for job, rec in sorted(store.jobs(("queued",)), key=lambda r: r[1]["status_at"] or ""):
        rel, hits = relevance(job, cfg.keywords)
        queued.append(Entry(job, rec, rel, hits, duplicate=index.match(job, rec)))
    today, _ = _matching(cfg, store, ("new", "shown"))
    line = [*queued, *_group(sorted(today, key=_ranker(cfg)))]
    out = []
    for e in line:
        job = e.job
        if (job.source != MANUAL or job.description.strip() or not filltext.browser_site(job.url) or e.duplicate
                or e.record.get("closed") or _recent(tried, job.key, now)
                or dupes.companies(job) & boards):
            continue
        out.append(e)
    return out


def queue(cfg: Config, store: Store, left: dict[str, int] | None = None, limit: int = QUEUE_MAX,
          now: datetime | None = None) -> dict:
    """What GET /ext/read-queue answers: the limits, how many jobs wait, and up to `limit` of them, best first, each
    {key, site, url, title, company}. `left` is how many reads the extension has left today for each site (what its
    daily caps allow): a site with none left gets no job. Off (autoread.enabled false): no jobs at all."""
    lim = limits(cfg)
    out = {"enabled": lim["enabled"], "limits": lim, "waiting": 0, "jobs": []}
    if not lim["enabled"]:
        return out
    left = left or {}
    allowed = {site for site in SITE_LABELS if left.get(site, lim["per_day"]) > 0}
    jobs = []
    for e in candidates(cfg, store, now):
        site = filltext.browser_site(e.job.url)
        if site in allowed:
            jobs.append({"key": e.job.key, "site": site, "url": e.job.url, "title": e.job.title,
                         "company": e.job.display_company})
    out["waiting"] = len(jobs)
    out["jobs"] = jobs[:max(1, min(limit, QUEUE_MAX))]
    return out


def report(store: Store, body: dict) -> dict:
    """What the extension says happened, in the Activity tab (and for a read that gave no text, on the job, so it isn't
    handed over again at once): {outcome: no_text|trouble|cancelled, key, site, reason} or
    {event: paused|resumed|off|on, reason}. A stop for the day is `paused` with the extension's own words, and is
    worth a look (notable)."""
    event, outcome = str(body.get("event") or ""), str(body.get("outcome") or "")
    reason = " ".join(str(body.get("reason") or "").split())[:300]
    site = SITE_LABELS.get(str(body.get("site") or ""), "")
    key = str(body.get("key") or "")
    job = store.job(key) if key else None
    if outcome:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome is one of {', '.join(OUTCOMES)}")
        if job:
            store.set_read_tried(job.key, outcome)
        what = f"{job.title} at {job.display_company}" if job else "a posting"
        store.log("mail", f"Couldn't read {what}{f' from {site}' if site else ''}: {reason or outcome}", ok=False,
                  jobs=[job.key] if job else [])
        return {"ok": True}
    if event not in EVENTS:
        raise ValueError(f"send an outcome ({', '.join(OUTCOMES)}) or an event ({', '.join(EVENTS)})")
    said = {"paused": reason or "Auto-read paused", "resumed": "Auto-read resumed: reading postings again",
            "off": "Auto-read turned off in the browser extension",
            "on": "Auto-read turned on in the browser extension"}[event]
    trouble = event == "paused" and bool(reason)
    store.log("mail", said, ok=not trouble, notable=trouble)
    return {"ok": True}
