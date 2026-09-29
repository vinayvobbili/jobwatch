"""Public job-board APIs: Greenhouse, Lever and Ashby.

All three publish a company's open roles as JSON, without an API key, for anyone to
build a careers page on. Each parser turns one board's response into Jobs.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from . import __version__
from .models import Job
from .text import html_to_text, parse_salary, split_locations

USER_AGENT = f"jobwatch/{__version__} (+https://github.com/vinayvobbili/jobwatch)"


class SourceError(RuntimeError):
    pass


class NotFound(SourceError):
    pass


def get_json(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from None
        raise SourceError(f"{url}: HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SourceError(f"{url}: {e}") from None


def _time(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # Lever: milliseconds since the epoch
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _salary(job: Job, text: str) -> None:
    """Fill the pay range from free text when the board has no structured field for it."""
    if job.salary_min is None and (found := parse_salary(text)):
        job.salary_min, job.salary_max = found
        job.currency = job.currency or "USD"


def parse_greenhouse(data: dict, board: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        meta = {m.get("name"): m.get("value") for m in j.get("metadata") or []}
        location_type = str(meta.get("Location Type") or "")
        offices = [o.get("location") or o.get("name") or "" for o in j.get("offices") or []]
        job = Job(
            source="greenhouse", company=board, id=str(j["id"]), title=j.get("title", "").strip(),
            url=j.get("absolute_url", ""), company_name=j.get("company_name") or "",
            locations=split_locations((j.get("location") or {}).get("name", ""), *offices),
            remote=True if "remote" in location_type.lower() else None,
            department=((j.get("departments") or [{}])[0] or {}).get("name") or "",
            posted=_time(j.get("first_published") or j.get("updated_at")),
            description=html_to_text(j.get("content") or ""),
        )
        _salary(job, job.description)
        jobs.append(job)
    return jobs


def parse_lever(data: list, board: str) -> list[Job]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        sections = [f"{s.get('text', '').strip()}\n{html_to_text(s.get('content', ''))}" for s in j.get("lists") or []]
        description = "\n\n".join(p for p in [j.get("descriptionPlain") or html_to_text(j.get("description", "")),
                                              *sections, j.get("additionalPlain", "")] if p and p.strip())
        job = Job(
            source="lever", company=board, id=j["id"], title=j.get("text", "").strip(),
            url=j.get("hostedUrl", ""),
            locations=split_locations(*(cats.get("allLocations") or [cats.get("location") or ""])),
            remote=True if j.get("workplaceType") == "remote" else None,
            department=cats.get("department") or cats.get("team") or "",
            posted=_time(j.get("createdAt")), description=description,
        )
        pay = j.get("salaryRange") or {}
        if pay.get("interval") == "per-year-salary" and pay.get("min"):
            job.salary_min, job.salary_max, job.currency = int(pay["min"]), int(pay.get("max") or pay["min"]), \
                pay.get("currency") or "USD"
        elif not pay:
            _salary(job, j.get("salaryDescriptionPlain") or job.description)
        jobs.append(job)
    return jobs


def parse_ashby(data: dict, board: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        where = [j.get("location") or ""] + [s.get("location") or "" for s in j.get("secondaryLocations") or []]
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        if country and where[0] and country not in where[0]:
            where[0] = f"{where[0]}, {country}"
        job = Job(
            source="ashby", company=board, id=j["id"], title=j.get("title", "").strip(), url=j.get("jobUrl", ""),
            locations=split_locations(*where),
            # isRemote is also true for hybrid roles on some boards; workplaceType is the reliable signal.
            remote=True if j.get("workplaceType") == "Remote" else None,
            department=j.get("department") or j.get("team") or "",
            posted=_time(j.get("publishedAt")),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
        )
        comp = j.get("compensation") or {}
        salaries = [c for t in comp.get("compensationTiers") or [] for c in t.get("components") or []
                    if c.get("compensationType") == "Salary" and c.get("interval") == "1 YEAR" and c.get("minValue")]
        if salaries:
            job.salary_min = int(min(c["minValue"] for c in salaries))
            job.salary_max = int(max(c.get("maxValue") or c["minValue"] for c in salaries))
            job.currency = salaries[0].get("currencyCode") or "USD"
        else:
            _salary(job, comp.get("scrapeableCompensationSalarySummary") or job.description)
        jobs.append(job)
    return jobs


@dataclass(frozen=True)
class Source:
    name: str
    api: str                       # formatted with board=
    parse: Callable[..., list[Job]]
    careers: str                   # public job-board page, formatted with board=


SOURCES = {
    "greenhouse": Source("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
                         parse_greenhouse, "https://job-boards.greenhouse.io/{board}"),
    "lever": Source("lever", "https://api.lever.co/v0/postings/{board}?mode=json", parse_lever,
                    "https://jobs.lever.co/{board}"),
    "ashby": Source("ashby", "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
                    parse_ashby, "https://jobs.ashbyhq.com/{board}"),
}


def fetch(source: str, board: str, get=None) -> list[Job]:
    """Every open role on one company's board. `get` replaces the HTTP call (tests, caching)."""
    src = SOURCES[source]
    return src.parse((get or get_json)(src.api.format(board=board)), board)


_HOSTS = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse", "jobs.lever.co": "lever", "jobs.eu.lever.co": "lever",
    "api.lever.co": "lever", "jobs.ashbyhq.com": "ashby", "api.ashbyhq.com": "ashby",
}
_API_PREFIX = {"boards-api.greenhouse.io": 2, "api.lever.co": 2, "api.ashbyhq.com": 2}


def detect(url: str) -> tuple[str, str] | None:
    """(source, board) from a job or careers link on one of the supported boards, else None."""
    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    source = _HOSTS.get(host)
    if not source:
        return None
    query = parse_qs(parsed.query)
    if "for" in query:  # Greenhouse embed: boards.greenhouse.io/embed/job_board?for=<board>
        return source, query["for"][0]
    parts = [p for p in parsed.path.split("/") if p]
    skip = _API_PREFIX.get(host, 0)
    return (source, parts[skip]) if len(parts) > skip and parts[skip] != "embed" else None


def board_names(company: str) -> list[str]:
    """Likely board names for a company name: "Scale AI" -> scaleai, scale-ai, scale."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    names = ["".join(words), "-".join(words), words[0] if words else ""]
    return [n for i, n in enumerate(names) if n and n not in names[:i]]


def probe(company: str, get=None) -> list[tuple[str, str, list[Job]]]:
    """Find a company's boards by trying likely board names on every source: (source, board, open roles).

    A guessed name can belong to a different company, so check a role or two before adding a board."""
    if found := detect(company):
        source, board = found
        return [(source, board, fetch(source, board, get))]
    hits = []
    for name in board_names(company):
        for source in SOURCES:
            try:
                jobs = fetch(source, name, get)
            except SourceError:  # not found, or that board is unreachable right now
                continue
            if jobs:
                hits.append((source, name, jobs))
    return hits
