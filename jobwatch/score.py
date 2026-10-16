"""Fit scores from shortlist-ai (optional): how well a resume covers each job's requirements.

shortlist-ai (https://github.com/vinayvobbili/shortlist-ai) turns a posting into must-have and
nice-to-have requirements and judges each one against the resume, with quotes it checks. It is
slow next to keyword relevance, so only the top few jobs get scored, and each score is stored
against that exact resume file and the prompts it was scored with. The prompts can be edited in
Settings (scoring.prompts holds the edited ones), with a shortlist-ai that takes edited prompts.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import importlib.metadata
import json
import re
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path

from .models import Job

INSTALL_HINT = "pip install 'jobwatch[score]' (or 'jobwatch[local]' for the on-device Apple Silicon model)"


class ScoringUnavailable(RuntimeError):
    pass


class ModelGate:
    """Turns on the on-device model: one generation at a time (MLX isn't thread-safe), and the person first.
    A chat reply or a Score fit click waits at most for the job being scored; background scoring waits while
    either is waiting or running.

    The model stays in memory (several GB) between turns so the next one starts at once, but not for ever: after
    `idle_after` seconds with nobody using it, it's let go (see unload_local_models) and loaded again by the next
    turn. One timer per use, no polling; None keeps the model for good."""

    def __init__(self, idle_after: float | None = None):
        self._cond = threading.Condition()
        self._busy = False
        self._waiting = 0  # foreground turns waiting
        self.idle_after = idle_after
        self._used = False  # a turn has had the model since it was last let go
        self._timer: threading.Timer | None = None

    @property
    def busy(self) -> bool:
        """Something is using the model now: a turn would have to wait."""
        return self._busy

    def _release(self, rest: bool = True):
        with self._cond:
            self._busy = False
            self._cond.notify_all()
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if rest and self._used and self.idle_after:
                self._timer = threading.Timer(self.idle_after, self._let_go)
                self._timer.daemon = True
                self._timer.start()

    def _let_go(self):
        """The idle time is up: unload the model, unless a turn has come in meanwhile."""
        with self._cond:
            if self._busy or self._waiting:
                return
            self._busy = True  # nobody starts a turn on a model that's being let go
            self._used = False
        try:
            unload_local_models()
        finally:
            self._release(rest=False)

    @contextmanager
    def foreground(self) -> Iterator[None]:
        with self._cond:
            self._waiting += 1
            try:
                self._cond.wait_for(lambda: not self._busy)
            finally:
                self._waiting -= 1
            self._busy, self._used = True, True
        try:
            yield
        finally:
            self._release()

    @contextmanager
    def background(self) -> Iterator[None]:
        with self._cond:
            self._cond.wait_for(lambda: not self._busy and not self._waiting)
            self._busy, self._used = True, True
        try:
            yield
        finally:
            self._release()


# What lets go of a model loaded by something else (the chat's, see chat._local_model); shortlist-ai's is found below.
UNLOADERS: list[Callable[[], None]] = []


def unload_local_models():
    """Let the on-device models go: forget the loaded ones (shortlist-ai's, once it has loaded one, and the
    chat's) and give MLX's cached GPU memory back, so an idle page holds close to nothing."""
    backends = sys.modules.get("shortlist_ai.backends")
    if clear := getattr(getattr(backends, "_load_local_generator", None), "cache_clear", None):
        clear()
    for unload in UNLOADERS:
        unload()
    gc.collect()
    if mx := sys.modules.get("mlx.core"):
        if clear := getattr(mx, "clear_cache", None):
            clear()


LOCAL = ModelGate()


def turn(backend: str, background: bool = False):
    """A turn on the model, when it's the shared local one; Claude takes calls side by side."""
    if backend != "local":
        return nullcontext()
    return LOCAL.background() if background else LOCAL.foreground()


def scorer_id() -> str:
    """Which scorer made a score: a short hash of shortlist-ai's version and its built-in prompt texts, so a
    shortlist-ai whose own prompts or scoring changed (a new release, or a prompt edited in its source) scores
    afresh instead of keeping scores made by the old one. Edited prompts (scoring.prompts) aren't in it: they
    have their own part of the key (see resume_id)."""
    try:
        version = importlib.metadata.version("shortlist-ai")
    except importlib.metadata.PackageNotFoundError:
        version = ""
    built_in = {p["name"]: p["default"] for p in prompt_info()["prompts"]}
    return hashlib.sha256(json.dumps([version, built_in], sort_keys=True).encode()).hexdigest()[:8]


def resume_id(resume: Path, prompts: Mapping[str, str] | None = None) -> str:
    """Scores are tied to the resume's content, to the scorer that made them (scorer_id: shortlist-ai's version
    and built-in prompts) and to any edited prompts (scoring.prompts), so an edited resume or prompt, or a
    changed scorer, is scored afresh. With no prompt edited there's no prompts part: putting the prompts back
    brings back the scores made with them."""
    rid = f"{resume.name}:{hashlib.sha256(resume.read_bytes()).hexdigest()[:12]}:scorer-{scorer_id()}"
    if prompts:
        rid += ":prompts-" + hashlib.sha256(json.dumps(dict(prompts), sort_keys=True).encode()).hexdigest()[:12]
    return rid


# The prompts shortlist-ai had before they could be edited (0.1.1): shown read-only (see prompt_info).
_FIXED_PROMPTS = (
    ("resume_system", "shortlist_ai.extract", "RESUME_SYSTEM", "Reads a resume into structured fields."),
    ("job_system", "shortlist_ai.extract", "JOB_SYSTEM", "Turns a posting into must-haves and nice-to-haves."),
    ("score_system", "shortlist_ai.score", "SCORE_SYSTEM", "Judges each requirement met, partial or not met."),
    ("years_system", "shortlist_ai.years", "ROLES_SYSTEM", 'For "N+ years of X": which roles count toward the years.'),
)
UPDATE_HINT = "pip install -U shortlist-ai"


def _editable_prompts():
    """shortlist-ai's prompts by name ({name: Prompt}, see shortlist_ai.prompts), or None when it's missing or too
    old to take edited prompts."""
    try:
        from shortlist_ai.prompts import PROMPTS
    except ImportError:
        return None
    return PROMPTS


def check_prompts(prompts: Mapping[str, str]) -> str | None:
    """What's wrong with these edited prompts (scoring.prompts), or None. Checked by the shortlist-ai that's
    installed; without one that takes edited prompts they aren't checked here (scoring says so instead)."""
    if _editable_prompts() is None:
        return None
    from shortlist_ai.prompts import PromptError, check
    for name, text in prompts.items():
        try:
            check(name, text)
        except PromptError as e:
            return str(e)
    return None


def prompt_info(edited: Mapping[str, str] | None = None) -> dict:
    """The prompts fit scoring sends, for Settings: installed (shortlist-ai is), editable (it takes edited prompts),
    a note when it can't, and each prompt's name, about (one line), placeholders (ones a template must keep),
    default, text (the edited one, or the default) and edited."""
    edited = dict(edited or {})
    defaults = _editable_prompts()
    if defaults is not None:
        rows = [(p.name, p.about, list(p.placeholders), p.default) for p in defaults.values()]
        return {"installed": True, "editable": True, "note": None, "prompts": _rows(rows, edited)}
    rows = []
    for name, module, constant, about in _FIXED_PROMPTS:
        try:
            rows.append((name, about, [], getattr(importlib.import_module(module), constant)))
        except (ImportError, AttributeError):
            pass
    if not rows:
        return {"installed": False, "editable": False, "note": f"Fit scoring isn't installed: {INSTALL_HINT}",
                "prompts": []}
    note = f"This shortlist-ai can't take edited prompts: {UPDATE_HINT} to edit them."
    if edited:
        note += " The watchlist has edited ones, so scoring stops until then (or until they're removed)."
    return {"installed": True, "editable": False, "note": note, "prompts": _rows(rows, edited)}


def _rows(rows, edited: dict) -> list[dict]:
    return [{"name": name, "about": about, "placeholders": placeholders, "default": default,
             "text": edited.get(name, default), "edited": name in edited}
            for name, about, placeholders, default in rows]


def _safe(key: str) -> str:
    return re.sub(r"[^\w.-]+", "_", key)


def requirement_rows(result, spec) -> list[dict]:
    """Why a score is what it is: each requirement the posting asks for, its verdict, and the resume's words
    that back it (only quotes found in the resume)."""
    asked = {r.id: r.description for r in getattr(spec, "requirements", None) or []}
    rows = []
    for r in getattr(result, "requirements", None) or []:
        unverified = set(r.unverified_quotes)
        rows.append({"id": r.requirement_id, "requirement": asked.get(r.requirement_id, r.requirement_id),
                     "kind": r.kind, "verdict": r.verdict,
                     "evidence": [q for q in r.evidence if q not in unverified],
                     "evidence_verified": r.evidence_verified, "reasoning": r.reasoning})
    return rows


def brief(fit: dict | None) -> dict | None:
    """A fit score without its per-requirement detail, for lists of jobs (one job's view keeps it all)."""
    return {k: v for k, v in fit.items() if k != "requirements"} if fit else fit


def score_jobs(jobs: list[Job], resume: Path, backend: str, cache_dir: Path, workers: int = 1,
               progress: Callable[[str], None] | None = None,
               prompts: Mapping[str, str] | None = None, model: str = "") -> tuple[dict[str, dict], dict[str, str]]:
    """({job key: result}, {job key: error}). A result has score, must_haves_met/total, gaps, summary and
    requirements (see requirement_rows; results saved before it have none). prompts: the edited ones
    (scoring.prompts) in place of shortlist-ai's own; results belong under resume_id(resume, prompts).
    model: the backend's model (scoring.model); unset, shortlist-ai's own."""
    try:
        from shortlist_ai.backends import get_backend
        from shortlist_ai.extract import Cache, extract_job
        from shortlist_ai.pipeline import match_jobs
    except ImportError:
        raise ScoringUnavailable(f"scoring needs shortlist-ai: {INSTALL_HINT}") from None
    # Never score with the shipped prompts what will be stored as scored with the edited ones.
    if prompts and _editable_prompts() is None:
        raise ScoringUnavailable(f"the fit-score prompts are edited (scoring.prompts) and this shortlist-ai can't "
                                 f"use edited prompts: {UPDATE_HINT}, or reset them in Settings")
    if prompts and (problem := check_prompts(prompts)):
        raise ScoringUnavailable(f"scoring.prompts: {problem}")
    edits = {"prompts": dict(prompts)} if prompts else {}  # none: works with a shortlist-ai from before prompts

    progress = progress or (lambda msg: None)
    model = get_backend(backend, model) if model else get_backend(backend)
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
            specs[name] = extract_job(path, model, cache, **edits)
        except Exception as e:
            errors[job.key] = f"{type(e).__name__}: {e}"
    if not specs:
        return {}, errors
    matches = match_jobs(resume, specs, model, cache=cache, workers=workers, progress=progress, **edits)
    errors.update({by_name[k]: v for k, v in matches.errors.items()})
    results = {}
    for m in matches.matches:
        r = m.result
        results[by_name[m.job_id]] = {
            "score": r.score, "must_haves_met": r.must_haves_met, "must_haves_total": r.must_haves_total,
            "gaps": m.gaps, "summary": r.summary, "flags": r.flags,
            "requirements": requirement_rows(r, specs.get(m.job_id)),
        }
    return results, errors
