"""What you sent with each application: the resume and cover letter as submitted, the answers you gave on the
form, and the posting as it read when you applied.

Everything is a copy, in a folder per job next to jobwatch's history (packages/<job>/), because tailored resumes
get rebuilt and postings get edited or taken down. When a recruiter calls weeks later, this is what they saw.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from .models import Job

MANIFEST = "package.json"   # {"answers": [{"question", "answer"}], "note": "...", "files": {name: {...}}}
POSTING = "posting.md"
REMOVED = ".removed"        # files taken out of a package are moved here, not deleted
MAX_FILE = 20 * 1024 * 1024
MAX_TEXT = 20000


def _safe(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("._") or "file"


def kind_of(name: str) -> str:
    """resume, letter or other, from the file name."""
    n = name.lower()
    if re.search(r"cover|letter", n):
        return "letter"
    if re.search(r"resume|résumé|\bcv\b|_cv|cv[_.-]", n):
        return "resume"
    return "other"


class Package:
    def __init__(self, root: Path, key: str):
        self.key = key
        self.dir = Path(root) / _safe(key)

    # -- reading

    def _manifest(self) -> dict:
        path = self.dir / MANIFEST
        m = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return {"answers": m.get("answers") or [], "note": m.get("note") or "", "files": m.get("files") or {}}

    def data(self) -> dict:
        """Files (newest first), answers, note, and when the posting was saved."""
        m = self._manifest()
        files = [{"name": n, **f, "size": (self.dir / n).stat().st_size}
                 for n, f in m["files"].items() if (self.dir / n).is_file()]
        files.sort(key=lambda f: datetime.fromisoformat(f["added"]), reverse=True)
        posting = self.dir / POSTING
        saved = posting.read_text(encoding="utf-8").split("\n", 1)[0] if posting.is_file() else ""
        return {"files": files, "answers": m["answers"], "note": m["note"], "folder": str(self.dir),
                "posting_saved": saved.removeprefix("<!-- saved ").removesuffix(" -->") if saved else None}

    def summary(self) -> dict:
        m = self._manifest()
        return {"files": len(m["files"]), "answers": len(m["answers"]), "note": bool(m["note"])}

    def path(self, name: str) -> Path:
        """A file in the package, by the name it's listed under."""
        if name == POSTING and (self.dir / POSTING).is_file():
            return self.dir / POSTING
        if name not in self._manifest()["files"]:
            raise KeyError(f"no file {name!r} in the package for {self.key}")
        return self.dir / name

    def resume(self) -> Path | None:
        """The resume sent, if one is attached (the latest, when there are several)."""
        files = [f for f in self.data()["files"] if f["kind"] == "resume"]
        return self.dir / files[0]["name"] if files else None

    # -- writing

    def _save(self, m: dict):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (MANIFEST + ".new")
        tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / MANIFEST)

    def keep_posting(self, job: Job, again: bool = False):
        """Save the posting as it reads now, once: the first time is the one that matters (again: replace it, for
        a posting whose text was given later)."""
        path = self.dir / POSTING
        if again or not path.is_file():
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_text(f"<!-- saved {date.today().isoformat()} -->\n{job.to_text()}", encoding="utf-8")

    def attach(self, name: str, data: bytes, kind: str | None = None) -> str:
        """Add a copy of a file; returns the name it's kept under. The same file twice is kept once."""
        if not data:
            raise ValueError("the file is empty")
        if len(data) > MAX_FILE:
            raise ValueError("that file is too large (20 MB at most)")
        if kind not in (None, "resume", "letter", "other"):
            raise ValueError("kind must be resume, letter or other")
        m = self._manifest()
        digest = hashlib.sha256(data).hexdigest()
        for existing, f in m["files"].items():
            if f.get("sha256") == digest:
                return existing
        stem, dot, ext = _safe(Path(name).name).rpartition(".")
        stem, ext = (stem, dot + ext) if dot and stem else (_safe(Path(name).name), "")
        final, n = f"{stem}{ext}", 2
        while final in m["files"] or final in (MANIFEST, POSTING) or (self.dir / final).exists():
            final, n = f"{stem}-{n}{ext}", n + 1
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / final).write_bytes(data)
        m["files"][final] = {"kind": kind or kind_of(name), "sha256": digest,
                             # local time: "added 2025-03-02" is the day it was for the person
                             "added": datetime.now().astimezone().isoformat(timespec="microseconds")}
        self._save(m)
        return final

    def remove(self, name: str):
        """Take a file out of the package. It's moved to packages/<job>/.removed/, not deleted."""
        path = self.path(name)
        m = self._manifest()
        gone = self.dir / REMOVED
        gone.mkdir(exist_ok=True)
        shutil.move(path, gone / f"{datetime.now():%Y%m%d-%H%M%S}-{name}")
        m["files"].pop(name, None)
        self._save(m)

    def write(self, answers: list[dict] | None = None, note: str | None = None):
        """Replace the form answers ([{question, answer}]) and/or the note (a cover letter or message you sent).
        None leaves one as it is."""
        m = self._manifest()
        if answers is not None:
            if not isinstance(answers, list) or not all(isinstance(a, dict) for a in answers):
                raise ValueError("answers are a list of {question, answer}")
            pairs = [(str(a.get("question") or "").strip()[:2000], str(a.get("answer") or "").strip()[:MAX_TEXT])
                     for a in answers]
            m["answers"] = [{"question": q, "answer": a} for q, a in pairs if q or a]
        if note is not None:
            m["note"] = str(note).strip()[:MAX_TEXT]
        self._save(m)

    # -- for the chat

    def context(self) -> str:
        """What was sent, as text for the chat: answers and note in full, files by name."""
        d = self.data()
        if not (d["files"] or d["answers"] or d["note"]):
            return ""
        out = ["## What the user sent with this application"]
        if d["files"]:
            out.append("Files: " + "; ".join(f"{f['name']} ({f['kind']}, added {f['added'][:10]})" for f in d["files"]))
        for a in d["answers"]:
            out.append(f"Q: {a['question']}\nA: {a['answer']}")
        if d["note"]:
            out.append(f"Cover letter or message:\n{d['note']}")
        return "\n\n".join(out)
