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


_AMOUNT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?"
_RANGE = re.compile(_AMOUNT + r"\s*(?:USD)?\s*(?:-|–|—|to)\s*\$?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?")
_NOT_ANNUAL = re.compile(r"\s*(?:USD\s*)?(?:/|per\s+|an?\s+)(?:hour|hr|month|mo|week|day)\b", re.I)


def _dollars(number: str, k: str | None) -> int:
    value = float(number.replace(",", ""))
    return int(value * 1000) if k else int(value)


def parse_salary(text: str) -> tuple[int, int] | None:
    """The first annual pay range in the text, e.g. "$180,000 — $220,000" or "$180K - $220K".

    Ranges quoted per hour or month, and amounts too small to be a yearly salary, are skipped."""
    for m in _RANGE.finditer(text or ""):
        low, high = _dollars(m.group(1), m.group(2)), _dollars(m.group(3), m.group(4) or m.group(2))
        if _NOT_ANNUAL.match(text, m.end()) or low < 20_000 or high < low:
            continue
        return low, high
    return None


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
