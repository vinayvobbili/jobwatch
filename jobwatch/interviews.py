"""The Interviews tab: the interviews and calls your open applications' next steps name, today's first, then the
days ahead, each with the prep sheets you wrote for that company.

A next step is read the way the calendar feed reads it (ics.meetings): a date and a time it can be sure of, and
one card for each meeting it names (a step with two calls is on the tab twice). One
that names a meeting but no time it can read ("panel interview, the recruiter to schedule") is listed as not scheduled
yet while its follow-up day is today or ahead, so it isn't lost, once the application is past applied (before
that, "wait for a recruiter screen" is a hope, not an interview). Prep sheets are the .html files in the
watchlist's prep.sheets folder whose name starts with the company's ("acme-onsite.html" for Acme), narrowed to
one application's: the ones its note or next step names, else all but those naming another posting's number. The page
serves that folder at an address with a secret in it, so a sheet's stylesheet, images and drill video next to
it load as they do from disk, and sandboxed: a sheet can't run scripts or reach the page's token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import ics, rounds
from .models import Job
from .store import ENDED

AHEAD = 14  # days ahead the tab lists
SHEET_TYPES = (".html", ".htm")
# What the page serves from the sheets folder: the sheets, and what a sheet shows from next to it.
FILE_TYPES = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".css": "text/css",
              ".mp4": "video/mp4", ".webm": "video/webm", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
              ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".svg": "image/svg+xml", ".pdf": "application/pdf"}


@dataclass(frozen=True)
class Interview:
    job: Job
    rec: dict
    meeting: ics.Meeting | None  # None: the next step names a meeting with no time that could be read
    day: date                    # the day it's on, on this computer's clock (the follow-up day when no time)


def _local_day(m: ics.Meeting) -> date:
    return m.start.astimezone().date() if m.zoned else m.start.date()


def upcoming(rows: list[tuple[Job, dict]], today: date | None = None, ahead: int = AHEAD) -> list[Interview]:
    """The interviews and calls open applications' next steps name, from today to `ahead` days on, soonest first
    (an application naming two is listed twice), then those not scheduled yet (by follow-up day)."""
    today = today or date.today()
    last = today + timedelta(days=ahead)
    timed, untimed = [], []
    for job, rec in rows:
        if rec.get("status") in ENDED:
            continue
        step, round_id = rec.get("next_step"), rec.get("round")
        if found := ics.meetings(step, today, round_id):
            timed += [Interview(job, rec, m, on) for m in found if today <= (on := _local_day(m)) <= last]
        elif rec.get("status") != "applied" and ics.names_meeting(step, round_id) and (follow := rec.get("follow_up")):
            if today <= (on := date.fromisoformat(follow)) <= last:
                untimed.append(Interview(job, rec, None, on))
    timed.sort(key=lambda i: i.meeting.start.astimezone())  # a floating time is read as this computer's
    untimed.sort(key=lambda i: i.day)
    return timed + untimed


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def sheets(folder: Path | None, *names: str) -> list[str]:
    """The prep sheets in `folder` for a company known by any of `names`, newest first."""
    if not folder or not folder.is_dir():
        return []
    slugs = {s for s in map(_slug, names) if s}
    found = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SHEET_TYPES
             and any(p.stem.lower() == s or p.stem.lower().startswith(s + "-") for s in slugs)]
    return [p.name for p in sorted(found, key=lambda p: (-p.stat().st_mtime, p.name))]


_REQ = re.compile(r"(?<!\d)\d{5,}(?!\d)")  # a req or posting number in a sheet's name ("initech-40125-dana")


def job_sheets(folder: Path | None, job: Job, rec: dict) -> list[str]:
    """One application's prep sheets among its company's: those its note or next step names by file name, if any;
    else the company's sheets less those naming another posting's number (a company you apply to often has a
    sheet per opening)."""
    found = sheets(folder, job.display_company, job.company)
    text = " ".join(rec.get(k) or "" for k in ("note", "next_step"))
    if named := [s for s in found if s in text]:
        return named
    own = " ".join((job.id, job.title, job.url or ""))
    return [s for s in found if all(n in own for n in _REQ.findall(Path(s).stem))]


def sheet_file(folder: Path | None, name: str) -> tuple[Path, str]:
    """(path, content type) of a file the page serves from the sheets folder: one directly in it (not in a
    folder inside it, nor one it links to elsewhere), of a type in FILE_TYPES."""
    if not folder or not folder.is_dir():
        raise FileNotFoundError("no prep sheets folder is set (prep.sheets in the watchlist)")
    path = (folder / name).resolve()
    ctype = FILE_TYPES.get(path.suffix.lower())
    if Path(name).name != name or path.parent != folder.resolve() or not ctype or not path.is_file():
        raise FileNotFoundError(f"no prep sheet file named {name!r}")
    return path, ctype


def to_dict(i: Interview, folder: Path | None) -> dict:
    j, rec, m = i.job, i.rec, i.meeting
    return {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
            "day": i.day.isoformat(), "scheduled": m is not None,
            "start": m.start.isoformat() if m else None, "end": m.end.isoformat() if m else None,
            "zoned": bool(m and m.zoned), "label": m.label if m else rounds.kind(rec.get("round")) or "Interview",
            "round": rec.get("round") or None, "round_label": rounds.label(rec.get("round")),
            "sheets": job_sheets(folder, j, rec),
            **{k: rec.get(k) for k in ("status", "next_step", "follow_up", "note")}}


def meeting_dict(next_step: str | None, today: date | None = None, round_id: str | None = None) -> dict | None:
    """A next step's interview time for the details view, or None: the next one that hasn't ended, else the last."""
    today = today or date.today()
    found = ics.meetings(next_step, today, round_id)
    now = datetime.now(timezone.utc)
    m = next((m for m in found if (m.end if m.zoned else m.end.astimezone()) >= now), found[-1] if found else None)
    return m and {"start": m.start.isoformat(), "end": m.end.isoformat(), "zoned": m.zoned, "label": m.label,
                  "round_label": m.round, "day": _local_day(m).isoformat()}
