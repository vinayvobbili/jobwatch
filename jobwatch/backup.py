"""A dated copy of what can't be fetched again, in a folder that leaves the machine (a synced drive).

Everything jobwatch knows lives in one folder on this computer: the database (every job, status, note and score) and
the packages (what you sent with each application). `jobwatch backup` writes them to one .tar.gz, with the watchlist
and the connections file, and keeps the newest few. `--install` runs it daily through launchd.

Left out: the page's extension token (a secret, and made again) and the LCA filings (downloaded again with `lca
update`). The database is copied with SQLite's own backup, so a check or a score running at the time can't tear it,
and the copy is checked before it's kept.

To restore, stop the page, unpack into jobwatch's folder (by default ~/.local/share/jobwatch), and put the watchlist
back: `jobwatch backup --list` shows what an archive holds.
"""

from __future__ import annotations

import os
import plistlib
import re
import socket
import sqlite3
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path

from .config import Config
from .service import ServiceError, _domain, _launchctl, _mac

LABEL = "io.github.jobwatch.backup"
KEEP = 30
HOUR, MINUTE = 9, 30
DRIVES = ("~/Google Drive/My Drive", "~/Dropbox", "~/OneDrive")  # the first of these that exists holds the backups
FALLBACK = "~/jobwatch-backups"
_ARCHIVE = re.compile(r"jobwatch-\d{4}-\d{2}-\d{2}\.tar\.gz$")


class BackupError(ValueError):
    pass


def default_dest() -> Path:
    """<a synced drive>/Backups/jobwatch/<this computer>, or a folder at home with a warning (see backup) if there's
    no synced drive: a copy on the same disk doesn't survive that disk."""
    name = socket.gethostname().split(".")[0]
    for drive in DRIVES:
        if (root := Path(drive).expanduser()).is_dir():
            return root / "Backups" / "jobwatch" / name
    return Path(FALLBACK).expanduser()


def parts(cfg: Config) -> list[tuple[Path, str]]:
    """(file or folder, its name in the archive) for what's there, the database apart (see _copy_db)."""
    home = cfg.state.parent
    found = [(home / "packages", "packages"), (home / "resume", "resume"), (cfg.path, f"config/{cfg.path.name}")]
    if cfg.connections:
        found.append((cfg.connections, f"config/{cfg.connections.name}"))
    return [(p, name) for p, name in found if p.exists()]


def _copy_db(source: Path, to: Path):
    """A whole copy of the database, however busy it is, checked before it's trusted."""
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=60)
    out = sqlite3.connect(to)
    try:
        src.backup(out)
        if (said := out.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            raise BackupError(f"the copy of {source} failed its check: {said}")
    finally:
        out.close()
        src.close()


def archives(dest: Path) -> list[Path]:
    """The backups in this folder, newest first; nothing else in it is ever touched."""
    return sorted((p for p in dest.iterdir() if _ARCHIVE.fullmatch(p.name)), key=lambda p: p.name, reverse=True) \
        if dest.is_dir() else []


def backup(cfg: Config, dest: Path, keep: int = KEEP, day: date | None = None) -> tuple[Path, list[Path]]:
    """Write today's archive (replacing one from earlier today) and drop all but the newest `keep`. Returns the
    archive and the ones dropped. It appears only when whole: an interrupted run leaves the last good one alone."""
    if keep < 1:
        raise BackupError("keep at least one backup")
    if not cfg.state.is_file():
        raise BackupError(f"no database at {cfg.state}: nothing to back up")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"jobwatch-{(day or date.today()).isoformat()}.tar.gz"
    partial = target.with_name(target.name + ".partial")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            _copy_db(cfg.state, db)
            with tarfile.open(partial, "w:gz") as tar:
                tar.add(db, arcname="state.db")
                for path, name in parts(cfg):
                    tar.add(path, arcname=name)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    dropped = archives(dest)[keep:]
    for old in dropped:
        old.unlink()
    return target, dropped


def contents(cfg: Config) -> list[str]:
    """What an archive made now would hold, without writing one."""
    return ["state.db", *(name for _, name in parts(cfg))]


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-backup.log"


def definition(config: Path, dest: Path, keep: int) -> dict:
    """The launchd job: this Python and jobwatch, once a day. A Mac asleep at that time runs it when it wakes."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobwatch.cli", "-c", str(config), "backup",
                             "--dest", str(dest), "--keep", str(keep)],
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "Nice": 10,
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }


def install(config: Path, dest: Path, keep: int = KEEP) -> str:
    """Write and load the daily job (replacing one installed before); says when it runs."""
    try:
        _mac()
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        log_path().parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
        with path.open("wb") as f:
            plistlib.dump(definition(config.expanduser().resolve(), dest, keep), f)
        _launchctl("bootstrap", _domain(), str(path))
    except ServiceError as e:
        raise BackupError(str(e)) from None
    return f"daily at {HOUR}:{MINUTE:02d}"
