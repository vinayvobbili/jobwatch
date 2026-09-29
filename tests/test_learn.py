import os
import urllib.error
import urllib.request

import pytest

from jobwatch import cli, config, learn
from jobwatch.models import Job
from jobwatch.web import ApiError, App

SKILLS = {s.id: s for s in learn.catalog()}


def job(id_, text, title="Engineer"):
    return Job("greenhouse", "acme", id_, title, f"https://example.com/{id_}", company_name="Acme",
               description=text)


def fit(*gaps):
    return {"score": 60, "must_haves_met": 3, "must_haves_total": 5, "gaps": list(gaps)}


def test_catalog_entries_are_complete():
    assert len(SKILLS) == len(learn.catalog())  # ids are unique
    for s in SKILLS.values():
        assert s.name and s.search and s.options, s.id
        for o in s.options:
            assert o["kind"] in ("certification", "course", "guide"), (s.id, o)
            assert o["cost"] in ("free", "paid") and o["time"] in learn.TIME, (s.id, o)
            assert o["url"].startswith("https://") and o["name"] and o["provider"], (s.id, o)


@pytest.mark.parametrize("text, skill, found", [
    ("Python, Go, Rust", "go", True), ("experience in Go", "go", True), ("Golang services", "go", True),
    ("(Go)", "go", True), ("It Doesn't Go in the Report", "go", False), ("Go-to-market", "go", False),
    ("ready to go", "go", False), ("Java and Kotlin", "java", True), ("JavaScript", "java", False),
    ("Rust", "rust", True), ("rust on the pipes", "rust", False), ("5+ yrs of K8s", "kubernetes", True),
    ("Amazon Web Services", "aws", True), ("laws of physics", "aws", False),
])
def test_skill_patterns(text, skill, found):
    assert SKILLS[skill].found_in(text) is found


def test_build_ranks_gaps_by_demand_and_sorts_out_what_a_course_cant_close():
    jobs = [job("1", "AWS and Kubernetes"), job("2", "AWS, Terraform"), job("3", "Python on AWS")]
    fits = [fit("3+ years with Kubernetes in production", "US citizenship required", "Salesforce CPQ experience"),
            None, fit("Active TS/SCI clearance")]
    r = learn.build(list(zip(jobs, fits, strict=True)), "Built Terraform modules.", "month", "Denver")
    names = [d.skill.id for d in r.skills]
    # Kubernetes: one mention + a missing must-have (weight 4) beats AWS's three mentions; Terraform is on the resume.
    assert names == ["kubernetes", "aws", "terraform"] and [d.skill.id for d in r.gaps()] == ["kubernetes", "aws"]
    k8s = r.skills[0]
    assert k8s.years and k8s.gap_jobs == [jobs[0]] and k8s.weight == 4
    assert set(r.blockers) == {"Work authorization", "Security clearance"}
    assert r.other_gaps == [("Salesforce CPQ experience", jobs[0])] and r.scored == 2 and r.jobs == 3
    assert learn.search_url("5+ years of experience with Salesforce CPQ").endswith("query=Salesforce%20CPQ")
    d = learn.to_dict(r)
    assert d["timeline"] == "month" and d["skills"][0]["gap_count"] == 1 and d["skills"][0]["of"] == 3
    with pytest.raises(ValueError):
        learn.build([], "", "someday")


def test_timeline_decides_what_fits_and_whether_colleges_show():
    aws = SKILLS["aws"]
    week = learn.options(aws, "week")
    assert week[0]["time"] == "weeks" and not any(o["fits"] for o in week)  # quickest first
    assert all(o["fits"] for o in learn.options(aws, "any"))
    assert [m["provider"] for m in learn.more(aws, "month", "Denver")] == ["LinkedIn Learning", "Coursera", "edX"]
    colleges = learn.more(aws, "quarter", "Denver")[-1]
    assert colleges["provider"] == "Colleges near Denver" and "near%20Denver" in colleges["url"]
    assert learn.more(aws, "any", "")[-1]["provider"] == "edX"  # no city, no colleges
    assert learn.more(SKILLS["agents"], "week")[0]["provider"] == "DeepLearning.AI"
    assert "keywords=Go%20programming%20language" in learn.more(SKILLS["go"])[0]["url"]


def test_summary_and_markdown_keep_to_the_timeline():
    r = learn.build([(job("1", "AWS", "Cloud Engineer"), fit("AWS certification"))], "", "month")
    md = learn.markdown(r)
    assert "## AWS" in md and "AWS Skill Builder" in md and "No resume in the watchlist" in md
    assert "Longer than your timeline: AWS Certified Solutions Architect" in md
    s = learn.summary(r)
    assert "timeline for learning: month" in s and "Skill Builder" in s and "Solutions Architect" not in s
    assert "a missing must-have in 1 scored job." in s


def test_for_job_puts_missing_must_haves_first():
    gaps = learn.for_job(job("1", "Kafka, AWS, Snowflake"), fit("Snowflake in production"), "Kafka pipelines")
    assert [d.skill.id for d in gaps] == ["snowflake", "aws"]


def test_learning_settings(watchlist):
    cfg = config.load(watchlist)
    assert cfg.timeline == "quarter" and cfg.near == "Denver"  # the first place that isn't "remote"
    config.save(watchlist, {"learning": {"timeline": "week", "near": ""}})
    cfg = config.load(watchlist)
    assert cfg.timeline == "week" and cfg.near == ""
    with pytest.raises(config.ConfigError, match=r"learning\.timeline"):
        config.save(watchlist, {"learning": {"timeline": "someday"}})
    assert config.load(watchlist).timeline == "week"  # a bad save leaves the file alone


def test_skills_in_the_page_and_the_terminal(watchlist, web, capsys):
    app = App(watchlist)
    app.post_fetch({})
    got = app.get_skills({"timeline": ["any"]})
    assert got["timeline"] == "any" and got["near"] == "Denver" and got["jobs"] == 3
    ids = [s["id"] for s in got["skills"]]
    assert {"ml", "llm", "distributed"} <= set(ids)
    assert app.get_settings({})["learning"] == {}
    with pytest.raises(ApiError):
        app.get_skills({"timeline": ["someday"]})
    assert any(s["id"] == "ml" for s in app.get_job({"key": ["aaaa-1111"]})["skills"])
    cli.main(["-c", str(watchlist), "skills", "--timeline", "week"])
    out = capsys.readouterr().out
    assert out.startswith("# Skills to build") and "Timeline: week" in out and "## Machine learning" in out


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("JOBWATCH_LINK_TESTS"), reason="network: set JOBWATCH_LINK_TESTS=1")
def test_catalog_links_resolve():
    """Every curated link still answers (run before a release; sites move pages)."""
    urls = sorted({o["url"] for s in learn.catalog() for o in s.options})
    broken = []
    for url in urls:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (jobwatch link check)"})
        try:
            with urllib.request.urlopen(req, timeout=20):
                pass
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429):  # bot walls answer 403/429 to scripts but work in a browser
                broken.append(f"{e.code} {url}")
        except OSError as e:
            broken.append(f"{e} {url}")
    assert not broken, "\n".join(broken)
