"""Which model made a fit score (scored_by), scoring with another backend or model for one run, comparing two
models' scores before trusting them side by side, and the Anthropic API key from the macOS keychain."""

import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from jobwatch import chat, cli, config, report, score, watch
from jobwatch.score import ScoringUnavailable, load_api_key, resume_id, score_jobs, scorer_label
from jobwatch.store import Store


def _module(name, **attrs):
    m = ModuleType(name)
    m.__dict__.update(attrs)
    return m


@pytest.fixture
def shortlist(monkeypatch):
    """A stand-in shortlist-ai whose backends have a name and a model, as the real ones do."""
    defaults = {"claude": "claude-opus-5", "local": "mlx-community/Qwen"}

    def get_backend(name, model=None):
        return SimpleNamespace(name=name, model=model or defaults[name])

    def match_jobs(resume, specs, model, **kw):
        result = SimpleNamespace(score=70, must_haves_met=2, must_haves_total=3, summary="", flags=[], requirements=[])
        return SimpleNamespace(errors={}, matches=[SimpleNamespace(job_id=k, result=result, gaps=[]) for k in specs])

    for name, module in {
        "shortlist_ai": _module("shortlist_ai"),
        "shortlist_ai.backends": _module("shortlist_ai.backends", get_backend=get_backend),
        "shortlist_ai.extract": _module("shortlist_ai.extract", Cache=lambda d: d,
                                        extract_job=lambda path, model, cache, **kw: SimpleNamespace(requirements=[])),
        "shortlist_ai.pipeline": _module("shortlist_ai.pipeline", match_jobs=match_jobs),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def _job(key="greenhouse:acme:1"):
    return SimpleNamespace(key=key, display_company="Acme", title="Engineer", to_text=lambda: "Engineer at Acme.")


def test_a_score_says_which_backend_and_model_made_it(shortlist, tmp_path):
    cv = tmp_path / "cv.md"
    cv.write_text("Dana")
    results, _ = score_jobs([_job()], cv, "local", tmp_path)
    assert results["greenhouse:acme:1"]["scored_by"] == "local:mlx-community/Qwen"
    results, _ = score_jobs([_job()], cv, "local", tmp_path, model="mlx-community/Other-4bit")
    assert results["greenhouse:acme:1"]["scored_by"] == "local:mlx-community/Other-4bit"


@pytest.mark.parametrize("by, label", [
    ("claude:claude-sonnet-5-5", "claude-sonnet-5-5"),
    ("local:mlx-community/Qwen3.5-9B-MLX-4bit", "Qwen3.5-9B-MLX-4bit (local)"),
    ("claude:", "claude"),
])
def test_scorer_label(by, label):
    assert scorer_label(by) == label


def test_fit_lines_name_the_scorer_when_known():
    fit = {"score": 72, "must_haves_met": 2, "must_haves_total": 3}
    assert report.fit_lines(fit) == ["Fit 72/100, must-haves 2/3"]  # scored before scores were labelled
    assert report.fit_lines({**fit, "scored_by": "claude:claude-sonnet-5-5"}) == [
        "Fit 72/100, must-haves 2/3 (scored by claude-sonnet-5-5)"]


# The API key from the keychain

def test_a_key_in_the_environment_is_used_as_is(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("the keychain isn't needed"))
    assert load_api_key("anthropic") is None


def test_no_keychain_item_named_means_nothing_to_do(no_key, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no item named"))
    assert load_api_key("") is None


def test_the_key_comes_from_the_named_keychain_item(no_key, monkeypatch):
    asked = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: asked.append(argv) or
                        SimpleNamespace(returncode=0, stdout="sk-ant-test\n"))
    assert load_api_key("anthropic") is None
    assert asked == [["security", "find-generic-password", "-s", "anthropic", "-w"]]
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_a_missing_keychain_item_says_how_to_add_one_without_the_key(no_key, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=44, stdout=""))
    problem = load_api_key("anthropic")
    assert "security add-generic-password -s anthropic" in problem


def test_scoring_with_claude_stops_before_any_call_without_a_key(shortlist, no_key, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=44, stdout=""))
    cv = tmp_path / "cv.md"
    cv.write_text("Dana")
    with pytest.raises(ScoringUnavailable, match="no API key in the keychain item 'anthropic'"):
        score_jobs([_job()], cv, "claude", tmp_path, keychain="anthropic")


def test_chat_with_claude_reads_the_keychain_item_too(no_key, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _module("anthropic"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="sk-ant-test"))
    chat.check("claude", "anthropic")  # no ChatUnavailable
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=44, stdout=""))
    with pytest.raises(chat.ChatUnavailable, match="keychain item 'anthropic'"):
        chat.check("claude", "anthropic")


def _set(watchlist, **sections):
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, **sections}))
    return config.load(watchlist)


def test_scoring_keychain_is_read_and_chat_shares_it_unless_it_names_its_own(watchlist):
    cfg = _set(watchlist, scoring={"backend": "local", "keychain": "anthropic"})
    assert cfg.api_keychain == "anthropic" and cfg.chat.keychain == "anthropic"
    cfg = _set(watchlist, scoring={"backend": "local", "keychain": "anthropic"}, chat={"keychain": "chat-key"})
    assert cfg.api_keychain == "anthropic" and cfg.chat.keychain == "chat-key"
    assert config.load(watchlist.parent / "jobwatch.yaml").score_model == ""
    assert "keychain" not in config.defaults()["chat"]


# One run with another backend or model, and comparing the two

@pytest.fixture
def scored(watchlist, web):
    """Every fetched job scored 10, 20, 30... by the local model."""
    cli.main(["-c", str(watchlist), "fetch"])
    (watchlist.parent / "cv.md").write_text("Dana")
    cfg = _set(watchlist, resume="cv.md", filters={**yaml.safe_load(watchlist.read_text())["filters"], "min_fit": 50})
    store = Store(cfg.state)
    rid = resume_id(cfg.resume, cfg.prompts)
    jobs = [job for job, _ in store.jobs() if watch.scorable(job) and job.description.strip()]
    for i, job in enumerate(jobs, 1):
        store.save_score(job.key, rid, {"score": 10 * i, "must_haves_met": 1, "must_haves_total": 2,
                                        "scored_by": "local:mlx-community/Qwen"})
    store.close()
    return cfg, rid, jobs


def test_compare_picks_spread_from_the_lowest_score_to_the_highest(scored):
    cfg, _, jobs = scored
    store = Store(cfg.state)
    picks = watch.compare_picks(cfg, store, 2)
    assert [f["score"] for _, f in picks] == [10, 10 * len(jobs)]
    assert len(watch.compare_picks(cfg, store, 99)) == len(jobs)
    assert watch.compare_picks(cfg, store, 0) == []
    store.close()


def test_score_compare_shows_both_scores_and_saves_nothing(scored, monkeypatch, capsys):
    cfg, rid, jobs = scored
    calls = []

    def fake(jobs, resume, backend, cache, **kw):
        calls.append((backend, kw.get("model"), kw.get("keychain")))
        return {j.key: {"score": 60.0, "must_haves_met": 2, "must_haves_total": 2,
                        "scored_by": f"{backend}:{kw.get('model')}"} for j in jobs}, {}
    monkeypatch.setattr(watch, "score_jobs", fake)
    cli.main(["-c", str(cfg.path), "score", "--compare", "2", "--backend", "claude", "--model", "claude-sonnet-5-5"])
    out = capsys.readouterr()
    assert calls == [("claude", "claude-sonnet-5-5", "")]
    assert "paid API calls" in out.err and "nothing is saved" in out.err
    assert "    10   60   +50" in out.out and "other side of min_fit 50" in out.out
    assert "Stored scores by: Qwen (local); new by: claude-sonnet-5-5" in out.out
    store = Store(cfg.state)
    assert {k: f["score"] for k, f in store.scores(rid).items()} == {j.key: 10 * i for i, j in enumerate(jobs, 1)}
    store.close()


def test_score_backend_scores_with_it_this_run_only(scored, monkeypatch, capsys):
    cfg, rid, _ = scored
    store = Store(cfg.state)
    store.db.execute("DELETE FROM scores")
    store.db.commit()
    store.close()
    calls = []
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, resume, backend, cache, **kw: (
        calls.append((backend, kw["model"])) or ({j.key: {"score": 55.0, "must_haves_met": 1, "must_haves_total": 1,
                                                         "scored_by": f"{backend}:x"} for j in jobs}, {})))
    cli.main(["-c", str(cfg.path), "score", "--limit", "1", "--backend", "claude"])
    assert calls == [("claude", "")]  # another backend: its own default model, not scoring.model's
    assert config.load(cfg.path).backend == "local"
    store = Store(cfg.state)
    assert [f["scored_by"] for f in store.scores(rid).values()][:1] == ["claude:x"]
    store.close()


def test_compare_with_nothing_scored_says_so(watchlist, web, capsys):
    (watchlist.parent / "cv.md").write_text("Dana")
    cfg = _set(watchlist, resume="cv.md")
    cli.main(["-c", str(cfg.path), "score", "--compare", "5"])
    assert "No job has a fit score" in capsys.readouterr().out


def test_the_scorer_module_reads_no_keychain_on_import():
    assert score.load_api_key("") is None


# The backend first, the fallback when it can't (or is at scoring.daily), and --rescore

def _backends(monkeypatch, claude_down=False):
    """Claude scores 60, the local model 30; with claude_down, Claude has no key."""
    calls = []

    def fake(jobs, resume, backend, cache, **kw):
        calls.append((backend, [j.key for j in jobs]))
        if backend == "claude" and claude_down:
            raise ScoringUnavailable("no API key")
        n = 60.0 if backend == "claude" else 30.0
        return {j.key: {"score": n, "must_haves_met": 1, "must_haves_total": 1, "scored_by": f"{backend}:m"}
                for j in jobs}, {}
    monkeypatch.setattr(watch, "score_jobs", fake)
    return calls


def _claude_first(cfg, **kw):
    from dataclasses import replace
    return replace(cfg, backend="claude", score_fallback="local", **kw)


def test_fallback_and_daily_are_read_and_checked(watchlist):
    cfg = _set(watchlist, scoring={"backend": "claude", "fallback": "local", "daily": 40})
    assert (cfg.score_fallback, cfg.score_daily) == ("local", 40)
    for bad in ("claude", "gpt"):
        with pytest.raises(config.ConfigError, match=r"scoring\.fallback is the other backend"):
            _set(watchlist, scoring={"backend": "claude", "fallback": bad})
    with pytest.raises(config.ConfigError, match=r"scoring\.daily"):
        _set(watchlist, scoring={"backend": "claude", "daily": -1})


def test_no_key_falls_back_marks_the_score_and_waits_before_trying_claude_again(scored, monkeypatch):
    cfg, rid, _ = scored
    cfg = _claude_first(cfg)
    calls = _backends(monkeypatch, claude_down=True)
    store = Store(cfg.state)
    store.db.execute("DELETE FROM scores")
    store.db.commit()
    e = watch.unscored(cfg, store)[0]
    assert watch.score_entries(cfg, store, [e], progress=lambda m: None)[0] == 1
    assert [b for b, _ in calls] == ["claude", "local"]
    fit = store.score(e.job.key, rid)
    assert fit["score"] == 30 and fit["fallback"] == "no API key" and fit["scored_by"] == "local:m"
    assert store.score_usage("claude") == 0
    assert e.job.key not in {x.job.key for x in watch.unscored(cfg, store)}  # Claude failed: not again at once
    store.close()


def test_past_the_daily_limit_the_fallback_scores_and_claude_takes_it_up_later(scored, monkeypatch):
    cfg, rid, _ = scored
    cfg = _claude_first(cfg, score_daily=1)
    _backends(monkeypatch)
    store = Store(cfg.state)
    store.db.execute("DELETE FROM scores")
    store.db.commit()
    first, second = watch.unscored(cfg, store)[:2]
    watch.score_entries(cfg, store, [first, second], progress=lambda m: None)
    assert store.score(first.job.key, rid)["scored_by"] == "claude:m"
    late = store.score(second.job.key, rid)
    assert late["scored_by"] == "local:m" and late["fallback"].startswith(watch.DAILY_LIMIT)
    assert store.score_usage("claude") == 1 and watch.at_daily_limit(cfg, store)
    assert second.job.key not in {x.job.key for x in watch.unscored(cfg, store)}  # at the limit: it waits
    roomier = _claude_first(cfg, score_daily=5)  # tomorrow, as far as the limit goes
    assert second.job.key in {x.job.key for x in watch.unscored(roomier, store)}  # no failure kept for it
    store.close()


def test_at_the_limit_with_no_fallback_nothing_is_in_line(scored, monkeypatch):
    cfg, _, _ = scored
    from dataclasses import replace
    cfg = replace(cfg, backend="claude", score_daily=2)
    store = Store(cfg.state)
    store.db.execute("DELETE FROM scores")
    store.db.commit()
    assert watch.unscored(cfg, store)
    store.add_score_usage("claude", 2)
    assert watch.unscored(cfg, store) == []
    store.close()


@pytest.mark.parametrize("fit, elsewhere", [
    (None, False),
    ({"score": 50}, True),                                       # before scores said who made them
    ({"score": 50, "scored_by": "local:m"}, True),
    ({"score": 50, "scored_by": "claude:claude-sonnet-5-5"}, False),
    ({"score": 50, "scored_by": "claude:claude-opus-5"}, True),  # scoring.model names another
    ({"score": 50, "scored_by": "claude:claude-sonnet-5-5", "fallback": "x"}, True),
])
def test_made_elsewhere(watchlist, fit, elsewhere):
    cfg = _set(watchlist, scoring={"backend": "claude", "model": "claude-sonnet-5-5"})
    assert watch.made_elsewhere(cfg, fit) is elsewhere


def test_rescore_scores_other_models_jobs_again_best_first_past_the_daily_limit(scored, monkeypatch, capsys):
    cfg, rid, jobs = scored
    calls = _backends(monkeypatch)
    _set(cfg.path, scoring={"backend": "claude", "fallback": "local", "daily": 1})
    store = Store(cfg.state)
    for i, job in enumerate(jobs):  # 45 (under min_fit: not on Today), 55, 65...
        store.save_score(job.key, rid, {"score": 45 + 10 * i, "must_haves_met": 1, "must_haves_total": 2})
    line = watch.rescore_line(config.load(cfg.path), store, 50)
    store.close()
    assert jobs[0].key not in {e.job.key for e in line}  # 45: under min_fit, so not on Today
    assert line and [e.fit["score"] for e in line] == sorted((e.fit["score"] for e in line), reverse=True)
    assert min(e.fit["score"] for e in line) >= 50
    cli.main(["-c", str(cfg.path), "score", "--rescore", "50"])
    assert {b for b, _ in calls} == {"claude"} and len(calls) == len(line)  # no limit, no fallback
    assert " -> 60/100" in capsys.readouterr().err
    store = Store(cfg.state)
    assert all(store.score(e.job.key, rid)["scored_by"] == "claude:m" for e in line)
    store.close()
    cli.main(["-c", str(cfg.path), "score", "--rescore", "50"])
    assert "Every scored job on Today was scored by claude" in capsys.readouterr().out


def test_compare_against_one_backends_scores_with_prompts_to_try(scored, monkeypatch, capsys):
    cfg, rid, jobs = scored
    store = Store(cfg.state)
    store.save_score(jobs[0].key, rid, {"score": 70, "must_haves_met": 1, "must_haves_total": 1,
                                        "scored_by": "claude:claude-sonnet-5-5"})
    assert [j.key for j, _ in watch.compare_picks(cfg, store, 10, by="claude")] == [jobs[0].key]
    store.close()
    sent = []
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, resume, backend, cache, **kw: (
        sent.append(kw["prompts"]) or ({j.key: {"score": 64.0, "must_haves_met": 1, "must_haves_total": 1,
                                                "scored_by": f"{backend}:q"} for j in jobs}, {})))
    tried = cfg.path.parent / "tight.yaml"
    tried.write_text("score_system: Judge strictly.\n")
    cli.main(["-c", str(cfg.path), "score", "--compare", "5", "--stored-by", "claude", "--backend", "local",
              "--prompts", str(tried)])
    out = capsys.readouterr()
    assert sent == [{"score_system": "Judge strictly."}] and "and the prompts in" in out.err
    assert "1 compared: mean difference -6.0, mean size 6.0, largest -6" in out.out
    assert config.load(cfg.path).prompts == {}  # tried, not kept
    store = Store(cfg.state)
    assert store.score(jobs[0].key, rid)["score"] == 70
    store.close()


def test_compare_prompts_must_be_names_and_texts(scored):
    cfg, _, _ = scored
    tried = cfg.path.parent / "bad.yaml"
    tried.write_text("- just a list\n")
    with pytest.raises(SystemExit, match="edited prompts by name"):
        cli.main(["-c", str(cfg.path), "score", "--compare", "2", "--prompts", str(tried)])
