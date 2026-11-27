"""The interview rounds an application's next step can be: id -> (label shown, kind). A round that is set says the
next step is a meeting and what sort (Call or Interview), instead of the words in its text (ics.py reads those
for steps with no round). The time still comes from the next step's text, and so does the length when the step
states one ("15-minute intro call"); an interview can also carry its length in minutes (`mark --length 15m`)."""

from __future__ import annotations

import re

DEFAULT_LENGTH = 60  # minutes a timed meeting lasts when nothing says (no round has its own)
MAX_LENGTH = 12 * 60

ROUNDS = {
    "recruiter_screen": ("Recruiter screen", "Call"),
    "hiring_manager": ("Hiring manager", "Interview"),
    "technical": ("Tech interview", "Interview"),
    "system_design": ("System design", "Interview"),
    "panel": ("Panel / onsite loop", "Interview"),
    "executive": ("VP / exec round", "Interview"),
    "hr": ("HR round", "Interview"),
    "informal": ("Informal chat", "Call"),
    "offer_call": ("Offer call", "Call"),
}


def label(round_id: str | None) -> str | None:
    """The round's label, or None for no round (or one this version doesn't know)."""
    return ROUNDS[round_id][0] if round_id in ROUNDS else None


def kind(round_id: str | None) -> str | None:
    """Call or Interview, or None for no round."""
    return ROUNDS[round_id][1] if round_id in ROUNDS else None


def check(round_id: str) -> str:
    """The id as stored: "" for none, else one of ROUNDS (ValueError otherwise)."""
    round_id = round_id.strip()
    if round_id and round_id not in ROUNDS:
        raise ValueError(f"round must be one of {', '.join(ROUNDS)}")
    return round_id


# A length written out in a next step: "15-minute", "15 min", "30 minutes", "1 hour", "1.5 hrs". The unit has to be
# a whole word: a bare "h" or "m" next to a number is too easily something else.
_STATED = re.compile(r"(?<![\d:/.-])(\d+(?:\.\d+)?)[\s-]*(hours?|hrs?|minutes?|mins?)\b", re.I)
# What the length option takes: "15m", "45 min", "1h", "1.5 hours", "1h30m", "90" (minutes).
_GIVEN = re.compile(r"(?:(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h))?\s*(?:(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)?)?", re.I)


def _minutes(hours: str | None, minutes: str | None) -> int | None:
    total = round(float(hours or 0) * 60 + float(minutes or 0))
    return total if 1 <= total <= MAX_LENGTH else None


def stated_length(text: str | None) -> int | None:
    """The minutes a next step says the meeting lasts ("15-minute intro call": 15), or None when it says none or
    says two different ones."""
    found = {_minutes(n, None) if u.lower().startswith("h") else _minutes(None, n)
             for n, u in _STATED.findall(text or "")}
    return found.pop() if len(found) == 1 else None


def check_length(value: str | int) -> str:
    """The length as stored: "" for none (clears it), else whole minutes as text ("15m", "1h30m", "45 min", "90"
    and 45 are accepted; ValueError otherwise, or under a minute or over 12 hours)."""
    text = str(value).strip()
    if not text:
        return ""
    m = _GIVEN.fullmatch(text)
    if not m or not (m.group(1) or m.group(2)) or (minutes := _minutes(m.group(1), m.group(2))) is None:
        raise ValueError("length must be between 1 minute and 12 hours, e.g. 15m, 45 min, 1h, 1h30m")
    return str(minutes)


def length_of(rec: dict) -> int | None:
    """The length in minutes an application's record carries, or None when it has none."""
    try:
        return int(rec.get("length")) or None
    except (TypeError, ValueError):
        return None
