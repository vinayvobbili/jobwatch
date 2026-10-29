"""The interview rounds an application's next step can be: id -> (label shown, kind). A round that is set says the
next step is a meeting and what sort (Call or Interview), instead of the words in its text (ics.py reads those
for steps with no round). The time still comes from the next step's text."""

from __future__ import annotations

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
