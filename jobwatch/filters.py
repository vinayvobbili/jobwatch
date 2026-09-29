"""Which jobs are worth a look: title, place, pay and age rules, plus keyword relevance."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Job
from .text import bare_remote, in_us, is_remote, remote_us_wide


@dataclass
class Filters:
    titles: list[str] = field(default_factory=list)          # regexes; the title must match one (none: any title)
    exclude_titles: list[str] = field(default_factory=list)  # regexes; a match rejects the job
    locations: list[str] = field(default_factory=list)       # "remote", or text to find in a location (none: anywhere)
    remote_country: str = "US"                               # where a remote job must be open: "US" or "any"
    min_salary: int | None = None                            # a listed range must reach this; unlisted pay passes
    require_salary: bool = False                             # reject jobs that don't list pay
    max_age_days: int | None = None
    exclude_departments: list[str] = field(default_factory=list)  # regexes

    @classmethod
    def from_dict(cls, d: dict | None) -> Filters:
        d = d or {}
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown filter setting(s): {', '.join(sorted(unknown))}")
        return cls(**d)


def _any(patterns: list[str], text: str) -> str | None:
    return next((p for p in patterns if re.search(p, text, re.I)), None)


def _remote_ok(job: Job, country: str) -> bool:
    anywhere = country.lower() == "any"
    others = [loc for loc in job.locations if not is_remote(loc)]
    # A bare "Remote" takes its country from the posting's other places: "India; Remote" is remote in India.
    bare_ok = not others or any(in_us(loc) for loc in others)
    remote_places = [loc for loc in job.locations if is_remote(loc)]
    # "Remote - Washington D.C." is remote for people there: it counts only as a place (a wanted one or not).
    if any(anywhere or remote_us_wide(loc) or (bare_remote(loc) and bare_ok) for loc in remote_places):
        return True
    # The posting's own remote flag, with the location saying where.
    return bool(job.remote) and (anywhere or not job.locations or any(in_us(loc) for loc in job.locations))


def title_ok(title: str, f: Filters) -> bool:
    """The title rules alone: what a searched board (Workday, Eightfold) reads in full."""
    return (not f.titles or bool(_any(f.titles, title))) and not _any(f.exclude_titles, title)


def search_terms(f: Filters) -> list[str]:
    """What to search a big board for: the title filters that are plain words ("engineer", "forward deployed").

    A title written as a regex can't be searched for; with none plain, the whole board is listed (capped)."""
    return [t for t in f.titles if not re.search(r"[\\^$.*+?()\[\]{}|]", t)]


def reject_reason(job: Job, f: Filters) -> str | None:
    """Why the job fails the filters, or None if it passes."""
    if f.titles and not _any(f.titles, job.title):
        return "title"
    if p := _any(f.exclude_titles, job.title):
        return f"title matches {p!r}"
    if job.department and (p := _any(f.exclude_departments, job.department)):
        return f"department matches {p!r}"
    if f.locations:
        wanted = [w for w in f.locations if w.lower() != "remote"]
        remote_wanted = len(wanted) < len(f.locations)
        if not ((remote_wanted and _remote_ok(job, f.remote_country))
                or any(w.lower() in loc.lower() for w in wanted for loc in job.locations)):
            return "location"
    if job.salary_min is None:
        if f.require_salary:
            return "pay not listed"
    elif f.min_salary and (job.salary_max or job.salary_min) < f.min_salary:
        return f"pay {job.pay()}"
    if f.max_age_days is not None and (age := job.age_days()) is not None and age > f.max_age_days:
        return f"posted {age} days ago"
    return None


def relevance(job: Job, keywords: dict[str, float]) -> tuple[float, list[str]]:
    """A cheap, explainable ranking: the weights of the keywords the posting mentions, doubled in the title.

    Keywords are case-insensitive whole words or phrases, plural included ("agent" matches "agents";
    "C++" is fine). Prefix one with "re:" to write a regex instead."""
    score, hits = 0.0, []
    for kw, weight in keywords.items():
        pattern = kw[3:] if kw.startswith("re:") else r"(?<!\w)" + re.escape(kw) + r"(?:s|es)?(?!\w)"
        in_title = re.search(pattern, job.title, re.I)
        if in_title or re.search(pattern, job.description, re.I):
            score += weight * (2 if in_title else 1)
            hits.append(kw)
    return score, hits
