"""Company logos for the page: each company's own site icon, found once and kept in the state file, so a card
shows the company's logo instead of its initials. No logo service is asked: the icon comes from the company's site.

The site comes from what's tracked about the company: a job's link on its own domain (careers.acme.com), or the
domain its postings link to whose name is the company's ("Acme" and acme.com), else its name plus .com when
that home page names the company. The icon is the biggest one the home page declares (an apple-touch-icon, then
<link rel=icon> by size), else /favicon.ico. robots.txt is obeyed, and only an image is kept (checked by its
bytes, not by what the site says it is).
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from . import dupes, sources
from .company import _HOST, _SECOND_LEVEL
from .models import Job

FRESH = timedelta(days=90)    # a logo found is used this long before it's looked for again
MISSING = timedelta(days=14)  # when to look again for a company whose logo wasn't found
MAX_BYTES = 256_000           # a bigger "icon" isn't one
PAUSE = 1.0                   # seconds between two companies looked up
MIN_NAME = 3                  # a domain name this short ("ge") could be anyone's

_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-z-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_TOUCH = ("apple-touch-icon", "apple-touch-icon-precomposed")


def key(name: str) -> str:
    """What a company's logo is kept under: its name as dupes.py compares companies."""
    return dupes.company_key(name or "")


def site_of(host: str) -> str:
    """The domain a host belongs to: careers.acme.com -> acme.com, www.acme.co.uk -> acme.co.uk."""
    labels = host.lower().strip(".").removeprefix("www.").split(".")
    n = 3 if len(labels) > 2 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2 else 2
    return ".".join(labels[-n:])


def _names(job: Job) -> set[str]:
    """The company's name, and its board's when that's a plain name (a Workday board's isn't)."""
    board = key(job.company) if re.fullmatch(r"[a-z0-9-]+", job.company or "") else ""
    return {k for k in (key(job.display_company), board) if len(k) >= MIN_NAME}


def _fit(site: str, names: set[str]) -> int:
    """2 when the domain's name is the company's, 1 when one starts with the other (globex and globexcorp), else 0."""
    label = key(site.split(".")[0])
    if len(label) < MIN_NAME:
        return 0
    if label in names:
        return 2
    return int(any(n.startswith(label) or label.startswith(n) for n in names))


def sites(jobs: list[Job]) -> list[tuple[str, bool]]:
    """The company's likely domains from its jobs, best first, each with whether it's only a guess: ones its job
    links and postings point to whose name is the company's, then its name plus .com (a guess: see named)."""
    names = set().union(*(_names(j) for j in jobs)) if jobs else set()
    seen = Counter()
    for j in jobs:
        hosts = [urlparse(j.url).hostname or ""] + [urlparse(h if "//" in h else "//" + h).hostname or ""
                                                    for h in _HOST.findall(j.description or "")]
        for host in filter(None, hosts):
            site = site_of(host)
            if fit := _fit(site, names):
                seen[site] += fit
    found = [s for s, _ in seen.most_common()]
    return [(s, False) for s in found] + [(f"{n}.com", True) for n in sorted(names, key=len) if f"{n}.com" not in found]


def named(html: str, jobs: list[Job]) -> bool:
    """Whether a home page names the company (a guessed domain could be anyone's)."""
    text = re.sub(r"[^a-z0-9]+", "", html.lower())
    return any(n in text for j in jobs for n in _names(j))


def icons(html: str, base: str) -> list[str]:
    """A home page's icons, biggest first, then /favicon.ico."""
    found = []
    for tag in _LINK.findall(html):
        a = {k.lower(): v.strip("'\"") for k, v in _ATTR.findall(tag)}
        rel = a.get("rel", "").lower().split()
        href = a.get("href", "")
        if not href or href.startswith("data:") or not ("icon" in rel or any(t in rel for t in _TOUCH)):
            continue
        size = max((int(w) for w in re.findall(r"(\d+)x\d+", a.get("sizes", ""))), default=0)
        if any(t in rel for t in _TOUCH):
            size = size or 180
        elif href.lower().split("?")[0].endswith(".svg") or a.get("type") == "image/svg+xml":
            size = size or 256
        found.append((size or 16, urljoin(base, href)))
    found.sort(key=lambda t: -t[0])
    return list(dict.fromkeys([u for _, u in found] + [urljoin(base, "/favicon.ico")]))


def image_type(data: bytes) -> str | None:
    """The content type of an image, from its first bytes; None when it isn't one."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):
        return "image/x-icon"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:1000].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith((b"<?xml", b"<!--", b"<!doctype svg")) and b"<svg" in head):
        return "image/svg+xml"
    return None


def find(jobs: list[Job], get=None, get_bytes=None, robots=None) -> tuple[str, str, bytes]:
    """(domain, content type, image) for the company these jobs are at; ("", "", b"") when none is found."""
    from .alerts import Robots
    get, get_bytes = get or sources.get_text, get_bytes or sources.get_bytes
    robots = robots or Robots(get)
    for site, guess in sites(jobs):
        home = f"https://{site}/"
        try:
            html = get(home) if robots.allowed(home) else ""
        except sources.SourceError:
            html = ""
        if guess and not named(html, jobs):
            continue
        for url in icons(html, home):
            if not robots.allowed(url):
                continue
            try:
                data = get_bytes(url)
            except sources.SourceError:
                continue
            if len(data) <= MAX_BYTES and (ctype := image_type(data)):
                return site, ctype, data
    return "", "", b""


def due(kept, now: datetime | None = None) -> bool:
    """Whether a company's logo (store.logo's answer) should be looked for (again)."""
    if not kept:
        return True
    _, _, body, at = kept
    return (now or datetime.now(timezone.utc)) - at >= (FRESH if body else MISSING)


def look_up(store, names: list[str], jobs: list[Job], **kw) -> list[str]:
    """Look up the logos of the companies named (that are due), from their jobs; the ones found."""
    by_name: dict[str, list[Job]] = {}
    for j in jobs:
        by_name.setdefault(key(j.display_company), []).append(j)
    found = []
    for i, name in enumerate(dict.fromkeys(key(n) for n in names)):
        if not name or not due(store.logo(name)) or not by_name.get(name):
            continue
        if i:
            time.sleep(PAUSE)
        site, ctype, data = find(by_name[name][:20], **kw)
        store.save_logo(name, site, ctype, data)
        if data:
            found.append(name)
    return found
