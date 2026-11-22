"""A daily launchd job (macOS) that reads the job-alert emails in the mailbox set in alerts.imap: `jobwatch alerts
--imap` once a day at 9:15, over the last few days, for one sender (Built In's, by default) or all.

The page already reads the mailbox every alerts.imap.every while it runs; this is for the times it doesn't (it's
stopped, the Mac was asleep) and for mail that skips the Inbox, which is read from alerts.imap.folder, so point that
at All Mail. Reading twice is harmless: jobs already tracked are left alone. A Mac asleep at 9:15 runs it on waking.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from .service import ServiceError, _domain, _launchctl, _mac

LABEL = "io.github.jobwatch.alerts"
HOUR, MINUTE = 9, 15
DAYS = 7  # a week of overlap, so a few days off (or a failed run) lose nothing
SENDER = "builtin.com"


class AlertsJobError(ValueError):
    pass


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-alerts.log"


def definition(config: Path, senders: tuple[str, ...] = (SENDER,), days: int = DAYS) -> dict:
    """The launchd job: this Python and jobwatch, once a day. No senders: every sender in alerts.imap.senders."""
    args = [sys.executable, "-m", "jobwatch.cli", "-c", str(config), "alerts", "--imap", "--days", str(days)]
    for who in senders:
        args += ["--sender", who]
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "Nice": 10,
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }


def install(config: Path, senders: tuple[str, ...] = (SENDER,), days: int = DAYS) -> str:
    """Write and load the daily job (replacing one installed before); says when it runs."""
    try:
        _mac()
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        log_path().parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
        with path.open("wb") as f:
            plistlib.dump(definition(config.expanduser().resolve(), senders, days), f)
        _launchctl("bootstrap", _domain(), str(path))
    except ServiceError as e:
        raise AlertsJobError(str(e)) from None
    return f"daily at {HOUR}:{MINUTE:02d}"


def uninstall() -> bool:
    """Stop the daily job and remove it; False if it wasn't installed."""
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    if not plist_path().exists():
        return False
    plist_path().unlink()
    return True
