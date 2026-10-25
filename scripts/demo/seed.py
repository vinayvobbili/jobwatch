"""Seed the demo: a watchlist and a state file holding only made-up companies (Acme, Globex, Initech, Umbrella,
Hooli), made-up jobs and a made-up resume, for the README's demo video.

    python scripts/demo/seed.py -o scripts/demo/out/demo
    python scripts/demo/seed.py -o scripts/demo/out/demo-more --more    # + the tutorials' records

Everything lives in that folder (watchlist, resume, state, cache). Nothing reads or writes your own watchlist or
~/.local/share/jobwatch, and nothing reaches the network: the jobs are written straight into the state file.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jobwatch import logos
from jobwatch.contacts import TIES_FILE
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.suggest import company_id

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
fetch_every: off   # the page checks no board by itself: nothing here reaches the web
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
CUSTOMER = posting("Globex sends engineers to sit with customers and ship.",
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
        job("greenhouse", "acme", "Acme", "4101", "Staff Data Engineer", ["Remote, United States"],
            210000, 260000, 1, AGENTS),
        job("greenhouse", "acme", "Acme", "4102", "Solutions Architect, AI", ["Denver, CO, United States"],
            170000, 215000, 5, GENERIC),
        job("greenhouse", "acme", "Acme", "4090", "Platform Engineer", ["Remote, United States"],
            165000, 205000, 18, GENERIC),
    ],
    ("lever", "globex"): [
        job("lever", "globex", "Globex", "a7c2", "Data Platform Engineer", ["Remote, United States"],
            180000, 230000, 2, CUSTOMER),
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
        job("workable", "umbrella", "Umbrella", "U1A2B3", "Senior Data Platform Engineer", ["Remote, United States"],
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


# -- the tutorials' extras (seed(..., more=True)): comps, contacts, interviews, a package, prep sheets and stories,
# all made up, in a separate folder so the README demo's scenes stay as they are.

MORE_WATCHLIST = """\
pay:
  target: 200000-230000
  floor: 175000
connections: connections/Connections.csv
stories: stories.yaml
prep:
  sheets: prep
calendar:
  remind: 30
"""

CONNECTIONS = [  # name, company, position, how well the made-up candidate knows them: (messages, last message)
    ("Maya Okafor", "Initech", "Staff Engineer", (14, "2026-09-02")),
    ("Theo Brandt", "Initech", "Recruiter", (3, "2026-07-18")),
    ("Priya Raman", "Acme", "Engineering Manager", (9, "2026-08-11")),
    ("Lucas Ferreira", "Globex", "Senior Engineer", (1, "2026-02-05")),
    ("Nora Kim", "Umbrella", "Director of Data", (6, "2026-06-30")),
    ("Sam Whitfield", "Hooli", "Principal Engineer", (2, "2026-04-21")),
    ("Elena Petrova", "Vandelay Industries", "Engineering Manager", (11, "2026-10-01")),
    ("Jonas Albrecht", "Acme", "Recruiter", (0, "")),
]
STORIES = """\
# Made-up stories for the demo candidate.
- id: eval-harness
  title: Built an evaluation harness for prompts and models
  did: Wrote a Python harness that replays saved questions against each prompt or model change and scores the answers.
  hard: The team disagreed on what a good answer was, so I wrote the rubric with the support leads first.
  result: Regressions caught before release went from none to about one a week.
  skills: [Python, LLM, evaluation]
- id: support-agent
  title: Shipped a support agent with retrieval
  did: Built an agent that answers support questions from the help center with RAG and vector search.
  hard: Old articles contradicted new ones, so I added a freshness rule to the retrieval step.
  result: The agent answered 40% of tickets without a person, with a thumbs-up rate of 82%.
  skills: [Python, RAG, agents]
"""
SHEET = """<!doctype html><meta charset="utf-8"><title>Initech onsite</title>
<style>body{font:16px/1.5 -apple-system,sans-serif;max-width:640px;margin:40px auto}</style>
<h1>Initech: panel interview</h1>
<p>Made-up prep sheet for the demo.</p>
"""


def at(days: int, hour: str) -> str:
    """A next step's meeting time, `days` from today: "Tue 10/27 10:00 AM"."""
    d = date.today() + timedelta(days=days)
    return f"{d:%a} {d.month}/{d.day} {hour}"


def extras(out: Path, store: Store):
    """Add the tutorials' records to the seeded demo: more applications (one gone quiet, one with an offer),
    interviews with times, pay and company details, a saved package, connections, stories and a prep sheet."""
    with (out / "jobwatch.yaml").open("a") as f:
        f.write(MORE_WATCHLIST)
    (out / "stories.yaml").write_text(STORIES)
    (out / "prep").mkdir()
    (out / "prep" / "initech-panel.html").write_text(SHEET)
    (out / "connections").mkdir()
    with (out / "connections" / "Connections.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        for name, company, position, _ in CONNECTIONS:
            first, _, last = name.partition(" ")
            w.writerow([first, last, f"https://www.linkedin.com/in/{first.lower()}-{last.lower()}-demo", "",
                        company, position, ""])
    ties = {f"{n.split()[0].lower()}-{n.split()[1].lower()}-demo": {"messages": m, "last_message": last}
            for n, _, _, (m, last) in CONNECTIONS if m}
    (out / "connections" / TIES_FILE).write_text(json.dumps(ties, indent=1))

    store.track("ashby:initech:c0", next_step=f"Panel interview {at(3, '10:00 AM')}")
    store.track("workable:umbrella:U0Z9Y8", next_step=f"Recruiter call {at(2, '2:15-3:00 PM')}")
    quiet = store.add("Soylent", "Principal Engineer", "https://jobs.example.com/soylent/p1", "applied",
                      applied=(date.today() - timedelta(days=30)).isoformat(), note="Via a recruiter",
                      follow_up=(date.today() - timedelta(days=16)).isoformat())
    offer = store.add("Vandelay Industries", "Staff Platform Engineer", "https://jobs.example.com/vandelay/s1",
                      "offer", applied=(date.today() - timedelta(days=26)).isoformat(),
                      note="Offer call went well", next_step="Decide on the offer", follow_up="+3")
    unwatched = [(quiet.display_company, quiet.key), (offer.display_company, offer.key)]
    for name, title in (("Pied Piper", "Senior Platform Engineer"), ("Cyberdyne", "AI Engineer")):
        alert = store.add(name, title, f"https://jobs.example.com/{name.lower().replace(' ', '')}/a1", "new",
                          location="Remote, United States",
                          description=posting(f"{name} is hiring.", ["Build Python services and LLM features"],
                                              ["Python", "AWS"], ["Kubernetes"]) + "\n\nPay: $180,000 - $220,000")
        store.set_via(alert.key, "linkedin-alert")
        unwatched.append((name, alert.key))
    for name, key in unwatched:  # a board given for each company, so the page looks none up on the web
        store.note_unwatched(company_id(name), name, key, entry=f"greenhouse:{company_id(name)}",
                             found_by="posting")
    for job_, _ in store.jobs(include_closed=True):  # no logo to look for on the web: the page draws initials
        store.save_logo(logos.key(job_.display_company), "", "", b"")

    store.set_comp("ashby:initech:c0", base="190-220K", bonus="10% target", equity="40K RSUs over 4 years",
                   asked="220-240K", role="product", career_note="LLM apps, staff IC",
                   note="Recruiter said 220K is the top of the band")
    store.set_comp("workable:umbrella:U0Z9Y8", base="165-185K", bonus="8% target", role="internal",
                   career_note="Internal analyst tools")
    store.set_comp(offer.key, base="205K", bonus="10% target", equity="60K RSUs over 4 years", signon="15K",
                   asked="215K", offered="205K", role="customer", career_note="Forward-deployed, travel 20%")
    store.set_health("Initech", kind="tech", listing="private", stage="Series C, $90M, 2025", raised="$180M",
                     revenue="1.8x YoY", headcount="growing", layoffs="none", rating="4.2 Glassdoor",
                     sources="https://example.com/initech")
    store.set_health("Umbrella", kind="enterprise", listing="public", headcount="shrinking",
                     layoffs="8% in 2026", rating="3.2 Glassdoor", risk="reorganizing the data group",
                     sources="https://example.com/umbrella")
    store.set_health("Vandelay Industries", kind="consulting", listing="private", stage="Series A, $20M, 2025",
                     raised="$25M", headcount="growing", layoffs="none", rating="3.9 Glassdoor",
                     sources="https://example.com/vandelay")
    store.rate_contact("maya-okafor-demo", "use", "answers fast")
    store.rate_contact("jonas-albrecht-demo", "skip", "doesn't check LinkedIn")

    package = store.package("ashby:initech:c0")
    package.attach("Resume_Initech.pdf", b"%PDF-1.4 demo resume")
    package.attach("Cover_Letter_Initech.pdf", b"%PDF-1.4 demo cover letter")
    package.write(answers=[{"question": "Salary expectation", "answer": "Open, based on the full package"},
                           {"question": "Notice period", "answer": "Two weeks"},
                           {"question": "Why Initech?", "answer": "The ML platform serves every product team."}])
    package.practise("Tell me about an LLM feature you shipped.",
                     "I built a support agent with retrieval.",
                     "I built a support agent that answers from the help center with RAG, and added a freshness "
                     "rule so old articles don't win. It answered 40% of tickets without a person.")


def settle_dates(store: Store):
    """Dates a person would see: a job applied to was first seen the day before at the latest (local days, so no
    UTC day ahead of today), and the boards were last checked three hours ago, with nothing failed."""
    local = datetime.now().astimezone()
    for job_, rec in store.applications():
        if rec["applied_at"]:
            applied = datetime.fromisoformat(rec["applied_at"]).replace(hour=12, tzinfo=local.tzinfo)
            seen = min(datetime.fromisoformat(rec["first_seen"]), applied - timedelta(days=1))
            with store.db:
                store.db.execute("UPDATE jobs SET first_seen=? WHERE key=?", (seen.isoformat(), job_.key))
    store.record_fetch(len(BOARDS), sum(map(len, BOARDS.values())), 6, {}, {})
    with store.db:
        three_hours_ago = (local - timedelta(hours=3)).astimezone(timezone.utc)
        store.db.execute("UPDATE fetches SET at=?", (three_hours_ago.isoformat(),))


def seed(out: Path, more: bool = False) -> Path:
    """Write the demo into `out`, replacing an earlier demo there; returns its watchlist. more: the tutorials'
    extra records on top (see extras)."""
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
    if more:
        extras(out, store)
    settle_dates(store)
    store.close()
    return out / "jobwatch.yaml"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=OUT, help=f"the demo's folder (default: {OUT})")
    ap.add_argument("--more", action="store_true", help="add the tutorials' records: comps, contacts, interviews...")
    args = ap.parse_args()
    print(f"Demo watchlist: {seed(args.out, args.more)}")


if __name__ == "__main__":
    main()
