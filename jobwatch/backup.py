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
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from .config import Config
from .service import ServiceError, _domain, _launchctl, _mac

LABEL = "io.github.jobwatch.backup"
KEEP = 30
HOUR, MINUTE = 9, 30
LATE_DAYS = 2  # Today warns past this: a Mac off for a day or a slow upload shouldn't cry wolf
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


def parts(cfg: Config, also: Sequence[Path] = ()) -> list[tuple[Path, str]]:
    """(file or folder, its name in the archive) for what's there, the database apart (see _copy_db). `also` is what
    else can't be fetched again, such as files a private repo ignores; a path that's missing is refused, in backup."""
    home = cfg.state.parent
    found = [(home / "packages", "packages"), (home / "resume", "resume"), (cfg.path, f"config/{cfg.path.name}")]
    if cfg.connections:
        found.append((cfg.connections, f"config/{cfg.connections.name}"))
    return [(p, name) for p, name in found if p.exists()] + [(p, f"also/{p.name}") for p in also]


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


def backup(cfg: Config, dest: Path, keep: int = KEEP, day: date | None = None,
           also: Sequence[Path] = ()) -> tuple[Path, list[Path]]:
    """Write today's archive (replacing one from earlier today) and drop all but the newest `keep`. Returns the
    archive and the ones dropped. It appears only when whole: an interrupted run leaves the last good one alone."""
    if keep < 1:
        raise BackupError("keep at least one backup")
    for path in also:  # a file that moved must fail loudly, or the backups quietly stop holding it
        if not path.exists():
            raise BackupError(f"{path} isn't there: fix --also, nothing was backed up")
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
                for path, name in parts(cfg, also):
                    tar.add(path, arcname=name)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    dropped = archives(dest)[keep:]
    for old in dropped:
        old.unlink()
    return target, dropped


def contents(cfg: Config, also: Sequence[Path] = ()) -> list[str]:
    """What an archive made now would hold, without writing one."""
    return ["state.db", *(name for _, name in parts(cfg, also))]


def verify(archive: Path) -> list[str]:
    """Unpack an archive somewhere temporary, as a restore would, and open what's in it: the database passes its
    check and has jobs, and a git repo kept with --also is whole. What it found, one line each, or BackupError."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        with tarfile.open(archive) as tar:
            tar.extractall(home, filter="data")
        if not (home / "state.db").is_file():
            raise BackupError(f"{archive.name} has no database")
        db = sqlite3.connect(home / "state.db")
        try:
            if (said := db.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
                raise BackupError(f"the database in {archive.name} failed its check: {said}")
            jobs = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        except sqlite3.DatabaseError as e:
            raise BackupError(f"the database in {archive.name} can't be read: {e}") from None
        finally:
            db.close()
        if not jobs:
            raise BackupError(f"the database in {archive.name} has no jobs")
        found = [f"{archive.name}: database ok, {jobs:,} jobs"]
        packages = home / "packages"
        if packages.is_dir():
            found.append(f"{sum(1 for _ in packages.iterdir()):,} application packages")
        for path in sorted((home / "also").glob("*")):
            found.append(_repo_line(path) if (path / ".git").exists() else f"also/{path.name}")
    return found


def _repo_line(path: Path) -> str:
    def git(*args):
        return subprocess.run(["git", "-c", f"safe.directory={path}", "-C", str(path), *args],
                              capture_output=True, text=True, check=False)
    fsck = git("fsck", "--no-progress")
    if fsck.returncode:
        raise BackupError(f"the git repo also/{path.name} is damaged: {fsck.stderr.strip() or fsck.stdout.strip()}")
    return f"also/{path.name}: git repo ok, at {git('rev-parse', '--short', 'HEAD').stdout.strip()}"


def overdue(today: date | None = None) -> dict | None:
    """For Today, when the daily job is installed but its newest archive is over LATE_DAYS old (or there's none): the
    last archive's day, the folder and the log. None when all's well, or when no daily job was asked for."""
    try:
        with plist_path().open("rb") as f:
            args = plistlib.load(f)["ProgramArguments"]
        dest = Path(args[args.index("--dest") + 1])
        newest = archives(dest)
    except (OSError, ValueError, KeyError, IndexError):
        return None
    last = date.fromisoformat(newest[0].name[len("jobwatch-"):-len(".tar.gz")]) if newest else None
    if last and ((today or date.today()) - last).days <= LATE_DAYS:
        return None
    return {"last": last.isoformat() if last else None, "dest": str(dest), "log": str(log_path())}


def installed_also(dest: Path) -> list[Path]:
    """What the daily job keeps with --also, when it writes to this folder. A run by hand replaces today's archive, so
    without these it would quietly swap a whole backup for a smaller one."""
    try:
        with plist_path().open("rb") as f:
            args = plistlib.load(f)["ProgramArguments"]
        if Path(args[args.index("--dest") + 1]) != dest:
            return []
    except (OSError, ValueError, KeyError, IndexError):
        return []
    return [Path(args[i + 1]) for i, arg in enumerate(args[:-1]) if arg == "--also"]


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-backup.log"


def definition(config: Path, dest: Path, keep: int, also: Sequence[Path] = ()) -> dict:
    """The launchd job: this Python and jobwatch, once a day. A Mac asleep at that time runs it when it wakes."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobwatch.cli", "-c", str(config), "backup",
                             "--dest", str(dest), "--keep", str(keep),
                             *(arg for path in also for arg in ("--also", str(path)))],
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "Nice": 10,
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }


def install(config: Path, dest: Path, keep: int = KEEP, also: Sequence[Path] = ()) -> str:
    """Write and load the daily job (replacing one installed before); says when it runs."""
    try:
        _mac()
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        log_path().parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
        with path.open("wb") as f:
            plistlib.dump(definition(config.expanduser().resolve(), dest, keep, also), f)
        _launchctl("bootstrap", _domain(), str(path))
    except ServiceError as e:
        raise BackupError(str(e)) from None
    return f"daily at {HOUR}:{MINUTE:02d}"
