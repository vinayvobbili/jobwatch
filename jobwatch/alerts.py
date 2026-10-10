"""Job-alert emails (LinkedIn, Built In, Indeed and others) turned into tracked jobs.

The emails are handed to jobwatch: files (.eml, an .mbox, a folder of them), stdin, or raw messages from an
assistant that read them with its mail connector. jobwatch never asks for, keeps or logs a mail password; the
optional IMAP route (off unless `alerts.imap` is set) takes it from an environment variable or the macOS keychain
each time.

Each sender has a parser, with a generic one for the rest. Every job's link is cleaned of tracking parameters and
redirect wrappers. Then, for the jobs that pass the watchlist's filters on what the email says:

- a link to one posting on a supported board (Greenhouse, Workday...) is read from there (sources.posting);
- a LinkedIn link is never read (linkedin.com's robots.txt disallows every page): the email's title, company and
  place stand in for the posting, and the same job is looked for on the company's own board;
- any other site's page is read only when its robots.txt (the rules for every crawler, `User-agent: *`) allows it,
  for the posting's JobPosting data and a link to the company's board; then the company's board is looked for too.

A job found on its company's board is tracked there; otherwise from what the email (and the page) said. Jobs
already tracked, including the same job seen on its board, are left alone. New ones are status new, so they go
through the filters into the digest like any other, with `via` saying where they came from (linkedin-alert...).
A new one that's (maybe) the same opening as a job already applied to, queued or skipped (see dupes.py) says
so, and the same opening (a shared id) is recorded as its duplicate; it's still in the digest, flagged.
"""

from __future__ import annotations

import email
import html
import imaplib
import os
import re
import ssl
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from . import dupes, linkedin, sources
from .filters import reject_reason
from .models import Job
from .store import MANUAL, Store, _slug
from .text import annual, html_to_text, parse_salary, pay_period, split_locations


class AlertError(RuntimeError):
    pass


# -- Links: redirect wrappers off, tracking parameters off, one canonical form per job on the big sites.

_TRACKING = re.compile(
    r"(utm_\w+|trk\w*|tracking\w*|refid|ref|lipi|midtoken|midsig|otptoken|eid|mc_[ce]id|fbclid|gclid|msclkid|"
    r"_hs\w+|mkt_tok|gh_src|lever-\w+|source|src|alid|tk|tmtk|from|qd|rd|bb|i|preference_id|email\w*|recipient\w*|"
    r"uid|user\w*|token|sig|campaign\w*|cmp|cid|sid|ssid|fmid|jobalert\w*)", re.I)


def _unwrap(url: str) -> str:
    """The link a click-tracking redirect stands for (Amazon SES, Google, Outlook safe links), without
    following it."""
    for _ in range(3):
        p = urlparse(url)
        host = p.netloc.lower()
        if host.endswith(".awstrack.me") and "/L0/" in p.path:  # /L0/<link, encoded>/<n>/<signature>
            url = unquote(p.path.split("/L0/", 1)[1].split("/", 1)[0])
        elif host in ("google.com", "www.google.com") and p.path == "/url":
            q = dict(parse_qsl(p.query))
            url = q.get("q") or q.get("url") or url
            if url == p.geturl():
                break
        elif host.endswith(".safelinks.protection.outlook.com"):
            url = dict(parse_qsl(p.query)).get("url", url)
            if url == p.geturl():
                break
        else:
            break
    return url


def clean_link(url: str) -> str:
    """A job link without tracking: LinkedIn and Indeed links become their plain posting link, Built In's lose
    their query, and other links lose tracking parameters (utm_*, ref, token...) and the fragment."""
    url = _unwrap(html.unescape(url.strip()))
    if pid := linkedin.job_id(url):
        return f"https://www.linkedin.com/jobs/view/{pid}/"
    p = urlparse(url if "//" in url else f"https://{url}")
    host = p.netloc.lower().removeprefix("www.")
    if host.endswith("indeed.com") and (jk := dict(parse_qsl(p.query)).get("jk")):
        return f"https://www.indeed.com/viewjob?jk={jk}"
    if host == "builtin.com" and p.path.startswith("/job/"):
        return f"https://builtin.com{p.path.rstrip('/')}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.fullmatch(k)])
    return p._replace(query=query, fragment="").geturl()


def _ats_posting(url: str) -> bool:
    """A link to one posting on a supported board (not to the whole board)."""
    found = sources.detect(url)
    if not found:
        return False
    if found[0] == "workday":
        return "/job/" in urlparse(url).path
    return bool(sources._posting_id(found[0], url))  # the board's own reading of its links


_JOB_PATH = re.compile(r"/(?:jobs?|careers?|positions?|openings?|vacanc\w*|job-listing|job-detail\w*)(?:/|$|[-_])",
                       re.I)


def job_link(url: str) -> tuple[str, str] | None:
    """(site, clean link) for a link to one job: linkedin, indeed, builtin, ats (a supported board) or other;
    None for anything else (a search page, settings, unsubscribe)."""
    if not url or not re.match(r"https?://", url.strip(), re.I):
        return None
    clean = clean_link(url)
    p = urlparse(clean)
    host = p.netloc.lower().removeprefix("www.")
    if linkedin.job_id(clean):
        return "linkedin", clean
    if host.endswith("indeed.com"):
        return ("indeed", clean) if p.path == "/viewjob" else None
    if host == "builtin.com":
        return ("builtin", clean) if re.fullmatch(r"/job/[^/]+/\d+", p.path) else None
    if _ats_posting(clean):
        return "ats", clean
    if _JOB_PATH.search(p.path) and not re.search(r"search|alert|unsubscribe|preferences|settings", clean, re.I):
        return "other", clean
    return None


# -- Emails: one message, or many, from files, stdin, or strings.

_HEADERS = re.compile(rb"(?im)^(?:from|subject|received|return-path|mime-version|delivered-to|date|message-id|"
                      rb"content-type|to):")


def message(raw: str | bytes) -> EmailMessage:
    """An email from its raw RFC822 text, or from just its body (HTML or plain text) when that's all there is."""
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    head = data.lstrip()[:8000]
    if re.match(rb"[!-9;-~]+:", head) and _HEADERS.search(head.split(b"\r\n\r\n")[0].split(b"\n\n")[0]):
        return email.message_from_bytes(data.lstrip(), policy=default_policy)
    text = _decode(data)
    msg = EmailMessage()
    is_html = re.search(r"<(?:html|body|table|div|a|p)\b", text, re.I)
    msg.set_content(text, subtype="html" if is_html else "plain")
    return msg


def _split_mbox(data: bytes) -> list[bytes]:
    """The messages in an mbox file: each starts with a "From " line."""
    parts = re.split(rb"(?:^|\r?\n)From [^\n]*\n", data)
    return [re.sub(rb"(?m)^>(>*From )", rb"\1", p) for p in parts if p.strip()]


def _from_bytes(data: bytes) -> list[EmailMessage]:
    if data.startswith(b"From "):
        return [message(p) for p in _split_mbox(data)]
    return [message(data)] if data.strip() else []


MAIL_FILES = (".eml", ".mbox", ".msg", ".html", ".htm", ".txt")


def read(paths: list[str], stdin=None) -> list[EmailMessage]:
    """Emails from files (.eml, .mbox, or a saved body), folders of them (searched all the way down) and "-"
    (stdin: one message or an mbox)."""
    out: list[EmailMessage] = []
    for p in paths:
        if p == "-":
            data = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read()
            out += _from_bytes(data.encode("utf-8") if isinstance(data, str) else data)
            continue
        path = Path(p).expanduser()
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and f.suffix.lower() in MAIL_FILES:
                    out += _from_bytes(f.read_bytes())
        elif path.is_file():
            out += _from_bytes(path.read_bytes())
        else:
            raise AlertError(f"no such file or folder: {p}")
    return out


def _decode(data: bytes) -> str:
    """Text whose charset nobody named: UTF-8, else Latin-1 (which reads any bytes)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def bodies(msg: EmailMessage) -> tuple[str, str]:
    """(HTML body, plain-text body): the first of each, attachments aside. A part that names no charset is read
    as UTF-8, not ASCII, so its em dashes and accents come through."""
    found = {"text/html": "", "text/plain": ""}
    for part in msg.walk():
        ct = part.get_content_type()
        if part.is_multipart() or ct not in found or found[ct] or part.get_content_disposition() == "attachment":
            continue
        try:
            if part.get_param("charset") is None:
                raise LookupError("no charset")
            found[ct] = part.get_content()
        except (LookupError, ValueError, AttributeError):
            found[ct] = _decode(part.get_payload(decode=True) or b"")
    return found["text/html"], found["text/plain"]


# -- Cards: each job in an email, as its link and the lines of text that go with it.

@dataclass
class Card:
    site: str
    link: str
    lines: list[str]


_BLOCK = frozenset({"p", "div", "br", "tr", "td", "th", "li", "ul", "ol", "table", "section", "article", "h1", "h2",
                    "h3", "h4", "h5", "h6"})
_HIDDEN = frozenset({"style", "script", "head", "title"})


class _Lines(HTMLParser):
    """An email's HTML as lines of text, each with the link it's in (if any)."""
    BLOCK = _BLOCK
    HIDDEN = _HIDDEN

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.text: list[str] = []
        self.hidden = 0

    def _flush(self):
        text = " ".join("".join(self.text).replace("͏", " ").replace("\xa0", " ").split())
        if text:
            self.lines.append((text, self.links[-1] if self.links else ""))
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
        elif tag == "a":
            self._flush()
            self.links.append(dict(attrs).get("href") or "")
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif tag == "a":
            self._flush()
            if self.links:
                self.links.pop()
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def html_cards(markup: str) -> list[Card]:
    """Jobs in an email's HTML: a link to a job starts a card; the lines in that link, and the lines without a
    link after it, are the card's (Indeed puts the company and place after the title's link)."""
    parser = _Lines()
    parser.feed(markup)
    parser.close()
    parser._flush()
    cards: list[Card] = []
    current: Card | None = None
    for text, href in parser.lines:
        found = job_link(href) if href else None
        if found:
            if not (current and current.link == found[1]):
                current = Card(found[0], found[1], [])
                cards.append(current)
            current.lines.append(text)
        elif href:
            current = None  # a link somewhere else ends the card
        elif current:
            current.lines.append(text)
    return _unique(cards)


_URL = re.compile(r"https?://[^\s<>\"']+")
_RULE = re.compile(r"^\s*[-=_*]{5,}\s*$")


def text_cards(text: str) -> list[Card]:
    """Jobs in a plain-text email: each job's lines come before its link ("View job: https://..."). They're the
    last paragraph of two lines or more since the link before (a heading or a note about the job aside)."""
    cards: list[Card] = []
    since: list[str] = []
    for line in text.splitlines():
        urls = _URL.findall(line)
        if not urls:
            since.append("" if _RULE.match(line) else line.strip())
            continue
        found = next(((u, f) for u in urls if (f := job_link(u))), None)
        if found:
            url, found = found
            if found[0] == "builtin" and (lines := _builtin_line(line[:line.find(url)], found[1])):
                cards.append(Card(found[0], found[1], lines))
                since = []
                continue
            paragraphs, para = [], []
            for s in [*since, ""]:
                if s:
                    para.append(s)
                elif para:
                    paragraphs.append(para)
                    para = []
            lines = next((p for p in reversed(paragraphs) if len(p) >= 2), paragraphs[-1] if paragraphs else [])
            if lines:
                cards.append(Card(found[0], found[1], lines))
        since = []
    return _unique(cards)


_WORKED_FROM = re.compile(r"(In[ -]Office|Remote|Hybrid|On-?site)\b\s*", re.I)
_PAY_END = re.compile(r"\$\s?[\d,.]+\s*[kK]?(?:\s*(?:-|–|—|to)\s*\$?\s?[\d,.]+\s*[kK]?)?"
                      r"(?:\s*(?:/|per\s+|an?\s+)[a-z]+)?\s*$", re.I)


def _builtin_line(before: str, link: str) -> list[str] | None:
    """A Built In job squashed onto one line of plain text, before its link: "Acme Staff Engineer (Python)
    Remote United States $200,000-$220,000". The title is the link's (/job/<title>/<id>): what comes before it
    is the company, and what follows is where it's worked from, the place and the pay. None when the title
    isn't there."""
    text = re.sub(r"^[\s|]+|[\s\[\]()<|]+$", "", before)
    words = [w for w in urlparse(link).path.split("/")[2].split("-") if w]
    m = re.search(r"\b" + r"[^a-z0-9]+".join(map(re.escape, words)) + r"\b\)?", text, re.I) if words else None
    if not m or not text[:m.start()].strip():
        return None
    lines, rest = [text[:m.start()].strip(), m.group(0)], text[m.end():].strip()
    if how := _WORKED_FROM.match(rest):
        lines.append(how.group(1))
        rest = rest[how.end():]
    pay = _PAY_END.search(rest)
    tail = (rest[:pay.start()], pay.group(0)) if pay else (rest, "")
    return [*lines, *(x.strip() for x in tail if x.strip())]


def _unique(cards: list[Card]) -> list[Card]:
    seen, out = set(), []
    for c in cards:
        c.lines = [x for x in c.lines if x]
        if c.lines and c.link not in seen:
            seen.add(c.link)
            out.append(c)
    return out


# -- What each sender's cards say.

@dataclass
class Alert:
    title: str
    company: str
    location: str = ""
    pay: str = ""
    url: str = ""
    site: str = ""     # the link's site: linkedin, indeed, builtin, ats (a supported board) or other
    via: str = ""      # where it was found: linkedin-alert, builtin-alert, indeed-alert, <site>-alert


_PAY = re.compile(r"\$\s?\d")
_PLACE = re.compile(r",\s*[A-Z]{2}\b|\b(?:remote|hybrid|on-?site|united states|usa|anywhere)\b", re.I)
_BUTTON = re.compile(r"^(?:view|apply|see|more|details|easy apply|learn more)\b", re.I)


_NOT_PAY = re.compile(r"\$\s?[\d,.]+\s*(?:[MB]\b|million|billion)", re.I)


def _pay(lines: list[str]) -> str:
    """The card's pay: a line that reads as a salary or a rate ("$150K - $190K", "$75 an hour"), or a short
    line with an amount ("Up to $200,000 a year"), not a sentence that mentions money ("$100M+ in energy
    savings")."""
    return next((x for x in lines[:8] if _PAY.search(x) and not _NOT_PAY.search(x)
                 and (parse_salary(x.replace("/yr", "")) or len(x) <= 60)), "")


def _split_company(line: str, seps=(" · ", " • ", " | ", " - ", " – ")) -> tuple[str, str]:
    """ "Acme - Austin, TX" -> ("Acme", "Austin, TX"): split where what follows reads as a place, else at the
    last separator. ("", "") when there's none."""
    for sep in seps:
        if sep not in line:
            continue
        pieces = line.split(sep)
        for i in range(1, len(pieces)):
            if _PLACE.search(sep.join(pieces[i:])):
                return sep.join(pieces[:i]).strip(), sep.join(pieces[i:]).strip()
        return sep.join(pieces[:-1]).strip(), pieces[-1].strip()
    return "", ""


def parse_linkedin(card: Card) -> Alert | None:
    """LinkedIn: the title, then "Company · Place" (HTML) or the company and the place on lines of their own
    (plain text); pay on a line of its own when listed."""
    title, rest = card.lines[0], card.lines[1:]
    company, place = _split_company(rest[0], (" · ", " • ")) if rest else ("", "")
    if not company and rest:
        company = rest[0]
        place = rest[1] if len(rest) > 1 and _PLACE.search(rest[1]) else ""
    return Alert(title, company, place, _pay(rest).replace("/yr", ""), card.link, card.site)


_WORKPLACE = {"remote": "Remote", "hybrid": "Hybrid", "in office": "", "in-office": "", "on-site": "", "onsite": ""}


def parse_builtin(card: Card) -> Alert | None:
    """Built In: the company, the title, then where it's worked from (Remote, Hybrid, In Office), the place and
    the pay."""
    if len(card.lines) < 2:
        return None
    company, title, rest = card.lines[0], card.lines[1], card.lines[2:]
    how = next((x for x in rest if x.lower() in _WORKPLACE), "")
    place = next((x for x in rest if x != how and not _PAY.search(x) and not _BUTTON.match(x)), "")
    if _WORKPLACE.get(how.lower()) == "Remote":
        place = f"Remote - {place}" if place else "Remote"
    elif _WORKPLACE.get(how.lower()) == "Hybrid" and place:
        place = f"{place} (Hybrid)"
    return Alert(title, company, place, _pay(rest), card.link, card.site)


def parse_indeed(card: Card) -> Alert | None:
    """Indeed: the title, then the company and the place on lines of their own (HTML) or as "Company - Place"
    (plain text), then the pay when listed."""
    title, rest = card.lines[0], card.lines[1:]
    if not rest:
        return None
    company, place = _split_company(rest[0], (" - ", " – "))
    if not company:
        company = rest[0]
        place = rest[1] if len(rest) > 1 and len(rest[1]) < 80 and not (_PAY.search(rest[1])
                                                                         or _NOTE.search(rest[1])) else ""
    return Alert(title, company, place, _pay(rest), card.link, card.site)


_NOTE = re.compile(r"\bago\b|just posted|easily apply|urgently hiring|responsive employer|\bnew\b", re.I)


def parse_generic(card: Card) -> Alert | None:
    """Any other sender: the link's text is the title (or the next line, when the link is a button), then
    "Company · Place" or the company and the place on lines of their own."""
    lines = [x for x in card.lines if not _BUTTON.match(x)] or card.lines
    title, rest = lines[0], lines[1:]
    company, place = _split_company(rest[0]) if rest else ("", "")
    if not company and rest:
        company = rest[0] if not _PAY.search(rest[0]) else ""
        place = rest[1] if len(rest) > 1 and _PLACE.search(rest[1]) else ""
    if not company and (board := sources.detect(card.link)):
        company = board[1].partition(".")[0].partition("/")[0]
    if not company:
        return None
    return Alert(title, company, place, _pay(rest), card.link, card.site)


PARSERS = {  # sender's domain -> (via, parser)
    "linkedin.com": ("linkedin-alert", parse_linkedin),
    "builtin.com": ("builtin-alert", parse_builtin),
    "indeed.com": ("indeed-alert", parse_indeed),
}
SITE_DOMAIN = {"linkedin": "linkedin.com", "builtin": "builtin.com", "indeed": "indeed.com"}


def sender(msg: EmailMessage) -> str:
    return parseaddr(str(msg.get("From") or ""))[1].lower()


def _parser_for(domain: str, cards: list[Card]):
    """The sender's parser; for an email without one (just a body, or forwarded), the parser of the site most
    of its job links are on."""
    for d, (via, parse) in PARSERS.items():
        if domain == d or domain.endswith("." + d):
            return via, parse
    sites = [c.site for c in cards if c.site in SITE_DOMAIN]
    if not domain and sites:
        return PARSERS[SITE_DOMAIN[max(set(sites), key=sites.count)]]
    name = domain.rsplit(".", 2)[-2] if domain.count(".") >= 1 else ""
    return (f"{name}-alert" if name else "email-alert"), parse_generic


def parse(msg: EmailMessage) -> list[Alert]:
    """The jobs in one alert email, with clean links."""
    markup, text = bodies(msg)
    cards = html_cards(markup) if markup else []
    if not cards and text:
        cards = text_cards(text)
    domain = sender(msg).rpartition("@")[2]
    via, parse_card = _parser_for(domain, cards)
    out = []
    for card in cards:
        a = parse_card(card)
        if a and a.title and a.company and not _BUTTON.match(a.title):
            a.title, a.company, a.via = " ".join(a.title.split()), " ".join(a.company.split()), via
            out.append(a)
    return out


# -- robots.txt: may jobwatch read this page?

def robots_rules(text: str, agent: str = "jobwatch") -> list[tuple[bool, str]]:
    """The (allow, path pattern) rules robots.txt gives a crawler: the group naming jobwatch if there is one,
    else the group for every crawler (User-agent: *)."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    current, agents_line = None, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        name, sep, value = line.partition(":")
        if not sep:
            continue
        name, value = name.strip().lower(), value.strip()
        if name == "user-agent":
            if not (current and agents_line):
                current = ([], [])
                groups.append(current)
            current[0].append(value.lower())
            agents_line = True
            continue
        agents_line = False
        if name in ("allow", "disallow") and current is not None:
            current[1].append((name == "allow", value))
    mine = [r for agents, rules in groups if agent in agents for r in rules]
    return mine or [r for agents, rules in groups if "*" in agents for r in rules]


def _matches(pattern: str, path: str) -> bool:
    end = pattern.endswith("$")
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
    return re.match(rx + ("$" if end else ""), path) is not None


def robots_allows(rules: list[tuple[bool, str]], url: str) -> bool:
    """Whether the rules allow a link: the longest matching pattern decides, Allow on a tie (RFC 9309)."""
    p = urlparse(url)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    best: tuple[int, bool] | None = None
    for allow, pattern in rules:
        if pattern and _matches(pattern, path) and (best is None or len(pattern) > best[0]
                                                    or (len(pattern) == best[0] and allow)):
            best = (len(pattern), allow)
    return best is None or best[1]


class Robots:
    """Each site's robots.txt, read once. No robots.txt (404) allows everything; one that can't be read (an
    error, a refusal) allows nothing."""

    def __init__(self, page=None):
        self.page = page
        self.sites: dict[str, list[tuple[bool, str]] | None] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        site = f"{p.scheme}://{p.netloc}"
        if site not in self.sites:
            try:
                self.sites[site] = robots_rules((self.page or sources.get_text)(f"{site}/robots.txt") or "")
            except sources.NotFound:
                self.sites[site] = []
            except sources.SourceError:
                self.sites[site] = None
        rules = self.sites[site]
        return rules is not None and robots_allows(rules, url)


# -- A job site's page: its JobPosting data (schema.org), which most job pages carry for search engines.

job_posting_data = sources.job_posting_data


def _place(loc) -> str:
    address = (loc or {}).get("address") if isinstance(loc, dict) else None
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return ""
    return ", ".join(str(address[k]) for k in ("addressLocality", "addressRegion", "addressCountry")
                     if isinstance(address.get(k), str) and address[k])


def _fill(job: Job, data: dict):
    """Fill a job tracked from an email with what the page's JobPosting data says."""
    job.description = html_to_text(str(data.get("description") or "")) or job.description
    org = data.get("hiringOrganization")
    if not job.company_name and isinstance(org, dict) and org.get("name"):
        job.company_name = str(org["name"])
    if not job.locations:
        places = data.get("jobLocation")
        job.locations = split_locations(*(_place(p) for p in (places if isinstance(places, list) else [places])))
    if str(data.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        job.remote = True
    pay = data.get("baseSalary")
    value = pay.get("value") if isinstance(pay, dict) else None
    per = pay_period(value.get("unitText")) if isinstance(value, dict) else None
    if job.salary_min is None and per:  # YEAR, or a rate (HOUR, MONTH) as the year's pay
        low, high = value.get("minValue"), value.get("maxValue") or value.get("minValue")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            job.salary_min, job.salary_max = annual(low, per), annual(high, per)
            job.currency = str(pay.get("currency") or "USD")
    if job.salary_min is None and (found := parse_salary(job.description)):
        job.salary_min, job.salary_max, job.currency = *found, "USD"
    try:
        posted = datetime.fromisoformat(str(data.get("datePosted", ""))[:10])
        job.posted = posted.replace(tzinfo=timezone.utc)
    except ValueError:
        pass


def _board_links(page: str) -> list[str]:
    """Links on a page to one posting on a supported board."""
    found: list[str] = []
    for url in _URL.findall(html.unescape(page).replace("\\/", "/")):
        url = clean_link(url.rstrip(").,;"))
        if _ats_posting(url) and url not in found:
            found.append(url)
    return found


# -- Taking them in.

@dataclass
class Found:
    alert: Alert
    job: Job | None = None
    how: str = ""          # board (on the company's own board), posting (read from its link), page (the job
                           # site's page), email (what the email said)
    result: str = ""       # new, or known (already tracked), or duplicate (twice in these emails)
    reason: str | None = None  # why the filters leave it out of the digest; None: it passes
    notes: list[str] = field(default_factory=list)  # links not read (robots.txt), errors
    same: dupes.Match | None = None  # a new job that's (maybe) the same opening as one acted on

    @property
    def key(self) -> str:
        return self.job.key if self.job else ""


@dataclass
class Intake:
    emails: int = 0
    found: list[Found] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)  # subjects of emails with no jobs found in them
    dry_run: bool = False

    def count(self, **match) -> int:
        return sum(all(getattr(f, k) == v for k, v in match.items()) for f in self.found)


def email_job(a: Alert) -> Job:
    """A job from what the alert says, tracked like one added by hand."""
    job = Job(source=MANUAL, company=_slug(a.company), id=_slug(a.title), title=a.title, url=a.url,
              company_name=a.company, locations=split_locations(a.location) if a.location else [])
    if re.search(r"\bremote\b", a.location, re.I):
        job.remote = True
    if found := parse_salary(a.pay):
        job.salary_min, job.salary_max, job.currency = *found, "USD"
    return job


class _Tracked:
    """What the store already has, to tell a job seen before: by link, or by company and title."""

    def __init__(self, store: Store):
        self.links: dict[str, str] = {}
        self.names: dict[str, list[tuple[str, str]]] = {}
        self.jobs: dict[str, Job] = {}
        for job, _ in store.jobs(include_closed=True):
            self.add(job)

    def add(self, job: Job):
        self.jobs[job.key] = job
        if job.url:
            self.links.setdefault(clean_link(job.url), job.key)
        for name in {job.display_company, job.company}:
            self.names.setdefault(linkedin._bare(name.replace("-", " ")), []).append((job.title, job.key))

    def match(self, company: str, title: str, url: str = "") -> str | None:
        if url and (key := self.links.get(clean_link(url))):
            return key
        return next((k for t, k in self.names.get(linkedin._bare(company), []) if linkedin.same_words(t, title)),
                    None)


LABELS = {"linkedin-alert": "LinkedIn", "builtin-alert": "Built In", "indeed-alert": "Indeed"}


class _Resolver:
    """Finds each alert's job where the application goes, reading as little as it can: robots.txt first for
    any job site's page, each company's boards looked for once."""

    def __init__(self, boards, page=None):
        self.boards = boards
        self.page = page
        self.robots = Robots(page)
        self.found_boards: dict[str, list[tuple[str, str, str]]] = {}

    def company_boards(self, company: str) -> list[tuple[str, str, str]]:
        """The company's boards: watched ones under its name, else the ones found by looking (once a run)."""
        key = linkedin._bare(company)
        if key not in self.found_boards:
            hits = [(b.source, b.board, company) for b in self.boards
                    if linkedin.same_company(b.name or b.board, company) or linkedin.same_company(b.board, company)]
            for name in linkedin.company_names(company) if not hits else []:
                hits = [(s, b, company) for s, b, _ in sources.probe(name, None, self.page)]
                if hits:
                    break
            self.found_boards[key] = hits
        return self.found_boards[key]

    def on_board(self, title: str, company: str, location: str, description: str = "") -> Job | None:
        boards = self.company_boards(company)
        if not boards:
            return None
        p = linkedin.Posting(id="", title=title, company=company, location=location, description=description)
        job = linkedin.on_board(p, boards, None, self.page)
        if job and sources.SOURCES[job.source].search:  # a searched board names only its tenant ("acme")
            job.company_name = company
        return job

    def resolve(self, f: Found):
        a, job = f.alert, f.job
        if a.site == "ats":
            try:
                if posted := sources.posting(a.url):
                    f.job, f.how = posted, "posting"
                    posted.company_name = posted.company_name or a.company
                    return
            except sources.SourceError as e:
                f.notes.append(f"couldn't read {a.url}: {e}")
        elif a.site == "linkedin":  # never read: linkedin.com's robots.txt disallows every page
            f.notes.append("linkedin.com's robots.txt doesn't allow reading the posting: the email's details "
                           "are used")
        elif a.url:
            if self.robots.allowed(a.url):
                self._read_page(f)
            else:
                f.notes.append(f"{urlparse(a.url).netloc}'s robots.txt doesn't allow reading {a.url}: the email's "
                               "details are used")
        if f.how == "posting":
            return
        try:
            found = self.on_board(a.title, a.company, a.location, job.description)
        except sources.SourceError as e:
            found = None
            f.notes.append(f"looking for {a.company}'s board: {e}")
        if found:
            f.job, f.how = found, "board"

    def _read_page(self, f: Found):
        try:
            page = (self.page or sources.get_text)(f.alert.url)
        except sources.SourceError as e:
            f.notes.append(f"couldn't read {f.alert.url}: {e}")
            return
        links = _board_links(page)
        if len(links) == 1:  # the page links to the company's own posting: read it from there
            try:
                posted = sources.posting(links[0])
                if posted and linkedin.same_title(posted.title, f.alert.title):
                    f.job, f.how = posted, "posting"
                    posted.company_name = posted.company_name or f.alert.company
                    return
            except sources.SourceError as e:
                f.notes.append(f"couldn't read {links[0]}: {e}")
        if data := job_posting_data(page):
            _fill(f.job, data)
            f.how = "page"


def intake(cfg, store: Store, messages: list[EmailMessage], follow: bool = True, dry_run: bool = False,
           page=None) -> Intake:
    """Track the jobs in these alert emails (see the module's docstring). follow=False reads no links: each job
    is kept as the email has it. dry_run: nothing is recorded, the result says what would be."""
    result = Intake(emails=len(messages), dry_run=dry_run)
    tracked = _Tracked(store)
    acted = dupes.Index(store)
    resolver = _Resolver(cfg.boards, page)
    seen: dict[str, Found] = {}
    for msg in messages:
        alerts = parse(msg)
        if not alerts:
            result.empty.append(str(msg.get("Subject") or "(no subject)"))
        for a in alerts:
            f = Found(a, email_job(a), how="email")
            result.found.append(f)
            same = f"{linkedin._bare(a.company)}|{' '.join(sorted(linkedin._words(a.title)))}"
            if twin := seen.get(a.url) or seen.get(same):  # a job in two alerts (LinkedIn's and Indeed's)
                f.job, f.how, f.result, f.reason = twin.job, twin.how, "duplicate", twin.reason
                continue
            seen[a.url] = seen[same] = f
            known = tracked.match(a.company, a.title, a.url)
            if not known:
                f.reason = reject_reason(f.job, cfg.filters)
                if follow and f.reason is None:  # only jobs worth a look are followed; the rest stay as emailed
                    resolver.resolve(f)
                    f.reason = reject_reason(f.job, cfg.filters)
                # The same job, already tracked from its board (or from another alert, under another name)
                known = (f.job.key if store.has(f.job.key) else None) or (
                    f.how in ("board", "posting") and tracked.match(f.job.display_company, f.job.title, f.job.url))
            if known:
                f.result, f.job = "known", tracked.jobs.get(known) or store.find(known)[0]
                f.reason = reject_reason(f.job, cfg.filters)
                continue
            f.result = "new"
            f.same = acted.match(f.job)
            if not dry_run:
                _record(store, f)
            tracked.add(f.job)
    return result


def _record(store: Store, f: Found):
    store.keep(f.job)
    store.set_via(f.job.key, f.alert.via)
    if f.same and f.same.strong:
        store.set_duplicate(f.job.key, f.same.other.key)
    if f.how in ("board", "posting") and f.alert.url and f.alert.url != f.job.url:
        label = LABELS.get(f.alert.via, f.alert.via.removesuffix("-alert"))
        store.add_note(f.job.key, f"From a {label} job alert: {f.alert.url}")


HOW = {"board": "found on the company's board", "posting": "read from the posting's link",
       "page": "read from the job site's page", "email": "from the email"}


def summary(r: Intake, every: bool = False) -> str:
    """What came in: counts, then a line per new job that passes the filters (every new job with every=True)."""
    new = [f for f in r.found if f.result == "new"]
    passing = [f for f in new if f.reason is None]
    head = (f"{'Dry run: nothing recorded. ' if r.dry_run else ''}Read {r.emails} email(s): {len(r.found)} job(s), "
            f"{r.count(result='known')} already tracked, {r.count(result='duplicate')} repeated, {len(new)} new.")
    hows = ", ".join(f"{sum(f.how == h for f in new)} {HOW[h]}" for h in HOW if any(f.how == h for f in new))
    out = [head]
    if new:
        out.append(f"New: {hows}. {len(passing)} pass your filters" + (" and are in the digest." if not r.dry_run
                                                                       else "."))
    for f in (new if every else passing):
        j = f.job
        mark = "" if f.reason is None else f"  [filtered: {f.reason}]"
        out.append(f"  {j.key}  {j.display_company}: {j.title}  ({HOW[f.how]}; via {f.alert.via}){mark}")
        if f.same:
            out.append(f"    {f.same.line}")
    if r.empty:
        out.append(f"No jobs found in {len(r.empty)} email(s): " + "; ".join(r.empty[:5])
                   + (" ..." if len(r.empty) > 5 else ""))
    return "\n".join(out)


def to_dict(r: Intake) -> dict:
    return {
        "dry_run": r.dry_run, "emails": r.emails, "jobs": len(r.found),
        "known": r.count(result="known"), "repeated": r.count(result="duplicate"), "new": r.count(result="new"),
        "new_passing_filters": sum(f.result == "new" and f.reason is None for f in r.found),
        "found": [{"key": f.key, "result": f.result, "how": f.how, "via": f.alert.via, "company": f.alert.company,
                   "title": f.alert.title, "location": f.alert.location, "pay": f.alert.pay, "link": f.alert.url,
                   "tracked_link": f.job.url if f.job else "", "filtered": f.reason, "notes": f.notes,
                   "duplicate_of": f.same.to_dict() if f.same else None}
                  for f in r.found],
        "no_jobs_in": r.empty,
    }


# -- Optional: read alert emails straight from a mailbox over IMAP (alerts.imap in the watchlist).

def imap_password(settings) -> str:
    """The mailbox password, from the environment variable named in password_env or the macOS keychain item named
    in keychain. Never stored, printed or logged by jobwatch."""
    if settings.password_env and os.environ.get(settings.password_env):
        return os.environ[settings.password_env]
    if settings.keychain:
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", settings.keychain, "-a", settings.user,
                                "-w"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            r = None
        if r is not None and r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip("\n")
        raise AlertError(f"no password in the keychain item {settings.keychain!r} for {settings.user}: add one "
                         f"with `security add-generic-password -s {settings.keychain} -a {settings.user} -w`")
    raise AlertError(f"set the environment variable {settings.password_env} to the mailbox's password (an app "
                     "password, for Gmail), or name a keychain item in alerts.imap.keychain")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_messages(settings, today: date | None = None, connect=None) -> list[EmailMessage]:
    """The alert emails from the last `days` days in the folder, from the configured senders. The folder is
    opened read-only and messages are fetched with BODY.PEEK, so nothing is marked read, moved or deleted."""
    day = (today or date.today()) - timedelta(days=settings.days)
    since = f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"
    password = imap_password(settings)
    try:
        conn = (connect or imaplib.IMAP4_SSL)(settings.host, settings.port, ssl_context=ssl.create_default_context())
    except (OSError, imaplib.IMAP4.error) as e:
        raise AlertError(f"couldn't reach {settings.host}:{settings.port}: {e}") from None
    try:
        try:
            conn.login(settings.user, password)
        except imaplib.IMAP4.error:
            raise AlertError(f"{settings.host} didn't accept the login for {settings.user}") from None
        status, _ = conn.select(f'"{settings.folder}"', readonly=True)
        if status != "OK":
            raise AlertError(f"no folder {settings.folder!r} on {settings.host}")
        ids: list[bytes] = []
        for who in settings.senders:
            status, data = conn.search(None, "SINCE", since, "FROM", f'"{who}"')
            ids += [i for i in (data[0] or b"").split() if i not in ids] if status == "OK" else []
        out = []
        for i in ids:
            status, data = conn.fetch(i, "(BODY.PEEK[])")
            raw = next((part[1] for part in data or [] if isinstance(part, tuple)), None)
            if status == "OK" and raw:
                out.append(message(raw))
        return out
    finally:
        try:
            conn.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
