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


def company_names(company: str) -> list[str]:
    """Names to look for a company's board under: "Initech Holdings, Inc." -> "Initech Holdings, Inc.",
    "Initech"."""
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
    matches: dict[str, Job] = {}
    for source, board in tries:
        try:
            jobs = sources.fetch(source, board, get, search=[re.sub(r"\([^)]*\)|\[[^]]*\]", " ", p.title).strip()],
                                 wanted=lambda t: same_title(t, p.title), cap=sources.PROBE_CAP)
        except sources.SourceError:
            continue
        for j in jobs:
            if same_title(j.title, p.title) and j.description:
                matches[j.key] = j
    return next(iter(matches.values())) if len(matches) == 1 else None
