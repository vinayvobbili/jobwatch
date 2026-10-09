"""Plain text from job-board HTML, pay ranges from free text, and where a location is."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "section", "article"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Readable text: paragraphs on their own lines, list items as "- item".

    Greenhouse returns its HTML entity-escaped ("&lt;p&gt;"), so escaped markup is unescaped first."""
    if not markup:
        return ""
    if "&lt;" in markup:
        markup = html.unescape(markup)
    parser = _Text()
    parser.feed(markup)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    text = "\n".join(line for line in lines if line and line != "-")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_NUMBER = r"(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d+)?)"  # 180,000 or 180,000.00 or 180 (with K)
_AMOUNT = r"\$\s?" + _NUMBER + r"\s*([kK])?"
# "USD $140,400.00 - USD $372,300.00" as well as "$180K - $220K"
_RANGE = re.compile(_AMOUNT + r"\s*(?:USD)?\s*(?:-|–|—|to)\s*(?:USD\s*)?\$?\s?" + _NUMBER + r"\s*([kK])?")
_NOT_ANNUAL = re.compile(r"\s*(?:USD\s*)?(?:/|per\s+|an?\s+)(hour|hr|month|mo|week|wk|day)\b", re.I)
# "$75 an hour", "$70/hr": one amount, an hourly wage
_HOURLY = re.compile(_AMOUNT + r"(?=\s*(?:USD\s*)?(?:/|per\s+|an?\s+)(?:hour|hr)\b)", re.I)
# "167,000 - 230,000 USD per year" or "88,000 to 136,900.00 USD": no dollar sign, the currency after (a CAD
# range next to it is skipped)
_USD_AFTER = re.compile(r"(?<![\d,.$])(\d{2,3},\d{3})(?:\.\d{2})?\s*(?:-|–|—|to)\s*(\d{2,3},\d{3})(?:\.\d{2})?\s*USD\b")
# Paid hours, days, weeks and months in a year: a rate is compared and shown as the yearly pay it comes to.
PER_YEAR = {"hour": 2080, "hr": 2080, "day": 260, "week": 52, "wk": 52, "month": 12, "mo": 12}
_LOWEST = 20_000  # less a year than any salary: a bonus, a stipend or a typo


def _dollars(number: str, k: str | None) -> int:
    value = float(number.replace(",", ""))
    return int(value * 1000) if k else int(value)


def annual(amount: float, per: str) -> int:
    """A rate as the yearly pay it comes to: per is hour, day, week or month (or "year")."""
    return round(amount * PER_YEAR.get(per.lower(), 1))


def pay_period(interval: str) -> str | None:
    """A board's pay interval as year, month, week, day or hour: Lever's "per-hour-wage", Ashby's "1 HOUR",
    schema.org's "HOUR". None when it's none of them."""
    words = set(re.findall(r"[a-z]+", str(interval or "").lower()))
    return next((p for p in ("year", "month", "week", "day", "hour") if p in words), None)


def parse_salary(text: str) -> tuple[int, int] | None:
    """The yearly pay range in the text, e.g. "$180,000 — $220,000" or "$180K - $220K".

    A yearly range comes first; without one, an hourly wage ("$75 - $80/hr", "$70 an hour") is turned into
    the yearly pay it comes to (2,080 hours a year). Amounts per day, week or month are skipped: in free text
    they're as often a stipend or a budget ("$15k/month for compute") as pay. So are amounts too small to be
    a yearly salary."""
    text, hourly = text or "", None
    for m in _RANGE.finditer(text):
        low, high = _dollars(m.group(1), m.group(2)), _dollars(m.group(3), m.group(4) or m.group(2))
        if high < low:
            continue
        if per := _NOT_ANNUAL.match(text, m.end()):
            if PER_YEAR[per.group(1).lower()] == PER_YEAR["hour"]:
                hourly = hourly or (annual(low, "hour"), annual(high, "hour"))
        elif low >= _LOWEST:
            return low, high
    for m in _USD_AFTER.finditer(text):
        low, high = _dollars(m.group(1), None), _dollars(m.group(2), None)
        if not (_NOT_ANNUAL.match(text, m.end()) or high < low):
            return low, high
    if not hourly and (m := _HOURLY.search(text)):
        hourly = (annual(_dollars(m.group(1), m.group(2)), "hour"),) * 2
    return hourly if hourly and hourly[0] >= _LOWEST else None


STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_US_NAMES = re.compile(r"\bunited states\b|\bnorth america\b|\bamericas\b|\b(?:" + "|".join(STATES.values()) + r")\b",
                       re.I)
# Case-sensitive: "us", "or", "in" and "me" are also words.
_US_CODES = re.compile(r"\bU\.S\.(?:A\.)?|\bUSA?\b|,\s*(?:" + "|".join(STATES) + r")\b")
_REMOTE_WORDS = re.compile(r"\b(?:remote|friendly|fully|first|only|anywhere|hybrid|or|and|work|from|at|home?)\b|[^\w]+",
                           re.I)
# Workday boards say "Work At Home-Texas" and "TX - Work from home" (sometimes cut short: "Work from hom").
_REMOTE = re.compile(r"remote|anywhere|work[\s-]+(?:from|at)[\s-]+hom|telecommut", re.I)


def in_us(location: str) -> bool:
    """True if a location names the US, a US state, or a "City, ST" state code."""
    return bool(_US_NAMES.search(location) or _US_CODES.search(location))


# The whole country, as opposed to a state or city in it.
_US_WIDE = re.compile(r"\bunited states(?: of america)?\b|\bnorth america\b|\bamericas\b|\bnationwide\b", re.I)
_US_WIDE_CODES = re.compile(r"\bU\.S\.(?:A\.)?|\bUSA?\b")
_FILLER = re.compile(r"\b(?:in|within|the|based|travel|required|occasional)\b", re.I)


def names_a_region(location: str) -> bool:
    """True for a remote place that names somewhere inside a country: "Remote - Washington D.C.", "Remote, CA"
    (remote only for people who live there), not "Remote - US" or "Remote in the US (Travel Required)"."""
    rest = _FILLER.sub("", _US_WIDE_CODES.sub("", _US_WIDE.sub("", location)))
    return bool(_REMOTE_WORDS.sub("", rest).strip())


def remote_us_wide(location: str) -> bool:
    """Remote anywhere in the US: "Remote - US", or one choice in a list ("Seattle, Chicago, US-Remote")."""
    return any(is_remote(p) and in_us(p) and not names_a_region(p) for p in [location, *location.split(",")])


def bare_remote(location: str) -> bool:
    """A "Remote" that names no place, alone or as one choice in a list of cities ("SF, NY, Remote")."""
    pieces = location.split(",")
    return names_no_place(location) or (len(pieces) >= 3 and any(names_no_place(p) for p in pieces))


def is_remote(location: str) -> bool:
    return bool(_REMOTE.search(location))


def names_no_place(location: str) -> bool:
    """True for a bare "Remote" / "Remote-Friendly" with no country or city after it."""
    return not _REMOTE_WORDS.sub("", location).strip()


def split_locations(*raw: str) -> list[str]:
    """ "London, UK; Remote, US | Austin, TX" -> one entry per place, order kept, duplicates dropped."""
    out: list[str] = []
    for text in raw:
        for part in re.split(r"[;|]", text or ""):
            part = " ".join(part.split())
            if part and part not in out:
                out.append(part)
    return out
