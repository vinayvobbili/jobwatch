"""Fit scores worked out as jobs come in: the page's background scorer, `jobwatch score`, and the model gate
that keeps a chat reply ahead of both."""

import sys
import threading
import time
from datetime import timedelta

import pytest
import yaml

from jobwatch import cli, config, score, watch, web
from jobwatch.store import Store
from jobwatch.web import App

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": ["Go"], "summary": ""}


@pytest.fixture
def resume_watchlist(watchlist, web):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md"}))
    return watchlist


@pytest.fixture
def scored(monkeypatch):
    """Stand in for shortlist-ai: records which jobs were scored; keys in `fail` come back as errors."""
    asked, fail = [], set()

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False):
        asked.extend(j.key for j in jobs)
        return ({j.key: FIT for j in jobs if j.key not in fail},
                {j.key: "model said no" for j in jobs if j.key in fail})

    monkeypatch.setattr(watch, "score_jobs", fake)
    return asked, fail


def test_unscored_is_most_relevant_first_and_skips_scored_jobs(resume_watchlist, scored):
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    todo = watch.unscored(cfg, store)
    assert [e.job.key for e in todo] == ["ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"]
    assert watch.score_entries(cfg, store, todo[:1], progress=lambda m: None) == (1, {})
    assert [e.job.key for e in watch.unscored(cfg, store)] == ["lever:globex:aaaa-1111", "greenhouse:acme:101"]
    assert [e.job.key for e in watch.unscored(cfg, store, skip={"lever:globex:aaaa-1111"})] == \
        ["greenhouse:acme:101"]
    store.close()


def test_unscored_needs_a_resume(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    assert watch.unscored(cfg, store) == []
    store.close()


def test_auto_scoring_defaults_to_on_only_for_the_local_model(watchlist):
    raw = yaml.safe_load(watchlist.read_text())
    assert config.load(watchlist).auto_score is True  # backend defaults to local
    for scoring, want in (({"backend": "claude"}, False), ({"backend": "claude", "auto": True}, True),
                          ({"backend": "local", "auto": False}, False)):
        watchlist.write_text(yaml.safe_dump({**raw, "scoring": scoring}))
        assert config.load(watchlist).auto_score is want
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"auto": "yes"}}))
    with pytest.raises(config.ConfigError, match=r"scoring\.auto"):
        config.load(watchlist)


def test_the_page_scores_new_jobs_in_the_background_after_a_fetch(resume_watchlist, scored):
    asked, fail = scored
    fail.add("lever:globex:aaaa-1111")
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert asked == ["ashby:initech:c1", "lever:globex:aaaa-1111", "greenhouse:acme:101"]
    status = app.get_scoring({})
    assert (status["running"], status["done"], status["left"]) == (False, 2, 0)
    assert "model said no" in status["error"]
    jobs = {j["key"]: j for j in app.get_digest({})["jobs"]}
    assert jobs["ashby:initech:c1"]["fit"]["score"] == 70
    assert jobs["lever:globex:aaaa-1111"]["fit"] is None
    asked.clear()
    app.post_fetch({})  # nothing new: a failed job isn't retried until the page restarts
    app.scorer.wait(10)
    assert asked == []


def test_without_background_the_app_only_scores_on_request(resume_watchlist, scored):
    asked, _ = scored
    app = App(resume_watchlist)
    app.post_fetch({})
    assert app.scorer.status()["running"] is False and asked == []
    assert app.get_scoring({})["enabled"] is False


def test_auto_off_leaves_scoring_to_the_button(resume_watchlist, scored):
    asked, _ = scored
    raw = yaml.safe_load(resume_watchlist.read_text())
    resume_watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"auto": False}}))
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert asked == []


def test_a_kick_while_scoring_runs_again(resume_watchlist, monkeypatch):
    """Jobs fetched while the scorer is busy are picked up in the same run, not left for the next fetch."""
    app = App(resume_watchlist, background=True)
    gate, calls = threading.Event(), []

    def slow(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False):
        calls.append(jobs[0].key)
        gate.wait(5)
        return {j.key: FIT for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", slow)
    app.post_fetch({})
    app.scorer.kick()
    gate.set()
    app.scorer.wait(10)
    assert len(calls) == 3 and app.scorer.status()["running"] is False


def test_background_scoring_waits_for_a_chat_reply():
    gate, order = score.ModelGate(), []
    in_chat, chat_done = threading.Event(), threading.Event()

    def chat():
        with gate.foreground():
            in_chat.set()
            time.sleep(0.05)
            order.append("chat")
        chat_done.set()

    def background():
        in_chat.wait(5)
        with gate.background():
            order.append("score")

    threads = [threading.Thread(target=chat), threading.Thread(target=background)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert order == ["chat", "score"]


def test_a_waiting_chat_goes_before_the_next_background_job():
    gate, order = score.ModelGate(), []
    scoring, chat_waiting = threading.Event(), threading.Event()

    def first_job():
        with gate.background():
            scoring.set()
            chat_waiting.wait(5)
            time.sleep(0.05)  # let the chat thread block on the gate
            order.append("job 1")

    def chat():
        scoring.wait(5)
        chat_waiting.set()
        with gate.foreground():
            order.append("chat")

    def second_job():
        scoring.wait(5)
        time.sleep(0.02)
        with gate.background():
            order.append("job 2")

    threads = [threading.Thread(target=f) for f in (first_job, chat, second_job)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert order == ["job 1", "chat", "job 2"]


def test_score_command(resume_watchlist, scored, capsys):
    asked, _ = scored
    cli.main(["-c", str(resume_watchlist), "fetch"])
    cli.main(["-c", str(resume_watchlist), "score", "--limit", "2"])
    assert asked == ["ashby:initech:c1", "lever:globex:aaaa-1111"]
    assert "Scored 2 of 2 jobs." in capsys.readouterr().out
    cli.main(["-c", str(resume_watchlist), "score"])
    assert asked[-1] == "greenhouse:acme:101"
    cli.main(["-c", str(resume_watchlist), "score"])
    assert "Every job on Today has a fit score." in capsys.readouterr().out


@pytest.fixture
def local_model(monkeypatch):
    """A stand-in for the loaded on-device model: counts loads, and unloads through score.unload_local_models."""
    loads = []

    class Backends:  # what shortlist_ai.backends has once it's loaded a model
        class _load_local_generator:
            @staticmethod
            def cache_clear():
                loads.append("unload")

    monkeypatch.setitem(sys.modules, "shortlist_ai.backends", Backends)
    monkeypatch.setattr(score, "LOCAL", score.ModelGate())
    monkeypatch.setattr("jobwatch.web.LOCAL", score.LOCAL)
    return loads


def test_nothing_to_score_loads_no_model_and_leaves_no_thread_or_timer(watchlist, web, local_model, monkeypatch):
    """A page with no resume (or every job scored) starts without touching the model and goes quiet."""
    called = []
    monkeypatch.setattr(watch, "score_jobs", lambda *a, **k: called.append(a) or ({}, {}))
    app = App(watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert called == [] and local_model == []
    assert app.scorer._thread is None and app.scorer._rest is None and score.LOCAL._timer is None
    assert not [t for t in threading.enumerate() if t.name == "jobwatch-scorer"]


def test_the_model_is_let_go_after_the_idle_time_and_not_before(monkeypatch):
    gate, unloads = score.ModelGate(idle_after=0.15), []
    monkeypatch.setattr(score, "unload_local_models", lambda: unloads.append(1))
    with gate.background():
        pass
    time.sleep(0.05)
    assert unloads == []
    with gate.foreground():  # used again: the clock starts over
        time.sleep(0.2)
    assert unloads == []  # busy for longer than the idle time, and not idle meanwhile
    time.sleep(0.4)
    assert unloads == [1]
    time.sleep(0.4)
    assert unloads == [1]  # unloaded once, and no timer left to unload again
    assert gate._timer is None or not gate._timer.is_alive()


def test_a_gate_with_no_idle_time_keeps_the_model_and_never_starts_a_timer():
    gate = score.ModelGate()
    with gate.background():
        pass
    assert gate._timer is None


def test_unloading_forgets_every_loaded_model(local_model):
    cleared = []
    score.UNLOADERS.append(lambda: cleared.append("chat"))
    try:
        score.unload_local_models()
    finally:
        score.UNLOADERS.pop()
    assert local_model == ["unload"] and cleared == ["chat"]


def test_scored_jobs_are_not_scored_again_by_later_runs(resume_watchlist, scored):
    asked, _ = scored
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert len(asked) == 3
    for _ in range(3):
        app.scorer.kick()
        app.scorer.wait(10)
    assert len(asked) == 3


def test_a_long_line_is_scored_in_batches_with_a_rest_between(resume_watchlist, scored):
    asked, _ = scored
    raw = yaml.safe_load(resume_watchlist.read_text())
    resume_watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"batch": 2, "rest": 1}}))
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert len(asked) == 2
    assert app.scorer._rest is not None and app.scorer._rest.interval == 60  # waiting, not polling
    assert app.get_scoring({})["left"] == 1 and app.scorer.status()["running"] is False
    app.scorer._rest.cancel()
    app.scorer.kick()  # the rest is over (or something new came in)
    app.scorer.wait(10)
    assert len(asked) == 3 and app.scorer._rest is None


def test_the_scorer_does_not_spin_while_it_has_nothing_to_do(resume_watchlist, scored, monkeypatch):
    """Each kick looks once; between kicks the scorer's thread is gone, so there is nothing to poll."""
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    looks, original = [], web.unscored
    monkeypatch.setattr(web, "unscored", lambda *a, **k: looks.append(1) or original(*a, **k))
    time.sleep(0.5)
    assert looks == [] and app.scorer._thread is None
    app.scorer.kick()
    app.scorer.wait(10)
    assert looks == [1]


def test_new_settings_are_read_and_checked(watchlist):
    cfg = config.load(watchlist)
    assert (cfg.score_batch, cfg.score_rest, cfg.unload_after) == (10, 10, 5)
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"batch": 3, "rest": 0, "unload_after": 0}}))
    cfg = config.load(watchlist)
    assert (cfg.score_batch, cfg.score_rest, cfg.unload_after) == (3, 0, 0)
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"unload_after": "soon"}}))
    with pytest.raises(config.ConfigError, match=r"scoring\.unload_after"):
        config.load(watchlist)


def test_a_failed_job_is_not_tried_again_after_a_restart_until_something_changes(resume_watchlist, scored):
    asked, fail = scored
    fail.add("lever:globex:aaaa-1111")
    app = App(resume_watchlist, background=True)
    app.post_fetch({})
    app.scorer.wait(10)
    assert asked.count("lever:globex:aaaa-1111") == 1
    asked.clear()
    restarted = App(resume_watchlist, background=True)  # a new process: nothing in memory
    restarted.scorer.kick()
    restarted.scorer.wait(10)
    assert asked == []
    why = restarted.scorer.reasons(config.load(resume_watchlist), Store(config.load(resume_watchlist).state))
    assert why["lever:globex:aaaa-1111"] == {"code": "failed", "text": "Scoring failed: model said no"}
    (resume_watchlist.parent / "cv.md").write_text("Python, LLMs, RAG, Go")  # a new resume: tried again
    restarted = App(resume_watchlist, background=True)
    restarted.scorer.kick()
    restarted.scorer.wait(10)
    assert "lever:globex:aaaa-1111" in asked


def test_a_failed_job_is_tried_again_for_another_model_or_after_the_retry_time(resume_watchlist, scored, monkeypatch):
    _, fail = scored
    fail.add("lever:globex:aaaa-1111")
    cfg = config.load(resume_watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    watch.score_entries(cfg, store, watch.unscored(cfg, store), progress=lambda m: None)
    assert "lever:globex:aaaa-1111" in watch.failed_scores(cfg, store)
    assert "lever:globex:aaaa-1111" not in [e.job.key for e in watch.unscored(cfg, store)]
    raw = yaml.safe_load(resume_watchlist.read_text())
    resume_watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"model": "another-model"}}))
    assert "lever:globex:aaaa-1111" in [e.job.key for e in watch.unscored(config.load(resume_watchlist), store)]
    monkeypatch.setattr(watch, "SCORE_RETRY", timedelta(seconds=-1))  # the time is up
    assert watch.failed_scores(cfg, store) == {}
    store.save_score("lever:globex:aaaa-1111", score.resume_id(cfg.resume, cfg.prompts), FIT)
    monkeypatch.undo()
    assert watch.failed_scores(cfg, store) == {}  # a score replaces the record of the failure
    store.close()
