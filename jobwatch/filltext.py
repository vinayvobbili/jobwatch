"""Filling in the posting text of jobs that have none.

A job that came from an alert email or a list has its title, company, place and sometimes pay, and nothing else:
LinkedIn and Indeed put the posting itself behind a sign-in, and jobwatch never fetches linkedin.com or indeed.com.
Without text a job can't be fit-scored, tailored for or prepped. `fill_text` gives each such job text from the
first source that can be read:

1. the company's own board (a watched one, the one already found for the company, or one guessed from its name),
2. the job's own link, when it isn't LinkedIn's or Indeed's and is a posting jobwatch can read,
3. the posting page in the person's own browser, for a LinkedIn or Indeed link: jobwatch can't open it, so the job
   is listed for the browser (`jobwatch fill-text --open`: the Queue card's Read posting button, or Chrome with the
   person signed in, read the page and hand the text back to `jobwatch fill-text --set KEY`).

`posting_from_page` is the one reader of a LinkedIn or Indeed posting page's text (what `get_page_text` or the
page's innerText gives): the description alone, without the page's menus, "more jobs" and footer, and a plain reason
when the page is a sign-in wall or a captcha instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import alerts, sources
from .models import Job
from .store import MANUAL, Store

SITES = {"linkedin": "LinkedIn", "indeed": "Indeed"}
STATUSES = ("new", "shown", "queued")  # the jobs one is about to look at or apply to
CAP = 25  # jobs looked for per run: each costs a few requests
MIN_TEXT = 200  # a description shorter than this is not a posting

# What each site writes around the description, in the page's text
_LINKEDIN_START = re.compile(r"^About the job\s*$", re.M)
_LINKEDIN_END = re.compile(r"^(?:[….]{1,3}\s*more|Benefits found in job post|Set alert for similar jobs|Show more|"
                           r"About the company|More jobs)\s*$", re.M)
_INDEED_START = re.compile(r"^Full job description\s*$", re.M)
_INDEED_END = re.compile(r"^(?:Report job|Hiring Lab|Career advice)\s*$", re.M)
_LINKEDIN_CLOSED = re.compile(r"^(?:Not currently accepting applications|No longer accepting applications)\s*$",
                              re.M | re.I)
_WALL = [
    (re.compile(r"verify you are (?:a )?human|are you a robot|captcha|security check|just a moment|"
                r"additional verification required", re.I), "it shows a captcha or a security check"),
    (re.compile(r"\b(?:sign in|log in|join now|authwall)\b", re.I), "it asks to sign in"),
]


class PageError(ValueError):
    """A posting page's text that holds no posting: what it shows instead, in a few plain words."""


@dataclass
class PagePosting:
    site: str
    text: str
    closed: bool = False  # the site says it's not taking applications any more


def browser_site(url: str) -> str:
    """"linkedin" or "indeed" for a link to one job there (a link jobwatch can't read, only the person's browser can),
    else ""."""
    u = urlparse(str(url or ""))
    host, path = u.netloc.lower(), u.path
    if host.endswith("linkedin.com") and path.startswith("/jobs/view/"):
        return "linkedin"
    if host.endswith("indeed.com") and path.startswith(("/viewjob", "/rc/clk", "/m/viewjob")):
        return "indeed"
    return ""


def posting_from_page(site: str, page_text: str) -> PagePosting:
    """The description on a LinkedIn or Indeed posting page, from the page's text. PageError when the page holds
    none: the page says it wants a sign-in or shows a captcha, or it isn't a posting."""
    if site not in SITES:
        raise PageError(f"can't read postings on {site or 'that site'}")
    start, end = (_LINKEDIN_START, _LINKEDIN_END) if site == "linkedin" else (_INDEED_START, _INDEED_END)
    s = start.search(page_text)
    if s:
        rest = page_text[s.end():]
        e = end.search(rest)
        text = (rest[:e.start()] if e else rest).strip()
        if len(text) >= MIN_TEXT:
            closed = site == "linkedin" and bool(_LINKEDIN_CLOSED.search(page_text[:s.start()]))
            return PagePosting(site, text, closed)
    for pattern, why in _WALL:
        if pattern.search(page_text[:3000]):
            raise PageError(f"{SITES[site]} didn't show the posting: {why}")
    raise PageError(f"{SITES[site]}'s page has no posting text on it (is it the job's own page?)")


NO_TEXT = ("no_text", "No posting text: add a link to the company's posting or paste it")


def no_text_why(job: Job) -> tuple[str, str]:
    """The `unscored` reason (code, text) of a job with no posting text: what is in the way, by where its link goes."""
    site = browser_site(job.url)
    if site:
        return ("no_text", f"No posting text: {SITES[site]} blocks automatic reading; open it and press Read posting")
    return NO_TEXT


@dataclass
class Outcome:
    job: Job
    how: str  # board, link, browser (read now), needs_browser, none
    note: str = ""


def textless(store: Store, statuses: tuple[str, ...] = STATUSES) -> list[Job]:
    """The open jobs added by hand or from an alert or list, in these statuses, with no posting text."""
    return [j for j, _ in store.iter_jobs(statuses) if j.source == MANUAL and not j.description.strip()]


def fill_text(cfg, store: Store, page=None, get=None, read_browser=None, statuses: tuple[str, ...] = STATUSES,
              limit: int = CAP, dry_run: bool = False, keys: tuple[str, ...] = ()) -> list[Outcome]:
    """Give each of these jobs without posting text some, from the first source that reads (see the module's
    docstring). `read_browser(url) -> page text` reads a LinkedIn or Indeed page in the person's browser; without
    it those jobs come back as needs_browser. Up to `limit` jobs; dry_run records nothing."""
    resolver = alerts._Resolver(cfg.boards, page, store)
    out: list[Outcome] = []
    for job in textless(store, statuses):
        if keys and job.key not in keys:
            continue
        if len(out) >= limit:
            break
        out.append(_fill_one(store, job, resolver, get, read_browser, dry_run))
    done = [o.job for o in out if o.how in ("board", "link", "browser")]
    if done and not dry_run:
        store.log("mail", f"Filled in the posting text of {len(done)} alert job{'s' * (len(done) != 1)}",
                  detail=[f"{j.display_company}: {j.title}" for j in done], jobs=[j.key for j in done])
    return out


def _fill_one(store: Store, job: Job, resolver, get, read_browser, dry_run: bool) -> Outcome:
    try:
        found = resolver.on_board(job.title, job.display_company, ", ".join(job.locations))
    except sources.SourceError:
        found = None
    if found:
        if not dry_run:
            alerts.fill_from_board(store, job, found)
        return Outcome(job, "board", f"found on the company's board: {found.url}")
    site = browser_site(job.url)
    if job.url and not site:
        try:
            posting = sources.posting(job.url, get)
        except sources.SourceError as e:
            return Outcome(job, "none", f"couldn't read {job.url}: {e}")
        if posting and posting.description.strip():
            if not dry_run:
                store.set_description(job.key, posting.description, posting)
            return Outcome(job, "link", f"read from {job.url}")
    if not site:
        return Outcome(job, "none", "no link jobwatch can read: add the posting's link or text")
    if read_browser is None:
        return Outcome(job, "needs_browser", job.url)
    try:
        read = posting_from_page(site, read_browser(job.url))
    except PageError as e:
        return Outcome(job, "needs_browser", f"{e} ({job.url})")
    if not dry_run:
        save_page_posting(store, job.key, read)
    return Outcome(job, "browser", f"read from the {SITES[site]} page in the browser")


def save_page_posting(store: Store, key: str, read: PagePosting):
    """Keep what a browser read of a LinkedIn or Indeed posting page gave as the job's text, with a note saying
    where it came from (and that the site says the posting is closed, when it does: the person decides)."""
    store.set_description(key, read.text)
    if job := store.job(key):
        store.log("mail", f"Read the posting text of {job.display_company}: {job.title} from the "
                  f"{SITES[read.site]} page in the browser", jobs=[key])
    store.add_note(key, f"Posting text read from the {SITES[read.site]} page, in the person's own browser")
    if read.closed:
        store.add_note(key, f"{SITES[read.site]} says it is not accepting applications any more")


def summary(outcomes: list[Outcome], dry_run: bool = False) -> str:
    """What a run did, in a few lines: a line per job, then the counts."""
    if not outcomes:
        return "Every queued, new and shown job has its posting text."
    out = [f"{'Dry run: nothing recorded. ' if dry_run else ''}{len(outcomes)} job(s) with no posting text:"]
    for o in outcomes:
        label = {"board": "filled", "link": "filled", "browser": "filled", "needs_browser": "needs the browser",
                 "none": "no source"}[o.how]
        out.append(f"  {label}: {o.job.display_company}: {o.job.title}  {o.job.key}\n      {o.note}")
    done = sum(o.how in ("board", "link", "browser") for o in outcomes)
    waiting = sum(o.how == "needs_browser" for o in outcomes)
    out.append(f"{done} {'would be ' if dry_run else ''}filled in; {waiting} on LinkedIn or Indeed, which only your "
               "browser can read (`jobwatch fill-text --open`).")
    return "\n".join(out)


def open_list(outcomes_or_jobs: list[Job]) -> str:
    """The jobs only the browser can read, one to a line pair: what it is, then its link on its own line, to open
    each in a new tab for the extension's Read posting (or Chrome) to read."""
    out = []
    for j in outcomes_or_jobs:
        out += [f"{j.display_company}: {j.title}  {j.key}", f"  {j.url}"]
    return "\n".join(out) if out else "No job is waiting for a LinkedIn or Indeed page to be read."
