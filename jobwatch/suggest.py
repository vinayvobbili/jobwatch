"""Companies to watch: the ones whose jobs keep coming in from job-alert emails (or `add`, or Hacker News' Who is
hiring thread) while their board isn't on the watchlist. A company that's never watched is never checked, however
good its jobs; alerts and HN posts show which.

Each job that comes in that way is recorded with its company (a thread's new posts only when they pass the
filters: a thread has hundreds). Its board is kept when it's known: the board the job itself was found on (the
alert import matched it there, its link was to one, or the HN post links to one), else a board found under the
company's name, the way `jobwatch find` looks (each source's official API; robots.txt for any page). A company is
looked for once: what's found, or that nothing was, is kept in the state file. jobwatch never reads LinkedIn or
Indeed for it.

Companies are ranked by how many of their jobs pass the watchlist's filters, a recent one counting more than an
old one. A company with an application in flight (applied to, and no no heard yet) comes first, whatever the
filters say of its jobs: they're in the middle of something there, and a req that's taken down often comes
back under a new one, which only watching its board catches. Accepting one adds its board the way add_board
does; a dismissed one isn't suggested again.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config, linkedin, sources
from .config import Board, Config
from .filters import reject_reason
from .models import Job
from .store import ENDED, MANUAL, STAGES, Store

# How the ranking fades with age (suggestions.half_life) and how many are listed (suggestions.limit): see
# config.Suggestions.

# Where the person is in the middle of something: applied, and not turned down or withdrawn. (Queued isn't: a job
# added by hand is queued unless told otherwise, filtered out or not.)
ENGAGED = tuple(s for s in STAGES if s not in ENDED)

@dataclass
class Suggestion:
    company: str                 # the company's bare name, its id here ("umbrella")
    name: str                    # as the jobs name it ("Umbrella LLC")
    entry: str | None            # its board (source:board); "" looked for and none found; None not looked for yet
    found_by: str | None = None  # posting: one of its jobs is on that board; name: found under its name
    jobs: list[Job] = field(default_factory=list)  # the ones that pass the filters, newest first
    last_seen: str = ""          # when the newest of those came in (YYYY-MM-DD)
    weight: float = 0.0          # the ranking: each job counts 1, halving every half_life days since it came in
    engaged: list[Job] = field(default_factory=list)  # the person's applications there in flight (ENGAGED)

    @property
    def sample_titles(self) -> list[str]:
        return list(dict.fromkeys(j.title for j in self.jobs or self.engaged))[:3]

    @property
    def careers(self) -> str:
        return sources.careers_url(*self.entry.split(":", 1)) if self.entry else ""

    @property
    def board_name(self) -> str:
        """The name to watch the board under: the company's, except Google's, whose roles keep their own employer
        (Google, YouTube, DeepMind)."""
        return "" if (self.entry or "").startswith("google:") else self.name

    @property
    def command(self) -> str:
        """What to run next: add it, or, with no board found, look for one with a link to its careers page."""
        if self.entry == "":
            return f"jobwatch find {shlex.quote(self.name)}"
        return f"jobwatch suggest --add {shlex.quote(self.name)}"

    def to_dict(self) -> dict:
        return {"company": self.name, "matching_jobs": len(self.jobs), "last_seen": self.last_seen,
                "applied_to": list(dict.fromkeys(j.title for j in self.engaged)),
                "board": self.entry or None, "board_found": self.found_by if self.entry else None,
                "looked_up": self.entry is not None, "careers": self.careers or None,
                "sample_titles": self.sample_titles, "command": self.command,
                "add_board": {"entry": self.entry, "name": self.board_name} if self.entry else None}


def company_id(name: str) -> str:
    return linkedin._bare(name)


def watched(boards: list[Board], name: str, entry: str = "") -> bool:
    """Is this company's board on the watchlist: the same board, or one under the company's name."""
    return any((entry and entry == b.entry) or linkedin.same_company(b.name or b.board, name)
               or linkedin.same_company(b.board, name) for b in boards)


def posted_on(job: Job) -> list[str]:
    """The boards a job is on (source:board each): the one it was found on, or for a post in a thread of many
    companies' posts (HN), the ones the post links to, or for a job added by hand (or from an alert), the board
    its link is on. None for a link to no supported board, or a post that links none."""
    if (src := sources.SOURCES.get(job.source)) and src.many_companies:
        return list(job.boards)
    if job.source == MANUAL:
        on = [sources.detect(u) for u in (job.posting_url, job.url) if u]
        return list(dict.fromkeys(f"{b[0]}:{b[1]}" for b in on if b))
    return [f"{job.source}:{job.company}"]


def record(store: Store, boards: list[Board], job: Job, found: list[tuple] | None = None,
           at: str | None = None) -> bool:
    """Note a job that came in from an alert, `add` or an HN post, when its company's board isn't watched. found:
    the boards already looked for under the company's name ((source, board, ...) each; empty: none found), or
    None when nobody looked. at: when it came in (default now). Returns whether it's newly noted."""
    name, on = job.display_company, posted_on(job)
    if not company_id(name) or any(watched(boards, name, e) for e in on or [""]):
        return False
    if on:
        entry, by = on[0], "posting"
    elif found:
        entry, by = f"{found[0][0]}:{found[0][1]}", "name"
    else:
        entry, by = None if found is None else "", None
    return store.note_unwatched(company_id(name), name, job.key, entry, by, at)


def record_posts(store: Store, cfg: Config, jobs: list[Job], at: dict[str, str] | None = None) -> set[str]:
    """Note the companies of a thread's new posts (HN), the ones that pass the filters, as record does. Nothing is
    looked for (no request is made): a post that links no board leaves its company to be looked for later. at:
    when each came in, by key (default now). Returns the companies (their ids) with a post newly noted."""
    at = at or {}
    return {company_id(job.display_company) for job in jobs
            if reject_reason(job, cfg.filters) is None and record(store, cfg.boards, job, None, at.get(job.key))}


def record_engaged(store: Store, boards: list[Board]) -> dict[str, list[Job]]:
    """Note the person's applications in flight (ENGAGED) whose company's board isn't watched, as record does,
    each from when it was first seen: however they came in, and closed ones too. Returns them by company (its
    id), watched ones aside."""
    out: dict[str, list[Job]] = {}
    for job, rec in store.jobs(ENGAGED, include_closed=True):
        name = job.display_company
        if company_id(name) and not any(watched(boards, name, e) for e in posted_on(job) or [""]):
            record(store, boards, job, None, rec["first_seen"])
            out.setdefault(company_id(name), []).append(job)
    return out


def rescan(cfg: Config, store: Store) -> int:
    """Note the companies of the posts already kept from each watched thread (HN), the ones still open, as
    record_posts does for new ones: posts fetched before they were noted, or that pass the filters only since
    they changed. Each counts from when it was first seen. Nothing is read from the web, and a post already noted
    isn't noted again. Returns how many companies had a post newly noted, dismissed ones aside."""
    noted = set()
    for b in cfg.boards:
        if (src := sources.SOURCES.get(b.source)) and src.many_companies:
            kept = store.open_board_jobs(b.source, b.board)
            noted |= record_posts(store, cfg, [j for j, _ in kept], at={j.key: seen for j, seen in kept})
    return len(noted - {r["company"] for r in store.unwatched(dismissed=True) if r["dismissed_at"]})


def look_up(store: Store, s: Suggestion, page=None):
    """Look for a company's board under its name, as `jobwatch find` does, and keep what's found (or that nothing
    was), so it's never looked for again."""
    hits = []
    for name in linkedin.company_names(s.name):
        if hits := sources.probe(name, None, page):
            break
    s.entry, s.found_by = (f"{hits[0][0]}:{hits[0][1]}", "name") if hits else ("", None)
    store.set_unwatched_board(s.company, s.entry, s.found_by)


def _age(at: str, now: datetime) -> float:
    return max(0.0, (now - datetime.fromisoformat(at)).total_seconds() / 86400)


def suggestions(cfg: Config, store: Store, limit: int | None = None, look: bool = False, page=None,
                now: datetime | None = None) -> list[Suggestion]:
    """Unwatched companies with jobs that pass the filters, or with an application in flight (see
    record_engaged), best first: those with one, then by weight. `limit` of them (None:
    suggestions.limit; 0: all). look: look for the board of each one listed that hasn't been looked for yet (see
    look_up); one found that's already watched drops it."""
    now, out = now or datetime.now(timezone.utc), []
    limit = cfg.suggest.limit if limit is None else limit
    half_life = cfg.suggest.half_life
    engaged = record_engaged(store, cfg.boards)
    for row in store.unwatched():
        if watched(cfg.boards, row["name"], row["entry"] or ""):
            continue
        jobs = [(j, at) for j, at in row["jobs"] if reject_reason(j, cfg.filters) is None]
        mine = engaged.get(row["company"], [])
        if not (jobs or mine):
            continue
        out.append(Suggestion(row["company"], row["name"], row["entry"], row["found_by"], [j for j, _ in jobs],
                              last_seen=(jobs or row["jobs"])[0][1][:10],
                              weight=sum(0.5 ** (_age(at, now) / half_life) for _, at in jobs), engaged=mine))
    out.sort(key=lambda s: s.name.lower())
    out.sort(key=lambda s: (bool(s.engaged), s.weight, s.last_seen), reverse=True)
    if not look:
        return out[:limit] if limit else out
    shown = []
    for s in out:
        if limit and len(shown) >= limit:
            break
        if s.entry is None:
            look_up(store, s, page)
        if not watched(cfg.boards, s.name, s.entry or ""):
            shown.append(s)
    return shown


def find(store: Store, which: str) -> Suggestion:
    """A recorded company, dismissed or not, by its name (any case, suffixes aside) or its board's entry."""
    rows = store.unwatched(dismissed=True)
    row = next((r for r in rows if r["company"] == company_id(which)), None) or next(
        (r for r in rows if r["entry"] and r["entry"] == which.strip()), None)
    if not row:
        raise KeyError(f"no suggested company matches {which!r}: see `jobwatch suggest`")
    return Suggestion(row["company"], row["name"], row["entry"], row["found_by"], [j for j, _ in row["jobs"]])


def accept(cfg: Config, store: Store, which: str, page=None) -> tuple[Config, Suggestion]:
    """Add a suggested company's board to the watchlist (as add_board does: the file is rewritten, the old one
    kept as .bak), looking for it first if nobody has. Returns the new watchlist and the suggestion."""
    s = find(store, which)
    # A job of theirs linked to its posting since (a LinkedIn alert's job, found on the company's own board)
    if not s.entry and (linked := next((e for j in s.jobs for e in posted_on(j)), None)):
        s.entry, s.found_by = linked, "posting"
        store.set_unwatched_board(s.company, s.entry, s.found_by)
    if s.entry is None:
        look_up(store, s, page)
    if not s.entry:
        raise ValueError(f"no board found for {s.name} under its name: give `jobwatch find` a link to its careers "
                         "page or one of its jobs, and add what it finds")
    return config.add_board(cfg.path, s.entry, s.board_name), s


def dismiss(store: Store, which: str) -> Suggestion:
    """Stop suggesting a company. Its jobs stay tracked."""
    s = find(store, which)
    store.dismiss_unwatched(s.company)
    return s


def text(found: list[Suggestion]) -> str:
    if not found:
        return ("No companies to suggest: none of the jobs from alerts, `add` or HN posts that pass your filters are "
                "from a company you don't watch.")
    out = ["Companies to watch: their jobs came in from alerts, `add` or HN posts, and their board isn't on your "
           "watchlist."]
    for s in found:
        n = len(s.jobs)
        out.append(f"\n{s.name}: " + (f"{n} matching job{'s' if n != 1 else ''}, the latest on {s.last_seen}" if n
                                      else f"last seen {s.last_seen}"))
        if s.engaged:
            out.append(f"  you applied to: {' · '.join(dict.fromkeys(j.title for j in s.engaged))} "
                       "(watch it to catch a repost)")
        if s.entry:
            how = "one of its jobs is there" if s.found_by == "posting" else "found under its name: check it's theirs"
            out.append(f"  board: {s.entry}  ({how})  {s.careers}")
        else:
            out.append("  board: none found under its name" if s.entry == "" else "  board: not looked for yet")
        out.append(f"  e.g. {' · '.join(s.sample_titles)}")
        out.append(f"  {s.command}")
    out.append("\nNot interested in one: jobwatch suggest --dismiss NAME")
    return "\n".join(out)
