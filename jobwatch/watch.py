"""The pipeline: check every board, then build a ranked digest of new matches."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import alerts, dupes, lca, levels, linkedin, sources, suggest
from .config import UNKNOWN_SOURCE, Board, Config
from .contacts import Contacts, company_key
from .filters import KINDS, Filters, red_flags, reject_reason, rejection, relevance, search_terms, title_ok
from .models import Job
from .score import ScoringUnavailable, brief, resume_id, score_jobs, turn
from .store import MANUAL, STAGES, Store


@dataclass
class FetchReport:
    boards: int = 0
    jobs: int = 0
    new: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # "source:board" -> error
    warnings: dict[str, str] = field(default_factory=dict)  # "source:board" -> what to do about it
    duplicates: dict[str, dupes.Match] = field(default_factory=dict)  # new job's key -> the job acted on it matches
    emails: int | None = None  # job-alert emails read from the mailbox (alerts.imap); None: no mailbox set


MAILBOX = "alerts.imap"  # the errors key for a mailbox that couldn't be read


HOSTED_KEEP = timedelta(days=1)  # how long an answer about a board's hosted job pages is trusted


class HostedPages:
    """Whether boards' hosted job pages are up (see sources.Hosted): each board's own page is read at most once a
    day, where robots.txt allows, and the answer kept in the store. When it can't be read now, the last answer
    stands (or none, the first time): a network error changes nothing. Use the store from one thread; `ask`, the
    one request, can run in others."""

    def __init__(self, store: Store, page=None):
        self.store, self.page = store, page
        self._robots = None

    def due(self, boards: list[tuple[str, str]]) -> set[tuple[str, str]]:
        """The (source, board) pairs to ask about now: a source with the check, not asked in the last day, and
        robots.txt allows reading the page (it's read once per site)."""
        now, out = datetime.now(timezone.utc), set()
        for source, board in boards:
            if not (url := sources.hosted_url(source, board)):
                continue
            kept = self.store.hosted_page(source, board)
            if kept and now - kept[1] < HOSTED_KEEP:
                continue
            if self._robots is None:
                from .alerts import Robots  # alerts reads job pages the same careful way
                self._robots = Robots(self.page)
            if self._robots.allowed(url):
                out.add((source, board))
        return out

    def ask(self, source: str, board: str) -> bool | None:
        return sources.hosted_up(source, board, self.page)

    def answer(self, source: str, board: str, fresh: bool | None) -> bool | None:
        """Keep a fresh answer; return it, or the last one kept when there's none (None: never known)."""
        if fresh is not None:
            self.store.save_hosted_page(source, board, fresh)
            return fresh
        kept = self.store.hosted_page(source, board)
        return kept[0] if kept else None

    def check(self, source: str, board: str) -> bool | None:
        """due, ask and answer for one board."""
        fresh = self.ask(source, board) if (source, board) in self.due([(source, board)]) else None
        return self.answer(source, board, fresh)


def offline_note(job: Job, careers: str = "") -> str:
    """The line shown with a job whose board's hosted pages are offline: where to apply instead."""
    system, company = sources.SOURCES[job.source].hosted.name, job.display_company
    if careers:
        return f"{company}'s {system} job pages are offline: this job's link goes to {company}'s own careers site."
    return (f"{company}'s {system} job pages are offline (its link shows \"Page not found\"): apply through "
            f"{company}'s own careers site.")


def mark_hosted(job: Job, up: bool | None, careers: str = "") -> bool:
    """Point a job at the company's careers site (`careers`, when the watchlist gives one) and say why, when its
    board's hosted pages are offline; put it back when they're up again. None (not known) changes nothing.
    Without `careers`, a careers link the job was given before is kept. Returns whether the job changed."""
    before = (job.url, job.posting_url, job.link_note)
    if up is not None:
        own, careers = job.posting_url or job.url, careers or (job.url if job.posting_url else "")
        if up:
            job.url, job.posting_url, job.link_note = own, "", ""
        else:
            job.url, job.posting_url, job.link_note = careers or own, own if careers else "", \
                offline_note(job, careers)
    return (job.url, job.posting_url, job.link_note) != before


def offline_warning(b: Board) -> str:
    """What `jobwatch fetch` says about a board whose hosted pages are offline and has no careers link."""
    system = sources.SOURCES[b.source].hosted.name
    return (f"its {system} job pages are offline (\"Page not found\") though its jobs are still listed: add the "
            f"company's careers site to the watchlist, {{board: {b.entry}, careers: https://...}}")


def fetch_all(cfg: Config, store: Store, workers: int = 8, get=None, page=None, mail=None,
              reread: tuple[str, ...] = (), by: str = "") -> FetchReport:
    """Pull every board in the watchlist and record what is new. Boards that fail are reported and skipped.

    A searched board's postings are read in full once; the boards named in `reread` (by entry, board or name) have
    every matching posting read again, as after a fix to how their pages are read.

    With a mailbox set (alerts.imap), the job-alert emails in it (LinkedIn's, Indeed's and the rest) are read
    too, the same as `jobwatch alerts --imap`, so their jobs come in with every check; `mail` replaces the IMAP
    connection. A mailbox that can't be read is reported like a failed board.

    For a source whose hosted job pages a company can switch off (Ashby), the board's own page is read too, once
    a day at most (see HostedPages; `page` replaces that HTTP call): when it's offline, the board's jobs link to
    its careers: site, or say to apply there. The check is recorded in the store (Store.last_fetch), and so is
    what it did, for the Activity tab (Store.log, started `by` the schedule, the page...). A new post in a thread of
    many companies' posts (HN) that passes the filters, from a company whose board isn't watched, makes that
    company a suggestion to watch (see suggest.py)."""
    report = FetchReport()
    for b in cfg.unknown:  # a source this version can't read: say so, and check the rest
        report.errors[b.entry] = UNKNOWN_SOURCE
    # Big boards are searched for the watchlist's titles (a board's own, when its entry has filters), and a
    # posting is read in full once: the store has it.
    again = {r.lower() for r in reread}
    if missing := again - {n.lower() for b in cfg.boards for n in (b.entry, b.board, b.name) if n}:
        raise ValueError(f"no watched board named {', '.join(sorted(missing))}: see `jobwatch list`")
    known = {b: store.board_jobs(b.source, b.board) for b in cfg.boards if sources.SOURCES[b.source].search
             and not again & {b.entry.lower(), b.board.lower(), (b.name or "").lower()}}
    hosted = HostedPages(store, page)
    due = hosted.due([(b.source, b.board) for b in cfg.boards])

    def one(b: Board):
        f = cfg.filters_of(b)
        try:
            jobs = sources.fetch(b.source, b.board, get, search=search_terms(f), wanted=lambda t: title_ok(t, f),
                                 known=known.get(b))
        except sources.Partial as e:  # rate-limited partway: keep what was read, close nothing
            partial[b.entry] = str(e)
            return b, e.jobs, None, None
        except sources.SourceError as e:
            return b, None, str(e), None
        return b, jobs, None, hosted.ask(b.source, b.board) if (b.source, b.board) in due else None

    new: list[Job] = []
    partial: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for b, jobs, err, up in pool.map(one, cfg.boards):
            if err:
                report.errors[b.entry] = err
                continue
            if b.entry in partial:
                report.warnings[b.entry] = f"read partway: {partial[b.entry]}"
            up = hosted.answer(b.source, b.board, up) if sources.SOURCES[b.source].hosted else None
            src = sources.SOURCES[b.source]
            for j in jobs:
                # A searched board's name is only its tenant id ("acme"): the watchlist's name reads better. A
                # thread of many companies' posts (HN) names each post's own.
                if not src.many_companies:
                    j.company_name = (b.name or j.company_name) if src.search else (j.company_name or b.name)
                mark_hosted(j, up, b.careers)
            if up is False and not b.careers:
                report.warnings[b.entry] = offline_warning(b)
            report.boards += 1
            report.jobs += len(jobs)
            keys = set(found := store.sync(b.source, b.board, jobs, close_missing=b.entry not in partial))
            report.new += found
            new += [j for j in jobs if j.key in keys]
            if src.many_companies and keys:
                # A matching post from a company whose board isn't watched: a suggestion to watch it (see
                # suggest.py). Only what the post says is kept; nothing is looked for here.
                try:
                    suggest.record_posts(store, cfg, [j for j in jobs if j.key in keys])
                except Exception as e:  # a suggestion is a hint: it never fails a check
                    report.warnings[b.entry] = f"companies to watch not noted: {e}"
    checked = len(report.new)  # the boards' new jobs; the mailbox's come next
    if cfg.imap:
        try:
            got = alerts.intake(cfg, store, alerts.imap_messages(cfg.imap, connect=mail))
        except alerts.AlertError as e:
            report.errors[MAILBOX] = str(e)
            store.log("mail", f"Couldn't read job-alert emails from {cfg.imap.host}", ok=False, detail=[str(e)], by=by,
                      notable=True)
        else:
            report.emails = got.emails
            report.new += [f.key for f in got.found if f.result == "new"]  # intake marks their duplicates
            fresh = [f for f in got.found if f.result == "new"]
            yours = for_you(cfg, [f.job for f in fresh if f.job])
            store.log("mail", f"Read {plural(got.emails, 'job-alert email')}: {found_line(len(yours))}",
                      detail=[*[f"New: {j.display_company}: {j.title}" for j in yours][:ACTIVITY_LINES],
                              f"From {cfg.imap.host}: {plural(len(got.found), 'job')}, {len(fresh)} new, "
                              f"{len(fresh) - len(yours)} hidden by your filters"],
                      by=by)
    # A new posting of a job already applied to (or queued, or skipped) is marked as its duplicate.
    report.duplicates = dupes.record(store, new) if new else {}
    store.record_fetch(report.boards, report.jobs, len(report.new), report.errors, report.warnings)
    boards = {k: v for k, v in report.errors.items() if k != MAILBOX}
    # What the check found that Today shows leads; the thousands of new postings the filters hide are a detail.
    yours = for_you(cfg, new)
    store.log("boards", (f"Checked {plural(report.boards, 'board')}: {found_line(len(yours))}" if report.boards
                         else "Couldn't check the boards") + (f", {len(boards)} failed" if boards else ""),
              ok=bool(report.boards) or not boards,
              detail=[f"New: {j.display_company}: {j.title}" for j in yours][:ACTIVITY_LINES]
              + [f"Failed: {b}: {e}" for b, e in boards.items()]
              + [f"Look at: {b}: {w}" for b, w in report.warnings.items()]
              + ([f"{report.jobs:,} open jobs, {checked} new, {checked - len(yours)} hidden by your filters"]
                 if report.boards else []), by=by,
              notable=not report.boards and bool(boards))  # every board failed: no network, or worse
    return report


ACTIVITY_LINES = 25  # at most this many jobs named in one Activity entry


def for_you(cfg: Config, jobs: list[Job]) -> list[Job]:
    """The ones of these new jobs that pass their filters: what a check brought in that Today shows."""
    return [j for j in jobs if not rejection(j, cfg.filters_for(j))]


def found_line(n: int) -> str:
    """What a check found, for its Activity line: "3 new jobs for you", or "nothing new for you"."""
    return f"{plural(n, 'new job')} for you" if n else "nothing new for you"


def plural(n: int, what: str) -> str:
    return f"{n:,} {what}" + ("" if n == 1 else "s")


@dataclass
class Entry:
    job: Job
    record: dict
    relevance: float
    keywords: list[str]
    fit: dict | None = None
    same_title: list[Job] = field(default_factory=list)  # the company's other postings with this title
    contacts: list[dict] = field(default_factory=list)  # people you know there
    warnings: list[str] = field(default_factory=list)  # reasons to look twice before applying (queue)
    pay: object = None  # expected pay from Levels.fyi (levels.Estimate, PENDING, REFUSED or None; queue only)
    lca: lca.Estimate | None = None  # base pay filed for H-1B hires (queue only)
    duplicate: dupes.Match | None = None  # a job acted on that it's (maybe) the same opening as; also in warnings

    @property
    def keys(self) -> list[str]:
        return [self.job.key] + [j.key for j in self.same_title]


@dataclass
class Digest:
    entries: list[Entry]          # best first
    rejected: dict[str, int]      # reason -> count
    scored: int = 0
    score_errors: dict[str, str] = field(default_factory=dict)
    note: str = ""
    total: int = 0                # how many matched, before the limit: more than len(entries) when it cut some


def pace(cfg: Config, store: Store, today: date | None = None) -> dict | None:
    """How many applications went out today (the local day) against the watchlist's pace: applied, daily, max,
    met (daily reached), at_max, and a line to show. None when pace.daily is 0 (off). It's advice: nothing is
    held back when it's met."""
    p = cfg.pace
    if not p.daily:
        return None
    n = store.applied_on(today or date.today())
    if n >= p.max:
        line = f"Applied today: {n}. That's a strong day: rest up, the rest can wait until tomorrow."
    elif n >= p.daily:
        line = f"Applied today: {n}. That's your {p.daily} for today. Well done!"
    elif n:
        line = f"Applied today: {n} of {p.daily}. Good going."
    else:
        line = f"Applied today: {n} of {p.daily}"  # no nudge: a day off is fine
    return {"applied": n, "daily": p.daily, "max": p.max, "met": n >= p.daily, "at_max": n >= p.max, "line": line}


def load_contacts(cfg: Config) -> Contacts | None:
    """The watchlist's connections file, if it has one. A missing file only warns: it's a hint, not a filter."""
    if not cfg.connections:
        return None
    try:
        store = Store(cfg.state)
        try:
            feedback = store.contact_feedback()  # whom to use and not to, from the page, CLI or an assistant
        finally:
            store.close()
        return Contacts.load(cfg.connections, cfg.connections_skip, feedback, cfg.employer)
    except (OSError, ValueError, sqlite3.Error) as e:
        print(f"jobwatch: connections skipped: {e}", file=sys.stderr)
        return None


def queue(cfg: Config, store: Store, pay_budget: int = 0) -> list[Entry]:
    """Jobs queued to apply to, in the order they were queued, with fit scores, contacts where known, and
    warnings: a job queued by hand never passed the filters, and a posting can close while it waits. With
    pay.levels on, each has its expected pay (see levels.py), asking Levels.fyi for up to `pay_budget` pages. The
    first warning says when a queued job is (maybe) the same opening as one applied to, queued or skipped."""
    rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
    contacts = load_contacts(cfg)
    reader = levels.Reader(store, pay_budget) if cfg.pay.levels else None
    index = dupes.Index(store)
    filings = lca.Index.open(lca.cache_path(cfg))
    out = []
    for job, rec in sorted(store.jobs(("queued",), include_closed=True), key=lambda r: r[1]["status_at"] or ""):
        rel, hits = relevance(job, cfg.keywords)
        e = Entry(job, rec, rel, hits, fit=brief(store.score(job.key, rid)) if rid else None)
        e.contacts = contacts.at(job.display_company, job.company) if contacts else []
        e.warnings = warnings(job, cfg.filters_for(job))
        e.duplicate = index.match(job, rec)
        if e.duplicate:  # first: applying twice is the costliest mistake here
            e.warnings.insert(0, e.duplicate.line)
        if reader:
            e.pay = levels.expected(cfg, store, job, reader=reader)
            if warn := levels.below(e.pay, cfg.filters_for(job).min_salary):
                e.warnings.append(warn)
        e.lca = lca.for_job(filings, job, cfg.filters_for(job).home_state)
        out.append(e)
    if filings:
        filings.close()
    return out


def warnings(job: Job, f: Filters) -> list[str]:
    """What a person should know before applying: pay below the watchlist's minimum, a location it doesn't
    want, and the posting text's red flags (filters.flags: clearance, on-site...). Not filters: the person
    queued it anyway, maybe for a reason."""
    out = []
    if f.min_salary and job.salary_min is not None and (job.salary_max or job.salary_min) < f.min_salary:
        out.append(f"pay {job.pay()} is below ${f.min_salary / 1000:.0f}K")
    # A job added by hand has its place as typed ("Remote (NC)"), which the location rules can't judge.
    if job.source != MANUAL and job.locations and \
            (why := reject_reason(job, Filters(locations=f.locations, remote_country=f.remote_country,
                                               home_state=f.home_state))):
        out.append(f"location: {'; '.join(job.locations[:3])}" + (f" ({why})" if why != "location" else ""))
    out += red_flags(job, f)
    return out


@dataclass
class Check:
    job: Job
    result: str        # open, closed, reopened, or unknown
    detail: str = ""


def _never(title: str) -> bool:
    return False


def _listed(job: Job, get, boards: dict) -> list[Job]:
    """The jobs open on a job's board now, as listed: a whole board is listed once per check, a searched one is
    searched for the job's title (nothing is read in full). An HN thread is read whole, once."""
    src = sources.SOURCES[job.source]
    searched = bool(src.search) and not src.many_companies
    k = (job.source, job.company, job.title if searched else "")
    if k not in boards:
        boards[k] = sources.fetch(job.source, job.company, get, search=[job.title], wanted=_never)
    return boards[k]


def _open_ids(job: Job, get, boards: dict) -> set[str]:
    return {j.id for j in _listed(job, get, boards)}


# A posting tracked this long before the job it might repost closed was open alongside it: another opening.
_ALONGSIDE = timedelta(days=1)


def find_repost(store: Store, job: Job, note: str = "", get=None, boards: dict | None = None,
                closed: str | None = None) -> list[Job]:
    """A closed job's opening posted again on its board: the open postings there with the same title (see
    dupes.title_key) under another id, the way a req that's taken down comes back under a new one, leaving out
    the ones tracked since before it closed (`closed`, ISO; default now): a board can post one title many times,
    one per opening, and those were open alongside it. Each one found is kept (read in full when the board lists
    it without its text). When just one is, it's taken as the repost: the old job's note says it was reposted as
    the new id (`note`: what the note says now, so that's said once), which makes the two the same opening (see
    dupes: "Reposted: you applied ..."). Several are only returned, for the person to tell which (if any) it is.
    Empty when there's none, for a job added by hand or an HN post, and when the board can't be read now."""
    src = sources.SOURCES.get(job.source)
    if not src or src.many_companies:
        return []
    want = dupes.title_key(job.title)
    if len(want[0].split()) < 2:  # just "Engineer": too common to say it's the same opening (as dupes says)
        return []
    try:
        listed = _listed(job, get, {} if boards is None else boards)
    except sources.SourceError:
        return []
    before = (datetime.fromisoformat(closed) if closed else datetime.now(timezone.utc)) - _ALONGSIDE
    found = [j for j in listed if j.id != job.id and dupes.title_key(j.title) == want
             and not ((seen := store.first_seen(j.key)) and datetime.fromisoformat(seen) < before)]
    for i, new in enumerate(found):
        if not new.description.strip():
            try:
                found[i] = new = sources.posting(new.url, get) or new
            except sources.SourceError:
                pass  # kept as listed: a later fetch or check reads it
        new.company_name = job.company_name or new.company_name  # a searched board names only its tenant
        store.keep(new)
    if len(found) == 1 and found[0].id not in note:
        store.add_note(job.key, f"Reposted as {found[0].id}: {found[0].url}")
    dupes.record(store, found)
    return found


def still_open(job: Job, get=None, page=None, boards: dict | None = None) -> bool | None:
    """Whether a job's posting still takes applications: on its board, at its link (a supported board), or None
    when jobwatch can't tell (a LinkedIn job: LinkedIn's robots.txt doesn't allow reading it). Raises SourceError
    when the board can't be read now."""
    boards = {} if boards is None else boards
    # one posting can be read by its link: surer than a title search (the board's own link, when the job's link
    # is the company's careers site: see mark_hosted)
    if job.source in ("workday", "rippling", "amazon", "oracle", "smartrecruiters", "avature", "icims",
                      "jobvite"):
        try:
            return sources.posting(job.posting_url or job.url, get) is not None
        except sources.NotFound:
            return False
    if job.source in sources.SOURCES:
        return job.id in _open_ids(job, get, boards)
    if not job.url or linkedin.job_id(job.url):
        return None
    try:
        return sources.posting(job.url, get) is not None or None
    except sources.NotFound:
        return False


def check_postings(store: Store, statuses: tuple[str, ...] = ("queued", "applied", "screening", "interviewing"),
                   get=None, page=None, watched: list[Board] = ()) -> list[Check]:
    """Check that the postings of queued jobs and open applications are still up, and record the ones that
    closed (or came back). Jobs from watched boards are checked by every fetch too; this also covers jobs added
    by hand from a link, and boards that aren't watched. For a closed one, its board is searched for the same
    opening posted again (see find_repost): its detail then says what it was reposted as.
    A job whose board's hosted pages are offline (see HostedPages) is still open while the board's API lists it:
    its detail says where to apply, and it links to the careers site its board has in `watched`, if any."""
    boards: dict = {}
    hosted, pages = HostedPages(store, page), {}
    careers = {(b.source, b.board): b.careers for b in watched}
    out = []
    for job, rec in store.jobs(statuses, include_closed=True):
        try:
            up = still_open(job, get, page, boards)
        except sources.SourceError as e:
            out.append(Check(job, "unknown", str(e)))
            continue
        if up and sources.hosted_url(job.source, job.company):
            if (job.source, job.company) not in pages:
                pages[job.source, job.company] = hosted.check(job.source, job.company)
            if mark_hosted(job, pages[job.source, job.company], careers.get((job.source, job.company), "")):
                store.update(job)
        if up is None:
            out.append(Check(job, "unknown", "no link jobwatch can read" if not job.url else "jobwatch can't read "
                             "that site: check it yourself"))
        elif store.set_closed(job.key, not up):
            out.append(Check(job, "reopened" if up else "closed", job.link_note if up else ""))
        else:
            out.append(Check(job, "open" if up else "closed",
                             job.link_note if up else f"since {(rec['closed'] or '')[:10]}"))
        if out[-1].result == "closed" and (new := find_repost(store, job, rec["note"] or "", get, boards,
                                                                rec["closed"])):
            said = (f"reposted as {new[0].id}: {new[0].url}" if len(new) == 1 else
                    "same title posted again as " + ", ".join(f"{j.id}: {j.url}" for j in new)
                    + ": check which, if any, is the one you applied to")
            out[-1].detail = "; ".join(d for d in (out[-1].detail, said) if d)
    return out


def watched_name(cfg: Config, link: str) -> str:
    """The watchlist's name for the board a link is on, if it's watched: a Workday link names only a tenant."""
    found = sources.detect(link) if link.strip() else None
    return next((b.name for b in cfg.boards if found and (b.source, b.board) == found and b.name), "")


def save_job(store: Store, link: str = "", company: str = "", title: str = "", text: str = "",
             status: str = "queued", note: str | None = None, applied: str | None = None, location: str = "",
             get=None, page=None, boards: list[Board] = ()) -> tuple[Job, bool]:
    """Add a job found somewhere else: (the job, whether its posting was read from the link).

    A link to one job on a supported board (Greenhouse, Lever, Ashby, Workable, Workday, Rippling, Google,
    Amazon, Oracle, SmartRecruiters, Avature, iCIMS, Jobvite) is read in full, so the job can be scored and prepped
    like any other; its board needn't be watched.
    A LinkedIn job link isn't read (LinkedIn's robots.txt disallows its job pages), so it needs the company and
    the title too; the same job is looked for on the company's own board (a watched one in `boards` under the
    company's name first): found, that posting is tracked, since it's where the application goes; not found, the
    job is kept with the LinkedIn link and the pasted text. Anything else (a company's own site) needs the
    company, the title and, to be scored, the posting's text pasted. An application already further along
    keeps its stage. When it's the same opening as a job already applied to, queued or skipped (see dupes.py),
    that's recorded on it; dupes.check says which, to warn. A company whose board isn't in `boards` becomes a
    suggestion to watch (see suggest.py)."""
    job, read = _save_job(store, link, company, title, text, status, note, applied, location, get, page, boards)
    dupes.record(store, [job])
    suggest.record(store, boards, job)
    return job, read


def _save_job(store: Store, link: str, company: str, title: str, text: str, status: str, note: str | None,
              applied: str | None, location: str, get, page, boards: list[Board]) -> tuple[Job, bool]:
    link, job = link.strip(), None
    if pid := linkedin.job_id(link):
        if not (company.strip() and title.strip()):
            raise ValueError("LinkedIn's robots.txt doesn't allow reading its job postings: give the company and "
                             "the job title too, and paste the posting's text to score it")
        p = linkedin.Posting(id=pid, title=title.strip(), company=company.strip(), location=location,
                             description=text.strip())
        job = linkedin.on_board(p, [(b.source, b.board, b.name) for b in boards], get, page)
        why = f"Found on LinkedIn: {p.url}"
        if job is None:
            job = store.add(p.company, p.title, url=p.url, status=status, note=note, applied=applied,
                            location=location, description=p.description)
            store.add_note(job.key, why)
            return job, False
        if sources.SOURCES[job.source].search:  # a searched board names only its tenant ("acme")
            job.company_name = p.company
        note = f"{note} {why}" if note else why
    elif link:
        job = sources.posting(link, get)
    if job is None:
        if link and not (company.strip() and title.strip()):
            raise ValueError("jobwatch can't read that link: give the company and the job title too, and paste "
                             "the posting's text to score it")
        return store.add(company, title, url=link, status=status, note=note, applied=applied, location=location,
                         description=text), False
    if company.strip():
        job.company_name = company.strip()
    store.keep(job)
    _, rec = store.find(job.key)
    if not (rec["status"] in STAGES and status not in STAGES):
        store.set_status([job.key], status, note, on=applied)
    elif note:
        store.add_note(job.key, note)
    return job, True


def set_link(store: Store, key: str, url: str, get=None) -> str:
    """Give a job added by hand its link and, when it has no posting text yet and the link is to one job on a
    supported board, read the posting from there (as add_application does): its text, and the pay and places
    the job has none of. Says what happened, in a few words; a link that can't be read is kept all the same."""
    store.set_url(key, url)
    job, _ = store.find(key)
    if not url.strip() or job.description.strip():
        return "link saved"
    try:
        posting = sources.posting(url, get)
    except sources.SourceError as e:
        return f"link saved; couldn't read the posting there: {e}"
    if posting is None or not posting.description.strip():
        return "link saved; jobwatch can't read postings on that site: paste the text to score it"
    store.set_description(key, posting.description, posting)
    return "link saved; posting read from it"


NO_RESUME = ("no_resume", "No resume to score against: add it in Settings (resume: in the watchlist)")
NO_TEXT = ("no_text", "No posting text: add a link to the company's posting or paste it")
MANY_ROLES = ("many_roles", "Not scored: a post listing several roles; watch the company's board to score each one")


def scorable(job: Job) -> bool:
    """Can this job be fit-scored? Not a post from a thread of many companies' posts (HN's Who is hiring): it
    lists several roles, places and links, and scored as one posting they all turn into must-haves ("Located
    in SF (Hybrid)"), so its score would say nothing. Its company's board, once watched, has each role."""
    src = sources.SOURCES.get(job.source)
    return not (src and src.many_companies)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def unscored_reasons(cfg: Config, store: Store, failed: dict[str, str] | None = None, current: str = "",
                     stopped: str = "") -> dict[str, dict]:
    """Why each queued and Today's job has no fit score: {job key: {"code", "text"}}. Codes: no_resume, no_text (a job
    from an alert email may have only its title), failed (with the error), scoring (now), queued (in the
    background scorer's line: "3rd of 4"), stopped (background scoring stopped, and why), manual (background
    scoring is off), same_role (another posting of the same role was scored before this one came in) and
    many_roles (a post listing several roles, never scored: see scorable).
    `failed` (job key -> error), `current` (the key being scored) and `stopped` come from the page's background
    scorer; without them, a job is described by where it stands in the scorer's line."""
    failed = {**failed_scores(cfg, store), **(failed or {})}
    has_resume = bool(cfg.resume and cfg.resume.is_file())
    fits = store.scores(resume_id(cfg.resume, cfg.prompts)) if has_resume else {}
    groups = scoring_line(cfg, store)  # the scorer's order
    line =[e.job.key for e in groups if _scorable(e) and e.job.key not in failed and e.job.key != current]
    out: dict[str, dict] = {}
    for e in groups:
        head = _why_unscored(e, has_resume, cfg.auto_score, failed, current, stopped, line)
        for job in (e.job, *e.same_title):
            if job.key in fits:
                continue
            why = head
            # its group's score was saved before this posting came in
            if job is not e.job and e.fit and not e.fit.get("stale"):
                why = ("same_role", f"Same role as another posting here, which scored {e.fit['score']}: press "
                       "Score fit to score this one")
            if why:
                out[job.key] = {"code": why[0], "text": why[1]}
    return out


def _why_unscored(e: Entry, has_resume: bool, auto: bool, failed: dict[str, str], current: str, stopped: str,
                  line: list[str]) -> tuple[str, str] | None:
    """Why a group's first posting (the one scored for all of them) has no fit score; None when it has one."""
    if e.fit is not None and not e.fit.get("stale"):
        return None
    if not scorable(e.job):
        return MANY_ROLES
    if not has_resume:
        return NO_RESUME
    if not e.job.description.strip():
        return NO_TEXT
    if e.job.key in failed:
        return "failed", f"Scoring failed: {failed[e.job.key]}"
    if e.job.key == current:
        return "scoring", "Being scored now"
    if not auto:
        return "manual", "Background scoring is off: press Score fit"
    if stopped:
        return "stopped", f"Background scoring stopped: {stopped}"
    return "queued", f"In line to score · {_ordinal(line.index(e.job.key) + 1)} of {len(line)}"


def unscored_reason(cfg: Config, store: Store, job: Job, reasons: dict[str, dict] | None = None) -> dict | None:
    """Why this job, on Today or not, has no fit score (see unscored_reasons; pass `reasons` when you have them
    already); None when it has one. A job that's neither queued nor on Today (applied, hidden by the filters)
    isn't scored in the background."""
    if (why := (unscored_reasons(cfg, store) if reasons is None else reasons).get(job.key)) is not None:
        return why
    has_resume = bool(cfg.resume and cfg.resume.is_file())
    if has_resume and store.score(job.key, resume_id(cfg.resume, cfg.prompts)):
        return None
    code, text = (MANY_ROLES if not scorable(job) else NO_RESUME if not has_resume
                  else NO_TEXT if not job.description.strip()
                  else ("manual", "Only queued and Today's jobs are scored in the background: press Score fit"))
    return {"code": code, "text": text}


def _rank(e: Entry):
    fit = e.fit["score"] if e.fit else -1
    return (-fit, -e.relevance, e.job.age_days() if e.job.age_days() is not None else 10_000)


PER_COMPANY = 2  # Today leads with at most this many jobs from one company
STALE_DAYS = 7  # a job shown this long ago without being acted on goes below the newer ones


def _stale(e: Entry, now: datetime) -> bool:
    """Shown in an earlier digest, first seen over STALE_DAYS ago, and still not queued, applied to or skipped."""
    seen = e.record.get("first_seen")
    return e.record.get("status") == "shown" and bool(seen) and \
        now - datetime.fromisoformat(seen) > timedelta(days=STALE_DAYS)


def _spread(entries: list[Entry], now: datetime | None = None) -> list[Entry]:
    """Ranked entries reordered so one company's high scores don't fill the top: the newer jobs first, then the
    stale ones (see _stale), each company's first PER_COMPANY of them; then every company's others, in the same
    order. Each part keeps the rank order."""
    now = now or datetime.now(timezone.utc)
    stale = {id(e): _stale(e, now) for e in entries}
    ordered = sorted(entries, key=lambda e: stale[id(e)])  # stable: the rank order within each
    count: dict[str, int] = {}
    over = {}
    for e in ordered:
        c = e.job.display_company.lower()
        count[c] = count.get(c, 0) + 1
        over[id(e)] = count[c] > PER_COMPANY
    return sorted(ordered, key=lambda e: over[id(e)])


def _fits(store: Store, rid: str) -> dict[str, dict]:
    """The fit scores to list and filter jobs by: the current one, else the last one made by another scorer
    (marked "stale") until the job is scored afresh, so a changed scorer doesn't make every job look unscored."""
    return {**store.stale_scores(rid), **store.scores(rid)}


def _matching(cfg: Config, store: Store, statuses: tuple[str, ...],
              redo_passes: bool = False) -> tuple[list[Entry], dict[str, int]]:
    """Jobs with these statuses that pass the filters, with stored fit scores for the current resume, and
    how many were filtered out (reason -> count). A job that's (maybe) the same opening as one acted on stays,
    flagged: its `duplicate` says which, and its first warning says so (see dupes.py). redo_passes: a score
    the fallback or an older scorer made doesn't count against filters.min_fit (for the scorer, which scores
    it again; without it, a stale score under min_fit would keep its job hidden for good)."""
    rejected: dict[str, int] = {}
    entries = []
    rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
    fits = _fits(store, rid) if rid else {}
    index = dupes.Index(store)
    for job, record in store.jobs(statuses):
        fit = fits.get(job.key)
        if reason := reject_reason(job, cfg.filters_for(job),
                                   None if redo_passes and fit and (fit.get("fallback") or fit.get("stale"))
                                   else fit):
            kind = reason.split()[0]  # title, department, location, pay, posted, fit
            rejected[kind] = rejected.get(kind, 0) + 1
            continue
        same = index.match(job, record)
        rel, hits = relevance(job, cfg.keywords)
        entries.append(e := Entry(job, record, rel, hits, fit=brief(fits.get(job.key)), duplicate=same))
        if same:
            e.warnings.append(same.line)
    return entries, rejected


SCORE_RETRY = timedelta(days=3)  # a job that failed to score is tried again after this, or at once after a change


def failed_scores(cfg: Config, store: Store) -> dict[str, str]:
    """{job key: error} for jobs that failed to score for the current resume, prompts and model within SCORE_RETRY:
    left alone until then (a restart doesn't try them again), unless the resume, the prompts or the model change."""
    if not (cfg.resume and cfg.resume.is_file()):
        return {}
    return store.score_failures(resume_id(cfg.resume, cfg.prompts), cfg.score_model, SCORE_RETRY)


def unscored(cfg: Config, store: Store, skip: set[str] = frozenset()) -> list[Entry]:
    """Queued and Today's jobs with no fit score for the current resume, in the scorer's order (see
    scoring_line). Keys in `skip`, and ones that failed lately (see failed_scores), are left out."""
    if not (cfg.resume and cfg.resume.is_file()):
        return []
    limit = at_daily_limit(cfg, store)
    if limit and not cfg.score_fallback:
        return []  # nothing can score until tomorrow
    skip = {*skip, *failed_scores(cfg, store)}
    return [e for e in scoring_line(cfg, store)
            if (_scorable(e) or (not limit and _provisional(e))) and e.job.key not in skip]


def made_elsewhere(cfg: Config, fit: dict | None) -> bool:
    """A score not made by the backend (and scoring.model, when set) now in use: by the other backend, as a
    fallback, or before scores said who made them."""
    if not fit:
        return False
    backend, _, model = str(fit.get("scored_by") or "").partition(":")
    return backend != cfg.backend or bool(cfg.score_model and model != cfg.score_model) or bool(fit.get("fallback"))


def rescore_line(cfg: Config, store: Store, at_least: float = 0) -> list[Entry]:
    """Queued and Today's jobs whose score another model made (see made_elsewhere), scoring at least `at_least`,
    best first: `jobwatch score --rescore` scores them again with the backend in use."""
    if not (cfg.resume and cfg.resume.is_file()):
        return []
    line = [e for e in scoring_line(cfg, store) if made_elsewhere(cfg, e.fit) and not e.fit.get("stale")
            and e.fit["score"] >= at_least and scorable(e.job) and e.job.description.strip()]
    return sorted(line, key=lambda e: -e.fit["score"])


def at_daily_limit(cfg: Config, store: Store) -> bool:
    """The backend has scored scoring.daily jobs today (the local day): the fallback scores the rest."""
    return bool(cfg.score_daily) and store.score_usage(cfg.backend) >= cfg.score_daily


def scoring_line(cfg: Config, store: Store) -> list[Entry]:
    """The jobs the background scorer works through, in its order: the open queued ones first, oldest first,
    since they're the ones about to be applied to (queued by hand, they never passed the filters), then
    Today's, most relevant first, one per company and title (the same role posted per region scores the same)."""
    rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
    fits = _fits(store, rid) if rid else {}
    queued = []
    for job, rec in sorted(store.jobs(("queued",)), key=lambda r: r[1]["status_at"] or ""):
        rel, hits = relevance(job, cfg.keywords)
        queued.append(Entry(job, rec, rel, hits, fit=brief(fits.get(job.key))))
    entries, _ = _matching(cfg, store, ("new", "shown"), redo_passes=True)
    return [*queued, *_group(sorted(entries, key=_rank))]


def _scorable(e: Entry) -> bool:
    """Without a current fit score (a stale one doesn't count), scorable, and with a posting's text to score
    (a job from an alert email may have only its title)."""
    return (e.fit is None or bool(e.fit.get("stale"))) and scorable(e.job) and bool(e.job.description.strip())


def _provisional(e: Entry) -> bool:
    """Scored by the fallback (scoring.fallback): scored again with the backend when it can."""
    return bool(e.fit and e.fit.get("fallback")) and scorable(e.job) and bool(e.job.description.strip())


DAILY_LIMIT = "daily limit"  # the start of a fallback score's reason when the backend was at scoring.daily


def _only_limit(reason: str) -> bool:
    """The reason is just the daily limit: the fallback is no failure to remember, and the backend takes the job
    up tomorrow. With "; local: ..." after it the fallback failed too (that is kept, so the job isn't tried again
    and again with the model held in memory)."""
    return reason.startswith(DAILY_LIMIT) and "; " not in reason


def score_with_fallback(cfg: Config, store: Store, jobs: list[Job], progress: Callable[[str], None] | None = None,
                        background: bool = False, batch: bool = False) -> tuple[dict[str, dict], dict[str, str]]:
    """Score with the backend, at most scoring.daily jobs a day, and what it can't (the limit reached, no key, no
    credit, a failure) with scoring.fallback (one backend, or several tried in order, each taking what the one
    before couldn't), each such result marked with why ("fallback"; its scored_by says which backend).
    ({key: result}, {key: error}). Without a fallback, ScoringUnavailable and the limit come back as they are.
    batch: the backend (Claude) through the Message Batches API, at half price (see score_jobs)."""
    results, errors = {}, {}
    room = max(cfg.score_daily - store.score_usage(cfg.backend), 0) if cfg.score_daily else len(jobs)
    first = jobs[:room]
    if first:
        try:
            results, errors = score_jobs(first, cfg.resume, cfg.backend, cfg.cache, workers=cfg.score_workers,
                                         progress=progress, prompts=cfg.prompts, model=cfg.score_model,
                                         keychain=cfg.api_keychain, batch=batch, key_command=cfg.api_key_command)
        except ScoringUnavailable as e:
            if not cfg.score_fallback:
                raise
            errors = {j.key: str(e) for j in first}
        store.add_score_usage(cfg.backend, len(results))
    limited = f"{DAILY_LIMIT}: {cfg.score_daily} jobs a day with {cfg.backend} (scoring.daily)"
    errors.update({j.key: limited for j in jobs[room:]})
    rest = [j for j in jobs if j.key not in results]
    if not (rest and cfg.score_fallback):
        return results, errors
    for name in cfg.score_fallback:  # in order; a backend that can't score (or fails a job) leaves it to the next
        try:
            with turn(name, background):
                more, more_errors = score_jobs(rest, cfg.resume, name, cfg.cache, workers=cfg.score_workers,
                                               progress=progress, prompts=cfg.prompts, keychain=cfg.api_keychain,
                                               model=fallback_model(cfg, name), key_command=cfg.api_key_command)
        except ScoringUnavailable as e:
            more, more_errors = {}, {j.key: str(e) for j in rest}
        for key, r in more.items():
            results[key] = {**r, "fallback": errors.pop(key, f"{cfg.backend} didn't score it")}
        errors.update({k: f"{errors[k]}; {name}: {v}" if k in errors else v for k, v in more_errors.items()})
        rest = [j for j in rest if j.key not in results]
        if not rest:
            break
    return results, errors


def fallback_model(cfg: Config, backend: str) -> str:
    """The model a fallback backend scores with: agy's is scoring.agy_model; the others use shortlist-ai's own."""
    return cfg.agy_model if backend == "agy" else ""


def score_entries(cfg: Config, store: Store, entries: list[Entry], progress: Callable[[str], None] | None = None,
                  background: bool = False, batch: bool = False, by: str = "") -> tuple[int, dict[str, str]]:
    """Score these jobs against the resume and store each result, for the job and its same-title postings.
    (how many were scored, {job key: error}). A fallback score for a job the backend failed on records that
    failure too, so the backend tries it again only after SCORE_RETRY (one over the daily limit, tomorrow).
    What was scored, and by which model, goes in the Activity log (Store.log)."""
    rid = resume_id(cfg.resume, cfg.prompts)
    before = {e.job.key: store.score(e.job.key, rid) for e in entries}  # a re-score's old result, for news()
    results, errors = score_with_fallback(cfg, store, [e.job for e in entries],
                                          progress=progress or (lambda m: print(f"  {m}", file=sys.stderr)),
                                          background=background, batch=batch)
    for e in entries:
        if e.job.key in results:
            fit = results[e.job.key]
            for key in e.keys:
                store.save_score(key, rid, fit)
            if fit.get("fallback") and not _only_limit(fit["fallback"]):
                store.save_score_failure(e.job.key, rid, cfg.score_model, fit["fallback"])
            e.fit = brief(fit)
        elif e.job.key in errors and not _only_limit(errors[e.job.key]):
            store.save_score_failure(e.job.key, rid, cfg.score_model, errors[e.job.key])
    if entries:
        text, ok, lines = _scored_text(entries, results, errors, batch)
        strong = [e for e in entries if (results.get(e.job.key) or {}).get("score", 0) >= STRONG_FIT]
        if strong and len(entries) > 1:
            text += f": {plural(len(strong), 'strong fit')}"
        store.log("score", text, ok, lines, by=by,
                  notable=any(news(cfg, e, results[e.job.key], before[e.job.key]) for e in strong))
    return len(results), errors


STRONG_FIT = 75  # a fit score from this on is a strong fit: the page tells you when one comes in


def news(cfg: Config, e: Entry, fit: dict, before: dict | None) -> bool:
    """A strong fit worth telling you about: a job Today shows (it passes your filters, its new fit too) that you
    haven't queued, applied to or skipped, strong for the first time. A re-score of a job that was already strong
    (the fallback's score done again by the backend, say) isn't news, and nor is a job your filters hide."""
    return (fit.get("score", 0) >= STRONG_FIT and (before or {}).get("score", 0) < STRONG_FIT
            and e.record.get("status", "new") in ("new", "shown") and not rejection(e.job, cfg.filters_for(e.job), fit))


def _scored_text(entries: list[Entry], results: dict[str, dict], errors: dict[str, str], batch: bool
                 ) -> tuple[str, bool, list[str]]:
    """An Activity entry for a scoring run: its line, whether anything was scored, and a line per job."""
    def model(fit: dict) -> str:
        name = str(fit.get("scored_by") or "").partition(":")[2] or "unknown model"
        return name.rsplit("/", 1)[-1] + (" (fallback)" if fit.get("fallback") else "")

    lines = []
    for e in entries:
        role = f"{e.job.display_company}: {e.job.title}"
        if fit := results.get(e.job.key):
            lines.append(f"{round(fit['score'])}/100 {role} ({model(fit)})")
        elif e.job.key in errors:
            lines.append(f"Failed: {role}: {errors[e.job.key]}")
    if len(entries) == 1:
        return f"Scored {lines[0]}" if results else lines[0] if lines else "Scored nothing", bool(results), []
    failed = sum(e.job.key in errors and e.job.key not in results for e in entries)
    return (f"Scored {plural(len(results), 'job')}" + (" through the Batches API" if batch else "")
            + (f", {failed} failed" if failed else ""), bool(results) or not failed, lines)


def compare_picks(cfg: Config, store: Store, n: int, by: str = "") -> list[tuple[Job, dict]]:
    """n open jobs with a fit score for the current resume (by: only ones that backend made), spread evenly from
    the lowest score to the highest, so a comparison with another model or prompts (see compare_scores) covers
    the whole range and filters.min_fit. One per company and title: the same role posted twice scores the same."""
    rid = resume_id(cfg.resume, cfg.prompts)
    fits = store.scores(rid)
    seen, scored = set(), []
    for job, _ in store.jobs():
        fit = fits.get(job.key)
        role = (job.display_company.lower(), job.title.lower())
        if (fit and role not in seen and scorable(job) and job.description.strip()
                and (not by or str(fit.get("scored_by") or "").startswith(f"{by}:"))):
            seen.add(role)
            scored.append((job, fit))
    scored.sort(key=lambda p: p[1]["score"])
    if n <= 0 or not scored:
        return []
    if n >= len(scored):
        return scored
    step = (len(scored) - 1) / max(n - 1, 1)
    return [scored[round(i * step)] for i in range(n)]


def compare_scores(cfg: Config, picks: list[tuple[Job, dict]], backend: str, model: str = "",
                   progress: Callable[[str], None] | None = None,
                   prompts: dict[str, str] | None = None,
                   batch: bool = False) -> tuple[dict[str, dict], dict[str, str]]:
    """These jobs scored again with another backend or model (or prompts to try in place of the watchlist's), to
    see how its scores line up with the stored ones before trusting them side by side (filters.min_fit is one
    cut-off for both). Nothing is stored. batch: Claude through the Message Batches API, at half price."""
    with turn(backend):
        return score_jobs([job for job, _ in picks], cfg.resume, backend, cfg.cache, workers=cfg.score_workers,
                          progress=progress, prompts=cfg.prompts if prompts is None else prompts, model=model,
                          keychain=cfg.api_keychain, batch=batch, key_command=cfg.api_key_command)


def build_digest(cfg: Config, store: Store, include_seen: bool = False, score_top: int | None = None,
                 limit: int | None = None, progress: Callable[[str], None] | None = None,
                 company: str = "") -> Digest:
    """Open jobs that pass the filters, ranked by fit score (when scored), then keyword relevance, and spread out
    (see _spread): at most PER_COMPANY from one company lead, and jobs seen over a week ago go below newer ones.

    Only jobs not yet shown are included unless include_seen. The `score_top` most relevant unscored
    jobs are scored with shortlist-ai first, when a resume is configured. company: only that company's jobs
    (its name or board, as company_key matches them), to pick among one company's roles."""
    entries, rejected = _matching(cfg, store, ("new", "shown") if include_seen else ("new",))
    if want := company_key(company):
        entries = [e for e in entries if want in (company_key(e.job.display_company), company_key(e.job.company))]
    digest = Digest(entries, rejected)
    contacts = load_contacts(cfg)
    if contacts:
        for e in entries:
            e.contacts = contacts.at(e.job.display_company, e.job.company)
    top = cfg.score_top if score_top is None else score_top
    if top:
        if not (cfg.resume and cfg.resume.is_file()):
            digest.note = "scoring skipped: set `resume:` in the config to a resume file"
        else:
            failed = failed_scores(cfg, store)
            todo = [e for e in _group(sorted(entries, key=_rank)) if _scorable(e) and e.job.key not in failed][:top]
            if todo:
                digest.scored, digest.score_errors = score_entries(cfg, store, todo, progress)
    entries.sort(key=_rank)
    grouped = _spread(_group(entries))
    digest.total = len(grouped)
    digest.entries = grouped[:limit] if limit else grouped
    return digest


def hidden(cfg: Config, store: Store, kind: str = "", limit: int = 100, since: datetime | None = None,
           source: str = "") -> dict:
    """What the filters hide from Today: how many, by which filter (filters.KINDS), and with `kind`, those
    jobs, newest first (`limit` of them). With `since`, only the jobs first seen since then, and all of them
    are listed (`kind` still narrows it): what a fetch or an alert email just brought in that you won't see.
    `source` counts only that source's jobs (manual: the ones from alert emails and links)."""
    if kind and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    by: dict[str, int] = {}
    jobs = []
    fits = _fits(store, resume_id(cfg.resume, cfg.prompts)) if cfg.resume and cfg.resume.is_file() else {}
    for job, rec in store.jobs(("new", "shown")):  # Today's statuses: see build_digest
        if (since and datetime.fromisoformat(rec["first_seen"]) < since) or (source and job.source != source):
            continue
        if r := rejection(job, cfg.filters_for(job), fits.get(job.key)):
            by[r[0]] = by.get(r[0], 0) + 1
            if r[0] == kind or (since and not kind):
                jobs.append({"key": job.key, "title": job.title, "company": job.display_company,
                             "url": job.url, "locations": job.places, "pay": job.pay(),
                             "age_days": job.age_days(), "kind": r[0], "why": r[1]})
    jobs.sort(key=lambda j: j["age_days"] if j["age_days"] is not None else 10_000)
    return {"total": sum(by.values()), "by": {k: by[k] for k in KINDS if k in by}, "kind": kind or None,
            "jobs": jobs[:limit], "more": max(0, len(jobs) - limit)}


def _group(entries: list[Entry]) -> list[Entry]:
    """One entry per company and title: many companies post a role once per region or city."""
    first: dict[tuple, Entry] = {}
    out = []
    for e in entries:
        e.same_title = []
    for e in entries:
        k = (e.job.source, e.job.company, " ".join(e.job.title.lower().split()))
        if k in first:
            first[k].same_title.append(e.job)
        else:
            first[k] = e
            out.append(e)
    return out
