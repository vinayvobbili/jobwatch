"""Which jobs are worth a look: title, place, pay and age rules, plus keyword relevance."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Job
from .text import (
    bare_remote,
    in_us,
    is_remote,
    names_a_region,
    remote_states_in_text,
    remote_us_wide,
    state_code,
    state_list,
    us_states,
)


@dataclass
class Filters:
    titles: list[str] = field(default_factory=list)          # regexes; the title must match one (none: any title)
    exclude_titles: list[str] = field(default_factory=list)  # regexes; a match rejects the job
    locations: list[str] = field(default_factory=list)       # "remote", or text to find in a location (none: anywhere)
    remote_country: str = "US"                               # where a remote job must be open: "US" or "any"
    # The US state the person lives in ("NC" or "North Carolina"): a remote job open only in some states is left
    # out unless it's one of them. Empty: any US remote job passes.
    home_state: str = ""
    min_salary: int | None = None                            # a listed range must reach this; unlisted pay passes
    require_salary: bool = False                             # reject jobs that don't list pay
    max_age_days: int | None = None
    # Hide jobs whose fit score is below this (0-100; 0: off). Jobs not scored yet still show.
    min_fit: int = 0
    exclude_departments: list[str] = field(default_factory=list)  # regexes
    # regex -> why it matters, found in a posting's text: a warning on queued jobs, not a filter (boilerplate
    # can say "clearance" too). e.g. {"active (?:TS|top secret)": "clearance", "on-?site 5 days": "on-site"}
    flags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict | None) -> Filters:
        d = d or {}
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown filter setting(s): {', '.join(sorted(unknown))}")
        if not isinstance(d.get("flags") or {}, dict):
            raise ValueError("filters.flags maps a pattern to why it matters, e.g. {'TS/SCI': clearance}")
        # A pattern that doesn't compile ("c++") is refused when saved, rather than breaking every digest later.
        for key in ("titles", "exclude_titles", "exclude_departments", "flags"):
            for p in d.get(key) or []:
                try:
                    re.compile(p)
                except (re.error, TypeError) as e:
                    raise ValueError(f"filters.{key}: {p!r} isn't a valid pattern: {e}") from None
        return cls(**d)

    def __post_init__(self):
        if self.home_state:  # kept as its code: "North Carolina" -> "NC"
            code = state_code(str(self.home_state))
            if not code:
                raise ValueError(f"filters.home_state: {self.home_state!r} isn't a US state "
                                 "(e.g. NC or North Carolina)")
            self.home_state = code
        try:
            fit = int(self.min_fit or 0)
        except (TypeError, ValueError):
            fit = -1
        if not 0 <= fit <= 100:
            raise ValueError(f"filters.min_fit: {self.min_fit!r} isn't a fit score from 0 to 100")
        self.min_fit = fit


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


def remote_states(job: Job) -> list[str]:
    """The US states a remote job is open in, when it's open only in some (as codes); [] when it's open across the
    US or doesn't say. From its places ("Remote - Texas"; or, with the remote flag, a list of states alone:
    "California, USA; Nevada, USA") and its text ("Remote locations: ...", "must reside in ...").
    One place alone with the remote flag doesn't count: "New York, United States" is often the office of a
    remote job, and New York and Washington are cities too."""
    places = [loc for loc in job.locations if is_remote(loc)]
    out: list[str] = []
    if not any(remote_us_wide(loc) or bare_remote(loc) for loc in places):
        out += [s for loc in places if names_a_region(loc) for s in us_states(loc)]
        lists = [state_list(loc) for loc in job.locations if not is_remote(loc)]
        if job.remote and len(lists) >= 2 and all(lists):
            out += [s for states in lists for s in states]
    out += remote_states_in_text(job.description)
    return list(dict.fromkeys(out))


def title_ok(title: str, f: Filters) -> bool:
    """The title rules alone: what a searched board (Workday, Eightfold) reads in full."""
    return (not f.titles or bool(_any(f.titles, title))) and not _any(f.exclude_titles, title)


def search_terms(f: Filters) -> list[str]:
    """What to search a big board for: the title filters that are plain words ("engineer", "forward deployed").

    A title written as a regex can't be searched for; with none plain, the whole board is listed (capped)."""
    return [t for t in f.titles if not re.search(r"[\\^$.*+?()\[\]{}|]", t)]


# Which filter a job failed, in the order they're checked: what rejection() names first.
KINDS = ("title", "excluded", "department", "place", "pay", "age", "fit")


def rejection(job: Job, f: Filters, fit: dict | None = None) -> tuple[str, str] | None:
    """(which filter, why) for a job that fails the filters, or None if it passes. The filter is one of KINDS:
    ("title", "title"), ("excluded", "title matches 'manager'"), ("place", "location"),
    ("place", "remote only in CA, NV"), ("pay", "pay $120K–$160K"), ("age", "posted 45 days ago"),
    ("fit", "fit 55/100"). `fit` is the job's stored fit score; a job without one passes min_fit."""
    if f.titles and not _any(f.titles, job.title):
        return "title", "title"
    if p := _any(f.exclude_titles, job.title):
        return "excluded", f"title matches {p!r}"
    if job.department and (p := _any(f.exclude_departments, job.department)):
        return "department", f"department matches {p!r}"
    if f.locations:
        wanted = [w for w in f.locations if w.lower() != "remote"]
        remote_wanted = len(wanted) < len(f.locations)
        if not any(w.lower() in loc.lower() for w in wanted for loc in job.locations):
            remote = remote_wanted and (job.remote or any(is_remote(loc) for loc in job.locations))
            states = remote_states(job) if remote and f.home_state else []
            # Remote only in the home state ("Remote - North Carolina") is remote for this person.
            if not ((remote_wanted and _remote_ok(job, f.remote_country)) or f.home_state in states):
                return "place", "location"
            if states and f.home_state not in states:
                return "place", f"remote only in {', '.join(states)}"
    if job.salary_min is None:
        if f.require_salary:
            return "pay", "pay not listed"
    elif f.min_salary and (job.salary_max or job.salary_min) < f.min_salary:
        return "pay", f"pay {job.pay()}"
    if f.max_age_days is not None and (age := job.age_days()) is not None and age > f.max_age_days:
        return "age", f"posted {age} days ago"
    if f.min_fit and fit and fit.get("score") is not None and fit["score"] < f.min_fit:
        return "fit", f"fit {fit['score']:.0f}/100"
    return None


def reject_reason(job: Job, f: Filters, fit: dict | None = None) -> str | None:
    """Why the job fails the filters, or None if it passes."""
    r = rejection(job, f, fit)
    return r[1] if r else None


def red_flags(job: Job, f: Filters) -> list[str]:
    """The filters.flags a posting's text matches: "clearance: “active TS/SCI clearance required”"."""
    out = []
    for pattern, why in f.flags.items():
        if m := re.search(pattern, f"{job.title}\n{job.description}", re.I):
            out.append(f"{why}: “{' '.join(m.group(0).split())}”")
    return out


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
