"""Settings' Fit scoring panel: which backend is in effect, jobs scored per backend, and the Claude API cost from
the tokens recorded for each run (priced when read), with scores made before that estimated."""

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

from jobwatch import config, score, scorestats, watch
from jobwatch.store import Store
from jobwatch.web import App

TODAY = date(2026, 11, 18)
FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
RUN = dict(backend="claude", model="claude-sonnet-5-5", batch=False, jobs=2, input_tokens=1_000_000,
           output_tokens=100_000, cache_write_tokens=0, cache_read_tokens=0)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def _score(store, key, backend, model, days_ago=0, **more):
    """A stored score made `days_ago` days before TODAY (at noon, local time)."""
    at = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).astimezone().replace(hour=12)
    with store.db:
        store.db.execute("INSERT INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                         (key, "cv.md:1", json.dumps({**FIT, "scored_by": f"{backend}:{model}", **more}),
                          at.astimezone(timezone.utc).isoformat()))


def _cfg(tmp_path, **scoring):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({"companies": ["greenhouse:acme"], "state": "state.db", "scoring": scoring}))
    return config.load(path)


def test_cost_is_tokens_times_the_price_and_half_for_a_batch():
    # 1M in at $2 + 100K out at $10 = $3
    assert scorestats.cost_usd(RUN) == pytest.approx(3.0)
    assert scorestats.cost_usd({**RUN, "batch": True}) == pytest.approx(1.5)
    cached = {**RUN, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 1_000_000,
              "cache_read_tokens": 1_000_000}
    assert scorestats.cost_usd(cached) == pytest.approx(2.5 + 0.2)
    assert scorestats.cost_usd({**RUN, "model": "claude-mystery"}) is None


def test_the_tokens_of_a_run_add_up_by_day_model_and_batch(store):
    store.add_score_cost(**RUN, day=TODAY)
    store.add_score_cost(**RUN, day=TODAY)
    store.add_score_cost(**{**RUN, "batch": True}, day=TODAY)
    store.add_score_cost(**RUN, day=TODAY - timedelta(days=40))
    rows = store.score_costs(TODAY - timedelta(days=1))
    assert [(r["batch"], r["jobs"], r["input_tokens"]) for r in rows] == [(0, 4, 2_000_000), (1, 2, 1_000_000)]
    assert len(store.score_costs()) == 3


def test_an_older_state_file_gets_the_cost_table(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE score_usage (day TEXT NOT NULL, backend TEXT NOT NULL, jobs INTEGER NOT NULL, "
               "PRIMARY KEY (day, backend))")
    db.commit()
    db.close()
    s = Store(path)
    s.add_score_cost(**RUN)
    assert s.score_costs()[0]["jobs"] == 2
    s.close()


def test_jobs_are_counted_per_backend_that_made_the_score_for_today_the_week_and_the_month(store, tmp_path):
    _score(store, "a", "claude", "claude-sonnet-5-5")
    _score(store, "b", "local", "Qwen-4bit")
    _score(store, "c", "local", "Qwen-4bit", days_ago=3)
    _score(store, "d", "local", "Qwen-4bit", days_ago=9)
    _score(store, "e", "claude", "claude-sonnet-5-5", days_ago=20)  # the month before
    _score(store, "f", "agy", "m", fallback="claude was at its limit")
    _score(store, "g", "agy", "m", kept_from="cv.md:0")  # kept from an earlier scorer: not new work
    d = scorestats.summary(_cfg(tmp_path, backend="claude", fallback=["local", "agy"]), store, today=TODAY)
    got = {b["backend"]: (b["today"], b["week"], b["month"]) for b in d["backends"]}
    assert got == {"claude": (1, 1, 1), "local": (1, 2, 3), "agy": (1, 1, 1)}
    assert {b["backend"]: b["role"] for b in d["backends"]} == {
        "claude": "main", "local": "fallback", "agy": "fallback"}
    assert [b["cost"] for b in d["backends"]] == [None, scorestats.COVERED["local"], scorestats.COVERED["agy"]]


def test_the_backend_in_effect(store, tmp_path):
    cfg = _cfg(tmp_path, backend="claude", model="claude-opus-5-5", fallback=["local"], daily=50, batch_api=True)
    store.add_score_usage("claude", 12)
    d = scorestats.summary(cfg, store, scoring={"running": True, "left": 4})
    assert d["backend"]["backend"] == "claude" and d["backend"]["model"] == "claude-opus-5-5"
    assert [f["backend"] for f in d["fallback"]] == ["local"]
    assert (d["daily"], d["used_today"], d["left_today"], d["batch_api"]) == (50, 12, 38, True)
    assert d["scoring"] == {"running": True, "left": 4}
    no_cap = scorestats.summary(_cfg(tmp_path, backend="local"), store)
    assert no_cap["daily"] is None and no_cap["left_today"] is None and no_cap["fallback"] == []


def test_claude_cost_is_recorded_then_estimated_then_not_recorded(store, tmp_path):
    cfg = _cfg(tmp_path, backend="claude")
    for i in range(4):
        _score(store, f"k{i}", "claude", "claude-sonnet-5-5")
    # nothing recorded yet: no average to estimate from
    c = scorestats.summary(cfg, store, today=TODAY)["claude"]
    assert (c["recorded_usd"], c["estimated_usd"], c["not_recorded_jobs"]) == (0, None, 4)
    # two of the four have tokens ($3 for the pair): the other two are priced at the average, $1.50 each
    store.add_score_cost(**RUN, day=TODAY)
    c = scorestats.summary(cfg, store, today=TODAY)["claude"]
    assert (c["recorded_usd"], c["recorded_jobs"], c["estimated_usd"], c["estimated_jobs"], c["total_usd"]) == \
        (3.0, 2, 3.0, 2, 6.0)
    assert c["average_usd"] == 1.5 and c["not_recorded_jobs"] == 0


def test_a_model_without_a_price_is_named_not_guessed(store, tmp_path):
    store.add_score_cost(**{**RUN, "model": "claude-mystery"}, day=TODAY)
    c = scorestats.summary(_cfg(tmp_path, backend="claude"), store, today=TODAY)["claude"]
    assert c["unpriced"] == ["claude-mystery"] and c["recorded_usd"] == 0


def test_score_jobs_hands_a_claude_runs_tokens_to_whoever_collects_them():
    usage = SimpleNamespace(calls=3, input_tokens=10, output_tokens=5, cache_write_tokens=2, cache_read_tokens=1)
    claude = SimpleNamespace(usage=usage, model="claude-sonnet-5-5")
    score._note_usage(claude, "claude", False, 1)  # nobody collecting: nothing happens
    with score.collecting_usage() as used:
        score._note_usage(claude, "claude", True, 2)
        score._note_usage(SimpleNamespace(usage=usage, model="m"), "local", False, 1)  # not billed by the token
        score._note_usage(SimpleNamespace(usage=SimpleNamespace(calls=0), model="m"), "claude", False, 0)
    assert used == [{"backend": "claude", "model": "claude-sonnet-5-5", "batch": True, "jobs": 2, "input_tokens": 10,
                     "output_tokens": 5, "cache_write_tokens": 2, "cache_read_tokens": 1}]


def test_a_runs_tokens_are_handed_over_in_parts_each_only_whats_new():
    usage = SimpleNamespace(calls=0, input_tokens=0, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0)
    kept = []
    with score.collecting_usage(record=kept.append) as used:
        tokens = score._Tokens(SimpleNamespace(usage=usage, model="claude-sonnet-5-5"), "claude", True)
        tokens.note()  # no calls yet: nothing
        usage.calls, usage.input_tokens, usage.output_tokens = 100, 1000, 500  # a batch collected
        tokens.note()
        usage.calls, usage.input_tokens, usage.output_tokens = 150, 1400, 700  # the next one
        tokens.note()
        tokens.note()  # nothing new since
        tokens.note(jobs=50)  # the run's end: the jobs it scored
    assert kept == used
    assert [(u["jobs"], u["input_tokens"], u["output_tokens"]) for u in kept] == [(0, 1000, 500), (0, 400, 200),
                                                                                   (50, 0, 0)]


def test_a_scoring_run_keeps_its_tokens_in_the_store(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, backend="claude")
    cfg.resume = tmp_path / "cv.md"

    def fake(jobs, resume, backend, cache_dir, **kw):
        score._note_usage(SimpleNamespace(usage=SimpleNamespace(calls=1, input_tokens=7, output_tokens=3,
                                                                cache_write_tokens=0, cache_read_tokens=0),
                                          model="claude-sonnet-5-5"), "claude", kw.get("batch", False), len(jobs))
        return {j.key: FIT for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake)
    job = SimpleNamespace(key="greenhouse:acme:1")
    store = Store(cfg.state)
    watch.score_with_fallback(cfg, store, [job])
    [row] = store.score_costs()
    assert (row["backend"], row["model"], row["jobs"], row["input_tokens"], row["output_tokens"]) == \
        ("claude", "claude-sonnet-5-5", 1, 7, 3)
    store.close()


def test_the_page_endpoint_gives_the_panel(watchlist, web):
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {"backend": "claude", "daily": 20, "fallback": ["local"]}}))
    store = Store(config.load(watchlist).state)
    store.add_score_cost(**RUN)
    store.close()
    d = App(watchlist).get_scoring_usage({})
    assert d["backend"]["backend"] == "claude" and d["daily"] == 20 and d["scoring"]["running"] is False
    assert d["claude"]["recorded_usd"] == 3.0 and [b["backend"] for b in d["backends"]] == ["claude", "local", "agy"]
