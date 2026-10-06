"""Seed the demo: a watchlist and a state file holding only made-up companies (Acme, Globex, Initech, Umbrella,
Hooli), made-up jobs and a made-up resume, for the README's demo video.

    python scripts/demo/seed.py -o scripts/demo/out/demo

Everything lives in that folder (watchlist, resume, state, cache). Nothing reads or writes your own watchlist or
~/.local/share/jobwatch, and nothing reaches the network: the jobs are written straight into the state file.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store

OUT = Path(__file__).resolve().parent / "out" / "demo"
MARK = ".jobwatch-demo"  # written into the folder, so seeding again only ever clears a demo folder

WATCHLIST = """\
# jobwatch DEMO watchlist: made-up companies only.
companies:
  - {source: greenhouse, board: acme, name: Acme}
  - {source: lever, board: globex, name: Globex}
  - {source: ashby, board: initech, name: Initech}
  - {source: workable, board: umbrella, name: Umbrella}
  - {source: workday, board: hooli.wd5/Careers, name: Hooli}
filters:
  titles: ["engineer", "architect"]
  exclude_titles: ["intern", "manager"]
  locations: ["remote", "Denver"]
  remote_country: US
  min_salary: 150000
  max_age_days: 30
keywords:
  Python: 2
  LLM: 3
  RAG: 3
  agents: 2
  Kubernetes: 1
resume: resume.txt
scoring:
  backend: local
  auto: false
display:
  theme: light
state: state/state.db
cache: cache
"""

RESUME = """\
Sample Candidate
Senior Software Engineer

- 8 years building software in Python: APIs, data pipelines and tools.
- Shipped LLM features to production: agents that answer support questions with retrieval (RAG) and vector search.
- Designed an evaluation harness for prompts and models; cut regressions before release.
- Ran Python APIs on AWS with Terraform and CI/CD; on call for a 24x7 platform.
- Led a team of four engineers; mentored two new hires.
- Wrote data pipelines in SQL and Spark for analytics.
"""


def posting(intro: str, do: list[str], need: list[str], nice: list[str]) -> str:
    lines = [intro, "", "What you'll do:"] + [f"- {x}" for x in do]
    lines += ["", "What we're looking for:"] + [f"- {x}" for x in need]
    lines += ["", "Nice to have:"] + [f"- {x}" for x in nice]
    return "\n".join(lines)


NOW = datetime.now(timezone.utc)


def job(source, board, name, id_, title, locs, lo, hi, age, desc, dept="Engineering"):
    return Job(source=source, company=board, id=id_, title=title,
               url=f"https://jobs.example.com/{name.lower()}/{id_}", company_name=name, locations=locs,
               department=dept, salary_min=lo, salary_max=hi, currency="USD",
               posted=NOW - timedelta(days=age, hours=3), description=desc)


AGENTS = posting("Acme builds tools that help teams ship faster.",
                 ["Build LLM agents and RAG pipelines in Python", "Own evaluation of prompts and models",
                  "Work with customers to take prototypes to production"],
                 ["5+ years building software in Python", "Experience shipping LLM features to production",
                  "Retrieval (RAG) and vector search", "3+ years with Kubernetes in production"],
                 ["Experience with fine-tuning", "Open-source contributions"])
PLATFORM = posting("Initech's ML platform serves every product team.",
                   ["Run the training and serving platform on Kubernetes", "Build Python tooling for model teams"],
                   ["Python and distributed systems", "Kubernetes and Terraform", "On-call for production systems"],
                   ["Experience with GPUs", "Spark or Ray"])
FDE = posting("Globex sends engineers to sit with customers and ship.",
              ["Deploy LLM agents at customer sites", "Turn field feedback into product changes"],
              ["Strong Python", "Customer-facing engineering experience", "Comfort with ambiguity"],
              ["Travel up to 25%"])
PRINCIPAL = posting("Hooli is building agents for its developer platform.",
                    ["Set technical direction for agent infrastructure", "Mentor senior engineers"],
                    ["10+ years in software engineering", "Large-scale distributed systems", "LLM agents and tools"],
                    ["Go or Rust"])
APPLIED = posting("Umbrella's applied AI team builds assistants for analysts.",
                  ["Build RAG assistants in Python", "Measure answer quality"],
                  ["Python", "LLM applications", "SQL"], ["Security domain experience"])
GENERIC = posting("A small team with a big remit.", ["Build and run Python services"],
                  ["Python", "AWS", "CI/CD"], ["Kubernetes"])

BOARDS = {
    ("greenhouse", "acme"): [
        job("greenhouse", "acme", "Acme", "4101", "Staff AI Engineer", ["Remote, United States"],
            210000, 260000, 1, AGENTS),
        job("greenhouse", "acme", "Acme", "4102", "Solutions Architect, AI", ["Denver, CO, United States"],
            170000, 215000, 5, GENERIC),
        job("greenhouse", "acme", "Acme", "4090", "Platform Engineer", ["Remote, United States"],
            165000, 205000, 18, GENERIC),
    ],
    ("lever", "globex"): [
        job("lever", "globex", "Globex", "a7c2", "Forward Deployed Engineer", ["Remote, United States"],
            180000, 230000, 2, FDE),
        job("lever", "globex", "Globex", "a6f1", "Senior Backend Engineer (Python)", ["Denver, CO, United States"],
            175000, 220000, 8, GENERIC),
        job("lever", "globex", "Globex", "a5d9", "Machine Learning Engineer", ["Remote, United States"],
            170000, 210000, 25, PLATFORM),
    ],
    ("ashby", "initech"): [
        job("ashby", "initech", "Initech", "c1", "Senior ML Platform Engineer",
            ["Denver, CO, United States", "Remote, United States"], 190000, 240000, 0, PLATFORM),
        job("ashby", "initech", "Initech", "c0", "AI Engineer, LLM Apps", ["Remote, United States"],
            185000, 235000, 20, AGENTS.replace("Acme", "Initech")),
    ],
    ("workable", "umbrella"): [
        job("workable", "umbrella", "Umbrella", "U1A2B3", "Applied AI Engineer", ["Remote, United States"],
            170000, 210000, 4, APPLIED),
        job("workable", "umbrella", "Umbrella", "U0Z9Y8", "Senior Data Engineer", ["Remote, United States"],
            160000, 200000, 14, GENERIC),
    ],
    ("workday", "hooli.wd5/Careers"): [
        job("workday", "hooli.wd5/Careers", "Hooli", "R0104211", "Principal Engineer, Agents",
            ["Remote, United States"], 240000, 320000, 3, PRINCIPAL),
        job("workday", "hooli.wd5/Careers", "Hooli", "R0103877", "Staff Engineer, Developer Platform",
            ["Remote, United States"], 220000, 280000, 9, GENERIC),
    ],
}

FIT = {  # made-up fit scores, in shortlist-ai's shape
    "greenhouse:acme:4101": (86, 6, 7, ["3+ years with Kubernetes in production"],
                             "Strong match on Python, LLM agents and RAG; Kubernetes depth isn't shown."),
    "ashby:initech:c1": (78, 5, 7, ["GPU serving experience", "Ray or Spark at scale"],
                         "Solid platform and Python background; GPU serving not shown."),
    "lever:globex:a7c2": (74, 4, 5, ["Customer-facing engineering experience"],
                          "Agent and Python work match; no customer-site deployments shown."),
    "workday:hooli.wd5/Careers:R0104211": (69, 4, 6, ["10+ years in software engineering",
                                                      "Large-scale distributed systems"],
                                           "Agent experience fits; seniority asks may be a stretch."),
    "workable:umbrella:U1A2B3": (81, 5, 6, ["Security domain experience"],
                                 "RAG assistants in Python match closely."),
    "lever:globex:a6f1": (72, 4, 5, ["Go or Rust"], "Python services match."),
    "workday:hooli.wd5/Careers:R0103877": (70, 4, 6, ["Kubernetes in production"], "Platform work matches."),
    "ashby:initech:c0": (84, 6, 7, ["3+ years with Kubernetes in production"], "LLM apps experience matches."),
}

# key -> (status, applied days ago, next step, follow-up, note)
TRACK = {
    "lever:globex:a6f1": ("queued", None, None, None, "Ask for a referral first"),
    "workday:hooli.wd5/Careers:R0103877": ("queued", None, None, None, None),
    "ashby:initech:c0": ("interviewing", 12, "Panel interview, Thursday 10:00", "+2", "Recruiter screen went well"),
    "workable:umbrella:U0Z9Y8": ("screening", 9, "Recruiter call", "today", None),
    "greenhouse:acme:4090": ("applied", 6, None, "+5", None),
    "lever:globex:a5d9": ("rejected", 21, None, None, "Closed after the first round"),
}


def seed(out: Path) -> Path:
    """Write the demo into `out`, replacing an earlier demo there; returns its watchlist."""
    out = out.expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        if not (out / MARK).is_file():
            raise SystemExit(f"{out} isn't empty and isn't a jobwatch demo: give an empty or new folder")
        shutil.rmtree(out)
    (out / "state").mkdir(parents=True)
    (out / MARK).write_text("Made by scripts/demo/seed.py: seeding again replaces this folder.\n")
    (out / "jobwatch.yaml").write_text(WATCHLIST)
    (out / "resume.txt").write_text(RESUME)
    store = Store(out / "state" / "state.db")
    for (source, board), jobs in BOARDS.items():
        store.sync(source, board, jobs)
    rid = resume_id(out / "resume.txt")
    for key, (score, met, total, gaps, summary) in FIT.items():
        store.save_score(key, rid, {"score": score, "must_haves_met": met, "must_haves_total": total,
                                    "gaps": gaps, "summary": summary, "flags": []})
    for key, (status, ago, next_step, follow, note) in TRACK.items():
        on = (date.today() - timedelta(days=ago)).isoformat() if ago else None
        store.set_status([key], status, note, on=on)
        store.track(key, next_step=next_step, follow_up=follow)
    store.close()
    return out / "jobwatch.yaml"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=OUT, help=f"the demo's folder (default: {OUT})")
    print(f"Demo watchlist: {seed(ap.parse_args().out)}")


if __name__ == "__main__":
    main()
