"""Lists of jobs a job site showed the person, taken in to see how many jobwatch already had, and to track the rest:
LinkedIn's ("Jobs based on your preferences", "Jobs that match your profile", a search's results), Indeed's
("Jobs for you", a search's results) and Ladders' ("Recommended Jobs", a search's results).

jobwatch never fetches linkedin.com, indeed.com or theladders.com. The list comes from the person's own browser: the
extension's "Read the jobs on this list" button, or an assistant that runs the extractor (job-lists.js, printed by
`jobwatch import-list --script`) on the page in Chrome. Each record is
{source, id, title, company, location, pay, posted}: source is the site (linkedin, indeed, ladders), id its own job id
(LinkedIn's job id, Indeed's job key, the number ending a Ladders job's path). A record with linkedin_id (the first
extractor's) is a LinkedIn one.

Ladders is an aggregator of the companies' own jobs, and a person applies on the company's own site, never through
Ladders (its Apply4Me is a paid service that applies for them). Its record also has url, the job's page on Ladders:
that is a reference only (a note on the job), never the job's link, and Ladders' pay (its own estimate) is in that
note too. The job's link is the company's board posting when it's found there; a job not found has no link, and its
note says to apply on the company's own site.

Each job is taken in the way an alert email's is (see alerts.py), with via "<source>-list":

- one already tracked (by its link on the site, or by its company and title, "(Verified job)", "Sr."/"Senior" and
  punctuation aside) is left alone and counted as tracked;
- a new one is looked for on the company's own board (a watched one, the one already known for the company, or the
  ones `jobwatch find` finds under its name) and tracked from there, status new. Every one is looked for, not only
  the ones that pass the filters: the filters decide what the digest shows, not what's tracked;
- a new one not found there (no board found, or the title isn't on it) is tracked from what the list says, like an
  alert's job, and listed as couldn't place; the alerts backfill keeps looking for it on the company's board.

Each company seen counts toward Companies to watch (see suggest.py), as an alert's do, so the ones a site keeps
showing get their boards watched (by hand, or by suggestions.auto_watch).

Coverage is the share of a site's jobs that jobwatch had found on its own before this import (tracked over
everything seen), per site: a job an earlier import added counts as one jobwatch missed, so a list seen twice
doesn't read as caught the second time. Each run is appended
to import-list.jsonl next to the database, a line per site; `jobwatch import-list --history` shows the trend.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from . import alerts, company, linkedin, sources, suggest
from .localday import local_day
from .store import MANUAL, Store, day

HISTORY = "import-list.jsonl"
LOOKUP_WORKERS = 6  # companies whose boards are looked for at once
LOOKUP_BUDGET = 240.0  # seconds the lookups may take in all: the extension waits on the import, so not open-ended
# Each site's link to one of its jobs, by its id: the form alerts.clean_link gives, so a job from an alert matches
LINKS = {"linkedin": "https://www.linkedin.com/jobs/view/{}/", "indeed": "https://www.indeed.com/viewjob?jk={}"}
NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "ladders": "Ladders"}
# Aggregators: the job is the company's own, and its page on the site is only a reference (kept in a note, never the
# job's link): the person applies on the company's own site, never through the aggregator
REFERENCE = {"ladders": re.compile(r"https://www\.theladders\.com/job/[\w-]+_\d+")}
_VERIFIED = re.compile(r"\s*(?:\((?:verified job|verified)\)|with verification)\s*$", re.I)
# LinkedIn's screen-reader text that ends up in a card's text (job-lists.js cleanTitle has the same rules)
_SELECTED_MID = re.compile(r"^(.+?)\s*:\s*selected\s*,\s*(.+)$", re.I)
_SELECTED_LEAD = re.compile(r"^selected\s*[,:]\s*", re.I)
_TWICE = re.compile(r"^(.{3,}?)(?:\s*[:|–—-]\s*|\s+)\1$", re.I)


def clean_title(title: str) -> str:
    """A listed title as the job has it: "(Verified job)" / "with verification", the selected card's "<title>:
    Selected, <title>", a leading "Selected," and the title said twice ("T T", "T: T", "T - T") are taken off."""
    t = " ".join(str(title or "").split())
    for _ in range(3):
        before = t
        t = _VERIFIED.sub("", t).strip()
        if m := _SELECTED_MID.match(t):
            t = m.group(1)
        t = _SELECTED_LEAD.sub("", t)
        if m := _TWICE.match(t):
            t = m.group(1)
        t = t.strip()
        if t == before:
            break
    return t


def script() -> str:
    """The extractor that reads a job list page in the browser (job-lists.js)."""
    return resources.files("jobwatch").joinpath("static/job-lists.js").read_text(encoding="utf-8")


def via(source: str) -> str:
    return f"{source}-list"


@dataclass
class Record:
    title: str
    company: str
    location: str = ""
    pay: str = ""
    posted: str = ""
    id: str = ""
    source: str = "linkedin"
    link: str = ""  # an aggregator's page for the job (see REFERENCE)

    @property
    def reference(self) -> bool:
        return self.source in REFERENCE

    @property
    def url(self) -> str:
        if self.reference:
            return self.link
        return LINKS[self.source].format(self.id) if self.id and self.source in LINKS else ""

    def to_dict(self) -> dict:
        return {"source": self.source, "id": self.id, "title": self.title, "company": self.company,
                "location": self.location, "pay": self.pay, "posted": self.posted,
                **({"url": self.link} if self.link else {})}


def _reference_link(source: str, url) -> str:
    """An aggregator's own page for a job, without its query: '' for anything but one of its job pages."""
    pattern = REFERENCE.get(source)
    m = pattern.match(str(url or "").strip()) if pattern else None
    return m.group(0) if m else ""


def records(data) -> list[Record]:
    """The records in what the extractor gave: a list of them, or {"records": [...]}, or the JSON text of either.
    Titles lose "(Verified job)"; a record with no title or company is left out, and one job listed twice is kept
    once."""
    if isinstance(data, (str, bytes)):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        try:
            data = json.loads(text) if text.strip() else []
        except json.JSONDecodeError as e:
            raise ValueError(f"not the extractor's JSON: {e}") from None
    if isinstance(data, dict):
        data = data.get("records", data.get("jobs"))
    if not isinstance(data, list):
        raise ValueError("expected a list of job records ({source, id, title, company, location, pay, posted})")
    out, ids = [], set()
    for raw in data:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or ("indeed" if raw.get("jk") else "linkedin")).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9]{1,20}", source):
            raise ValueError(f"a record's source is a site's name (linkedin, indeed), got {source!r}")
        jid = str(raw.get("id") or raw.get("linkedin_id") or raw.get("jk") or "").strip()
        r = Record(title=clean_title(raw.get("title")),
                   company=linkedin.unrated(" ".join(str(raw.get("company") or "").split())),
                   location=" ".join(str(raw.get("location") or "").split()), pay=str(raw.get("pay") or "").strip(),
                   posted=str(raw.get("posted") or "").strip(), id=re.sub(r"[^\w-]", "", jid), source=source,
                   link=_reference_link(source, raw.get("url")))
        if not (r.title and r.company) or (r.id and (r.source, r.id) in ids):
            continue
        ids.add((r.source, r.id))
        out.append(r)
    return out


@dataclass
class Seen:
    record: Record
    outcome: str        # tracked (jobwatch had it), earlier (an earlier import added it), added (found on the
    #                     company's board), unplaced (tracked from the list's text), repeated (twice in the list)
    key: str = ""
    board: str = ""     # added: the board it's on; unplaced: the boards looked on, if any
    why: str = ""       # unplaced: no board found under its name, or not on that board
    filtered: str | None = None  # why the filters leave it out of the digest; None: it's in
    upgraded: bool = False  # earlier: kept as listed by an earlier import, now found on its board (board says which)

    def to_dict(self) -> dict:
        return {**self.record.to_dict(), "outcome": self.outcome, "key": self.key, "board": self.board or None,
                "why": self.why or None, "filtered": self.filtered, "upgraded": self.upgraded}


def _counts(seen: list[Seen]) -> dict:
    n = {o: sum(s.outcome == o for s in seen) for o in ("tracked", "earlier", "added", "unplaced")}
    total = sum(n.values())
    return {"seen": total, **n, "coverage": round(n["tracked"] / total, 4) if total else None,
            "upgraded": sum(s.upgraded for s in seen), "note": _repeat_note(n, total)}


def _repeat_note(n: dict, total: int) -> str | None:
    """Said when most of a list was added by an earlier import: this run found little that's new."""
    if not total or n["earlier"] * 2 < total:
        return None
    new = n["added"] + n["unplaced"]
    return "Same list as before: nothing new" if not new else f"Mostly the same list as before: {new} new"


@dataclass
class Result:
    seen: list[Seen] = field(default_factory=list)
    dry_run: bool = False
    at: str = ""
    cut: int = 0  # companies whose board lookup ran out of the budget: their jobs are tracked from the list

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(s.record.source for s in self.seen))

    def counts(self, source: str | None = None) -> dict:
        """seen, tracked, earlier, added, unplaced, coverage (tracked over seen, 0-1, None with none) and note
        (said when most of the list was added by an earlier import): one site's, or all of them."""
        return _counts([s for s in self.seen if source is None or s.record.source == source])

    def to_dict(self) -> dict:
        return {"at": self.at, "dry_run": self.dry_run, **self.counts(),
                "by_source": {src: self.counts(src) for src in self.sources},
                "jobs": [s.to_dict() for s in self.seen]}


def _alert(r: Record) -> alerts.Alert:
    if r.reference:  # the pay is the aggregator's own estimate: kept in the note, not as the job's pay
        aside = f"Its pay estimate (not the employer's): {r.pay}." if r.pay else ""
        return alerts.Alert(r.title, r.company, r.location, "", r.url, r.source if r.url else "", via(r.source),
                            reference=True, aside=aside)
    return alerts.Alert(r.title, r.company, r.location, r.pay.replace("/yr", ""), r.url, r.source if r.url else "",
                        via(r.source))


def _via(store: Store, key: str) -> str | None:
    try:
        return store.find(key)[1].get("via")
    except KeyError:
        return None


def take(cfg, store: Store, recs: list[Record], dry_run: bool = False, page=None, follow: bool = True,
         now: datetime | None = None, budget: float = LOOKUP_BUDGET) -> Result:
    """Take in a list's jobs (see the module's docstring). dry_run: nothing is recorded (not even the history);
    the result says what would be. follow=False looks for no boards: each new job is tracked as listed. The boards
    are looked for `budget` seconds at most; a company not done by then is tracked as listed (Result.cut)."""
    result = Result(dry_run=dry_run, at=(now or datetime.now(UTC)).isoformat(timespec="seconds"))
    taker = alerts.Taker(cfg, store, alerts.Intake(), follow=follow, dry_run=dry_run, page=page, every=True)
    # The companies of the jobs not tracked yet have their boards looked for at once: the slow part
    cut: set[str] = set()
    if follow:
        def wants_board(r: Record) -> bool:
            key = taker.tracked.match(r.company, r.title, r.url)
            return not key or ((_via(store, key) or "").endswith("-list") and _textless(taker.tracked.get(key)))
        missing = list(dict.fromkeys(r.company for r in recs if wants_board(r)))
        pool = ThreadPoolExecutor(max_workers=LOOKUP_WORKERS)
        try:
            lookups = {pool.submit(_quietly(taker.resolver.company_boards), c): c for c in missing}
            _, late = wait(lookups, timeout=budget)
        finally:  # a lookup still running is left to end by itself: nothing waits for it
            pool.shutdown(wait=False, cancel_futures=True)
        for f in late:
            key = linkedin._bare(lookups[f])
            cut.add(key)
            taker.resolver.found_boards.setdefault(key, [])  # not looked for again, one by one, below
        result.cut = len(cut)
    for r in recs:
        f = taker.take(_alert(r))
        if f is None:
            continue
        s = Seen(r, "", key=f.key, filtered=f.reason)
        if f.result == "duplicate":
            s.outcome = "repeated"
        elif f.result == "known":
            via_list = (_via(store, f.key) or "").endswith("-list")
            s.outcome = "earlier" if via_list else "tracked"
            if via_list and follow and _textless(f.job):  # kept as listed before: look for it on its board again
                found = _on_board(taker, r)
                if found:
                    s.upgraded, s.board = True, f"{found.source}:{found.company}"
                    if not dry_run:
                        alerts.fill_from_board(store, f.job, found)
                else:
                    s.why = _why(taker, r, cut)
                    if not dry_run:
                        store.set_unplaced(f.key, s.why)
            if not dry_run:  # it counts toward watching the company's board, as when it first came in
                suggest.record(store, cfg.boards, f.job, taker.resolver.looked(r.company))
        elif f.how == "email":
            s.outcome = "unplaced"
            boards = taker.resolver.looked(r.company)
            s.board = ", ".join(f"{src}:{b}" for src, b, _ in boards or [])
            s.why = _why(taker, r, cut)
            if not dry_run:
                store.set_unplaced(f.key, s.why)  # for `import-list --unplaced`
        else:
            s.outcome, s.board = "added", f"{f.job.source}:{f.job.company}"
        result.seen.append(s)
    if not dry_run:
        append_history(cfg, result)
    return result


def _textless(job) -> bool:
    return job.source == MANUAL and not job.description.strip()


def _on_board(taker, r: Record):
    try:
        return taker.resolver.on_board(r.title, r.company, r.location)
    except sources.SourceError:
        return None


def _why(taker, r: Record, cut: set[str] = frozenset()) -> str:
    if linkedin._bare(r.company) in cut:
        return "lookup ran out of time"
    boards = taker.resolver.looked(r.company)
    return "not looked for" if boards is None else "no board found under its name" if not boards \
        else "not on its board"


def _quietly(fn):
    def run(arg):
        try:
            return fn(arg)
        except Exception:  # a board that can't be read now is looked for again when its job is taken in
            return None
    return run


def history_path(cfg) -> Path:
    return Path(cfg.state).parent / HISTORY


def append_history(cfg, r: Result):
    """A line per site in the run: its counts and the jobs it couldn't place."""
    path = history_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for src in r.sources:
            entry = {"at": r.at, "source": src, **r.counts(src)}
            entry["unplaced_jobs"] = [{"company": s.record.company, "title": s.record.title,
                                       "location": s.record.location, "key": s.key, "why": s.why}
                                      for s in r.seen if s.outcome == "unplaced" and s.record.source == src]
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def history(cfg, source: str | None = None) -> list[dict]:
    """Every run so far (a line per site), oldest first: one site's, or all."""
    path = history_path(cfg)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            h = json.loads(line)
        except json.JSONDecodeError:
            continue
        h.setdefault("source", "linkedin")
        if source is None or h["source"] == source:
            out.append(h)
    return out


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def _name(source: str) -> str:
    return NAMES.get(source, source.title())


def summary(r: Result) -> str:
    out = []
    for src in r.sources:
        c = r.counts(src)
        out.append(f"{'Dry run: nothing recorded. ' if r.dry_run else ''}{_name(src)}: seen {c['seen']} job(s), "
                   f"{c['tracked'] + c['earlier']} already tracked"
                   + (f" ({c['earlier']} added by an earlier import)" if c["earlier"] else "")
                   + f", {c['added']} {'would be ' if r.dry_run else ''}added from the company's board, "
                   f"{c['unplaced']} couldn't place.")
        if c["seen"]:
            out.append(f"  Coverage: {_pct(c['coverage'])} ({c['tracked']} of {c['seen']} were found by jobwatch "
                       "itself, not added by an import).")
        if c["note"]:
            out.append(f"  {c['note']}.")
        if c["upgraded"]:
            were = "would be" if r.dry_run else "were"
            out.append(f"  {c['upgraded']} job(s) an earlier import kept as listed {were} moved onto their "
                       "company's board.")
    if r.cut:
        out.append(f"{r.cut} company's board lookup ran out of time: their jobs are tracked from the list, and "
                   "found on their boards when those are watched or the list is read again.")
    if not r.seen:
        out.append("No jobs in the list.")
    if added := [s for s in r.seen if s.outcome == "added"]:
        out.append("Added (status new):")
        out += [f"  {s.key}  {s.record.company}: {s.record.title}"
                + (f"  [filtered: {s.filtered}]" if s.filtered else "") for s in added]
    if unplaced := [s for s in r.seen if s.outcome == "unplaced"]:
        out.append("Couldn't place" + (" (tracked from the list's text: watch the company's board, then `jobwatch "
                                       "alerts --backfill --again` finds each there)" if not r.dry_run else "") + ":")
        out += [f"  {s.record.company}: {s.record.title}" + (f" ({s.record.location})" if s.record.location else "")
                + f"  {s.why}" + (f" ({s.board})" if s.board else "")
                + (f"  `{s.key}`" if s.key and not r.dry_run else "") for s in unplaced]
    if still := [s for s in r.seen if s.outcome == "earlier" and s.why]:
        out.append("Kept as listed by an earlier import, still not found on a board:")
        out += [f"  {s.record.company}: {s.record.title}  {s.why}" + (f" ({s.board})" if s.board else "")
                for s in still]
    return "\n".join(out)


def _utc(stamp: str) -> datetime:
    at = datetime.fromisoformat(stamp)
    return at if at.tzinfo else at.replace(tzinfo=UTC)  # an old row with no offset is UTC too


def _local_when(stamp: str) -> str:
    """A stored run time (UTC) as this computer's clock reads it."""
    try:
        return _utc(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp[:16].replace("T", " ")


def history_text(runs: list[dict], now: datetime | None = None) -> str:
    """Each run's counts and coverage, then each site's last week and whole history, jobs weighed alike."""
    if not runs:
        return "No lists imported yet: `jobwatch import-list FILE` takes one in."
    out = ["When              Site      Seen  Tracked  Earlier  Added  Unplaced  Coverage"]
    for h in runs[-40:]:
        out.append(f"{_local_when(h['at']):<16}  {_name(h['source']):<8}  {h['seen']:>4}  "
                   f"{h['tracked']:>7}  {h['earlier']:>7}  {h['added']:>5}  {h['unplaced']:>8}  "
                   # worked out here: older rows kept another figure
                   f"{_pct(h['tracked'] / h['seen'] if h['seen'] else None):>8}")
    now = now or datetime.now(UTC)
    for src in dict.fromkeys(h["source"] for h in runs):
        mine = [h for h in runs if h["source"] == src]
        week = [h for h in mine if _utc(h["at"]) >= now - timedelta(days=7)]
        for label, rows in (("last 7 days", week), ("all runs", mine)):
            own = sum(h["tracked"] for h in rows)
            base = sum(h["seen"] for h in rows)
            out.append(f"{_name(src)}, {label}: {_pct(own / base if base else None)} of {base} job(s) were found "
                       "by jobwatch itself.")
    return "\n".join(out)


def _history_why(cfg) -> dict[str, str]:
    """Why each job couldn't be placed, by key, from the runs kept before the store recorded it (the latest run's
    reason wins)."""
    return {u["key"]: u["why"] for h in history(cfg) for u in h.get("unplaced_jobs", [])
            if u.get("key") and u.get("why")}


def _inferred_why(store: Store, looked: dict[str, dict], job) -> str:
    """A best guess at why an older job wasn't placed, from what's known of its company now: a board found for it
    (looked at by suggest.look_up, or tracked from a board) means the job isn't on it; a company looked for with
    none found, or never looked for, has no board under its name."""
    row = looked.get(suggest.company_id(job.display_company))
    if row and row["entry"]:
        return "not on its board"
    if row and row["entry"] == "":
        return "no board found under its name"
    return "not on its board" if company.on_a_board(store, job.display_company) else "no board found under its name"


def unplaced(cfg, store: Store, source: str | None = None, since: str | None = None) -> list[dict]:
    """The jobs the list imports tracked from the list's text alone (not found on the company's board), newest
    first: company, title, location, source (the site), key, why (no board found under its name, or not on its
    board; or why the lookup didn't run), why_source (recorded: the import said so; history: the import's kept
    run said so; inferred: a guess from what's known of the company now, for a job imported before the reason
    was kept), first_seen, status, closed and url. source: only that site's; since: only those first seen on or
    after that day (see store.day)."""
    since = day(since) if since else None
    said = _history_why(cfg)
    looked = {r["company"]: r for r in store.unwatched(dismissed=True)}
    out = []
    for job, rec in store.unplaced_list_jobs(since):
        site = rec["via"].removesuffix("-list")
        if source and site != source.strip().lower():
            continue
        why, how = ((rec["why"], "recorded") if rec.get("why") else (said[job.key], "history") if job.key in said
                    else (_inferred_why(store, looked, job), "inferred"))
        out.append({"company": job.display_company, "title": job.title, "location": "; ".join(job.places),
                    "source": site, "key": job.key, "why": why, "why_source": how,
                    "first_seen": local_day(rec["first_seen"]), "status": rec["status"],
                    "closed": bool(rec["closed"]), "url": job.url or None})
    return out


def unplaced_text(rows: list[dict], source: str | None = None, since: str | None = None) -> str:
    """`jobwatch import-list --unplaced`: the jobs to read."""
    if not rows:
        return ("No job tracked from " + (f"{_name(source.lower())} " if source else "a ") + "list's text alone"
                + (f" since {day(since)}" if since else "") + ".")
    out = [f"{len(rows)} job{'s' * (len(rows) != 1)} tracked from a list's text alone, not found on the company's "
           "board, newest first:", ""]
    for j in rows:
        facts = [_name(j["source"]), f"first seen {j['first_seen']}",
                 j["why"] + (" (guessed)" if j["why_source"] == "inferred" else "")]
        if j["status"] not in ("new", "shown"):
            facts.append(j["status"])
        if j["closed"]:
            facts.append("posting closed")
        out += [f"  {j['company']}: {j['title']}" + (f" ({j['location']})" if j["location"] else ""),
                f"    {' · '.join(facts)}", f"    `{j['key']}`"]
    return "\n".join(out)
