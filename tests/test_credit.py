"""A dated, capped Claude step in the scoring chain (an API credit that ends): the date, the caps, an account that
refuses it, and what the entry looks like in the watchlist."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import yaml

from jobwatch import cli, config, credit, score, watch
from jobwatch.store import Store

ENTRY = "claude:claude-sonnet-5-5 until 2026-12-20"
FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
MILLION = 1_000_000  # a Sonnet 5.5 call of a million tokens in costs $2.00 (scorestats.PRICES)


def _cfg(tmp_path, **scoring):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({"companies": ["greenhouse:acme"], "state": "state.db", "scoring": scoring}))
    cfg = config.load(path)
    cfg.resume = tmp_path / "cv.md"
    return cfg


def _jobs(n):
    return [SimpleNamespace(key=f"greenhouse:acme:{i}") for i in range(n)]


def _at(text):
    return datetime.fromisoformat(text).astimezone(UTC)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def said_nothing():
    credit_said = watch._CREDIT_SAID
    credit_said.clear()
    yield
    credit_said.clear()


@pytest.fixture
def calls(monkeypatch):
    """Stands in for shortlist-ai: records (backend, model, job keys) per call. `spend` is the input tokens each
    Claude call reports; `fail` maps a backend to an exception it raises, or a per-job error text."""
    made = SimpleNamespace(log=[], spend=MILLION, raises={}, errors={})

    def fake(jobs, resume, backend, cache_dir, workers=1, progress=None, prompts=None, model="", keychain="",
             batch=False, key_command="", **kw):
        made.log.append((backend, model, [j.key for j in jobs]))
        if backend in made.raises:
            raise made.raises[backend]
        if backend in made.errors:
            return {}, {j.key: made.errors[backend] for j in jobs}
        if backend == "claude":
            usage = SimpleNamespace(calls=1, input_tokens=made.spend, output_tokens=0, cache_write_tokens=0,
                                    cache_read_tokens=0)
            score._note_usage(SimpleNamespace(usage=usage, model=model), "claude", False, len(jobs))
        return {j.key: {**FIT, "scored_by": f"{backend}:{model}"} for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", fake)
    return made


# the date

@pytest.mark.parametrize("now, skipped", [
    ("2026-12-19T23:59:00-05:00", False),   # the day before
    ("2026-12-20T00:00:00-05:00", True),    # the day itself, from midnight Eastern
    ("2026-12-20T12:00:00-05:00", True),
    ("2026-12-21T09:00:00-05:00", True),    # after
    ("2026-12-20T04:59:00+00:00", False),   # still the 19th in New York: 11:59 PM EST
    ("2026-12-20T05:00:00+00:00", True),    # midnight in New York
])
def test_the_entry_is_used_before_its_day_and_skipped_on_and_after_it(tmp_path, store, now, skipped):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY, "local"])
    why = credit.skip_reason(cfg, store, cfg.score_fallback[0], _at(now))
    assert bool(why) is skipped
    if skipped:
        assert "credit window ended (2026-12-20)" in why


def test_an_ended_window_is_one_log_line_and_the_chain_is_the_free_scorers(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY, "local"])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 12, 20).date())
    for _ in range(2):
        results, errors = watch.score_with_fallback(cfg, store, _jobs(3))
        assert len(results) == 3 and not errors
    assert {b for b, _, _ in calls.log} == {"agy"}
    lines = [a for a in store.activity() if a["kind"] == "score"]
    assert [a["text"] for a in lines] == [
        "Claude credit step: credit window ended (2026-12-20): claude:claude-sonnet-5-5 is skipped"]


def test_a_dated_entry_scores_first_and_what_it_scores_is_no_fallback(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=["agy:gemini-4-hydrogen-medium", ENTRY, "local"])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    results, errors = watch.score_with_fallback(cfg, store, _jobs(2))
    assert [(b, m) for b, m, _ in calls.log] == [("claude", "claude-sonnet-5-5")]
    assert not errors and all("fallback" not in r for r in results.values())
    assert results["greenhouse:acme:0"]["scored_by"] == "claude:claude-sonnet-5-5"
    assert store.credit_spent(datetime(2026, 11, 19).date())[1] == pytest.approx(2.0 * 1)  # one chunk, one call


# the caps

def test_the_daily_cap_stops_it_for_the_day_and_the_chain_scores_the_rest(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 3, "total_usd": 90})
    day = {"now": datetime(2026, 11, 19).date()}
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: day["now"])
    results, _ = watch.score_with_fallback(cfg, store, _jobs(12))  # chunks of 5: $2, then $4 passes the cap
    claude = [keys for b, _, keys in calls.log if b == "claude"]
    assert [len(k) for k in claude] == [5, 5]
    assert len(results) == 12 and store.credit_spent(day["now"]) == (pytest.approx(4.0), pytest.approx(4.0))
    assert [a["text"] for a in store.activity() if "daily cap" in a["text"]] == [
        "Claude credit step: credit daily cap $3.00 reached ($4.00 today): skipped until tomorrow"]
    calls.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(2))
    assert {b for b, _, _ in calls.log} == {"agy"}  # still today: not asked again
    day["now"] = datetime(2026, 11, 20).date()  # tomorrow the daily cap starts over
    calls.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(2))
    assert [b for b, _, _ in calls.log] == ["claude"]


def test_the_total_cap_stops_it_for_good(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 50, "total_usd": 5})
    day = {"now": datetime(2026, 11, 19).date()}
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: day["now"])
    watch.score_with_fallback(cfg, store, _jobs(15))  # $2, $4, $6: stops after the third chunk
    assert [len(k) for b, _, k in calls.log if b == "claude"] == [5, 5, 5]
    day["now"] = datetime(2026, 11, 25).date()
    calls.log.clear()
    watch.score_with_fallback(cfg, store, _jobs(2))
    assert {b for b, _, _ in calls.log} == {"agy"}
    assert any("total cap $5.00 reached ($6.00 spent): skipped for good" in a["text"] for a in store.activity())


def test_a_model_with_no_list_price_is_skipped_because_its_spend_cant_be_capped(tmp_path, store, calls):
    cfg = _cfg(tmp_path, backend="agy", fallback=["claude:claude-mystery until 2026-12-20"])
    results, _ = watch.score_with_fallback(cfg, store, _jobs(1))
    assert {b for b, _, _ in calls.log} == {"agy"} and results
    assert any("no list price for claude-mystery" in a["text"] for a in store.activity())


def test_the_ledger_prices_tokens_at_list_price_with_cache_reads_cheaper(store):
    day = datetime(2026, 11, 19).date()
    usd = credit.record(store, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": 12_000,
                                "output_tokens": 2_000, "cache_write_tokens": 0, "cache_read_tokens": 100_000},
                        _at("2026-11-19T12:00:00-05:00"))
    assert usd == pytest.approx(12_000 * 2 / 1e6 + 2_000 * 10 / 1e6 + 100_000 * 0.10 / 1e6)
    assert store.credit_spent(day) == (pytest.approx(usd), pytest.approx(usd))
    [row] = store.credit_ledger()
    assert (row["day"], row["model"], row["jobs"], row["input_tokens"], row["output_tokens"]) == \
        ("2026-11-19", "claude-sonnet-5-5", 1, 12_000, 2_000)


# an account that refuses it

@pytest.mark.parametrize("raised", [
    score.ScoringUnavailable("Claude's API is out of credit (console Billing: buy credits or turn on auto-reload)"),
    score.ScoringUnavailable("Claude's API refused the key: Error code: 401"),
])
def test_an_account_error_skips_the_entry_and_fails_no_job(tmp_path, store, calls, monkeypatch, raised):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    calls.raises["claude"] = raised
    job = _jobs(2)
    results, errors = watch.score_with_fallback(cfg, store, job)
    assert len(results) == 2 and not errors  # agy scored both: no failure to remember
    assert [b for b, _, _ in calls.log] == ["claude", "agy"]
    calls.log.clear()
    watch.score_with_fallback(cfg, store, job)  # paused: no second call, no retry storm
    assert [b for b, _, _ in calls.log] == ["agy"]
    assert "claude:claude-sonnet-5-5" in store.scorers_down()


@pytest.mark.parametrize("error", [
    "AuthenticationError: Error code: 401 - invalid x-api-key",
    "BadRequestError: Error code: 400 - Your credit balance is too low to access the Anthropic API",
    "PermissionDeniedError: Error code: 403",
    "APIStatusError: Error code: 402 - insufficient credit",
])
def test_an_error_per_job_from_the_account_is_no_job_failure_and_stops_the_run(tmp_path, store, calls, monkeypatch,
                                                                                error):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    calls.errors["claude"] = error
    results, errors = watch.score_with_fallback(cfg, store, _jobs(12))
    assert len(results) == 12 and not errors
    assert [len(k) for b, _, k in calls.log if b == "claude"] == [5]  # the first chunk found out: no more calls
    assert "claude:claude-sonnet-5-5" in store.scorers_down()


def test_a_job_claude_fails_on_for_its_own_reason_goes_on_to_the_next_scorer(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    calls.errors["claude"] = "ValueError: the model gave no verdict"
    results, errors = watch.score_with_fallback(cfg, store, _jobs(1))
    assert len(results) == 1 and not errors


def test_credit_only_tries_nothing_else(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY, "local"])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 12, 25).date())  # window over
    results, errors = watch.score_with_fallback(cfg, store, _jobs(1), credit_only=True)
    assert (results, errors) == ({}, {}) and calls.log == []


# the watchlist

def test_a_dated_entry_is_written_one_way_and_names_the_same_scorer_as_without_the_date():
    assert config.fallback_entry(ENTRY) == ("claude", "claude-sonnet-5-5")
    assert config.entry_until(ENTRY).isoformat() == "2026-12-20"
    assert config.entry_until("claude:claude-sonnet-5-5") is None
    assert config.credit_entry("claude:claude-sonnet-5-5   until   2026-12-20 ") == ENTRY


def test_a_dated_entry_and_the_caps_load(tmp_path):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY, "local"], same_as=["claude:claude-sonnet-5-5"])
    assert cfg.score_fallback == (ENTRY, "local")
    assert (cfg.score_credit_daily, cfg.score_credit_total) == (3.0, 90.0)
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY], credit={"daily_usd": 1.5, "total_usd": 20})
    assert (cfg.score_credit_daily, cfg.score_credit_total) == (1.5, 20.0)


@pytest.mark.parametrize("scoring, match", [
    ({"fallback": ["claude:claude-sonnet-5-5 until 2026-13-40"]}, "the end is a date"),
    ({"fallback": ["claude:claude-sonnet-5-5 until soon"]}, "the end is a date"),
    ({"fallback": ["claude until 2026-12-20"]}, "needs its model"),
    ({"fallback": ["local until 2026-12-20"]}, "only Claude's API takes an 'until' date"),
    ({"fallback": ["agy:claude-sonnet-5-5-high until 2026-12-20"]}, "only Claude's API takes an 'until' date"),
    ({"fallback": [ENTRY, "claude:claude-sonnet-5-5"]}, "scoring.fallback"),   # the same scorer twice
    ({"fallback": [ENTRY], "credit": {"daily_usd": 0}}, "scoring.credit.daily_usd"),
    ({"fallback": [ENTRY], "credit": {"total_usd": "lots"}}, "scoring.credit.total_usd"),
    ({"fallback": [ENTRY], "credit": {"weekly_usd": 5}}, "scoring.credit"),
])
def test_a_bad_dated_entry_or_cap_is_refused(tmp_path, scoring, match):
    with pytest.raises(config.ConfigError, match=match):
        _cfg(tmp_path, backend="agy", **scoring)


def test_the_credit_command_shows_the_window_and_the_ledger(tmp_path, store, capsys, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy", fallback=[ENTRY, "local"])
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    credit.record(store, {"model": "claude-sonnet-5-5", "jobs": 1, "input_tokens": MILLION, "output_tokens": 0})
    cli.cmd_credit(SimpleNamespace(entry=None, test=False, job=None), cfg, store)
    out = capsys.readouterr().out
    assert "claude:claude-sonnet-5-5 until 2026-12-20: scoring" in out
    assert "spent today $2.0000 of $3.00, in all $2.0000 of $90.00" in out
    assert "2026-11-19  claude-sonnet-5-5: 1 job, 1,000,000 in" in out


def test_the_credit_command_without_a_dated_entry_says_the_step_is_off(tmp_path, store, capsys):
    cli.cmd_credit(SimpleNamespace(entry=None, test=False, job=None), _cfg(tmp_path, backend="agy"), store)
    assert "the credit step is off" in capsys.readouterr().out


def test_credit_test_scores_one_job_through_claude_alone_and_records_its_cost(tmp_path, store, calls, monkeypatch,
                                                                              capsys):
    cfg = _cfg(tmp_path, backend="agy", fallback=["local"])  # the entry isn't in the watchlist: --entry names it
    cfg.resume.write_text("Dana: Python, security")
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    short = SimpleNamespace(key="greenhouse:acme:1", display_company="Acme", title="Engineer", description="Short.")
    longer = SimpleNamespace(key="greenhouse:acme:2", display_company="Acme", title="Engineer 2",
                             description="Longer " * 50)
    entries = [SimpleNamespace(job=j, keys=[j.key]) for j in (longer, short)]
    monkeypatch.setattr(cli, "unscored", lambda cfg, store: entries)
    calls.spend = 18_000
    cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job=None), cfg, store)
    # the shortest posting, through Claude alone: no agy, no local
    assert calls.log == [("claude", "claude-sonnet-5-5", ["greenhouse:acme:1"])]
    assert "this call $0.0360" in capsys.readouterr().out
    assert store.credit_spent(datetime(2026, 11, 19).date())[1] == pytest.approx(18_000 * 2 / 1e6)
    assert store.score(short.key, score.resume_id(cfg.resume, cfg.prompts))["scored_by"] == "claude:claude-sonnet-5-5"


def test_credit_test_can_take_a_named_job_and_refuses_one_already_scored(tmp_path, store, calls, monkeypatch, capsys):
    cfg = _cfg(tmp_path, backend="agy")
    cfg.resume.write_text("Dana")
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    job = SimpleNamespace(key="greenhouse:acme:7", display_company="Acme", title="E", description="Short.")
    monkeypatch.setattr(store, "job", lambda key: job if key == job.key else None)
    monkeypatch.setattr(cli, "unscored", lambda cfg, store: pytest.fail("--job names the job"))
    with pytest.raises(SystemExit, match="no such job"):
        cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job="nope"), cfg, store)
    cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job=job.key), cfg, store)
    assert calls.log == [("claude", "claude-sonnet-5-5", [job.key])]
    assert "this call $" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="already has a fit score"):
        cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job=job.key), cfg, store)


def test_credit_test_reports_the_error_of_an_account_that_refuses(tmp_path, store, calls, monkeypatch):
    cfg = _cfg(tmp_path, backend="agy")
    cfg.resume.write_text("Dana")
    monkeypatch.setattr(credit, "today_eastern", lambda now=None: datetime(2026, 11, 19).date())
    job = SimpleNamespace(key="greenhouse:acme:1", display_company="Acme", title="E", description="Short.")
    monkeypatch.setattr(cli, "unscored", lambda cfg, store: [SimpleNamespace(job=job, keys=[job.key])])
    calls.errors["claude"] = "AuthenticationError: Error code: 401 - invalid x-api-key"
    with pytest.raises(SystemExit, match="AuthenticationError"):
        cli.cmd_credit(SimpleNamespace(entry=ENTRY, test=True, job=None), cfg, store)
    assert store.credit_ledger() == []
