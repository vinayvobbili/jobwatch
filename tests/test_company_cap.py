"""scoring.per_company: the most jobs from one company the background scorer scores a day."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
import yaml

from jobwatch import config, watch
from jobwatch.store import Store

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
INITECH, GLOBEX = "ashby:initech:c1", "lever:globex:aaaa-1111"


@pytest.fixture
def setup(watchlist, web, monkeypatch):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, *a, **kw: ({j.key: FIT for j in jobs}, {}))
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    yield replace(cfg, score_per_company=1), store
    store.close()


def keys(cfg, store):
    return [e.job.key for e in watch.unscored(cfg, store)]


def test_a_company_at_its_cap_is_left_out_of_the_line_and_the_rest_keep_their_order(setup):
    cfg, store = setup
    assert keys(cfg, store)[:2] == [INITECH, GLOBEX]
    store.add_company_usage("initech", 1)
    assert INITECH not in keys(cfg, store) and GLOBEX in keys(cfg, store)


def test_background_scores_count_toward_the_cap(setup):
    cfg, store = setup
    first = watch.unscored(cfg, store)[0]
    assert first.job.key == INITECH
    watch.score_entries(cfg, store, [first], progress=lambda m: None, background=True)
    assert store.company_usage() == {"initech": 1}


def test_the_reason_says_the_company_hit_its_cap_and_the_line_counts_only_whats_in_it(setup):
    cfg, store = setup
    store.add_company_usage("initech", 1)
    why = watch.unscored_reasons(cfg, store)
    assert why[INITECH]["code"] == "company_cap"
    assert why[INITECH]["text"] == ("Initech hit today's cap of 1 background scores: press Score fit, "
                                    "or it's scored tomorrow")
    assert why[GLOBEX]["code"] == "queued" and why[GLOBEX]["text"].endswith("1st of 2")


def test_manual_scoring_ignores_the_cap_and_isnt_counted(setup):
    cfg, store = setup
    store.add_company_usage("initech", 1)
    capped = next(e for e in watch.scoring_line(cfg, store) if e.job.key == INITECH)
    assert watch.score_entries(cfg, store, [capped], progress=lambda m: None)[0] == 1
    assert store.company_usage() == {"initech": 1}


def test_the_next_day_resets_the_cap(setup):
    cfg, store = setup
    store.add_company_usage("initech", 1, day=date.today() - timedelta(days=1))
    assert INITECH in keys(cfg, store)
    assert watch.unscored_reasons(cfg, store)[INITECH]["code"] == "queued"


def test_zero_means_no_cap(setup):
    cfg, store = setup
    store.add_company_usage("initech", 99)
    assert INITECH not in keys(cfg, store)
    assert INITECH in keys(replace(cfg, score_per_company=0), store)
    assert config.load(cfg.path).score_per_company == 0


def test_the_cap_is_read_from_the_watchlist_and_a_bad_value_is_an_error(watchlist):
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"per_company": 25}}))
    assert config.load(watchlist).score_per_company == 25
    for bad in (-1, "many", 2.5, True):
        watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"per_company": bad}}))
        with pytest.raises(config.ConfigError, match=r"scoring\.per_company"):
            config.load(watchlist)
