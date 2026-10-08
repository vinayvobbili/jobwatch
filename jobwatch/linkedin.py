"""Jobs found on LinkedIn: read a posting from its public page, then look for the same job on the company's own
board, where the application goes and where jobwatch can keep checking it.

LinkedIn serves every public posting at /jobs-guest/jobs/api/jobPosting/<id> without signing in: the title,
company, place, pay when listed, the text, and whether it still takes applications. It's one page per link the
person gives, nothing more: jobwatch doesn't search or crawl LinkedIn.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from . import sources
from .models import Job
from .text import html_to_text, parse_salary

GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


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
    salary_min: int | None = None
    salary_max: int | None = None
    closed: bool = False

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.id}/"


def _first(pattern: str, page: str) -> str:
    m = re.search(pattern, page, re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else ""


def parse(page: str, pid: str) -> Posting:
    """A posting from LinkedIn's public posting page. Raises SourceError when the page isn't one (LinkedIn
    answers too many requests with a sign-in or challenge page)."""
    title = _first(r"<h2[^>]*top-card-layout__title[^>]*>(.*?)</h2>", page)
    if not title:
        raise sources.SourceError("LinkedIn didn't show that posting (it may be asking to sign in): try again "
                                  "later, or add it with the company, title and pasted text")
    body = re.search(r'<div class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>\s*(?:<button|</section)',
                     page, re.S)
    pay = _first(r'<div class="salary compensation__salary"[^>]*>(.*?)</div>', page).replace("/yr", "")
    p = Posting(id=pid, title=title, company=_first(r"topcard__org-name-link[^>]*>(.*?)</a>", page),
                location=_first(r'<span class="topcard__flavor topcard__flavor--bullet"[^>]*>(.*?)</span>', page),
                description=html_to_text(body.group(1)) if body else "",
                closed=bool(re.search(r"No longer accepting applications", page, re.I)))
    if found := parse_salary(pay):
        p.salary_min, p.salary_max = found
        p.description += f"\n\nBase pay range (LinkedIn): {pay}"
    return p


def read(url: str, page=None) -> Posting | None:
    """The posting a LinkedIn job link points to; None when the link isn't to one LinkedIn job."""
    pid = job_id(url)
    if not pid:
        return None
    return parse((page or sources.get_text)(GUEST.format(id=pid)), pid)


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
