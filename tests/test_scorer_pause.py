"""A scoring step out of quota or credit pauses its whole quota pool (claude_api, agy_claude_gpt, agy_gemini, local,
or a provider's own) until the time the error names, else for an hour, on every path that scores; the pause lives in
the state file, so it outlives a restart and ends on the wall clock, and a step that scores clears its pool's."""

import subprocess
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from jobwatch import cli, config, credit, score, watch
from jobwatch.store import Store

from .test_rescore import FIT, app  # noqa: F401  (app: the page's App with agy's Sonnet, then Gemini, then local)

SONNET, GPT, HYDROGEN = "claude-sonnet-5-5-high", "gpt-5-medium", "gemini-4-hydrogen-medium"
QUOTA = "BackendError: agy's quota or rate limit (exit 3): error: Third-party quota reached. Resets in 138h16m."
GEMINI_OUT = "BackendError: agy's quota or rate limit (exit 3): error: Gemini quota reached. Resets in 4h53m6s."
NO_TIME = "agy failed (exit 1): You have hit your usage limit."
ENTRY = "claude:claude-sonnet-5-5 until 2099-12-31"
MILLION = 1_000_000  # a million Sonnet 5.5 tokens in: $2.00 at list price (scorestats.PRICES)


def _cfg(tmp_path, **scoring):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({"companies": ["greenhouse:acme"], "state": "state.db", "scoring": scoring}))
    cfg = config.load(path)
    cfg.resume = tmp_path / "cv.md"
    return cfg


def _agy_chain(tmp_path):
    """agy's Sonnet, then agy's GPT (the same quota), then agy's Gemini (another), then the local model."""
    return _cfg(tmp_path, backend="agy", model=SONNET, fallback=[f"agy:{GPT}", f"agy:{HYDROGEN}", "local"])


def _jobs(n):
    return [SimpleNamespace(key=f"greenhouse:acme:{i}") for i in range(n)]


def _near(stamp, when, slack=60):
    return abs((datetime.fromisoformat(stamp) - when).total_seconds()) < slack


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def chain(monkeypatch):
    """Stands in for shortlist-ai: logs each call as "backend:model"; `out` maps one to the error every job gets, or
    to a function of the jobs giving {key: error} (the rest score); `during` runs inside a call."""
    made = SimpleNamespace(log=[], out={}, during={})

    def fake(jobs, resume, backend, cache_dir, model="", **kw):
        step = f"{backend}:{model}"
        made.log.append(step)
        if step in made.during:
            made.during[step]()
        out = made.out.get(step)
        bad = {} if out is None else out(jobs) if callable(out) else {j.key: out for j in jobs}
        return {j.key: {**FIT, "scored_by": step} for j in jobs if j.key not in bad}, bad
    monkeypatch.setattr(watch, "score_jobs", fake)
    return made


def _pool(cfg, store, name):
    return next(p for p in watch.pools(cfg, store) if p["name"] == name)


# the pools

@pytest.mark.parametrize("step, pool", [
    ("claude:claude-sonnet-5-5", "claude_api"), ("claude:", "claude_api"),
    ("agy:claude-sonnet-5-5-high", "agy_claude_gpt"), ("agy:gpt-5-medium", "agy_claude_gpt"),
    ("agy:", "agy_claude_gpt"),  # agy's default model is Sonnet
    ("agy:gemini-4-hydrogen-medium", "agy_gemini"), ("agy:gemini-4-neon-high", "agy_gemini"),
    ("local:", "local"), ("acme:vendor/m1", "acme"),
])
def test_each_step_draws_on_one_quota_pool(step, pool):
    assert watch.pool_of(step) == pool


def test_two_steps_in_one_pool_one_out_of_quota_skips_the_other_with_no_call(tmp_path, store, chain):
    cfg = _agy_chain(tmp_path)
    chain.out[f"agy:{SONNET}"] = QUOTA
    results, errors = watch.score_with_fallback(cfg, store, _jobs(2))
    assert chain.log == [f"agy:{SONNET}", f"agy:{HYDROGEN}"]  # GPT shares Sonnet's quota: not called
    assert not errors and {r["scored_by"] for r in results.values()} == {f"agy:{HYDROGEN}"}
    flag = _pool(cfg, store, "agy_claude_gpt")
    assert not flag["available"] and flag["reason"] == "out of quota" and not flag["by_hand"]
    assert _near(flag["until"], datetime.now(UTC) + timedelta(hours=138, minutes=16))
    assert [p["available"] for p in watch.pools(cfg, store)] == [True, False, True, True]
    assert set(watch.paused_steps(cfg, store)) == {f"agy:{SONNET}", f"agy:{GPT}"}
    chain.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{HYDROGEN}"]


def test_two_pools_are_independent(tmp_path, store, chain):
    cfg = _agy_chain(tmp_path)
    chain.out[f"agy:{SONNET}"] = QUOTA
    chain.out[f"agy:{HYDROGEN}"] = GEMINI_OUT
    results, _ = watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{SONNET}", f"agy:{HYDROGEN}", "local:"]
    assert {r["scored_by"] for r in results.values()} == {"local:"}
    sonnet, gemini = _pool(cfg, store, "agy_claude_gpt"), _pool(cfg, store, "agy_gemini")
    assert _near(sonnet["until"], datetime.now(UTC) + timedelta(hours=138, minutes=16))
    assert _near(gemini["until"], datetime.now(UTC) + timedelta(hours=4, minutes=53, seconds=6))
    assert _pool(cfg, store, "local")["available"] and _pool(cfg, store, "claude_api")["available"]
    store.clear_scorer_down(watch.pool_id("agy_gemini"))  # Gemini's back: Sonnet's pool stays paused
    chain.out.pop(f"agy:{HYDROGEN}")
    chain.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{HYDROGEN}"] and not _pool(cfg, store, "agy_claude_gpt")["available"]


def test_a_step_that_scores_clears_its_pools_pause_so_a_wrong_one_heals(tmp_path, store, chain):
    """Another run paused the pool while this one's call was out (a stale or wrong pause): the success clears it."""
    cfg = _agy_chain(tmp_path)
    chain.during[f"agy:{SONNET}"] = lambda: store.set_scorer_down(
        watch.pool_id("agy_claude_gpt"), "out of quota", datetime.now(UTC) + timedelta(days=30))
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert _pool(cfg, store, "agy_claude_gpt")["available"] and store.scorers_down() == {}


def test_a_run_that_scores_some_jobs_then_hits_the_limit_pauses_the_pool(tmp_path, store, chain):
    cfg = _agy_chain(tmp_path)
    chain.out[f"agy:{SONNET}"] = lambda jobs: {j.key: QUOTA for j in jobs[2:]}  # two scored, then the limit
    results, errors = watch.score_with_fallback(cfg, store, _jobs(4))
    assert not errors and [results[f"greenhouse:acme:{i}"]["scored_by"] for i in range(4)] == \
        [f"agy:{SONNET}"] * 2 + [f"agy:{HYDROGEN}"] * 2
    assert chain.log == [f"agy:{SONNET}", f"agy:{HYDROGEN}"]
    assert not _pool(cfg, store, "agy_claude_gpt")["available"]


def test_no_reset_time_pauses_an_hour_says_so_then_one_retry_pauses_again(tmp_path, store, chain):
    cfg = _agy_chain(tmp_path)
    chain.out[f"agy:{SONNET}"] = NO_TIME
    watch.score_with_fallback(cfg, store, _jobs(1))
    flag = _pool(cfg, store, "agy_claude_gpt")
    assert flag["reason"] == "out of quota (no reset time given, so tried again in an hour)"
    assert _near(flag["until"], datetime.now(UTC) + timedelta(hours=1))
    # the hour is up (its row ends in the past): the next run tries the step once, and it's paused again
    store.set_scorer_down(watch.pool_id("agy_claude_gpt"), flag["reason"], datetime.now(UTC) - timedelta(seconds=1))
    assert _pool(cfg, store, "agy_claude_gpt")["available"]
    chain.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{SONNET}", f"agy:{HYDROGEN}"] and not _pool(cfg, store, "agy_claude_gpt")["available"]
    store.set_scorer_down(watch.pool_id("agy_claude_gpt"), flag["reason"], datetime.now(UTC) - timedelta(seconds=1))
    chain.out.clear()  # back: it scores, and nothing is paused
    chain.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{SONNET}"] and store.scorers_down() == {}


def test_a_model_the_api_no_longer_serves_pauses_that_step_alone(tmp_path, store, chain):
    cfg = _agy_chain(tmp_path)
    chain.out[f"agy:{SONNET}"] = "BackendError: The agy API refused the model x (404): Not found"
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{SONNET}", f"agy:{GPT}"]  # its pool is fine: GPT scores
    assert set(store.scorers_down()) == {f"agy:{SONNET}"} and _pool(cfg, store, "agy_claude_gpt")["available"]


# what the errors say: agy's words, Claude's 429s

def test_a_429s_retry_after_is_kept_in_the_error_and_sets_the_pause():
    class BackendError(Exception):
        def __init__(self, message, retry_after=None):
            super().__init__(message)
            self.retry_after = retry_after

    class RateLimitError(Exception):  # the anthropic SDK's: the response's headers carry Retry-After
        def __init__(self, message, wait):
            super().__init__(message)
            self.response = SimpleNamespace(headers={"retry-after": wait})

    now = datetime(2026, 1, 5, 9, tzinfo=UTC)
    said = score.error_text(BackendError("The acme API at https://api.example.com/v1 answered 429: slow down", 20))
    assert said == "BackendError: The acme API at https://api.example.com/v1 answered 429: slow down (retry after 20s)"
    assert score.paused_until(said, now) == ("rate limited", now + timedelta(seconds=20))
    said = score.error_text(RateLimitError("Error code: 429 - {'type': 'rate_limit_error'}", "45"))
    assert score.paused_until(said, now) == ("rate limited", now + timedelta(seconds=45))
    assert score.error_text(ValueError("no requirements")) == "ValueError: no requirements"


def _shortlist(monkeypatch, extract_job):
    def module(name, **attrs):
        m = ModuleType(name)
        m.__dict__.update(attrs)
        return m

    for name, m in {
        "shortlist_ai": module("shortlist_ai"),
        "shortlist_ai.backends": module("shortlist_ai.backends",
                                        get_backend=lambda name, model=None: SimpleNamespace(name=name, model="m")),
        "shortlist_ai.extract": module("shortlist_ai.extract", Cache=lambda d: d, extract_job=extract_job),
        "shortlist_ai.pipeline": module("shortlist_ai.pipeline",
                                        match_jobs=lambda *a, **kw: pytest.fail("no match call once it's out")),
    }.items():
        monkeypatch.setitem(sys.modules, name, m)


def _job(key):
    return SimpleNamespace(key=key, display_company="Acme", title="Engineer", to_text=lambda: "Engineer at Acme.")


def test_once_a_run_finds_the_step_out_it_makes_no_more_calls(monkeypatch, tmp_path):
    calls = []

    def extract_job(path, model, cache, **kw):
        calls.append(path.name)
        if len(calls) == 2:
            raise RuntimeError("Error code: 429 - rate_limit_error")
        return SimpleNamespace(requirements=[])
    _shortlist(monkeypatch, extract_job)
    cv = tmp_path / "cv.md"
    cv.write_text("Dana")
    results, errors = score.score_jobs([_job(f"greenhouse:acme:{i}") for i in range(5)], cv, "local", tmp_path)
    assert len(calls) == 2 and results == {}  # the first read, the second refused; nothing more asked
    assert len(errors) == 5 and all(score.paused_until(e)[0].startswith("rate limited") for e in errors.values())


# the credit's caps: claude_api's pool

def test_the_daily_cap_pauses_claude_api_until_midnight_eastern(tmp_path, store):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 5, "total_usd": 85})
    now = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)  # 5 PM in New York
    credit.record(store, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": 3 * MILLION}, now)
    why, until = credit.cap_pause(cfg, store, ENTRY, now)
    assert why == "daily cap $5.00 reached ($6.00 today): back at midnight Eastern"
    assert until == datetime(2026, 11, 27, 5, 0, tzinfo=UTC)  # midnight EST, a wall-clock time, not a duration
    assert credit.cap_pause(cfg, store, ENTRY, datetime(2026, 11, 27, 5, 0, tzinfo=UTC)) is None  # the next day


def test_a_reached_cap_pauses_the_pool_from_the_ledger_on_disk_and_a_raised_cap_frees_it(tmp_path, chain):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 5, "total_usd": 85})
    first = Store(cfg.state)
    credit.record(first, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": 3 * MILLION})  # $6 today
    first.close()
    store = Store(cfg.state)  # a restart: the day's spend is in the state file
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == ["agy:"]  # no call to Claude
    flag = _pool(cfg, store, "claude_api")
    midnight = datetime.combine(credit.today_eastern() + timedelta(days=1), time(), credit.EASTERN)
    assert flag["reason"].startswith("daily cap $5.00 reached ($6.00 today)")
    assert datetime.fromisoformat(flag["until"]) == midnight
    roomier = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 10, "total_usd": 85})
    chain.log.clear()
    watch.score_with_fallback(roomier, store, _jobs(1))
    assert chain.log == ["claude:claude-sonnet-5-5"] and store.scorers_down() == {}
    store.close()


def test_the_total_cap_pauses_claude_api_until_someone_resumes_it(tmp_path, store, chain, capsys):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 5, "total_usd": 85})
    for day in range(1, 23):  # $4 a day for 22 days: $88
        credit.record(store, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": 2 * MILLION},
                      datetime(2026, 10, day, 15, tzinfo=UTC))
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == ["agy:"]
    flag = _pool(cfg, store, "claude_api")
    assert flag["reason"] == ("total cap $85.00 reached ($88.00 spent): until resumed "
                              "(jobwatch scorers --resume claude:claude-sonnet-5-5)")
    assert datetime.fromisoformat(flag["until"]) == score.UNTIL_RESUMED
    assert watch.pause_end(flag["until"]) == "resumed"
    _scorers(cfg, store)
    assert "  claude_api      available: no, back when resumed: total cap $85.00" in capsys.readouterr().out


# `jobwatch credit --test` (what private-data's rescore_queue runs) and `jobwatch scorers`

def _credit_test(tmp_path, store, monkeypatch, **caps):
    cfg = _cfg(tmp_path, backend="agy", credit=caps or {"daily_usd": 5, "total_usd": 85})
    cfg.resume.write_text("Dana: Python, security")
    job = SimpleNamespace(key="greenhouse:acme:1", display_company="Acme", title="Engineer", description="Short.")
    monkeypatch.setattr(cli, "unscored", lambda cfg, store: [SimpleNamespace(job=job, keys=[job.key])])
    return cfg, lambda: cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job=None), cfg, store)


def test_credit_test_at_a_cap_pauses_the_pool_and_calls_nothing(tmp_path, store, chain, monkeypatch):
    cfg, run = _credit_test(tmp_path, store, monkeypatch)
    credit.record(store, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": 3 * MILLION})
    with pytest.raises(SystemExit, match="Not testing: credit daily cap"):
        run()
    assert chain.log == [] and _pool(cfg, store, "claude_api")["reason"].startswith("daily cap")


def test_credit_test_refused_by_the_api_pauses_the_pool_and_the_next_one_makes_no_call(tmp_path, store, chain,
                                                                                       monkeypatch):
    cfg, run = _credit_test(tmp_path, store, monkeypatch)
    chain.out["claude:claude-sonnet-5-5"] = "RateLimitError: Error code: 429 - rate_limit_error (retry after 90s)"
    with pytest.raises(SystemExit, match=r"^Claude couldn't score: RateLimitError"):  # rescore_queue stops on it
        run()
    assert _near(_pool(cfg, store, "claude_api")["until"], datetime.now(UTC) + timedelta(seconds=90), slack=10)
    with pytest.raises(SystemExit, match=r"^Claude couldn't score: claude rate limited \(claude_api\), paused until"):
        run()
    assert chain.log == ["claude:claude-sonnet-5-5"]


def _scorers(cfg, store, **kw):
    cli.cmd_scorers(SimpleNamespace(**{"pause": None, "resume": None, "until": None, "reason": "", "pool": None,
                                       **kw}), cfg, store)


def test_scorers_shows_the_pools_as_flags_and_pauses_or_resumes_a_pool(tmp_path, store, capsys):
    cfg = _agy_chain(tmp_path)
    _scorers(cfg, store, pause="", pool="agy_gemini", until="2099-12-01 22:00", reason="weekly limit")
    assert capsys.readouterr().out == "Paused the agy_gemini pool until 2099-12-01 22:00 (held by hand).\n"
    store.set_scorer_down(watch.pool_id("agy_claude_gpt"), "out of quota", datetime(2099, 12, 1, 21, 50, tzinfo=UTC))
    _scorers(cfg, store)
    out = capsys.readouterr().out.splitlines()
    local = datetime(2099, 12, 1, 21, 50, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    assert out[:5] == ["Quota pools:", "  claude_api      available: yes",
                       f"  agy_claude_gpt  available: no, back at {local}: out of quota (set by a scoring run, since "
                       + out[2].rsplit("since ", 1)[1],
                       out[3], "  local           available: yes"]
    assert out[3].startswith("  agy_gemini      available: no, back at 2099-12-01 22:00: weekly limit (held by hand")
    assert out[6].startswith(f"1. agy:claude-sonnet-5-5-high    paused until {local}: out of quota")
    assert out[6].endswith("[agy_claude_gpt pool]")
    _scorers(cfg, store, resume="", pool="agy_gemini")
    assert capsys.readouterr().out == "Resumed the agy_gemini pool.\n"
    assert _pool(cfg, store, "agy_gemini")["available"]


@pytest.mark.parametrize("kw, message", [
    ({"pause": "", "pool": "gemini", "until": "2099-12-01 22:00"}, "gemini isn't a quota pool"),
    ({"pause": "local", "pool": "local", "until": "2099-12-01 22:00"}, "a STEP or --pool NAME, not both"),
    ({"pause": "", "until": "2099-12-01 22:00"}, "--pause needs a STEP"),
    ({"pool": "local"}, "--pool goes with --pause or --resume"),
])
def test_scorers_refuses_a_bad_pool_ask_and_changes_nothing(tmp_path, store, kw, message):
    with pytest.raises(SystemExit, match=message):
        _scorers(_agy_chain(tmp_path), store, **kw)
    assert store.scorers_down() == {}


# restarts: the state file is the only memory

def test_a_pause_outlives_a_restart_and_ends_on_the_wall_clock(tmp_path):
    path = tmp_path / "state.db"
    until = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=138, minutes=16)
    first = Store(path)
    first.set_scorer_down(watch.pool_id("agy_claude_gpt"), "out of quota", until)
    first.close()
    del first  # nothing held in memory: a fresh Store reads it back
    fresh = Store(path)
    row = fresh.db.execute("SELECT until FROM scorer_down").fetchone()["until"]
    assert row == until.isoformat(timespec="seconds") and row.endswith("+00:00")  # absolute, in UTC
    assert fresh.scorers_down()["pool:agy_claude_gpt"]["until"] == row
    assert fresh.scorers_down(now=until - timedelta(seconds=1))  # still paused just before
    assert fresh.scorers_down(now=until + timedelta(seconds=1)) == {}  # the clock past it: back, nothing to clear
    fresh.close()


def test_a_fresh_process_sees_the_pause(tmp_path):
    cfg = _agy_chain(tmp_path)
    store = Store(cfg.state)
    store.set_scorer_down(watch.pool_id("agy_gemini"), "out of quota", datetime(2099, 12, 1, 22, tzinfo=UTC))
    store.close()
    done = subprocess.run([sys.executable, "-m", "jobwatch", "-c", str(cfg.path), "scorers"], capture_output=True,
                          text=True, cwd=Path(__file__).parents[1], check=True)
    assert "  agy_gemini      available: no, back at " in done.stdout
    assert "  agy_claude_gpt  available: yes" in done.stdout


@pytest.mark.parametrize("until", ["not a time", "", "2099-13-45T99:00:00"])
def test_a_row_whose_time_cant_be_read_is_no_pause_so_the_step_is_tried(tmp_path, store, chain, until):
    cfg = _agy_chain(tmp_path)
    store.db.execute("INSERT INTO scorer_down (scorer, reason, since, until) VALUES (?, ?, ?, ?)",
                     (watch.pool_id("agy_claude_gpt"), "out of quota", "?", until))
    store.db.commit()
    assert store.scorers_down() == {} and _pool(cfg, store, "agy_claude_gpt")["available"]
    watch.score_with_fallback(cfg, store, _jobs(1))
    assert chain.log == [f"agy:{SONNET}"]  # tried, scored: and the bad row is gone with the pool's pause
    assert store.db.execute("SELECT COUNT(*) AS n FROM scorer_down").fetchone()["n"] == 0


def test_a_pause_written_without_a_zone_is_read_as_utc(store):
    later = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None, microsecond=0)
    store.db.execute("INSERT INTO scorer_down (scorer, reason, since, until) VALUES ('pool:local', 'down', '?', ?)",
                     (later.isoformat(),))
    store.db.commit()
    assert store.scorers_down()["pool:local"]["until"] == later.replace(tzinfo=UTC).isoformat()


# every path that scores: the page's Score button, its background scorer, Read posting, the ↻ rescore, `score`

def _sonnet_out(app, monkeypatch):  # noqa: F811
    def fake(jobs, resume, backend, cache_dir, model="", **kw):
        app.calls.append((backend, model))
        if model == "claude-sonnet-5-5-medium":
            return {}, {j.key: QUOTA for j in jobs}
        return {j.key: {**FIT, "scored_by": f"{backend}:{model}"} for j in jobs}, {}
    monkeypatch.setattr(watch, "score_jobs", fake)
    return app._with_store(lambda cfg, store: [e.job.key for e in watch.unscored(cfg, store)])


SONNET_CALL = ("agy", "claude-sonnet-5-5-medium")


def test_the_score_button_pauses_the_pool_and_the_next_press_skips_it(app, monkeypatch):  # noqa: F811
    keys = _sonnet_out(app, monkeypatch)
    assert app.post_score({"key": keys[0]})["scored_by"] == "agy:gemini-3.8-flash-medium"
    assert app.post_score({"key": keys[1]})["scored_by"] == "agy:gemini-3.8-flash-medium"
    assert app.calls.count(SONNET_CALL) == 1
    seen = app.pauses()  # what Settings reads (in /api/ai)
    assert {p["name"]: p["available"] for p in seen["pools"]} == \
        {"claude_api": True, "agy_claude_gpt": False, "agy_gemini": True, "local": True}
    assert seen["paused"]["agy:claude-sonnet-5-5-medium"]["pool"] == "agy_claude_gpt"


def test_the_background_scorer_pauses_the_pool_and_skips_it(app, watchlist, monkeypatch):  # noqa: F811
    _sonnet_out(app, monkeypatch)
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, "scoring": {**raw["scoring"], "auto": True}}))
    assert app.scorer._step() == 1 and app.scorer._step() == 1
    assert app.calls.count(SONNET_CALL) == 1 and not app.pauses()["pools"][1]["available"]


def test_read_posting_and_rescore_skip_a_paused_pool(app, monkeypatch):  # noqa: F811
    keys = _sonnet_out(app, monkeypatch)
    app._score_posted(keys[0])  # Read posting's one-job score: finds the quota out, pauses the pool
    app._score_posted(keys[1])
    assert app.calls.count(SONNET_CALL) == 1
    heard = app.events.subscribe()
    app.post_rescore({"key": keys[2], "backend": "agy", "model": "claude-sonnet-5-5-medium"})
    kind, data = heard.get(timeout=10)
    assert kind == "score" and data["fit"]["scored_by"] == "agy:gemini-3.8-flash-medium"
    assert "out of quota (agy_claude_gpt), paused until" in data["note"]
    assert app.calls.count(SONNET_CALL) == 1  # asked for by name, still no call while paused


def test_jobwatch_score_and_rescore_skip_a_paused_pool(app, watchlist, monkeypatch):  # noqa: F811
    _sonnet_out(app, monkeypatch)
    cli.main(["-c", str(watchlist), "score", "--limit", "1"])
    cli.main(["-c", str(watchlist), "score", "--limit", "1"])
    try:
        cli.main(["-c", str(watchlist), "score", "--rescore"])
    except SystemExit as e:  # no stand-in in the chain for a rescore: it says the step is paused
        assert "paused until" in str(e)
    assert app.calls.count(SONNET_CALL) == 1
