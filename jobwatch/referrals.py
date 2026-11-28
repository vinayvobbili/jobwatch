"""Whom to ask for a referral: the people you know at companies with jobs you're tracking, each with what
you've said about them (use, or don't use, and a note). The page's Referrals tab, `jobwatch referrals` and the
`rate_contact`, `add_contact` and `remove_contact` tools all read and write it here. The people are your LinkedIn
connections and whoever you added by hand (someone who isn't on LinkedIn): see contacts.py."""

from __future__ import annotations

from . import GUIDE, jobpass
from .config import Config
from .contacts import clean_person, company_key, hand_note
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
    company, status}]. A person added by hand (by_hand; see add) is listed like a connection, with their about (own
    note), reach (how you reach them: contacts.REACH), email, phone and added_at, and the note shown is reach and about
    together. min_fit is the fit that makes a good fit (see good_fit) and details holds each listed job's
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
    except (OSError, AttributeError):  # no file, or none set (only people added by hand)
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
    """The connection, or person added by hand, that a name or linkedin.com/in/ link means (see Contacts.find)."""
    known = load_contacts(cfg)
    if not known:
        if not cfg.connections:
            raise ValueError("no connections file: set `connections:` in the watchlist, or add someone by hand")
        raise ValueError("the connections file couldn't be read")
    return known.find(who)


def rate(cfg: Config, store: Store, who: str, verdict: str, note: str = "") -> dict:
    """Record use or skip for a person (verdict "clear" forgets it). Returns the person with the new verdict.
    Someone added by hand keeps their words with them (their note, not the choice): a note that differs from what
    is shown beside them now replaces it, one that matches (a pill's key press sends it back) changes nothing."""
    person = resolve(cfg, who)
    if verdict == "clear":
        store.clear_contact(person["key"])
        return {**person, "verdict": "", "note": hand_note(person) if person["by_hand"] else ""}
    if person["by_hand"]:
        if (note := note.strip()) and note != person["note"]:
            store.update_person(person["key"], note=note)
            person = resolve(cfg, person["key"])
        store.rate_contact(person["key"], verdict, "")
        return {**person, "verdict": verdict}
    store.rate_contact(person["key"], verdict, note)
    return {**person, "verdict": verdict, "note": note.strip()}


class AlreadyKnown(ValueError):
    """Someone is already listed at that company; .person is who (as Contacts lists them)."""

    def __init__(self, person: dict):
        by_hand = person.get("by_hand")
        super().__init__(f"Already {'added by hand' if by_hand else 'in your connections'}: {person['name']}"
                         f" at {person['company']}")
        self.person = person


def duplicate(cfg: Config, name: str, company: str) -> dict | None:
    """Someone already listed with this name at this company (any spelling of it), or None."""
    known = load_contacts(cfg)
    return known.duplicate(name, company) if known else None


def tracked(store: Store, company: str) -> bool:
    """Whether a job you track is at this company (any spelling of its name), so people there show on Referrals."""
    from .company import _groups  # company reads watch, as this module does
    key = company_key(company)
    return any(company_key(n) == key
               for g in _groups(store).values() for n in (*g["names"], *(b for _, b in g["boards"])))


def add(cfg: Config, store: Store, name: str, company: str, title: str = "", note: str = "", reach: str = "",
        url: str = "", email: str = "", phone: str = "", added_at: str | None = None) -> dict:
    """Add someone who isn't a LinkedIn connection (a friend, an ex-colleague, someone met in person), kept in the
    state file and listed everywhere connections are. Raises AlreadyKnown (a ValueError) when someone with that name
    is listed at that company, ValueError for anything else wrong. Returns the person as the lists show them, with
    tracked: whether a job you track is at their company (when not, they show on Referrals once one is)."""
    clean_person(name, company, title, note, reach, url, email, phone)  # say what is wrong before what is known
    if dup := duplicate(cfg, name, company):
        raise AlreadyKnown(dup)
    key = store.add_person(name, company, title, note, reach, url, email, phone, added_at)["key"]
    return {**resolve(cfg, key), "tracked": tracked(store, company)}


def update(cfg: Config, store: Store, who: str, **fields: str | None) -> dict:
    """Change someone added by hand (name, company, title, note, reach, url, email, phone). ValueError for a
    LinkedIn connection: only their choice can be changed."""
    person = _by_hand(cfg, who, "changed")
    return resolve(cfg, store.update_person(person["key"], **fields)["key"])  # the key follows a new name or link


def _by_hand(cfg: Config, who: str, what: str) -> dict:
    person = resolve(cfg, who)
    if not person["by_hand"]:
        raise ValueError(f"{person['name']} is one of your LinkedIn connections: they can't be {what} here"
                         + (", only skipped" if what == "removed" else ""))
    return person


def remove(cfg: Config, store: Store, who: str) -> dict:
    """Forget someone added by hand. ValueError for a LinkedIn connection (they can only be skipped). Returns them,
    to put back."""
    person = _by_hand(cfg, who, "removed")
    store.remove_person(person["key"])
    return person


def text(v: dict) -> str:
    """The same rows as a list for the terminal."""
    if not v["has_connections"]:
        return (f"No connections file: set `connections:` in the watchlist, or add someone yourself with "
                f"`jobwatch referrals --add NAME --company COMPANY` (see {GUIDE}/contacts.md).")

    def line(p: dict) -> str:
        mark = {"use": "[use] ", "skip": "[don't use] "}.get(p["verdict"], "")
        jobs = ", ".join(f"{j['company']}: {j['title']}" for j in p["jobs"][:3])
        more = f" and {len(p['jobs']) - 3} more" if len(p["jobs"]) > 3 else ""
        reach = ", ".join(filter(None, (p["email"], p["phone"])))
        return (f"  {mark}{p['name']}" + (f" ({p['position']})" if p["position"] else "") + f", {p['company']}"
                + (f" [{p['why']}]" if p["why"] else "") + (f" - {p['note']}" if p["note"] else "")
                + (f" <{reach}>" if reach else "")
                + ("  (in your watchlist file)" if p["from_file"] else "") + f"\n      {jobs}{more}")
    out = [f"People you know at companies you're tracking ({len(v['people'])}):"]
    out += [line(p) for p in v["people"]] or ["  nobody yet"]
    if v["skipped"]:
        out += ["", f"Not suggested ({len(v['skipped'])}):"] + [line(p) for p in v["skipped"]]
    return "\n".join(out)
