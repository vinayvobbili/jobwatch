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
from .store import IN_PROGRESS, Store

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
    `application`; applications first, each group newest closed first."""
    rows = [{**n, "day": local_day(n["closed"]), "application": n["status"] in APPLICATIONS}
            for n in store.closed_notices(untold)]  # newest closed first
    return sorted(rows, key=lambda n: not n["application"])


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
    show(title, body)
    store.mark_closed_notified([n["key"] for n in notices])
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
