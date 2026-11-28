"""People you know at a company, from your LinkedIn data: a referral beats a cold application.

LinkedIn: Settings > Data privacy > Get a copy of your data. Either file works:

- Connections.csv: who you're connected to, with their current company and position.
- The full archive (.zip): the same, plus how well you know each person, counted from messages you exchanged,
  recommendations, and endorsements. Only counts and dates are used. Message text is never read or kept.

Someone who isn't on LinkedIn (or isn't a connection) is added by hand and kept in jobwatch's own store, so a fresh
LinkedIn export never drops them (see Store.add_person and referrals.add).

Everything stays on your machine.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

# Legal and filler words that differ between how a board and a profile name one company.
_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "com", "company", "pbc", "plc", "gmbh", "the",
             "technologies", "technology", "labs", "ai", "hq", "group", "holdings"}

# A division people name on their profile, by its key, -> the company whose board posts its jobs.
DIVISIONS = {"amazon web services": "amazon", "aws": "amazon"}

TIES_FILE = "linkedin-ties.json"  # derived from an archive, kept next to Connections.csv

# People you add by hand (a friend, an ex-colleague, someone met in person) live in jobwatch's own store, not in
# LinkedIn's file, so a fresh export never drops them. They are listed wherever connections are. You added them on
# purpose, so each ranks as a close tie: like someone you exchanged ADDED_STRENGTH messages with (see strength()),
# above anyone who only accepted a request or endorsed you, below a recommendation (10) and your real correspondents.
ADDED_STRENGTH = 5
BY_HAND = "added by hand"
NOTE_MAX = 200
# How you reach someone, as the page's quick-pick offers it (key -> the words shown beside their name).
REACH = {"whatsapp": "reach on WhatsApp", "text": "reach by text", "email": "reach by email", "phone": "reach by phone",
         "in person": "see in person"}


def company_key(name: str) -> str:
    """ "Acme, Inc." and "acme" -> "acme"; "Scale AI" -> "scale"; "Acme Cloud (AC)" -> "acme cloud"; a division in
    DIVISIONS -> its company. Empty when nothing is left."""
    bare = re.sub(r"\([^)]*\)", " ", name) if re.sub(r"\([^)]*\)", "", name).strip() else name
    words = re.findall(r"[a-z0-9]+", bare.lower().replace("&", " and "))
    core = " ".join([w for w in words if w not in _SUFFIXES] or words)
    return DIVISIONS.get(core, core)


def profile_key(url: str) -> str:
    """linkedin.com/in/<slug>, however the export wrote it."""
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


def _name_key(first: str, last: str = "") -> str:
    return " ".join(f"{first} {last}".lower().split())


def person_key(person: dict) -> str:
    """How feedback about a person is keyed: their profile slug when they have a link, else "name:<full name>"
    (the same keys the tie counts use)."""
    return profile_key(person.get("url", "")) or "name:" + _name_key(person.get("name", ""))


def key_for(who: str) -> str:
    """person_key for what a person typed: a linkedin.com/in/ link, or a name."""
    return profile_key(who) or "name:" + _name_key(who)


def _rows(text: str, first_column: str) -> list[dict]:
    """CSV rows, skipping the notes LinkedIn puts above some headers."""
    lines = text.lstrip("﻿").splitlines()
    # The full archive quotes some headers ("CONVERSATION ID",...); Connections.csv doesn't.
    start = next((i for i, line in enumerate(lines) if line.lstrip('"').lower().startswith(first_column.lower())),
                 None)
    if start is None:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def parse_connections(text: str, source: str = "Connections.csv") -> list[dict]:
    rows = _rows(text, "First Name")
    if not rows and "first name" not in text.lower():
        raise ValueError(f"{source}: no 'First Name,...' header; is this LinkedIn's Connections.csv?")
    people = []
    for row in rows:
        first, last = (row.get("First Name") or "").strip(), (row.get("Last Name") or "").strip()
        if first or last:
            people.append({"name": " ".join(filter(None, (first, last))),
                           "position": (row.get("Position") or "").strip(),
                           "company": (row.get("Company") or "").strip(), "url": (row.get("URL") or "").strip()})
    return people


def ties_from_archive(files: dict[str, str]) -> dict[str, dict]:
    """{profile slug or "name:<full name>": {"messages": n, "last_message": date, "recommendation": bool,
    "endorsements": n}} from an archive's messages, recommendations and endorsements (keys are lowercase names)."""
    ties: dict[str, dict] = {}

    def tie(key: str) -> dict:
        return ties.setdefault(key, {})

    if text := files.get("messages.csv"):
        rows = _rows(text, "CONVERSATION ID")
        # The archive owner sends most of the messages in their own export.
        me = Counter(profile_key(r.get("SENDER PROFILE URL", "")) for r in rows).most_common(1)
        me = me[0][0] if me else ""
        for r in rows:
            sender = profile_key(r.get("SENDER PROFILE URL", ""))
            others = [sender] if sender != me else [profile_key(u) for u in
                                                   (r.get("RECIPIENT PROFILE URLS") or "").split(",")]
            date = (r.get("DATE") or "")[:10]
            for o in filter(None, others):
                if o == me:
                    continue
                t = tie(o)
                t["messages"] = t.get("messages", 0) + 1
                if date > t.get("last_message", ""):
                    t["last_message"] = date
    for name in ("recommendations_received.csv", "recommendations_given.csv"):
        for r in _rows(files.get(name, ""), "First Name"):
            if key := _name_key(r.get("First Name", ""), r.get("Last Name", "")):
                tie("name:" + key)["recommendation"] = True
    for r in _rows(files.get("endorsement_received_info.csv", ""), "Endorsement Date"):
        if key := profile_key(r.get("Endorser Public Url", "")):
            tie(key)["endorsements"] = tie(key).get("endorsements", 0) + 1
    return ties


def read_archive(data: bytes | Path) -> tuple[list[dict], dict[str, dict]]:
    """(people, ties) from LinkedIn's data archive (.zip)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes) else data)
    except zipfile.BadZipFile:
        raise ValueError("not a zip file; upload the archive LinkedIn emailed you, or Connections.csv") from None
    wanted = {"connections.csv", "messages.csv", "recommendations_received.csv", "recommendations_given.csv",
              "endorsement_received_info.csv"}
    files = {}
    with zf:
        for info in zf.infolist():
            base = info.filename.rsplit("/", 1)[-1].lower()
            if base in wanted and not info.is_dir():
                files[base] = zf.read(info).decode("utf-8-sig", errors="replace")
    if "connections.csv" not in files:
        raise ValueError("the archive has no Connections.csv; request the larger archive that includes "
                         "connections, or upload Connections.csv itself")
    return parse_connections(files["connections.csv"]), ties_from_archive(files)


def strength(tie: dict) -> float:
    """How well you know someone. A recommendation is written for someone you've worked with; each message is a
    conversation; an endorsement takes one click, so it counts least."""
    return 10 * bool(tie.get("recommendation")) + tie.get("messages", 0) + 0.5 * tie.get("endorsements", 0)


def why(tie: dict) -> str:
    """ "messaged 12×, last 2025-03-02; recommendation" """
    parts = []
    if n := tie.get("messages"):
        parts.append(f"messaged {n}×" + (f", last {tie['last_message']}" if tie.get("last_message") else ""))
    if tie.get("recommendation"):
        parts.append("recommendation")
    if n := tie.get("endorsements"):
        parts.append(f"endorsed you {n}×")
    return "; ".join(parts)


def clean_person(name: str = "", company: str = "", title: str = "", note: str = "", reach: str = "", url: str = "",
                 email: str = "", phone: str = "") -> dict:
    """A person to add by hand, checked and tidied: {name, company, position (the title), about (the note), reach,
    url, email, phone}. Raises ValueError, in words for the person who typed it, when something is missing or wrong."""
    got = {"name": " ".join(name.split()), "company": " ".join(company.split()), "position": " ".join(title.split()),
           "about": " ".join(note.split()), "reach": reach.strip().lower(), "url": url.strip(), "email": email.strip(),
           "phone": phone.strip()}
    if not got["name"]:
        raise ValueError("a person needs a name")
    if not company_key(got["company"]):
        raise ValueError("a person needs a company")
    if len(got["about"]) > NOTE_MAX:
        raise ValueError(f"keep the note to {NOTE_MAX} characters or fewer")
    if got["reach"] and got["reach"] not in REACH:
        raise ValueError(f"how you reach them must be one of {', '.join(REACH)}")
    if got["url"]:
        if not (slug := profile_key(got["url"])):
            raise ValueError("a LinkedIn link looks like linkedin.com/in/their-name")
        got["url"] = "https://www.linkedin.com/in/" + slug
    if got["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", got["email"]):
        raise ValueError(f"{got['email']!r} isn't an email address")
    return got


def hand_note(person: dict) -> str:
    """What is said beside someone added by hand: how you reach them, then your own words ("reach on WhatsApp; met
    at a conference")."""
    return "; ".join(filter(None, (REACH.get(person.get("reach", "")), (person.get("about") or "").strip())))


def _order(p: dict) -> tuple:
    """People marked Use first, then the strongest ties."""
    return (p.get("verdict") != "use", -p.get("strength", 0))


class Contacts:
    def __init__(self, people: list[dict], ties: dict[str, dict] | None = None, skip: list[str] | tuple = (),
                 feedback: dict[str, dict] | None = None, employer: list[str] | tuple = (),
                 added: list[dict] | tuple = ()):
        """skip: people never to suggest (a name, or a linkedin.com/in/ link), however close the tie.
        feedback: {person_key: {"verdict": "use" | "skip", "note": ...}} from the referrals page: skip is the same
        as above, use sorts a person ahead of closer ties, and the note goes with the person.
        employer: where you work now; at() lists no one there (colleagues, not referrals).
        added: the people added by hand (Store.added_people), listed with the connections: same company matching,
        same choices, a close tie (ADDED_STRENGTH) and "added by hand" among their reasons."""
        self.has_ties = bool(ties)
        self.employer = {k for e in employer if (k := company_key(e))}
        ties = ties or {}
        feedback = feedback or {}
        skip_profiles = {k for s in skip if (k := profile_key(s))}
        skip_names = {_name_key(s) for s in skip if not profile_key(s)}
        self.by_company: dict[str, list[dict]] = {}
        self.everyone: list[dict] = []
        self.hidden: dict[str, list[dict]] = {}  # the people left out, to list them where they can be put back
        for p in [*people, *({"by_hand": True, **a} for a in added)]:
            t = {**ties.get("name:" + _name_key(p["name"]), {}), **ties.get(profile_key(p.get("url", "")), {})}
            fb = feedback.get(person_key(p), {})
            in_file = _name_key(p["name"]) in skip_names or profile_key(p.get("url", "")) in skip_profiles
            by_hand = bool(p.get("by_hand"))
            p = {"email": "", "phone": "", "reach": "", "about": "", "added_at": "", **p, "by_hand": by_hand,
                 "key": person_key(p), "verdict": fb.get("verdict", ""), "from_file": in_file,
                 "strength": max(strength(t), ADDED_STRENGTH) if by_hand else strength(t),
                 "why": "; ".join(filter(None, (why(t), BY_HAND if by_hand else ""))),
                 "note": fb.get("note") or (hand_note(p) if by_hand else "")}
            self.everyone.append(p)
            if key := company_key(p.get("company", "")):
                left_out = in_file or p["verdict"] == "skip"
                (self.hidden if left_out else self.by_company).setdefault(key, []).append(p)
        for group in self.by_company.values():
            group.sort(key=_order)

    @classmethod
    def load(cls, path: Path | str, skip: list[str] | tuple = (), feedback: dict[str, dict] | None = None,
             employer: list[str] | tuple = (), added: list[dict] | tuple = ()) -> Contacts:
        """Connections.csv (with linkedin-ties.json beside it, if an archive was imported), or the archive .zip,
        and the people added by hand."""
        path = Path(path).expanduser()
        if path.suffix.lower() == ".zip":
            return cls(*read_archive(path), skip=skip, feedback=feedback, employer=employer, added=added)
        people = parse_connections(path.read_text(encoding="utf-8-sig"), str(path))
        ties_path = path.with_name(TIES_FILE)
        ties = json.loads(ties_path.read_text()) if ties_path.is_file() else None
        return cls(people, ties, skip, feedback, employer, added)

    def duplicate(self, name: str, company: str) -> dict | None:
        """Someone already listed (a connection or added by hand, even one left out) with this name at this
        company, or None."""
        key = company_key(company)
        return next((p for p in self.everyone if _name_key(p["name"]) == _name_key(name)
                     and company_key(p.get("company", "")) == key), None)

    def at(self, *names: str) -> list[dict]:
        """Connections whose current company is any of these names (the board's name, its slug, ...),
        people you actually talk to first; none at your own employer."""
        keys = {company_key(n) for n in names if n}
        if keys & self.employer:
            return []
        found = [p for k in keys if k for p in self.by_company.get(k, [])]
        return sorted(found, key=_order)

    def find(self, who: str) -> dict:
        """The connection a name, linkedin.com/in/ link or person key means. Raises ValueError when none, or
        several, are."""
        if found := [p for p in self.everyone if p["key"] == who.strip().lower()]:
            pass
        elif slug := profile_key(who):
            found = [p for p in self.everyone if profile_key(p.get("url", "")) == slug]
        else:
            found = [p for p in self.everyone if _name_key(p["name"]) == _name_key(who)]
        if not found:
            raise ValueError(f"no connection matches {who!r}")
        if len(found) > 1:
            raise ValueError(f"{len(found)} connections are called {who!r}: use a linkedin.com/in/ link")
        return found[0]

    def left_out(self, *names: str) -> list[dict]:
        """The connections at a company that are never suggested: marked Don't use, or in connections_skip
        (from_file)."""
        keys = {company_key(n) for n in names if n}
        return [p for k in keys if k for p in self.hidden.get(k, [])]


def import_archive(data: bytes, folder: Path) -> tuple[Path, int, int]:
    """Save what jobwatch needs from an archive: Connections.csv and the tie counts. The archive itself (with your
    messages) is not kept. Returns (Connections.csv path, people, people you've interacted with)."""
    people, ties = read_archive(data)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "Connections.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        for p in people:
            first, _, last = p["name"].partition(" ")
            w.writerow([first, last, p["url"], "", p["company"], p["position"], ""])
    (folder / TIES_FILE).write_text(json.dumps(ties, indent=1, sort_keys=True), encoding="utf-8")
    known = sum(1 for g in Contacts(people, ties).by_company.values() for p in g if p.get("strength"))
    return out, len(people), known


def linkedin_search(company: str) -> str:
    """People search for the company in your 2nd-degree network: who could introduce you."""
    from urllib.parse import quote

    return ("https://www.linkedin.com/search/results/people/?keywords=" + quote(company)
            + "&network=%5B%22S%22%5D")
