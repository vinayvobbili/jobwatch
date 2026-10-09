"""Why a job has no fit score yet: in the scorer's line, no posting text, failed, the same role scored
before; and a job added by hand that gets its posting read once a link to it is added."""

import pytest
import yaml

from jobwatch import cli, config, sources, watch
from jobwatch.mcp_server import get_job, mark_job
from jobwatch.store import Store
from jobwatch.web import App

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": ["Go"], "summary": ""}
POSTING = "https://job-boards.greenhouse.io/acme/jobs/101"


@pytest.fixture
def resume_watchlist(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    return watchlist


@pytest.fixture
def scored(monkeypatch):
    fail = set()

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None):
        return ({j.key: FIT for j in jobs if j.key not in fail},
                {j.key: "model said no" for j in jobs if j.key in fail})

    monkeypatch.setattr(watch, "score_jobs", fake)
    return fail


def _fetched(path):
    cfg = config.load(path)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    return cfg, store


def test_jobs_in_line_say_where_they_stand(resume_watchlist, scored):
    cfg, store = _fetched(resume_watchlist)
    why = watch.unscored_reasons(cfg, store)
    assert {k: w["text"] for k, w in why.items()} == {
        "ashby:initech:c1": "In line to score · 1st of 3",
        "lever:globex:aaaa-1111": "In line to score · 2nd of 3",
        "greenhouse:acme:101": "In line to score · 3rd of 3"}
    # what the page's scorer knows: one is being scored, one failed
    why = watch.unscored_reasons(cfg, store, failed={"lever:globex:aaaa-1111": "model said no"},
                                 current="ashby:initech:c1")
    assert why["ashby:initech:c1"]["code"] == "scoring"
    assert why["lever:globex:aaaa-1111"] == {"code": "failed", "text": "Scoring failed: model said no"}
    assert why["greenhouse:acme:101"]["text"] == "In line to score · 1st of 1"
    assert watch.unscored_reasons(cfg, store, stopped="the model isn't running")["greenhouse:acme:101"] == \
        {"code": "stopped", "text": "Background scoring stopped: the model isn't running"}
    watch.score_entries(cfg, store, watch.unscored(cfg, store)[:1], progress=lambda m: None)
    assert "ashby:initech:c1" not in watch.unscored_reasons(cfg, store)
    store.close()


def test_a_job_with_only_a_title_needs_its_posting(resume_watchlist, scored):
    cfg, store = _fetched(resume_watchlist)
    job = store.add("Umbrella", "Staff Python Engineer", status="new", location="Remote")
    assert watch.unscored_reasons(cfg, store)[job.key]["code"] == "no_text"
    assert job.key not in [e.job.key for e in watch.unscored(cfg, store)]  # not in the scorer's line
    assert watch.unscored_reason(cfg, store, job)["code"] == "no_text"
    store.close()


def test_off_or_without_a_resume(watchlist, resume_watchlist):
    raw = yaml.safe_load(resume_watchlist.read_text())
    resume_watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"auto": False}}))
    cfg, store = _fetched(resume_watchlist)
    assert {w["code"] for w in watch.unscored_reasons(cfg, store).values()} == {"manual"}
    store.close()
    del raw["resume"]
    resume_watchlist.write_text(yaml.safe_dump(raw))
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    assert {w["code"] for w in watch.unscored_reasons(cfg, store).values()} == {"no_resume"}
    store.close()


def test_a_posting_of_a_role_scored_before_it_came(resume_watchlist, scored):
    cfg, store = _fetched(resume_watchlist)
    watch.score_entries(cfg, store, watch.unscored(cfg, store), progress=lambda m: None)
    first, _ = store.find("greenhouse:acme:101")
    later = first.__class__(**{**first.__dict__, "id": "102", "url": first.url.replace("101", "102")})
    store.keep(later)
    store.set_status([later.key], "new")
    assert watch.unscored_reasons(cfg, store)[later.key]["code"] == "same_role"
    store.close()


def test_a_queued_job_is_scored_on_request(resume_watchlist, scored):
    cfg, store = _fetched(resume_watchlist)
    store.set_status(["greenhouse:acme:101"], "queued")
    job, _ = store.find("greenhouse:acme:101")
    assert watch.unscored_reason(cfg, store, job)["code"] == "manual"
    store.close()


def test_the_page_shows_why_and_failures_from_its_scorer(resume_watchlist, scored):
    scored.add("lever:globex:aaaa-1111")
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    jobs = {j["key"]: j for j in app.get_digest({})["jobs"]}
    assert jobs["ashby:initech:c1"]["unscored"] is None
    assert jobs["lever:globex:aaaa-1111"]["unscored"]["text"] == "Scoring failed: model said no"


def test_a_link_added_later_reads_the_posting(resume_watchlist, web):
    cfg, store = _fetched(resume_watchlist)
    job = store.add("Acme", "Staff Python Engineer", status="new", location="Remote")
    assert watch.set_link(store, job.key, POSTING, web) == "link saved; posting read from it"
    got, _ = store.find(job.key)
    assert got.key == job.key and got.url == POSTING and "Python" in got.description
    assert watch.unscored_reasons(cfg, store)[job.key]["code"] == "queued"
    # text it has already is kept; a link jobwatch can't read is kept all the same
    assert watch.set_link(store, job.key, "https://acme.example/careers/1", web) == "link saved"
    other = store.add("Umbrella", "Data Engineer", status="new")
    assert "can't read postings on that site" in watch.set_link(store, other.key, "https://umbrella.example/1", web)
    assert store.find(other.key)[0].url == "https://umbrella.example/1"
    store.close()


def test_a_link_that_cant_be_read_is_a_note_not_an_error(resume_watchlist, monkeypatch):
    _, store = _fetched(resume_watchlist)
    job = store.add("Acme", "Staff Python Engineer", status="new")

    def gone(url, get=None):
        raise sources.SourceError("that posting is gone")

    monkeypatch.setattr(sources, "posting", gone)
    assert watch.set_link(store, job.key, POSTING) == \
        "link saved; couldn't read the posting there: that posting is gone"
    assert store.find(job.key)[0].url == POSTING
    store.close()


def test_the_page_adds_a_posting(resume_watchlist, web):
    app = App(resume_watchlist)
    app.post_fetch({})
    key = app.post_add({"company": "Umbrella", "title": "Staff Python Engineer", "status": "queued"})["key"]
    got = app.get_job({"key": [key]})
    assert got["unscored"]["code"] == "no_text" and got["manual"] is True
    r = app.post_posting({"key": key, "text": "Build agents in Python. 5+ years."})
    assert r == {"key": key, "said": "text saved", "has_text": True}
    assert app.get_job({"key": [key]})["unscored"]["code"] == "manual"  # queued: scored on request


def test_cli_and_mcp(resume_watchlist, web, capsys, monkeypatch):
    _, store = _fetched(resume_watchlist)
    job = store.add("Acme", "Staff Python Engineer", status="new", location="Remote")
    store.close()
    cli.main(["--config", str(resume_watchlist), "unscored"])
    out = capsys.readouterr().out
    assert "Acme: Staff Python Engineer\n  No posting text" in out and "4 without a score: 3 queued, 1 no text" in out
    monkeypatch.setenv("JOBWATCH_CONFIG", str(resume_watchlist))
    assert get_job(job.key)["unscored_reason"]["code"] == "no_text"
    assert mark_job(job.key, url=POSTING).endswith("(link saved; posting read from it)")
    assert get_job(job.key)["unscored_reason"]["code"] == "queued"
