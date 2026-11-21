"""The filter pass (jobpass.py): every tab that starts from "which jobs pass the filters" shares one run of it, and
gets what the per-tab passes it replaced gave."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from jobwatch import config, jobpass, referrals, watch
from jobwatch.filters import KINDS, reject_reason, rejection, relevance
from jobwatch.models import Job
from jobwatch.store import Store

NOW = datetime.now(timezone.utc)
FIT = {"score": 40, "must_haves_met": 1, "must_haves_total": 3, "gaps": [], "summary": ""}


def job(i, title="Platform Engineer", company="initech", days=2, **more):
    return Job(source="greenhouse", company=company, id=str(i), title=title, url=f"https://example.com/{company}/{i}",
               company_name=company.title(), locations=more.pop("locations", ["Remote"]),
               posted=NOW - timedelta(days=days), description=more.pop("description", "Python and RAG work"), **more)


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "cv.md").write_text("Python, RAG")
    (tmp_path / "people.csv").write_text(
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Jane,Doe,https://www.example.com/in/jane-doe,,Globex,Staff Engineer,01 Jan 2024\n")
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({
        "companies": ["greenhouse:initech"], "state": "state.db", "cache": "cache", "resume": "cv.md",
        "connections": "people.csv",
        "filters": {"locations": ["remote"], "exclude_titles": ["manager"], "exclude_companies": ["Umbrella"],
                    "titles": ["engineer", "analyst", "manager"], "max_age_days": 30, "min_fit": 50},
        "keywords": {"Python": 2, "RAG": 3}}))
    cfg = config.load(path)
    store = Store(cfg.state)
    jobs = [job(1), job(2, "Data Engineer", days=3), job(3, "Engineering Manager"), job(4, "Chef"),
            job(5, "Platform Engineer", days=90), job(6, "Platform Engineer", locations=["Paris"]),
            job(7, "ML Engineer", "umbrella"), job(8, "Security Engineer", "globex"), job(9, "Analyst", "globex"),
            job(10, "SRE", "globex"), job(11, "Platform Engineer", days=2, salary_min=1000, salary_max=2000)]
    store.sync("greenhouse", "initech", [j for j in jobs if j.company == "initech"])
    store.sync("greenhouse", "umbrella", [j for j in jobs if j.company == "umbrella"])
    store.sync("greenhouse", "globex", [j for j in jobs if j.company == "globex"])
    store.set_status(["greenhouse:initech:2"], "shown")
    store.set_status(["greenhouse:globex:8"], "queued")
    from jobwatch.score import resume_id
    store.save_score("greenhouse:initech:1", resume_id(cfg.resume, cfg.prompts), FIT)  # under min_fit
    yield cfg, store, path
    store.close()


def old_matching(cfg, store, statuses, redo_passes=False):
    """_matching as it was before the pass was remembered: every job judged on every call."""
    from jobwatch import dupes
    from jobwatch.filters import focus_hits
    from jobwatch.score import brief, resume_id
    rejected, entries = {}, []
    rid = resume_id(cfg.resume, cfg.prompts) if cfg.resume and cfg.resume.is_file() else None
    fits = watch._fits(store, rid) if rid else {}
    index = dupes.Index(store)
    for j, record in store.iter_jobs(statuses):
        fit = fits.get(j.key)
        f = cfg.filters_for(j)
        judged = None if redo_passes and fit and (fit.get("fallback") or fit.get("stale")) else fit
        reason, same = reject_reason(j, f, judged), None
        if reason and reason.startswith("posted") and (same := index.match(j, record)) and same.back:
            reason = reject_reason(j, replace(f, max_age_days=None), judged)
        if reason:
            rejected[reason.split()[0]] = rejected.get(reason.split()[0], 0) + 1
            continue
        same = same or index.match(j, record)
        rel, hits = relevance(j, cfg.keywords)
        entries.append(watch.Entry(j, record, rel, hits, fit=brief(fits.get(j.key)), duplicate=same,
                                   focus=focus_hits(j, cfg.focus)))
    return entries, rejected


def old_hidden(cfg, store, kind=""):
    from jobwatch.score import resume_id
    fits = watch._fits(store, resume_id(cfg.resume, cfg.prompts)) if cfg.resume and cfg.resume.is_file() else {}
    by, companies, jobs = {}, dict.fromkeys(cfg.filters.exclude_companies, 0), []
    for j, rec in store.iter_jobs(("new", "shown")):
        f = cfg.filters_for(j)
        if r := rejection(j, f, fits.get(j.key)):
            by[r[0]] = by.get(r[0], 0) + 1
            if r[0] == "company" and not rejection(j, replace(f, exclude_companies=[]), fits.get(j.key)):
                from jobwatch.filters import excluded_company
                name = excluded_company(j, f.exclude_companies)
                companies[name] = companies.get(name, 0) + 1
            if r[0] == kind:
                jobs.append({"key": j.key, "title": j.title, "company": j.display_company, "url": j.url,
                             "locations": j.places, "pay": j.pay(), "age_days": j.age_days(), "kind": r[0],
                             "why": r[1]})
    jobs.sort(key=lambda x: x["age_days"] if x["age_days"] is not None else 10_000)
    return {"total": sum(by.values()), "by": {k: by[k] for k in KINDS if k in by}, "kind": kind or None,
            "jobs": jobs[:100], "more": max(0, len(jobs) - 100), "companies": companies}


def shape(entries):
    return [(e.job.key, e.record["status"], e.relevance, e.keywords, e.fit, e.warnings) for e in entries]


@pytest.fixture
def judgings(monkeypatch):
    """How many times the filters were run over the whole table."""
    calls = []
    real = jobpass.judge
    monkeypatch.setattr(jobpass, "judge", lambda *a: calls.append(1) or real(*a))
    jobpass.forget()
    return calls


def test_the_pass_gives_what_the_separate_passes_gave(setup):
    cfg, store, _ = setup
    jobpass.forget()
    for statuses, redo in ((("new", "shown"), False), (("new",), False), (("new", "shown"), True)):
        got, rejected = watch._matching(cfg, store, statuses, redo)
        old, old_rejected = old_matching(cfg, store, statuses, redo)
        assert shape(got) == shape(old) and rejected == old_rejected
    assert rejected  # the made-up jobs hit several filters
    for kind in ("", *KINDS):
        assert watch.hidden(cfg, store, kind) == old_hidden(cfg, store, kind)
    assert watch.hidden(cfg, store)["by"] and watch.hidden(cfg, store)["companies"] == {"Umbrella": 1}


def test_redo_passes_still_lets_a_stale_score_under_min_fit_through(setup):
    cfg, store, _ = setup
    jobpass.forget()
    assert "greenhouse:initech:1" not in [e.job.key for e in watch._matching(cfg, store, ("new", "shown"))[0]]
    from jobwatch.score import resume_id
    store.save_score("greenhouse:initech:1", resume_id(cfg.resume, cfg.prompts), {**FIT, "fallback": True})
    assert "greenhouse:initech:1" in [e.job.key for e in watch._matching(cfg, store, ("new", "shown"), True)[0]]
    assert "greenhouse:initech:1" not in [e.job.key for e in watch._matching(cfg, store, ("new", "shown"))[0]]


def old_referrals(cfg, store):
    """referrals.view as it was: every new or shown job through the filters."""
    from jobwatch.store import closed_state
    known = watch.load_contacts(cfg)
    found = {}
    for j, rec in store.jobs(referrals.OPEN, include_closed=True):
        if closed_state(rec) == "closed" and rec["status"] in ("new", "shown", "queued"):
            continue
        if rec["status"] in ("new", "shown") and reject_reason(j, cfg.filters_for(j)):
            continue
        names = (j.display_company, j.company)
        for p in known.at(*names) + known.left_out(*names):
            row = found.setdefault(p["key"], {**p, "jobs": []})
            if j.key not in {x["key"] for x in row["jobs"]}:
                row["jobs"].append({"key": j.key, "title": j.title, "company": j.display_company,
                                    "status": rec["status"]})
    return list(found.values())


def test_referrals_use_the_same_people_and_jobs_as_before(setup):
    cfg, store, _ = setup
    jobpass.forget()
    got = referrals.view(cfg, store)
    assert [p["jobs"] for p in got["people"]] == [p["jobs"] for p in old_referrals(cfg, store)]
    # Security Engineer (queued) and Analyst pass; SRE fails the titles filter
    assert {j["key"] for j in got["people"][0]["jobs"]} == {"greenhouse:globex:8", "greenhouse:globex:9"}


def test_digest_hidden_line_and_referrals_judge_the_table_once(setup, judgings):
    cfg, store, _ = setup
    watch.build_digest(cfg, store, include_seen=True, score_top=0)
    watch.hidden(cfg, store)
    watch.scoring_line(cfg, store)
    referrals.view(cfg, store)
    watch.build_digest(cfg, store, include_seen=True, score_top=0)
    assert judgings == [1]


def test_a_new_job_is_judged_at_once(setup, judgings):
    cfg, store, _ = setup
    assert "greenhouse:initech:12" not in [e.job.key for e in watch.build_digest(cfg, store, True, 0).entries]
    store.sync("greenhouse", "initech", [*(j for j, _ in store.jobs(include_closed=True)
                                           if j.company == "initech"), job(12, "Staff Engineer")])
    assert "greenhouse:initech:12" in [e.job.key for e in watch.build_digest(cfg, store, True, 0).entries]
    assert len(judgings) == 2


def test_a_write_from_another_connection_is_seen(setup, judgings):
    cfg, store, _ = setup
    first = watch.hidden(cfg, store)["total"]
    other = Store(cfg.state)  # another process's connection, as a fetch's would be
    other.keep(job(13, "Chef"))
    other.close()
    assert watch.hidden(cfg, store)["total"] == first + 1 and len(judgings) == 2


def test_a_changed_filter_is_judged_again(setup, judgings):
    cfg, store, path = setup
    assert "greenhouse:initech:3" not in [e.job.key for e in watch.build_digest(cfg, store, True, 0).entries]
    raw = yaml.safe_load(path.read_text())
    raw["filters"]["exclude_titles"] = []
    path.write_text(yaml.safe_dump(raw))
    entries = watch.build_digest(config.load(path), store, True, 0).entries
    assert "greenhouse:initech:3" in [e.job.key for e in entries] and len(judgings) == 2
    # a Config changed in memory (no file touched) counts too
    cfg = config.load(path)
    narrower = replace(cfg, filters=replace(cfg.filters, exclude_titles=["engineer"]))
    assert "greenhouse:initech:1" not in [e.job.key for e in watch.build_digest(narrower, store, True, 0).entries]
    assert len(judgings) == 3


def test_a_new_score_is_seen(setup, judgings):
    cfg, store, _ = setup
    from jobwatch.score import resume_id
    assert "greenhouse:initech:1" not in [e.job.key for e in watch.build_digest(cfg, store, True, 0).entries]
    store.save_score("greenhouse:initech:1", resume_id(cfg.resume, cfg.prompts), {**FIT, "score": 90})
    assert "greenhouse:initech:1" in [e.job.key for e in watch.build_digest(cfg, store, True, 0).entries]


def test_the_stamp_changes_with_every_write_and_not_with_reads(setup):
    _, store, _ = setup
    one = store.stamp()
    assert Store(store.path).stamp() == one == store.stamp()  # opening again writes nothing
    store.add_note("greenhouse:initech:1", "hello")
    assert store.stamp() != one


def test_a_result_made_while_a_write_lands_is_made_again(setup):
    cfg, store, _ = setup
    jobpass.forget()
    runs = []

    def make():
        runs.append(1)
        if len(runs) == 1:
            store.add_note("greenhouse:initech:1", "written during the run")
        return len(runs)
    assert jobpass.remembered(store, "x", (), make) == 1
    assert jobpass.remembered(store, "x", (), make) == 2  # the first was made from an older file: not served
    assert jobpass.remembered(store, "x", (), make) == 2
