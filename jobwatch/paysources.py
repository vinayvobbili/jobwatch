"""One job's pay, one labelled item per source, in a fixed order: Posted, Levels, LCA, Recruiter, Glassdoor, Ask.

Each source is {"key", "label", "value", "reason", "blank"}: `value` is its short text, or None when the source has
nothing, and then `reason` says why in a few words (so a blank never looks like a bug) and `blank` is what a chip or
line shows in the value's place ("TBD" while it will be known later, "none" when it won't, "off" when it's switched
off). A source with a figure also has `detail`, the longer words for a hover. The page shows these as chips, `jobwatch
show` as one line, get_job as the `pay_sources` object. Nothing here looks anything up: the callers pass what they
have (levels.py's result, lca.py's estimate, the store's comp row).
"""
from __future__ import annotations

from . import lca, levels
from .models import Job

LATER = "later"  # a Levels.fyi result not asked for yet: this list only looks up some of its jobs
ORDER = (("posted", "Posted"), ("levels", "Levels"), ("lca", "LCA"), ("recruiter", "Recruiter"),
         ("glassdoor", "Glassdoor"), ("ask", "Ask"))
# What a recruiter said, in the order shown (asked is the person's own number, not a source)
RECRUITER = (("base", "base"), ("bonus", "bonus"), ("equity", "equity"), ("signon", "sign-on"), ("offered", "offered"))


def _k(n: float) -> str:
    return f"${n / 1000:.0f}K"


def _src(key: str, value: str | None = None, reason: str = "", blank: str = "none", **more) -> dict:
    label = dict(ORDER)[key]
    return {"key": key, "label": label, "value": value, "reason": None if value else reason,
            "blank": None if value else blank, **more}


def _levels(job: Job, result, on: bool) -> dict:
    if not on:
        return _src("levels", reason="turn on with pay.levels: true in the watchlist", blank="off")
    if result == levels.REFUSED:
        return _src("levels", reason="refused today, asks again tomorrow", blank="TBD")
    if result == levels.PENDING:
        return _src("levels", reason="looking it up on Levels.fyi, a few pages at a time", blank="TBD")
    if result == LATER:
        return _src("levels", reason="not looked up in this list yet; open the job to look it up", blank="TBD")
    if not isinstance(result, levels.Estimate):
        why = "no data for this title" if levels.family_for(job.title) else \
            "no data for this title (Levels.fyi has no job family for it)"
        return _src("levels", reason=why)
    value = f"{_k(result.base)} base" if result.base else f"{_k(result.total)} total"
    return _src("levels", value, detail=f"Levels.fyi {result.level} median {value} ({result.where})",
                amount=result.base or result.total, url=result.url)


def _lca(est: lca.Estimate | None, cached: bool) -> dict:
    if est is None and not cached:
        return _src("lca", reason="no H-1B filings cache yet; run jobwatch lca update", blank="off")
    if est is None:
        return _src("lca", reason=f"fewer than {lca.MIN_FILINGS} matching H-1B filings for this employer and title")
    if est.where.endswith(lca.MARKET):  # other employers' filings in the home state: never read as this one's pay
        return _src("lca", f"{_k(est.median)} median ({est.count} filings, {est.where}; not this employer's)",
                    detail=est.line(), amount=est.median, short=f"{_k(est.median)} mkt", url=est.url)
    return _src("lca", f"{_k(est.median)} median ({est.count} filings)", detail=est.line(), amount=est.median,
                short=f"{_k(est.median)} med", url=est.url)


def _recruiter(comp: dict | None) -> dict:
    said = [(label, comp[k]) for k, label in RECRUITER if comp and comp.get(k)]
    if not said:
        return _src("recruiter", reason="no recruiter figures kept (jobwatch comp KEY --base 165-195K)")
    return _src("recruiter", ", ".join(f"{label} {v}" for label, v in said))


def _glassdoor(comp: dict | None) -> dict:
    if comp and comp.get("glassdoor"):
        return _src("glassdoor", comp["glassdoor"])
    return _src("glassdoor", reason="none entered; jobwatch never fetches Glassdoor (jobwatch comp KEY --glassdoor)")


def _ask(result, on: bool) -> dict:
    if isinstance(result, levels.Estimate) and result.ask:
        return _src("ask", _k(result.ask), amount=result.ask,
                    detail=f"{_k(result.ask)} base: the Levels.fyi median plus room to meet in the middle")
    if not on:
        return _src("ask", reason="needs pay.levels on", blank="off")
    if isinstance(result, levels.Estimate):
        return _src("ask", reason="Levels.fyi gives no base for this level")
    if result in (levels.REFUSED, levels.PENDING, LATER):
        return _src("ask", reason="waits on Levels.fyi", blank="TBD")
    return _src("ask", reason="no Levels.fyi figure to work from")


def sources(job: Job, *, comp: dict | None = None, result=None, levels_on: bool = False,
            est: lca.Estimate | None = None, lca_cached: bool = False) -> list[dict]:
    """The six sources for a job, in order. `result` is levels.py's answer (an Estimate, PENDING, REFUSED, LATER or
    None), `est` lca.py's, `comp` what store.comp kept."""
    return [_src("posted", job.pay(), reason="the posting lists no pay"),
            _levels(job, result, levels_on), _lca(est, lca_cached), _recruiter(comp), _glassdoor(comp),
            _ask(result, levels_on)]


def gather(cfg, store, job: Job, result, est: lca.Estimate | None) -> list[dict]:
    """sources() with the watchlist's settings and the job's kept comp."""
    return sources(job, comp=store.comp(job.key), result=result, levels_on=cfg.pay.levels, est=est,
                   lca_cached=lca.cache_path(cfg).is_file())


def as_dict(items: list[dict]) -> dict:
    """For JSON: {source key: {label, value, reason, ...}}, in order."""
    return {s["key"]: {k: v for k, v in s.items() if k != "key"} for s in items}


def line(items: list[dict], width: int = 100) -> str:
    """`Pay: Posted $150K–$196K · Levels TBD (refused today, asks again tomorrow) · LCA $165K median (14 filings)
    · Recruiter none · Glassdoor none · Ask $180K`, wrapped under the first word at `width`. Only a TBD (when
    it'll come) or an off (how to turn it on) says why; a none's reason is for the page's hover and get_job."""
    import textwrap
    parts = [f"{s['label']} {s['value']}" if s["value"]
             else f"{s['label']} {s['blank']}" + (f" ({s['reason']})" if s["blank"] in ("TBD", "off") else "")
             for s in items]
    return textwrap.fill(" · ".join(parts), width, initial_indent="Pay: ", subsequent_indent="     ",
                         break_long_words=False, break_on_hyphens=False)
