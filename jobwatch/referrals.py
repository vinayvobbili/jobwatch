"""Whom to ask for a referral: the people you know at companies with jobs you're tracking, each with what
you've said about them (use, or don't use, and a note). The page's Referrals tab, `jobwatch referrals` and the
`rate_contact` tool all read and write it here."""

from __future__ import annotations

from .config import Config
from .filters import reject_reason
from .store import ENDED, STAGES, Store
from .watch import load_contacts

OPEN = ("new", "shown", "queued", *(s for s in STAGES if s not in ENDED))


def view(cfg: Config, store: Store) -> dict:
    """{"people": [...], "skipped": [...], "has_connections": bool}: the connections at companies that have a
    tracked job (new or shown and passing the filters, queued, or an open application), people marked Use first
    and then the closest ties.
    skipped are those left out: marked Don't use, or in the watchlist file (from_file; edit the file to restore).
    Each has key, name, url, company, position, why, strength, verdict, note, from_file and jobs: [{key, title,
    company, status}]."""
    known = load_contacts(cfg)
    if not known:
        return {"people": [], "skipped": [], "has_connections": False}
    found: dict[str, dict] = {}
    for job, rec in store.jobs(OPEN, include_closed=True):
        if rec["closed"] and rec["status"] in ("new", "shown", "queued"):
            continue
        if rec["status"] in ("new", "shown") and reject_reason(job, cfg.filters):
            continue  # a board's other openings (a chip maker's hundreds) aren't jobs you'd ask about
        names = (job.display_company, job.company)
        for p in known.at(*names) + known.left_out(*names):
            row = found.setdefault(p["key"], {**p, "jobs": []})
            if job.key not in {j["key"] for j in row["jobs"]}:
                row["jobs"].append({"key": job.key, "title": job.title, "company": job.display_company,
                                    "status": rec["status"]})
    rows = sorted(found.values(), key=lambda r: (r["verdict"] != "use", -r["strength"], r["name"].lower()))
    left_out = lambda r: r["from_file"] or r["verdict"] == "skip"  # noqa: E731
    return {"people": [r for r in rows if not left_out(r)], "skipped": [r for r in rows if left_out(r)],
            "has_connections": True}


def resolve(cfg: Config, who: str) -> dict:
    """The connection a name or linkedin.com/in/ link means (see Contacts.find)."""
    if not cfg.connections:
        raise ValueError("no connections file: set `connections:` in the watchlist")
    known = load_contacts(cfg)
    if not known:
        raise ValueError("the connections file couldn't be read")
    return known.find(who)


def rate(cfg: Config, store: Store, who: str, verdict: str, note: str = "") -> dict:
    """Record use or skip for a person (verdict "clear" forgets it). Returns the person with the new verdict."""
    person = resolve(cfg, who)
    if verdict == "clear":
        store.clear_contact(person["key"])
        return {**person, "verdict": "", "note": ""}
    store.rate_contact(person["key"], verdict, note)
    return {**person, "verdict": verdict, "note": note.strip()}


def text(v: dict) -> str:
    """The same rows as a list for the terminal."""
    if not v["has_connections"]:
        return "No connections file: set `connections:` in the watchlist (see the README)."

    def line(p: dict) -> str:
        mark = {"use": "[use] ", "skip": "[don't use] "}.get(p["verdict"], "")
        jobs = ", ".join(f"{j['company']}: {j['title']}" for j in p["jobs"][:3])
        more = f" and {len(p['jobs']) - 3} more" if len(p["jobs"]) > 3 else ""
        return (f"  {mark}{p['name']}" + (f" ({p['position']})" if p["position"] else "") + f", {p['company']}"
                + (f" [{p['why']}]" if p["why"] else "") + (f" - {p['note']}" if p["note"] else "")
                + ("  (in your watchlist file)" if p["from_file"] else "") + f"\n      {jobs}{more}")
    out = [f"People you know at companies you're tracking ({len(v['people'])}):"]
    out += [line(p) for p in v["people"]] or ["  nobody yet"]
    if v["skipped"]:
        out += ["", f"Not suggested ({len(v['skipped'])}):"] + [line(p) for p in v["skipped"]]
    return "\n".join(out)
