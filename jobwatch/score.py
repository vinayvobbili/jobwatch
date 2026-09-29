"""Fit scores from shortlist-ai (optional): how well a resume covers each job's requirements.

shortlist-ai (https://github.com/vinayvobbili/shortlist-ai) turns a posting into must-have and
nice-to-have requirements and judges each one against the resume, with quotes it checks. It is
slow next to keyword relevance, so only the top few jobs get scored, and each score is stored
against that exact resume file.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from .models import Job

INSTALL_HINT = "pip install 'jobwatch[score]' (or 'jobwatch[local]' for the on-device Apple Silicon model)"


class ScoringUnavailable(RuntimeError):
    pass


def resume_id(resume: Path) -> str:
    """Scores are tied to the resume's content, so an edited resume is scored afresh."""
    return f"{resume.name}:{hashlib.sha256(resume.read_bytes()).hexdigest()[:12]}"


def _safe(key: str) -> str:
    return re.sub(r"[^\w.-]+", "_", key)


def score_jobs(jobs: list[Job], resume: Path, backend: str, cache_dir: Path, workers: int = 1,
               progress: Callable[[str], None] | None = None) -> tuple[dict[str, dict], dict[str, str]]:
    """({job key: result}, {job key: error}). A result has score, must_haves_met/total, gaps and summary."""
    try:
        from shortlist_ai.backends import get_backend
        from shortlist_ai.extract import Cache, extract_job
        from shortlist_ai.pipeline import match_jobs
    except ImportError:
        raise ScoringUnavailable(f"scoring needs shortlist-ai: {INSTALL_HINT}") from None

    progress = progress or (lambda msg: None)
    model = get_backend(backend)
    cache = Cache(cache_dir / "shortlist")
    postings = cache_dir / "postings"
    postings.mkdir(parents=True, exist_ok=True)
    specs, errors, by_name = {}, {}, {}
    for job in jobs:
        name = _safe(job.key)
        by_name[name] = job.key
        path = postings / f"{name}.md"
        path.write_text(job.to_text(), encoding="utf-8")
        progress(f"requirements  {job.display_company}: {job.title}")
        try:
            specs[name] = extract_job(path, model, cache)
        except Exception as e:
            errors[job.key] = f"{type(e).__name__}: {e}"
    if not specs:
        return {}, errors
    matches = match_jobs(resume, specs, model, cache=cache, workers=workers, progress=progress)
    errors.update({by_name[k]: v for k, v in matches.errors.items()})
    results = {}
    for m in matches.matches:
        r = m.result
        results[by_name[m.job_id]] = {
            "score": r.score, "must_haves_met": r.must_haves_met, "must_haves_total": r.must_haves_total,
            "gaps": m.gaps, "summary": r.summary, "flags": r.flags,
        }
    return results, errors
