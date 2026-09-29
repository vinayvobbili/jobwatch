"""People you know at a company, from a LinkedIn connections export: a referral beats a cold application.

LinkedIn: Settings > Data privacy > Get a copy of your data > Connections. The file stays on your machine.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# Legal and filler words that differ between how a board and a profile name one company.
_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "pbc", "plc", "gmbh", "the",
             "technologies", "technology", "labs", "ai", "hq", "group", "holdings"}


def company_key(name: str) -> str:
    """ "Acme, Inc." and "acme" -> "acme"; "Scale AI" -> "scale". Empty when nothing is left."""
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    core = [w for w in words if w not in _SUFFIXES]
    return " ".join(core or words)


class Contacts:
    def __init__(self, people: list[dict]):
        self.by_company: dict[str, list[dict]] = {}
        for p in people:
            if key := company_key(p.get("company", "")):
                self.by_company.setdefault(key, []).append(p)

    @classmethod
    def load(cls, path: Path | str) -> Contacts:
        """Read LinkedIn's Connections.csv (it starts with a few lines of notes before the header)."""
        text = Path(path).expanduser().read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith("First Name")), None)
        if start is None:
            raise ValueError(f"{path}: no 'First Name,...' header; is this LinkedIn's Connections.csv?")
        people = []
        for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
            name = " ".join(filter(None, (row.get("First Name", "").strip(), row.get("Last Name", "").strip())))
            if name:
                people.append({"name": name, "position": (row.get("Position") or "").strip(),
                               "company": (row.get("Company") or "").strip(), "url": (row.get("URL") or "").strip()})
        return cls(people)

    def at(self, *names: str) -> list[dict]:
        """Connections whose current company is any of these names (the board's name, its slug, ...)."""
        keys = {company_key(n) for n in names if n}
        return [p for k in keys if k for p in self.by_company.get(k, [])]
