"""Whom to ask for a referral: the people you know at companies with jobs you're tracking, each with what
you've said about them (use, or don't use, and a note). The page's Referrals tab, `jobwatch referrals` and the
`rate_contact` tool all read and write it here."""

from __future__ import annotations

from . import GUIDE, jobpass
from .config import Config
from .filters import reject_reason, title_ok
from .models import Job
from .store import ENDED, STAGES, Store, closed_state
from .watch import job_fits, judged_pass, load_contacts

OPEN = ("new", "shown", "queued", *(s for s in STAGES if s not in ENDED))


def _marked_closed(cfg: Config, store: Store, known) -> dict[str, tuple]:
    """The new and shown jobs marked closed whose posting hasn't been confirmed closed (they may be open still)
    that pass the filters, at companies you know someone at: the only ones of the many a board marks that could
    show here. Today's pass leaves closed jobs out, so these are read from just the boards of those companies."""
    from .company import _groups  # company reads watch, as this module does
    boards = set()
    for g in _groups(store).values():
        if any(known.at(name, board) or known.left_out(name, board) for name in g["names"]
               for _, board in g["boards"]):
            boards |= g["boards"]
    # A title that fails the title filters fails the job: that is decided in the query, before a posting is read.
    passes = lambda source, company, title: title_ok(  # noqa: E731
        title, cfg.filters_for(Job(source=source, company=company, id="", title=title, url="")))
    return {job.key: (job, rec)
            for job, rec in store.board_rows(boards, ("new", "shown"), closed_only=True, title_ok=passes)
            if closed_state(rec) != "closed" and not reject_reason(job, cfg.filters_for(job))}


def view(cfg: Config, store: Store) -> dict:
    """{"people": [...], "skipped": [...], "has_connections": bool}: the connections at companies that have a
    tracked job (new or shown and passing the filters, queued, or an open application), people marked Use first
    and then the closest ties.
    skipped are those left out: marked Don't use, or in the watchlist file (from_file; edit the file to restore).
    Each has key, name, url, company, position, why, strength, verdict, note, from_file and jobs: [{key, title,
    company, status}]. min_fit is the fit that makes a good fit (see good_fit) and details holds each listed job's
    fit, place, pay, day first seen and whether its title is off-target, by key (see job_details), for the page
    to show the good fits and keep the rest a click away; health is what is kept of each company's health, by name
    (see company_health)."""
    known = load_contacts(cfg)
    if not known:
        return {"people": [], "skipped": [], "has_connections": False}
    found: dict[str, dict] = {}
    # A board's other openings (a chip maker's hundreds) aren't jobs you'd ask about: of the new and shown jobs,
    # only those the filters pass are read in full. They were judged once for every tab (jobpass.py); a min_fit
    # rejection doesn't count here, since a score isn't one of the filters of this list.
    wanted = [v.key for v in judged_pass(cfg, store).in_status(("new", "shown")) if v.kind in (None, "fit")]
    rows = {j.key: (j, rec) for j, rec in store.jobs(tuple(s for s in OPEN if s not in ("new", "shown")),
                                                      include_closed=True)} | store.rows(wanted)
    try:
        mtime = cfg.connections.stat().st_mtime_ns
    except OSError:
        mtime = None
    rows |= jobpass.remembered(  # the people come from the connections file and what was said of them (the store)
        store, "marked-closed", (jobpass.config_stamp(cfg), mtime, repr(cfg.connections_skip), cfg.employer),
        lambda: _marked_closed(cfg, store, known))
    for job, rec in (rows[k] for k in store.newest_first(OPEN) if k in rows):
        if closed_state(rec) == "closed" and rec["status"] in ("new", "shown", "queued"):
            continue
        names = (job.display_company, job.company)
        for p in known.at(*names) + known.left_out(*names):
            row = found.setdefault(p["key"], {**p, "jobs": []})
            if job.key not in {j["key"] for j in row["jobs"]}:
                row["jobs"].append({"key": job.key, "title": job.title, "company": job.display_company,
                                    "status": rec["status"]})
    people = sorted(found.values(), key=lambda r: (r["verdict"] != "use", -r["strength"], r["name"].lower()))
    left_out = lambda r: r["from_file"] or r["verdict"] == "skip"  # noqa: E731
    return {"people": [r for r in people if not left_out(r)], "skipped": [r for r in people if left_out(r)],
            "has_connections": True, "min_fit": good_fit(cfg),
            "min_fit_set": bool(cfg.filters.min_fit or cfg.today_fit),
            "details": job_details(cfg, store, {j["key"] for r in people for j in r["jobs"]}, rows),
            "health": company_health(store, {j["company"] for r in people for j in r["jobs"]})}


def company_health(store: Store, names: set[str]) -> dict[str, dict]:
    """What is kept of each company's health (funding, headcount, layoffs, rating, risk, sources, as of when), by the
    name its jobs carry, for the companies with some: the fields that hold a value only. The company dialog shows it."""
    out = {}
    for name in sorted(names):
        health = store.health(name)
        kept = {k: v for k, v in (health or {}).items() if v and k != "name"}
        if kept:
            out[name] = kept
    return out


GOOD_FIT = 60  # the fit a job needs to count as a good fit when the watchlist sets no minimum


def good_fit(cfg: Config) -> int:
    """The fit score from which a job is a good fit: the watchlist's filters.min_fit, else the fit chip Today
    opens on (display.today_defaults.fit), else GOOD_FIT."""
    return cfg.filters.min_fit or cfg.today_fit or GOOD_FIT


def job_details(cfg: Config, store: Store, keys: set[str], rows: dict) -> dict[str, dict]:
    """What the page's job lists show beside each title, once per job (people at one company share their jobs):
    {key: {fit (0-100 or None), stale, place, pay, seen (the day first seen), closed (the posting is confirmed
    closed: an application in progress is listed all the same), off (the title filters turn the title down: a job
    you queued or applied to is listed all the same, but is never a good fit by its score)}}. The jobs
    a person lists stay as they were; these are looked up by key."""
    fits = job_fits(cfg, store)
    out = {}
    for key in keys:
        job, rec = rows[key]
        fit = fits.get(key)
        score = fit.get("score") if fit else None
        out[key] = {"fit": None if score is None else round(score), "stale": bool(fit and fit.get("stale")),
                    "place": "; ".join(job.places[:2]) + (f" +{len(job.places) - 2}" if len(job.places) > 2 else ""),
                    "pay": job.pay(), "seen": str(rec["first_seen"])[:10], "closed": closed_state(rec) == "closed",
                    "off": not title_ok(job.title, cfg.filters_for(job))}
    return out


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
        return f"No connections file: set `connections:` in the watchlist (see {GUIDE}/contacts.md)."

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
