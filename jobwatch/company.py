"""Look up one company across everything tracked: whichever status its jobs are in (new, queued, applied, an
interview, rejected, skipped...) and open or closed. Today only shows new roles on watched boards, so a company
you added by hand or are already talking to isn't there; this finds it by name.

A name matches the way dupes.py compares companies (case, punctuation, suffixes such as Inc aside), and a
domain ("acme.com", "https://www.acme.com/careers") matches the company's name: "acme" finds "Acme Robotics, Inc."
as a start of its name, "robotics" as part of it. An exact name comes first, then the ones whose name starts with
it, then the rest, companies you applied to before those you only watch.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter
from urllib.parse import urlparse

from . import contacts as people
from . import dupes, report, suggest
from .config import Config
from .models import Job
from .package import Package
from .store import ENDED, STAGES, Store
from .watch import load_contacts

MIN_KEY = 2     # a shorter search ("a") would match nearly everything
OPEN_SHOWN = 25  # open roles listed that you haven't acted on: a watched board can have hundreds

_HOST = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:[/?#:]\S*)?", re.I)
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac"}  # acme.co.uk: the name is "acme", not "co"


def query_key(text: str) -> str:
    """What a search matches on: a domain gives its name ("https://www.acme.com/careers" -> "acme"), any other
    text is set aside like a company name (see dupes.company_key)."""
    text = text.strip()
    if " " not in text and _HOST.fullmatch(text):
        host = (urlparse(text if "//" in text else "//" + text).hostname or "").removeprefix("www.")
        labels = host.split(".")[:-1]  # without the top-level domain
        if len(labels) > 1 and labels[-1] in _SECOND_LEVEL:
            labels.pop()
        if labels:
            return dupes.company_key(labels[-1])
    return dupes.company_key(text)


def _rank(query: str, keys: set[str]) -> int | None:
    """0 for the same name, 1 for a name that starts with the search, 2 for one that contains it, else None.
    (search ranks a company known by its board's name only after these.)"""
    if query in keys:
        return 0
    if any(k.startswith(query) for k in keys):
        return 1
    return 2 if any(query in k for k in keys) else None


def _groups(store: Store) -> dict[str, dict]:
    """Every company the jobs name, by its key: name, the keys it goes by, and its jobs counted by status."""
    out: dict[str, dict] = {}
    for r in store.company_counts():
        probe = Job(source=r["source"], company=r["company"], id="", title="", url="", company_name=r["name"] or "")
        key = dupes.company_key(probe.display_company)
        if not key:
            continue
        g = out.setdefault(key, {"names": Counter(), "keys": set(), "status": Counter(), "open": 0})
        g["names"][probe.display_company] += r["n"]
        g["keys"] |= dupes.companies(probe)
        g["status"][r["status"]] += r["n"]
        g["open"] += r["n"] * (not r["closed"] and r["status"] in ("new", "shown"))
    return out


def search(store: Store, text: str, limit: int = 8) -> list[dict]:
    """The companies a name, part of one, or a domain matches, best first: name, key, applications (applied or
    a later stage), queued, skipped, open (new roles on a board), jobs (all of them) and exact (the same
    name)."""
    query = query_key(text)
    if len(query) < MIN_KEY:
        return []
    found = []
    for key, g in _groups(store).items():
        rank = _rank(query, {key})
        if rank is None and (rank := _rank(query, g["keys"])) is not None:
            rank += 3  # only its board's name matches
        if rank is not None:
            s = g["status"]
            found.append((rank, {"name": g["names"].most_common(1)[0][0], "key": key,
                                 "applications": sum(s[x] for x in STAGES), "queued": s["queued"],
                                 "skipped": s["skipped"], "open": g["open"], "jobs": sum(s.values()),
                                 "exact": rank == 0}))
    found.sort(key=lambda f: (f[0], not f[1]["applications"], not f[1]["queued"], f[1]["name"].lower()))
    return [f for _, f in found[:limit]]


# Open applications, then queued jobs, the ones that ended, skipped ones, and last the roles not acted on.
def _order(rec: dict) -> int:
    s = rec["status"]
    return (0 if s in STAGES and s not in ENDED else 1 if s == "queued" else 2 if s in ENDED
            else 3 if s == "skipped" else 4)


def _day(value: str | None) -> str | None:
    return value[:10] if value else None


def _job(store: Store, job: Job, rec: dict, index: dupes.Index) -> dict:
    same = index.match(job, rec)
    pkg = Package(store.packages, job.key).summary()
    return {"key": job.key, "title": job.title, "url": job.url, "locations": job.places, "pay": job.pay(),
            "status": rec["status"], "closed": _day(rec.get("closed")), "first_seen": _day(rec.get("first_seen")),
            "posted": job.posted.date().isoformat() if job.posted else None, "applied_at": rec.get("applied_at"),
            "status_at": _day(rec.get("status_at")), "next_step": rec.get("next_step"),
            "follow_up": rec.get("follow_up"), "due": report.due(rec), "note": rec.get("note"),
            "via": rec.get("via"), "package": pkg, "has_package": any(pkg.values()),
            "duplicate_of": same.to_dict() if same else None}


def _watch(cfg: Config, store: Store, name: str, jobs: list[Job]) -> dict:
    """Whether the company's board is on the watchlist and, when it isn't, what to pass add_board."""
    on = [e for j in jobs for e in suggest.posted_on(j)]
    if any(suggest.watched(cfg.boards, name, e) for e in on or [""]):
        return {"watched": True, "entry": None, "command": None, "add_board": None, "careers": None,
                "suggested": False}
    row = next((r for r in store.unwatched(dismissed=True) if r["company"] == suggest.company_id(name)), None)
    entry = on[0] if on else (row["entry"] if row else None)
    s = suggest.Suggestion(suggest.company_id(name), name, entry or None)
    # `suggest --add` knows the companies recorded as unwatched; for any other, `find` shows what to add.
    command = suggest.Suggestion(row["company"], row["name"], row["entry"]).command if row else \
        f"jobwatch find {shlex.quote(name)}"
    return {"watched": False, "entry": entry or None, "careers": s.careers or None, "command": command,
            "add_board": {"entry": entry, "name": s.board_name} if entry else None,
            "suggested": bool(row)}


def view(cfg: Config, store: Store, text: str) -> dict | None:
    """Everything tracked at the company a name or domain matches best (None when none matches): each job with
    its status and dates, next step, follow-up, note, whether a package was saved, and a duplicate warning;
    people you know there; and whether its board is watched. Roles that closed without being acted on are only
    counted (closed_unacted), and open ones you haven't acted on are listed up to OPEN_SHOWN (more_open). Other
    companies the name matched are in `also`."""
    found = search(store, text, limit=6)
    if not found:
        return None
    best, key = found[0], found[0]["key"]
    index, mine = dupes.Index(store), []
    for job, rec in store.jobs(include_closed=True):
        if dupes.company_key(job.display_company) == key:
            mine.append((job, rec))
    mine.sort(key=lambda r: _order(r[1]))  # stable: newest first within each
    listed = [r for r in mine if _order(r[1]) < 4 or not r[1].get("closed")]
    shown = [r for r in listed if _order(r[1]) < 4] + [r for r in listed if _order(r[1]) == 4][:OPEN_SHOWN]
    jobs = [j for j, _ in mine]
    known = load_contacts(cfg)
    names = {best["name"], *(j.company for j in jobs)}
    counts = Counter(rec["status"] for _, rec in listed)
    return {"company": best["name"], "query": text.strip(), "key": key,
            "counts": {s: counts[s] for s in counts}, "jobs": [_job(store, j, rec, index) for j, rec in shown],
            "closed_unacted": len(mine) - len(listed), "more_open": len(listed) - len(shown),
            "contacts": known.at(*names) if known else [],
            "find_referral": people.linkedin_search(best["name"]), "watch": _watch(cfg, store, best["name"], jobs),
            "also": [f["name"] for f in found[1:]]}


def _line(j: dict) -> list[str]:
    """One job: its status and dates, then what's next, the note and any warning."""
    facts = [j["status"]]
    if j["applied_at"]:
        facts.append(f"applied {j['applied_at']}")
    elif j["posted"]:
        facts.append(f"posted {j['posted']}")
    elif j["status"] in ("new", "shown") and j["first_seen"]:
        facts.append(f"first seen {j['first_seen']}")
    elif j["status_at"]:
        facts.append(f"since {j['status_at']}")
    if j["closed"]:
        facts.append(f"posting closed {j['closed']}")
    if j["has_package"]:
        facts.append("package saved")
    out = [f"  {j['title']}", f"    {' · '.join(facts)}"]
    if j["next_step"] or j["follow_up"]:
        step = " · ".join(x for x in (j["next_step"], f"follow up {j['follow_up']}" if j["follow_up"] else "") if x)
        out.append(("    Due: " if j["due"] else "    Next: ") + step)
    if j["note"]:
        out.append(f"    Note: {j['note']}")
    if j["duplicate_of"]:
        out.append(f"    Check: {j['duplicate_of']['text']}")
    return [*out, f"    `{j['key']}`"]


def text(v: dict | None, query: str = "") -> str:
    """`jobwatch company`: the view to read."""
    if not v:
        return f"No tracked job is at a company matching {query!r}: nothing new, queued, applied to or skipped."
    n = sum(v["counts"].values())
    by = ", ".join(f"{c} {s}" for s, c in sorted(v["counts"].items(), key=lambda x: _order({"status": x[0]})))
    out = [f"# {v['company']}", f"{n} job{'s' * (n != 1)}: {by}.", ""]
    for j in v["jobs"]:
        out += _line(j)
    if v["more_open"]:
        out.append(f"  and {v['more_open']} more open roles you haven't acted on: `jobwatch list --status new`")
    if v["closed_unacted"]:
        out.append(f"  {v['closed_unacted']} closed posting{'s' * (v['closed_unacted'] != 1)} you never acted on "
                   "not listed")
    if v["contacts"]:
        out += ["", f"You know: {report.people(v['contacts'], most=10)}"]
    else:
        out += ["", f"Find someone who could refer you: {v['find_referral']}"]
    w = v["watch"]
    if not w["watched"]:
        out.append(f"Not watched: its board isn't on your watchlist, so new roles there aren't checked. "
                   f"Run `{w['command']}`"
                   + (f" (add_board {w['add_board']['entry']})" if w["add_board"] else "") + ".")
    if v["also"]:
        out.append("Also matches: " + ", ".join(v["also"]) + " (give a longer name to see one)")
    return "\n".join(out)
