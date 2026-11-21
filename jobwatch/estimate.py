"""An estimated yearly base for a job whose posting lists no pay, from figures jobwatch already holds: what a recruiter
told you for this job, what recruiters told you for similar jobs, H-1B filings (lca.py) and Levels.fyi (levels.py).

It is an estimate and is always shown as one ("Est."), with the basis that produced it: the page's chip, a digest
line, `jobwatch comp KEY --estimate` and the `pay_estimate` of get_comps (flagged `estimate: true`). Nothing is
looked up here and nothing is saved: the sources are used in this order, and the first with a figure wins.

1. recruiter: the base (else the offer, else a figure in the note) a recruiter gave for this very job.
2. similar: the bases recruiters gave for other jobs of the same kind of work (lca.same_work on the titles), their
   lowest, middle and highest.
3. lca: the H-1B filings' median and quartiles, the employer's own when it has enough, else the market's (the home
   state's filings for the same kind of work, said so in the detail).
4. levels: Levels.fyi's median base for the level, when pay.levels is on and the page was read already.

A job with a posted range has no estimate: the posting is the pay. The estimate never feeds the Comps suggestion's
score, so a guess can't outrank a figure someone gave.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from statistics import median

from . import lca, levels
from .models import Job
from .store import Store

BASES = ("base", "offered")   # a recruiter's figures for a job, best first (what they asked of others isn't one)


def _k(n: float) -> str:
    return f"${n / 1000:.0f}K"


@dataclass
class PayEstimate:
    low: int
    mid: int
    high: int
    basis: str      # recruiter, similar, lca or levels
    detail: str     # where it came from, in a sentence
    figures: int = 1  # how many figures it rests on

    def short(self) -> str:
        """"$150K–$170K" or, for a single point, "~$165K"."""
        return f"~{_k(self.mid)}" if self.low == self.high else f"{_k(self.low)}–{_k(self.high)}"

    def label(self) -> str:
        return f"Est. {self.short()} base"

    def to_dict(self) -> dict:
        return {"estimate": True, "low": self.low, "mid": self.mid, "high": self.high, "basis": self.basis,
                "label": self.label(), "detail": self.detail, "figures": self.figures}


def _range(low: float, high: float) -> tuple[int, int, int]:
    return round(low), round((low + high) / 2), round(high)


def similar_bases(store: Store, job: Job, comps: dict[str, dict] | None = None) -> list[tuple[int, int]]:
    """The base ranges (low, high) recruiters gave for other jobs of the same kind of work as this one."""
    from .comps import amount  # here, not at the top: comps reads watch, and watch reads this module
    mine = lca.title_words(job.title)
    given = {key: base for key, comp in (store.comps() if comps is None else comps).items()
             if (base := amount(comp.get("base")))}
    titles = store.titles(given)  # one indexed read of every comp's title, kept for the next job
    return [base for key, base in given.items()
            if key != job.key and key in titles and lca.same_work(mine, _words(titles[key]))]


@lru_cache(maxsize=4096)
def _words(title: str) -> list[frozenset[str]]:
    """lca.title_words, remembered: the same few comp titles are read against every job of a page."""
    return lca.title_words(title)


def estimate(job: Job, *, comp: dict | None = None, similar: list[tuple[int, int]] | None = None,
             filings: lca.Estimate | None = None, result=None) -> PayEstimate | None:
    """The job's estimated base from what's passed in (see the module docstring for the order), or None when the
    posting lists pay or no source has a figure. `result` is levels.py's answer for the job."""
    from .comps import amount  # see similar_bases
    if job.salary_min or job.salary_max:
        return None
    comp = comp or {}
    for field in (*BASES, "note"):
        if got := amount(comp.get(field)):
            what = {"base": "base", "offered": "offer", "note": "note"}[field]
            return PayEstimate(*_range(*got), "recruiter",
                               f"A recruiter's {what} for this job ({_k(got[0])}–{_k(got[1])}), kept with `jobwatch "
                               "comp`.")
    if similar:
        low, high = min(s[0] for s in similar), max(s[1] for s in similar)
        mid = round(median((s[0] + s[1]) / 2 for s in similar))
        n = len(similar)
        return PayEstimate(round(low), mid, round(high), "similar",
                           f"Bases recruiters gave you for {n} similar job{'s' * (n != 1)}: lowest {_k(low)}, "
                           f"highest {_k(high)}.", n)
    if filings:
        market = filings.where.endswith(lca.MARKET)
        whose = "other employers' filings in your state for similar work" if market else "this employer's filings"
        return PayEstimate(filings.p25, filings.median, filings.p75, "lca",
                           f"Median {_k(filings.median)} base ({_k(filings.p25)}–{_k(filings.p75)}) in {filings.count} "
                           f"H-1B filings ({whose}, {filings.where}): a base, not total pay.", filings.count)
    if isinstance(result, levels.Estimate) and (result.base or result.company_base):
        base = result.base or result.company_base
        return PayEstimate(base, base, base, "levels",
                           f"Levels.fyi {result.level} median base {_k(base)} ({result.where}).")
    return None


def render(job: Job, got: PayEstimate | None) -> str:
    """What `jobwatch comp KEY --estimate` prints."""
    who = f"{job.display_company}: {job.title}"
    if job.pay():
        return f"{who} lists its pay ({job.pay()}): no estimate is needed."
    if not got:
        return (f"{who}: no estimate. Nothing is kept to go on: no figure from a recruiter for this job or similar "
                f"ones, no H-1B filings for it, no Levels.fyi page. A recruiter's range helps most: "
                f"`jobwatch comp {job.key} --base 165-195K`.")
    return (f"{who}\n  {got.label()}: an estimate, not an offer or a posted range\n  Basis ({got.basis}): "
            f"{got.detail}\n  Nothing was saved.")


READ = object()   # "read it here": a caller that already has the H-1B estimate (even none) or Levels' answer passes it


def for_job(cfg, store: Store, job: Job, *, comps: dict[str, dict] | None = None, filings=READ,
            result=READ) -> PayEstimate | None:
    """estimate() from the store: the job's comp row and the similar jobs' bases. Pass `filings` (lca.Estimate or
    None) and `result` (levels.py's answer) when the caller already has them, as a list of jobs does; else the
    H-1B cache and the Levels.fyi pages already kept are read for this one job, and nothing is asked of
    Levels.fyi."""
    if job.salary_min or job.salary_max:
        return None
    comps = store.comps() if comps is None else comps
    if filings is READ:
        filings = lca.for_one_job(cfg, job)
    if result is READ:
        result = levels.expected(cfg, store, job)
    return estimate(job, comp=comps.get(job.key), similar=similar_bases(store, job, comps), filings=filings,
                    result=result)
