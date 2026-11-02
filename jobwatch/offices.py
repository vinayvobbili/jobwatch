"""Companies with an office near you: their jobs elsewhere are worth applying to, asking the recruiter in the phone
screen about working from the office near you.

Found from the jobs already seen: a company that has posted a tech job (tech_role: IT, cyber, AI, software and
the like, not field sales) in one of your places (filters.locations, the ones that aren't "remote") has an office
there. Kept in filters.nearby_offices, which lets their jobs past the place rules.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import Config, save
from .dupes import companies, company_key
from .filters import office_nearby, rejection, remote_offered
from .rolekinds import OTHER, role_kinds
from .store import Store
from .text import is_remote


def wanted_places(cfg: Config) -> list[str]:
    """The places in the location filter that aren't "remote"."""
    return [p for p in cfg.filters.locations if p.strip() and p.strip().lower() != "remote"]


#  Field and customer-facing roles live near their customers, wherever the company's offices are
_FIELD = re.compile(r"\b(sales|account|customer|client|business development|partners?|territory|field|named|"
                    r"regional|district|forward[- ]deployed|fde|solutions? (?:engineer|architect)\w*)\b", re.I)
#  IT work rolekinds.py calls "other" ("IT" in capitals: "it" is a word)
_IT = re.compile(r"\bIT\b|(?i:\b(information technology|systems? admin\w*|network\w*|help ?desk|desktop support|"
                 r"database\w*|data engineer\w*|cloud|penetration|pen ?test\w*|red team\w*)\b)")


def tech_role(title: str) -> bool:
    """Whether a job says the company has a tech office there: an IT, cyber, automation, AI, forward deployed or
    software role (rolekinds.py), and not a field or customer-facing one (a Customer Engineer or an Account
    Executive in Boulder covers the region's customers from home)."""
    title = title or ""
    return bool(set(role_kinds(title)) - {OTHER[0]} or _IT.search(title)) and not _FIELD.search(title)


def tech_job(job) -> bool:
    """tech_role, or a Hacker News "Who is hiring?" post (one per company, titled by its roles or not at all)."""
    return job.source == "hn" or tech_role(job.title)


def _here(job, places: list[str]) -> list[str]:
    """The job's locations in one of your places (lowercased). "Remote - Boulder, CO" is a remote job for people
    there, not an office."""
    return [loc for loc in job.locations if any(p in loc.lower() for p in places) and not is_remote(loc)]


def jobs_there(cfg: Config, store: Store, name: str) -> list[tuple]:
    """A company's jobs posted in one of your places, open or closed, newest first: (job, record, locations
    there). What `offices --jobs NAME` lists: has it ever posted here, and what?"""
    places, want = [p.lower() for p in wanted_places(cfg)], company_key(name)
    return [(job, rec, here) for job, rec in store.jobs(include_closed=True)
            if want in companies(job) and (here := _here(job, places))]


def found(cfg: Config, store: Store) -> list[dict]:
    """Companies with a job seen in one of your places, open or closed, that aren't counted yet (nor left out):
    name, places (where, as the postings say), jobs (how many there), most jobs first."""
    places = [p.lower() for p in wanted_places(cfg)]
    if not places:
        return []
    known = {company_key(n) for n in cfg.filters.nearby_offices + cfg.filters.exclude_companies}
    out: dict[str, dict] = {}
    for job, _ in store.jobs(include_closed=True):
        if companies(job) & known or not tech_job(job):
            continue
        here = _here(job, places)
        if not here:
            continue
        c = out.setdefault(company_key(job.display_company), {"name": job.display_company, "places": [], "jobs": 0})
        c["jobs"] += 1
        c["places"] += [loc for loc in here if loc not in c["places"]]
    return sorted(out.values(), key=lambda c: (-c["jobs"], c["name"].lower()))


def remote_offers(cfg: Config, store: Store) -> list[tuple]:
    """Open jobs placed outside your places that show only because the posting offers remote by arrangement
    ("unless designated remote"), passing every other filter: (job, record, the words), newest first.
    `offices --remote-offers`, to see what that rule lets in."""
    out = []
    for job, rec in store.jobs():
        f = cfg.filters_for(job)
        if (offer := remote_offered(job, f)) and not office_nearby(job, f) and rejection(job, f) is None:
            out.append((job, rec, offer))
    return out


def unproven(cfg: Config, store: Store) -> list[str]:
    """Counted companies (filters.nearby_offices) with no tech role seen in your places, open or closed: only
    field sales there, or nothing at all. A hint, not proof: jobwatch sees only some of a company's postings, so
    one you know has a tech office there (filters.known_offices) isn't listed. `offices --drop` uncounts one."""
    places = [p.lower() for p in wanted_places(cfg)]
    shown = {company_key(n) for n in cfg.filters.known_offices}
    for job, _ in store.jobs(include_closed=True):
        if tech_job(job) and _here(job, places):
            shown |= companies(job)
    return [n for n in cfg.filters.nearby_offices if company_key(n) not in shown]


def drop(cfg: Config, names: list[str]) -> Config:
    """Stop counting these companies as having an office near you; the watchlist is rewritten, the old one kept
    as .bak."""
    path = Path(cfg.path)
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    filters = dict(raw.get("filters") or {})
    gone = {company_key(n) for n in names}
    for key in ("nearby_offices", "known_offices"):
        if key in filters:
            filters[key] = [n for n in filters[key] or [] if company_key(str(n)) not in gone]
    return save(path, {"filters": filters})


def add(cfg: Config, names: list[str], known: bool = False) -> Config:
    """Count these companies as having an office near you (filters.nearby_offices; known: also
    filters.known_offices, a tech office you know of); the watchlist is rewritten, the old one kept as .bak. One
    already there isn't added twice."""
    path = Path(cfg.path)
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    filters = dict(raw.get("filters") or {})
    for key in ("nearby_offices", "known_offices") if known else ("nearby_offices",):
        have = list(filters.get(key) or [])
        keys = {company_key(str(n)) for n in have}
        for name in (n.strip() for n in names):
            if name and company_key(name) not in keys:
                have.append(name)
                keys.add(company_key(name))
        filters[key] = have
    return save(path, {"filters": filters})


def text(cfg: Config, rows: list[dict], doubtful: list[str] = ()) -> str:
    near = ", ".join(wanted_places(cfg)) or "your places"
    head = f"Counted as having an office near you: {', '.join(cfg.filters.nearby_offices) or 'none yet'}.\n"
    if doubtful:
        head += (f"\nCounted, with no tech job seen in {near} (field sales or nothing): {', '.join(doubtful)}.\n"
                 "jobwatch sees only some postings: check before `jobwatch offices --drop NAME`; `--known NAME` "
                 "keeps one you know has a tech office there; `--jobs NAME` lists what it posted there.\n")
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
