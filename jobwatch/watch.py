"""The pipeline: check every board, then build a ranked digest of new matches."""

from __future__ import annotations

import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import sources
from .config import Board, Config
from .contacts import Contacts
from .filters import reject_reason, relevance, search_terms, title_ok
from .models import Job
from .score import resume_id, score_jobs
from .store import Store


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
    """Jobs queued to apply to, in the order they were queued, with fit scores and contacts where known."""
    rid = resume_id(cfg.resume) if cfg.resume and cfg.resume.is_file() else None
    contacts = load_contacts(cfg)
    out = []
    for job, rec in sorted(store.jobs(("queued",), include_closed=True), key=lambda r: r[1]["status_at"] or ""):
        rel, hits = relevance(job, cfg.keywords)
        e = Entry(job, rec, rel, hits, fit=store.score(job.key, rid) if rid else None)
        e.contacts = contacts.at(job.display_company, job.company) if contacts else []
        out.append(e)
    return out


def _rank(e: Entry):
    fit = e.fit["score"] if e.fit else -1
    return (-fit, -e.relevance, e.job.age_days() if e.job.age_days() is not None else 10_000)


def build_digest(cfg: Config, store: Store, include_seen: bool = False, score_top: int | None = None,
                 limit: int | None = None, progress: Callable[[str], None] | None = None) -> Digest:
    """Open jobs that pass the filters, ranked by fit score (when scored), then keyword relevance.

    Only jobs not yet shown are included unless include_seen. The `score_top` most relevant unscored
    jobs are scored with shortlist-ai first, when a resume is configured."""
    statuses = ("new", "shown") if include_seen else ("new",)
    rejected: dict[str, int] = {}
    entries = []
    for job, record in store.jobs(statuses):
        if reason := reject_reason(job, cfg.filters):
            kind = reason.split()[0]  # title, department, location, pay, posted
            rejected[kind] = rejected.get(kind, 0) + 1
            continue
        rel, hits = relevance(job, cfg.keywords)
        entries.append(Entry(job, record, rel, hits))

    digest = Digest(entries, rejected)
    contacts = load_contacts(cfg)
    if contacts:
        for e in entries:
            e.contacts = contacts.at(e.job.display_company, e.job.company)
    rid = resume_id(cfg.resume) if cfg.resume and cfg.resume.is_file() else None
    if rid:
        for e in entries:
            e.fit = store.score(e.job.key, rid)
    top = cfg.score_top if score_top is None else score_top
    if top:
        if not rid:
            digest.note = "scoring skipped: set `resume:` in the config to a resume file"
        else:
            # One score per company and title: the same role posted per region scores the same.
            todo = [e for e in _group(sorted(entries, key=_rank)) if e.fit is None][:top]
            if todo:
                results, errors = score_jobs([e.job for e in todo], cfg.resume, cfg.backend, cfg.cache,
                                             progress=progress or (lambda m: print(f"  {m}", file=sys.stderr)))
                for e in todo:
                    if e.job.key in results:
                        e.fit = results[e.job.key]
                        store.save_score(e.job.key, rid, e.fit)
                digest.scored, digest.score_errors = len(results), errors
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
