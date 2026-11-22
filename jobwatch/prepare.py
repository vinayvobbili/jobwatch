"""What Prepare has saved for a job, so a page that loads later can show it again: the kept resume, the last ATS check
and the newest cover letter version. Only successes are saved, so a step that failed shows nothing here.

The resume and the letters are kept by package.py and cover.py. The ATS check (ats.py) was only ever shown, so its last
result is kept beside the letters, in covers/<job>/ats.json: the score, the keywords found and missing, which file
was read, when, and fingerprints of the posting text and the resume it was read from, so a later change to either
marks it older. Everything here is read from files: no model, no PDF reader.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from . import cover
from .autofill import resume_for
from .config import Config
from .models import Job
from .store import Store

ATS_FILE = "ats.json"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _posting_digest(posting: Job) -> str:
    return _digest(posting.description.strip().encode("utf-8"))


def _file_digest(path: Path | None) -> str:
    try:
        return _digest(path.read_bytes()) if path else ""
    except OSError:
        return ""


def save_ats(store: Store, job: Job, posting: Job, result: dict, resume: Path) -> None:
    """Keep an ATS check (what ats.check returns) as the job's latest, with when it ran and what it read."""
    where = cover.folder_of(store, job.key)
    where.mkdir(parents=True, exist_ok=True)
    keep = {k: result[k] for k in ("file", "tailored", "read_with", "chars", "score", "found", "missing", "checks")}
    keep.update(at=datetime.now().astimezone().isoformat(timespec="seconds"),
                posting=_posting_digest(posting), resume=_file_digest(resume))
    tmp = where / (ATS_FILE + ".new")
    tmp.write_text(json.dumps(keep, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(where / ATS_FILE)


def saved_ats(cfg: Config, store: Store, job: Job) -> dict | None:
    """The job's last ATS check, with `older` true when its posting text or its resume is not what was read
    ({score, found, missing, checks, file, tailored, read_with, chars, at, older}); None when none is saved."""
    path = cover.folder_of(store, job.key) / ATS_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["found"], saved["missing"], saved["checks"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    posting = store.linked(job) or job
    older = saved.get("posting") != _posting_digest(posting) \
        or saved.get("resume") != _file_digest(resume_for(cfg, store, job))
    return {**{k: v for k, v in saved.items() if k not in ("posting", "resume")}, "older": older}


def state(cfg: Config, store: Store, job: Job, resume_name: str | None) -> dict:
    """The saved Prepare results of a job, one key per step that has one (none when nothing is saved):
    resume {state, label, name}, ats (see saved_ats), cover {version, tone, words, at}."""
    out: dict = {}
    if resume_name:
        out["resume"] = {"state": "ok", "label": "Resume", "name": resume_name}
    if ats := saved_ats(cfg, store, job):
        out["ats"] = ats
    if letter := cover.latest(store, job.key):
        out["cover"] = {"version": letter["version"], "tone": letter["tone"], "words": letter["words"],
                        "at": letter["drafted"]}
    return out
