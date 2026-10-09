"""Expected pay from Levels.fyi: what a job's level pays at its company, and a base salary to ask for.

For personal use, and off unless the watchlist says `pay: {levels: true}`. While it's off nothing is ever asked of
Levels.fyi. Levels.fyi publishes its salary pages as Markdown (a page's link plus .md) and its robots.txt lets
every crawler read them. It asks to be credited: every estimate links its page and says "Data: Levels.fyi".

What's read is kept only in the local state file (Store.pay_page). It never goes into a digest, a package or a
chat. Levels.fyi answers with an empty page when it doesn't have one ready, which can change within hours, so an
empty answer is asked again after a few hours (one, when someone looks at that job); a page that isn't there (404)
after a few days. Pages are read one at a time, a couple of seconds apart, and only for the jobs a person is
looking at or has queued.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from . import sources
from .models import Job
from .text import is_remote, us_states

SITE = "https://www.levels.fyi"
CREDIT = "Data: Levels.fyi"
FRESH = timedelta(days=30)  # how long a page read is trusted
GONE = timedelta(days=3)    # when to ask again for a page that isn't there (404) or robots.txt keeps out
# An empty answer means Levels.fyi didn't have the page ready (its cache hadn't it yet), not that there's none:
EMPTY = timedelta(hours=6)          # when to ask again
EMPTY_ONE_JOB = timedelta(hours=1)  # ... when someone looks at that one job (show, get_job)
PAUSE = 2.0                 # seconds between two requests to Levels.fyi, across every thread
ONE_JOB = 5                 # pages one job can need: a region's page and the US page for two company names, a level's
QUEUE = 20                  # pages a look at the queue may ask for; the rest wait for the next look
US = "United States"

_polite = threading.Lock()
_last = [0.0]


class Reader:
    """Levels.fyi pages, through the store's cache. `budget`: how many pages it may ask Levels.fyi for now (0:
    only what's already kept). A stale page is still used when the budget has run out. `empty`: how old an empty
    answer may be before it's asked for again."""

    def __init__(self, store, budget: int = 0, get=None, robots=None, pause: float | None = None,
                 now: datetime | None = None, empty: timedelta = EMPTY):
        from .alerts import Robots  # alerts reads job pages the same careful way
        self.store, self.budget, self.pause = store, budget, PAUSE if pause is None else pause
        self.get = get or sources.get_text
        self.robots = robots or Robots(self.get)
        self.now = now or datetime.now(timezone.utc)
        self.empty = empty
        self.asked = 0

    def page(self, path: str) -> str | None:
        """The Markdown at SITE/path.md: "" when Levels.fyi has nothing there (for now), None when it isn't
        known yet."""
        url = f"{SITE}/{path}.md"
        hit = self.store.pay_page(url)
        if hit:
            body, at, gone = hit
            if self.now - at < (FRESH if body else GONE if gone else self.empty):
                return body
        if self.budget <= 0:
            # An old empty answer says nothing: not known yet, so it's asked for when there's room.
            return hit[0] if hit and (hit[0] or hit[2]) else None
        self.budget -= 1
        gone = False
        if not self.robots.allowed(url):
            body, gone = "", True
        else:
            with _polite:
                time.sleep(max(0.0, _last[0] + self.pause - time.monotonic()))
                try:
                    body = self.get(url).strip()
                except sources.NotFound:
                    body, gone = "", True
                except sources.SourceError:  # not an answer: ask again next time
                    return hit[0] if hit and (hit[0] or hit[2]) else None
                finally:
                    _last[0] = time.monotonic()
                    self.asked += 1
        self.store.save_pay_page(url, body, gone)
        return body


# -- a Levels.fyi page

@dataclass
class Family:
    """A company's pay for one job family (Software Engineer...), as one Levels.fyi page gives it."""
    company: str
    family: str
    location: str                                  # "United States", or the region the page is about
    currency: str
    levels: list[tuple[str, int]]                  # (level, median total compensation), lowest first
    senior: str | None = None                      # the level Levels.fyi says a "Senior" title is
    years: dict[str, tuple[int, int]] = field(default_factory=dict)  # level -> typical years of experience
    mix: tuple[int, int, int] | None = None        # median base, stock, bonus across all levels


def _money(text: str) -> int:
    return int(text.replace(",", ""))


_HEAD = re.compile(r"^# Levels\.fyi\s*[–-]\s*(.+?) Salaries\s*$", re.M)
_LOCATION = re.compile(r"^\*\*Location:\*\*\s*(.+?)\s*$", re.M)
_CURRENCY = re.compile(r"^\*\*Currency:\*\*\s*([A-Z]{3})", re.M)
_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*\$([\d,]+)\s*\|\s*$", re.M)
_MIX = re.compile(r"median pay mix for .+? is \$([\d,]+) base salary, \$([\d,]+) in stock per year"
                  r"(?:,? and \$([\d,]+) bonus)?")
_YEARS = re.compile(r"typically have (\d+)\s*[–-]\s*(\d+) years")


def parse_family(text: str, family: str = "") -> Family | None:
    """A job family page (companies/<company>/salaries/<family>.md), or None when it isn't one."""
    head, loc, cur = _HEAD.search(text), _LOCATION.search(text), _CURRENCY.search(text)
    table = text.split("### Levels Breakdown", 1)
    if not (head and loc and cur and len(table) == 2):
        return None
    levels = [(name, _money(pay)) for name, pay in _ROW.findall(table[1].split("\n---", 1)[0])
              if not set(name) <= set("- ") and name.lower() != "level"]
    if not levels:
        return None
    name = head.group(1)
    if family and name.lower().endswith(" " + family.lower()):
        name = name[:-len(family) - 1]
    f = Family(company=name, family=family, location=loc.group(1), currency=cur.group(1), levels=levels)
    by_length = sorted((lv for lv, _ in levels), key=len, reverse=True)
    if m := re.search(r"What level is a Senior .+?\?\s*\n(.+)", text):
        f.senior = next((lv for lv in by_length if f"is level {lv}" in m.group(1)), None)
    for lv in by_length:
        if lv not in f.years and (m := re.search(re.escape(f" {lv} have?") + r"\s*\n(.+)", text)):
            if y := _YEARS.search(m.group(1)):
                f.years[lv] = (int(y.group(1)), int(y.group(2)))
    if m := _MIX.search(text):
        f.mix = (_money(m.group(1)), _money(m.group(2)), _money(m.group(3) or "0"))
    return f


def level_base(text: str) -> int | None:
    """A level's median base salary from its page (…/levels/<level>.md), in US dollars."""
    cur = _CURRENCY.search(text)
    m = re.search(r"^- Base:\s*\$([\d,]+)", text, re.M)
    return _money(m.group(1)) if m and cur and cur.group(1) == "USD" else None


# -- which page, which level

FAMILIES = (  # title -> Levels.fyi job family; the first that matches
    (r"\b(engineering|software|development) manager\b|\bmanager,? (of )?(software )?engineering\b"
     r"|\bhead of engineering\b", "software-engineering-manager"),
    (r"\bdata scien", "data-scientist"),
    (r"\btechnical program manager\b|\btpm\b", "technical-program-manager"),
    (r"\bproduct manager\b", "product-manager"),
    (r"\b(sales|solutions|pre-?sales) engineer", "sales-engineer"),
    (r"\barchitect\b", "solution-architect"),
    (r"\b(security|soc|cyber\s?security|threat|information security) analyst\b", "security-analyst"),
    (r"\b(engineer|engineering|developer|programmer|swe|sde)\b", "software-engineer"),
)
FAMILY_NAMES = {"software-engineering-manager": "Software Engineering Manager", "data-scientist": "Data Scientist",
                "technical-program-manager": "Technical Program Manager", "product-manager": "Product Manager",
                "sales-engineer": "Sales Engineer", "solution-architect": "Solution Architect",
                "security-analyst": "Security Analyst", "software-engineer": "Software Engineer"}


def family_for(title: str) -> str | None:
    t = title.lower()
    return next((slug for rx, slug in FAMILIES if re.search(rx, t)), None)


# Seniority words, as steps from the level Levels.fyi calls Senior; the highest one in a title counts.
RANKS = ((r"\b(distinguished|fellow)\b", 3, "Distinguished"), (r"\b(director|head of)\b", 3, "Director"),
         (r"\bprincipal\b", 2, "Principal"), (r"\b(senior|sr\.?) manager\b", 2, "Senior Manager"),
         (r"\b(staff|lead)\b", 1, "Staff/Lead"), (r"\bmanager\b", 1, "Manager"),
         (r"\b(senior|sr\.?)\b", 0, "Senior"), (r"\b(junior|jr\.?|entry[- ]level|associate)\b", -2, "Junior"))


def seniority(title: str) -> tuple[int, str] | None:
    t = title.lower()
    found = [(steps, word) for rx, steps, word in RANKS if re.search(rx, t)]
    return max(found) if found else None


_SUFFIX = re.compile(r"[,.]?\s+(inc|llc|ltd|limited|corp|corporation|co|company|plc|group|holdings|"
                     r"technologies|technology|the)\.?$", re.I)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("&", "and")).strip("-")


def company_slugs(job: Job) -> list[str]:
    """Levels.fyi company slugs to try: the company's name, then the name without "Inc", "Group"..."""
    name = " ".join(job.display_company.split())
    short = name
    while (cut := _SUFFIX.sub("", short)) != short:
        short = cut
    return list(dict.fromkeys(s for s in (_slug(name), _slug(short)) if s))[:2]


def near(job: Job, region: str, home_state: str | None) -> bool:
    """Whether a job is the user's region's: remote, or in their home state."""
    if not region:
        return False
    if job.remote or any(is_remote(loc) for loc in job.locations):
        return True
    return bool(home_state) and any(home_state.upper() in us_states(loc) for loc in job.locations)


# -- the estimate

ASK_OVER = 0.10  # ask this much over the level's median base: room to meet in the middle
ROUND = 5000


@dataclass
class Estimate:
    company: str
    family: str
    level: str
    total: int               # the level's median total compensation
    base: int | None         # the level's median base, when Levels.fyi gives it
    ask: int | None          # base salary to ask for
    where: str               # the region the numbers are for, or "US-wide"
    url: str                 # the Levels.fyi page
    why: list[str]
    company_base: int | None = None  # the median base across all the family's levels, when the page gives it
    credit: str = CREDIT

    def line(self, posted: str = "") -> str:
        """ "Ask ~$235K base · Levels.fyi L6 median $228K base / $260K total (US-wide) · posted $152K–$233K" """
        k = lambda n: f"${n / 1000:.0f}K"  # noqa: E731
        median = f"median {k(self.base)} base / {k(self.total)} total" if self.base else \
            f"median {k(self.total)} total, base not given" + (
                f"; {k(self.company_base)} base across all levels" if self.company_base else "")
        parts = [f"Ask ~{k(self.ask)} base" if self.ask else "",
                 f"Levels.fyi {self.level} {median} ({self.where})", f"posted {posted}" if posted else ""]
        return " · ".join(p for p in parts if p)

    def to_dict(self, posted: str = "") -> dict:
        return {**asdict(self), "line": self.line(posted)}


PENDING = "pending"  # not looked up yet: there wasn't time to ask Levels.fyi for every page needed


def _pick(fam: Family, title: str, years: int | None) -> tuple[int, str]:
    """The level a job's title (and the person's years) points to, as an index into fam.levels, and why."""
    names = [lv for lv, _ in fam.levels]
    senior = names.index(fam.senior) if fam.senior in names else len(names) // 2
    senior_name = names[senior]
    rank = seniority(title)
    if rank:
        steps, word = rank
        i = max(0, min(len(names) - 1, senior + steps))
        why = f'the title says {word}: {senior_name} is Levels.fyi\'s Senior' + (
            f", {abs(steps)} {'above' if steps > 0 else 'below'}" if steps else "")
    elif years is not None and fam.years:
        fits = [k for k, lv in enumerate(names[:senior + 1]) if lv in fam.years and fam.years[lv][0] <= years]
        i = fits[-1] if fits else 0
        why = f"no seniority word in the title: the highest level up to Senior ({senior_name}) whose typical " \
              f"years ({fam.years[names[i]][0]}–{fam.years[names[i]][1]}) you have" if fits else \
              "no seniority word in the title, and fewer years than any level's typical ones"
    else:
        i, why = senior, f"no seniority word in the title: Levels.fyi's Senior level ({senior_name})"
    while years is not None and i > 0 and names[i] in fam.years and fam.years[names[i]][0] > years:
        i -= 1
        why += f"; one down to {names[i]}, as {names[i + 1]} typically has {fam.years[names[i + 1]][0]}+ years"
    return i, why


def _round_up(n: float) -> int:
    return int(-(-n // ROUND) * ROUND)


def estimate(job: Job, pay, home_state: str | None, reader: Reader) -> Estimate | str | None:
    """The job's level at its company on Levels.fyi and a base to ask for; PENDING when pages it needs aren't
    known yet; None when Levels.fyi has nothing for it (then nothing is shown, never a guess)."""
    family = family_for(job.title)
    if not family:
        return None
    region = pay.region if near(job, pay.region, home_state) else ""
    pending, found = False, None
    for slug in company_slugs(job):
        tries = ([(f"companies/{slug}/salaries/{family}/locations/{region}", True)] if region else []) + \
            [(f"companies/{slug}/salaries/{family}", False)]
        for path, regional in tries:
            text = reader.page(path)
            if text is None:
                pending = True
                continue
            fam = parse_family(text, FAMILY_NAMES[family])
            if fam and fam.currency == "USD" and (regional or fam.location == US):
                found = (slug, path, fam, regional)
                break
        if found:
            break
    if not found:
        return PENDING if pending else None
    slug, path, fam, regional = found
    i, why_level = _pick(fam, job.title, pay.years)
    level, total = fam.levels[i]
    where = fam.location if regional else "US-wide"
    why = [f"{fam.company}, {FAMILY_NAMES[family]} on Levels.fyi ({where}): {len(fam.levels)} levels, "
           f"{fam.levels[0][0]} to {fam.levels[-1][0]}",
           f"Level {level}: {why_level}"]
    base = None
    if not regional:
        level_text = reader.page(f"companies/{slug}/salaries/{family}/levels/{_slug(level.split('|')[0])}")
        if level_text is None:
            return PENDING  # rather than a rougher number now and a different one later
        if level_text and (base := level_base(level_text)):
            why.append(f"{level} median base ${base:,} (its level page)")
    company_base = fam.mix[0] if fam.mix else None
    if base is None:
        # Stock grows much faster than base up the levels, so the all-levels mix says little about one level's
        # base: shown for context, never scaled into a number to ask.
        why.append(f"{level} median total ${total:,}; Levels.fyi gives no base for this level, so there's no "
                   "number to ask" + (f". Across all levels the median is ${fam.mix[0]:,} base, ${fam.mix[1]:,} "
                                      "stock" + (f", ${fam.mix[2]:,} bonus" if fam.mix[2] else "") if fam.mix else ""))
    ask = None
    if base:
        ask = _round_up(base * (1 + ASK_OVER))
        why.append(f"Ask: {ASK_OVER:.0%} over the median base, rounded up to ${ROUND // 1000}K: ${ask:,}")
        low, high = job.salary_min, job.salary_max or job.salary_min
        if low is not None and job.currency in ("", "USD"):
            if ask > high:
                ask = high
                why.append(f"capped at the posting's top, ${high:,}: a posted range is what the job can pay")
            elif ask < low:
                ask = low
                why.append(f"raised to the posting's bottom, ${low:,}")
    if years := pay.years:
        why.append(f"Your years of experience: {years}")
    url = f"{SITE}/{path}"
    return Estimate(company=fam.company, family=FAMILY_NAMES[family], level=level, total=total, base=base, ask=ask,
                    where=where, url=url, why=why, company_base=company_base)


def expected(cfg, store, job: Job, budget: int = 0, reader: Reader | None = None) -> Estimate | str | None:
    """estimate() with the watchlist's settings: from what's kept, asking Levels.fyi for up to `budget` pages (or
    through `reader`, to share one budget across jobs). None at once, asking nothing, when pay.levels is off."""
    if not cfg.pay.levels:
        return None
    return estimate(job, cfg.pay, cfg.filters.home_state, reader or Reader(store, budget))


def for_one_job(cfg, store, job: Job) -> Estimate | str | None:
    """expected() when someone looks at one job: up to ONE_JOB pages, and empty answers over an hour old asked
    again, since Levels.fyi may have the page ready by now."""
    if not cfg.pay.levels:
        return None
    return expected(cfg, store, job, reader=Reader(store, ONE_JOB, empty=EMPTY_ONE_JOB))


def as_dict(result, job: Job) -> dict | None:
    """For JSON: the estimate, {"pending": true} while it's being looked up, or None."""
    if result == PENDING:
        return {"pending": True}
    return result.to_dict(job.pay()) if isinstance(result, Estimate) else None


def below(result, min_salary: int | None) -> str | None:
    """A warning when the level's median base is under the watchlist's minimum pay."""
    if isinstance(result, Estimate) and result.base and min_salary and result.base < min_salary:
        return (f"Levels.fyi: {result.level} median base ${result.base / 1000:.0f}K ({result.where}) is below "
                f"${min_salary / 1000:.0f}K")
    return None
