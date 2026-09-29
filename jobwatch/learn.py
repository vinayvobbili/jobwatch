"""Skills to build: what the jobs you're looking at ask for that your resume doesn't show, and where to learn it.

Two signals, both explainable:
- demand: how many of your matching jobs mention a skill anywhere in the posting;
- fit gaps: must-haves a fit score found missing from your resume, which count for more.

Recommendations come from a curated catalog (data/learning.yaml) of official course and certification pages, not
from a model, so every link is real. Gaps the catalog doesn't cover get a course-search link. Gaps no course can
close (a clearance, citizenship, a degree, travel) are listed apart, and so are the ones asking for years of
experience: a course gives you something concrete to point to, not the years.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from urllib.parse import quote

import yaml

from .config import TIMELINES, Config
from .models import Job
from .resume import resume_text
from .score import resume_id
from .store import Store

MOST_JOBS = 5  # example jobs listed per skill

# How long an option takes, and the longest each timeline allows.
TIME = {"hours": 1, "weeks": 2, "months": 3}
FITS = {"week": 1, "month": 2, "quarter": 3, "any": 4}
TIME_LABEL = {"hours": "a few hours", "weeks": "a few weeks", "months": "months"}
AI_SKILLS = {"ml", "pytorch", "llm", "agents", "rag", "mcp", "mlops"}

# Gaps a course can't close, by what they're about.
BLOCKERS = [
    ("Security clearance", re.compile(r"clearance|\bTS/SCI\b|\bpolygraph\b", re.I)),
    ("Work authorization", re.compile(r"citizen|work authori[sz]|visa|sponsorship|\bgreen card\b", re.I)),
    ("Degree", re.compile(r"\b(?:bachelor|master)'?s?\b|\bPh\.?D\b|\bdegree\b|\bB\.?S\.?\b|\bM\.?S\.?\b", re.I)),
    ("Travel or location", re.compile(r"travel|on-?site|relocat|in[- ]office|hybrid|in[- ]person", re.I)),
]
YEARS = re.compile(r"\b\d+\+?\s*(?:or more\s+)?(?:years?|yrs)\b", re.I)


@dataclass
class Skill:
    id: str
    name: str
    pattern: re.Pattern
    options: list[dict]
    search: str = ""

    def found_in(self, text: str) -> bool:
        return bool(text) and bool(self.pattern.search(text))


@lru_cache(maxsize=1)
def catalog() -> tuple[Skill, ...]:
    raw = yaml.safe_load(resources.files("jobwatch").joinpath("data/learning.yaml").read_text(encoding="utf-8"))
    return tuple(Skill(s["id"], s["name"], re.compile("|".join(f"(?:{m})" for m in s["match"]), re.I), s["options"],
                       s.get("search") or re.sub(r"\s*\(.*?\)", "", s["name"])) for s in raw)


def blocker(gap: str) -> str | None:
    """What kind of gap no course closes, if this is one."""
    return next((label for label, pattern in BLOCKERS if pattern.search(gap)), None)


def fits(option: dict, timeline: str) -> bool:
    return TIME.get(option.get("time", "months"), 3) <= FITS[timeline]


def more(skill: Skill, timeline: str = "quarter", near: str = "") -> list[dict]:
    """Searches on the big course sites, for more choice than the curated options: searches rather than
    guessed course pages, so a link never goes dead or points somewhere made up. Colleges nearby only when
    the timeline leaves room for a semester."""
    q = quote(skill.search)
    out = [{"provider": "LinkedIn Learning", "url": f"https://www.linkedin.com/learning/search?keywords={q}"},
           {"provider": "Coursera", "url": f"https://www.coursera.org/search?query={q}"},
           {"provider": "edX", "url": f"https://www.edx.org/search?q={q}"}]
    if skill.id in AI_SKILLS:
        out.insert(0, {"provider": "DeepLearning.AI", "url": "https://www.deeplearning.ai/courses/"})
    if near and FITS[timeline] >= FITS["quarter"]:
        out.append({"provider": f"Colleges near {near}", "url": "https://www.google.com/search?q=" + quote(
            f"{skill.search} certificate program college near {near}")})
    return out


def search_url(gap: str) -> str:
    """Courses on anything, for a gap the catalog doesn't cover (a search, so never a dead or made-up link)."""
    words = re.sub(r"\b\d+\+?\s*(?:years?|yrs)\b(?:\s+of)?(?:\s+(?:experience|hands-on))?(?:\s+(?:in|with))?", "", gap)
    return "https://www.coursera.org/search?query=" + quote(" ".join(words.split()[:8]))


@dataclass
class Demand:
    skill: Skill
    jobs: list[Job] = field(default_factory=list)      # postings that mention it
    gap_jobs: list[Job] = field(default_factory=list)  # scored jobs where it's a missing must-have
    years: bool = False                                # some gap asks for years of it
    on_resume: bool = False

    @property
    def weight(self) -> int:
        return len(self.jobs) + 3 * len(self.gap_jobs)


@dataclass
class Report:
    skills: list[Demand]                  # gaps first (not on the resume), most in demand first
    other_gaps: list[tuple[str, Job]]     # fit gaps the catalog doesn't cover
    blockers: dict[str, list[tuple[str, Job]]]
    jobs: int
    scored: int
    has_resume: bool
    timeline: str = "quarter"
    near: str = ""

    def gaps(self) -> list[Demand]:
        return [d for d in self.skills if not d.on_resume]


def build(pairs: list[tuple[Job, dict | None]], resume: str, timeline: str = "quarter", near: str = "") -> Report:
    """pairs: (job, fit result or None) for every job to read, e.g. today's matches and your applications."""
    if timeline not in TIMELINES:
        raise ValueError(f"timeline must be one of {', '.join(TIMELINES)}")
    skills = catalog()
    demand = {s.id: Demand(s, on_resume=s.found_in(resume)) for s in skills}
    other, blocked, scored = [], {}, 0
    for job, fit in pairs:
        text = f"{job.title}\n{job.description}"
        for s in skills:
            if s.found_in(text):
                demand[s.id].jobs.append(job)
        if not fit:
            continue
        scored += 1
        for gap in fit.get("gaps") or []:
            if label := blocker(gap):
                blocked.setdefault(label, []).append((gap, job))
                continue
            hits = [s for s in skills if s.found_in(gap)]
            for s in hits:
                d = demand[s.id]
                if job not in d.gap_jobs:
                    d.gap_jobs.append(job)
                d.years = d.years or bool(YEARS.search(gap))
            if not hits:
                other.append((gap, job))
    found = [d for d in demand.values() if d.jobs or d.gap_jobs]
    found.sort(key=lambda d: (d.on_resume, -d.weight, d.skill.name))
    return Report(found, other, blocked, len(pairs), scored, bool(resume.strip()), timeline, near)


def for_job(job: Job, fit: dict | None, resume: str) -> list[Demand]:
    """This posting's skills the resume doesn't show, most pressing (a missing must-have) first."""
    r = build([(job, fit)], resume)
    return sorted(r.gaps(), key=lambda d: (not d.gap_jobs, d.skill.name))


def _fit(cfg: Config, store: Store, key: str) -> dict | None:
    return store.score(key, resume_id(cfg.resume)) if cfg.resume and cfg.resume.is_file() else None


def gather(cfg: Config, store: Store, timeline: str | None = None, entries: list | None = None) -> Report:
    """Skills across today's matching jobs and every application (what you're actually going after).
    entries: the digest's, when the caller already built it."""
    if entries is None:
        from .watch import build_digest  # watch imports the scoring stack; only needed here
        entries = build_digest(cfg, store, include_seen=True, score_top=0).entries
    pairs, seen = [], set()
    for e in entries:
        pairs.append((e.job, e.fit))
        seen.add(e.job.key)
    for job, _ in store.applications():
        if job.key not in seen:
            pairs.append((job, _fit(cfg, store, job.key)))
            seen.add(job.key)
    return build(pairs, resume_text(cfg.resume), timeline or cfg.timeline, cfg.near)


def job_gaps(cfg: Config, store: Store, job: Job) -> list[dict]:
    """One posting's skills the resume doesn't show, for its details page."""
    return [{"id": d.skill.id, "name": d.skill.name, "must_have": bool(d.gap_jobs), "years": d.years}
            for d in for_job(job, _fit(cfg, store, job.key), resume_text(cfg.resume))]


# -- output

def _job(j: Job) -> dict:
    return {"key": j.key, "title": j.title, "company": j.display_company}


def options(skill: Skill, timeline: str) -> list[dict]:
    """The curated options, quickest first, each marked whether it fits the timeline."""
    return [{**o, "time_label": TIME_LABEL.get(o.get("time", "months"), ""), "fits": fits(o, timeline)}
            for o in sorted(skill.options, key=lambda o: TIME.get(o.get("time", "months"), 3))]


def demand_dict(d: Demand, total: int, timeline: str = "quarter", near: str = "") -> dict:
    return {"id": d.skill.id, "name": d.skill.name, "on_resume": d.on_resume, "count": len(d.jobs), "of": total,
            "gap_count": len(d.gap_jobs), "years": d.years, "options": options(d.skill, timeline),
            "more": more(d.skill, timeline, near),
            "jobs": [_job(j) for j in (d.gap_jobs + [j for j in d.jobs if j not in d.gap_jobs])[:MOST_JOBS]]}


def to_dict(r: Report) -> dict:
    return {"jobs": r.jobs, "scored": r.scored, "has_resume": r.has_resume, "timeline": r.timeline,
            "near": r.near, "skills": [demand_dict(d, r.jobs, r.timeline, r.near) for d in r.skills],
            "other_gaps": [{"gap": g, "search": search_url(g), **_job(j)} for g, j in r.other_gaps],
            "blockers": [{"label": label, "gaps": [{"gap": g, **_job(j)} for g, j in items]}
                         for label, items in r.blockers.items()]}


def _option(o: dict) -> str:
    return f"{o['name']} ({o['provider']}, {o['kind']}, {o['cost']}, {o['time_label']}): {o['url']}"


def summary(r: Report, most: int = 8) -> str:
    """A few lines for the chat: the biggest gaps and where to learn them."""
    lines = [f"## Skills the user's matching jobs ask for that their resume doesn't show (from {r.jobs} jobs)",
             f"The user's timeline for learning: {r.timeline} (week, month, quarter or any)."
             + (f" They're near {r.near}." if r.near else "")]
    for d in r.gaps()[:most]:
        n = len(d.gap_jobs)
        extra = f", a missing must-have in {n} scored job{'s' * (n != 1)}" if n else ""
        fitting = [o for o in options(d.skill, r.timeline) if o["fits"]]
        learn = "Learn: " + "; ".join(map(_option, fitting)) if fitting else "Nothing curated fits the timeline."
        lines.append(f"- {d.skill.name}: mentioned in {len(d.jobs)} jobs{extra}. {learn}"
                     + " Also: " + ", ".join(m["provider"] for m in more(d.skill, r.timeline, r.near)))
    if r.blockers:
        lines.append("Gaps no course closes: " + "; ".join(f"{k} ({len(v)})" for k, v in r.blockers.items()))
    return "\n".join(lines)


def markdown(r: Report, include_covered: bool = False) -> str:
    out = [f"# Skills to build\n\nFrom {r.jobs} jobs ({r.scored} with fit scores). Timeline: {r.timeline}."]
    if not r.has_resume:
        out.append("\nNo resume in the watchlist, so every skill shows as missing. "
                   "Add `resume:` to see which you have.")
    for d in (r.skills if include_covered else r.gaps()):
        head = f"\n## {d.skill.name}" + (" (on your resume)" if d.on_resume else "")
        facts = [f"Mentioned in {len(d.jobs)} of {r.jobs} jobs"]
        if d.gap_jobs:
            n = len(d.gap_jobs)
            facts.append(f"a missing must-have in {n} scored " + ("job" if n == 1 else "jobs"))
        out += [head, "; ".join(facts) + "."]
        if d.years:
            out.append("Some ask for years of it: a course gives you something concrete to point to, not the years.")
        opts = options(d.skill, r.timeline)
        out += [f"- {_option(o)}" for o in opts if o["fits"]]
        if longer := [o["name"] for o in opts if not o["fits"]]:
            out.append(f"- Longer than your timeline: {'; '.join(longer)}")
        out.append("- More: " + " · ".join(f"[{m['provider']}]({m['url']})" for m in more(d.skill, r.timeline, r.near)))
    if r.other_gaps:
        out.append("\n## Other gaps from fit scores")
        out += [f"- {g} ({j.display_company}): {search_url(g)}" for g, j in r.other_gaps]
    if r.blockers:
        out.append("\n## Gaps a course can't close")
        out += [f"- {label}: " + "; ".join(f"{g} ({j.display_company})" for g, j in items)
                for label, items in r.blockers.items()]
    return "\n".join(out) + "\n"
