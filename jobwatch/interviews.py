"""The Interviews tab: the interviews and calls your open applications' next steps name, today's first, then the
days ahead, each with the prep sheets you wrote for that company.

A next step is read the way the calendar feed reads it (ics.meeting): a date and a time it can be sure of. One
that names a meeting but no time it can read ("panel interview, the recruiter to schedule") is listed as not scheduled
yet while its follow-up day is today or ahead, so it isn't lost, once the application is past applied (before
that, "wait for a recruiter screen" is a hope, not an interview). Prep sheets are the .html files in the
watchlist's prep.sheets folder whose name starts with the company's ("acme-onsite.html" for Acme); the page
opens one with its scripts turned off, since it runs next to the page's token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import ics
from .models import Job
from .store import ENDED

AHEAD = 14  # days ahead the tab lists
SHEET_TYPES = (".html", ".htm")
_STYLESHEET = re.compile(r"""<link\b[^>]*\brel=["']?stylesheet["']?[^>]*>""", re.I)
_HREF = re.compile(r"""\bhref=["']?([^"'\s>]+)""", re.I)
# What a sheet opened from the page may do: show itself and its own styles and images, never run a script.
_NO_SCRIPTS = ('<meta http-equiv="Content-Security-Policy" content="script-src \'none\'; object-src \'none\'; '
               'base-uri \'none\'">')


@dataclass(frozen=True)
class Interview:
    job: Job
    rec: dict
    meeting: ics.Meeting | None  # None: the next step names a meeting with no time that could be read
    day: date                    # the day it's on, on this computer's clock (the follow-up day when no time)


def _local_day(m: ics.Meeting) -> date:
    return m.start.astimezone().date() if m.zoned else m.start.date()


def upcoming(rows: list[tuple[Job, dict]], today: date | None = None, ahead: int = AHEAD) -> list[Interview]:
    """The open applications whose next step is an interview or call from today to `ahead` days on, soonest
    first, then those not scheduled yet (by follow-up day)."""
    today = today or date.today()
    last = today + timedelta(days=ahead)
    timed, untimed = [], []
    for job, rec in rows:
        if rec.get("status") in ENDED:
            continue
        step = rec.get("next_step")
        if m := ics.meeting(step, today):
            if today <= (on := _local_day(m)) <= last:
                timed.append(Interview(job, rec, m, on))
        elif rec.get("status") != "applied" and ics.names_meeting(step) and (follow := rec.get("follow_up")):
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


def sheet(folder: Path | None, name: str) -> str:
    """One prep sheet's page, ready to open on its own: stylesheets next to it written in, scripts turned off.
    Only a file directly in `folder` is read."""
    if not folder or not folder.is_dir():
        raise FileNotFoundError("no prep sheets folder is set (prep.sheets in the watchlist)")
    path = (folder / name).resolve()
    if (Path(name).name != name or path.parent != folder.resolve() or path.suffix.lower() not in SHEET_TYPES
            or not path.is_file()):
        raise FileNotFoundError(f"no prep sheet named {name!r}")
    text = path.read_text(encoding="utf-8", errors="replace")

    def inline(m: re.Match) -> str:
        href = _HREF.search(m.group(0))
        css = folder / href.group(1) if href and Path(href.group(1)).name == href.group(1) else None
        if css and css.suffix.lower() == ".css" and css.is_file():
            return f"<style>\n{css.read_text(encoding='utf-8', errors='replace')}\n</style>"
        return m.group(0)
    text = _STYLESHEET.sub(inline, text)
    head = re.search(r"<head[^>]*>", text, re.I)
    return text[:head.end()] + _NO_SCRIPTS + text[head.end():] if head else _NO_SCRIPTS + text


def to_dict(i: Interview, folder: Path | None) -> dict:
    j, rec, m = i.job, i.rec, i.meeting
    return {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
            "day": i.day.isoformat(), "scheduled": m is not None,
            "start": m.start.isoformat() if m else None, "end": m.end.isoformat() if m else None,
            "zoned": bool(m and m.zoned), "label": m.label if m else "Interview",
            "sheets": sheets(folder, j.display_company, j.company),
            **{k: rec.get(k) for k in ("status", "next_step", "follow_up", "note")}}


def meeting_dict(next_step: str | None, today: date | None = None) -> dict | None:
    """A next step's interview time for the details view, or None."""
    m = ics.meeting(next_step, today or date.today())
    return m and {"start": m.start.isoformat(), "end": m.end.isoformat(), "zoned": m.zoned, "label": m.label,
                  "day": _local_day(m).isoformat()}
