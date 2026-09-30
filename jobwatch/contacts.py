"""People you know at a company, from your LinkedIn data: a referral beats a cold application.

LinkedIn: Settings > Data privacy > Get a copy of your data. Either file works:

- Connections.csv: who you're connected to, with their current company and position.
- The full archive (.zip): the same, plus how well you know each person, counted from messages you exchanged,
  recommendations, and endorsements. Only counts and dates are used. Message text is never read or kept.

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
_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "pbc", "plc", "gmbh", "the",
             "technologies", "technology", "labs", "ai", "hq", "group", "holdings"}

TIES_FILE = "linkedin-ties.json"  # derived from an archive, kept next to Connections.csv


def company_key(name: str) -> str:
    """ "Acme, Inc." and "acme" -> "acme"; "Scale AI" -> "scale". Empty when nothing is left."""
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    core = [w for w in words if w not in _SUFFIXES]
    return " ".join(core or words)


def profile_key(url: str) -> str:
    """linkedin.com/in/<slug>, however the export wrote it."""
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


def _name_key(first: str, last: str = "") -> str:
    return " ".join(f"{first} {last}".lower().split())


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


class Contacts:
    def __init__(self, people: list[dict], ties: dict[str, dict] | None = None):
        self.has_ties = bool(ties)
        ties = ties or {}
        self.by_company: dict[str, list[dict]] = {}
        for p in people:
            t = {**ties.get("name:" + _name_key(p["name"]), {}), **ties.get(profile_key(p.get("url", "")), {})}
            if t:
                p = {**p, "strength": strength(t), "why": why(t)}
            if key := company_key(p.get("company", "")):
                self.by_company.setdefault(key, []).append(p)
        for group in self.by_company.values():
            group.sort(key=lambda p: -p.get("strength", 0))

    @classmethod
    def load(cls, path: Path | str) -> Contacts:
        """Connections.csv (with linkedin-ties.json beside it, if an archive was imported), or the archive .zip."""
        path = Path(path).expanduser()
        if path.suffix.lower() == ".zip":
            return cls(*read_archive(path))
        people = parse_connections(path.read_text(encoding="utf-8-sig"), str(path))
        ties_path = path.with_name(TIES_FILE)
        ties = json.loads(ties_path.read_text()) if ties_path.is_file() else None
        return cls(people, ties)

    def at(self, *names: str) -> list[dict]:
        """Connections whose current company is any of these names (the board's name, its slug, ...),
        people you actually talk to first."""
        keys = {company_key(n) for n in names if n}
        found = [p for k in keys if k for p in self.by_company.get(k, [])]
        return sorted(found, key=lambda p: -p.get("strength", 0))


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
