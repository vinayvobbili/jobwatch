"""A prep sheet for a recruiter call or an interview: the posting's asks next to the resume lines that answer them,
the gaps to be honest about, what was sent, and questions to expect and to ask.

Everything on it comes from the posting, the resume and the tracker: nothing is written for you, so nothing on it
is a claim you haven't made yourself.

The exceptions are asked for (draft, questions): likely questions, from the posting's asks, that a model writes
for this role (questions), and answer outlines drafted from your stories and resume only (draft); the code checks
both before they go on the sheet (see drafts.py). The company brief and the pay section need no model: the brief
quotes the posting and your notes, the pay section the posted range and your own settings (pay.target, and a pay.floor
that never leaves this computer).
"""

from __future__ import annotations

import html as _html
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, replace

from . import drafts
from .config import Config
from .learn import _fit, for_job
from .models import Job
from .resume import resume_text
from .store import Store
from .watch import load_contacts

# Section headings in a posting, by what follows them.
_NEED = re.compile(r"qualif|requir|must|you have|you bring|you'll bring|looking for|about you|what we need|"
                   r"skills|experience|who you are|ideal candidate|basic|minimum", re.I)
_NICE = re.compile(r"prefer|nice to have|bonus|plus|desired|stand out", re.I)
_DO = re.compile(r"you will|you'll|responsib|what you.?ll do|the role|day to day|in this role|duties|impact", re.I)
_SKIP = re.compile(r"benefit|perks|pay|salary|compensation|equal opportunity|about us|who we are|eeo|accommodat|"
                   r"privacy|location|why join|our values", re.I)
_SCHOOL = re.compile(r"\b(?:university|institute|college|bachelor|master|GPA)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣–]|\d+[.)])\s*")
_DEGREE_ASK = re.compile(r"\b(?:degree|bachelor|master|ph\.?d|doctorate)", re.I)
_DEGREE = re.compile(r"\b(?:bachelor|master|doctor|ph\.?d|b\.?tech|m\.?tech|b\.?sc?|m\.?sc?|b\.?e|mba)\b", re.I)

_STOP = set("""a an and are as at be been by can do for from has have in into is it its of on or our that the their
them they this to we what when where which who will with you your yours able across all also any both each more most
new other over such than within work working role team teams ability strong including using use etc years year plus
experience experiences related similar via well proven technology technologies technical engineering engineer
engineers skill skills knowledge solid deep excellent demonstrated expertise hands""".split())

SCREEN_QUESTIONS = [
    "Walk me through your background (two minutes: now, before, why this role).",
    "Why this company, and why now?",
    "What are you looking for in pay? (Have your range ready.)",
    "Where are you located, and does the role's location or travel work for you?",
    "Are you authorized to work here, and will you need sponsorship?",
    "What's your timeline? Are you interviewing elsewhere?",
]
INTERVIEW_QUESTIONS = [
    "Tell me about the project you're proudest of: what you built, the hard part, the result.",
    "A time you disagreed with a decision: what you did and how it ended.",
    "A time something you owned failed: what happened and what you changed.",
    "A time you had to move without clear requirements.",
    "How would you approach the first 90 days here?",
]
ASK_SCREEN = [
    "Why is the role open, and what does the team own?",
    "Who would I report to, and how big is the team?",
    "What are the interview steps and the timeline?",
    "How much remote, on-site and travel does it really involve?",
]
ASK_INTERVIEW = [
    "What does doing well look like after 90 days, and after a year?",
    "What's the hardest problem the team is working on right now?",
    "How are decisions made about what to build, and who makes them?",
    "What's on-call or after-hours work like?",
    "What do people who do well here have in common?",
]


@dataclass
class Match:
    ask: str            # a line from the posting
    kind: str           # need, nice or do
    resume: str = ""    # the resume line sharing the most words with it
    shared: list[str] = field(default_factory=list)


@dataclass
class Sheet:
    key: str
    company: str
    title: str
    status: str
    url: str = ""
    posting_key: str = ""       # the fetched posting used, when the application was added by hand
    applied_at: str | None = None
    next_step: str | None = None
    follow_up: str | None = None
    note: str | None = None
    fit: dict | None = None
    gaps: list[dict] = field(default_factory=list)       # skills asked for that the resume doesn't show
    matches: list[Match] = field(default_factory=list)
    sent: dict = field(default_factory=dict)
    resume_used: str = ""                                # "sent" or "base"; "" when there's none
    expect: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    posting: str = ""
    # Questions written for this role from the posting's asks (see drafts.questions): saved ones, or made when
    # asked for; none: expect's generic ones stand. questions_note says where they came from, or why there are none.
    role_questions: list[str] = field(default_factory=list)
    questions_note: str = ""
    brief: dict = field(default_factory=dict)            # the company, as the posting and your notes tell it
    pay: dict = field(default_factory=dict)              # the posted range, your target and your private floor
    # Asked for with draft (see drafts.check for each one's fields); none: expect's questions stand.
    drafted: list[dict] = field(default_factory=list)
    draft_note: str = ""                                 # how the drafts were made, or why there are none
    practised: list[dict] = field(default_factory=list)  # answers kept from mock interviews (see mock.py)


def _stems(text: str) -> dict[str, str]:
    """{stem: word} for the words that carry meaning. The stem is the first six letters, which is crude but
    lets mentor/mentoring and architect/architecture meet."""
    out = {}
    for w in re.findall(r"[a-z][a-z0-9+#]*(?:\.[a-z0-9]+)?", text.lower()):
        if w not in _STOP and (len(w) > 2 or w in ("ai", "ml", "go", "c#", "ci", "cd")):
            out.setdefault(w[:6], w)
    return out


def _heading(line: str) -> bool:
    s = line.strip()
    return bool(s) and not _BULLET.match(s) and len(s.split()) <= 8 and (s.endswith(":") or s.isupper() or
                                                                          not re.search(r"[.,;]$", s)) \
        and len(s) < 70


def asks(description: str, most: int = 14) -> list[tuple[str, str]]:
    """(line, kind) for the posting's requirements (need, nice) and responsibilities (do), in its order."""
    out, kind = [], None
    for raw in description.splitlines():
        line = _BULLET.sub("", raw).strip()
        if not line:
            continue
        if _heading(raw):
            kind = ("skip" if _SKIP.search(line) else "nice" if _NICE.search(line) else "need" if _NEED.search(line)
                    else "do" if _DO.search(line) else None)
            continue
        if kind in ("need", "nice", "do") and 4 <= len(line.split()) <= 60:
            out.append((line, kind))
    if not out:  # no headings: take the sentences that read like requirements
        for s in re.split(r"(?<=[.;])\s+|\n", description):
            if re.search(r"\b(?:experience|years|proficien|familiar|knowledge|degree)\b", s, re.I) \
                    and 4 <= len(s.split()) <= 60:
                out.append((_BULLET.sub("", s).strip(), "need"))
    order = {"need": 0, "do": 1, "nice": 2}
    return sorted(out, key=lambda a: order[a[1]])[:most]


def _resume_lines(resume: str) -> list[str]:
    """The resume's lines with PDF line wrapping undone: a bullet runs on until the next bullet or heading."""
    items: list[str] = []
    wrapped = False
    for raw in resume.splitlines():
        line = raw.strip()
        if not line:
            wrapped = False
            continue
        if items and not _BULLET.match(line) and (wrapped or line[0].islower()):
            items[-1] += " " + line
        else:
            items.append(_BULLET.sub("", line))
        wrapped = raw.endswith(" ") or bool(re.search(r"[,;&/(-]$|\b(?:and|or|of|the|to|with|in)$", line))
    # One sentence each, so a long summary paragraph doesn't answer everything.
    return [x.strip() for i in items for x in re.split(r"(?<=[.;])\s+(?=[A-Z])", i)
            if len(x.split()) >= 5 and not _SCHOOL.search(x)]


def _degrees(resume: str) -> str:
    """The resume's degree lines, for a posting that asks for a degree."""
    return "; ".join(dict.fromkeys(_BULLET.sub("", ln).strip() for ln in resume.splitlines()
                                   if _DEGREE.search(ln) and len(ln.split()) <= 25))


def pair(ask_lines: list[tuple[str, str]], resume: str) -> list[Match]:
    """Each ask with the resume line sharing the most words with it (at least two), and those words. Words the
    resume uses everywhere count for less, and so do long lines and lines already given for another ask, so one
    skills list doesn't answer everything. An ask for a degree gets the resume's degrees."""
    lines = [(ln, set(_stems(ln))) for ln in _resume_lines(resume)]
    seen = Counter(st for _, sts in lines for st in sts)
    weight = {st: math.log((len(lines) + 1) / n) for st, n in seen.items()}
    used: Counter = Counter()
    degrees = _degrees(resume)

    def score(want: dict, ln: str, sts: set) -> float:
        return sum(weight[st] for st in want.keys() & sts) / math.sqrt(len(sts) or 1) / (1 + used[ln])
    out = []
    for ask, kind in ask_lines:
        if degrees and _DEGREE_ASK.search(ask):
            out.append(Match(ask, kind, degrees, ["degree"]))
            continue
        want = _stems(ask)
        best = max(lines, key=lambda lw: score(want, *lw), default=("", set()))
        shared = sorted(want[st] for st in want.keys() & best[1])
        if len(shared) >= 2:
            used[best[0]] += 1
            out.append(Match(ask, kind, best[0], shared))
        else:
            out.append(Match(ask, kind))
    return out


def _screen(status: str) -> bool:
    """Whether the next conversation is a screen (the first call) rather than interviews."""
    return status in ("applied", "screening", "queued")


def _money(n: int) -> str:
    return f"${n / 1000:g}K" if n % 1000 == 0 else f"${n:,}"


def pay_info(cfg: Config, job: Job) -> dict:
    """The pay section: {posted, posted_min, posted_max (from the posting), target, floor (from pay.target and
    pay.floor, 0 when unset), target_note, floor_note (how each sits against the posted range), floor_withheld}.
    {} when there's nothing to show. The floor is private: see without_floor for the copy that leaves."""
    low, high = job.salary_min or 0, job.salary_max or job.salary_min or 0
    target, floor = cfg.pay.target, cfg.pay.floor
    if not (job.pay() or target or floor):
        return {}
    notes = {"target_note": "", "floor_note": ""}
    if low and target:
        notes["target_note"] = ("below the posted range" if target < low else
                                "above the posted range" if target > high else "inside the posted range")
    if high and floor:
        notes["floor_note"] = ("above the top of the posted range: they may not reach it" if floor > high else
                               "inside the posted range" if floor >= low else "below the posted range")
    return {"posted": job.pay(), "posted_min": low, "posted_max": high, "target": target, "floor": floor,
            "floor_withheld": False, **notes}


def without_floor(s: Sheet) -> Sheet:
    """The sheet as it may leave this computer (to an assistant or a cloud model): the pay floor, and what was
    said about it, taken out and marked as left out."""
    if not s.pay.get("floor"):
        return s
    return replace(s, pay={**s.pay, "floor": 0, "floor_note": "", "floor_withheld": True})


_ABOUT = ("about us|about the company|who we are|our mission|our story|our company|company overview|overview|"
          "what we do")


def _about(description: str, company: str, most: int = 4) -> list[str]:
    """What the posting says about the company, in its words: the lines under its "About us" kind of heading, or
    failing that, the sentences in its first lines that name the company."""
    head = re.compile(rf"^(?:{_ABOUT}|about {re.escape(company)})\b", re.I) if company else re.compile(_ABOUT, re.I)
    lines, inside = [], False
    for raw in description.splitlines():
        line = _BULLET.sub("", raw).strip()
        if not line:
            continue
        if _heading(raw):
            inside = bool(head.search(line.rstrip(":")))
            continue
        if inside and 4 <= len(line.split()) <= 60:
            lines.append(line)
    if not lines and company:
        for line in description.splitlines()[:25]:
            lines += [x for x in re.split(r"(?<=[.!?])\s+", _BULLET.sub("", line).strip())
                      if company.lower() in x.lower() and len(x.split()) >= 4]
    return [drafts._clip(x, 300) for x in lines[:most]]


def company_brief(cfg: Config, job: Job, posting: Job, rec: dict) -> dict:
    """The company as the posting and your own notes tell it: {about (the posting's lines), facts ([{label,
    value}] from the posting's record), notes (your note on the job), contacts (people you know there), source}.
    Nothing is looked up and nothing is added: {} when the sources say nothing."""
    company = posting.display_company
    facts = [{"label": label, "value": value} for label, value in
             (("Locations", "; ".join(posting.places)), ("Team", posting.department)) if value]
    known = load_contacts(cfg)
    people = [{"name": p["name"], "position": p.get("position", ""), "why": p.get("why", "")}
              for p in (known.at(job.display_company, job.company, company) if known else [])]
    brief = {"about": _about(posting.description, company), "facts": facts, "notes": rec.get("note") or "",
             "contacts": people[:5]}
    return {**brief, "source": "Drawn from the posting and your notes; nothing else was looked up."} \
        if any(brief.values()) else {}


def role_questions(cfg: Config, store: Store, key: str, generate: bool = True) -> list[str]:
    """The questions this role is likely to bring up, for the stage it is at: written by the chat's model from the
    posting's asks, or the generic screen / interview list when there's no model, no posting text or nothing
    usable (it never raises for the model's sake). Saved per job and posting text, so asking again doesn't call
    the model; without generate only saved ones are read. For a mock interview or any other caller."""
    job, rec = store.find(key)
    posting: Job = store.linked(job) or job
    screen = _screen(rec["status"])
    got, _ = drafts.questions(cfg, store, job.key, asks(posting.description), screen, posting.to_text(),
                              pay_info(cfg, posting if posting.salary_min is not None else job), generate)
    return got or list(SCREEN_QUESTIONS if screen else INTERVIEW_QUESTIONS)


def build(cfg: Config, store: Store, key: str, draft: bool = False, questions: bool = False) -> Sheet:
    """The sheet, rule-based and instant. questions: also have the chat's model write questions for this role
    from the posting's asks (saved ones are always read; with the claude backend the posting goes to Anthropic).
    draft: also ask it for role-specific questions with answers drafted from the stories and resume (slower, and
    with the claude backend they're sent to Anthropic too)."""
    job, rec = store.find(key)
    posting: Job = store.linked(job) or job
    pkg = store.package(job.key)
    fit = _fit(cfg, store, job.key) or (_fit(cfg, store, posting.key) if posting is not job else None)
    sent = pkg.resume()
    resume = resume_text(sent)
    resume_used = "sent" if resume else ""
    if not resume and (resume := resume_text(cfg.resume)):
        resume_used = "base"
    stage = rec["status"]
    screen = _screen(stage)
    expect = SCREEN_QUESTIONS if screen else INTERVIEW_QUESTIONS
    ask = ASK_SCREEN if screen else ASK_INTERVIEW
    ask_lines = asks(posting.description)
    pay = pay_info(cfg, posting if posting.salary_min is not None else job)
    drafted, draft_note = drafts.draft(cfg, store, job.key, ask_lines, screen, resume,
                                       posting.to_text()) if draft else ([], "")
    if drafted:  # already role-specific: no second call
        written, questions_note = [d["question"] for d in drafted], ""
    else:
        written, questions_note = drafts.questions(cfg, store, job.key, ask_lines, screen, posting.to_text(), pay,
                                                   generate=questions)
    data = pkg.data()
    return Sheet(key=job.key, company=job.display_company, title=job.title, status=stage, url=posting.url or job.url,
                 posting_key=posting.key if posting is not job else "",
                 **{k: rec.get(k) for k in ("applied_at", "next_step", "follow_up", "note")}, fit=fit,
                 gaps=[{"name": d.skill.name, "must_have": bool(d.gap_jobs)} for d in for_job(posting, fit, resume)],
                 matches=pair(ask_lines, resume), resume_used=resume_used,
                 sent={"files": [f["name"] for f in data["files"]], "answers": data["answers"], "note": data["note"]},
                 expect=expect, ask=ask, posting=posting.to_text(), drafted=drafted, draft_note=draft_note,
                 role_questions=written, questions_note=questions_note, pay=pay,
                 brief=company_brief(cfg, job, posting, rec), practised=pkg.practised())


def to_dict(s: Sheet) -> dict:
    return asdict(s)


_KIND = {"need": "They ask for", "do": "You'd be doing", "nice": "Nice to have"}


def _pay_lines(pay: dict) -> list[tuple[str, str]]:
    """(label, text) for the pay section. The floor is labelled private: it stays on this computer."""
    out = [("Posted range", pay["posted"] + " (from the posting)" if pay.get("posted") else
            "not in the posting")]
    if pay.get("target"):
        out.append(("Your target", _money(pay["target"]) + (f", {pay['target_note']}" if pay.get("target_note")
                                                           else "")))
    if pay.get("floor"):
        out.append(("Your floor (private)", _money(pay["floor"]) + (f", {pay['floor_note']}" if pay.get("floor_note")
                                                                  else "") + ". Never sent to Claude"))
    elif pay.get("floor_withheld"):
        out.append(("Your floor (private)", "set, and left out of this copy"))
    return out


def markdown(s: Sheet) -> str:
    out = [f"# Prep: {s.title}, {s.company}", ""]
    track = [f"**Stage:** {s.status}"] + [f"**{label}:** {v}" for label, v in
                                         (("Applied", s.applied_at), ("Next step", s.next_step),
                                          ("Follow up", s.follow_up)) if v]
    out.append(" · ".join(track))
    if s.note:
        out.append(f"\n**Notes:** {s.note}")
    if s.url:
        out.append(f"\n[The posting]({s.url})" + (f" (found on a watched board: `{s.posting_key}`)"
                                                  if s.posting_key else ""))
    if s.fit:
        out += ["", "## Fit", f"{s.fit.get('score', 0):.0f}/100, {s.fit.get('must_haves_met', 0)} of "
                f"{s.fit.get('must_haves_total', 0)} must-haves."]
        if s.fit.get("summary"):
            out.append(s.fit["summary"])
    if s.brief:
        out += ["", "## Company brief", f"_{s.brief['source']}_"]
        out += [f"- {a}" for a in s.brief["about"]] + [f"- {f['label']}: {f['value']}" for f in s.brief["facts"]]
        if s.brief["notes"]:
            out.append(f"\n**Your notes:** {s.brief['notes']}")
        if s.brief["contacts"]:
            out.append("\n**You know:** " + "; ".join(
                p["name"] + (f" ({p['position']})" if p["position"] else "") + (f" [{p['why']}]" if p["why"] else "")
                for p in s.brief["contacts"]))
    if s.matches:
        which = {"sent": "the resume you sent", "base": "your resume"}.get(s.resume_used, "")
        out += ["", "## Their asks and your closest line" + (f" ({which})" if which else "")]
        for m in s.matches:
            out.append(f"- **{_KIND[m.kind]}:** {m.ask}")
            out.append(f"  - You: {m.resume}" if m.resume else "  - Nothing close on the resume: have a story, or "
                                                             "say plainly how you'd get there.")
    if not s.matches:
        out += ["", "No requirements found in the posting text. An application added by hand has only its title "
                    "until a watched board lists the same requisition id."]
    gaps = [g for g in s.gaps if g["must_have"]] + [g for g in s.gaps if not g["must_have"]]
    fit_gaps = (s.fit or {}).get("gaps") or []
    if gaps or fit_gaps:
        out += ["", "## Be ready to be honest about",
                "Say what's closest and how you'd ramp up. Don't claim what you haven't done."]
        out += [f"- {g}" for g in fit_gaps]
        out += [f"- {g['name']}" + (" (a must-have)" if g["must_have"] else "") for g in gaps]
    if s.pay:
        out += ["", "## Pay"] + [f"- **{label}:** {value}" for label, value in _pay_lines(s.pay)]
    if s.sent["files"] or s.sent["answers"] or s.sent["note"]:
        out += ["", "## What you sent"]
        if s.sent["files"]:
            out.append("Files: " + ", ".join(s.sent["files"]))
        out += [f"- **{a['question']}** {a['answer']}" for a in s.sent["answers"]]
        if s.sent["note"]:
            out += ["", s.sent["note"]]
    if s.drafted:  # the drafted questions take the generic ones' place
        out.append(drafts.markdown(s.drafted, s.draft_note).rstrip("\n"))
    else:
        out += ["", "## They'll likely ask"] + [f"_{n}_" for n in (s.draft_note, s.questions_note) if n] \
            + [f"- {q}" for q in s.role_questions or s.expect]
    if s.practised:
        out += ["", "## Practised answers", "Tightened in mock interviews, from what you said and your stories."]
        for p in s.practised:
            out += [f"- **{p['question']}**", f"  - {p['improved']}"]
    out += ["", "## Ask them"] + [f"- {q}" for q in s.ask]
    return "\n".join(out) + "\n"


_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1d2330;--muted:#5d6678;--line:#d9dde5;--card:#f5f7fa;--accent:#1f5fbf}
@media (prefers-color-scheme:dark){:root{--bg:#161a22;--fg:#e4e8ef;--muted:#9aa3b5;--line:#2c3342;--card:#1e232e;
--accent:#7fb0ff}}
body{margin:0 auto;max-width:46rem;padding:1.5rem 1rem 3rem;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:1.5rem;margin:0 0 .3rem}h2{font-size:1.1rem;margin:1.6rem 0 .5rem;border-bottom:1px solid var(--line)}
a{color:var(--accent)}.meta,.muted{color:var(--muted)}.small{font-size:.9rem}
ul{margin:.3rem 0;padding-left:1.3rem}li{margin:.2rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:.5rem .75rem;margin:.5rem 0}
.kind{font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.you{margin-top:.25rem;padding-left:.6rem;border-left:3px solid var(--accent)}.none{margin-top:.25rem;font-style:italic;
color:var(--muted)}
.note{white-space:pre-wrap}
@media print{:root{--bg:#fff;--fg:#000;--muted:#444;--line:#bbb;--card:#fff;--accent:#000}
body{max-width:none;padding:0;font-size:11pt}.card,li,h2{break-inside:avoid}h2{break-after:avoid}
a{text-decoration:none}@page{size:Letter;margin:.7in}}
"""


def _e(text) -> str:
    """Posting text is written by employers: nothing from it reaches the page unescaped."""
    return _html.escape(str(text), quote=True)


def _link(url: str, label: str) -> str:
    """A link only for http(s) URLs: a javascript: or data: URL from a posting is shown as text."""
    if not re.match(r"https?://", url, re.I):
        return _e(label)
    return f'<a href="{_e(url)}" rel="noopener noreferrer">{_e(label)}</a>'


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


# Each section is a function returning (heading, body html), or None when the sheet has nothing for it. To add a
# section, write one and put it in html()'s list.
def _fit_part(s: Sheet):
    if s.fit:
        body = f"<p>{s.fit.get('score', 0):.0f}/100, {s.fit.get('must_haves_met', 0)} of " \
               f"{s.fit.get('must_haves_total', 0)} must-haves.</p>"
        if s.fit.get("summary"):
            body += f'<p class="small muted">{_e(s.fit["summary"])}</p>'
        return "Fit", body


def _brief_part(s: Sheet):
    if s.brief:
        b = s.brief
        items = [_e(a) for a in b["about"]] + [f"{_e(f['label'])}: {_e(f['value'])}" for f in b["facts"]]
        body = f'<p class="small muted">{_e(b["source"])}</p>' + (_ul(items) if items else "")
        if b["notes"]:
            body += f'<p class="note"><b>Your notes:</b> {_e(b["notes"])}</p>'
        if b["contacts"]:
            body += "<p><b>You know:</b> " + "; ".join(
                _e(p["name"]) + (f" ({_e(p['position'])})" if p["position"] else "")
                + (f' <span class="muted">[{_e(p["why"])}]</span>' if p["why"] else "") for p in b["contacts"]) + "</p>"
        return "Company brief", body


def _pay_part(s: Sheet):
    if s.pay:
        return "Pay", _ul([f"<b>{_e(label)}:</b> {_e(value)}" for label, value in _pay_lines(s.pay)])


def _matches_part(s: Sheet):
    if not s.matches:
        return "", ('<p class="muted">No requirements found in the posting text. An application added by hand has '
                    'only its title until a watched board lists the same requisition id.</p>')
    which = {"sent": "the resume you sent", "base": "your resume"}.get(s.resume_used, "")
    cards = "".join(
        f'<div class="card"><div class="kind">{_KIND[m.kind]}</div><div>{_e(m.ask)}</div>'
        + (f'<div class="you">{_e(m.resume)}</div>' if m.resume else
           '<div class="none">Nothing close on the resume: have a story, or say plainly how you\'d get there.</div>')
        + "</div>" for m in s.matches)
    return "Their asks and your closest line" + (f" ({which})" if which else ""), cards


def _gaps_part(s: Sheet):
    gaps = [g for g in s.gaps if g["must_have"]] + [g for g in s.gaps if not g["must_have"]]
    fit_gaps = (s.fit or {}).get("gaps") or []
    if gaps or fit_gaps:
        items = [_e(g) for g in fit_gaps] + [_e(g["name"]) + (" (a must-have)" if g["must_have"] else "")
                                             for g in gaps]
        return "Be ready to be honest about", ('<p class="small muted">Say what\'s closest and how you\'d ramp up. '
                                               "Don't claim what you haven't done.</p>" + _ul(items))


def _sent_part(s: Sheet):
    if s.sent["files"] or s.sent["answers"] or s.sent["note"]:
        body = f'<p>Files: {_e(", ".join(s.sent["files"]))}</p>' if s.sent["files"] else ""
        if s.sent["answers"]:
            body += _ul([f"<b>{_e(a['question'])}</b> {_e(a['answer'])}" for a in s.sent["answers"]])
        if s.sent["note"]:
            body += f'<p class="note">{_e(s.sent["note"])}</p>'
        return "What you sent", body


def _expect_part(s: Sheet):
    note = "".join(f'<p class="small muted">{_e(n)}</p>' for n in (s.draft_note, s.questions_note) if n)
    if not s.drafted:
        return "They'll likely ask", note + _ul([_e(q) for q in s.role_questions or s.expect])
    cards = []
    for d in s.drafted:
        probes = f'<div class="kind">Probes: {_e(d["probes"])}</div>' if d["probes"] else ""
        if d["no_story"]:
            body = f'<div class="none">No story yet. {_e(d["angle"])}</div>'
        else:
            body = (f'<div class="small muted">From: {_e(", ".join(st["title"] for st in d["stories"]))}</div>'
                    + '<div class="you">' + _ul([_e(p) for p in d["outline"]]) + "</div>")
        cards.append(f'<div class="card">{probes}<div><b>{_e(d["question"])}</b></div>{body}</div>')
    return "Likely questions for this role, with drafted answers", note + "".join(cards)


def _practised_part(s: Sheet):
    if s.practised:
        cards = "".join(f'<div class="card"><div><b>{_e(p["question"])}</b></div>'
                        f'<div class="you note">{_e(p["improved"])}</div></div>' for p in s.practised)
        return "Practised answers", ('<p class="small muted">Tightened in mock interviews, from what you said '
                                     "and your stories.</p>" + cards)


def _ask_part(s: Sheet):
    return "Ask them", _ul([_e(q) for q in s.ask])


def html(s: Sheet) -> str:
    """The same sheet as a standalone page: inline CSS only, no scripts or network loads, and print styles."""
    track = [f"<b>Stage:</b> {_e(s.status)}"] + [f"<b>{label}:</b> {_e(v)}" for label, v in
                                                 (("Applied", s.applied_at), ("Next step", s.next_step),
                                                  ("Follow up", s.follow_up)) if v]
    head = [f"<h1>Prep: {_e(s.title)}, {_e(s.company)}</h1>", f'<div class="meta">{" · ".join(track)}</div>']
    if s.note:
        head.append(f'<p class="note"><b>Notes:</b> {_e(s.note)}</p>')
    if s.url:
        head.append("<p>" + _link(s.url, "The posting") + (f" (found on a watched board: <code>{_e(s.posting_key)}"
                                                         "</code>)" if s.posting_key else "") + "</p>")
    parts = [p for p in (_fit_part(s), _brief_part(s), _matches_part(s), _gaps_part(s), _pay_part(s),
                         _sent_part(s), _expect_part(s), _practised_part(s), _ask_part(s)) if p]
    body = "\n".join(head + [(f"<section><h2>{_e(h)}</h2>{b}</section>" if h else b) for h, b in parts])
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{_e('Prep: ' + s.title + ', ' + s.company)}</title><style>{_CSS}</style></head>\n"
            f"<body>\n{body}\n</body></html>\n")
