"""Companies with an office near you: their jobs elsewhere are worth applying to, asking the recruiter in the phone
screen about working from the office near you.

Found from the jobs already seen: a company that has posted a job in one of your places (filters.locations, the
ones that aren't "remote") has an office there. Kept in filters.nearby_offices, which lets their jobs past the
place rules.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import Config, save
from .dupes import companies, company_key
from .store import Store
from .text import is_remote


def wanted_places(cfg: Config) -> list[str]:
    """The places in the location filter that aren't "remote"."""
    return [p for p in cfg.filters.locations if p.strip() and p.strip().lower() != "remote"]


def found(cfg: Config, store: Store) -> list[dict]:
    """Companies with a job seen in one of your places, open or closed, that aren't counted yet (nor left out):
    name, places (where, as the postings say), jobs (how many there), most jobs first."""
    places = [p.lower() for p in wanted_places(cfg)]
    if not places:
        return []
    known = {company_key(n) for n in cfg.filters.nearby_offices + cfg.filters.exclude_companies}
    out: dict[str, dict] = {}
    for job, _ in store.jobs(include_closed=True):
        if companies(job) & known:
            continue
        # "Remote - Boulder, CO" is a remote job for people there, not an office
        here = [loc for loc in job.locations if any(p in loc.lower() for p in places) and not is_remote(loc)]
        if not here:
            continue
        c = out.setdefault(company_key(job.display_company), {"name": job.display_company, "places": [], "jobs": 0})
        c["jobs"] += 1
        c["places"] += [loc for loc in here if loc not in c["places"]]
    return sorted(out.values(), key=lambda c: (-c["jobs"], c["name"].lower()))


def add(cfg: Config, names: list[str]) -> Config:
    """Count these companies as having an office near you (filters.nearby_offices); the watchlist is rewritten,
    the old one kept as .bak. One already there isn't added twice."""
    path = Path(cfg.path)
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    filters = dict(raw.get("filters") or {})
    have = list(filters.get("nearby_offices") or [])
    keys = {company_key(str(n)) for n in have}
    for name in (n.strip() for n in names):
        if name and company_key(name) not in keys:
            have.append(name)
            keys.add(company_key(name))
    filters["nearby_offices"] = have
    return save(path, {"filters": filters})


def text(cfg: Config, rows: list[dict]) -> str:
    near = ", ".join(wanted_places(cfg)) or "your places"
    head = f"Counted as having an office near you: {', '.join(cfg.filters.nearby_offices) or 'none yet'}.\n"
    if not wanted_places(cfg):
        return head + "\nYour location filter names no place but remote, so there's nothing to look for.\n"
    if not rows:
        return head + f"\nNo other company has posted a job in {near}.\n"
    lines = [head, f"Companies that have posted jobs in {near}:"]
    for r in rows:
        where = "; ".join(r["places"][:3]) + ("…" if len(r["places"]) > 3 else "")
        lines.append(f"  {r['name']}: {r['jobs']} job{'s' if r['jobs'] != 1 else ''} ({where})")
    lines.append("\n`jobwatch offices --add NAME` (or --add-all) lets their jobs anywhere through, with a warning to "
                 "ask the recruiter about working from that office.")
    return "\n".join(lines) + "\n"
