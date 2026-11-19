"""ATS check: a posting's keywords against the text of the job's resume, as a parser reads it. Reading a PDF is faked
(pdftotext), and no model is involved."""

import json
import subprocess

import pytest

from jobwatch import ats, cli, config
from jobwatch.store import Store
from jobwatch.web import ApiError, App

POSTING = """About Initech
Initech builds widgets for logistics teams. Our Globex partnership runs on Monday.

What you'll do:
- Run the platform on Kubernetes and keep CI/CD pipelines fast
- Own PostgreSQL schema changes with the data team

Requirements:
- 6+ years of Python and AWS in production
- Experience with Terraform and observability tooling
- Comfortable in C++ or Rust is a plus

Nice to have:
- Experience with Kafka or other event streaming

Benefits
- Dental and a gym stipend
"""
RESUME = """Jordan Rivera
jordan@example.com  3035550142

Experience
Platform Engineer, Globex (2019-2024)
- Ran 40 K8s clusters on AWS with Terraform
- Wrote Python tooling for the on-call rotation
- Cut deploy time from 40 minutes to 9 by caching builds and splitting the monorepo into services
- Mentored four engineers and ran the quarterly capacity review with finance

Education
BS Computer Science, Boulder, CO

Skills
Python, Terraform, AWS, observability, Kubernetes, Postgres
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "resume.txt").write_text(RESUME)
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies: []\nresume: resume.txt\nstate: state.db\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    job = store.add("Initech", "Senior Platform Engineer", status="queued", description=POSTING)
    yield cfg, store, job.key, path
    store.close()


def by_term(rows):
    return {r["term"]: r for r in rows}


def test_keywords_come_from_the_requirements_with_aliases_and_tools():
    kws = by_term(ats.keywords("Senior Platform Engineer", "Initech", POSTING))
    assert kws["Kubernetes"]["kind"] == "must" and kws["AWS"]["kind"] == "must" and kws["Terraform"]["kind"] == "must"
    assert kws["Kafka and streaming"]["kind"] == "nice"
    assert kws["SQL"]["kind"] == "must" and kws["C++"]["kind"] == "must"  # PostgreSQL is the catalog's SQL
    assert kws["Python"]["kind"] == "must" and kws["Rust"]["kind"] == "must"  # tools the catalog doesn't know
    # the company, the title and the days of the week aren't tools; the benefits aren't asked for
    assert not {"Initech", "Globex", "Monday", "Dental", "Platform"} & set(kws)


def test_the_catalog_matches_an_alias_in_the_resume(ctx):
    cfg, store, key, _ = ctx
    r = ats.check(cfg, store, key)
    assert "Kubernetes" not in by_term(r["missing"])  # the resume says K8s and Kubernetes
    assert {"Kafka and streaming", "C++", "Rust"} <= set(by_term(r["missing"]))
    assert {"Python", "Terraform", "AWS", "SQL"} <= set(by_term(r["found"]))  # "Postgres" is the catalog's SQL
    assert 0 < r["score"] < 100 and r["file"] == "resume.txt" and r["tailored"] is False
    assert r["read_with"] == "text" and r["checks"] == []


def test_a_must_have_counts_double(ctx):
    cfg, store, key, _ = ctx
    r = ats.check(cfg, store, key)
    rows = [*r["found"], *r["missing"]]
    weight = {"must": 2, "nice": 1, "mentioned": 1}
    want = round(100 * sum(weight[x["kind"]] for x in r["found"]) / sum(weight[x["kind"]] for x in rows))
    assert r["score"] == want


def test_the_tailored_pdf_is_read_with_pdftotext_and_wins_over_the_general_resume(ctx, monkeypatch):
    cfg, store, key, _ = ctx
    store.package(key).attach("Jordan_Rivera_Resume_Initech.pdf", b"%PDF-1 fake", "resume")
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, RESUME + "\nKafka, C++, Rust\n", "")

    monkeypatch.setattr(ats.shutil, "which", lambda name: "/opt/bin/" + name)
    monkeypatch.setattr(ats.subprocess, "run", fake)
    r = ats.check(cfg, store, key)
    assert calls[0][0] == "/opt/bin/pdftotext" and calls[0][1:3] == ["-enc", "UTF-8"] and calls[0][-1] == "-"
    assert r["tailored"] is True and r["read_with"] == "pdftotext" and r["file"] == "Jordan_Rivera_Resume_Initech.pdf"
    assert not {"Kafka and streaming", "C++", "Rust"} & set(by_term(r["missing"]))


def test_a_pdf_with_no_pdftotext_falls_back_to_shortlist_then_says_what_to_install(ctx, monkeypatch):
    cfg, store, key, _ = ctx
    store.package(key).attach("Resume.pdf", b"%PDF-1 fake", "resume")
    monkeypatch.setattr(ats.shutil, "which", lambda name: None)
    monkeypatch.setattr(ats, "resume_text", lambda path: RESUME)
    assert ats.check(cfg, store, key)["read_with"] == "shortlist-ai"
    monkeypatch.setattr(ats, "resume_text", lambda path: "")
    with pytest.raises(ValueError, match="install poppler"):
        ats.check(cfg, store, key)


def test_an_image_only_pdf_is_flagged():
    assert "almost no readable text" in ats.format_checks("  \n", "Platform Engineer")[0]


@pytest.mark.parametrize("text, flag", [
    (RESUME.replace("jordan@example.com", ""), "No email address"),
    (RESUME.replace("3035550142", ""), "No phone number"),
    (RESUME.replace("Education\n", "Schooling\n"), "No Education heading"),
    (RESUME + "\n Led a team �", "came out as boxes"),
    (RESUME.replace("Platform Engineer", "Builder"), "None of the title's words"),
])
def test_format_checks_name_what_a_parser_would_trip_on(text, flag):
    assert any(flag in c for c in ats.format_checks(text, "Senior Platform Engineer"))


def test_a_clean_resume_has_no_format_flags():
    assert ats.format_checks(RESUME, "Senior Platform Engineer") == []


def test_no_posting_text_or_no_resume_is_an_error_that_says_so(ctx, tmp_path):
    cfg, store, key, _ = ctx
    bare = store.add("Umbrella", "Data Engineer", status="queued", description="")
    with pytest.raises(ValueError, match="no posting text"):
        ats.check(cfg, store, bare.key)
    cfg.resume = None
    with pytest.raises(ValueError, match="no resume to check"):
        ats.check(cfg, store, key)
    other = tmp_path / "other.txt"
    other.write_text(RESUME)
    assert ats.check(cfg, store, key, resume=other)["file"] == "other.txt"


def test_the_command_prints_the_check_and_json(ctx, capsys):
    _, _, key, path = ctx
    cli.main(["-c", str(path), "ats", key])
    out = capsys.readouterr().out
    assert out.startswith("Initech: Senior Platform Engineer\nResume: resume.txt (your general resume, not tailored")
    assert "Missing from the resume's text:" in out and "  Kafka and streaming  (nice to have, " in out
    assert "How a parser reads it: nothing to fix." in out and "Add a keyword only where it's true of you" in out
    cli.main(["-c", str(path), "ats", key, "--format", "json"])
    got = json.loads(capsys.readouterr().out)
    assert got["key"] == key and {"found", "missing", "checks", "score"} <= set(got)


def test_the_page_endpoint_returns_the_check_and_errors_plainly(ctx):
    _, _, key, path = ctx
    got = App(path).get_ats({"key": [key]})
    assert got["title"] == "Senior Platform Engineer" and got["missing"]
    with pytest.raises(ApiError, match="no job"):
        App(path).get_ats({"key": ["nope"]})
