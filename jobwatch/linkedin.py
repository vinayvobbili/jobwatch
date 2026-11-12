"""Jobs found on LinkedIn: look for the same job on the company's own board, where the application goes and
where jobwatch can keep checking it.

LinkedIn's robots.txt disallows every page (`Disallow: /` for `User-agent: *`), its job postings included, so
jobwatch never reads linkedin.com. From a LinkedIn link it takes only the posting's id; the company, the title
and the text come from the person (or a job-alert email).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from . import sources
from .models import Job


def job_id(url: str) -> str | None:
    """The posting id in a LinkedIn job link: /jobs/view/<id>, /jobs/view/<title>-<id>, or ?currentJobId=<id>."""
    parsed = urlparse(url if "//" in url else f"https://{url}")
    if not re.fullmatch(r"(?:[\w-]+\.)?linkedin\.com", parsed.netloc.lower()):
        return None
    if ids := parse_qs(parsed.query).get("currentJobId"):
        return ids[0] if ids[0].isdigit() else None
    m = re.search(r"/jobs(?:-guest/jobs/api/jobPosting|/view)/(?:[\w%-]*-)?(\d{6,})/?$", parsed.path)
    return m.group(1) if m else None


@dataclass
class Posting:
    id: str
    title: str
    company: str
    location: str
    description: str

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.id}/"


_SUFFIX = re.compile(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|plc|gmbh|group|holdings|"
                     r"technologies|labs)\b\.?", re.I)


_RATING = re.compile(r"\s+[1-5]\.\d$")


def unrated(company: str) -> str:
    """A company's name without the star rating a job site puts after it: "Initech 3.9" -> "Initech"."""
    return _RATING.sub("", company.strip())


def company_names(company: str) -> list[str]:
    """Names to look for a company's board under: "Initech Holdings, Inc." -> "Initech Holdings, Inc.",
    "Initech"."""
    company = unrated(company)
    bare = " ".join(_SUFFIX.sub(" ", company).replace(",", " ").split())
    return [n for n in dict.fromkeys([company.strip(), bare]) if n]


def _words(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", re.sub(r"\([^)]*\)|\[[^]]*\]", " ", title.lower())))


def same_title(a: str, b: str) -> bool:
    """Titles of one job on two sites: the same words, leaving out what's in brackets ("(Remote - NC)",
    "[123]") and allowing one extra or missing word."""
    x, y = _words(a), _words(b)
    return bool(x and y) and len(x ^ y) <= 1 and len(x & y) >= 2


def _bare(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company_names(name)[-1].lower()) if name.strip() else ""


def same_company(a: str, b: str) -> bool:
    """Two names for one company: "Initech, Inc." and "initech" (suffixes, case and punctuation aside)."""
    return bool(_bare(a)) and _bare(a) == _bare(b)


def same_words(a: str, b: str) -> bool:
    """Exactly the same title, leaving out what's in brackets: stricter than same_title, for telling that a job
    is one already tracked."""
    return bool(_words(a)) and _words(a) == _words(b)


def on_board(p: Posting, watched: list[tuple[str, str, str]] = (), get=None, page=None) -> Job | None:
    """The same job on the company's own board: a watched board under the company's name ((source, board,
    name) in `watched`) if there is one, else the boards `find` finds for the name. A searched board (Workday,
    Eightfold) is searched for the title. None unless exactly one open role there has the same title."""
    company = _bare(p.company)
    tries = [(s, b) for s, b, name in watched if company and company in (_bare(name or b), _bare(b))]
    if not tries:
        for name in company_names(p.company):
            tries += [(s, b) for s, b, _ in sources.probe(name, get, page) if (s, b) not in tries]
            if tries:
                break
    found: dict[str, tuple[int, Job]] = {}
    for source, board in tries:
        try:
            jobs = sources.fetch(source, board, get, search=search_terms(p.title),
                                 wanted=lambda t: could_be(t, p.title), cap=sources.PROBE_CAP)
        except sources.SourceError:
            continue
        for j in jobs:
            if (tier := title_tier(j.title, p.title)) is not None and j.description:
                found[j.key] = (tier, j)
    return _pick(found, p.location, p.title)


_SENIORITY = {"senior", "sr", "staff", "principal", "lead", "junior", "jr", "associate", "head", "director",
              "manager", "mid", "intermediate"}
_FUZZY = 0.8  # the share of the words two titles must have in common to be taken for one job's


def search_terms(title: str) -> list[str]:
    """What to search a board for: the title's words, then the title without its seniority words ("Sr." and
    "Senior" are spelled alike on few boards). Punctuation is left out: a portal can answer a comma with an error."""
    full = " ".join(re.findall(r"[A-Za-z0-9+#]+", re.sub(r"\([^)]*\)|\[[^]]*\]", " ", title)))
    core = " ".join(w for w in full.split() if w.lower() not in _SENIORITY)
    return [t for t in dict.fromkeys([full, core]) if t]


def _unbracketed(title: str) -> str:
    return re.sub(r"\([^)]*\)|\[[^]]*\]", " ", title)


def _spelled(title: str) -> set[str]:
    """Every word of a title, brackets' and "Sr." for "Senior" too: "Staff Engineer (Blue Team)" and
    "Staff Engineer - Blue Team (US)" say the same."""
    return {"senior" if w == "sr" else w for w in re.findall(r"[a-z0-9+#]+", title.lower())}


def title_tier(a: str, b: str) -> int | None:
    """How well two titles of one job on two sites agree: 0 the same words, 1 the same but one extra or missing
    word, 2 nearly all the same words (bracketed ones counted: "(Blue Team)" and "- Blue Team (US)"); None if
    they are two jobs' titles."""
    if same_words(a, b):
        return 0
    if same_title(a, b):
        return 1
    x, y = _spelled(a), _spelled(b)
    return 2 if len(x & y) >= 3 and len(x & y) / len(x | y) >= _FUZZY else None


def could_be(listed: str, title: str) -> bool:
    """Whether a posting listed under this title is worth reading in full to see if it's `title`'s: its title
    agrees (title_tier), or has all of `title`'s words (a careers site's sitemap gives a title from the link, with
    the place after it: "... security remote united states")."""
    return title_tier(listed, title) is not None or (len(w := _spelled(title)) >= 3 and w <= _spelled(listed))


_PLACE_STOP ={"hybrid", "on", "site", "onsite", "area", "metropolitan", "greater", "office"}


def _place_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _PLACE_STOP


def _near(job: Job, location: str) -> tuple[float, int]:
    """How close a posting's places come to the one asked for: its best-matching place's share of words in common
    (so "Boulder, CO" is nearer "Boulder, CO" than a list of cities), then fewer places listed first."""
    want = _place_words(location)
    best = max((len(want & w) / len(want | w) for place in job.locations if (w := _place_words(place))), default=0)
    return best if want else 0, -len(job.locations)


def _pick(found: dict[str, tuple[int, Job]], location: str = "", title: str = "") -> Job | None:
    """The one job on the board that is this title's: of the closest-spelled titles, the posting nearest the
    place asked for. None if two different titles tie, or two postings of one title can't be told apart by place
    (neither is picked: it's two openings)."""
    if not found:
        return None
    best = min(tier for tier, _ in found.values())
    jobs = [j for tier, j in found.values() if tier == best]
    # "Engineer (IT Security)" and "Engineer (Research)" have the same words outside brackets: the brackets tell
    if title and (same := [j for j in jobs if _spelled(j.title) == _spelled(title)]):
        jobs = same
    if len({frozenset(_spelled(_unbracketed(j.title))) for j in jobs}) > 1:  # "(US)" and "(UK)" are places
        return None
    if len(jobs) == 1:
        return jobs[0]
    ranked = sorted(jobs, key=lambda j: _near(j, location), reverse=True)
    return ranked[0] if _near(ranked[0], location) > _near(ranked[1], location) else None
