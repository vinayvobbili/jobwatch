"""One job's pay, one labelled item per source, in a fixed order: Posted, Levels, LCA, Recruiter, Glassdoor, Ask.

Each source is {"key", "label", "value", "reason", "blank"}: `value` is its short text, or None when the source has
nothing, and then `reason` says why in a few words (so a blank never looks like a bug) and `blank` is what a chip or
line shows in the value's place ("TBD" while it will be known later, "none" when it won't, "off" when it's switched
off). A source with a figure also has `detail`, the longer words for a hover. The page shows these as chips, `jobwatch
show` as one line, get_job as the `pay_sources` object. Nothing here looks anything up: the callers pass what they
have (levels.py's result, lca.py's estimate, the store's comp row).

A source with a figure also has a `tip`, the hover sentence, and, when a reader can check the figure somewhere, an
`href`: Posted links to the posting itself, Levels to the Levels.fyi page the figure came from, LCA to the Department of
Labor's data. The DOL has no page per filing, so the chip opens h1bdata.info's page of the employer's filings with
the title (marked third-party in its tip; `site` names it) when it has one, else the DOL's disclosure file the filings
are in (its fiscal year and quarter), else the page that lists the DOL's files. Glassdoor to Glassdoor's salary
search for the company and title (the figure is typed in, and Glassdoor has no stable page per company, so it is a
search link). Recruiter and Ask come from the person's own notes: never a link. An unknown address is no `href`,
never an empty one. Building a link looks nothing up.
"""
from __future__ import annotations

from urllib.parse import quote, urlsplit

from . import lca, levels
from .models import Job

LATER = "later"  # a Levels.fyi result not asked for yet: this list only looks up some of its jobs
ORDER = (("posted", "Posted"), ("levels", "Levels"), ("lca", "LCA"), ("recruiter", "Recruiter"),
         ("glassdoor", "Glassdoor"), ("ask", "Ask"))
# What a recruiter said, in the order shown (asked is the person's own number: it shows as the Ask chip)
RECRUITER = (("base", "base"), ("bonus", "bonus"), ("equity", "equity"), ("signon", "sign-on"), ("offered", "offered"))


GLASSDOOR_SEARCH = "https://www.glassdoor.com/Search/results.htm"


def _k(n: float) -> str:
    return f"${n / 1000:.0f}K"


def web_url(url: str | None) -> str | None:
    """`url` when it is a full http(s) address, else None: a job added by hand has none, and a link must never be
    empty, relative or a script."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    return url.strip() if parts.scheme in ("http", "https") and parts.netloc else None


def glassdoor_url(company: str | None, title: str | None = "") -> str | None:
    """Glassdoor's search for "<company> <title> salary", from words already on the page; None without a company."""
    company = " ".join((company or "").split())
    if not company:
        return None
    words = " ".join(f"{company} {title or ''} salary".split())
    return f"{GLASSDOOR_SEARCH}?keyword={quote(words, safe='')}"


def _src(key: str, value: str | None = None, reason: str = "", blank: str = "none", href: str | None = None,
         tip: str | None = None, **more) -> dict:
    label = dict(ORDER)[key]
    return {"key": key, "label": label, "value": value, "reason": None if value else reason,
            "blank": None if value else blank, **({"href": href} if value and href else {}),
            **({"tip": tip} if value and tip else {}), **more}


def _tip(href: str | None, where: str, what: str) -> str:
    """The hover sentence: where a link goes and what it shows, or just what it is when there is no link."""
    return f"Open {where} to verify: {what}" if href else what


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
    href = web_url(result.url)
    return _src("levels", value, detail=f"Levels.fyi {result.level} median {value} ({result.where})",
                amount=result.base or result.total, url=result.url, href=href,
                tip=_tip(href, "Levels.fyi", f"{result.level} median {value} for {result.family} at {result.company} "
                                             f"({result.where}), the page this figure was read from"))


def _lca(est: lca.Estimate | None, cached: bool) -> dict:
    if est is None and not cached:
        return _src("lca", reason="no H-1B filings cache yet; run jobwatch lca update", blank="off")
    if est is None:
        return _src("lca", reason=f"fewer than {lca.MIN_FILINGS} matching H-1B filings for this employer and title")
    years = "" if not est.years else f", starting {est.years[0]}" if est.years[0] == est.years[1] \
        else f", starting {est.years[0]}–{est.years[1]}"
    filings = f"{est.count} certified filing{'s' if est.count != 1 else ''}{years}"
    base = "base pay only, not total compensation"
    # The chip goes to the most specific page there is. The DOL has no page per filing, only its spreadsheets, so that
    # is h1bdata.info's page listing this employer's filings with this title (an independent site that republishes
    # the DOL's files; the figure itself is still computed from the DOL's data). Without one (other employers'
    # filings, or an address that is no link) it is the DOL file the filings are in (the newest, when they span two),
    # else, for a cache that kept no file addresses, the page that lists the DOL's files.
    file = est.files[0] if est.files and web_url(est.files[0]["url"]) else None
    source = (f"the DOL's {file['label']} disclosure file" if file else "the DOL's disclosure data")
    search = web_url(est.search_url)
    href = search or web_url(est.url)
    cases = [e["case"] for e in est.examples if e.get("case")]
    find = f"; examples by case number: {', '.join(cases)}" if cases else ""
    if search:
        where = f"{lca.THIRD_PARTY}, a third-party site that republishes the DOL's data (not the DOL)"
        find = f"{find}; the figure itself comes from {source}, and the site may lag its newest filings"
    elif file:
        where = source + (f" (the newest of {len(est.files)} files it draws on)" if len(est.files) > 1 else "")
    else:
        where = "the U.S. Department of Labor's H-1B (LCA) disclosure data"
        find = ""
    extra = {"site": lca.THIRD_PARTY} if search else {}
    if est.where.endswith(lca.MARKET):  # other employers' filings in the home state: never read as this one's pay
        return _src("lca", f"{_k(est.median)} median ({est.count} filings, {est.where}; not this employer's)",
                    detail=est.line(), amount=est.median, short=f"{_k(est.median)} mkt", market=True, url=est.url,
                    href=href, tip=_tip(href, where, f"{filings} by other employers in {est.where.split(',')[0]}, "
                                                     f"not this employer's; {base}{find}"), **extra)
    return _src("lca", f"{_k(est.median)} median ({est.count} filings)", detail=est.line(), amount=est.median,
                short=f"{_k(est.median)} med", url=est.url, href=href,
                tip=_tip(href, where, f"{filings} for {est.company} ({est.where}); {base}{find}"), **extra)


def _recruiter(comp: dict | None) -> dict:
    said = [(label, comp[k]) for k, label in RECRUITER if comp and comp.get(k)]
    if not said:
        return _src("recruiter", reason="no recruiter figures kept (jobwatch comp KEY --base 165-195K)")
    value = ", ".join(f"{label} {v}" for label, v in said)
    return _src("recruiter", value, tip=f"From your notes: {value}")


def _glassdoor(comp: dict | None, job: Job) -> dict:
    if comp and comp.get("glassdoor"):
        href = glassdoor_url(job.display_company, job.title)
        return _src("glassdoor", comp["glassdoor"], href=href,
                    tip=_tip(href, "Glassdoor", f"a Glassdoor salary search for {job.display_company}, {job.title}; "
                                                f"the figure ({comp['glassdoor']}) is the one you entered"))
    return _src("glassdoor", reason="none entered; jobwatch never fetches Glassdoor (jobwatch comp KEY --glassdoor)")


def _ask(comp: dict | None, result, on: bool) -> dict:
    if comp and comp.get("asked"):  # what the person told a recruiter they want beats the Levels.fyi suggestion
        return _src("ask", comp["asked"], detail=f"You asked for {comp['asked']} (kept with jobwatch comp --asked)",
                    tip=f"From your notes: you asked for {comp['asked']} (kept with jobwatch comp --asked)")
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
    top = job.salary_max or job.salary_min  # the page reads the posted top from here
    href = web_url(job.url)
    own = _tip(href, "the posting", "the posting's own range")
    posted = (_src("posted", job.pay(), rate=True, short=job.pay().split(", about ")[0], amount=top, href=href,
                   detail=f"{job.pay()}: a rate worked out as a year's pay, not a salary",
                   tip=_tip(href, "the posting", "the posting's own rate, worked out here as a year's pay"))
              if job.is_rate else _src("posted", job.pay(), reason="the posting lists no pay", amount=top, href=href,
                                       tip=own))
    return [posted,
            _levels(job, result, levels_on), _lca(est, lca_cached), _recruiter(comp), _glassdoor(comp, job),
            _ask(comp, result, levels_on)]


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
