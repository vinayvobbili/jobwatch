"""Prep sheets: the posting's asks next to the resume's closest lines, found even for applications added by hand."""

import pytest

from jobwatch import cli, config, prep
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

POSTING = """About us
We make widgets.

What you'll do:
- Lead the design of detection pipelines for cloud workloads
- Partner with product teams on threat models

Requirements:
- 8+ years building Python services in production
- Experience mentoring engineers and leading design reviews
- Deep Kubernetes operations experience

Nice to have:
- Published open-source security tooling

Benefits
- Dental
"""

RESUME = """Jane Doe
EXPERIENCE
• Built Python detection services running in production at 10,000
events per second, with CI/CD and on-call ownership
• Mentored four engineers and ran the team's design reviews for two years
• Published three open-source security tools on PyPI
EDUCATION
State University — BS in Computer Science, 2010
"""


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "resume.txt").write_text(RESUME)
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: []\nresume: {tmp_path / 'resume.txt'}\nstate: {tmp_path / 'state.db'}\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    posting = Job("workday", "initech.wd5/External", "R0123456-1", "Staff Detection Engineer",
                  "https://initech.wd5.myworkdayjobs.com/External/job/x_R0123456-1", company_name="Initech",
                  description=POSTING)
    other = Job("workday", "globex.wd1/Careers", "R0123456", "Staff Detection Engineer", "", company_name="Globex",
                description="Other company, same number.")
    store.sync("workday", posting.company, [posting])
    store.sync("workday", other.company, [other])
    yield cfg, store, path
    store.close()


def test_asks_by_section():
    got = prep.asks(POSTING)
    assert [k for _, k in got] == ["need"] * 3 + ["do"] * 2 + ["nice"]
    assert got[0][0] == "8+ years building Python services in production"
    assert not any("Dental" in a or "widgets" in a for a, _ in got)


def test_resume_lines_undo_wrapping_and_skip_school():
    lines = prep._resume_lines(RESUME)
    assert lines[0].startswith("Built Python") and lines[0].endswith("on-call ownership")
    assert not any("University" in ln for ln in lines)


def test_pairs_each_ask_with_the_closest_line_or_none():
    by_ask = {m.ask: m for m in prep.pair(prep.asks(POSTING), RESUME)}
    assert by_ask["8+ years building Python services in production"].resume.startswith("Built Python")
    mentor = by_ask["Experience mentoring engineers and leading design reviews"]
    assert mentor.resume.startswith("Mentored") and "mentoring" in mentor.shared
    assert by_ask["Deep Kubernetes operations experience"].resume == ""  # nothing close: say so, don't invent


@pytest.mark.parametrize("title, found", [
    ("Staff Detection Engineer (R0123456)", True), ("Staff Detection Engineer R0123456", True),
    ("Staff Detection Engineer", False), ("Staff Detection Engineer (R0123457)", False),
])
def test_a_hand_added_application_finds_its_posting_by_requisition_id(setup, title, found):
    _, store, _ = setup
    job = store.add("Initech", title)
    linked = store.linked(job)
    assert (linked.key if linked else None) == ("workday:initech.wd5/External:R0123456-1" if found else None)


def test_requisition_formats():
    from jobwatch.store import _same_req
    assert _same_req("REQ-47040", "REQ-47040") and _same_req("JOB 20769", "20769")
    assert _same_req("R0970084", "R0970084-1") and not _same_req("R097008", "R0970084")
    assert not _same_req("4711", "c0ffee12-4711-4711-4711-123456789abc")


def test_sheet(setup):
    cfg, store, _ = setup
    job = store.add("Initech", "Staff Detection Engineer (R0123456)", status="screening",
                    next_step="Recruiter call Tuesday")
    store.package(job.key).write(answers=[{"question": "Why us?", "answer": "Detection at scale."}])
    s = prep.build(cfg, store, job.key)
    assert s.posting_key == "workday:initech.wd5/External:R0123456-1" and s.url.startswith("https://initech")
    assert s.resume_used == "base" and s.expect == prep.SCREEN_QUESTIONS and s.ask == prep.ASK_SCREEN
    assert any(g["name"] == "Kubernetes" for g in s.gaps)
    md = prep.markdown(s)
    for text in ("# Prep: Staff Detection Engineer (R0123456), Initech", "Recruiter call Tuesday",
                 "  - You: Built Python", "**Why us?** Detection at scale.", "## Be ready to be honest about"):
        assert text in md, text
    store.set_status([job.key], "interviewing")
    assert prep.build(cfg, store, job.key).expect == prep.INTERVIEW_QUESTIONS


def test_cli_and_web(setup, capsys):
    _, store, path = setup
    job = store.add("Initech", "Staff Detection Engineer (R0123456)")
    cli.main(["--config", str(path), "prep", job.key])
    assert "# Prep: Staff Detection Engineer" in capsys.readouterr().out
    got = App(path).get_prep({"key": [job.key]})
    assert got["posting_key"].endswith("R0123456-1") and got["markdown"].startswith("# Prep:")
