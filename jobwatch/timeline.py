"""The interview rounds of one application, as a timeline: the rounds that are done, the next one, and what isn't
scheduled yet (never invented).

Rounds are structured records (store.interview_rounds): kind (one of rounds.ROUNDS, or "" for an interview or call
that says no more), day, time, length, who, mode, outcome, note, and where it came from (`source`):
  next_step  written when `mark --next` / `--round` sets or moves the next step: the step's meeting is kept as a
             scheduled round, and when the step is replaced a round whose time has passed becomes done
  you        added or edited by hand (the Details dialog, `jobwatch rounds`, the MCP tool)
  inferred   proposed from the dated History lines by `jobwatch rounds --backfill`, written only on --apply

`build` joins the stored rounds with the meeting the application's next step names right now (so an application
that was never synced shows its next round too) and says which round is next. `infer` reads the dated History
lines for rounds that were held; it only proposes, nothing here writes."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import ics, rounds
from .store import ENDED, STAGES

STATES = ("scheduled", "done")
MODES = {"teams": "Teams", "zoom": "Zoom", "google meet": "Google Meet", "meet link": "Google Meet",
         "webex": "Webex", "phone": "Phone", "dial-in": "Phone", "dial in": "Phone", "on-site": "Onsite",
         "onsite": "Onsite", "in person": "Onsite", "in-person": "Onsite", "video": "Video"}
_MODE = re.compile(r"\b(" + "|".join(sorted((re.escape(m) for m in MODES), key=len, reverse=True)) + r")\b", re.I)

# What each kind of round is, for the tooltips (the page shows these next to the kind names).
KIND_HELP = {
    "recruiter_screen": "A short first call with a recruiter: your background, pay range, timing.",
    "hiring_manager": "A conversation with the person you would work for: the team, the work, how you fit.",
    "technical": "A coding or hands-on technical interview.",
    "system_design": "You design a system on a whiteboard or document and talk through the trade-offs.",
    "panel": "Several interviews in a row, or a panel, often called the onsite loop.",
    "executive": "A VP or executive conversation, usually near the end.",
    "hr": "A people or HR conversation: values, logistics, references.",
    "informal": "A casual coffee or chat with no formal evaluation.",
    "offer_call": "The call where they talk about the offer.",
    "": "An interview or call that doesn't say what kind it is.",
}

# Words that say which round a text is about, the more specific first. HM, VP, CEO and HR count only in capitals.
_KINDS = (
    ("system_design", r"(?i:system[- ]design)"),
    ("panel", r"(?i:panel|on-?site|\bloop\b|final round)"),
    ("offer_call", r"(?i:offer (?:call|discussion|conversation)|comp(?:ensation)? (?:call|discussion))"),
    ("hiring_manager", r"(?i:hiring[- ]manager)|\bHM\b"),
    ("executive", r"(?i:\bexec(?:utive)?\b)|\bVP\b|\bC[TEF]O\b"),
    ("technical", r"(?i:technical|\btech\b|coding|code (?:review|pairing)|pair programming|live code)"),
    ("hr", r"(?i:people (?:team|ops|partner)|culture fit|behavioral)|\bHR\b"),
    ("informal", r"(?i:coffee|informal|casual chat)"),
    ("recruiter_screen", r"(?i:recruiter|\bintro\b|introductory|phone screen|screening|\bscreen\b)"),
)
_KIND_RES = [(k, re.compile(p)) for k, p in _KINDS]

_NAME = r"[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+){0,2}"
_WHO = re.compile(rf"\bwith\s+({_NAME}(?:(?:,\s*|\s+and\s+|\s*&\s*){_NAME})*)")
NOT_NAMES = {"Teams", "Zoom", "Meet", "Webex", "Google", "Phone", "Slack", "Calendly", "The", "Their",
             "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Mon", "Tue", "Wed",
             "Thu", "Fri", "Sat", "Sun", "January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug",
             "Sep", "Oct", "Nov", "Dec", "Hr", "Hiring", "Recruiter", "Team", "Panel"}


def kind_from_text(text: str | None) -> str:
    """Which round a text is about ("system design interview": system_design), "" when it names none."""
    t = text or ""
    return next((k for k, rx in _KIND_RES if rx.search(t)), "")


def label(kind: str) -> str:
    """The kind's name as shown: "Panel / onsite loop", or "Interview" for a round of no known kind."""
    return rounds.label(kind) or "Interview"


def mode_from_text(text: str | None) -> str:
    """Where a meeting is held, from its words ("Zoom", "phone"), else ""."""
    m = _MODE.search(text or "")
    return MODES[m.group(1).lower()] if m else ""


def who_from_text(text: str | None) -> str:
    """The people a text says the meeting is with ("call with Dana Lee and Sam Ortiz"), else "". Capitalised words
    after "with" that are not names (Teams, a weekday, a month) are left out."""
    names = []
    for m in _WHO.finditer(text or ""):
        for name in re.split(r",\s*|\s+and\s+|\s*&\s*", m.group(1)):
            if name.split()[0] not in NOT_NAMES and name not in names:
                names.append(name)
    return ", ".join(names)


def clock(value: str | None) -> str:
    """A time as HH:MM (24-hour), "" for none; ValueError for what isn't a time. Takes 14:30, 2:30 PM and 2pm."""
    text = (value or "").strip()
    if not text or text.lower() == "none":
        return ""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?", text, re.I)
    if m and (hour := int(m.group(1))) < 24 and int(m.group(2) or 0) < 60 and (m.group(2) or m.group(3)):
        if m.group(3):
            if not 1 <= hour <= 12:
                raise ValueError(f"{value!r} isn't a time: use 14:30 or 2:30 PM")
            hour = hour % 12 + (12 if m.group(3).lower() == "p" else 0)
        return f"{hour:02d}:{m.group(2) or '00'}"
    raise ValueError(f"{value!r} isn't a time: use 14:30 or 2:30 PM")


def _local(m: ics.Meeting) -> tuple[datetime, datetime]:
    """A meeting's start and end on this computer's clock (a time the text gave no zone for is already that)."""
    return (m.start.astimezone().replace(tzinfo=None), m.end.astimezone().replace(tzinfo=None)) if m.zoned \
        else (m.start.replace(tzinfo=None), m.end.replace(tzinfo=None))


def live_meetings(rec: dict, today: date | None = None) -> list[dict]:
    """The meetings an application's next step names right now, as round dicts (no id, source next_step): one for
    each clause that reads as a meeting with a time; else, past the applied stage, one with no day when the step
    names a meeting and gives no time ("panel interview, the recruiter to schedule"). None once it has ended."""
    if rec.get("status") in ENDED:
        return []
    today = today or date.today()
    step, rid, length = rec.get("next_step"), rec.get("round") or None, rounds.length_of(rec)
    whole = ics.meeting(step, today, rid, length)
    clauses = [step or ""] if whole else [c for c in re.split(r"[;\r\n]+", step or "") if c.strip()]
    found = []
    for clause in clauses:
        m = ics.meeting(clause, today, rid, length)
        if not m:
            continue
        start, end = _local(m)
        kind = rid if len(clauses) == 1 and rid else kind_from_text(clause) or rid or ""
        found.append({"kind": kind, "day": start.date().isoformat(), "time": start.strftime("%H:%M"),
                      "length": round((end - start) / timedelta(minutes=1)), "who": who_from_text(clause),
                      "mode": mode_from_text(clause), "text": " ".join(clause.split()), "source": "next_step"})
    if not found and rec.get("status") != "applied" and ics.names_meeting(step, rid):
        found.append({"kind": rid or kind_from_text(step), "day": None, "time": "", "length": length,
                      "who": who_from_text(step), "mode": mode_from_text(step),
                      "text": " ".join((step or "").split()), "source": "next_step"})
    return found


def held(item: dict, now: datetime) -> bool:
    """Whether a scheduled round's time has passed: its end if it has a time, else the end of its day."""
    if not item.get("day"):
        return False
    start = datetime.combine(date.fromisoformat(item["day"]), datetime.min.time())
    if item.get("time"):
        h, m = map(int, item["time"].split(":"))
        return start.replace(hour=h, minute=m) + timedelta(minutes=item.get("length") or rounds.DEFAULT_LENGTH) <= now
    return start + timedelta(days=1) <= now


def _same(a: dict, b: dict) -> bool:
    return (a.get("day"), a.get("time") or "") == (b.get("day"), b.get("time") or "")


def short_day(day: str | None) -> str:
    if not day:
        return ""
    d = date.fromisoformat(day)
    return f"{d:%a %b} {d.day}"


def ampm(t: str) -> str:
    h, m = map(int, t.split(":"))
    return f"{h % 12 or 12}{f':{m:02d}' if m else ''} {'AM' if h < 12 else 'PM'}"


# "a four-round interview process", "4 rounds of interviews", "interview process has 3 stages", "3-step process".
_NUMBER = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_N = r"(\d|two|three|four|five|six|seven)"
_TYPICAL = re.compile(
    rf"\b{_N}[- ](?:stage|step|round)s?(?:[- ]interview)?(?: interview)?(?: process)"
    rf"|\binterview process[^.\n]{{0,40}}?\b{_N}\s+(?:stages|steps|rounds)"
    rf"|\b{_N} rounds? of interviews?", re.I)


def typical_rounds(text: str | None) -> int | None:
    """How many rounds a posting says its process has, when it does ("a four-round interview process"), else None.
    Only a hint, shown as "typical, not confirmed"."""
    for m in _TYPICAL.finditer(text or ""):
        word = next(g for g in m.groups() if g).lower()
        n = _NUMBER.get(word) or int(word)
        if 2 <= n <= 8:
            return n
    return None


def build(rec: dict, stored: list[dict], text: str | None = None, today: date | None = None,
          now: datetime | None = None) -> dict:
    """The timeline of one application: `items` in order (each with a `state`: done, held (its time has passed and
    no outcome is recorded yet), next (the first one ahead) or scheduled (later ones)), counts, the `next` item,
    `number` (which round the next one is, else how many have happened), `typical` (a hint from the posting) and
    `chip`, the one line the lists show ("Round 3 of ? · next: Panel Mon Nov 30")."""
    today, now = today or date.today(), now or datetime.now()
    items = [dict(r) for r in stored]
    for lm in live_meetings(rec, today):
        have = any(_same(lm, r) for r in items) if lm["day"] else any(
            r["state"] == "scheduled" and not r.get("day") for r in items)
        if not have:
            items.append({**lm, "id": None, "state": "scheduled", "outcome": "", "note": ""})
    items.sort(key=lambda r: (r["state"] != "done" and not r.get("day"), r.get("day") or "", r.get("time") or ""))
    nxt = None
    for r in items:
        r["label"] = label(r["kind"])
        r["inferred"] = r.get("source") == "inferred"
        if r["state"] == "scheduled":
            if held(r, now):
                r["state"] = "held"
            elif nxt is None:
                r["state"], nxt = "next", r
    for n, r in enumerate(items, 1):
        r["number"] = n
    done = sum(r["state"] == "done" for r in items)
    late = sum(r["state"] == "held" for r in items)
    tl = {"items": items, "done": done, "held": late, "next": nxt, "typical": typical_rounds(text),
          "number": nxt["number"] if nxt else done + late or None}
    tl["chip"] = chip(tl)
    return tl


def chip(tl: dict) -> str | None:
    """The one-line summary: "Round 3 of ? · next: Panel Mon Nov 30" (of ~4 when the posting says four rounds),
    "Round 2 held · how did it go?", "2 rounds done · none scheduled", None for an application with no rounds."""
    n, done, late, nxt = tl["number"], tl["done"], tl["held"], tl["next"]
    if not n:
        return None
    of = f"~{tl['typical']}" if tl["typical"] else "?"
    if nxt:
        when = " ".join(x for x in (short_day(nxt.get("day")), nxt.get("time") and ampm(nxt["time"])) if x)
        return f"Round {n} of {of} · next: {nxt['label']}" + (f" {when}" if when else ", not dated yet")
    if late:
        return f"Round {done + late} held · how did it go?"
    return f"{done} round{'s' * (done != 1)} done · none scheduled"


def public(r: dict) -> dict:
    """A stored round row as the API and the CLI show it."""
    return {k: r.get(k) for k in ("id", "kind", "state", "day", "time", "length", "who", "mode", "outcome", "note",
                                  "source")}


# -- the backfill: done rounds proposed from the dated History lines

_ENTRY = re.compile(r"\s(?=\d{4}-\d{2}-\d{2}: )")
_LEAD_DAY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?:\s+\d{1,2}:\d{2}\s*[AP]M)?\b", re.I)
_ANY_DAY = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_SENTENCE = re.compile(r"(?<=[.;!?])\s+|\s+[-–—]\s+")
# A sentence that says the round was held (done, went well, we spoke) ...
_HELD = re.compile(r"\b(?:done|completed|finished|interviewed|spoke|talked|met|debriefed|went (?:well|badly|fine|ok)|"
                   r"did (?:well|great|fine)|thank-?you (?:note |email )?(?:sent|written)|sent (?:a )?thank-?you)\b"
                   r"|\bround:", re.I)
# ... unless it is about setting one up, waiting on it, or one that did not happen.
_SETTING_UP = re.compile(r"\b(?:schedul\w*|invit\w*|availab\w*|book(?:ed|ing)|confirm\w*|will|would|upcoming|next|"
                         r"waiting|reminder|to (?:set|arrange)|send dates|propos\w*|reply|replied|draft\w*|"
                         r"ask(?:ed)? (?:the |them )?(?:for|to)|tomorrow|prep(?:are)? for|form|"
                         r"did not|didn't|no-?show|cancel\w*|postpon\w*|reschedul\w*|if passed|not happen)\b", re.I)
_GENERIC = re.compile(r"\b(call|interview|chat|round|meeting|conversation)\b", re.I)
_WELL = re.compile(r"\b(?:went well|did (?:well|great)|advanced|moved (?:me )?(?:forward|on))\b", re.I)
_BAD = re.compile(r"\bwent badly\b", re.I)
_FAILED = re.compile(r"\b(rejected|declined|not moving forward|won't be moving|will not be moving)\b", re.I)
MAX_NOTE = 140


def _entries(note: str | None) -> list[tuple[str | None, str]]:
    """A note's dated lines, oldest first, as (day, text); text before the first dated line has no day."""
    out = []
    for part in _ENTRY.split(" ".join((note or "").split())):
        m = re.match(r"(\d{4}-\d{2}-\d{2}): (.*)$", part)
        out.append((m.group(1), m.group(2)) if m else (None, part))
    return [e for e in out if e[1]]


def _day_in(match: re.Match, near: date) -> date | None:
    mo, d, y = int(match.group(1)), int(match.group(2)), match.group(3)
    try:
        if y:
            return date(int(y) + 2000 if len(y) == 2 else int(y), mo, d)
        on = date(near.year, mo, d)
        return on if on <= near + timedelta(days=31) else date(near.year - 1, mo, d)
    except ValueError:
        return None


def infer(rec: dict, today: date | None = None) -> list[dict]:
    """The rounds an application's dated History lines say were held, as proposals (state done, source inferred,
    sorted by day), at most one for each day and kind. A line counts when one of its sentences names a round and
    says it happened ("11/13 HM round: Sam asked about ..."), not when it is about setting one up or waiting.
    The day is the one inside the sentence ("the 11/13 call"), else the line's own; a future day is never a held
    round. `who` is the people after "with"; the sentence itself is kept (shortened) as the note."""
    today = today or date.today()
    found: list[dict] = []
    for day_text, text in _entries(rec.get("note")):
        lead = _LEAD_DAY.match(text)
        if not (logged := date.fromisoformat(day_text) if day_text else today if lead else None):
            continue  # an undated line says when only by starting with its day ("11/13 HM round: ...")
        for sentence in _SENTENCE.split(text):
            if _SETTING_UP.search(sentence) or not _HELD.search(sentence):
                continue
            kind = kind_from_text(sentence)
            if not kind and not _GENERIC.search(sentence):
                continue
            inside = [d for m in _ANY_DAY.finditer(sentence) if (d := _day_in(m, logged))]
            # two days, or one ahead of the line, name other meetings: this one was held the day the line is from
            on = inside[0] if len(inside) == 1 and inside[0] <= logged else logged
            if on > today or on < logged - timedelta(days=60):
                continue
            plain = " ".join(sentence.split())
            if lead and plain.startswith(lead.group(0).strip()):
                plain = plain[len(lead.group(0).strip()):].lstrip(" :-–—")
            who = who_from_text(sentence)
            same = next((r for r in found if r["day"] == on.isoformat()
                         and (not r["kind"] or not kind or r["kind"] == kind)), None)
            if same:
                same["kind"], same["who"] = same["kind"] or kind, same["who"] or who
                continue
            outcome = "Not moving forward" if _FAILED.search(sentence) else "Went badly" if _BAD.search(
                sentence) else "Went well" if _WELL.search(sentence) else ""
            found.append({"kind": kind, "state": "done", "day": on.isoformat(), "time": "", "length": None,
                          "who": who, "mode": mode_from_text(sentence), "outcome": outcome,
                          "note": plain[:MAX_NOTE].rstrip(), "source": "inferred"})
    return sorted(found, key=lambda r: r["day"])


def new_proposals(rec: dict, stored: list[dict], today: date | None = None) -> list[dict]:
    """infer's proposals the application doesn't have yet: no stored round the same day (of the same kind, or of
    no kind either side), and not the meeting its next step names."""
    live = live_meetings(rec, today)
    return [p for p in infer(rec, today)
            if not any(r["day"] == p["day"] and (not r["kind"] or not p["kind"] or r["kind"] == p["kind"])
                       for r in [*stored, *live])]


# -- with the store

def for_job(store, job, rec: dict, stored: list[dict] | None = None, today: date | None = None,
            now: datetime | None = None) -> dict:
    """An application's timeline: its stored rounds (read here unless `stored` is given) and its next step."""
    if stored is None:
        stored = store.rounds_for([job.key]).get(job.key, [])
    return build(rec, stored, job.description, today, now)


def summaries(store, rows: list[tuple]) -> dict[str, dict]:
    """The lists' view of each application's timeline, by key: the chip, the counts, the next round and the dots
    (the states of its rounds in order), for applications that have rounds."""
    every = store.rounds_for([j.key for j, _ in rows])
    out = {}
    for job, rec in rows:
        tl = for_job(store, job, rec, every.get(job.key, []))
        if tl["items"]:
            nxt = tl["next"]
            out[job.key] = {"chip": tl["chip"], "done": tl["done"], "held": tl["held"], "number": tl["number"],
                            "typical": tl["typical"], "dots": [r["state"] for r in tl["items"]],
                            "next": nxt and {k: nxt.get(k) for k in ("kind", "label", "day", "time", "length")}}
    return out


def found_counts(store, rows: list[tuple]) -> dict:
    """How many rounds the notes could add, and to how many of these applications: for the Applications page's
    one dismissible line."""
    every = store.rounds_for([j.key for j, _ in rows])
    counts = [len(new_proposals(rec, every.get(j.key, []))) for j, rec in rows]
    return {"rounds": sum(counts), "applications": sum(bool(n) for n in counts)}


def payload(store, job, rec: dict) -> dict:
    """The Details dialog's rounds: the timeline (`next` is the number of the next round), what each kind is, and
    the rounds the History lines could add (`proposed`: offered, never written without a click)."""
    store.sync_rounds(job.key)  # the next step's meeting has a row of its own, so it can be edited
    stored = store.rounds_for([job.key]).get(job.key, [])
    tl = build(rec, stored, job.description)
    return {**tl, "next": tl["next"]["number"] if tl["next"] else None,
            "kinds": [{"id": k, "label": v[0], "help": KIND_HELP[k]} for k, v in rounds.ROUNDS.items()]
            + [{"id": "", "label": "Other interview or call", "help": KIND_HELP[""]}],
            "proposed": [] if rec.get("status") not in STAGES else new_proposals(rec, stored)}


def change(store, key: str, action: str, round_id: int | None = None, **fields) -> dict:
    """add, edit, done or delete one round of an application (fields: kind, state, day, time, length, who, mode,
    outcome, note). A round the next step names can't be moved from here (its day and time are the step's words),
    but its kind and length go to the application. Returns {"id": ...} for an add."""
    job, _ = store.find(key)
    if fields.get("kind") == "other":
        fields["kind"] = ""
    if action == "add":
        return {"id": store.add_round(job.key, **fields)}
    if round_id is None:
        raise ValueError(f"{action} needs the round's id")
    old = store.get_round(job.key, round_id)
    if action == "delete":
        store.delete_round(job.key, round_id)
    elif action == "done":
        store.finish_round(job.key, round_id, fields.pop("outcome", "") or "", fields.pop("note", None))
        if fields:
            store.edit_round(job.key, round_id, **fields)
    elif action == "edit":
        steps = old["source"] == "next_step" and old["state"] == "scheduled"
        if steps and any(k in fields and (fields[k] or "") != (old[k] or "") for k in ("day", "time")):
            raise ValueError("this round comes from the next step: change the step to move it")
        if steps:
            for name in ("kind", "length"):
                if fields.get(name) is not None:
                    store.track(job.key, **{"round" if name == "kind" else name: fields[name] or ""})
        store.edit_round(job.key, round_id, **fields)
    else:
        raise ValueError("action must be add, edit, done or delete")
    return {}


def proposals(store, only: list[str] | None = None, today: date | None = None) -> list[tuple[str, dict, list[dict]]]:
    """The backfill: (key, record, proposed rounds) for each application, or just those named (`only`)."""
    keys = {store.find(k)[0].key for k in only} if only else None
    rows = [(j, r) for j, r in store.applications() if keys is None or j.key in keys]
    every = store.rounds_for([j.key for j, _ in rows])
    return [(j.key, r, new_proposals(r, every.get(j.key, []), today)) for j, r in rows]


def apply(store, found: list[tuple[str, dict, list[dict]]]) -> int:
    """Write the proposals (source inferred). Returns how many rounds."""
    n = 0
    for key, _, props in found:
        for p in props:
            store.add_round(key, source="inferred", **{k: v for k, v in p.items() if k != "source"})
            n += 1
    return n


# -- as text, for `jobwatch rounds` and the MCP tool

def round_line(r: dict) -> str:
    """One round as a line: its id, state, when, kind, who, length, mode, outcome."""
    when = " ".join(x for x in (short_day(r.get("day")) or "no day yet", r.get("time") and ampm(r["time"])) if x)
    bits = [r["label"] if "label" in r else label(r["kind"]), f"with {r['who']}" if r.get("who") else "",
            f"{r['length']} min" if r.get("length") else "", r.get("mode") or ""]
    tail = " — ".join(x for x in (r.get("outcome"), r.get("note")) if x)
    mark = "  (inferred from your notes)" if r.get("source") == "inferred" else ""
    ident = f"#{r['id']}" if r.get("id") else "·"
    return (f"  {ident:>5}  {r.get('state', 'scheduled'):9} {when:20} {', '.join(b for b in bits if b)}"
            + (f" — {tail}" if tail else "") + mark)


def text(title: str, tl: dict) -> str:
    """A timeline as text: the title, each round, and the line for what isn't scheduled yet."""
    if not tl["items"]:
        return (f"{title}\n  No rounds yet. Add one with `jobwatch rounds KEY --add KIND --date DAY`, "
                "or set a next step.")
    hint = f" (the posting says about {tl['typical']}: typical, not confirmed)" if tl["typical"] else ""
    return "\n".join([title, *(round_line(r) for r in tl["items"]), "  Later rounds: not scheduled yet" + hint])


def backfill_text(found: list[tuple[str, dict, list[dict]]], applied: bool) -> str:
    """The backfill's proposals, for each application (key, rec, proposals): what would be written, or was."""
    out = []
    for key, rec, props in found:
        if props:
            out += [f"{key}  ({rec['status']})", *(round_line({**p, "id": None}) for p in props)]
    n, total = sum(bool(p) for _, _, p in found), sum(len(p) for _, _, p in found)
    head = f"{total} round(s) in {n} of {len(found)} application(s) " + ("written." if applied else
           "proposed. Nothing is written: look them over, then `jobwatch rounds --backfill --apply --only KEY...`.")
    return "\n".join([*out, head])
