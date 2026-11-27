"""scoring.batch_api (half price through Claude's Message Batches API) applies whenever Claude scores first in the
chain: scoring.backend: claude, or a dated Claude entry in scoring.fallback (an API credit that ends, which runs
ahead of scoring.backend). It is for the background scorer and bulk runs only: a score asked for in the page (the
Score button, Read posting, a rescore) is one immediate call, and a job that falls to another scorer is scored
normally, not through batches."""

from datetime import UTC, datetime

import pytest
import yaml

from jobwatch import cli, config, score, watch
from jobwatch.store import Store
from jobwatch.web import App

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
DATED = "claude:claude-sonnet-5-5 until 2099-12-31"
SCORING = {"backend": "agy", "auto": True, "batch_api": True, "fallback": [DATED, "local"]}


@pytest.fixture
def resume_watchlist(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    return _scoring(watchlist, SCORING, resume="cv.md")


def _scoring(path, scoring, **top):
    raw = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**raw, **top, "scoring": scoring}))
    return path


@pytest.fixture
def calls(monkeypatch):
    """Stand in for shortlist-ai: every call's (jobs, backend, batch); a backend in `refuse` fails the whole run."""
    class Calls(list):
        def __init__(self):
            super().__init__()
            self.refuse = {}

    seen = Calls()
    refuse = seen.refuse

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False, key_command="", provider=None):
        seen.append(([j.key for j in jobs], backend, batch))
        if backend in refuse:
            raise score.ScoringUnavailable(refuse[backend])
        return {j.key: {**FIT, "scored_by": f"{backend}:{model}"} for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake)
    return seen


# -- the setting is valid whenever Claude can score first

def test_batch_api_is_valid_with_a_dated_claude_entry_even_when_scoring_backend_is_not_claude(watchlist):
    cfg = config.load(_scoring(watchlist, SCORING))
    assert cfg.backend == "agy" and cfg.score_batch_api is True
    # a date long past: the entry is skipped at run time, but the file still loads
    past = {**SCORING, "fallback": ["claude:claude-sonnet-5-5 until 2020-01-01"]}
    assert config.load(_scoring(watchlist, past)).score_batch_api is True


@pytest.mark.parametrize("scoring", [
    {"backend": "local", "batch_api": True},
    {"backend": "agy", "batch_api": True, "fallback": ["claude:claude-sonnet-5-5", "local"]},  # undated: never first
])
def test_batch_api_needs_claude_to_score_first(watchlist, scoring):
    with pytest.raises(config.ConfigError, match="Claude to score first"):
        config.load(_scoring(watchlist, scoring))


def test_claude_scores_first_follows_the_chain_as_it_runs(resume_watchlist):
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    before = datetime(2026, 11, 27, 12, tzinfo=UTC)
    assert watch.claude_scores_first(cfg, store, before) is True
    assert watch.claude_scores_first(cfg, store, datetime(2100, 1, 2, tzinfo=UTC)) is False  # the credit window ended
    watch.hold_step(store, watch.pool_id("claude_api"), datetime(2099, 1, 1, tzinfo=UTC), "out of credit")
    assert watch.claude_scores_first(cfg, store, before) is False  # paused: agy scores first now
    store.clear_scorer_down(watch.pool_id("claude_api"))
    plain = config.load(_scoring(resume_watchlist, {"backend": "agy"}))
    assert watch.claude_scores_first(plain, store, before) is False
    claude = config.load(_scoring(resume_watchlist, {"backend": "claude"}))
    assert watch.claude_scores_first(claude, store, before) is True
    store.close()


# -- background scoring batches; the page's own requests never do

def test_the_background_scorer_batches_through_the_dated_claude_step(resume_watchlist, calls):
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert calls == [(["ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"], "claude", True)]
    assert app.get_scoring({})["done"] == 3


def test_a_job_that_falls_to_another_scorer_is_scored_normally_not_through_batches(resume_watchlist, calls):
    calls.refuse["claude"] = "Your credit balance is too low (insufficient credit)"
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert [(b, batch) for _, b, batch in calls if b != "claude"] == [("agy", False)]
    assert calls[0][1:] == ("claude", True)  # the batch was tried first
    assert app.get_scoring({})["done"] == 3


def test_a_batch_refused_for_credit_pauses_the_claude_pool_like_a_single_call(resume_watchlist, calls):
    calls.refuse["claude"] = "Your credit balance is too low (insufficient credit)"
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    store = Store(config.load(resume_watchlist).state)
    assert watch.pool_id("claude_api") in store.scorers_down()
    store.close()
    calls.clear()
    app.post_fetch({})  # paused: no batch is sent again until the pool is back
    app.scorer.wait(10)
    assert all(b != "claude" for _, b, _ in calls)


def test_a_score_asked_for_in_the_page_is_one_instant_call_even_with_batch_api_on(resume_watchlist, calls):
    app = App(resume_watchlist)
    app.post_fetch({})
    app.post_score({"key": "greenhouse:acme:101"})
    assert calls == [(["greenhouse:acme:101"], "claude", False)]  # the dated step scores first, as one call
    # a rescore and Read posting go through score_entries as well, which batches only when asked to (the
    # background scorer and bulk runs ask)
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    assert cfg.score_batch_api is True
    entry = watch.unscored(cfg, store)[0]
    watch.score_entries(cfg, store, [entry], progress=lambda m: None, by="rescore")
    store.close()
    assert all(batch is False for _, _, batch in calls)


def test_the_cli_batches_by_default_when_claude_scores_first(resume_watchlist, calls, capsys):
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    store.close()
    cli.main(["-c", str(resume_watchlist), "score"])
    assert calls and all(batch for _, b, batch in calls if b == "claude")
    assert "Message Batches API" in capsys.readouterr().err


def test_the_cli_batch_flag_still_needs_claude_first(resume_watchlist, calls):
    _scoring(resume_watchlist, {"backend": "agy"})
    with pytest.raises(SystemExit, match="--batch-api is for Claude"):
        cli.main(["-c", str(resume_watchlist), "score", "--batch-api"])
