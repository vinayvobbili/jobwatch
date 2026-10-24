"""Where the AI runs: which choices are ready here, saving the Claude key in the keychain, and the one-call test."""

import subprocess
import sys
import types

from jobwatch import ai

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


def run_result(returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


def test_agy_is_found_on_the_path_first(monkeypatch, tmp_path):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/somewhere/agy")
    monkeypatch.setattr(ai, "AGY_PLACES", (str(tmp_path / "agy"),))
    assert ai.find_agy() == "/somewhere/agy"


def test_agy_is_found_in_a_usual_install_place_when_it_is_not_on_the_path(monkeypatch, tmp_path):
    missing, there = tmp_path / "nope" / "agy", tmp_path / "bin" / "agy"
    there.parent.mkdir()
    there.write_text("#!/bin/sh\n")
    there.chmod(0o755)
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    monkeypatch.setattr(ai, "AGY_PLACES", (str(missing), str(there)))
    assert ai.find_agy() == str(there)


def test_a_non_executable_file_in_an_install_place_is_not_agy(monkeypatch, tmp_path):
    plain = tmp_path / "agy"
    plain.write_text("not runnable")
    plain.chmod(0o644)
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    monkeypatch.setattr(ai, "AGY_PLACES", (str(plain),))
    assert ai.find_agy() is None


def test_agy_is_none_when_it_is_nowhere(monkeypatch, tmp_path):
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    monkeypatch.setattr(ai, "AGY_PLACES", (str(tmp_path / "agy"),))
    assert ai.find_agy() is None


def test_the_key_comes_from_the_environment_without_asking_the_keychain(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def boom(*a, **k):
        raise AssertionError("the keychain should not be asked")

    monkeypatch.setattr(ai.subprocess, "run", boom)
    assert ai.key_source("item") == "environment"


def test_the_key_source_is_the_keychain_when_the_item_exists_and_the_secret_is_never_read(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ai.sys, "platform", "darwin")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return run_result(0)

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    assert ai.key_source("item") == "keychain"
    assert calls == [["security", "find-generic-password", "-s", "item"]]
    assert "-w" not in calls[0]


def test_there_is_no_key_source_when_the_keychain_has_no_item_or_is_not_a_mac(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ai.subprocess, "run", lambda cmd, **kw: run_result(44))
    monkeypatch.setattr(ai.sys, "platform", "darwin")
    assert ai.key_source("item") == ""
    assert ai.key_source("") == ""
    monkeypatch.setattr(ai.sys, "platform", "linux")
    monkeypatch.setattr(ai.subprocess, "run", lambda cmd, **kw: run_result(0))
    assert ai.key_source("item") == ""


def ready_here(monkeypatch, **over):
    """Everything present, unless overridden."""
    things = {"_installed": lambda m: True, "_agy_supported": lambda: True, "find_agy": lambda: "/bin/agy",
              "apple_silicon": lambda: True, "key_source": lambda k: "environment"}
    things.update(over)
    for name, fn in things.items():
        monkeypatch.setattr(ai, name, fn)


def test_status_has_every_choice_ready_when_everything_is_present(monkeypatch):
    ready_here(monkeypatch)
    s = ai.status()
    assert set(s) == set(ai.BACKENDS)
    assert all(s[b]["ready"] and not s[b]["steps"] for b in ai.BACKENDS)
    assert s["claude"]["key"] == "environment"
    assert s["claude"]["keychain"] == ai.KEYCHAIN
    assert s["agy"]["path"] == "/bin/agy"


def test_claude_needs_a_key_step_when_there_is_no_key(monkeypatch):
    ready_here(monkeypatch, key_source=lambda k: "")
    monkeypatch.setattr(ai.sys, "platform", "darwin")
    s = ai.status("mine")
    assert not s["claude"]["ready"]
    assert [st["link"] for st in s["claude"]["steps"]] == [ai.KEYS_PAGE]
    assert "keychain" in s["claude"]["steps"][0]["text"]
    assert s["claude"]["keychain"] == "mine"
    assert s["agy"]["ready"] and s["local"]["ready"]


def test_off_a_mac_the_key_step_says_to_set_the_environment_variable(monkeypatch):
    ready_here(monkeypatch, key_source=lambda k: "")
    monkeypatch.setattr(ai.sys, "platform", "linux")
    s = ai.status()
    assert "ANTHROPIC_API_KEY" in s["claude"]["steps"][0]["text"]
    assert s["claude"]["can_save_key"] is False


def test_agy_needs_a_step_when_the_cli_is_missing(monkeypatch):
    ready_here(monkeypatch, find_agy=lambda: None)
    s = ai.status()
    assert not s["agy"]["ready"]
    assert [st["link"] for st in s["agy"]["steps"]] == [ai.AGY_DOCS]
    assert s["agy"]["path"] == ""
    assert s["claude"]["ready"]


def test_agy_needs_an_update_when_the_scoring_add_on_is_too_old(monkeypatch):
    ready_here(monkeypatch, _agy_supported=lambda: False)
    s = ai.status()
    assert not s["agy"]["ready"]
    assert s["agy"]["steps"][0]["command"] == "pip install -U shortlist-ai"


def test_without_the_scoring_add_on_claude_and_agy_ask_to_install_it(monkeypatch):
    ready_here(monkeypatch, _installed=lambda m: m != "shortlist_ai")
    s = ai.status()
    for b in ("claude", "agy"):
        assert not s[b]["ready"]
        assert s[b]["steps"][0]["command"] == ai.INSTALL_SCORE
    assert s["local"]["ready"]


def test_local_needs_apple_silicon(monkeypatch):
    ready_here(monkeypatch, apple_silicon=lambda: False)
    s = ai.status()
    assert not s["local"]["ready"]
    assert s["local"]["possible"] is False
    assert s["local"]["steps"] == [{"text": "Needs a Mac with Apple Silicon (M1 or later)"}]


def test_local_asks_for_the_on_device_add_on_when_mlx_is_missing(monkeypatch):
    ready_here(monkeypatch, _installed=lambda m: m != "mlx_lm")
    s = ai.status()
    assert not s["local"]["ready"]
    assert s["local"]["steps"][0]["command"] == ai.INSTALL_LOCAL
    assert s["local"]["possible"] is True


# save_key


class Spy:
    def __init__(self, result=None, raises=None):
        self.calls, self.result, self.raises = [], result or run_result(0), raises

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.raises:
            raise self.raises
        return self.result


def mac(monkeypatch, spy):
    monkeypatch.setattr(ai.sys, "platform", "darwin")
    monkeypatch.setattr(ai.subprocess, "run", spy)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_a_key_that_is_not_an_anthropic_key_is_refused_without_calling_security(monkeypatch):
    spy = Spy()
    mac(monkeypatch, spy)
    for bad in ("", "hunter2", "sk-ant-short", "sk-openai-" + "a" * 40):
        try:
            ai.save_key(bad)
        except ValueError as e:
            assert "Anthropic API key" in str(e)
        else:
            raise AssertionError(f"{bad!r} was accepted")
    assert spy.calls == []


def test_a_bad_keychain_name_is_refused(monkeypatch):
    spy = Spy()
    mac(monkeypatch, spy)
    for bad in ("has space", "semi;colon", "a" * 65, "new\nline"):
        try:
            ai.save_key(KEY, bad)
        except ValueError as e:
            assert "keychain item name" in str(e)
        else:
            raise AssertionError(f"{bad!r} was accepted")
    assert spy.calls == []


def test_saving_a_key_off_a_mac_is_refused(monkeypatch):
    spy = Spy()
    mac(monkeypatch, spy)
    monkeypatch.setattr(ai.sys, "platform", "linux")
    try:
        ai.save_key(KEY)
    except ValueError as e:
        assert "macOS only" in str(e)
    else:
        raise AssertionError("accepted off a Mac")
    assert spy.calls == []


def test_the_key_goes_to_security_on_its_input_never_its_command_line(monkeypatch):
    spy = Spy()
    mac(monkeypatch, spy)
    assert ai.save_key(f"  {KEY}\n", "my-item") == "my-item"
    (cmd, kw), = spy.calls
    assert cmd == ["security", "-i"]
    assert not any(KEY in part for part in cmd)
    assert KEY in kw["input"]
    assert "-s my-item" in kw["input"]
    assert ai.os.environ["ANTHROPIC_API_KEY"] == KEY


def test_the_default_keychain_item_is_used_when_none_is_named(monkeypatch):
    spy = Spy()
    mac(monkeypatch, spy)
    assert ai.save_key(KEY) == ai.KEYCHAIN
    assert f"-s {ai.KEYCHAIN} " in spy.calls[0][1]["input"]


def test_an_error_from_security_does_not_leak_the_key_or_set_the_environment(monkeypatch):
    spy = Spy(run_result(1, stderr=f"security: error: bad value {KEY} in item"))
    mac(monkeypatch, spy)
    try:
        ai.save_key(KEY)
    except ValueError as e:
        assert KEY not in str(e)
        assert "didn't take the key" in str(e)
    else:
        raise AssertionError("an error was swallowed")
    assert "ANTHROPIC_API_KEY" not in ai.os.environ


def test_security_that_cannot_run_gives_a_plain_error(monkeypatch):
    mac(monkeypatch, Spy(raises=OSError(f"no such file {KEY}")))
    try:
        ai.save_key(KEY)
    except ValueError as e:
        assert KEY not in str(e)
        assert "OSError" in str(e)
    else:
        raise AssertionError("an error was swallowed")


# test()


class Reply:
    def __init__(self, ok):
        self.ok = ok


class FakeEngine:
    model = "fake-model"

    def __init__(self, ok=True, error=None):
        self.ok, self.error, self.executable = ok, error, None

    def structured(self, system, content, schema):
        if self.error:
            raise self.error
        return Reply(self.ok)


def fake_backends(monkeypatch, engine, asked=None):
    def get_backend(name, model=None):
        if asked is not None:
            asked.append((name, model))
        return engine

    pkg = types.ModuleType("shortlist_ai")
    mod = types.ModuleType("shortlist_ai.backends")
    mod.get_backend = get_backend
    pkg.backends = mod
    monkeypatch.setitem(sys.modules, "shortlist_ai", pkg)
    monkeypatch.setitem(sys.modules, "shortlist_ai.backends", mod)


def test_an_unknown_backend_is_not_ok():
    out = ai.test("gpt")
    assert out["ok"] is False
    assert "unknown backend 'gpt'" in out["error"]


def test_a_working_model_reports_the_time_and_the_model(monkeypatch):
    asked = []
    fake_backends(monkeypatch, FakeEngine(), asked)
    out = ai.test("local", "some-model")
    assert out["ok"] is True
    assert out["model"] == "fake-model"
    assert isinstance(out["seconds"], float)
    assert asked == [("local", "some-model")]


def test_no_model_name_asks_for_the_default(monkeypatch):
    asked = []
    fake_backends(monkeypatch, FakeEngine(), asked)
    ai.test("local")
    assert asked == [("local", None)]


def test_a_model_that_answers_not_ok_is_not_ok(monkeypatch):
    fake_backends(monkeypatch, FakeEngine(ok=False))
    assert ai.test("local")["ok"] is False


def test_a_model_that_raises_gives_the_error_text(monkeypatch):
    fake_backends(monkeypatch, FakeEngine(error=RuntimeError("quota exhausted")))
    out = ai.test("local")
    assert out == {"ok": False, "error": "RuntimeError: quota exhausted"}


def test_a_long_error_is_cut_short(monkeypatch):
    fake_backends(monkeypatch, FakeEngine(error=RuntimeError("x" * 1000)))
    assert len(ai.test("local")["error"]) == 400


def test_agy_runs_from_where_find_agy_found_it(monkeypatch):
    engine = FakeEngine()
    fake_backends(monkeypatch, engine)
    monkeypatch.setattr(ai, "find_agy", lambda: "/opt/agy")
    assert ai.test("agy")["ok"] is True
    assert engine.executable == "/opt/agy"


def test_agy_falls_back_to_the_bare_command_when_it_was_not_found(monkeypatch):
    engine = FakeEngine()
    fake_backends(monkeypatch, engine)
    monkeypatch.setattr(ai, "find_agy", lambda: None)
    ai.test("agy")
    assert engine.executable == "agy"


def test_claude_without_a_key_says_why_and_never_calls_the_model(monkeypatch):
    fake_backends(monkeypatch, FakeEngine(error=AssertionError("model called")))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ai.subprocess, "run", lambda cmd, **kw: run_result(44))
    out = ai.test("claude", keychain="missing-item")
    assert out["ok"] is False
    assert "missing-item" in out["error"]
