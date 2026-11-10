"""`jobwatch scan`: a list of companies (a post naming who's hiring, an investor's portfolio, a ranking) checked
once against the watchlist's filters, so the ones with a job worth having join the watchlist by rule instead of
one `find` at a time.

Each name is looked up the way `jobwatch find` does (each source's official API; robots.txt for any page), its
boards are read the way a check reads a watched board (searched for the watchlist's titles), and their jobs are
judged by the watchlist's filters: title, place, pay, age. With --add, the board with the most matching jobs is
watched when it has `least` of them: 1 unless told, lower than suggestions.min_jobs on purpose, since a list someone
picked is worth more than an alert's sample (where one job alone is mostly a staffing firm's). A board found only by
guessing from the name can be another company's: one whose roles name a different company is reported and never
added. Nothing is stored but the watchlist entries added; the next check reads their jobs.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import config, linkedin, sources
from .config import Board, Config
from .filters import reject_reason, search_terms, title_ok
from .models import Job
from .suggest import watched

SAMPLE = 3  # matching titles shown per company


@dataclass
class Scanned:
    query: str                   # the name (or link) as given
    entry: str = ""              # the board with the most matching jobs (source:board); "" none with open roles
    matching: list[Job] = field(default_factory=list)  # its jobs that pass the filters
    open_roles: str = ""         # its open roles, matching or not, as `find` counts them ("300+" for a big one)
    other: str = ""              # the company its roles name, when that isn't the one asked for
    watched: bool = False        # already on the watchlist: not read
    added: bool = False
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.entry)


def names(lines: list[str]) -> list[str]:
    """Company names from a list's lines: one a line, blank lines and # comments left out, each once."""
    out = (line.split("#", 1)[0].strip() for line in lines)
    return list(dict.fromkeys(n for n in out if n))


def _named(jobs: list[Job]) -> str:
    return next((j.company_name for j in jobs if j.company_name), "")


def _read(cfg: Config, source: str, board: str, get=None) -> list[Job]:
    f = cfg.filters_of(Board(source, board))
    return sources.fetch(source, board, get, search=search_terms(f), wanted=lambda t: title_ok(t, f))


def scan_one(cfg: Config, query: str, get=None, page=None) -> Scanned:
    """One company: its boards found, read and judged (see the module's docstring)."""
    s = Scanned(query)
    if watched(cfg.boards, query):
        s.watched = True
        return s
    try:
        hits = sources.probe(query, get, page)
    except sources.SourceError as e:
        s.error = str(e)
        return s
    by_name = ":" not in query and "/" not in query  # a link or an entry names no company to check against
    boards = []
    for source, board, sample in hits:
        if not sample:
            continue
        if watched(cfg.boards, query, f"{source}:{board}"):
            s.watched = True
            return s
        try:
            jobs = _read(cfg, source, board, get)
        except sources.SourceError as e:
            s.error = f"{source}:{board}: {e}"
            continue
        named = _named(jobs or sample)
        other = named if by_name and named and not linkedin.same_company(named, query) else ""
        boards.append(Scanned(query, f"{source}:{board}", [j for j in jobs if reject_reason(j, cfg.filters_for(j))
                                                            is None], sources.open_roles(sample), other))
    # The asked-for company's board beats another company's, whatever their counts; then the most matching jobs
    return max(boards, key=lambda b: (not b.other, len(b.matching)), default=s)


def progress_line(done: int, total: int, s: Scanned) -> str:
    """One company as it finishes, for a long list (minutes) that would otherwise say nothing until the end."""
    what = ("already watched" if s.watched else s.error or "no board found" if not s.found
            else f"{s.entry}, another company's?" if s.other else f"{s.entry}, {len(s.matching)} matching")
    return f"[{done}/{total}] {s.query}: {what}"


def scan(cfg: Config, queries: list[str], add: bool = False, least: int = 1, get=None, page=None,
         workers: int = 8, progress: Callable[[int, int, Scanned], None] | None = None) -> list[Scanned]:
    """Every company in the list, in its order (see scan_one); progress(done, total, company) hears of each as it
    finishes. add: watch each one's board that has `least` matching jobs and names no other company (the watchlist
    is rewritten as add_board does, the old one kept as .bak)."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(scan_one, cfg, q, get, page) for q in queries]
        for done, f in enumerate(as_completed(futures), 1):
            if progress:
                progress(done, len(futures), f.result())
        found = [f.result() for f in futures]
    if add:
        for s in found:
            if s.found and not s.other and len(s.matching) >= least \
                    and not watched(cfg.boards, s.query, s.entry):
                name = "" if ":" in s.query or "/" in s.query else s.query
                cfg = config.add_board(cfg.path, s.entry, name)
                s.added = True
    return found


def text(found: list[Scanned], least: int, add: bool) -> str:
    """The report: companies with matching jobs first, then the rest, each in the list's order."""
    def line(s: Scanned) -> str:
        if s.watched:
            return f"{s.query}: already watched"
        if not s.found:
            why = s.error or "no board with open roles found; `jobwatch find` takes a link to their careers page"
            return f"{s.query}: {why}"
        head = f"{s.query}: {s.entry} ({s.open_roles} open roles, {len(s.matching)} matching)"
        if s.other:
            return f"{head}\n    Its roles name {s.other}: another company's board? Not added."
        out = [head + (" — added" if s.added else "")]
        out += [f"    {j.title}  ({'; '.join(j.places) or 'no place'}{' · ' + j.pay() if j.pay() else ''})  {j.url}"
                for j in s.matching[:SAMPLE]]
        if len(s.matching) > SAMPLE:
            out.append(f"    … {len(s.matching) - SAMPLE} more")
        return "\n".join(out)

    hits = [s for s in found if s.matching and not s.other]
    rest = [s for s in found if s not in hits]
    added = sum(s.added for s in found)
    summary = (f"{len(found)} companies: {len(hits)} with a job that passes your filters"
               + (f", {added} added to the watchlist" if add else
                  f"; `--add` watches the ones with {least}+"))
    return "\n".join([summary, "", *map(line, hits), *([""] if hits and rest else []), *map(line, rest)])
