"""Fit scores worked out as jobs come in: the page's background scorer, `jobwatch score`, and the model gate
that keeps a chat reply ahead of both."""

import threading
import time

import pytest
import yaml

from jobwatch import cli, config, score, watch
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

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None):
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

    def slow(jobs, resume, backend, cache_dir, workers=1, progress=None):
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
