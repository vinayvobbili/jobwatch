"""Follow-ups and interviews as an iCalendar (RFC 5545) feed, for a calendar app to import or subscribe to.

Each open application's follow-up day is an all-day event. When its next step names an interview or call with a
date and a time ("Panel interview Tue 3/10 10:00 AM ET", "call Wed 3/11 2:15-3:00 PM ET", an ISO datetime), that
is a timed event too; a step naming several, one clause each separated by ";" or a line break, gives one event
each. Text that can't be read with confidence (no time, two dates in one clause, a weekday that doesn't fit the
date) gives no timed event: the follow-up day is still there. jobwatch never gets access to a calendar: the
calendar app reads the file. Nothing here uses the network.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import rounds
from .models import Job
from .store import ENDED

PRODID = "-//jobwatch//follow-ups//EN"
DURATION = timedelta(hours=1)  # a timed event with no end time given

# A zone's abbreviation: an IANA zone for those that change with daylight saving, else a fixed offset in hours.
ZONES: dict[str, str | int] = {
    "ET": "America/New_York", "PT": "America/Los_Angeles", "CT": "America/Chicago", "MT": "America/Denver",
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7,
    "UTC": 0, "GMT": 0,
}
MONTHS = {m: n for n, names in enumerate(
    ("jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july", "aug august",
     "sep sept september", "oct october", "nov november", "dec december"), 1) for m in names.split()}
WEEKDAYS = {d: n for n, names in enumerate(
    ("mon monday", "tue tues tuesday", "wed weds wednesday", "thu thur thurs thursday", "fri friday",
     "sat saturday", "sun sunday")) for d in names.split()}

# What makes a next step a meeting, and which of those are calls rather than interviews.
_MEETING = re.compile(r"\b(interview|call|chat|screen|screening|onsite|on-site|loop|panel|round|meeting|"
                      r"conversation|sync|demo|presentation|talk|coffee)\b", re.I)
_CALL = re.compile(r"\b(call|chat|screen|screening|conversation|sync|talk|coffee)\b", re.I)

_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::\d{2})?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?"
                  r"(?![\d])")
_NUMERIC_DATE = re.compile(r"(?<![\d/.-])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_NAMED_DATE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})"
                         r"(?:st|nd|rd|th)?(?![\d:])(?:,?\s+(\d{4}))?\b", re.I)
_DAY_FIRST = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) +
                        r")\b\.?(?:,?\s+(\d{4}))?", re.I)
_WEEKDAY = re.compile(r"\b(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b\.?", re.I)
_CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?"
_RANGE = re.compile(rf"(?<![\d:])(\d{{1,2}})(?::(\d{{2}}))?\s*(?:([ap])\.?m\.?)?\s*(?:-|–|—|to)\s*{_CLOCK}", re.I)
_TIME = re.compile(rf"(?<![\d:/.-]){_CLOCK}", re.I)
_TIME24 = re.compile(r"(?<![\d:/.-])([01]?\d|2[0-3]):([0-5]\d)(?![\d:]|\s*[ap]\.?m)", re.I)
_ZONE = re.compile(r"\b(" + "|".join(ZONES) + r")\b", re.I)


@dataclass(frozen=True)
class Meeting:
    """A time found in a next step: `start` and `end` are UTC when `zoned`, else the same clock time for whoever
    reads it ("floating"), as the text gave no zone."""
    start: datetime
    end: datetime
    zoned: bool
    label: str  # Interview or Call
    round: str | None = None  # the round's label (rounds.py), when the application has one


def _zone(name: str) -> timezone | ZoneInfo | None:
    zone = ZONES[name.upper()]
    if isinstance(zone, int):
        return timezone(timedelta(hours=zone))
    try:
        return ZoneInfo(zone)
    except ZoneInfoNotFoundError:  # no time zone database on this computer (Windows without tzdata)
        return None


def _hour(hour: int, meridiem: str) -> int | None:
    if not 1 <= hour <= 12:
        return None
    return hour % 12 + (12 if meridiem.lower() == "p" else 0)


def _the_day(text: str, today: date) -> date | None:
    """The one calendar day the text names, else None (none, two different ones, or a weekday that doesn't fit)."""
    found: set[tuple[int, int, int | None]] = set()
    for m in _NUMERIC_DATE.finditer(text):
        mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
        found.add((mo, d, int(y) + 2000 if y and len(y) == 2 else int(y) if y else None))
    for m in _NAMED_DATE.finditer(text):
        found.add((MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    for m in _DAY_FIRST.finditer(text):
        found.add((MONTHS[m.group(2).lower()], int(m.group(1)), int(m.group(3)) if m.group(3) else None))
    if len(found) != 1:
        return None
    mo, d, y = found.pop()
    try:
        if y is not None:
            on = date(y, mo, d)
        else:  # no year: the next one that isn't long past
            on = date(today.year, mo, d)
            if on < today - timedelta(days=60):
                on = date(today.year + 1, mo, d)
    except ValueError:
        return None
    named = {WEEKDAYS[w.group(1).lower()] for w in _WEEKDAY.finditer(text)}
    if named and named != {on.weekday()}:
        return None
    return on


def _the_time(text: str) -> tuple[time, time | None] | None:
    """(start, end or None) when the text has exactly one time or time range, else None. A bare 10:00 with no
    am/pm is only read as a 24-hour time from 13:00 on."""
    if m := _RANGE.search(text):
        if len(_RANGE.findall(text)) != 1:
            return None
        h1, m1, mer1, h2, m2, mer2 = int(m.group(1)), int(m.group(2) or 0), m.group(3), int(m.group(4)), \
            int(m.group(5) or 0), m.group(6)
        end_h = _hour(h2, mer2)
        if end_h is None or not (m1 < 60 and m2 < 60):
            return None
        start_h = _hour(h1, mer1 or mer2)
        if start_h is None:
            return None
        if not mer1 and (start_h, m1) >= (end_h, m2):  # "11:30-12:30 PM": the start is before noon
            start_h = _hour(h1, "a")
        if (start_h, m1) >= (end_h, m2):
            return None
        return time(start_h, m1), time(end_h, m2)
    twelve = _TIME.findall(text)
    if twelve:
        if len(twelve) != 1 or _TIME24.search(text):
            return None
        h, mi, mer = twelve[0]
        hour = _hour(int(h), mer)
        return (time(hour, int(mi or 0)), None) if hour is not None and int(mi or 0) < 60 else None
    twenty_four = [m for m in _TIME24.finditer(text) if int(m.group(1)) >= 13]
    if len(twenty_four) == 1 and len(_TIME24.findall(text)) == 1:
        return time(int(twenty_four[0].group(1)), int(twenty_four[0].group(2))), None
    return None


def _iso_meeting(text: str, label: str, round_label: str | None) -> Meeting | None:
    found = list(_ISO.finditer(text))
    if len(found) != 1:
        return None
    y, mo, d, h, mi, off = found[0].groups()
    try:
        start = datetime(int(y), int(mo), int(d), int(h), int(mi))
    except ValueError:
        return None
    if off:
        start = start.replace(tzinfo=timezone.utc if off == "Z" else timezone(
            (1 if off[0] == "+" else -1) * timedelta(hours=int(off[1:3]), minutes=int(off[-2:]))))
    elif zone := _ZONE.search(text[found[0].end():found[0].end() + 8]):
        if (tz := _zone(zone.group(1))) is None:
            return None
        start = start.replace(tzinfo=tz)
    if start.tzinfo:
        start = start.astimezone(timezone.utc)
    return Meeting(start, start + DURATION, start.tzinfo is not None, label, round_label)


def names_meeting(next_step: str | None, round_id: str | None = None) -> bool:
    """Whether a next step is about an interview or call at all, with a time or not. An application with a
    round (rounds.py) always is; the words are read only when it has none."""
    return bool(rounds.kind(round_id) or _MEETING.search(next_step or ""))


def meeting(next_step: str | None, today: date, round_id: str | None = None) -> Meeting | None:
    """The interview or call a next step names, when it gives a date and a time confidently, else None.
    `today` fills in a missing year. See the module's docstring for what is understood. With a round
    (rounds.py) the step is a meeting whatever its words, and the round gives its label."""
    text = " ".join((next_step or "").split())
    if kind := rounds.kind(round_id):
        label, round_label = kind, rounds.label(round_id)
    elif not _MEETING.search(text):
        return None
    else:
        label = "Call" if _CALL.search(text) and not re.search(r"\binterview\b", text, re.I) else "Interview"
        round_label = None
    if _ISO.search(text):
        return _iso_meeting(text, label, round_label)
    day_, clock = _the_day(text, today), _the_time(text)
    if day_ is None or clock is None:
        return None
    zones = {z.upper() for z in _ZONE.findall(text)}
    if len(zones) > 1:
        return None
    start, end = datetime.combine(day_, clock[0]), datetime.combine(day_, clock[1]) if clock[1] else None
    zoned = bool(zones)
    if zones:
        if (tz := _zone(zones.pop())) is None:
            return None
        start = start.replace(tzinfo=tz).astimezone(timezone.utc)
        end = end.replace(tzinfo=tz).astimezone(timezone.utc) if end else None
    return Meeting(start, end or start + DURATION, zoned, label, round_label)


def meetings(next_step: str | None, today: date, round_id: str | None = None) -> list[Meeting]:
    """Every interview or call a next step names, in the order written. When the whole step reads as one meeting,
    that one; else each clause (split at ";" and line breaks) that reads as a meeting on its own, so
    "Sync Fri 10/23 9:30 AM ET; final round Sun 10/25 5:00 PM ET" is two and a clause with no time is dropped."""
    if m := meeting(next_step, today, round_id):
        return [m]
    return [m for clause in re.split(r"[;\r\n]+", next_step or "") if (m := meeting(clause, today, round_id))]


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def _fold(line: str) -> list[str]:
    """A content line cut into pieces of at most 75 octets (the continuation lines start with a space, which
    counts), never in the middle of a character."""
    pieces, current, size, room = [], "", 0, 75
    for ch in line:
        n = len(ch.encode())
        if size + n > room:
            pieces.append(current)
            current, size, room = " ", 1, 75
        current += ch
        size += n
    return [*pieces, current]


def _uid(key: str, kind: str) -> str:
    return f"{hashlib.sha1(key.encode()).hexdigest()}-{kind}@jobwatch"


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event(uid: str, now: datetime, summary: str, description: str, url: str, when: dict[str, str],
           remind: int = 0) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_stamp(now)}", *(f"{k}{v}" for k, v in when.items()),
             f"SUMMARY:{_escape(summary)}", f"DESCRIPTION:{_escape(description)}"]
    if url:
        lines.append(f"URL:{url}")
    if remind:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(summary)}", f"TRIGGER:-PT{remind}M",
                  "END:VALARM"]
    return [*lines, "END:VEVENT"]


def calendar(rows: list[tuple[Job, dict]], today: date | None = None, now: datetime | None = None,
             remind: int = 0) -> str:
    """The feed for these applications (store.applications()): CRLF lines, ready to write to a .ics file.
    Rejected and withdrawn ones are left out. remind: minutes before a timed event for a reminder (0: none; the
    all-day follow-ups never have one). An event's UID is its application and kind (meeting, then meeting-2, ...),
    so importing the feed again updates the events instead of adding more."""
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:jobwatch follow-ups", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for job, rec in rows:
        if rec["status"] in ENDED:
            continue
        name, step = f"{job.display_company} — {job.title}", (rec.get("next_step") or "").strip()
        about = "\n".join(filter(None, [f"Next step: {step}" if step else "", f"Posting: {job.url}" if job.url else "",
                                         f"jobwatch key: {job.key}"]))
        if rec.get("follow_up"):
            on = date.fromisoformat(rec["follow_up"])
            lines += _event(_uid(job.key, "followup"), now, f"Follow up: {name}", about, job.url,
                            {"DTSTART;VALUE=DATE:": on.strftime("%Y%m%d"),
                             "DTEND;VALUE=DATE:": (on + timedelta(days=1)).strftime("%Y%m%d")})
        for n, m in enumerate(meetings(step, today, rec.get("round")), 1):
            fmt = "%Y%m%dT%H%M%S" + ("Z" if m.zoned else "")
            kind = "meeting" if n == 1 else f"meeting-{n}"  # the first keeps the UID it always had
            lines += _event(_uid(job.key, kind), now, f"{m.round or m.label}: {name}", about, job.url,
                            {"DTSTART:": m.start.strftime(fmt), "DTEND:": m.end.strftime(fmt)}, remind)
    lines.append("END:VCALENDAR")
    return "".join(piece + "\r\n" for line in lines for piece in _fold(line))
