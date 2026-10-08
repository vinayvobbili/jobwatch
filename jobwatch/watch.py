"""The pipeline: check every board, then build a ranked digest of new matches."""

from __future__ import annotations

import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import linkedin, sources
from .config import Board, Config
from .contacts import Contacts
from .filters import Filters, red_flags, reject_reason, relevance, search_terms, title_ok
from .models import Job
from .score import resume_id, score_jobs
from .store import MANUAL, STAGES, Store


@dataclass
class FetchReport:
    boards: int = 0
    jobs: int = 0
    new: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # "source:board" -> error


def fetch_all(cfg: Config, store: Store, workers: int = 8, get=None) -> FetchReport:
    """Pull every board in the watchlist and record what is new. Boards that fail are reported and skipped."""
    report = FetchReport()
    # Big boards are searched for the watchlist's titles, and a posting is read in full once: the store has it.
    search, wanted = search_terms(cfg.filters), (lambda title: title_ok(title, cfg.filters))
    known = {b: store.board_jobs(b.source, b.board) for b in cfg.boards if sources.SOURCES[b.source].search}

    def one(b: Board):
        try:
            return b, sources.fetch(b.source, b.board, get, search=search, wanted=wanted, known=known.get(b)), None
        except sources.SourceError as e:
            return b, None, str(e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for b, jobs, err in pool.map(one, cfg.boards):
            if err:
                report.errors[f"{b.source}:{b.board}"] = err
                continue
            for j in jobs:
                # A searched board's name is only its tenant id ("acme"): the watchlist's name reads better.
                j.company_name = (b.name or j.company_name) if sources.SOURCES[b.source].search else \
                    (j.company_name or b.name)
            report.boards += 1
            report.jobs += len(jobs)
            report.new += store.sync(b.source, b.board, jobs)
    return report


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


def load_contacts(cfg: Config) -> Contacts | None:
    """The watchlist's connections file, if it has one. A missing file only warns: it's a hint, not a filter."""
    if not cfg.connections:
        return None
    try:
        return Contacts.load(cfg.connections)
    except (OSError, ValueError) as e:
        print(f"jobwatch: connections skipped: {e}", file=sys.stderr)
        return None


def queue(cfg: Config, store: Store) -> list[Entry]:
    """Jobs queued to apply to, in the order they were queued, with fit scores, contacts where known, and
    warnings: a job queued by hand never passed the filters, and a posting can close while it waits."""
    rid = resume_id(cfg.resume) if cfg.resume and cfg.resume.is_file() else None
    contacts = load_contacts(cfg)
    out = []
    for job, rec in sorted(store.jobs(("queued",), include_closed=True), key=lambda r: r[1]["status_at"] or ""):
        rel, hits = relevance(job, cfg.keywords)
        e = Entry(job, rec, rel, hits, fit=store.score(job.key, rid) if rid else None)
        e.contacts = contacts.at(job.display_company, job.company) if contacts else []
        e.warnings = warnings(job, cfg.filters)
        out.append(e)
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
            reject_reason(job, Filters(locations=f.locations, remote_country=f.remote_country)):
        out.append(f"location: {'; '.join(job.locations[:3])}")
    out += red_flags(job, f)
    return out


@dataclass
class Check:
    job: Job
    result: str        # open, closed, reopened, or unknown
    detail: str = ""


def _never(title: str) -> bool:
    return False


def _open_ids(job: Job, get, boards: dict) -> set[str]:
    """The ids open on a job's board now: a whole board is listed once per check, a searched one is searched for
    the job's title (nothing is read in full)."""
    searched = bool(sources.SOURCES[job.source].search)
    k = (job.source, job.company, job.title if searched else "")
    if k not in boards:
        boards[k] = {j.id for j in sources.fetch(job.source, job.company, get, search=[job.title], wanted=_never)}
    return boards[k]


def still_open(job: Job, get=None, page=None, boards: dict | None = None) -> bool | None:
    """Whether a job's posting still takes applications: on its board, at its link (a supported board or a
    LinkedIn job), or None when jobwatch can't tell. Raises SourceError when the board can't be read now."""
    boards = {} if boards is None else boards
    if job.source in ("workday", "rippling", "amazon", "oracle"):  # one posting read by its link: surer than a search
        try:
            return sources.posting(job.url, get) is not None
        except sources.NotFound:
            return False
    if job.source in sources.SOURCES:
        return job.id in _open_ids(job, get, boards)
    if not job.url:
        return None
    if p := linkedin.read(job.url, page):
        return not p.closed
    try:
        return sources.posting(job.url, get) is not None or None
    except sources.NotFound:
        return False


def check_postings(store: Store, statuses: tuple[str, ...] = ("queued", "applied", "screening", "interviewing"),
                   get=None, page=None) -> list[Check]:
    """Check that the postings of queued jobs and open applications are still up, and record the ones that
    closed (or came back). Jobs from watched boards are checked by every fetch too; this also covers jobs added
    by hand from a link, and boards that aren't watched."""
    boards: dict = {}
    out = []
    for job, rec in store.jobs(statuses, include_closed=True):
        try:
            up = still_open(job, get, page, boards)
        except sources.SourceError as e:
            out.append(Check(job, "unknown", str(e)))
            continue
        if up is None:
            out.append(Check(job, "unknown", "no link jobwatch can read" if not job.url else "jobwatch can't read "
                             "that site: check it yourself"))
        elif store.set_closed(job.key, not up):
            out.append(Check(job, "reopened" if up else "closed"))
        else:
            out.append(Check(job, "open" if up else "closed", "" if up else f"since {(rec['closed'] or '')[:10]}"))
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
    Amazon, Oracle) is read in full, so the job can be scored and prepped like any other; its board needn't be
    watched.
    A LinkedIn job link is read from LinkedIn's public posting page, and the same job is looked for on the
    company's own board (a watched one in `boards` under the company's name first): found, that posting is
    tracked, since it's where the application goes; not found, the LinkedIn posting is. Anything else (a
    company's own site) needs the company, the title and, to be scored, the posting's text pasted. An
    application already further along keeps its stage."""
    link, job, p = link.strip(), None, None
    try:
        p = linkedin.read(link, page) if link else None
    except sources.SourceError:  # LinkedIn wants a sign-in now: what the person gave is enough, if they gave it
        if not (company.strip() and title.strip()):
            raise
    if p:
        job = linkedin.on_board(p, [(b.source, b.board, b.name) for b in boards], get, page)
        why = f"Found on LinkedIn: {p.url}" + (" (no longer accepting applications there)" if p.closed else "")
        if job is None:
            job = store.add(company.strip() or p.company, title.strip() or p.title, url=p.url, status=status,
                            note=note, applied=applied, location=location or p.location,
                            description=text.strip() or p.description)
            store.add_note(job.key, why)
            if p.closed:
                store.set_closed(job.key, True)
            return job, True
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


def _rank(e: Entry):
    fit = e.fit["score"] if e.fit else -1
    return (-fit, -e.relevance, e.job.age_days() if e.job.age_days() is not None else 10_000)


def _matching(cfg: Config, store: Store, statuses: tuple[str, ...]) -> tuple[list[Entry], dict[str, int]]:
    """Jobs with these statuses that pass the filters, with stored fit scores for the current resume, and
    how many were filtered out (reason -> count)."""
    rejected: dict[str, int] = {}
    entries = []
    for job, record in store.jobs(statuses):
        if reason := reject_reason(job, cfg.filters):
            kind = reason.split()[0]  # title, department, location, pay, posted
            rejected[kind] = rejected.get(kind, 0) + 1
            continue
        rel, hits = relevance(job, cfg.keywords)
        entries.append(Entry(job, record, rel, hits))
    rid = resume_id(cfg.resume) if cfg.resume and cfg.resume.is_file() else None
    if rid:
        for e in entries:
            e.fit = store.score(e.job.key, rid)
    return entries, rejected


def unscored(cfg: Config, store: Store, skip: set[str] = frozenset()) -> list[Entry]:
    """Today's jobs with no fit score for the current resume, most relevant first, one per company and title
    (the same role posted per region scores the same). Keys in `skip` are left out."""
    if not (cfg.resume and cfg.resume.is_file()):
        return []
    entries, _ = _matching(cfg, store, ("new", "shown"))
    return [e for e in _group(sorted(entries, key=_rank)) if e.fit is None and e.job.key not in skip]


def score_entries(cfg: Config, store: Store, entries: list[Entry],
                  progress: Callable[[str], None] | None = None) -> tuple[int, dict[str, str]]:
    """Score these jobs against the resume and store each result, for the job and its same-title postings.
    (how many were scored, {job key: error})."""
    rid = resume_id(cfg.resume)
    results, errors = score_jobs([e.job for e in entries], cfg.resume, cfg.backend, cfg.cache,
                                 progress=progress or (lambda m: print(f"  {m}", file=sys.stderr)))
    for e in entries:
        if e.job.key in results:
            e.fit = results[e.job.key]
            for key in e.keys:
                store.save_score(key, rid, e.fit)
    return len(results), errors


def build_digest(cfg: Config, store: Store, include_seen: bool = False, score_top: int | None = None,
                 limit: int | None = None, progress: Callable[[str], None] | None = None) -> Digest:
    """Open jobs that pass the filters, ranked by fit score (when scored), then keyword relevance.

    Only jobs not yet shown are included unless include_seen. The `score_top` most relevant unscored
    jobs are scored with shortlist-ai first, when a resume is configured."""
    entries, rejected = _matching(cfg, store, ("new", "shown") if include_seen else ("new",))
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
            todo = [e for e in _group(sorted(entries, key=_rank)) if e.fit is None][:top]
            if todo:
                digest.scored, digest.score_errors = score_entries(cfg, store, todo, progress)
    entries.sort(key=_rank)
    digest.entries = _group(entries)[:limit] if limit else _group(entries)
    return digest


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
