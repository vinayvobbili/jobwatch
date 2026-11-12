"""Lists of jobs a job site showed the person, taken in to see how many jobwatch already had, and to track the rest:
LinkedIn's ("Jobs based on your preferences", "Jobs that match your profile", a search's results) and Indeed's
("Jobs for you", a search's results).

jobwatch never fetches linkedin.com or indeed.com. The list comes from the person's own browser: the extension's
"Import this list" button, or an assistant that runs the extractor (job-lists.js, printed by `jobwatch import-list
--script`) on the page in Chrome. Each record is {source, id, title, company, location, pay, posted}: source is the
site (linkedin, indeed), id its own job id (LinkedIn's job id, Indeed's job key). A record with linkedin_id (the
first extractor's) is a LinkedIn one.

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

Coverage is the share of a site's jobs that jobwatch had found before this import, per site: jobs an earlier
import added are left out of it, so a list seen twice isn't counted as caught the second time. Each run is appended
to import-list.jsonl next to the database, a line per site; `jobwatch import-list --history` shows the trend.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

from . import alerts, suggest
from .store import Store

HISTORY = "import-list.jsonl"
LOOKUP_WORKERS = 6  # companies whose boards are looked for at once
# Each site's link to one of its jobs, by its id: the form alerts.clean_link gives, so a job from an alert matches
LINKS = {"linkedin": "https://www.linkedin.com/jobs/view/{}/", "indeed": "https://www.indeed.com/viewjob?jk={}"}
NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed"}
_VERIFIED = re.compile(r"\s*(?:\((?:verified job|verified)\)|with verification)\s*$", re.I)


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

    @property
    def url(self) -> str:
        return LINKS[self.source].format(self.id) if self.id and self.source in LINKS else ""

    def to_dict(self) -> dict:
        return {"source": self.source, "id": self.id, "title": self.title, "company": self.company,
                "location": self.location, "pay": self.pay, "posted": self.posted}


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
        r = Record(title=_VERIFIED.sub("", " ".join(str(raw.get("title") or "").split())),
                   company=" ".join(str(raw.get("company") or "").split()),
                   location=" ".join(str(raw.get("location") or "").split()), pay=str(raw.get("pay") or "").strip(),
                   posted=str(raw.get("posted") or "").strip(), id=re.sub(r"[^\w-]", "", jid), source=source)
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

    def to_dict(self) -> dict:
        return {**self.record.to_dict(), "outcome": self.outcome, "key": self.key, "board": self.board or None,
                "why": self.why or None, "filtered": self.filtered}


def _counts(seen: list[Seen]) -> dict:
    n = {o: sum(s.outcome == o for s in seen) for o in ("tracked", "earlier", "added", "unplaced")}
    base = n["tracked"] + n["added"] + n["unplaced"]
    return {"seen": sum(n.values()), **n, "coverage": round(n["tracked"] / base, 4) if base else None}


@dataclass
class Result:
    seen: list[Seen] = field(default_factory=list)
    dry_run: bool = False
    at: str = ""

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(s.record.source for s in self.seen))

    def counts(self, source: str | None = None) -> dict:
        """seen, tracked, earlier, added, unplaced and coverage (tracked over the jobs earlier imports aside, 0-1,
        None with none): one site's, or all of them."""
        return _counts([s for s in self.seen if source is None or s.record.source == source])

    def to_dict(self) -> dict:
        return {"at": self.at, "dry_run": self.dry_run, **self.counts(),
                "by_source": {src: self.counts(src) for src in self.sources},
                "jobs": [s.to_dict() for s in self.seen]}


def _alert(r: Record) -> alerts.Alert:
    return alerts.Alert(r.title, r.company, r.location, r.pay.replace("/yr", ""), r.url, r.source if r.url else "",
                        via(r.source))


def _via(store: Store, key: str) -> str | None:
    try:
        return store.find(key)[1].get("via")
    except KeyError:
        return None


def take(cfg, store: Store, recs: list[Record], dry_run: bool = False, page=None, follow: bool = True,
         now: datetime | None = None) -> Result:
    """Take in a list's jobs (see the module's docstring). dry_run: nothing is recorded (not even the history);
    the result says what would be. follow=False looks for no boards: each new job is tracked as listed."""
    result = Result(dry_run=dry_run, at=(now or datetime.now(timezone.utc)).isoformat(timespec="seconds"))
    taker = alerts.Taker(cfg, store, alerts.Intake(), follow=follow, dry_run=dry_run, page=page, every=True)
    # The companies of the jobs not tracked yet have their boards looked for at once: the slow part
    if follow:
        missing = list(dict.fromkeys(r.company for r in recs if not taker.tracked.match(r.company, r.title, r.url)))
        with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
            list(pool.map(_quietly(taker.resolver.company_boards), missing))
    for r in recs:
        f = taker.take(_alert(r))
        if f is None:
            continue
        s = Seen(r, "", key=f.key, filtered=f.reason)
        if f.result == "duplicate":
            s.outcome = "repeated"
        elif f.result == "known":
            s.outcome = "earlier" if (_via(store, f.key) or "").endswith("-list") else "tracked"
            if not dry_run:  # it counts toward watching the company's board, as when it first came in
                suggest.record(store, cfg.boards, f.job, taker.resolver.looked(r.company))
        elif f.how == "email":
            s.outcome = "unplaced"
            boards = taker.resolver.looked(r.company)
            s.board = ", ".join(f"{src}:{b}" for src, b, _ in boards or [])
            s.why = ("not looked for" if boards is None else "no board found under its name" if not boards
                     else "not on its board")
        else:
            s.outcome, s.board = "added", f"{f.job.source}:{f.job.company}"
        result.seen.append(s)
    if not dry_run:
        append_history(cfg, result)
    return result


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
        if base := c["tracked"] + c["added"] + c["unplaced"]:
            out.append(f"  Coverage: {_pct(c['coverage'])} ({c['tracked']} of {base} were tracked before this "
                       "import" + ("; earlier imports aside" if c["earlier"] else "") + ").")
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
    return "\n".join(out)


def history_text(runs: list[dict], now: datetime | None = None) -> str:
    """Each run's counts and coverage, then each site's last week and whole history, jobs weighed alike."""
    if not runs:
        return "No lists imported yet: `jobwatch import-list FILE` takes one in."
    out = ["When              Site      Seen  Tracked  Earlier  Added  Unplaced  Coverage"]
    for h in runs[-40:]:
        out.append(f"{h['at'][:16].replace('T', ' '):<16}  {_name(h['source']):<8}  {h['seen']:>4}  "
                   f"{h['tracked']:>7}  {h['earlier']:>7}  {h['added']:>5}  {h['unplaced']:>8}  "
                   f"{_pct(h['coverage']):>8}")
    now = now or datetime.now(timezone.utc)
    for src in dict.fromkeys(h["source"] for h in runs):
        mine = [h for h in runs if h["source"] == src]
        week = [h for h in mine if datetime.fromisoformat(h["at"]) >= now - timedelta(days=7)]
        for label, rows in (("last 7 days", week), ("all runs", mine)):
            own = sum(h["tracked"] for h in rows)
            base = own + sum(h["added"] + h["unplaced"] for h in rows)
            out.append(f"{_name(src)}, {label}: {_pct(own / base if base else None)} of {base} job(s) were tracked "
                       "before their import.")
    return "\n".join(out)
