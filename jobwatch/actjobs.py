"""Which jobs an Activity row is about, so the page can link each row to its job's card.

New rows carry their jobs' keys (Store.log's `jobs`). Rows written before that stored no keys: `backfill` reads the
"Company: Title" the row's line and detail lines name and keeps a job only when exactly one job in the store has
that company and title (the same role posted in two places is ambiguous: no link beats a wrong one). A prep sheet's
row is about the application the sheet belongs to: `sheet_jobs`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import Job

KEPT = 100  # jobs one row keeps
LOOKED = 25  # lines of one row read for names (a row names at most this many jobs: watch.ACTIVITY_LINES)
NAMED = ("score", "pay", "boards", "mail")  # the kinds whose lines name jobs
_LEAD = re.compile(r"^(?:Scored\s+)?(?:\d+/100\s+)?(?:(?:New|Failed|Look at):\s+)?")
_PAREN = re.compile(r"\s+\(")  # where "Optum: Senior Engineer (claude-sonnet-5-5)" may drop its "(model)"
_SHEET = re.compile(r"[\w.-]+\.html?\b", re.I)
APPLIED = ("queued", "applied", "screening", "interviewing", "offer", "rejected", "withdrawn", "closed")
Name = tuple[str, str]


_REQ = re.compile(r"(?<!\d)\d{5,}(?!\d)")  # a req number in a sheet's name, as interviews.py reads it


def _slug(name: str) -> str:  # a sheet's name starts with its company's, as interviews.sheets reads it
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def name_candidates(line: str) -> Iterator[Name]:
    """The (company, title) a line may name, as read: "88/100 Optum: Senior AI/ML Engineer (model)" is Optum and the
    title; a company or title with ": " in it is tried at each split, and a trailing ": reason" or "(model)" dropped."""
    s = _LEAD.sub("", line.strip(), count=1)
    # a trailing "(model)", which may hold a "(fallback)", dropped from the last "(" that makes a name
    variants = [s, *(s[:m.start()] for m in reversed(list(_PAREN.finditer(s))) if s.endswith(")"))]
    for v in variants:
        parts = v.split(": ")
        for i in range(1, len(parts)):
            for j in range(len(parts), i, -1):
                yield _norm(": ".join(parts[:i])), _norm(": ".join(parts[i:j]))


def lines_of(kind: str, text: str, detail: Iterable[str]) -> list[str]:
    return [text, *list(detail)[:LOOKED]] if kind in NAMED else []


def scan(db: sqlite3.Connection, wanted: set[Name]) -> dict[Name, list[str]]:
    """{(company, title): the keys of the jobs with them}, for these names, in one pass over the jobs."""
    found: dict[Name, list[str]] = {}
    if not wanted:
        return found
    for r in db.execute("SELECT key, company, json_extract(data, '$.company_name') AS name, "
                        "json_extract(data, '$.title') AS title FROM jobs"):
        k = (_norm(r["name"] or r["company"]), _norm(r["title"]))
        if k in wanted:
            found.setdefault(k, []).append(r["key"])
    return found


def keys_named(found: dict[Name, list[str]], lines: Iterable[str]) -> list[str]:
    """The jobs these lines name, one each, only where a name matches exactly one job."""
    keys: list[str] = []
    for line in lines:
        for name in name_candidates(line):
            if len(found.get(name, ())) == 1:
                if found[name][0] not in keys:
                    keys.append(found[name][0])
                break
    return keys


def sheet_jobs(rows: Iterable[tuple], name: str) -> list[str]:
    """The key of the application (or queued job) a prep sheet's file belongs to, [] when it isn't known: the one
    whose note or next step names the file, else the one at the company the file name starts with ("initech-" or
    "initech-40125-dana.html") that a req number in the name doesn't rule out, the open one when still several."""
    rows = list(rows)
    name = Path(name).name
    named = [j for j, rec in rows if name in " ".join(rec.get(k) or "" for k in ("note", "next_step"))]
    if len(named) == 1:
        return [named[0].key]
    stem = Path(name).stem.lower()
    at = [(j, rec) for j, rec in rows
          if any(s and (stem == s or stem.startswith(s + "-")) for s in (_slug(j.display_company), _slug(j.company)))
          and all(n in " ".join((j.id, j.title, j.url or "")) for n in _REQ.findall(stem))]
    if len(at) > 1:
        at = [(j, rec) for j, rec in at if rec.get("status") in ("applied", "screening", "interviewing")] or at
    return [at[0][0].key] if len(at) == 1 else []


_KEY = re.compile(r"(?<![\w:.-])[a-z][a-z0-9_]*:[\w.-]+:[\w.-]+(?![\w:.-])")


def line_keys(text: str) -> list[str]:
    """The job keys (source:board:id) a line of another program's log names, to be looked up in the store."""
    return list(dict.fromkeys(m.group(0) for m in _KEY.finditer(text)))[:LOOKED]


def sheets_in(text: str, detail: Iterable[str] = ()) -> list[str]:
    return list(dict.fromkeys(m.group(0) for line in (text, *detail) for m in _SHEET.finditer(line)))


def backfill(db: sqlite3.Connection) -> int:
    """Give the rows written before they kept keys the jobs they name (see the module's docstring). Returns how many
    rows got one or more."""
    rows = db.execute("SELECT rowid, kind, text, detail FROM activity WHERE job_keys='[]'").fetchall()
    lines = {r["rowid"]: lines_of(r["kind"], r["text"], json.loads(r["detail"])) for r in rows}
    found = scan(db, {n for ls in lines.values() for line in ls for n in name_candidates(line)})
    apps = []
    if any(r["kind"] == "prep" for r in rows):
        apps = [(Job.from_dict(json.loads(a["data"])), {k: a[k] for k in ("status", "note", "next_step")})
                for a in db.execute("SELECT data, status, note, next_step FROM jobs WHERE status IN "
                                    f"({','.join('?' * len(APPLIED))})", APPLIED)]
    done = 0
    with db:
        for r in rows:
            keys = ([k for s in sheets_in(r["text"]) for k in sheet_jobs(apps, s)] if r["kind"] == "prep"
                    else keys_named(found, lines[r["rowid"]]))
            if keys:
                db.execute("UPDATE activity SET job_keys=? WHERE rowid=?",
                           (json.dumps(list(dict.fromkeys(keys))), r["rowid"]))
                done += 1
    return done
