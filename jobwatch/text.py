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
_NOT_ANNUAL = re.compile(r"\s*(?:USD\s*)?(?:/|per\s+|an?\s+)(?:hour|hr|month|mo|week|day)\b", re.I)
# "167,000 - 230,000 USD per year" or "88,000 to 136,900.00 USD": no dollar sign, the currency after (a CAD
# range next to it is skipped)
_USD_AFTER = re.compile(r"(?<![\d,.$])(\d{2,3},\d{3})(?:\.\d{2})?\s*(?:-|–|—|to)\s*(\d{2,3},\d{3})(?:\.\d{2})?\s*USD\b")


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
    for m in _USD_AFTER.finditer(text or ""):
        low, high = _dollars(m.group(1), None), _dollars(m.group(2), None)
        if not (_NOT_ANNUAL.match(text, m.end()) or high < low):
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


_DC = re.compile(r"\bWashington,?\s*D\.?\s?C\b\.?|\bDistrict of Columbia\b", re.I)
# A state by name (any case), or by code in capitals standing on its own ("Remote - CA", "CA, NV, OR or WA"):
# "or", "in" and "me" are words too.
_STATE = re.compile(r"(?i:\b(" + "|".join(sorted(STATES.values(), key=len, reverse=True)) + r")\b)"
                    r"|(?<![\w.])(" + "|".join(STATES) + r")(?![\w.])")
_CODE_OF = {name.lower(): code for code, name in STATES.items()}
# What a list of states says besides the states: "California, USA; Nevada, USA", "the following states: CA, NV".
_LIST_WORDS = re.compile(r"\b(?:and|or|only|states?|following|one|of|the|remote|locations?|in|within)\b|[^\w]+",
                         re.I)


def state_code(name: str) -> str | None:
    """ "NC" or "North Carolina" (any case) -> "NC"; None for anything that isn't a US state (or DC)."""
    s = " ".join(name.split()).strip(" .")
    if s.upper() in STATES:
        return s.upper()
    return "DC" if _DC.fullmatch(s) else _CODE_OF.get(s.lower())


def us_states(text: str) -> list[str]:
    """The US states a place names, as codes in order, each once: "Remote-Minnesota-Minneapolis Metro" -> ["MN"],
    "Remote - Washington D.C." -> ["DC"]."""
    found = (state_code(m.group(0)) for m in _STATE.finditer(_DC.sub(" DC ", text)))
    return list(dict.fromkeys(c for c in found if c))


def state_list(text: str) -> list[str] | None:
    """The states, when the text is nothing but a list of US states: "California, USA; Nevada, USA",
    "CA, NV, OR or WA", "Remote - Texas". None when it names anything else too ("Austin, TX", "anywhere in the
    United States, with travel to Austin, TX"), or no state at all."""
    text = _DC.sub(" DC ", text)
    rest = _STATE.sub(" ", text)
    rest = _LIST_WORDS.sub(" ", _US_WIDE_CODES.sub(" ", _US_WIDE.sub(" ", rest)))
    rest = re.sub(r"\b(?:work|from|at|home?|fully|friendly|first|anywhere|hybrid)\b", " ", rest, flags=re.I)
    return (us_states(text) or None) if not rest.strip() else None


# Where a posting says a remote job is open: "Remote locations: California, USA; Nevada, USA.", "remote in CA,
# NV, OR or WA", "must reside in one of the following states: ...". The rest of the line is checked with state_list.
_REMOTE_LIMIT = re.compile(
    r"remote\s+locations?\s*:(?P<a>[^\n]+)"
    r"|remote\s+(?:only\s+)?(?:in|from|within)\b(?P<b>[^\n]+)"
    r"|(?:must|required\s+to|need\s+to|should)\s+(?:currently\s+)?(?:reside|live|be\s+located|be\s+based)"
    r"\s+(?:in|within)\b(?P<c>[^\n]+)", re.I)


def remote_states_in_text(text: str) -> list[str]:
    """The states a posting's text limits a remote job to; [] when it doesn't (or says the whole US)."""
    out: list[str] = []
    for m in _REMOTE_LIMIT.finditer(_DC.sub(" DC ", text)):
        # Up to the end of the sentence; "D.C." is "DC" by now, so a period ends it.
        segment = re.split(r"\.(?:\s|$)|\.$", m.group("a") or m.group("b") or m.group("c"))[0]
        out += state_list(segment) or []
    return list(dict.fromkeys(out))


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
