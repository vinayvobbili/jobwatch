"""The same opening tracked twice: an application added by hand, and the same job back months later from a
job-alert email under another title ("Senior ..." and an em dash instead of "- ... (482913)"). Applying again, or
asking someone for a referral to a job already applied to, is what this is here to stop.

Jobs are compared with the ones the person acted on: queued, applied (or a later stage) and skipped, closed ones
too. Two jobs at the same company (case, punctuation and suffixes such as Inc or Investments aside) match in one
of two ways:

- **The same opening** (strong): they share a requisition or posting id. That's a board's posting id, a req in the
  title, note or posting text ("(482913)", "R-0123456", "JR12345", "req 4711", "Job ID: 20769"), or the id in a
  known link, in the job's link or its note (Workday's ..._R0123456, an Avature .../JobDetail/<title>/<id>,
  Greenhouse, Lever, Ashby, SmartRecruiters...). When a note says the job was reposted as the other's id, it's a
  repost: an application may or may not carry over. Two jobs each posted under its own req, different ones,
  aren't matched by a note on one naming the other's req: that's a note about a second opening ("asked whether
  the application carries over to R0822345"). A strong match is recorded on the new job (duplicate_of).
- **Possibly the same** (title only): the same title once case, dashes, punctuation, a req or where the job is done
  ("(Remote)") at the end, and seniority words are set aside ("Senior Data Platform Engineer — Payments" and
  "Data Platform Engineer - Payments (482913)"). A softer warning: a board can post one title many times, one
  per opening. Even so, a title counts only when it
  has at least two words left (not just "Engineer"), the seniority doesn't conflict ("Senior" and "Staff" are two
  openings; "Senior" and none may be one), the two don't name different reqs, and they aren't two postings on one
  board (the board itself lists them apart).

Nothing is hidden for a match: it's better to flag a posting as a possible duplicate than to hide it. Each one
shows with a label ("Already applied 2026-02-11", "Reposted: you applied 2026-03-02 (old req ...)", "Possible
duplicate of your 2026-03-02 application: check it's a different opening") on Today, in the queue, `show`,
get_job and `jobwatch dupes`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import linkedin, sources
from .models import Job
from .store import MANUAL, STAGES, Store

ACTED = ("queued", *STAGES, "skipped")
SAME_TITLE = "same title"  # why a title-only match matched: possibly the same opening

# Words after a company's name that don't change which company it is: "Fidelity Investments", "Initech, Inc.".
_COMPANY_SUFFIXES = {"inc", "incorporated", "llc", "llp", "lp", "ltd", "limited", "corp", "corporation", "co",
                     "company", "plc", "gmbh", "ag", "sa", "nv", "bv", "group", "holdings", "holding",
                     "technologies", "technology", "labs", "investments", "international"}

# Boards whose name is the company's own short name (greenhouse:acme); a Workday or Oracle board names a tenant.
_NAMED_BOARDS = {"greenhouse", "lever", "ashby", "workable", "rippling", "smartrecruiters", "google", "amazon", MANUAL}

# Boards whose posting id is the company's requisition number, so it can conflict with a req given elsewhere.
_REQ_BOARDS = {"workday", "oracle", "avature", "amazon"}

_SENIORITY = {"senior": "senior", "sr": "senior", "snr": "senior", "staff": "staff", "lead": "lead",
              "principal": "principal", "junior": "junior", "jr": "junior", "i": "i", "ii": "ii", "iii": "iii",
              "iv": "iv"}

_DASHES = re.compile(r"[‐‑‒–—―−]")
# A req at the end of a title, in brackets or after a dash: "(482913)", "[R-0123456]", "- Req 4711".
_REQ_WORD = r"(?:req(?:uisition)?\.?\s*(?:id)?\s*[#:]?\s*)?"
_TITLE_REQ = re.compile(rf"\s*(?:[(\[]\s*{_REQ_WORD}[a-z]{{0,4}}[-_ ]?\d{{4,}}(?:-\d{{1,2}})?\s*[)\]]"
                        rf"|[-|,]\s*{_REQ_WORD}[a-z]{{0,4}}-?\d{{5,}})\s*$", re.I)
# Reqs given in words: "req 482913", "Requisition ID: R0123456", "Job ID: 20769", "Job #4711".
_NAMED_REQ = re.compile(r"\b(?:req(?:uisition)?\.?(?:\s*(?:id|#|number|no\.?))?|job\s*(?:id|#|number|no\.?))"
                        r"\s*[:#-]?\s*([a-z]{0,4}[-_]?\d{4,}(?:-\d{1,2})?)\b", re.I)
# Reqs by their shape alone, in capitals: R-0123456, JR12345, REQ-4711, WD00203344.
_SHAPED_REQ = re.compile(r"(?<![A-Za-z0-9])((?:R|JR|REQ|WD)-?\d{4,}(?:-\d{1,2})?)(?![A-Za-z0-9])")
# Where the job is done, at the end of a title: "(Remote)", "(Hybrid - Austin)", ", Remote US", "- On-site".
_TITLE_WORKPLACE = re.compile(r"\s*(?:[(\[][^()\[\]]*\b(?:remote|hybrid|on-?site|in-office|wfh)\b[^()\[\]]*[)\]]"
                              r"|[-|,]\s*(?:fully\s+)?(?:remote|hybrid|on-?site)\b[^-|,()\[\]]*)\s*$", re.I)
# A bracketed number in a title: "(482913)", "(R0123456)"; a year in brackets "(2026)" is too short to count.
_BRACKETED_REQ = re.compile(r"[(\[]\s*([a-z]{0,4}-?\d{5,}(?:-\d{1,2})?|[a-z]{1,4}-?\d{4})\s*[)\]]", re.I)
# An Avature posting named in a note, as a link or not: "jobs.acme.com JobDetail/Solutions-Engineer/61542".
_DETAIL_ID = re.compile(r"JobDetail(?:/[^/\s?#]+)?/(\d{4,})\b|JobDetail\?jobId=(\d{4,})", re.I)
# A link, with or without its https://: "jobs.lever.co/acme/1b2c...".
_URL = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}/[^\s<>\"')]+", re.I)
_REPOSTED = re.compile(r"\bre-?post(?:ed|ing)?\b", re.I)


def company_key(name: str) -> str:
    """A company's name with case, punctuation and suffixes set aside: "Fidelity Investments" and "fidelity",
    "Initech, Inc." and "initech". Names that are really different ("Hewlett Packard Enterprise", "hpe") stay
    different."""
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    if words[:1] == ["the"] and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return "".join(words)


def companies(job: Job) -> set[str]:
    """The names a job's company goes by: its display name, and its board's name when that's the company's."""
    names = {company_key(job.display_company)}
    if job.source in _NAMED_BOARDS:
        names.add(company_key(job.company.replace("-", " ")))
    return {n for n in names if n}


def title_key(title: str) -> tuple[str, frozenset[str]]:
    """(the title's words, its seniority words): lowercase, every dash and punctuation mark alike, a req and where
    the job is done ("(Remote)", "(Hybrid)") at the end dropped, seniority words (senior, staff, lead, principal,
    junior, I-IV) set apart."""
    t = _DASHES.sub("-", title.lower()).replace("&", " and ")
    while (stripped := _TITLE_WORKPLACE.sub("", _TITLE_REQ.sub("", t))) != t:
        t = stripped
    words = re.findall(r"[a-z0-9+#]+", t)
    return " ".join(w for w in words if w not in _SENIORITY), frozenset(_SENIORITY[w] for w in words if w in _SENIORITY)


def _norm_id(raw: str) -> str:
    """One id however it's written: R0123456, R-0123456, JR123456 and 123456 are "123456" (a posting's copy,
    R0123456-1, too); any other id (a Lever or Ashby uuid) as it is, in lowercase."""
    raw = raw.strip()
    if m := re.fullmatch(r"[A-Za-z]{0,4}[-_ ]?(\d{4,})(?:-\d{1,2})?", raw):
        digits = m.group(1).lstrip("0")
        return digits if len(digits) >= 4 else ""
    return raw.lower()


def _text_reqs(text: str) -> set[str]:
    found = [m.group(1) for m in _NAMED_REQ.finditer(text)] + [m.group(1) for m in _SHAPED_REQ.finditer(text)]
    return {i for i in map(_norm_id, found) if i}


def _link_id(url: str) -> tuple[str, str] | None:
    """(source, id) of the posting a link is to, for a link to one job on a supported board or LinkedIn."""
    if pid := linkedin.job_id(url):
        return "linkedin", f"linkedin:{pid}"
    found = sources.detect(url)
    if not found:
        return None
    source = found[0]
    if source == "workday":  # .../job/<place>/<title>_R0123456
        path = urlparse(url if "//" in url else f"https://{url}").path
        pid = path.rstrip("/").rsplit("_", 1)[-1] if "/job/" in path and "_" in path else None
    else:
        pid = sources._posting_id(source, url)
    return (source, _norm_id(pid)) if pid and _norm_id(pid) else None


@dataclass
class Signature:
    """What two jobs are compared by."""
    job: Job
    companies: set[str]
    title: str
    levels: frozenset[str]
    ids: set[str]       # every id the job goes by: its posting id, reqs, ids in its links and note
    reqs: set[str]      # the ones that are requisition numbers, which two different openings can't share
    note_ids: set[str]  # the ones only its note names (another posting it's related to, say)
    reposted_as: set[str]  # the ones its note says it was reposted as ("Reposted as WD00207765 (...)")

    @property
    def reposted(self) -> bool:
        return bool(self.reposted_as)

    @classmethod
    def of(cls, job: Job, note: str | None = "") -> Signature:
        title, levels = title_key(job.title)
        note = note or ""
        ids: set[str] = set()
        reqs = _text_reqs(f"{job.title} {job.description}")
        reqs |= {i for i in map(_norm_id, (m.group(1) for m in _BRACKETED_REQ.finditer(job.title))) if i}
        if job.source != MANUAL and (pid := _norm_id(job.id)):
            ids.add(pid)
            if job.source in _REQ_BOARDS:
                reqs.add(pid)
        if job.url and (found := _link_id(job.url)):
            ids.add(found[1])
            if found[0] in _REQ_BOARDS:
                reqs.add(found[1])
        own = ids | reqs
        manual = job.source == MANUAL
        note_ids, note_reqs = _named(note, manual)
        # What a "reposted" names, up to the end of its sentence: "Reposted 2026-03-20 as WD00207765 (...)."
        reposted_as = {i for m in _REPOSTED.finditer(note)
                       for i in _named(re.split(r"[.;](?:\s|$)|\n", note[m.end():], maxsplit=1)[0], manual)[0]}
        return cls(job, companies(job), title, levels, own | note_ids, reqs | note_reqs, note_ids - own,
                   reposted_as)

    @property
    def own_reqs(self) -> set[str]:
        """The reqs the posting itself shows (not the ones its note names, which a repost changes)."""
        return self.reqs - self.note_ids

    @property
    def own_ids(self) -> set[str]:
        """The ids the posting itself goes by (its link, posting id and reqs), not the ones its note names."""
        return self.ids - self.note_ids


def _named(text: str, manual: bool) -> tuple[set[str], set[str]]:
    """The ids a note names, and the ones of them that are reqs: reqs in words, Avature postings, and (for a job
    added by hand) the real posting's link."""
    reqs = _text_reqs(text) | ({_norm_id(a or b) for a, b in _DETAIL_ID.findall(text)} - {""})
    ids = set(reqs)
    for url in _URL.findall(text) if manual else []:
        if found := _link_id(url):
            ids.add(found[1])
            if found[0] in _REQ_BOARDS:
                reqs.add(found[1])
    return ids, reqs


def same_opening(a: Signature, b: Signature) -> str | None:
    """Why two jobs are the same opening ("same req 482913", "reposted as req 61542", "same title"), or None when
    they aren't. "reposted": one's note says it was reposted as an id the other posting goes by."""
    if a.job.key == b.job.key or not (a.companies & b.companies):
        return None
    if shared := a.ids & b.ids:
        if again := sorted((a.reposted_as & b.own_ids) | (b.reposted_as & a.own_ids)):
            return f"reposted as req {again[0]}"
        if a.own_reqs and b.own_reqs and not a.own_reqs & b.own_reqs:
            return None  # each posted under its own req: a note naming the other's is about a second opening
        first = sorted(shared)[0]
        return f"same req {first}" if shared & (a.reqs | b.reqs) else f"same posting id {first}"
    if not a.title or a.title != b.title or len(a.title.split()) < 2:
        return None
    if a.levels and b.levels and a.levels != b.levels:
        return None  # "Senior Engineer" and "Staff Engineer": two openings
    if a.own_reqs and b.own_reqs:
        return None  # different reqs: two openings with one title (a note's reqs may be a repost's)
    if a.job.source == b.job.source != MANUAL and a.job.company == b.job.company:
        return None  # two postings on one board: it lists them apart
    return SAME_TITLE


@dataclass
class Match:
    """A job the person already did something with that another one is (maybe) the same opening as. Nothing is
    hidden for it: the other job is shown with `label` (a badge) and `line` (the warning)."""
    other: Job
    record: dict
    why: str
    old_req: str = ""  # for a repost: the req applied to before, when the old job names just one other

    @property
    def status(self) -> str:
        return self.record["status"]

    @property
    def applied(self) -> bool:
        return self.status in STAGES

    @property
    def day(self) -> str:
        """The day applied for an application, else the day it got its status."""
        return (self.record.get("applied_at") if self.applied else None) or (self.record.get("status_at") or "")[:10]

    @property
    def strong(self) -> bool:
        """Matched by an id: the same opening. A title alone only says it may be (a board can post one title
        many times, one per opening)."""
        return self.why != SAME_TITLE

    @property
    def reposted(self) -> bool:
        """The same opening posted again under a new req: an application may or may not carry over."""
        return self.why.startswith("reposted")

    @property
    def label(self) -> str:
        """A few words for a badge: "Already applied 2026-02-11", "Reposted: you applied 2026-03-02 (old req
        200431)", "Possible duplicate of your 2026-03-02 application: check it's a different opening"."""
        later = f", now {self.status}" if self.applied and self.status != "applied" else ""
        if not self.strong:
            what = {"queued": f"a job you queued {self.day}", "skipped": f"a job you skipped {self.day}"}.get(
                self.status, f"your {self.day} application{later}")
            return f"Possible duplicate of {what}" + (": check it's a different opening"
                                                       if self.status != "skipped" else "")
        if self.applied and self.reposted:
            return f"Reposted: you applied {self.day}{later}" + (f" (old req {self.old_req})" if self.old_req else "")
        if self.applied:
            return f"Already applied {self.day}{later}"
        return f"Already queued {self.day}" if self.status == "queued" else f"Skipped before {self.day}"

    @property
    def line(self) -> str:
        """The warning, in one line: the label, the job it matches and why, and what to do."""
        o = self.other
        if not self.strong:
            head = self.label.removesuffix(": check it's a different opening")
            tail = ": check it's a different opening" if self.status != "skipped" else ""
            return f"{head}, {o.title} ({o.key}; same title){tail}"
        todo = ("check whether that application carries over before applying again" if self.applied and
                self.reposted else "don't apply or ask for a referral again" if self.applied else
                "don't queue it twice" if self.status == "queued" else "you skipped it then")
        return f"{self.label}: same opening as {o.title} ({o.key}; {self.why}). {todo[0].upper()}{todo[1:]}"

    def to_dict(self) -> dict:
        return {"key": self.other.key, "title": self.other.title, "company": self.other.display_company,
                "status": self.status, "date": self.day, "why": self.why, "strong": self.strong,
                "reposted": self.reposted, "label": self.label, "text": self.line}


_RANK = {**{s: 0 for s in STAGES}, "queued": 1, "skipped": 2}


def _order(rec: dict) -> int:
    return _RANK.get(rec["status"], 3)


class Index:
    """The jobs acted on (queued, applied or later, skipped; closed ones too), by company, to check others against.
    Build it once for a batch of jobs."""

    def __init__(self, store: Store):
        self.by_company: dict[str, list[tuple[Signature, dict]]] = {}
        self.records: dict[str, tuple[Signature, dict]] = {}
        for job, rec in store.jobs(ACTED, include_closed=True):
            entry = (Signature.of(job, rec.get("note")), rec)
            self.records[job.key] = entry
            for name in entry[0].companies:
                self.by_company.setdefault(name, []).append(entry)

    def at(self, names: set[str]) -> list[tuple[Signature, dict]]:
        """The jobs acted on at a company that goes by any of these names, each once."""
        return list({sig.job.key: (sig, rec) for n in names for sig, rec in self.by_company.get(n, [])}.values())

    def match(self, job: Job, record: dict | None = None) -> Match | None:
        """The job acted on that this one matches best: the same opening (by an id) before a title alone, then an
        application before a queued job before a skipped one, the latest first. The one recorded when the job
        came in (`duplicate_of`) counts first, while it's still acted on."""
        record = record or {}
        pinned = self.records.get(record.get("duplicate_of") or "")
        others = self.at(companies(job))
        if not (pinned or others):
            return None
        sig = Signature.of(job, record.get("note"))
        if pinned and pinned[0].job.key != job.key:
            why = same_opening(sig, pinned[0])
            why = why if why and why != SAME_TITLE else "matched when it came in"
            return Match(pinned[0].job, pinned[1], why, _old_req(sig, pinned[0], why))
        found = [Match(other.job, rec, why, _old_req(sig, other, why))
                 for other, rec in others if (why := same_opening(sig, other))]
        found.sort(key=lambda m: m.record.get("status_at") or "", reverse=True)
        found.sort(key=lambda m: (not m.strong, _RANK[m.status]))  # stable: the latest first within each
        return found[0] if found else None


def _old_req(new: Signature, old: Signature, why: str) -> str:
    """For a repost, the req applied to before: the one req the old job goes by that's neither the new posting's
    nor one it was reposted as, when there's just one."""
    left = old.reqs - new.ids - old.reposted_as if why.startswith("reposted") else set()
    return next(iter(left)) if len(left) == 1 else ""


def record(store: Store, jobs: list[Job], index: Index | None = None) -> dict[str, Match]:
    """Check jobs that just came in against the ones acted on. The same opening (matched by an id) is recorded on
    the new job (`duplicate_of`); a title alone isn't. Returns every match, possible ones too, by the new job's
    key."""
    index = index or Index(store)
    found = {}
    for job in jobs:
        if m := index.match(job):
            if m.strong:
                store.set_duplicate(job.key, m.other.key)
            found[job.key] = m
    return found


def check(store: Store, key: str, index: Index | None = None) -> Match | None:
    """The job acted on that a tracked job (by key) matches, if any (see Index.match)."""
    job, rec = store.find(key)
    return (index or Index(store)).match(job, rec)


@dataclass
class Pair:
    a: Job          # the one acted on (or acted on further: an application before a queued job)
    a_record: dict
    b: Job
    b_record: dict
    why: str

    @property
    def strong(self) -> bool:
        return self.why != SAME_TITLE


def pairs(store: Store, strong_only: bool = False) -> list[Pair]:
    """Every pair of tracked jobs that match where at least one was acted on (queued, applied or later, skipped),
    open or closed: the same opening first, then the possible ones (same title); applications before queued jobs
    before skipped ones within each. Changes nothing."""
    index = Index(store)
    out: dict[frozenset, Pair] = {}
    for job, rec in store.jobs(include_closed=True):
        if not (names := companies(job)) or not any(n in index.by_company for n in names):
            continue
        sig = Signature.of(job, rec.get("note"))
        for other, orec in index.at(names):
            k = frozenset((job.key, other.job.key))
            if k in out or not (why := same_opening(sig, other)) or (strong_only and why == SAME_TITLE):
                continue
            first, second = ((other.job, orec), (job, rec)) if _order(orec) <= _order(rec) else \
                ((job, rec), (other.job, orec))
            out[k] = Pair(first[0], first[1], second[0], second[1], why)
    return sorted(out.values(), key=lambda p: (not p.strong, _order(p.a_record), _order(p.b_record),
                                               p.a.display_company.lower(), p.a.key, p.b.key))


def day_of(rec: dict) -> str:
    """The day that goes with a job's status: applied for an application, else when it got its status."""
    return (rec.get("applied_at") if rec["status"] in STAGES else None) or \
        (rec.get("status_at") or rec.get("first_seen") or "")[:10]


def pair_dict(p: Pair) -> dict:
    """A pair for find_duplicates: why, whether it's the same opening (strong) or possibly (a title alone), and
    both jobs, the one acted on (or acted on further) first."""
    def side(j: Job, r: dict) -> dict:
        return {"key": j.key, "company": j.display_company, "title": j.title, "status": r["status"],
                "date": day_of(r), "closed": bool(r.get("closed"))}
    return {"why": p.why, "strong": p.strong, "jobs": [side(p.a, p.a_record), side(p.b, p.b_record)]}


def pairs_text(found: list[Pair]) -> str:
    """`jobwatch dupes`: each pair, with both jobs' status, day and key, and why they match."""
    if not found:
        return "No duplicates: no tracked job matches one you queued, applied to or skipped."
    out = []
    for p in found:
        kind = "same opening" if p.strong else "possibly the same opening: check it's a different one"
        out.append(f"{p.a.display_company}: {kind} ({p.why})")
        for j, r in ((p.a, p.a_record), (p.b, p.b_record)):
            closed = " [closed]" if r.get("closed") else ""
            out.append(f"  {r['status']:12} {day_of(r):10}  {j.title}{closed}  `{j.key}`")
    strong = sum(p.strong for p in found)
    out.append(f"\n{strong} the same opening, {len(found) - strong} possibly (same title). Nothing was changed: skip "
               "the one you don't need with `jobwatch mark skipped <key>`.")
    return "\n".join(out)
