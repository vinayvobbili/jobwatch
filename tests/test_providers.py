"""Setting up cloud scoring providers from Settings: add and remove one, keep its key in the keychain, list its
models, test it. The network and the keychain are mocked; the key must never be in a response or a log."""

import io
import json
import logging
import subprocess
import types
import urllib.error

import pytest
import yaml

from jobwatch import ai, config, providers, score

from .conftest import TOKEN, request

KEY = "-".join(["made", "up", "token", "for", "tests"])  # built, so a secret scanner has no literal to flag
URL = "https://api.example.com/v1"
HEAD = {"X-Jobwatch-Token": TOKEN}


class Keychain:
    """Stands in for `security`: records what it was run with, and says an item exists once a key was put in."""

    def __init__(self):
        self.calls, self.saved = [], False  # calls: everything but lookups

    def __call__(self, cmd, **kw):
        if cmd[1] == "find-generic-password":
            return subprocess.CompletedProcess(cmd, 0 if self.saved else 44, stdout="", stderr="")
        self.calls.append((cmd, kw))
        self.saved = self.saved or cmd[1] == "-i"
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


class Net:
    """Stands in for urllib.request.urlopen: answers by URL (a dict, or an HTTP status to fail with)."""

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, req, timeout=None):
        self.seen.append((req.full_url, req.get_header("Authorization"), req.data))
        answer = self.answers[req.full_url]
        if isinstance(answer, int):
            raise urllib.error.HTTPError(req.full_url, answer, "x", {}, io.BytesIO(b'{"error": "nope"}'))
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())


@pytest.fixture
def mac(monkeypatch):
    """A Mac with a mocked keychain; the provider's env var is restored afterwards."""
    keychain = Keychain()
    monkeypatch.setattr(ai, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr("jobwatch.web.sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(ai, "subprocess", types.SimpleNamespace(
        run=keychain, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(score.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 44, "", ""))
    monkeypatch.delenv("ACME_API_KEY", raising=False)
    return keychain


def call(server, path, body=None, method="POST"):
    status, data = request(server, method, path, body, headers=HEAD)
    return status, json.loads(data)


def scoring_of(watchlist):
    return yaml.safe_load(watchlist.read_text()).get("scoring") or {}


def add_acme(server):
    assert call(server, "/api/ai/providers/add", {"name": "acme", "url": URL + "/"})[0] == 200


def test_the_presets_fill_in_a_base_url_and_custom_leaves_it_blank(server, mac):
    status, data = call(server, "/api/ai/providers", method="GET")
    assert status == 200 and data["keychain"] is True and data["providers"] == []
    by_id = {p["id"]: p for p in data["presets"]}
    assert list(by_id) == ["openrouter", "groq", "google", "custom"]
    assert by_id["openrouter"]["url"].startswith("https://openrouter.ai")
    assert by_id["custom"]["url"] == ""
    assert all(p["url"].startswith("https://") for p in data["presets"][:-1])


def test_a_provider_is_added_to_the_watchlist_without_a_key(server, mac, watchlist):
    add_acme(server)
    assert scoring_of(watchlist)["providers"] == {"acme": {"url": URL}}  # trailing slash dropped
    cfg = config.load(watchlist)
    assert cfg.provider("acme").item == "jobwatch-acme"
    _, data = call(server, "/api/ai/providers", method="GET")
    assert data["providers"] == [{"name": "acme", "url": URL, "env": "ACME_API_KEY", "item": "jobwatch-acme",
                                  "key": ""}]


@pytest.mark.parametrize("body,why", [
    ({"name": "Acme Co", "url": URL}, "lowercase"),
    ({"name": "claude", "url": URL}, "lowercase"),
    ({"name": "acme", "url": "ftp://example.com"}, "http(s)"),
    ({"name": "acme", "url": ""}, "http(s)"),
])
def test_a_bad_name_or_url_is_refused(server, mac, watchlist, body, why):
    status, data = call(server, "/api/ai/providers/add", body)
    assert status == 400 and why in data["error"]
    assert "providers" not in scoring_of(watchlist)


def test_the_same_name_twice_is_refused(server, mac):
    add_acme(server)
    status, data = call(server, "/api/ai/providers/add", {"name": "acme", "url": URL})
    assert status == 400 and "already" in data["error"]


def test_the_key_goes_to_the_keychain_item_and_is_never_echoed(server, mac, monkeypatch, caplog):
    add_acme(server)
    caplog.set_level(logging.DEBUG)
    status, data = request(server, "POST", "/api/ai/providers/key", {"name": "acme", "key": f" {KEY}\n"}, headers=HEAD)
    assert status == 200 and json.loads(data) == {"saved": True, "item": "jobwatch-acme"}
    (cmd, kw), = mac.calls
    assert cmd == ["security", "-i"] and "-s jobwatch-acme " in kw["input"] and KEY in kw["input"]
    assert KEY not in "".join(cmd)
    assert ai.os.environ["ACME_API_KEY"] == KEY
    _, listed = request(server, "GET", "/api/ai/providers", headers=HEAD)
    assert KEY not in listed.decode() and json.loads(listed)["providers"][0]["key"] == "environment"
    assert KEY not in caplog.text


def test_a_key_for_a_provider_that_is_not_set_up_or_that_is_junk_is_refused(server, mac):
    assert call(server, "/api/ai/providers/key", {"name": "ghost", "key": KEY})[0] == 404
    add_acme(server)
    status, data = call(server, "/api/ai/providers/key", {"name": "acme", "key": "two words"})
    assert status == 400 and "API key" in data["error"] and "two words" not in data["error"]
    assert mac.calls == []


def test_a_failing_keychain_does_not_leak_the_key(server, monkeypatch, mac):
    add_acme(server)

    def broken(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=f"security: error: {KEY} refused")

    monkeypatch.setattr(ai.subprocess, "run", broken)
    status, data = request(server, "POST", "/api/ai/providers/key", {"name": "acme", "key": KEY}, headers=HEAD)
    assert status == 400 and KEY not in data.decode() and "ACME_API_KEY" not in ai.os.environ


def test_off_a_mac_it_says_to_set_the_environment_variable(server, monkeypatch, mac):
    add_acme(server)
    monkeypatch.setattr(ai, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr("jobwatch.web.sys", types.SimpleNamespace(platform="linux"))
    status, data = call(server, "/api/ai/providers/key", {"name": "acme", "key": KEY})
    assert status == 400 and "ACME_API_KEY" in data["error"] and "macOS only" in data["error"]
    assert call(server, "/api/ai/providers", method="GET")[1]["keychain"] is False
    assert mac.calls == []


def test_the_models_are_listed_with_the_key_sent_only_as_a_bearer_token(server, mac, monkeypatch):
    add_acme(server)
    monkeypatch.setenv("ACME_API_KEY", KEY)
    net = Net({f"{URL}/models": {"data": [{"id": "models/zeta-1"}, {"id": "alpha-2"}, {"nope": 1}, {"id": "alpha-2"}]}})
    monkeypatch.setattr(providers.urllib.request, "urlopen", net)
    status, data = request(server, "POST", "/api/ai/providers/models", {"name": "acme"}, headers=HEAD)
    assert status == 200 and json.loads(data) == {"models": ["alpha-2", "zeta-1"]}
    assert net.seen == [(f"{URL}/models", f"Bearer {KEY}", None)]
    assert KEY not in data.decode()


def test_listing_models_without_a_key_says_where_to_put_it(server, mac):
    add_acme(server)
    status, data = call(server, "/api/ai/providers/models", {"name": "acme"})
    assert status == 400 and "jobwatch-acme" in data["error"]


@pytest.mark.parametrize("answer,message", [(401, "refused"), (429, "rate limited"), (500, "HTTP 500"),
                                            ({}, "listed no models")])
def test_a_models_list_that_fails_says_why(server, mac, monkeypatch, answer, message):
    add_acme(server)
    monkeypatch.setenv("ACME_API_KEY", KEY)
    monkeypatch.setattr(providers.urllib.request, "urlopen", Net({f"{URL}/models": answer}))
    status, data = request(server, "POST", "/api/ai/providers/models", {"name": "acme"}, headers=HEAD)
    assert status == 400 and message in json.loads(data)["error"] and KEY not in data.decode()


@pytest.mark.parametrize("answer,status", [
    ({"choices": []}, "ok"), (401, "auth"), (403, "auth"), (429, "rate"), (503, "error"),
    (urllib.error.URLError(f"connection to {KEY} failed"), "unreachable")])
def test_the_test_button_reports_ok_auth_failed_or_rate_limited(server, mac, monkeypatch, caplog, answer, status):
    add_acme(server)
    monkeypatch.setenv("ACME_API_KEY", KEY)
    net = Net({f"{URL}/chat/completions": answer})
    monkeypatch.setattr(providers.urllib.request, "urlopen", net)
    caplog.set_level(logging.DEBUG)
    code, data = request(server, "POST", "/api/ai/providers/test", {"name": "acme", "model": "alpha-2"}, headers=HEAD)
    body = json.loads(data)
    assert code == 200 and body["status"] == status
    assert (status == "ok") == ("seconds" in body)
    sent = json.loads(net.seen[0][2])
    assert sent["model"] == "alpha-2" and net.seen[0][1] == f"Bearer {KEY}"
    assert KEY not in data.decode() and KEY not in caplog.text


def test_the_test_needs_a_model(server, mac, monkeypatch):
    add_acme(server)
    monkeypatch.setenv("ACME_API_KEY", KEY)
    status, data = call(server, "/api/ai/providers/test", {"name": "acme", "model": " "})
    assert status == 400 and "model" in data["error"]


def test_a_step_added_to_the_chain_saves_through_settings_and_runs_as_name_model(server, mac, watchlist):
    add_acme(server)
    status, _ = call(server, "/api/settings", {"scoring": {**scoring_of(watchlist), "fallback": ["acme:alpha-2"]}})
    assert status == 200
    assert config.load(watchlist).score_providers[0].name == "acme"
    assert scoring_of(watchlist)["fallback"] == ["acme:alpha-2"]


def test_removing_a_provider_takes_its_chain_steps_and_leaves_the_keychain_alone(server, mac, watchlist):
    add_acme(server)
    call(server, "/api/ai/providers/add", {"name": "other", "url": "https://other.example.com/v1"})
    call(server, "/api/settings", {"scoring": {**scoring_of(watchlist), "backend": "claude",
                                               "fallback": ["acme:alpha-2", "other:beta", "local"]}})
    status, data = call(server, "/api/ai/providers/remove", {"name": "acme"})
    assert status == 200 and data["scoring"]["fallback"] == ["other:beta", "local"]
    saved = scoring_of(watchlist)
    assert list(saved["providers"]) == ["other"] and saved["fallback"] == ["other:beta", "local"]
    assert mac.calls == []  # no `security delete-generic-password`
    call(server, "/api/ai/providers/remove", {"name": "other"})
    assert "providers" not in scoring_of(watchlist)
    config.load(watchlist)


def test_the_provider_that_scores_first_cannot_be_removed(server, mac, watchlist):
    add_acme(server)
    call(server, "/api/settings", {"scoring": {**scoring_of(watchlist), "backend": "acme", "model": "alpha-2"}})
    status, data = call(server, "/api/ai/providers/remove", {"name": "acme"})
    assert status == 400 and "scores first" in data["error"]
    assert "acme" in scoring_of(watchlist)["providers"]
    assert call(server, "/api/ai/providers/remove", {"name": "ghost"})[0] == 400


def test_the_page_has_the_card_and_says_the_key_stays_in_the_keychain(server):
    status, html = request(server, "GET", "/")
    page = html.decode()
    assert status == 200 and 'setCard("providers", "Cloud providers"' in page
    assert "Its key stays in your keychain" in page
    for path in ("add", "key", "models", "test", "remove"):
        assert f'"/api/ai/providers/{path}"' in page
