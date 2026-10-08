"""Public job-board APIs: Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Jibe, Rippling and Google.

Each publishes a company's open roles as JSON, without an API key: it's what their careers pages are built
on. Google Careers publishes its roles as an XML feed for job sites instead. Greenhouse, Lever, Ashby and
Google return a whole board in one response, and a parser turns it into Jobs. Rippling lists a board in one
response too, but its postings' text is read one at a time.
Workday and Eightfold boards at large companies list thousands of roles, so those are searched for the
watchlist's job titles, and only the new postings whose titles match are read in full (see fetch).
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlparse

from . import __version__
from .models import Job
from .text import html_to_text, in_us, is_remote, parse_salary, split_locations

USER_AGENT = f"jobwatch/{__version__} (+https://github.com/vinayvobbili/jobwatch)"


class SourceError(RuntimeError):
    pass


class NotFound(SourceError):
    pass


RETRIES = 3  # a board that says "slow down" (429) or "busy" (503) is asked again, waiting longer each time
MAX_WAIT = 30


def _wait(e: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait before asking again: the server's Retry-After if it gives one, else 2, 4, 8..."""
    after = (e.headers or {}).get("Retry-After", "")
    return min(float(after) if after.strip().isdigit() else 2 ** (attempt + 1), MAX_WAIT)


def _read(url: str, timeout: float, body: dict | None, accept: str) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from None
            if e.code in (429, 503) and attempt < RETRIES:
                time.sleep(_wait(e, attempt))
                continue
            raise SourceError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise SourceError(f"{url}: {e}") from None
    raise SourceError(f"{url}: no answer")  # not reached: the last attempt returns or raises


def get_json(url: str, timeout: float = 30, body: dict | None = None):
    """GET a JSON document, or POST `body` as JSON and read the reply."""
    raw = _read(url, timeout, body, "application/json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SourceError(f"{url}: {e}") from None


def get_text(url: str, timeout: float = 30) -> str:
    """A web page, as text (a careers page to look for job-board links in, a LinkedIn posting)."""
    return _read(url, timeout, None, "text/html,application/xhtml+xml,*/*").decode("utf-8", "replace")


def _time(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # Lever: milliseconds since the epoch
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    try:
        # Python 3.10 reads only "+00:00": Jibe writes "+0000"
        t = datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value).replace("Z", "+00:00")))
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


def parse_workable(data: dict, board: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        places = j.get("locations") if isinstance(j.get("locations"), list) else []
        where = [", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
                 for loc in places if not loc.get("hidden")] or \
                [", ".join(p for p in (j.get("city"), j.get("state"), j.get("country")) if p)]
        job = Job(
            source="workable", company=board, id=j["shortcode"], title=(j.get("title") or "").strip(),
            url=f"https://apply.workable.com/{board}/j/{j['shortcode']}/", company_name=data.get("name") or "",
            locations=split_locations(*where), remote=True if str(j.get("telecommuting")).lower() == "true" else None,
            department=j.get("department") or "", posted=_time(j.get("published_on") or j.get("created_at")),
            description=html_to_text(j.get("description") or ""),
        )
        _salary(job, job.description)
        jobs.append(job)
    return jobs


# -- Workday: board "tenant.wdN/site", from https://tenant.wdN.myworkdayjobs.com/site

WORKDAY_PAGE = 20          # the most Workday returns at once
SEARCH_CAP = 1000          # postings read per search term, at most: a broad term can match thousands


def _workday_parts(board: str) -> tuple[str, str, str]:
    """(api base, public base, tenant) for a board like "acme.wd1/Acme_Careers"."""
    host, _, site = board.partition("/")
    tenant, _, pod = host.partition(".")
    if not (tenant and pod.startswith("wd") and site):
        raise SourceError(f"a Workday board looks like tenant.wd1/Site, got {board!r}")
    root = f"https://{tenant}.{pod}.myworkdayjobs.com"
    return f"{root}/wday/cxs/{tenant}/{site}", f"{root}/{site}", tenant


def _workday_posted(text: str) -> datetime | None:
    """ "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago" (at least 30)."""
    text = (text or "").lower()
    days = 0 if "today" in text else 1 if "yesterday" in text else None
    if days is None and (m := re.search(r"(\d+)\+? days? ago", text)):
        days = int(m.group(1))
    return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)


def _search_all(page: Callable[[int], tuple[list, int]], size: int, cap: int = SEARCH_CAP, workers: int = 4) -> list:
    """Every result of a paged search, up to `cap`: page(offset) -> (results, total).

    The first page says how many there are; the rest are asked for at once."""
    found, total = page(0)
    offsets = range(size, min(total, cap), size) if found else ()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for results, _ in pool.map(page, offsets):
            found += results
    return found[:cap]


def _unread_if_refused(read: Callable[[], Job], listed: Job) -> Job:
    """One posting that can't be read right now (the board rate-limits a first big fetch) doesn't fail its whole
    board: the job is kept as listed, without its text, and the next fetch reads it (see `known`)."""
    try:
        return read()
    except SourceError:
        return listed


def _details(items: list, read: Callable, workers: int = 4) -> list:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(read, items))


def fetch_workday(board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    get = get or get_json
    api, public, tenant = _workday_parts(board)
    postings = {}
    for term in search or [""]:
        def page(offset, term=term):
            d = get(f"{api}/jobs", body={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset,
                                         "searchText": term})
            return d.get("jobPostings") or [], d.get("total") or 0
        for p in _search_all(page, WORKDAY_PAGE, cap):
            if p.get("externalPath"):
                postings.setdefault(p["externalPath"].rsplit("_", 1)[-1], p)

    def job(item) -> Job:
        pid, p = item
        key = f"workday:{board}:{pid}"
        if known and key in known and known[key].description:
            return known[key]  # read in full before: postings rarely change
        j = Job(source="workday", company=board, id=pid, title=(p.get("title") or "").strip(),
                url=public + p["externalPath"], company_name=tenant,
                locations=split_locations(p.get("locationsText") or ""), posted=_workday_posted(p.get("postedOn")))
        if wanted and not wanted(j.title):
            return j  # listed, not read: the title filter drops it anyway
        return _unread_if_refused(lambda: _workday_read(j, api, p["externalPath"], get), j)
    return _details(list(postings.items()), job)


def _workday_read(j: Job, api: str, path: str, get) -> Job:
    """Fill a Workday job from its posting (path: /job/<place>/<title>_<id>)."""
    info = (get(f"{api}{path}") or {}).get("jobPostingInfo") or {}
    j.title = j.title or (info.get("title") or "").strip()
    j.locations = split_locations(info.get("location") or "", *(info.get("additionalLocations") or [])) \
        or j.locations
    j.remote = True if (info.get("remoteType") or "").lower() == "remote" else None
    j.posted = _time(info.get("startDate")) or j.posted
    j.url = info.get("externalUrl") or j.url
    j.description = html_to_text(info.get("jobDescription") or "")
    _salary(j, j.description)
    return j


# -- Eightfold: board "tenant" or "tenant/domain", from https://tenant.eightfold.ai/careers?domain=domain

EIGHTFOLD_PAGE = 10
EIGHTFOLD_WORKERS = 1  # pages are 10 roles, so a big board is hundreds of requests: parallel ones get HTTP 429


def _eightfold_parts(board: str) -> tuple[str, str]:
    tenant, _, domain = board.partition("/")
    return f"https://{tenant}.eightfold.ai/api/pcsx", domain or f"{tenant}.com"


def _listish(value) -> list[str]:
    """Eightfold sends some lists as their Python repr: "['Denver, CO', 'Remote, United States']"."""
    if isinstance(value, list):
        return [str(v) for v in value]
    return re.findall(r"'([^']*)'", value or "") or ([value] if value else [])


def fetch_eightfold(board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    get = get or get_json
    api, domain = _eightfold_parts(board)
    tenant = board.partition("/")[0]
    positions = {}
    for term in search or [""]:
        def page(offset, term=term):
            d = (get(f"{api}/search?domain={quote(domain)}&query={quote(term)}&start={offset}") or {}).get("data") or {}
            return d.get("positions") or [], d.get("count") or 0
        for p in _search_all(page, EIGHTFOLD_PAGE, cap, EIGHTFOLD_WORKERS):
            positions.setdefault(str(p["id"]), p)

    def job(item) -> Job:
        pid, p = item
        key = f"eightfold:{board}:{pid}"
        if known and key in known and known[key].description:
            return known[key]
        where = p.get("workLocationOption") or ""
        posted = p.get("postedTs") or p.get("creationTs")
        j = Job(source="eightfold", company=board, id=pid, title=(p.get("name") or "").strip(),
                url=f"https://{tenant}.eightfold.ai/careers/job/{pid}?domain={domain}", company_name=tenant,
                locations=split_locations(*_listish(p.get("locations"))), department=p.get("department") or "",
                remote=True if where == "remote" or (where == "remote_local" and not _listish(p.get("locations")))
                else None,
                posted=datetime.fromtimestamp(int(posted), timezone.utc) if str(posted or "").isdigit() else None)
        if wanted and not wanted(j.title):
            return j
        def read() -> Job:
            info = (get(f"{api}/position_details?position_id={pid}&domain={quote(domain)}") or {}).get("data") or {}
            j.url = info.get("publicUrl") or j.url
            j.description = html_to_text(info.get("jobDescription") or "")
            _salary(j, j.description)
            return j
        return _unread_if_refused(read, j)
    return _details(list(positions.items()), job, EIGHTFOLD_WORKERS)


# -- Jibe (Google's careers-site product, over iCIMS and others): board is the site's host, e.g.
# careers.acme.com. The site's own /api/jobs lists every role with its full text, 100 a page.

JIBE_PAGE = 100


def _squash(text: str) -> str:
    return " ".join(text.split()).lower()


def fetch_jibe(board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    """Every role on a Jibe careers site. Small enough to read whole, so `search` and `wanted` aren't needed."""
    get = get or get_json

    def page(offset):
        d = get(f"https://{board}/api/jobs?page={offset // JIBE_PAGE + 1}&limit={JIBE_PAGE}") or {}
        return [j.get("data") or {} for j in d.get("jobs") or []], d.get("totalCount") or 0
    jobs = []
    for d in _search_all(page, JIBE_PAGE, cap):
        rid = str(d.get("req_id") or d.get("slug") or "")
        if not rid:
            continue
        text = html_to_text(d.get("description") or "")
        for k in ("responsibilities", "qualifications"):  # separate fields, or already in the description
            part = html_to_text(d.get(k) or "")
            if part and _squash(part.splitlines()[0]) not in _squash(text):
                text += "\n\n" + part
        where = d.get("location_name") or ""
        j = Job(source="jibe", company=board, id=rid, title=(d.get("title") or "").strip(),
                url=f"https://{board}/careers-home/jobs/{d.get('slug') or rid}",
                company_name=d.get("hiring_organization") or "",
                locations=split_locations(d.get("full_location") or where),
                remote=True if "remote" in (where + " " + " ".join(d.get("tags6") or [])).lower() else None,
                department=", ".join(c.get("name", "") for c in d.get("categories") or [] if c.get("name")),
                posted=_time(d.get("posted_date")), description=text.strip())
        _salary(j, j.description)
        jobs.append(j)
    return jobs


# -- Rippling: board is the slug in https://ats.rippling.com/<board>/jobs. The list names each role (once per
# place it's open in); the text is per posting, so only new postings whose titles match are read in full.

RIPPLING_API = "https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs"


def fetch_rippling(board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    """Every role on a Rippling board. Small boards: `search` isn't needed, `wanted` and `known` save reads."""
    get = get or get_json
    api = RIPPLING_API.format(board=board)
    listed: dict[str, list[dict]] = {}
    for p in (get(api) or [])[:cap]:
        if p.get("uuid"):
            listed.setdefault(p["uuid"], []).append(p)

    def job(item) -> Job:
        pid, ps = item
        key = f"rippling:{board}:{pid}"
        if known and key in known and known[key].description:
            return known[key]
        p = ps[0]
        places = [(x.get("workLocation") or {}).get("label") or "" for x in ps]
        j = Job(source="rippling", company=board, id=pid, title=(p.get("name") or "").strip(),
                url=p.get("url") or f"https://ats.rippling.com/{board}/jobs/{pid}",
                locations=split_locations(*places), department=(p.get("department") or {}).get("label") or "")
        if wanted and not wanted(j.title):
            return j
        return _unread_if_refused(lambda: _rippling_read(j, f"{api}/{pid}", get), j)
    return _details(list(listed.items()), job)


def _rippling_read(j: Job, url: str, get) -> Job:
    info = get(url) or {}
    parts = info.get("description") or {}
    j.title = (info.get("name") or j.title).strip()
    j.company_name = (info.get("companyName") or "").strip()
    j.locations = split_locations(*(info.get("workLocations") or [])) or j.locations
    j.remote = True if any(is_remote(loc) for loc in j.locations) else None
    j.department = (info.get("department") or {}).get("name") or j.department
    j.posted = _time(info.get("createdOn"))
    j.description = "\n\n".join(t for t in (html_to_text(v) for v in parts.values() if isinstance(v, str)) if t)
    _salary(j, j.description)
    return j


# -- Google (with YouTube and DeepMind): board "google" for its roles in the US, "google/any" for all of them.
# Google Careers publishes every open role, worldwide and with its full text, as one XML feed for job sites
# (~20 MB): one request a run, kept for a few minutes so a run's other reads of it don't fetch it again.

GOOGLE_FEED = "https://www.google.com/about/careers/applications/jobs/feed.xml"
GOOGLE_JOBS = "https://www.google.com/about/careers/applications/jobs/results/"
GOOGLE_KEEP = 600  # seconds a downloaded feed is used again (Google's own cache time is 25 minutes)
_google_feed_cache: list = []  # [(downloaded at, feed text)]
_google_lock = threading.Lock()
_US_PAY = re.compile(r"US: \$[\d,]+ - \$[\d,]+")  # pay is given per country; this is the US line


def _google_feed(get) -> ET.Element:
    if get:  # tests, or a caller with its own cache
        text = get(GOOGLE_FEED)
    else:
        with _google_lock:
            if not _google_feed_cache or time.monotonic() - _google_feed_cache[0][0] > GOOGLE_KEEP:
                _google_feed_cache[:] = [(time.monotonic(), get_text(GOOGLE_FEED, timeout=120))]
            text = _google_feed_cache[0][1]
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise SourceError(f"{GOOGLE_FEED}: {e}") from None


def _google_anywhere(board: str) -> bool:
    if board not in ("google", "google/any"):
        raise SourceError(f"the Google board is google (its US roles) or google/any, got {board!r}")
    return board == "google/any"


def _google_places(e: ET.Element) -> list[str]:
    """Each <location> as "City, ST, USA": the feed spreads it over city, state and country however it likes."""
    return split_locations(*(", ".join(p.strip() for p in (loc.findtext(k) or "" for k in ("city", "state", "country"))
                                       if p.strip()) for loc in e.iter("location")))


def _google_job(e: ET.Element, board: str, read: bool = True) -> Job:
    """A Job from one feed entry; `read` False keeps it without its text, like a searched board's unread one."""
    jid = (e.findtext("jobid") or "").strip()
    slug = urlparse(e.findtext("url") or "").path.rstrip("/").rsplit("/", 1)[-1]
    j = Job(source="google", company=board, id=jid, title=(e.findtext("title") or "").strip(),
            url=GOOGLE_JOBS + (slug if slug.startswith(f"{jid}-") else jid), company_name=e.findtext("employer") or "",
            locations=_google_places(e), remote=True if (e.findtext("isRemote") or "").lower() == "yes" else None,
            department=", ".join((c.text or "").replace("_", " ").title() for c in e.iter("category")
                                 if c.text and c.text != "JOB_CATEGORY_UNSPECIFIED"),
            posted=_time(e.findtext("published")))
    if read:
        j.description = html_to_text(e.findtext("description") or "")
        _salary(j, us.group(0) if (us := _US_PAY.search(j.description)) else j.description)
    return j


def _title_has(title: str, terms) -> bool:
    """A search term's words are all in the title ("forward deployed" finds "Forward Deployed Engineer")."""
    title = title.lower()
    return any(all(w in title for w in re.findall(r"\w+", t.lower())) for t in terms)


def fetch_google(board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    """Google's roles (its US ones, for board "google") whose titles have one of the `search` terms' words, all
    of them with no terms. One request whatever the size, so `cap` and `known` aren't needed. A role whose title
    fails `wanted` is kept without its text, as a searched board keeps one it didn't read."""
    anywhere, jobs = _google_anywhere(board), []
    for e in _google_feed(get).iter("job"):
        title = e.findtext("title") or ""
        if not (e.findtext("jobid") or "").strip() or (search and not _title_has(title, search)):
            continue
        if not (anywhere or any(in_us(p) for p in _google_places(e))):
            continue
        jobs.append(_google_job(e, board, read=not (wanted and not wanted(title.strip()))))
    return jobs


def _google_posting(pid: str, board: str, get) -> Job:
    for e in _google_feed(get).iter("job"):
        if (e.findtext("jobid") or "").strip() == pid:
            return _google_job(e, board)
    raise NotFound("Google Careers doesn't list that job any more")


@dataclass(frozen=True)
class Source:
    name: str
    api: str                       # formatted with board=; empty for a searched source
    parse: Callable[..., list[Job]] | None
    careers: str                   # public job-board page, formatted with board= (or the parts of it)
    search: Callable[..., list[Job]] | None = None  # a searched source's fetch: (board, get, search, wanted, known)


SOURCES = {
    "greenhouse": Source("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
                         parse_greenhouse, "https://job-boards.greenhouse.io/{board}"),
    "lever": Source("lever", "https://api.lever.co/v0/postings/{board}?mode=json", parse_lever,
                    "https://jobs.lever.co/{board}"),
    "ashby": Source("ashby", "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
                    parse_ashby, "https://jobs.ashbyhq.com/{board}"),
    "workable": Source("workable", "https://apply.workable.com/api/v1/widget/accounts/{board}?details=true",
                       parse_workable, "https://apply.workable.com/{board}/"),
    "workday": Source("workday", "", None, "https://{tenant}.{pod}.myworkdayjobs.com/{site}", fetch_workday),
    "eightfold": Source("eightfold", "", None, "https://{tenant}.eightfold.ai/careers?domain={domain}",
                        fetch_eightfold),
    "jibe": Source("jibe", "", None, "https://{board}/careers-home/jobs", fetch_jibe),
    "rippling": Source("rippling", "", None, "https://ats.rippling.com/{board}/jobs", fetch_rippling),
    "google": Source("google", "", None, GOOGLE_JOBS, fetch_google),
}


def careers_url(source: str, board: str) -> str:
    if source == "workday":
        host, _, site = board.partition("/")
        tenant, _, pod = host.partition(".")
        return SOURCES[source].careers.format(tenant=tenant, pod=pod, site=site)
    if source == "eightfold":
        return SOURCES[source].careers.format(tenant=board.partition("/")[0], domain=_eightfold_parts(board)[1])
    return SOURCES[source].careers.format(board=board)


def candidate_home(url: str) -> str | None:
    """Where the applicant signs in to see their applications, for a job on a board that has such a page.
    Each company's Workday site keeps its own accounts, so this is that company's page. Only Workday for now."""
    found = detect(url) if url else None
    if not found or found[0] != "workday":
        return None
    return careers_url(*found) + "/userHome"


def fetch(source: str, board: str, get=None, search=(), wanted=None, known=None, cap=SEARCH_CAP) -> list[Job]:
    """The open roles on one company's board. `get` replaces the HTTP call (tests, caching).

    Greenhouse, Lever, Ashby, Workable and Jibe return every role; Google every role whose title has a `search`
    term's words, from its whole feed. Workday and Eightfold are searched for each
    of `search` (plain title words; nothing searches for everything), reading in full only the postings whose
    title passes `wanted` and that aren't in `known` (key -> Job, read before) already."""
    src = SOURCES[source]
    if src.search:
        return src.search(board, get, search=search, wanted=wanted, known=known, cap=cap)
    return src.parse((get or get_json)(src.api.format(board=board)), board)


_HOSTS = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse", "jobs.lever.co": "lever", "jobs.eu.lever.co": "lever",
    "api.lever.co": "lever", "jobs.ashbyhq.com": "ashby", "api.ashbyhq.com": "ashby",
}
_API_PREFIX = {"boards-api.greenhouse.io": 2, "api.lever.co": 2, "api.ashbyhq.com": 2}


_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")  # Workday links often start /en-US/


def detect(url: str) -> tuple[str, str] | None:
    """(source, board) from a job or careers link on one of the supported boards, else None."""
    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]
    if m := re.fullmatch(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com", host):
        site = [p for p in parts if not _LOCALE.match(p)][:1]
        return ("workday", f"{m.group(1)}.{m.group(2)}/{site[0]}") if site and site[0] != "wday" else None
    if (m := re.fullmatch(r"(wd\d+)\.myworkdaysite\.com", host)) and len(parts) >= 3 and parts[0] == "recruiting":
        return "workday", f"{parts[1]}.{m.group(1)}/{parts[2]}"
    if m := re.fullmatch(r"([\w-]+)\.eightfold\.ai", host):
        domain = parse_qs(parsed.query).get("domain", [""])[0]
        return "eightfold", m.group(1) + (f"/{domain}" if domain and domain != f"{m.group(1)}.com" else "")
    if host == "apply.workable.com":
        return ("workable", parts[0]) if parts and parts[0] not in ("j", "api") else None
    if (m := re.fullmatch(r"([\w-]+)\.workable\.com", host)) and m.group(1) not in ("apply", "jobs", "www"):
        return "workable", m.group(1)
    if parts[:1] == ["careers-home"]:  # a Jibe site, on the company's own domain
        return "jibe", parsed.netloc.lower()
    if host == "ats.rippling.com":
        parts = [p for p in parts if not _LOCALE.match(p)]
        return ("rippling", parts[0]) if parts and parts[0] != "api" else None
    if host == "api.rippling.com" and "board" in parts[:-1]:
        return "rippling", parts[parts.index("board") + 1]
    if host == "careers.google.com" or (host == "google.com" and parts[:2] == ["about", "careers"]):
        return "google", "google"
    source = _HOSTS.get(host)
    if not source:
        return None
    query = parse_qs(parsed.query)
    if "for" in query:  # Greenhouse embed: boards.greenhouse.io/embed/job_board?for=<board>
        return source, query["for"][0]
    skip = _API_PREFIX.get(host, 0)
    return (source, parts[skip]) if len(parts) > skip and parts[skip] != "embed" else None


def _posting_id(source: str, url: str) -> str | None:
    """The posting's id in a link to one job on a board, or None for a link to the whole board."""
    parsed = urlparse(url if "//" in url else f"https://{url}")
    parts = [p for p in parsed.path.split("/") if p]
    if source == "greenhouse":
        if jid := parse_qs(parsed.query).get("gh_jid"):
            return jid[0]
        return parts[parts.index("jobs") + 1] if "jobs" in parts[:-1] else None
    if source in ("lever", "ashby"):
        return parts[1] if len(parts) > 1 else None
    if source == "jibe":
        return parts[2] if len(parts) > 2 and parts[1] == "jobs" else None
    if source == "rippling":
        return parts[parts.index("jobs") + 1] if "jobs" in parts[:-1] else None
    if source == "google":  # .../jobs/results/<id>-<slug>; an .../apply/<uuid> link doesn't name the posting
        m = re.match(r"\d+(?=-|$)", parts[parts.index("results") + 1]) if "results" in parts[:-1] else None
        return m.group(0) if m else None
    if source == "workable":
        for marker in ("j", "view"):
            if marker in parts[:-1]:
                return parts[parts.index(marker) + 1].removesuffix(".md")
    return None


def posting(url: str, get=None) -> Job | None:
    """One job, read from its link on a supported board; None when the link isn't to one job on one.
    Raises SourceError when the board can't be read or no longer lists the job."""
    found = detect(url)
    if not found:
        return None
    source, board = found
    if source == "google":  # looked up in the whole feed (an XML one): a link can be to a role outside the US
        pid = _posting_id(source, url)
        return _google_posting(pid, board, get) if pid else None
    get = get or get_json
    if source == "workday":
        path = urlparse(url if "//" in url else f"https://{url}").path
        if "/job/" not in path:
            return None
        path = path[path.index("/job/"):]
        api, public, tenant = _workday_parts(board)
        j = _workday_read(Job(source="workday", company=board, id=path.rsplit("_", 1)[-1], title="",
                              url=public + path, company_name=tenant), api, path, get)
        if not j.description:
            raise NotFound("that Workday posting isn't open any more")
        return j
    pid = _posting_id(source, url)
    if not pid:
        return None
    if source == "rippling":  # one posting is read on its own; the board's list doesn't have the text
        j = _rippling_read(Job(source="rippling", company=board, id=pid, title="",
                               url=f"https://ats.rippling.com/{board}/jobs/{pid}"),
                           f"{RIPPLING_API.format(board=board)}/{pid}", get)
        if not j.title:
            raise NotFound("that Rippling posting isn't open any more")
        return j
    for j in fetch(source, board, get):
        if j.id.lower() == pid.lower():
            return j
    raise NotFound(f"the {source} board {board!r} doesn't list that job any more")


def board_names(company: str) -> list[str]:
    """Likely board names for a company name: "Scale AI" -> scaleai, scale-ai, scale."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    names = ["".join(words), "-".join(words), words[0] if words else ""]
    return [n for i, n in enumerate(names) if n and n not in names[:i]]


PROBE_CAP = 100  # open roles listed (not read) to show what a board is: a sample, not the count


def open_roles(jobs: list[Job]) -> str:
    """How many roles a probe saw: "12", or "100+" when it stopped at the sample size."""
    return f"{len(jobs)}+" if len(jobs) >= PROBE_CAP else str(len(jobs))


def _never(title: str) -> bool:
    return False


def _peek(source: str, board: str, get) -> list[Job]:
    return fetch(source, board, get, wanted=_never, cap=PROBE_CAP)


# Workday spreads companies over numbered data centers (wd1, wd5, ...) and each names its careers site.
WORKDAY_PODS = ("wd1", "wd3", "wd5", "wd10", "wd12", "wd101", "wd103", "wd501", "wd503")


def _workday_sites(tenant: str) -> list[str]:
    t = tenant.capitalize()
    names = ["External", "Careers", tenant, t, f"{t}_Careers", f"{t}Careers", "External_Careers", "careers"]
    return [n for i, n in enumerate(names) if n not in names[:i]]


def probe_workday(tenant: str, get=None) -> list[tuple[str, list[Job]]]:
    """A company's Workday site by its likely tenant name: (board, open roles), or nothing.

    Workday answers 200 for a site that exists, 404 when the tenant is in that data center but the site is
    named something else, and 422 when the tenant isn't there."""
    def at(pod):
        board = f"{tenant}.{pod}/External"
        try:
            return pod, _peek("workday", board, get)
        except NotFound:
            return pod, None    # here, under another site name
        except SourceError:
            return None, None   # not here
    with ThreadPoolExecutor(max_workers=len(WORKDAY_PODS)) as pool:
        pods = [(pod, jobs) for pod, jobs in pool.map(at, WORKDAY_PODS) if pod]
    hits = []
    for pod, jobs in pods:
        if jobs:
            hits.append((f"{tenant}.{pod}/External", jobs))
            continue
        for site in _workday_sites(tenant)[1:]:
            try:
                if jobs := _peek("workday", f"{tenant}.{pod}/{site}", get):
                    hits.append((f"{tenant}.{pod}/{site}", jobs))
                    break
            except SourceError:
                continue
    return hits


_LINK = re.compile(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+/")
_HREF = re.compile(r"https?://[\w.-]+\.[a-z]{2,}(?:/[^\s\"'<>\\]*)?", re.I)


def boards_on_page(url: str, page=None) -> list[tuple[str, str]]:
    """The supported boards a web page links to: a company's careers page often hands off to its ATS
    ("Open roles" → ats.rippling.com/acme/jobs, or a Greenhouse embed), under a board name nobody would guess."""
    text = html.unescape((page or get_text)(url if "//" in url else f"https://{url}")).replace("\\/", "/")  # JSON
    found: list[tuple[str, str]] = []
    for link in _HREF.findall(text):
        if (board := detect(link)) and board not in found:
            found.append(board)
    return found


def probe(company: str, get=None, page=None) -> list[tuple[str, str, list[Job]]]:
    """Find a company's boards by trying likely board names on every source: (source, board, open roles).
    A link to the company's own careers page is read for links to a board instead (`page` fetches it).

    A guessed name can belong to a different company, so check a role or two before adding a board. Roles on
    a searched board (Workday, Eightfold) are listed, not read in full: a sample of up to PROBE_CAP."""
    if found := detect(company):
        source, board = found
        return [(source, board, _peek(source, board, get))]
    if _LINK.match(company):  # the company's own careers page: look for links to a board on it
        hits = []
        for source, board in boards_on_page(company, page):
            try:
                hits.append((source, board, _peek(source, board, get)))
            except SourceError:
                continue
        return hits
    names = board_names(company)
    # jibe: sites on their own domains; google: Google's own board ("Google DeepMind" finds it too)
    tries = [(s, n) for n in names for s in SOURCES if s not in ("workday", "jibe", "google")]
    tries += [("google", "google")] if "google" in names else []

    def one(t):
        try:
            return t, _peek(*t, get)
        except SourceError:  # not found, or that board is unreachable right now
            return t, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        hits = [(s, n, jobs) for (s, n), jobs in pool.map(one, tries) if jobs]
        for found in pool.map(lambda n: probe_workday(n, get), [n for n in names if "-" not in n]):
            hits += [("workday", board, jobs) for board, jobs in found]
    return hits
