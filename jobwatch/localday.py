"""The calendar day, on this computer, of one of the store's timestamps.

The store writes every stamp in UTC (store._now), so cutting one to its first 10 characters gives the UTC day: after
7 PM Eastern that is tomorrow, and a posting found closed this evening read "closed Nov 26" on Nov 25. Show a stamp's
day through local_day instead. The page has the same helper (localDay in static/index.html)."""

from datetime import date, datetime


def local_day(stamp: str | None) -> str:
    """YYYY-MM-DD, the day on this computer of a stamp such as "2026-11-26T03:13:00+00:00" (a stamp with no zone is
    read as local already). A plain day ("2026-11-26", written from date.today()) comes back as it is, and an empty
    or unreadable value gives ""."""
    text = (stamp or "").strip()
    if not text:
        return ""
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        return datetime.fromisoformat(text).astimezone().date().isoformat()
    except ValueError:
        return ""
