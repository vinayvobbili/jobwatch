"""Tailor a resume to one job with resume-kit (an optional add-on, like shortlist-ai for fit scores): its `resume
draft` picks and orders your confirmed facts by what the posting asks for, its `resume build` renders the PDF and
checks the page target and the fact guardrails. jobwatch builds nothing itself: it runs the tool, keeps the PDF
with the job's application (see package.py) and the browser extension attaches it (autofill.resume_for).

Setting: `resume_kit` in the watchlist is the command (default `resume` on PATH). resume-kit finds your facts
itself (RESUME_KIT_CONTENT, else ~/.config/resume-kit/content). The headline and summary a draft starts with are
its parent version's: edit the version in resume-kit to tailor them, then Rebuild.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Config
from .models import Job
from .store import STAGES, Store

# The PDF's name starts with your name and "Resume" (21 characters or so), and some application sites refuse a
# file name over 55: the version's name leaves room for both.
NAME_MAX = 40
TITLE_MAX = 80
DRAFT_TIMEOUT = 60
BUILD_TIMEOUT = 300   # rendering needs node and LibreOffice, a few seconds when they're warm
RESUME_KIT = "https://github.com/vinayvobbili/resume-kit"
SETUP = (f"Tailoring needs resume-kit ({RESUME_KIT}): set it up following its README (your facts in its content "
         "folder; rendering needs node and LibreOffice), then either put its `resume` command on your PATH or set "
         "resume_kit in Settings > Applying to the command's full path.")


class TailorError(ValueError):
    pass


class NotInstalled(TailorError):
    """resume-kit isn't set up here; the message says how to."""


def command(setting: str) -> list[str]:
    """resume-kit's command as argv: the resume_kit setting, else `resume` on PATH."""
    if setting.strip():
        argv = shlex.split(setting)
        argv[0] = str(Path(argv[0]).expanduser())
    else:
        argv = ["resume"]
    if not shutil.which(argv[0]):
        raise NotInstalled(f"{argv[0]!r} was not found. {SETUP}")
    return argv


def ready(setting: str) -> bool:
    try:
        command(setting)
    except TailorError:
        return False
    return True


def version_name(job: Job) -> str:
    """The resume-kit version for a job: company and title, lowercase words joined by hyphens, at most NAME_MAX
    characters and ending on a whole word."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.display_company} {job.title}".lower()).strip("-")
    if len(slug) > NAME_MAX:
        slug = slug[:NAME_MAX + 1].rpartition("-")[0] or slug[:NAME_MAX]
    return slug.strip("-") or "job-" + hashlib.sha1(job.key.encode()).hexdigest()[:8]


def _trim(text: str, most: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= most else "…" + text[-most:]


def _run(argv: list[str], timeout: int, stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TailorError(f"`{' '.join(argv[:2])}` took over {timeout} seconds and was stopped") from None
    except OSError as e:
        raise NotInstalled(f"could not run {argv[0]!r}: {e}. {SETUP}") from None


def _fail(step: str, done: subprocess.CompletedProcess) -> TailorError:
    return TailorError(f"resume-kit {step} failed: " + _trim(done.stderr or done.stdout or f"exit {done.returncode}"))


def _versions(argv: list[str]) -> set[str]:
    """The names of the versions resume-kit has (`resume list`: a "content:" line, then a line per version)."""
    done = _run([*argv, "list"], DRAFT_TIMEOUT)
    if done.returncode:
        raise _fail("list", done)
    return {line.split()[0] for line in done.stdout.splitlines() if line.strip() and not line.startswith("content:")}


def tailor(cfg: Config, store: Store, key: str) -> dict:
    """Draft (the first time) or rebuild a resume version for the job, and keep its PDF as the job's resume.

    An existing version is never redrafted: you may have edited it. Returns {key, version, title, new, pdf (the
    name kept in the package), pages, ok, problems}; ok is resume-kit's verdict (page target and fact checks),
    and problems what it said otherwise. A PDF that missed the page target is still kept, flagged: review it."""
    argv = command(cfg.resume_kit)
    job, rec = store.find(key)
    name = version_name(job)
    title = f"{job.display_company}: {job.title}"[:TITLE_MAX]
    new = name not in _versions(argv)
    if new:
        done = _run([*argv, "draft", name, "-", "--title", title], DRAFT_TIMEOUT, stdin=job.to_text())
        if done.returncode:
            raise _fail("draft", done)
    with tempfile.TemporaryDirectory(prefix="jobwatch-resume-") as out:
        done = _run([*argv, "build", name, "--out", out], BUILD_TIMEOUT)
        pdfs = sorted(Path(out).glob("*.pdf"))
        if not pdfs:  # a failed fact check or missing renderer builds nothing
            raise _fail("build", done)
        pdf = pdfs[0]
        pkg = store.package(job.key)
        # A rebuild replaces the earlier build (moved aside, see Package.remove) so the name stays put; once
        # applied, the copy that was sent stays and the new one is kept beside it.
        if rec.get("status") not in STAGES and pdf.name in {f["name"] for f in pkg.data()["files"]}:
            pkg.remove(pdf.name)
        kept = pkg.attach(pdf.name, pdf.read_bytes(), "resume")
    pages = re.search(r"(\d+) page\(s\)", done.stdout)
    notes = [line.strip() for line in done.stdout.splitlines()[1:] if line.strip()] + \
        ([done.stderr.strip()] if done.stderr.strip() else [])
    return {"key": job.key, "version": name, "title": title, "new": new, "pdf": kept,
            "pages": int(pages.group(1)) if pages else None, "ok": done.returncode == 0,
            "problems": [_trim(n, 300) for n in notes]}
