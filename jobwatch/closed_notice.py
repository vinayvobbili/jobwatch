"""Closed-posting notices: tell you when a posting you care about has been taken down, instead of a quiet gray chip.

A posting that closes for an application in any open stage (applied, screening, interviewing, offer), or for a job
you queued, becomes a notice, kept until you clear it ("Got it" in the Closed postings strip at the top of
Applications, or `jobwatch notify-closed --clear`). Clearing only hides the notice: the job stays tracked as it was.
Jobs on Today that you never acted on get none: they come and go all day.
Notices come from the closed marks the fetch and the daily posting check already write (see watch.check_daily), so
nothing here reads a board.

`jobwatch notify-closed` is the daily popup: one macOS notification summarising the notices not yet told, applications
first. It runs the daily posting check first (a job checked within the last 12 hours isn't checked again), so the
popup rests on a fresh look even when the fetch runs less than daily. `--install` runs it every day at 9:00 through
launchd; `--dry-run` prints what it would say and changes nothing; `--test` pops a sample.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .service import ServiceError, _domain, _launchctl, _mac
from .store import IN_PROGRESS, STATUSES, Store, closed_state

LABEL = "io.github.jobwatch.notify-closed"
HOUR, MINUTE = 9, 0
WINDOW_DAYS = 14   # a posting that closed longer ago than this is old news: not a notice
FRESH = timedelta(hours=12)  # a posting checked this recently isn't checked again by the popup's own check
SHOWN = 3          # lines of 'Company: Title' in the popup; the rest are '+N more'
APPLICATIONS = IN_PROGRESS
WANTED = (*APPLICATIONS, "queued")  # applications first, queued jobs second


class NoticeError(ValueError):
    pass


def local_day(stamp: str | None) -> str | None:
    """The calendar day on this computer of one of the store's UTC stamps."""
    return datetime.fromisoformat(stamp).astimezone().date().isoformat() if stamp else None


def collect(store: Store, today: date | None = None) -> list[str]:
    """Make a notice of each wanted job whose posting closed in the last WINDOW_DAYS and has none yet; drop the
    notices of jobs that reopened or moved on. Returns the keys of the new ones. Run it as often as you like."""
    now = datetime.combine(today, datetime.min.time()).astimezone(timezone.utc) if today else datetime.now(timezone.utc)
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat(timespec="microseconds")
    return store.record_closed_notices(WANTED, since)


def unseen(store: Store, untold: bool = False) -> list[dict]:
    """The notices not dismissed (not yet told in the popup, if `untold`), each with `day` (when it closed) and
    `application` and `action` (see action_for); applications first, each group newest closed first."""
    rows = [{**n, "day": local_day(n["closed"]), "application": n["status"] in APPLICATIONS,
             "action": action_for(n["status"])} for n in store.closed_notices(untold)]  # newest closed first
    return sorted(rows, key=lambda n: not n["application"])


ACTIONS = {"close": ("applied", "closed", "closed by company"), "skip": ("queued", "skipped", "skipped")}
# action: (the one status it applies to, the status it sets, what the note says). A screening, interviewing or offer
# application has no action: a closed posting there usually only means they stopped advertising it.


def action_for(status: str) -> str | None:
    """The action the Closed postings strip offers a notice at this status: 'close' (mark it Closed by company) for
    an application that is only applied, 'skip' for a queued job, none for the rest (an application in process gets
    'Got it' only)."""
    return next((name for name, (at, _, _) in ACTIONS.items() if at == status), None)


def act(store: Store, action: str, keys: list[str] | None = None) -> list[dict]:
    """Mark applied applications Closed by company, or skip queued jobs, whose notices are showing, through the
    store's own status and note functions: the status is set, the dated note 'Posting closed <day>: closed by
    company' (or 'skipped') is added and the notice is cleared. `keys`: these notices only (each must be one this
    action applies to; ValueError
    otherwise); none: every showing notice it applies to. Returns what undo() needs, one record per job."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    at, to, word = ACTIONS[action]
    showing = {n["key"]: n for n in unseen(store)}
    if keys is None:
        keys = [k for k, n in showing.items() if n["status"] == at]
    for key in keys:
        if key not in showing:  # a notice cleared ("Got it"), or a Queue card: closed on two looks is enough
            try:
                job, rec = store.find(key)
            except KeyError:
                raise ValueError(f"{key} has no closed-posting notice showing") from None
            if closed_state(rec) != "closed":
                raise ValueError(f"{job.display_company}: {job.title}: its posting isn't confirmed closed")
            showing[key] = {"key": job.key, "company": job.display_company, "title": job.title,
                            "status": rec["status"], "day": local_day(rec["closed"])}
        if showing[key]["status"] != at:
            raise ValueError(f"{showing[key]['company']}: {showing[key]['title']} is {showing[key]['status']}: "
                             f"{action} only applies to {at} jobs")
    undo = []
    for key in keys:
        _, rec = store.find(key)
        undo.append({"key": key, "status": rec["status"], "note": rec["note"] or ""})
        store.set_status([key], to)
        store.add_note(key, f"Posting closed {showing[key]['day']}: {word}")
        store.dismiss_closed_notices([key])
    return undo


def undo(store: Store, records: list[dict]) -> int:
    """Put back what act() changed: each job's status and note, and its notice. Returns how many."""
    for r in records:
        if not (isinstance(r, dict) and isinstance(r.get("key"), str) and r.get("status") in STATUSES
                and isinstance(r.get("note", ""), str)):
            raise ValueError("undo needs records of key, status and note")
    for r in records:
        store.find(r["key"])
        store.set_status([r["key"]], r["status"])
        store.track(r["key"], note=r.get("note", ""))
    store.restore_closed_notices([r["key"] for r in records])
    return len(records)


def verify(store: Store, keys: list[str], get=None, page=None, watched=(), reopen_unknown: bool = False) -> list:
    """Look at these jobs' postings again, now (watch.check_postings): the ones found open are reopened and lose
    their notices; the ones found closed again stay (and count as confirmed when the mark is old enough). A posting
    that can't be told either way (maintenance, an outage, a refusal) is 'unknown': left as it is, or with
    `reopen_unknown` reopened too, since closed needs positive evidence. Returns the watch.Check of each."""
    from .watch import check_postings  # watch imports this module for its own notes
    checks = check_postings(store, get=get, page=page, watched=watched, jobs=[store.find(k) for k in keys])
    if reopen_unknown:
        for c in checks:
            if c.result == "unknown":
                store.set_closed(c.job.key, False)
    collect(store)  # drops the notices of the reopened
    return checks


def recheck(cfg, store: Store, get=None, page=None) -> str:
    """Look again at every wanted job marked closed (the Closed postings strip's, pending ones too) and keep the
    mark only where the posting is positively closed: a job found open, or that can't be told (maintenance, an
    outage, a refusal), is reopened and loses its notice. Returns one line per job, grouped by outcome."""
    keys = [j.key for j, r in store.jobs(WANTED, include_closed=True) if r["closed"]]
    checks = verify(store, keys, get, page, cfg.boards, reopen_unknown=True)
    groups: dict[str, list[str]] = {"closed": [], "open": [], "unknown": []}
    for c in checks:
        why = f" ({c.detail})" if c.detail and c.result != "closed" else ""
        groups["open" if c.result in ("open", "reopened") else c.result].append(
            f"  {c.job.display_company}: {c.job.title}{why}")
    lines = [f"Looked again at {len(checks)} jobs marked closed."]
    for result, what in (("closed", "still closed (positive evidence)"), ("open", "open: reopened"),
                         ("unknown", "could not be told (maintenance, an outage, a refusal): reopened")):
        if groups[result]:
            lines += [f"{len(groups[result])} {what}:", *groups[result]]
    return "\n".join(lines)


def summary(notices: list[dict], shown: int = SHOWN) -> tuple[str, str]:
    """(title, body) of the popup: how many postings closed, up to `shown` 'Company: Title' lines, '+N more'."""
    n = len(notices)
    lines = [f"{x['company']}: {x['title']}" for x in notices[:shown]]
    if n > shown:
        lines.append(f"+{n - shown} more")
    return f"jobwatch: {n} posting{'s' * (n != 1)} closed", "\n".join(lines)


def popup(title: str, body: str):
    """A macOS notification through osascript (nothing to install). The text goes in as arguments, never into the
    script, so a title with a quote or a backslash can't break out of it."""
    if sys.platform != "darwin":
        raise NoticeError("the popup is macOS only: use --dry-run to read what it would say")
    script = ["on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run"]
    r = subprocess.run(["osascript", *(a for line in script for a in ("-e", line)), body or " ", title],
                       capture_output=True, text=True, check=False)
    if r.returncode:
        raise NoticeError(f"osascript failed: {r.stderr.strip() or r.stdout.strip() or r.returncode}")


def run(cfg, store: Store, dry_run: bool = False, test: bool = False, get=None, page=None, show=popup) -> str:
    """The daily popup. Checks the open applications' and queued jobs' postings first (see watch.check_daily), notes
    the ones that closed, and tells the ones not told before in one notification, then marks them told. `dry_run`
    reads and prints only (it reads no board and tells no one); `test` pops a sample. Returns what to print."""
    if test:
        title, body = summary([{"company": "Initech", "title": "Principal Architect"},
                               {"company": "Globex", "title": "Staff Engineer"}])
        show(title, body)
        return f"Popped a test notification: {title}\n{body}"
    warning = ""
    if not dry_run:
        from .watch import check_daily  # watch imports this module for its own notes
        try:
            check_daily(store, get, page, cfg.boards, every=FRESH)
        except Exception as e:  # a stale look is better than no popup
            warning = f"The postings could not be checked ({e}); going on what is known.\n"
    collect(store)
    notices = unseen(store, untold=True)
    if not notices:
        return warning + "No newly closed postings."
    title, body = summary(notices)
    if dry_run:
        return f"{warning}Would say:\n{title}\n{body}"
    # just before telling, look at each posting once more: a blip, or a posting that came back, is not news
    still = {c.job.key for c in verify(store, [n["key"] for n in notices], get, page, cfg.boards)
             if c.result == "closed"}
    held = len(notices) - len(still)
    notices = [n for n in notices if n["key"] in still]
    if not notices:
        return f"{warning}No newly closed postings ({held} could not be confirmed just now, so nobody was told)."
    title, body = summary(notices)
    show(title, body)
    store.mark_closed_notified([n["key"] for n in notices])
    store.log("boards", f"Told you {len(notices)} posting{'s' * (len(notices) != 1)} taken down",
              detail=[f"{n['company']}: {n['title']}" for n in notices], by="schedule",
              jobs=[n["key"] for n in notices])
    return f"{warning}{title}\n{body}"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-notify-closed.log"


def definition(config: Path) -> dict:
    """The launchd job: this Python and jobwatch, once a day at 9:00. A Mac asleep then runs it when it wakes."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobwatch.cli", "-c", str(config), "notify-closed"],
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "Nice": 10,
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }


def install(config: Path) -> str:
    """Write and load the daily job (replacing one installed before); says when it runs."""
    try:
        _mac()
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        log_path().parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
        with path.open("wb") as f:
            plistlib.dump(definition(config.expanduser().resolve()), f)
        _launchctl("bootstrap", _domain(), str(path))
    except ServiceError as e:
        raise NoticeError(str(e)) from None
    return f"daily at {HOUR}:{MINUTE:02d}"


def uninstall() -> bool:
    """Stop the daily job and remove it; False if it wasn't installed."""
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    if not plist_path().exists():
        return False
    plist_path().unlink()
    return True
