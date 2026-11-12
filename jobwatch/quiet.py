"""Applications that have gone quiet: no stage change or note for a while. For each, whether its posting is
still open and what to do next. A suggestion only: nothing here changes an application."""

from __future__ import annotations

import re
from datetime import date, datetime

from .config import Quiet
from .contacts import Contacts
from .models import Job
from .store import ENDED, STAGES

SNOOZED = "Snoozed"  # a note line starting with this is a snooze (see Store.snooze), not news
_LINE = re.compile(r"(\d{4}-\d{2}-\d{2}): (.*?)(?=\s\d{4}-\d{2}-\d{2}: |$)", re.S)
_SNOOZE_UNTIL = re.compile(r"follow up (\d{4}-\d{2}-\d{2})")
NUDGE = "A short check-in to the recruiter or a contact."


def _day(text: str | None) -> date | None:
    """The local day of a date or a timestamp: a status change stored in UTC at 9 PM Eastern is still today here,
    not tomorrow, as date.today() counts."""
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return when.astimezone().date() if when.tzinfo and len(text) > 10 else when.date()


def last_news(rec: dict) -> date | None:
    """The day of the last news on an application: its latest note line (a snooze isn't news), or its stage
    change; one still at applied counts from the day applied, which may be before it was added here."""
    noted = [_day(d) for d, text in _LINE.findall(rec.get("note") or "") if not text.startswith(SNOOZED)]
    stage = _day(rec.get("applied_at")) if rec["status"] == "applied" else None
    return max((d for d in [*noted, stage or _day(rec.get("status_at")) or _day(rec.get("first_seen"))] if d),
               default=None)


def snoozed_until(rec: dict, today: date | None = None) -> str | None:
    """The day an open application's snooze ends, or None when it isn't snoozed: its latest note line is a snooze
    (Store.snooze), its follow-up day is still the one that line set (changing it by hand ends the snooze) and
    that day hasn't come. Snoozed applications drop out of "gone quiet" until then."""
    if rec["status"] not in STAGES or rec["status"] in ENDED or not rec.get("follow_up"):
        return None
    lines = _LINE.findall(rec.get("note") or "")
    if not lines or not lines[-1][1].startswith(SNOOZED):
        return None
    m = _SNOOZE_UNTIL.search(lines[-1][1])
    until = rec["follow_up"]
    return until if m and m.group(1) == until and until > (today or date.today()).isoformat() else None


def assess(job: Job, rec: dict, quiet: Quiet, today: date | None = None,
           known: Contacts | None = None) -> dict | None:
    """None for an application that isn't quiet. Else: days (since the last news), since (that day),
    posting_open, long (quiet longer than `quiet.long`), move ("nudge", or "close" when the posting is gone or
    it's long quiet), advice (a sentence), and contacts (people you know there, when asked for a nudge)."""
    stage = rec["status"]
    wait = getattr(quiet, stage, 0) if stage in STAGES and stage not in ENDED else 0
    if not wait or snoozed_until(rec, today) or not (since := last_news(rec)):
        return None
    days = ((today or date.today()) - since).days
    if days < wait:
        return None
    is_open, long = not rec.get("closed"), bool(quiet.long) and days >= quiet.long
    close = not is_open or long
    why = "its posting is gone" if not is_open else f"nothing for {days} days"
    return {"days": days, "since": since.isoformat(), "posting_open": is_open, "long": long,
            "move": "close" if close else "nudge",
            "advice": f"Likely closed ({why}): mark it rejected or withdrawn." if close else NUDGE,
            "contacts": [] if close or not known else known.at(job.display_company, job.company)}


def find(rows: list[tuple[Job, dict]], quiet: Quiet, today: date | None = None,
         known: Contacts | None = None) -> dict[str, dict]:
    """{key: assess(...)} for the applications that have gone quiet."""
    found = {j.key: assess(j, rec, quiet, today, known) for j, rec in rows}
    return {k: v for k, v in found.items() if v}


def order(rows: list[tuple[Job, dict]], found: dict[str, dict],
          today: date | None = None) -> list[tuple[Job, dict]]:
    """Applications as given (see Store.applications), but the snoozed ones and the open ones that are long quiet
    go below the fresher ones, so a due list isn't flooded by follow-ups nobody answered; ended ones stay last."""
    return sorted(rows, key=lambda r: (r[1]["status"] in ENDED, bool(snoozed_until(r[1], today)),
                                       bool(found.get(r[0].key, {}).get("long"))))
