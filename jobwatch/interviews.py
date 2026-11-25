"""The Interviews tab: the interviews and calls your open applications' next steps name, today's first, then the
days ahead, each with the one prep sheet to open first.

A next step is read the way the calendar feed reads it (ics.meetings): a date and a time it can be sure of, and
one card for each meeting it names (a step with two calls is on the tab twice). One
that names a meeting but no time it can read ("panel interview, the recruiter to schedule") is listed as not scheduled
yet while its follow-up day is today or ahead, so it isn't lost, once the application is past applied (before
that, "wait for a recruiter screen" is a hope, not an interview). A card links one prep sheet, the main one: the
.html files in the watchlist's prep.sheets folder whose name starts with the company's ("acme-onsite.html" for Acme)
are the candidates, and the one it links is the sheet its note or next step names ("Prep sheet: prep/acme-onsite.html":
the last labelled one, else the first named), else the newest that doesn't name another posting's number. Only a
page whose role is "sheet" can be it. A page says its role in `<meta name="jobwatch-prep-role">`: "module" (one
drill clip's page), "playlist" (the clips in order) or "rehearse" (the practice page `jobwatch rehearse` writes); a
page without the marker is a sheet, except a rehearse page by its title or name, a playlist by its name and a
"companion" page (`<meta name="prep-sheet" content="companion">`). Playlist and practice pages are reached from the
main sheet itself. The page serves that folder at an address with a secret in it, so a sheet's stylesheet, images
and drill video next to it load as they do from disk, and sandboxed: a sheet can't reach the page's token. Its web
links open in new tabs, outside the sandbox, so the sheet stays open during the call.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import ics, rounds
from .models import Job
from .store import ENDED

AHEAD = 14  # days ahead the tab lists
SHEET_TYPES = (".html", ".htm")
# What the page serves from the sheets folder: the sheets, and what a sheet shows from next to it.
FILE_TYPES = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".css": "text/css",
              ".js": "text/javascript; charset=utf-8",
              ".mp4": "video/mp4", ".webm": "video/webm", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
              ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".svg": "image/svg+xml", ".pdf": "application/pdf"}
# A sheet's own scripts (player.js: the theme pills, video keys, the Edit pill) run, but it stays in an opaque origin
# (no allow-same-origin): it can't read this page, its token or its storage. Modals are allowed for the browser's
# "leave with unsaved edits?" question. Its links may open a normal tab: a site opened from it isn't sandboxed.
SHEET_POLICY = "sandbox allow-scripts allow-modals allow-popups allow-popups-to-escape-sandbox"
_WEB_LINK = re.compile(r"""<a\b(?![^>]*\btarget\s*=)(?=[^>]*\bhref\s*=\s*["']?https?:)""", re.I)


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


ROLE_BYTES = 2048  # how much of a page is read for its role and title: the <head> is at the top
_ROLE = re.compile(r"""<meta\b[^>]*\bname=["']?jobwatch-prep-role["']?[^>]*\bcontent=["']?([a-z]+)""", re.I)
_COMPANION = re.compile(r"""<meta\b[^>]*\bname=["']?prep-sheet["']?[^>]*\bcontent=["']?companion""", re.I)
_TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
ROLES = ("sheet", "module", "playlist", "rehearse", "companion")


def sheet_info(path: Path) -> tuple[str, str]:
    """(role, title) of a page in the sheets folder, from its first ROLE_BYTES: its role is the one it says in
    `<meta name="jobwatch-prep-role">` (one of ROLES), else a rehearse page by its title or name, a playlist by its
    name, a "companion" page by its prep-sheet marker, and anything else a "sheet". The title is its <title>, else
    its file name read as words."""
    try:
        with open(path, "rb") as f:
            top = f.read(ROLE_BYTES).decode("utf-8", "replace")
    except OSError:
        top = ""
    title = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if (m := _TITLE.search(top)) else ""
    stem = Path(path).stem
    if (said := _ROLE.search(top)) and said.group(1).lower() in ROLES:
        role = said.group(1).lower()
    elif title.startswith("Rehearse:") or stem.endswith("-rehearse"):
        role = "rehearse"
    elif stem.endswith("-playlist"):
        role = "playlist"
    else:
        role = "companion" if _COMPANION.search(top) else "sheet"
    return role, title or stem.replace("-", " ")


def sheet_role(path: Path) -> str:
    return sheet_info(path)[0]


# "Prep sheet: prep/acme-onsite.html" in a note: the sheet its writer calls the main one.
_LABELLED = re.compile(r"prep sheet:?\s*(?:[^\s,;()]*/)?([^\s,;()/]+\.html?)", re.I)


def job_sheet(folder: Path | None, job: Job, rec: dict) -> str | None:
    """The one prep sheet an application's card links. The sheet its note or next step names by file name (any
    page in the folder, so a sheet named for the interviewer, not the company, works): the last one labelled
    "Prep sheet:" (a note's newest line comes last), else the first named. None named, or none of them a sheet (a
    rehearse page, a playlist, a module): the company's newest that doesn't name another posting's number (a company
    you apply to often has a sheet per opening)."""
    found = sheets(folder, job.display_company, job.company)
    text = " ".join(rec.get(k) or "" for k in ("note", "next_step"))
    # a sheet the note names is the one, whatever its name starts with ("acme-sam-screen.html" for Acme Corp)
    anywhere = sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SHEET_TYPES) \
        if folder and folder.is_dir() else []

    def is_sheet(name: str) -> bool:
        return sheet_role(folder / name) == "sheet"

    labelled = [n for n in (m.group(1) for m in _LABELLED.finditer(text)) if n in anywhere]
    named = [(m.start(), s) for s in anywhere if (m := re.search(rf"(?<![\w.-]){re.escape(s)}", text))]
    for name in [*reversed(labelled), *(s for _, s in sorted(named))]:
        if is_sheet(name):
            return name
    own = " ".join((job.id, job.title, job.url or ""))
    return next((s for s in found if all(n in own for n in _REQ.findall(Path(s).stem)) and is_sheet(s)), None)


def job_sheets(folder: Path | None, job: Job, rec: dict) -> list[str]:
    """job_sheet as a list: the card's one prep sheet, or none."""
    return [name] if (name := job_sheet(folder, job, rec)) else []


def sheet_fields(folder: Path | None, job: Job, rec: dict) -> dict:
    """What a card or the details view needs of the main prep sheet: its name, its title, and `sheets`, the same
    name as a list (the one chip's name, or none)."""
    sheet = job_sheet(folder, job, rec)
    return {"sheets": [sheet] if sheet else [], "sheet": sheet,
            "sheet_title": sheet_info(folder / sheet)[1] if sheet else None}


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


def new_tab_links(sheet: bytes) -> bytes:
    """A sheet with its web links set to open in new tabs. In-page links and a link with its own target stay."""
    return _WEB_LINK.sub('<a target="_blank" rel="noopener"', sheet.decode("utf-8", "replace")).encode()


def to_dict(i: Interview, folder: Path | None) -> dict:
    j, rec, m = i.job, i.rec, i.meeting
    return {"key": j.key, "title": j.title, "company": j.display_company, "url": j.url, "pay": j.pay(),
            "day": i.day.isoformat(), "scheduled": m is not None,
            "start": m.start.isoformat() if m else None, "end": m.end.isoformat() if m else None,
            "zoned": bool(m and m.zoned), "label": m.label if m else rounds.kind(rec.get("round")) or "Interview",
            "round": rec.get("round") or None, "round_label": rounds.label(rec.get("round")),
            **sheet_fields(folder, j, rec),
            **{k: rec.get(k) for k in ("status", "next_step", "follow_up", "note")}}


def meeting_dict(next_step: str | None, today: date | None = None, round_id: str | None = None) -> dict | None:
    """A next step's interview time for the details view, or None: the next one that hasn't ended, else the last."""
    today = today or date.today()
    found = ics.meetings(next_step, today, round_id)
    now = datetime.now(UTC)
    m = next((m for m in found if (m.end if m.zoned else m.end.astimezone()) >= now), found[-1] if found else None)
    return m and {"start": m.start.isoformat(), "end": m.end.isoformat(), "zoned": m.zoned, "label": m.label,
                  "round_label": m.round, "day": _local_day(m).isoformat()}
