"""Status updates from application emails: a confirmation ("Thank you for applying"), a rejection, an interview
invitation or scheduling link, a take-home assignment, an offer, or a recruiter's reply, matched to the application
it's about and proposed as a status change and a dated note. Nothing is applied here: the person (or the assistant
that read their mail, asking them) decides, and `apply` records a confirmed proposal the way mark_job does.

The emails come as import_job_alerts takes them: files, stdin, or raw messages (or just a body) from an assistant's
mail connector. jobwatch never asks for, keeps or logs a mail password, and nothing is read from the network.

Each email is read with the rules in data/inbox.yaml (the ATS senders, and the phrasings of each kind). A kind
goes by the first that matches, in the order the file lists them; sentences that only say what might happen ("if your
background fits, we'll schedule an interview") don't count for an offer, an assessment or an interview.

It's matched to an application (a queued job too: a confirmation says it went out) by the company, as strongly as
the email shows it:

- the sender's domain or display name (3), or an ATS sender's mailbox name (Workday's is the company's);
- how the body names it, "Thank you for applying to Acme Robotics" (2);
- a tracked company's name mentioned anywhere in the text (1; alone it's not enough).

Then by the requisition or posting id in the text or its links (+2), or the job's title in the text (+1). Several
applications at the company and nothing to tell them apart is not a match: it's reported as unmatched, with their
keys. Confidence is high at 4 or more, medium at 3, low below that.

A status only moves forward (queued, applied, screening, interviewing, offer) or ends (rejected): a late
confirmation for an application already interviewing, or any email about one that ended, is a note at most. An
email that adds nothing (the confirmation again, the rejection already recorded) is listed as such. A rejection
clears the next step and follow-up day; an interview, assessment or offer sets a next step when there's none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from functools import cache
from importlib import resources

import yaml

from . import alerts, company, dupes
from .models import Job
from .store import ENDED, STAGES, Store
from .text import html_to_text

# The stages an application moves forward through; rejected and withdrawn end it.
RANK = {"queued": 0, "applied": 1, "screening": 2, "interviewing": 3, "offer": 4}
QUOTED = 90  # characters of a phrase the note quotes
_URL = re.compile(r"https?://[^\s<>\"']+")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Kind:
    name: str
    label: str
    status: str | None
    next_step: str | None
    patterns: list[re.Pattern]
    links: list[str]
    screening: re.Pattern | None


@dataclass
class Rules:
    kinds: list[Kind]
    hedges: re.Pattern
    ats: tuple[str, ...]
    free_mail: frozenset[str]
    noise: re.Pattern
    company: list[re.Pattern]
    title: list[re.Pattern]


@cache
def rules() -> Rules:
    raw = yaml.safe_load(resources.files("jobwatch").joinpath("data/inbox.yaml").read_text(encoding="utf-8"))
    kinds = [Kind(name, k["label"], k.get("status"), k.get("next_step"),
                  [re.compile(p, re.I) for p in k["patterns"]], k.get("links", []),
                  re.compile(k["screening"], re.I) if k.get("screening") else None)
             for name, k in raw["kinds"].items()]
    return Rules(kinds, re.compile(raw["hedges"], re.I), tuple(raw["ats"]), frozenset(raw["free_mail"]),
                 re.compile(raw["noise"], re.I), [re.compile(p, re.I) for p in raw["company"]],
                 [re.compile(p, re.I) for p in raw["title"]])


@dataclass
class Email:
    """One email as read: what kind, the phrase that says so, who it's from, and who it's about."""
    kind: str               # a kind in data/inbox.yaml, or "other"
    label: str
    status: str | None      # the stage it suggests
    phrase: str             # the decisive words (or the scheduling link's site)
    date: str
    sender: str
    subject: str
    guesses: list[tuple[str, str]]  # (how, name): sender, body
    title: str
    ids: set[str]
    text: str = field(repr=False, default="")

    @property
    def company(self) -> str:
        """The company this email's from, as well as it can be told: the body's name for it, else the sender's."""
        order = {"body": 0, "domain": 1, "sender": 2, "mailbox": 3}
        return min(self.guesses, key=lambda g: order[g[0]])[1] if self.guesses else ""

    def to_dict(self) -> dict:
        return {"date": self.date, "sender": self.sender, "subject": self.subject}


def _words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9+#]+", text.lower()))


def _plain(msg: EmailMessage) -> tuple[str, str]:
    """(the text to read, every link and word the email has, for scheduling links)."""
    html, plain = alerts.bodies(msg)
    return (plain.strip() or html_to_text(html)), f"{html}\n{plain}"


def _day(msg: EmailMessage) -> str:
    try:
        return parsedate_to_datetime(str(msg["Date"])).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:  # an ISO date, as a mail connector's own fields give it ("2026-10-27T12:30:15Z")
        return datetime.fromisoformat(str(msg["Date"]).strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return date.today().isoformat()


def _quote(phrase: str) -> str:
    """A phrase for a note: cut at a word, with an ellipsis, when it's longer than QUOTED."""
    phrase = " ".join(phrase.split())
    return phrase if len(phrase) <= QUOTED else phrase[:QUOTED].rsplit(" ", 1)[0] + "…"


def classify(subject: str, text: str, raw: str = "") -> tuple[Kind | None, str]:
    """(the kind, the phrase that says so) for an email's subject and text; (None, "") when it's none of them.
    `raw` is the email as sent, for its links."""
    r = rules()
    whole = " ".join(f"{subject}. {text}".split())  # a line wrapped in the middle of a phrase is one line
    whole = whole.replace("’", "'")  # "won’t" as mail clients type it
    hedged = " ".join(s for s in _SENTENCES.split(whole) if not r.hedges.search(s))
    for kind in r.kinds:
        for pattern in kind.patterns:
            if m := pattern.search(whole if kind.name in ("rejection", "confirmation") else hedged):
                return kind, _quote(m.group(0))
        for link in kind.links:
            if re.search(rf"https?://(?:[\w-]+\.)*{re.escape(link)}\b", raw, re.I):
                return kind, f"a link to {link}"
    return None, ""


def _ats(domain: str) -> bool:
    return any(domain == d or domain.endswith(f".{d}") for d in rules().ats)


def _guesses(name: str, address: str, whole: str) -> list[tuple[str, str]]:
    """The names the email gives for the company: how the body names it, the sender's domain (unless it's an ATS's
    or a free mail's), the sender's display name and an ATS's mailbox (Workday's is the company's tenant)."""
    r = rules()
    out: list[tuple[str, str]] = []
    for pattern in r.company:
        out += [("body", m.group("company").strip(" .,!")) for m in pattern.finditer(whole)]
    local, _, domain = address.lower().rpartition("@")
    if domain and domain not in r.free_mail:
        if _ats(domain):
            mailbox = r.noise.sub(" ", local.replace(".", " ").replace("_", " ").replace("-", " ")).strip()
            out += [("mailbox", mailbox)] if mailbox else []
        elif (label := company.query_key(domain)):
            out.append(("domain", label))
    for part in re.split(r"\s+(?:at|from|via)\s+|\s+[|·•–-]\s+|,\s*|\(|\)", name):
        if part := " ".join(r.noise.sub(" ", part).split()):
            out.append(("sender", part))
    return [g for g in out if dupes.company_key(g[1])]


def read(msg: EmailMessage) -> Email:
    """One email read: its kind (or "other"), date, sender, and the company, title and ids it names."""
    subject = " ".join(str(msg["Subject"] or "").split())
    name, address = parseaddr(str(msg["From"] or ""))
    text, raw = _plain(msg)
    kind, phrase = classify(subject, text, raw)
    whole = f"{subject}\n{text}"
    title = next((" ".join(m.group("title").split()) for p in rules().title if (m := p.search(whole))), "")
    ids = dupes._text_reqs(whole) | {f[1] for u in _URL.findall(raw) if (f := dupes._link_id(u))}
    ids |= {i for i in map(dupes._norm_id, (m.group(1) for m in dupes._BRACKETED_REQ.finditer(whole))) if i}
    status = kind.status if kind else None
    if kind and kind.screening and status == "interviewing" and kind.screening.search(f"{subject}\n{text}"):
        status = "screening"
    return Email(kind.name if kind else "other", kind.label if kind else "recruiter email", status, phrase,
                 _day(msg), f"{name} <{address}>".strip() if name else address, subject,
                 _guesses(name, address, whole), title, ids, whole)


# -- Matching an email to an application.

def _same(a: str, b: str) -> bool:
    """The same company's key, or one that starts with the other ("acme" and "acmerobotics")."""
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))))


def _names(job) -> set[str]:
    return {job.display_company, re.sub(r"[,.]?\s+(?:inc|llc|ltd|corp)\.?$", "", job.display_company, flags=re.I)}


def _level(mail: Email, job) -> int:
    """How strongly the email names this job's company: 3 its sender, 2 its body, 1 mentioned in the text, else 0."""
    keys = dupes.companies(job)
    for how, name in mail.guesses:
        if how != "body" and any(_same(dupes.company_key(name), k) for k in keys):
            return 3
    if any(_same(dupes.company_key(name), k) for how, name in mail.guesses if how == "body" for k in keys):
        return 2
    for name in _names(job):
        if len(dupes.company_key(name)) >= 4 and re.search(rf"\b{re.escape(name)}\b", mail.text, re.I):
            return 1
    return 0


@dataclass
class Match:
    job: Job
    rec: dict
    confidence: str
    why: str


def match(mail: Email, entries: list[tuple]) -> tuple[Match | None, str]:
    """(the application the email is about, or None and why not): entries are (job, record) pairs."""
    seen = _words(mail.text)
    scored = []
    for job, rec in entries:
        level = _level(mail, job)
        ids = dupes.Signature.of(job, rec.get("note")).ids & mail.ids
        words = dupes.title_key(job.title)[0]
        title = bool(words) and f" {words} " in f" {seen} "
        if level or ids:
            scored.append((level, bool(ids), bool(title), job, rec))
    if not scored:
        return None, ""
    best = max(s[0] for s in scored)
    pool = [s for s in scored if s[0] == best or s[1]]
    pool = [s for s in pool if s[1]] or pool  # the id settles it
    if len(pool) > 1 and any(s[2] for s in pool):
        pool = [s for s in pool if s[2]]
    if len(pool) > 1:
        keys = ", ".join(s[3].key for s in pool[:6])
        return None, f"{len(pool)} applications there and nothing in the email tells them apart: {keys}"
    level, ids, title, job, rec = pool[0]
    score = level + 2 * ids + title
    if score < 2:
        return None, ""
    how = [{3: "sender", 2: "company named in the body", 1: "company mentioned"}.get(level, ""),
           "req or posting id" if ids else "", "title" if title else ""]
    return Match(job, rec, "high" if score >= 4 else "medium" if score == 3 else "low",
                 ", ".join(h for h in how if h)), ""


# -- Proposals.

@dataclass
class Proposal:
    key: str
    title: str
    company: str
    current: str
    suggested: str | None   # a stage to move to; None: only the note
    kind: str
    note: str
    next_step: str | None   # set when the application has none; "" clears it (and the follow-up day)
    email: Email
    confidence: str
    why: str


@dataclass
class Unmatched:
    email: Email
    company: str            # the company the email seems to be from
    title: str
    suggested: str | None
    reason: str


@dataclass
class Inbox:
    proposals: list[Proposal] = field(default_factory=list)
    unmatched: list[Unmatched] = field(default_factory=list)
    nothing_new: list[dict] = field(default_factory=list)  # emails that add nothing: key, email, why
    other: int = 0          # emails that are none of the kinds and not about a tracked application


def forward(now: str, new: str) -> bool:
    """Whether new is a move forward from now: any open stage to rejected, or up the stages; never back."""
    if now in ENDED:
        return False
    return new in ENDED or (new in RANK and now in RANK and RANK[new] > RANK[now])


def _note(mail: Email, sender: str) -> str:
    if mail.kind == "other":
        return f'{mail.date}: {mail.label} from {sender}: "{_quote(mail.subject)}"'
    return f"{mail.date}: {mail.label}: " + (mail.phrase if mail.phrase.startswith("a link") else f'"{mail.phrase}"')


def _sender(mail: Email) -> str:
    return mail.sender.split("<")[0].strip() or mail.sender


def propose(store: Store, messages: list[EmailMessage]) -> Inbox:
    """What the emails say about the applications, as proposals (nothing is changed). Emails go in date order, so
    a confirmation and the interview invitation after it each see the stage the one before proposed."""
    out = Inbox()
    entries = store.jobs(("queued", *STAGES), include_closed=True)
    status = {job.key: rec["status"] for job, rec in entries}
    notes = {job.key: rec.get("note") or "" for job, rec in entries}
    for mail in sorted((read(m) for m in messages), key=lambda m: m.date):
        found, why = match(mail, entries)
        if not found:
            if mail.kind == "other":
                out.other += 1
            else:
                out.unmatched.append(Unmatched(mail, mail.company, mail.title, mail.status, why))
            continue
        if mail.kind == "other" and found.confidence == "low":
            out.other += 1
            continue
        job, key, now = found.job, found.job.key, status[found.job.key]
        move = mail.status if mail.kind != "other" and mail.status and forward(now, mail.status) else None
        note = _note(mail, _sender(mail))
        if note in notes[key] or (move is None and mail.kind in ("confirmation", "rejection")):
            out.nothing_new.append({"key": key, "email": mail.to_dict(), "kind": mail.kind,
                                    "why": "already in the note" if note in notes[key] else f"already {now}"})
            continue
        ask = next((k.next_step for k in rules().kinds if k.name == mail.kind), None)
        step = ask if move and (ask == "" or not found.rec.get("next_step")) else None
        why = found.why + (f"; already {now}, so a note only" if now in ENDED else "")
        out.proposals.append(Proposal(key, job.title, job.display_company, now, move, mail.kind, note, step, mail,
                                      found.confidence, why))
        status[key] = move or now
        notes[key] += f" {note}"
    return out


def apply(store: Store, p: Proposal) -> str:
    """Record a proposal the way mark_job would: the stage (if it's still a move forward), a dated note, and the
    next step. Returns a line saying what was done."""
    job, rec = store.find(p.key)
    now = rec["status"]
    move = p.suggested if p.suggested and forward(now, p.suggested) else None
    if move:
        store.set_status([job.key], move, on=p.email.date if move == "applied" else None)
    if p.note not in (rec.get("note") or ""):
        store.add_note(job.key, p.note)
    if move and p.next_step == "":
        store.track(job.key, next_step="", follow_up="")
    elif move and p.next_step and not rec.get("next_step"):
        store.track(job.key, next_step=p.next_step)
    return f"{job.key}: {now} -> {move}" if move else f"{job.key}: noted ({now})"


# -- What to show.

def proposal_text(p: Proposal) -> str:
    move = f"{p.current} -> {p.suggested}" if p.suggested else f"{p.current} (note only)"
    out = [f"{p.company}: {p.title}", f"  {move}   [{p.confidence}: {p.why}]", f"  Note: {p.note}"]
    if p.next_step is not None:
        out.append("  Clears the next step and follow-up." if p.next_step == "" else f"  Next: {p.next_step}")
    return "\n".join([*out, f"  From {p.email.sender} on {p.email.date}: {p.email.subject}", f"  `{p.key}`"])


def summary(r: Inbox) -> str:
    """`jobwatch inbox`: the proposals, then what matched nothing and what added nothing."""
    n, u = len(r.proposals), len(r.unmatched)
    out = [f"{n} proposal{'s' * (n != 1)}, {u} unmatched, {len(r.nothing_new)} adding nothing, "
           f"{r.other} not about an application."]
    for p in r.proposals:
        out += ["", proposal_text(p)]
    if r.unmatched:
        out += ["", "Not matched to an application (track one with `jobwatch add`):"]
        for m in r.unmatched:
            guess = f"{m.company or 'unknown company'}" + (f", {m.title}" if m.title else "")
            out.append(f"  {m.email.date} {m.email.label}: {m.email.subject or 'no subject'} ({guess}"
                       + (f"; from {m.email.sender}" if m.email.sender else "") + ")"
                       + (f"\n    {m.reason}" if m.reason else ""))
    for x in r.nothing_new:
        out.append(f"Nothing new for {x['key']}: {x['kind']} email of {x['email']['date']}, {x['why']}.")
    return "\n".join(out)


def to_dict(r: Inbox) -> dict:
    """The proposals for an assistant: each with the mark_job arguments that would record it."""
    def one(p: Proposal) -> dict:
        args = {"key": p.key, "add_note": p.note}
        if p.suggested:
            args["status"] = p.suggested
        if p.next_step is not None and (p.suggested or p.next_step):
            args["next_step"] = p.next_step
        if p.suggested and p.next_step == "":
            args["follow_up"] = ""
        return {"key": p.key, "company": p.company, "title": p.title, "current_status": p.current,
                "suggested_status": p.suggested, "kind": p.kind, "note": p.note, "next_step": p.next_step,
                "email": p.email.to_dict(), "confidence": p.confidence, "why": p.why, "mark_job": args}

    return {"proposals": [one(p) for p in r.proposals],
            "unmatched": [{"email": m.email.to_dict(), "kind": m.email.kind, "company": m.company,
                           "title": m.title, "suggested_status": m.suggested, "note": _note(m.email, _sender(m.email)),
                           "reason": m.reason} for m in r.unmatched],
            "nothing_new": r.nothing_new, "other": r.other}
