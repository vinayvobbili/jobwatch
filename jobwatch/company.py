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
from dataclasses import replace
from urllib.parse import urlparse

from . import contacts as people
from . import dupes, jobpass, report, rounds, sources, suggest
from .config import Config
from .filters import KINDS, focus_hits, rejection
from .localday import local_day
from .models import Job
from .package import Package
from .score import resume_id
from .store import ENDED, MANUAL, STAGES, STATUSES, Store, _letters, closed_state
from .watch import _fits, load_contacts

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


def on_a_board(store: Store, name: str) -> bool:
    """Whether a job of a company this name goes by was read from a board (not added by hand)."""
    return any(source != MANUAL for source, _ in _groups(store).get(dupes.company_key(name), {}).get("boards", ()))


def _rank(query: str, keys: set[str]) -> int | None:
    """0 for the same name, 1 for a name that starts with the search, 2 for one that contains it, else None.
    (search ranks a company known by its board's name only after these.)"""
    if query in keys:
        return 0
    if any(k.startswith(query) for k in keys):
        return 1
    return 2 if any(query in k for k in keys) else None


def _groups(store: Store) -> dict[str, dict]:
    """Every company the jobs name, by its key: name, the keys it goes by, its boards and its jobs counted by
    status. Grouping the table takes most of a second, and the page's search box asks on every keystroke, so it is
    kept until something is written (see jobpass.py)."""
    return jobpass.remembered(store, "company-groups", (), lambda: _group_companies(store))


def _group_companies(store: Store) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in store.company_counts():
        probe = Job(source=r["source"], company=r["company"], id="", title="", url="", company_name=r["name"] or "")
        key = dupes.company_key(probe.display_company)
        if not key:
            continue
        g = out.setdefault(key, {"names": Counter(), "keys": set(), "status": Counter(), "open": 0,
                                 "boards": set()})
        g["boards"].add((r["source"], r["company"]))
        g["names"][probe.display_company] += r["n"]
        g["keys"] |= dupes.companies(probe)
        g["status"][r["status"]] += r["n"]
        g["open"] += r["n"] * (not r["closed"] and r["status"] in ("new", "shown"))
    return out


def search(store: Store, text: str, limit: int = 8) -> list[dict]:
    """The companies a name, part of one, or a domain matches, best first: name, key, applications (applied or
    a later stage), queued, skipped, open (new roles on a board), jobs (all of them) and exact (the same
    name). Names are also compared by their letters alone, as Store.find does: "Pied Piper" finds "Pied & Piper",
    whose key reads "piedandpiper", and as the same name as it."""
    query = query_key(text)
    if len(query) < MIN_KEY:
        return []
    groups = _groups(store)
    bare = _letters(text) if query == dupes.company_key(text) else query  # a domain's name is already bare
    found = _ranked(groups, lambda key, g: _rank(query, {key}), lambda key, g: _rank(query, g["keys"]))
    if len(bare) >= MIN_KEY:
        loose = _ranked(groups, lambda key, g: _rank(bare, {_letters(n) for n in g["names"]}), lambda key, g: None)
        best = {f["key"]: (r, f) for r, f in loose}
        for r, f in found:  # the better of the two ranks
            if f["key"] not in best or r < best[f["key"]][0]:
                best[f["key"]] = (r, f)
        found = list(best.values())
    found.sort(key=lambda f: (f[0], not f[1]["applications"], not f[1]["queued"], f[1]["name"].lower()))
    return [f for _, f in found[:limit]]


def _ranked(groups: dict[str, dict], by_name, by_board) -> list[tuple[int, dict]]:
    """(rank, company) for each group whose name ranks, or else whose board's name does (below those)."""
    found = []
    for key, g in groups.items():
        rank = by_name(key, g)
        if rank is None and (rank := by_board(key, g)) is not None:
            rank += 3  # only its board's name matches
        if rank is not None:
            s = g["status"]
            found.append((rank, {"name": g["names"].most_common(1)[0][0], "key": key,
                                 "applications": sum(s[x] for x in STAGES), "queued": s["queued"],
                                 "skipped": s["skipped"], "open": g["open"], "jobs": sum(s.values()),
                                 "exact": rank == 0}))
    return found


# Open applications, then queued jobs, the ones that ended, skipped ones, and last the roles not acted on.
def _order(rec: dict) -> int:
    s = rec["status"]
    return (0 if s in STAGES and s not in ENDED else 1 if s in ("queued", "snoozed") else 2 if s in ENDED
            else 3 if s == "skipped" else 4)


def _day(value: str | None) -> str | None:
    return local_day(value) or None


def _job(store: Store, job: Job, rec: dict, index: dupes.Index) -> dict:
    same = index.match(job, rec)
    pkg = Package(store.packages, job.key).summary()
    return {"key": job.key, "title": job.title, "url": job.url, "locations": job.places, "pay": job.pay(),
            "status": rec["status"], "closed": _day(rec.get("closed")), "closed_state": closed_state(rec),
            "first_seen": _day(rec.get("first_seen")),
            "posted": job.posted.date().isoformat() if job.posted else None, "applied_at": rec.get("applied_at"),
            "status_at": _day(rec.get("status_at")), "next_step": rec.get("next_step"),
            "round": rec.get("round"), "length": rounds.length_of(rec), "follow_up": rec.get("follow_up"),
            "due": report.due(rec), "note": rec.get("note"),
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


def _left_out(cfg: Config, store: Store, rows: list[tuple[Job, dict]]) -> dict[str, str]:
    """The open roles not acted on that Today's filters would hide, each key -> its filter (filters.KINDS): what
    view() leaves out under display.company: matches. Not their age: an older role still open at a company you
    looked up is one to see. Nor one you wrote a note, next step or follow-up on: you're keeping an eye on it."""
    fits = _fits(store, resume_id(cfg.resume, cfg.prompts)) if cfg.resume and cfg.resume.is_file() else {}
    return {job.key: r[0] for job, rec in rows
            if not (rec.get("note") or rec.get("next_step") or rec.get("follow_up"))
            and (r := rejection(job, replace(cfg.filters_for(job), max_age_days=None), fits.get(job.key)))}


def _mine(store: Store, key: str) -> list[tuple[Job, dict]]:
    """Every job at the company with this key (see search), closed postings too, open applications first, then
    queued ones, the ones that ended, skipped ones, and last the roles not acted on (newest first within each).
    Only the boards the company's jobs are on are read (_groups knows them), not all 63,000 jobs."""
    mine = [(job, rec) for job, rec in store.board_rows(_groups(store).get(key, {}).get("boards", ()))
            if dupes.company_key(job.display_company) == key]
    mine.sort(key=lambda r: _order(r[1]))  # stable: newest first within each
    return mine


def view(cfg: Config, store: Store, text: str, every: bool | None = None,
         statuses: tuple[str, ...] = ()) -> dict | None:
    """Everything tracked at the company a name or domain matches best (None when none matches): each job with
    its status and dates, next step, follow-up, note, whether a package was saved, and a duplicate warning;
    people you know there; and whether its board is watched. Roles that closed without being acted on are only
    counted (closed_unacted). Open ones you haven't acted on that Today's filters would hide, age aside (a big
    board lists roles in other cities, a pharmacy chain's lists nurses), are only counted too: left_out, with
    left_out_by (filter -> count); `every` (by default display.company: all) lists them as well. The rest are
    listed up to OPEN_SHOWN (more_open). Other companies the name matched are in `also`. With `statuses`, every job
    at one of them is listed instead (closed postings and the ones the filters leave out too, none cut)."""
    found = search(store, text, limit=6)
    if not found:
        return None
    best, key = found[0], found[0]["key"]
    index = jobpass.acted_index(store)
    mine = _mine(store, key)
    acted = [r for r in mine if _order(r[1]) < 4]
    unacted = [r for r in mine if _order(r[1]) == 4 and not r[1].get("closed")]
    # A board's roles all arrive together when it's first watched: the latest posting leads, not the order they came
    unacted.sort(key=lambda r: (r[0].posted.isoformat() if r[0].posted else "", r[1]["first_seen"]), reverse=True)
    unacted.sort(key=lambda r: -focus_hits(r[0], cfg.focus))  # stable: the work wanted most (focus) first
    every = cfg.company_view == "all" if every is None else every
    hide = {} if every else _left_out(cfg, store, unacted)
    open_ = [r for r in unacted if r[0].key not in hide]
    listed = acted + open_
    shown = acted + open_[:OPEN_SHOWN]
    closed_unacted = len(mine) - len(acted) - len(unacted)
    if statuses:
        listed = shown = [r for r in mine if r[1]["status"] in statuses]
        hide, every, closed_unacted = {}, True, 0
    by = Counter(hide.values())
    jobs = [j for j, _ in mine]
    known = load_contacts(cfg)
    names = {best["name"], *(j.company for j in jobs)}
    counts = Counter(rec["status"] for _, rec in listed)
    return {"company": best["name"], "query": text.strip(), "key": key,
            "counts": {s: counts[s] for s in counts}, "jobs": [_job(store, j, rec, index) for j, rec in shown],
            "closed_unacted": closed_unacted, "more_open": len(listed) - len(shown), "statuses": list(statuses),
            "left_out": len(hide), "left_out_by": {k: by[k] for k in KINDS if by[k]}, "every": every,
            "contacts": known.at(*names) if known else [],
            "find_referral": people.linkedin_search(best["name"]), "watch": _watch(cfg, store, best["name"], jobs),
            "also": [f["name"] for f in found[1:]]}


NOTE_SHOWN = 200  # characters of a note the text view prints


def note_preview(note: str, most: int = NOTE_SHOWN) -> tuple[str, bool]:
    """(the note for a terminal, whether some was left out): the latest dated entry (notes grow a dated line at a
    time), cut to `most` characters with an ellipsis."""
    note = " ".join(note.split())
    latest = re.split(r"\s(?=\d{4}-\d{2}-\d{2}\b)", note)[-1]
    if len(latest) > most:
        latest = latest[:most - 1].rstrip() + "…"
    return latest, latest != note


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
        facts.append(f"posting closed {j['closed']}" if j["closed_state"] == "closed"
                     else f"posting may have closed {j['closed']} (checking)")
    if j["has_package"]:
        facts.append("package saved")
    out = [f"  {j['company'] + ': ' if j.get('company') else ''}{j['title']}", f"    {' · '.join(facts)}"]
    if j["next_step"] or j["follow_up"]:
        step = " · ".join(x for x in (j["next_step"], f"follow up {j['follow_up']}" if j["follow_up"] else "") if x)
        out.append(("    Due: " if j["due"] else "    Next: ") + step)
    if j["note"]:
        shown, cut = note_preview(j["note"])
        out.append(f"    Note: {shown}" + (f" (all of it: `jobwatch show {j['key']}`)" if cut else ""))
    if j["duplicate_of"]:
        out.append(f"    Check: {j['duplicate_of']['text']}")
    return [*out, f"    `{j['key']}`"]


def mentions(store: Store, text: str) -> list[dict]:
    """Every tracked job, whatever its status, open or closed, whose note, next step, via, title, company, key or
    link contains the text (see Store.search): each as view() lists a job, plus its company."""
    index, out = dupes.Index(store), []
    for job, rec in store.search(text):
        j = {**_job(store, job, rec, index), "company": job.display_company}
        # the text view shows a note's latest dated entry: show the one that matched instead (json has it all)
        entries = re.split(r"\s(?=\d{4}-\d{2}-\d{2}\b)", " ".join((j["note"] or "").split()))
        j["note_match"] = next((e for e in entries if text.strip().lower() in e.lower()), None)
        out.append(j)
    return out


def mentions_text(found: list[dict], query: str) -> str:
    """`jobwatch search`: the jobs to read."""
    if not found:
        return f"No tracked job has {query!r} in its note, next step, source, title, company, key or link."
    out = [f"{len(found)} job{'s' * (len(found) != 1)} mention{'s' * (len(found) == 1)} {query!r}:", ""]
    for j in found:
        out += _line({**j, "note": j["note_match"] or j["note"]})
    return "\n".join(out)


SNIPPET = 90  # characters of posting text kept on each side of a match


def term_pattern(term: str) -> re.Pattern:
    """A term as a whole word or phrase, never inside another word ("ITAR" is not in "military"). A term written
    in capitals (an acronym: ITAR, EAR) also matches in that case only, so "ear" in running text is not "EAR"; any
    other term matches in any case, and its plural too ("U.S. Person" finds "U.S. Persons"). Spaces match any run
    of whitespace; the rest is taken literally."""
    words = r"\s+".join(re.escape(w) for w in term.split())
    if term.isupper():
        return re.compile(rf"(?<!\w){words}(?!\w)")
    return re.compile(rf"(?<!\w){words}(?:s)?(?!\w)", re.I)


def posting_hits(store: Store, name: str, terms: list[str], include_closed: bool = False,
                 only_open: bool = False, live=None) -> dict | None:
    """The jobs of the company a name matches best (None when none matches) whose posting text holds any of the
    terms as whole words (see term_pattern), each as view() lists a job, plus `matches`: every term found with a
    bit of the text around its first occurrence. Reads the text jobwatch kept, which a live page can differ from;
    `slim` jobs lost theirs (see prune.py) and are counted as `no_text`. A posting whose closing a second look
    confirmed is left out unless include_closed; only_open leaves out every posting with a closed mark, one look
    or two; `scanned` counts the jobs read. With `live` (a function job -> the text of its page now, "" when it
    can't be read; see live_text) each job is read from its page instead of the kept text, falling back to the kept
    text when the page won't read (counted as `unreadable`); `in_saved` names the terms the kept text has, to show
    what a live page added. Nothing is saved."""
    if not (terms := [t.strip() for t in terms if t.strip()]):
        raise ValueError("give at least one term to look for")
    if not (found := search(store, name, limit=1)):
        return None
    patterns = {t: term_pattern(t) for t in terms}
    index, out, scanned, no_text, unreadable = jobpass.acted_index(store), [], 0, 0, []
    for job, rec in _mine(store, found[0]["key"]):
        state = closed_state(rec)
        if (state == "closed" and not include_closed) or (state and only_open):
            continue
        scanned += 1
        saved = _found(patterns, job.description)
        no_text += not job.description.strip()
        read, matches = "saved", saved
        if live:
            if page := live(job):
                read, matches = "live", _found(patterns, page)
            else:
                read = "saved (live page unreadable)"
                unreadable.append(job.key)
        if matches:
            out.append({**_job(store, job, rec, index), "company": job.display_company, "id": job.id,
                        "matches": matches, "read": read, "in_saved": [m["term"] for m in saved]})
    return {"company": found[0]["name"], "terms": terms, "scanned": scanned, "no_text": no_text,
            "unreadable": unreadable, "live": bool(live), "jobs": out}  # unreadable: the keys


def _found(patterns: dict[str, re.Pattern], text: str) -> list[dict]:
    """Each term that is in the text, with a bit of the text around its first occurrence."""
    body, found = " ".join(text.split()), []
    for term, pattern in patterns.items():
        if m := pattern.search(body):
            found.append({"term": term, "snippet": body[max(0, m.start() - SNIPPET):m.end() + SNIPPET]})
    return found


def live_text(job: Job, get=None) -> str:
    """The posting's text as its own page gives it now, or "" when that can't be read (the board no longer lists
    it, the link is no board's, a network error). Nothing is saved."""
    try:
        posting = sources.posting(job.posting_url or job.url, get) if job.url else None
    except sources.SourceError:
        return ""
    return posting.description if posting else ""


def posting_hits_text(v: dict | None, name: str) -> str:
    """`jobwatch grep`: the jobs to read."""
    if not v:
        return f"No tracked job is at a company matching {name!r}."
    n, terms = len(v["jobs"]), ", ".join(v["terms"])
    out = [f"# {v['company']}", f"{n} of {v['scanned']} job{'s' * (v['scanned'] != 1)} read name {terms}"
           + (f" ({v['no_text']} had no posting text kept)." if v["no_text"] and not v["live"] else "."), ""]
    if n := len(v["unreadable"]):
        out[1] += f" {n} live page{'s' * (n != 1)} couldn't be read (--format json lists them)."
    for j in v["jobs"]:
        out += _line(j)
        out += [f"    Read: {j['read']}; the kept text has: {', '.join(j['in_saved']) or 'none of them'}"]
        out += [f"    Found {m['term']!r}: ...{m['snippet']}..." for m in j["matches"]]
    return "\n".join(out)


def text(v: dict | None, query: str = "") -> str:
    """`jobwatch company`: the view to read."""
    if not v:
        return f"No tracked job is at a company matching {query!r}: nothing new, queued, applied to or skipped."
    n = sum(v["counts"].values())
    if v.get("statuses") and not n:
        return f"No {' or '.join(v['statuses'])} job at {v['company']}."
    by = ", ".join(f"{c} {s}" for s, c in sorted(v["counts"].items(), key=lambda x: _order({"status": x[0]})))
    out = [f"# {v['company']}", f"{n} job{'s' * (n != 1)}: {by}.", ""]
    for j in v["jobs"]:
        out += _line(j)
    if v["more_open"]:
        out.append(f"  and {v['more_open']} more open roles you haven't acted on: `jobwatch list --status new`")
    if v["left_out"]:
        why = ", ".join(f"{k} {n}" for k, n in v["left_out_by"].items())
        out.append(f"  {v['left_out']} open role{'s' * (v['left_out'] != 1)} your filters leave out ({why}) not "
                   "listed: --all lists them")
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


def _brief(job: Job, rec: dict) -> dict:
    return {"key": job.key, "title": job.title, "status": rec["status"]}


def mark_all(store: Store, name: str, status: str, only: tuple[str, ...] = (), include_active: bool = False,
             dry_run: bool = False, note: str | None = None, add_note: str | None = None, on: str | None = None,
             next_step: str | None = None, follow_up: str | None = None, round: str | None = None,
             length: str | None = None) -> dict:
    """Give every job at the company the name matches the status (`jobwatch mark STATUS --company NAME`): only
    those now in a status of `only` when given. A job you applied to (applied or any later stage) is left alone
    unless include_active: a status like skipped would drop its applied day. A job already in the status isn't
    touched. dry_run changes nothing. Returns company, status, dry_run, changed (key, title, was: its status
    before), left_alone (the jobs held back: key, title, status) and already (key, title). The name must match one
    company: the exact name, or no other."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if note is not None and not note.strip():
        raise ValueError("--note is empty and would erase the note; leave it out to keep the note")
    found = search(store, name, limit=6)
    if not found:
        raise ValueError(f"no tracked job is at a company matching {name!r}")
    if len(found) > 1 and not (found[0]["exact"] and not found[1]["exact"]):
        raise ValueError(f"{name!r} matches several companies ({', '.join(f['name'] for f in found)}): give the "
                         "full name of one")
    if not include_active and (held := [s for s in only if s in STAGES]):
        raise ValueError(f"{', '.join(held)}: jobs you applied to are only changed with --include-active")
    rows = [r for r in _mine(store, found[0]["key"]) if not only or r[1]["status"] in only]
    left = [] if include_active else [r for r in rows if r[1]["status"] in STAGES]
    rest = [r for r in rows if r not in left]
    same = [r for r in rest if r[1]["status"] == status]
    change = [r for r in rest if r not in same]
    keys = [j.key for j, _ in change]
    if keys and not dry_run:
        store.set_status(keys, status, note, on=on)
        for k in keys:
            store.track(k, next_step=next_step, follow_up=follow_up, round=round, length=length)
            if add_note:
                store.add_note(k, add_note)
    return {"company": found[0]["name"], "status": status, "dry_run": dry_run,
            "changed": [{"key": j.key, "title": j.title, "was": rec["status"]} for j, rec in change],
            "left_alone": [_brief(j, rec) for j, rec in left],
            "already": [{"key": j.key, "title": j.title} for j, _ in same]}


def mark_all_text(r: dict) -> str:
    """`jobwatch mark --company`: a line per job changed (`key: status`, as `mark` prints one), then what was held
    back and why."""
    out = [f"would mark {c['key']}: {r['status']} (was {c['was']})" if r["dry_run"] else f"{c['key']}: {r['status']}"
           for c in r["changed"]]
    if r["left_alone"]:
        out.append("Left alone, applied to (--include-active changes them): " + ", ".join(
            f"{j['key']} ({j['status']})" for j in r["left_alone"]))
    if r["already"]:
        out.append(f"Already {r['status']}: {len(r['already'])}.")
    if not r["changed"] and not r["left_alone"] and not r["already"]:
        out.append(f"No job at {r['company']} to mark.")
    return "\n".join(out)
