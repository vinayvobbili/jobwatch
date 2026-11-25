"""`jobwatch notes`: a job's note history, and notes read back from a backup.

A note is the dated record of an application (who said what, when). `mark --note` replaces it, so the old one is kept
in the database (store.note_history) and `notes KEY --undo` brings it back. When a note was lost before that, or a
long time ago, the daily backup still holds it: `notes KEY --from-backup ARCHIVE` reads it out of the archive without
touching the live database, and `--restore` writes it back in front of the note there now, so what was added since
isn't lost.
"""

from __future__ import annotations

import re
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import backup
from .store import Store

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")


class NotesError(ValueError):
    pass


@dataclass
class Restore:
    key: str
    archived: str  # the note in the archive ("" when the job had none there, or wasn't there)
    current: str
    merged: str  # what the note becomes: the archived one, then the current one
    action: str  # "restore", or why nothing changes: "no archived note", "already in the note"


def archive_path(spec: str, dest: Path | None = None) -> Path:
    """An archive given as a file, or as the day it was made (2026-11-24), looked up in the backup folder."""
    path = Path(spec).expanduser()
    if path.is_file():
        return path
    if _DAY.fullmatch(spec):
        found = (dest or backup.default_dest()) / f"jobwatch-{spec}.tar.gz"
        if found.is_file():
            return found
        raise NotesError(f"no backup for {spec} in {found.parent}")
    raise NotesError(f"{spec} is neither a backup file nor a day (YYYY-MM-DD)")


def archived_notes(archive: Path, keys: list[str]) -> dict[str, str]:
    """The note each key's job had in the archive ("" when it had none, or wasn't there). Only the database is
    unpacked, into a temporary folder, and opened read-only; the live database isn't touched."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with tarfile.open(archive) as tar:
                for member in tar:  # the database is the first member: stop there, not after reading the whole archive
                    if member.name == "state.db":
                        tar.extract(member, tmp, filter="data")
                        break
                else:
                    raise NotesError(f"{archive.name} has no database")
        except (OSError, tarfile.TarError) as e:
            raise NotesError(f"{archive.name} can't be read: {e}") from None
        db = sqlite3.connect(f"{(Path(tmp) / 'state.db').as_uri()}?mode=ro", uri=True)
        try:
            return {k: (db.execute("SELECT note FROM jobs WHERE key=?", (k,)).fetchone() or ("",))[0] or ""
                    for k in keys}
        except sqlite3.DatabaseError as e:
            raise NotesError(f"the database in {archive.name} can't be read: {e}") from None
        finally:
            db.close()


def plan(store: Store, archive: Path, keys: list[str]) -> list[Restore]:
    """What restoring each job's archived note would do. A key may be anything `find` takes (a posting id, a company);
    each result carries the full key."""
    resolved = [store.find(k)[0].key for k in keys]
    archived = archived_notes(archive, resolved)
    out = []
    for key in resolved:
        old = archived[key].strip()
        current = (store.find(key)[1].get("note") or "").strip()
        if not old:
            action = "no archived note"
        elif old in current:
            action = "already in the note"
        else:
            action = "restore"
        out.append(Restore(key, old, current, f"{old} {current}".strip() if action == "restore" else current, action))
    return out


def restore(store: Store, plans: list[Restore]) -> list[Restore]:
    """Write each planned merge. The note replaced goes to the note history, so `notes KEY --undo` reverses it."""
    done = [p for p in plans if p.action == "restore"]
    for p in done:
        store.track(p.key, note=p.merged)
    return done
