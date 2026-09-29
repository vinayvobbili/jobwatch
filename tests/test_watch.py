import json

import pytest

from jobwatch import config, report, sources, watch
from jobwatch.store import Store


@pytest.fixture
def setup(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    yield cfg, store
    store.close()


def test_config_paths_are_relative_to_the_file(watchlist, setup):
    cfg, _ = setup
    assert cfg.state == watchlist.parent / "state.db"
    assert [b.label for b in cfg.boards] == ["acme", "globex", "Initech"]


def test_fetch_all_records_new_roles_once(setup):
    cfg, store = setup
    r = watch.fetch_all(cfg, store)
    assert (r.boards, r.jobs, len(r.new), r.errors) == (3, 5, 5, {})
    assert watch.fetch_all(cfg, store).new == []


def test_fetch_all_reports_a_failing_board_and_keeps_going(setup, web):
    cfg, store = setup
    web.responses["https://api.lever.co/v0/postings/globex?mode=json"] = sources.SourceError("HTTP 503")
    r = watch.fetch_all(cfg, store)
    assert r.boards == 2 and list(r.errors) == ["lever:globex"]


def test_board_name_from_the_watchlist_fills_in_the_company(setup):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    names = {j.key: j.display_company for j, _ in store.jobs()}
    assert names["ashby:initech:c1"] == "Initech"
    assert names["greenhouse:acme:101"] == "Acme"  # the board's own name wins


def test_digest_filters_ranks_and_explains(setup):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    d = watch.build_digest(cfg, store)
    # London sales role: location. Toronto contract role: title (and age).
    assert d.rejected == {"location": 1, "title": 1}
    assert [e.job.key for e in d.entries] == ["ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"]
    top = d.entries[0]
    assert top.keywords == ["Python", "RAG"] and top.relevance == 5


def test_digest_uses_stored_scores_before_relevance(setup, tmp_path):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    cfg.resume = tmp_path / "cv.pdf"
    cfg.resume.write_bytes(b"resume")
    rid = watch.resume_id(cfg.resume)
    store.save_score("greenhouse:acme:101", rid, {"score": 90, "must_haves_met": 5, "must_haves_total": 5,
                                                  "gaps": [], "summary": ""})
    d = watch.build_digest(cfg, store)
    assert d.entries[0].job.key == "greenhouse:acme:101"


def test_scoring_only_the_top_unscored_jobs(setup, tmp_path, monkeypatch):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    cfg.resume = tmp_path / "cv.pdf"
    cfg.resume.write_bytes(b"resume")
    asked = []

    def fake_score(jobs, resume, backend, cache_dir, workers=1, progress=None):
        asked.extend(j.key for j in jobs)
        return {j.key: {"score": 40, "must_haves_met": 1, "must_haves_total": 3, "gaps": ["Go"], "summary": ""}
                for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake_score)
    d = watch.build_digest(cfg, store, score_top=2)
    assert asked == ["ashby:initech:c1", "lever:globex:aaaa-1111"]
    assert d.scored == 2
    asked.clear()
    watch.build_digest(cfg, store, score_top=2)  # stored scores are reused, the next job is scored
    assert asked == ["greenhouse:acme:101"]


def test_scoring_without_a_resume_says_why(setup):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    assert "resume" in watch.build_digest(cfg, store, score_top=3).note


def test_reports_render(setup):
    cfg, store = setup
    watch.fetch_all(cfg, store)
    d = watch.build_digest(cfg, store)
    md = report.to_markdown(d)
    assert "### [Staff AI Engineer](https://jobs.ashbyhq.com/initech/c1)" in md
    assert "$230K–$300K" in md and "Filtered out: 1 by location, 1 by title." in md
    data = json.loads(report.to_json(d))
    assert data["jobs"][0]["key"] == "ashby:initech:c1" and "description" not in data["jobs"][0]


def test_the_same_title_posted_per_region_is_one_entry(setup, web):
    cfg, store = setup
    twin = dict(web.responses["https://api.lever.co/v0/postings/globex?mode=json"][0], id="aaaa-2222",
                hostedUrl="https://jobs.lever.co/globex/aaaa-2222",
                categories={"location": "Remote (Canada)", "allLocations": ["Austin, TX"]})
    web.responses["https://api.lever.co/v0/postings/globex?mode=json"] = [
        *web.responses["https://api.lever.co/v0/postings/globex?mode=json"], twin]
    watch.fetch_all(cfg, store)
    d = watch.build_digest(cfg, store)
    [ml] = [e for e in d.entries if e.job.title == "Machine Learning Engineer"]
    assert ml.keys == ["lever:globex:aaaa-1111", "lever:globex:aaaa-2222"]
    assert "Also posted 1 more time(s): Austin, TX" in report.to_markdown(d)
