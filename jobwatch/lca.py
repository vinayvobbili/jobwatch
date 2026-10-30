"""Base pay filed for H-1B hires, from the U.S. Department of Labor's LCA disclosure data: a second pay source next
to Levels.fyi (levels.py), for personal use.

Every employer that hires on an H-1B, H-1B1 or E-3 visa files a Labor Condition Application naming the job, the
worksite and the wage it will pay. The DOL (OFLC) publishes those filings for each federal fiscal year (Oct 1 to Sep
30) as Excel files, cumulative and updated each quarter, on https://www.dol.gov/agencies/eta/foreign-labor/performance.

`jobwatch lca update` reads that page for the current and the previous fiscal year's newest files (the links are
found on the page, never hardcoded), downloads each one (robots.txt is read first, and requests are a couple of
seconds apart), and keeps only the certified, full-time rows and the columns an estimate needs in a small SQLite
file next to the state file (lca.db). The Excel files are deleted once read. `jobwatch ui` refreshes it about
every 30 days, once it has been asked for by hand. Nothing here is asked of the DOL until then.

An estimate is what an employer filed as the base wage for a title like the job's: a floor the employer promised
an H-1B hire, not total compensation (no bonus or stock), and not a posted range.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

from . import sources
from .contacts import company_key
from .levels import seniority
from .models import Job
from .text import us_states

SITE = "https://www.dol.gov"
PAGE = f"{SITE}/agencies/eta/foreign-labor/performance"
CREDIT = "Data: U.S. DOL LCA disclosures"
LABEL = "Base pay filed for H-1B hires (not total compensation)"
FILE = "lca.db"
REFRESH = timedelta(days=30)  # how old the cache may get before the schedule refreshes it
YEARS = 2                     # fiscal years kept: the current and the previous one
PAUSE = 2.0                   # seconds between two requests to the DOL
MIN_FILINGS = 3               # fewer matching filings than this is no estimate
EXAMPLES = 3
US = "US-wide"
# Hours in a work year and so on, to turn the unit a wage was filed in into a yearly one:
PER_YEAR = {"year": 1, "month": 12, "bi-weekly": 26, "biweekly": 26, "week": 52, "hour": 2080}
SANE = (30_000, 2_000_000)    # yearly wages outside this are typing errors (a monthly wage filed as yearly...)
COLUMNS = ("CASE_NUMBER", "CASE_STATUS", "FULL_TIME_POSITION", "EMPLOYER_NAME", "JOB_TITLE", "SOC_TITLE",
           "WORKSITE_CITY", "WORKSITE_STATE", "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO", "WAGE_UNIT_OF_PAY",
           "PW_WAGE_LEVEL", "BEGIN_DATE")


class LcaError(ValueError):
    pass


_last = [0.0]


def _pause(seconds: float):
    time.sleep(max(0.0, _last[0] + seconds - time.monotonic()))
    _last[0] = time.monotonic()


def cache_path(cfg) -> Path:
    """The cache, next to the state file."""
    return Path(cfg.state).expanduser().with_name(FILE)


# -- which files

_LINK = re.compile(r"""href=["']([^"']*LCA_Disclosure_Data_FY(\d{4})_Q([1-4])\.xlsx)["']""", re.I)


def find_files(html: str) -> list[tuple[int, int, str]]:
    """(fiscal year, quarter, link) of the newest file of each of the last YEARS fiscal years on the page, newest
    first. Quarters are cumulative, so the last one out for a year has all of it."""
    best: dict[int, tuple[int, str]] = {}
    for href, fy, q in _LINK.findall(html):
        if (int(q), href) > best.get(int(fy), (0, ""))[:2]:
            best[int(fy)] = (int(q), urljoin(PAGE, href))
    return [(fy, best[fy][0], best[fy][1]) for fy in sorted(best, reverse=True)[:YEARS]]


# -- reading a file

def yearly(amount, unit) -> int | None:
    """A wage filed per hour, week, bi-week, month or year, as a yearly one; None when it isn't a plausible one."""
    try:
        n = float(str(amount).replace(",", "").replace("$", ""))
    except ValueError:
        return None
    per = PER_YEAR.get(str(unit or "").strip().lower())
    return round(n * per) if per and SANE[0] <= n * per <= SANE[1] else None


# Words an employer's name has in the DOL's files and not on its job board ("Globex Systems, Inc." and "Globex"):
_EXTRA = {"systems", "usa", "us", "america", "americas", "international", "intl"}


def employer_key(name: str) -> str:
    """contacts.company_key, and without words like "Systems" too: "Globex Systems, Inc." -> "globex"."""
    key = company_key(name)
    return " ".join(w for w in key.split() if w not in _EXTRA) or key


def job_keys(job: Job) -> list[str]:
    return [k for k in dict.fromkeys(employer_key(n) for n in (job.display_company, job.company)) if k]


def _year(value) -> int | None:
    if hasattr(value, "year"):
        return value.year
    m = re.search(r"\b(20\d\d)\b", str(value or ""))
    return int(m.group(1)) if m else None


def read_rows(path: Path):
    """The certified, full-time rows of an LCA disclosure Excel file as (case, employer, title, city, state, wage
    from, wage to, level, year), streamed so the hundreds of megabytes are never all in memory."""
    try:
        import openpyxl
    except ImportError:
        raise LcaError("reading the DOL's Excel files needs openpyxl: pip install 'jobwatch[lca]'") from None
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        head = [str(c or "").strip().upper() for c in next(rows)]
        missing = [c for c in COLUMNS if c not in head]
        if missing:
            raise LcaError(f"{path.name}: no {', '.join(missing)} column; did the DOL change its layout?")
        at = {c: head.index(c) for c in COLUMNS}
        for row in rows:
            cell = {c: row[i] if i < len(row) else None for c, i in at.items()}
            # "Certified - Withdrawn" and "Certified - Expired" aren't hires that went ahead.
            if str(cell["CASE_STATUS"] or "").strip().lower() != "certified" \
                    or str(cell["FULL_TIME_POSITION"] or "").strip().upper() != "Y":
                continue
            unit = cell["WAGE_UNIT_OF_PAY"]
            low, high = yearly(cell["WAGE_RATE_OF_PAY_FROM"], unit), yearly(cell["WAGE_RATE_OF_PAY_TO"], unit)
            employer, title = str(cell["EMPLOYER_NAME"] or "").strip(), str(cell["JOB_TITLE"] or "").strip()
            if not (low and employer and title):
                continue
            yield (str(cell["CASE_NUMBER"] or "").strip(), employer, title, str(cell["WORKSITE_CITY"] or "").strip(),
                   str(cell["WORKSITE_STATE"] or "").strip().upper(), low, high,
                   str(cell["PW_WAGE_LEVEL"] or "").strip(), _year(cell["BEGIN_DATE"]))
    finally:
        wb.close()


SCHEMA = """
CREATE TABLE filings (case_no TEXT PRIMARY KEY, fy INTEGER, employer TEXT, ekey TEXT, title TEXT, city TEXT,
                      state TEXT, low INTEGER, high INTEGER, level TEXT, year INTEGER);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def index_file(db: sqlite3.Connection, path: Path, fy: int, say=print) -> int:
    """Add a file's rows to the cache; how many were kept. A case in two files stays as the first one had it."""
    keys: dict[str, str] = {}
    kept = seen = 0
    batch = []
    for case, employer, title, city, state, low, high, level, year in read_rows(path):
        seen += 1
        if employer not in keys:
            keys[employer] = employer_key(employer)
        batch.append((case, fy, employer, keys[employer], title, city, state, low, high, level, year))
        if len(batch) >= 5000:
            kept += _insert(db, batch)
            batch = []
            say(f"  indexing FY{fy}: {kept:,} certified full-time filings so far")
    kept += _insert(db, batch)
    return kept


def _insert(db: sqlite3.Connection, batch: list[tuple]) -> int:
    before = db.total_changes
    db.executemany("INSERT OR IGNORE INTO filings VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
    return db.total_changes - before


def download(url: str, dest: Path, say=print, timeout: float = 60) -> int:
    """Stream a file to `dest`, saying how far along it is; its size in bytes."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": sources.USER_AGENT})
    done, shown = 0, -1
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                step = done * 10 // total if total else done >> 26
                if step != shown:
                    shown = step
                    say(f"  downloading {url.rsplit('/', 1)[-1]}: {done / 1e6:,.0f}"
                        + (f" of {total / 1e6:,.0f} MB" if total else " MB"))
    except urllib.error.HTTPError as e:
        raise sources.SourceError(f"{url}: HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise sources.SourceError(f"{url}: {e}") from None
    return done


def stale(path: Path, now: datetime | None = None) -> bool:
    """Whether the cache exists and is older than REFRESH. One that was never asked for is not stale: the
    schedule only keeps up what was started by hand."""
    if not path.is_file():
        return False
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = db.execute("SELECT v FROM meta WHERE k='updated'").fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return True
    return not row or (now or datetime.now(timezone.utc)) - datetime.fromisoformat(row[0]) >= REFRESH


def update(path: Path, say=print, get_text=None, fetch=None, robots=None, pause: float | None = None) -> dict:
    """Rebuild the cache from the DOL's newest files for the current and previous fiscal year. It's built beside
    the old one and swapped in when done, so a failed run keeps what was there. `fetch(url, dest)` stands in for
    the download. Returns {"files": [...], "rows": n, "bytes": size of the cache}."""
    from .alerts import Robots
    get_text = get_text or sources.get_text
    robots = robots or Robots(get_text)
    gap = PAUSE if pause is None else pause
    fetch = fetch or (lambda url, dest: download(url, dest, say))
    if not robots.allowed(PAGE):
        raise LcaError(f"{SITE}/robots.txt asks robots not to read {PAGE}")
    _pause(gap)
    say(f"Reading {PAGE}")
    files = find_files(get_text(PAGE))
    if not files:
        raise LcaError(f"{PAGE} links no LCA disclosure files (LCA_Disclosure_Data_FY..._Q....xlsx); "
                       "did the DOL move them?")
    path.parent.mkdir(parents=True, exist_ok=True)
    new = path.with_name(path.name + ".new")
    new.unlink(missing_ok=True)
    db = sqlite3.connect(new)
    done = []
    try:
        db.executescript(SCHEMA)
        for fy, q, url in files:
            if not robots.allowed(url):
                raise LcaError(f"{SITE}/robots.txt asks robots not to read {url}")
            part = path.with_name(f"lca-download-FY{fy}_Q{q}.xlsx")  # openpyxl wants the .xlsx
            _pause(gap)
            say(f"FY{fy} Q{q}: {url}")
            try:
                size = fetch(url, part)
                n = index_file(db, part, fy, say)
            finally:
                part.unlink(missing_ok=True)  # hundreds of MB, and everything needed is in the cache now
            db.commit()
            say(f"  FY{fy} Q{q}: {size / 1e6:,.0f} MB read, {n:,} certified full-time filings kept")
            done.append({"fy": fy, "quarter": q, "url": url, "bytes": size, "rows": n})
        db.execute("CREATE INDEX filings_ekey ON filings (ekey)")
        db.execute("INSERT INTO meta VALUES ('updated', ?)", (datetime.now(timezone.utc).isoformat(),))
        db.commit()
        rows = db.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    except BaseException:
        db.close()
        new.unlink(missing_ok=True)
        raise
    db.close()
    os.replace(new, path)
    say(f"Done: {rows:,} filings in {path} ({path.stat().st_size / 1e6:,.0f} MB)")
    return {"files": done, "rows": rows, "bytes": path.stat().st_size}


# -- matching a job

# Words that say the level, which levels.seniority reads, and filler, left out of a title when comparing titles.
_NOISE = {"a", "an", "and", "of", "the", "for", "in", "to", "at", "remote", "us", "usa", "i", "ii", "iii", "iv", "v",
          "vi", "sr", "jr", "senior", "staff", "principal", "lead", "junior", "associate", "entry", "level",
          "distinguished", "fellow", "director", "head", "hybrid", "onsite", "contract"}
_ABBREVIATIONS = {"swe": ("software", "engineer"), "sde": ("software", "engineer"),
                  "sre": ("site", "reliability", "engineer"), "ml": ("machine", "learning"),
                  "qa": ("quality", "assurance")}


def _stem(word: str) -> str:
    if len(word) > 6 and word.endswith("ing"):
        return word[:-3]
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _words(text: str) -> frozenset[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        out.extend(_ABBREVIATIONS.get(w, (w,)))
    return frozenset(_stem(w) for w in out if w not in _NOISE and not w.isdigit())  # digits: a posting's id


def title_words(title: str) -> list[frozenset[str]]:
    """The words of a title that say what the work is, as the readings to try: "Senior Software Engineer,
    Platform" -> {software, engineer} (the team after a comma left out), then the whole title's. Seniority words
    (levels.seniority reads those), filler and numbers aren't words of the work."""
    plain = re.sub(r"\([^)]*\)", " ", title)
    head = plain.split(",")[0]
    readings = [_words(head)] if len(head.split()) > 1 else []
    return [r for r in dict.fromkeys([*readings, _words(plain)]) if r]


def same_work(job_words: list[frozenset[str]], other: list[frozenset[str]]) -> bool:
    """Whether two titles name the same kind of work: their shared words are most of both (Dice, 0.6), by any of
    the job's readings against the filing's whole title."""
    return bool(other) and any(2 * len(j & other[-1]) / (len(j) + len(other[-1])) >= 0.6 for j in job_words)


def percentile(values: list[int], p: float) -> int:
    v = sorted(values)
    at = (len(v) - 1) * p
    low = int(at)
    return round(v[low] + (v[min(low + 1, len(v) - 1)] - v[low]) * (at - low))


@dataclass
class Estimate:
    company: str                # as the employer filed its name
    title: str                  # the filing title most of the matches had
    where: str                  # "Boulder, CO", "CO" or "US-wide"
    count: int                  # filings matched
    median: int                 # yearly base
    p25: int
    p75: int
    levels: dict[str, int]      # prevailing wage levels (I to IV) the filings were at, and how many each
    examples: list[dict]        # the newest few: title, city, state, wage, year
    why: list[str]
    years: tuple[int, int] | None = None  # the years the jobs start in
    url: str = PAGE
    credit: str = CREDIT
    label: str = LABEL
    rows: list[dict] = field(default_factory=list, repr=False)  # every match, newest first (not in to_dict)

    def line(self) -> str:
        """ "H-1B filings: median $168K base (25th–75th $155K–$182K), 42 filings (CO)" """
        k = lambda n: f"${n / 1000:.0f}K"  # noqa: E731
        return (f"H-1B filings: median {k(self.median)} base (25th–75th {k(self.p25)}–{k(self.p75)}), "
                f"{self.count} filing{'s' if self.count != 1 else ''} ({self.where})")

    def to_dict(self) -> dict:
        return {**{k: v for k, v in asdict(self).items() if k != "rows"}, "line": self.line()}


def _by_recency(row: dict):
    return row["year"] or 0, row["wage"]


class Index:
    """The cache, read-only."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> Index | None:
        """The cache at `path`, or None when it hasn't been made (or can't be read)."""
        if not path.is_file():
            return None
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            db.execute("SELECT 1 FROM filings LIMIT 1")
        except sqlite3.Error:
            return None
        return cls(db)

    def close(self):
        self.db.close()

    def info(self) -> dict:
        row = self.db.execute("SELECT v FROM meta WHERE k='updated'").fetchone()
        years = self.db.execute("SELECT fy, COUNT(*) n FROM filings GROUP BY fy ORDER BY fy DESC").fetchall()
        return {"updated": row[0] if row else None, "rows": sum(r["n"] for r in years),
                "years": {r["fy"]: r["n"] for r in years}}

    def employer_rows(self, keys: list[str]) -> list[dict]:
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        return [{"employer": r["employer"], "title": r["title"], "city": r["city"], "state": r["state"],
                 "wage": r["low"], "high": r["high"], "level": r["level"], "year": r["year"] or r["fy"],
                 "words": title_words(r["title"]), "rank": (seniority(r["title"]) or (None,))[0]}
                for r in self.db.execute(f"SELECT * FROM filings WHERE ekey IN ({marks})", keys)]

    def titles(self, keys: list[str], limit: int = 15) -> list[dict]:
        """An employer's most filed titles, with how many filings and the median base of each."""
        by: dict[str, list[int]] = {}
        for r in self.employer_rows(keys):
            by.setdefault(r["title"].lower(), []).append(r["wage"])
        top = sorted(by.items(), key=lambda kv: -len(kv[1]))[:limit]
        return [{"title": t, "count": len(w), "median": percentile(w, 0.5)} for t, w in top]

    def estimate(self, keys: list[str], title: str, cities: list[str] = (), states: list[str] = ()) -> Estimate | None:
        """Filings by the employer for the same kind of work at the same seniority: those in one of the cities
        if there are MIN_FILINGS, else in one of the states, else anywhere in the US; None when even that is
        fewer than MIN_FILINGS."""
        words = title_words(title)
        rank = (seniority(title) or (None,))[0]
        matches = [r for r in self.employer_rows(keys) if r["rank"] == rank and same_work(words, r["words"])]
        cities = {c.lower() for c in cities if c}
        tiers = ((lambda r: r["city"].lower() in cities, "{city}"), (lambda r: r["state"] in states, "{state}"),
                 (lambda r: True, US))
        for test, tier in tiers:
            near = sorted((r for r in matches if test(r)), key=_by_recency, reverse=True)
            if len(near) >= MIN_FILINGS:
                where = tier.format(city=f"{near[0]['city'].title()}, {near[0]['state']}", state=", ".join(states))
                break
        else:
            return None
        wages = [r["wage"] for r in near]
        common = lambda field_: Counter(r[field_] for r in near).most_common(1)[0][0]  # noqa: E731
        levels = dict(sorted(Counter(r["level"] for r in near if r["level"]).items()))
        examples = [{k: r[k] for k in ("title", "city", "state", "wage", "year")} for r in near[:EXAMPLES]]
        years = [r["year"] for r in near if r["year"]]
        seen = ", ".join(f"{lv} x{n}" for lv, n in levels.items())
        same = ", the same seniority as the job's title" if rank is not None else ""
        why = [f"{len(near)} certified full-time LCA filings by {common('employer')} for titles like "
               f"\"{common('title')}\" ({where}){same}",
               "Each is the base wage the employer filed for an H-1B hire: no bonus or stock, and a floor rather "
               "than a negotiated number",
               *([f"Prevailing wage levels filed: {seen}"] if levels else []),
               "Examples: " + "; ".join(f"{e['title']}, {e['city'].title()} {e['state']}, ${e['wage']:,}"
                                        + (f" ({e['year']})" if e["year"] else "") for e in examples)]
        return Estimate(company=common("employer"), title=common("title"), where=where, count=len(near),
                        median=percentile(wages, 0.5), p25=percentile(wages, 0.25), p75=percentile(wages, 0.75),
                        levels=levels, examples=examples, why=why,
                        years=(min(years), max(years)) if years else None, rows=near)


def places(job: Job) -> tuple[list[str], list[str]]:
    """(cities, states) of a job's locations: "Boulder, CO" -> Boulder, CO. Remote ones name no city."""
    cities, states = [], []
    for loc in job.locations:
        states += us_states(loc)
        head = loc.split(",")[0].strip()
        if head and not re.search(r"remote|united states|usa|hybrid", head, re.I) and not us_states(head):
            cities.append(head)
    return cities, list(dict.fromkeys(states))


def for_job(index: Index | None, job: Job) -> Estimate | None:
    """The job's estimate from the cache; None without a cache, an employer filed under another name, or fewer
    than MIN_FILINGS matches (then nothing is shown, never a guess)."""
    if index is None:
        return None
    cities, states = places(job)
    return index.estimate(job_keys(job), job.title, cities, states)


def for_one_job(cfg, job: Job) -> Estimate | None:
    index = Index.open(cache_path(cfg))
    try:
        return for_job(index, job)
    finally:
        if index:
            index.close()


def as_dict(est: Estimate | None) -> dict | None:
    return est.to_dict() if est else None
