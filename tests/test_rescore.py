"""Score one job again when asked, with a model picked from a list (the scoring chain first), in the background;
the new score reaches the page as a Server-Sent Event on /events."""

import http.client
import threading

import pytest
import yaml

from jobwatch import ai, scorestats, watch
from jobwatch.web import ApiError, App, serve

from .conftest import TOKEN

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
KEY = "ashby:initech:c1"
AGY = [("claude-sonnet-5-5-medium", "Claude Sonnet 5.5 (Medium)"), ("gemini-3.8-flash-medium", "Gemini 3.8 Flash"),
       ("gemini-4-argon-medium", "Gemini 4 Argon (Medium)")]


@pytest.fixture
def app(watchlist, web, monkeypatch):
    """The page's App with a resume, agy's Sonnet first, then agy's Flash, then the local model; every backend
    ready, and a stand-in shortlist-ai that scores 70 (or fails a job in `fail`) and says who scored it."""
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "resume": "cv.md", "scoring": {
        "backend": "agy", "model": "claude-sonnet-5-5-medium", "auto": False,
        "fallback": ["agy:gemini-3.8-flash-medium", "local"]}}))
    monkeypatch.setattr(ai, "status", lambda *a: {b: {"ready": True} for b in ("claude", "agy", "local")})
    monkeypatch.setattr(ai, "agy_models", lambda: AGY)
    monkeypatch.setattr(scorestats, "default_model", lambda b: {"claude": "claude-sonnet-5-5",
                                                               "local": "mlx-community/Qwen", "agy": AGY[0][0]}[b])
    calls, fail = [], set()

    def fake(jobs, resume, backend, cache_dir, model="", **kw):
        calls.append((backend, model))
        return ({j.key: {**FIT, "scored_by": f"{backend}:{model}"} for j in jobs if j.key not in fail},
                {j.key: "model said no" for j in jobs if j.key in fail})
    monkeypatch.setattr(watch, "score_jobs", fake)
    a = App(watchlist)
    a.post_fetch({})
    a.calls, a.fail = calls, fail
    return a


def test_agys_models_are_read_from_its_list_and_kept_a_while(monkeypatch):
    from types import SimpleNamespace
    asked = []
    out = "Fetching available models...\nalpha-1-medium\tAlpha 1 (Medium)\n--bad\tNope\nbeta-2.5-low\tBeta 2.5 (Low)\n"
    monkeypatch.setattr(ai, "_AGY_MODELS", (0.0, []))
    monkeypatch.setattr(ai, "find_agy", lambda: "/bin/agy")
    monkeypatch.setattr(ai.subprocess, "run", lambda argv, **kw: asked.append(argv) or SimpleNamespace(stdout=out))
    want = [("alpha-1-medium", "Alpha 1 (Medium)"), ("beta-2.5-low", "Beta 2.5 (Low)")]
    assert ai.agy_models() == want and ai.agy_models() == want
    assert asked == [["/bin/agy", "models"]]  # once: kept for AGY_MODELS_FOR


def test_the_choices_are_the_scoring_chain_first_then_the_other_models(app):
    d = app.get_rescore({"key": [KEY]})
    assert [(c["backend"], c["model"], c["role"]) for c in d["choices"]] == [
        ("agy", "claude-sonnet-5-5-medium", "main"), ("agy", "gemini-3.8-flash-medium", "fallback"),
        ("local", "mlx-community/Qwen", "fallback"), ("agy", "gemini-4-argon-medium", ""),
        ("claude", "claude-sonnet-5-5", "")]
    assert d["choices"][1]["name"] == "Gemini 3.8 Flash" and d["choices"][4]["cost"] == "billed per job"
    assert (d["scored_by"], d["running"]) == ("", False)


def test_a_rescore_runs_in_the_background_and_its_score_comes_as_an_event(app):
    heard = app.events.subscribe()
    started = app.post_rescore({"key": KEY, "backend": "agy", "model": "gemini-4-argon-medium"})
    assert started["started"] is True
    kind, data = heard.get(timeout=10)
    assert (kind, data["key"], data["fit"]["score"]) == ("score", KEY, 70)
    assert data["fit"]["scored_by"] == "agy:gemini-4-argon-medium" and KEY in data["keys"]
    assert app.calls == [("agy", "gemini-4-argon-medium")]  # that model only: no fallback
    assert app.get_rescore({"key": [KEY]})["scored_by"] == "agy:gemini-4-argon-medium"
    assert KEY not in app.rescoring


def test_only_a_model_offered_can_be_asked_for(app):
    with pytest.raises(ApiError, match="pick one of the models offered"):
        app.post_rescore({"key": KEY, "backend": "agy", "model": "--dangerously-skip-permissions"})
    assert app.calls == []


def test_a_failed_rescore_says_why_as_an_event(app):
    heard = app.events.subscribe()
    app.fail.add(KEY)
    app.post_rescore({"key": KEY, "backend": "local", "model": "mlx-community/Qwen"})
    kind, data = heard.get(timeout=10)
    assert (kind, data) == ("score-failed", {"key": KEY, "error": "model said no"})


def test_the_event_stream_needs_the_token_and_carries_what_is_published(watchlist, web):
    srv = serve(watchlist, port=0, open_browser=False, token=TOKEN)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/events?t=wrong", headers={"Host": f"127.0.0.1:{port}"})
        assert conn.getresponse().status == 403
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", f"/events?t={TOKEN}", headers={"Host": f"127.0.0.1:{port}"})
        r = conn.getresponse()
        assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
        assert r.fp.readline() == b"retry: 3000\n"
        r.fp.readline()
        srv.app.events.publish("score", {"key": KEY, "fit": FIT})
        assert r.fp.readline() == b"event: score\n"
        assert r.fp.readline().startswith(b'data: {"key": "ashby:initech:c1"')
        conn.close()
    finally:
        srv.app.refresher.stop(10)
        srv.shutdown()
        srv.server_close()
