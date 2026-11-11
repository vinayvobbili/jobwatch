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
                                  "key": "", "links": []}]


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
    assert status == 200
    assert [m["id"] for g in json.loads(data)["groups"] for m in g["models"]] == ["alpha-2", "zeta-1"]
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


# -- sorting the model list for fit scoring

@pytest.mark.parametrize("model_id,billions", [
    ("acme/widget-70b-instruct", 70), ("acme/widget-3.1-8b", 8), ("acme/mixer-8x22b-instruct", 176),
    ("acme/moe-30b-a3b", 30), ("acme/giant-550b-a55b", 550), ("acme/trill-1t", 1000), ("acme/sparse-a12b", 12),
    ("acme/tiny-1.5b-it:free", 1.5), ("acme/widget2.5-72b", 72), ("acme/widget-large", None),
    ("acme/widget-v3.1", None), ("models/gemini-pro", None)])
def test_the_size_is_read_from_the_id(model_id, billions):
    assert providers.size_billions(model_id) == billions


@pytest.mark.parametrize("model_id", [
    "acme/embed-qa-4", "acme/widget-embedqa-1b", "acme/retriever-300m", "acme/rerank-mistral", "acme/guard-8b",
    "acme/widget-content-safety", "acme/topic-control-8b", "acme/widget-reward-340b", "acme/pii-detector",
    "acme/widget-90b-vision-instruct", "acme/widget-vlm-8b", "acme/widget-vl-72b", "acme/video-gen", "acme/cosmos-1",
    "acme/stable-diffusion-3", "acme/whisper-large", "acme/speech-1", "acme/tts-2", "acme/asr-3",
    "acme/widget-coder-32b", "acme/codellama-70b", "acme/starcoder2-15b", "acme/codegemma-7b", "acme/codestral-22b"])
def test_models_that_cant_do_the_job_are_flagged(model_id):
    assert providers.not_for_scoring(model_id)


@pytest.mark.parametrize("model_id", [
    "acme/widget-70b-instruct", "acme/decoder-8b", "acme/mixer-8x22b", "acme/oracle-1t",
    "acme/widget-reasoning-32b", "gemini-2.5-pro"])
def test_models_that_can_are_not_flagged(model_id):
    assert not providers.not_for_scoring(model_id)


def entry(mid, context=0, free=False):
    return {"id": mid, "context": context, "free": free}


def test_the_groups_come_in_order_with_instruct_first_then_larger_models():
    out = providers.group_models([
        entry("acme/embed-1"), entry("acme/small-8b"), entry("acme/plain-405b"), entry("acme/widget-120b-instruct"),
        entry("acme/mid-70b"), entry("acme/mid-40b-instruct"), entry("acme/mystery"), entry("acme/moe-30b-a3b"),
        entry("acme/small-2b-instruct"), entry("acme/sparse-550b-a55b"), entry("acme/coder-32b")])
    assert [g["id"] for g in out["groups"]] == ["large", "medium", "small", "unknown", "skip"]
    assert out["groups"][0]["label"].startswith("Large: most accurate (100B+")
    by = {g["id"]: [m["id"] for m in g["models"]] for g in out["groups"]}
    assert by["large"] == ["acme/widget-120b-instruct", "acme/sparse-550b-a55b", "acme/plain-405b"]
    assert by["medium"] == ["acme/mid-40b-instruct", "acme/mid-70b", "acme/moe-30b-a3b"]
    assert by["small"] == ["acme/small-2b-instruct", "acme/small-8b"]
    assert by["unknown"] == ["acme/mystery"] and by["skip"] == ["acme/coder-32b", "acme/embed-1"]
    assert out["count"] == 11 and out["free"] == 0


def test_empty_groups_are_left_out():
    assert [g["id"] for g in providers.group_models([entry("acme/a-8b")])["groups"]] == ["small"]


def test_the_free_filter_keeps_only_free_models_and_labels_carry_the_metadata():
    entries = [entry("acme/a-70b:free", 131072, True), entry("acme/b-70b", 32000), entry("acme/c-8b", 1_048_576, True)]
    out = providers.group_models(entries)
    assert out["free"] == 2 and out["count"] == 3
    assert out["groups"][0]["models"][0] == {"id": "acme/a-70b:free", "detail": "free · 131K ctx", "free": True}
    assert out["groups"][0]["models"][1]["detail"] == "32K ctx"
    assert out["groups"][1]["models"][0]["detail"] == "free · 1.05M ctx"
    only = providers.group_models(entries, free_only=True)
    assert only["count"] == 2 and only["free"] == 2
    assert [m["id"] for g in only["groups"] for m in g["models"]] == ["acme/a-70b:free", "acme/c-8b"]


def test_models_reads_context_and_free_from_the_listing(monkeypatch):
    rows = {"data": [{"id": "acme/a-70b:free", "context_length": 8000},
                     {"id": "acme/b", "pricing": {"prompt": "0", "completion": "0"}},
                     {"id": "acme/c", "pricing": {"prompt": "0.000001", "completion": "0"}}, {"id": "acme/d"}]}
    monkeypatch.setattr(providers.urllib.request, "urlopen", Net({f"{URL}/models": rows}))
    got = providers.models(score.Provider("acme", URL), KEY)
    assert [(m["id"], m["context"], m["free"]) for m in got] == [
        ("acme/a-70b:free", 8000, True), ("acme/b", 0, True), ("acme/c", 0, False), ("acme/d", 0, False)]


def test_the_models_endpoint_answers_in_groups_and_filters_free(server, mac, monkeypatch):
    add_acme(server)
    monkeypatch.setenv("ACME_API_KEY", KEY)
    rows = {"data": [{"id": "acme/big-405b-instruct", "context_length": 131072}, {"id": "acme/tiny-3b:free"},
                     {"id": "acme/embed-1"}]}
    monkeypatch.setattr(providers.urllib.request, "urlopen", Net({f"{URL}/models": rows}))
    status, data = request(server, "POST", "/api/ai/providers/models", {"name": "acme"}, headers=HEAD)
    got = json.loads(data)
    assert status == 200 and set(got) == {"groups", "count", "free"} and got["free"] == 1
    assert [g["id"] for g in got["groups"]] == ["large", "small", "skip"]
    assert got["groups"][0]["models"] == [{"id": "acme/big-405b-instruct", "detail": "131K ctx", "free": False}]
    status, data = request(server, "POST", "/api/ai/providers/models", {"name": "acme", "free": True}, headers=HEAD)
    assert [m["id"] for g in json.loads(data)["groups"] for m in g["models"]] == ["acme/tiny-3b:free"]


# -- links to the provider's account pages

def test_a_provider_at_a_presets_base_url_gets_its_links():
    preset = next(p for p in providers.PRESETS if p["id"] == "groq")
    got = providers.links(score.Provider("my-groq", preset["url"] + "/"))
    assert [(link["label"], link["url"]) for link in got] == [
        ("Keys", "https://console.groq.com/keys"), ("Usage", "https://console.groq.com/settings/usage")]
    assert [link["label"] for link in providers.links(score.Provider("x", "https://openrouter.ai/api/v1"))] == [
        "Keys", "Credits & usage"]


def test_an_unknown_provider_has_no_links_unless_it_sets_an_account_url():
    assert providers.links(score.Provider("acme", URL)) == []
    assert providers.links(score.Provider("acme", URL, account_url="https://example.com/me")) == [
        {"label": "Account", "url": "https://example.com/me"}]
    google = score.Provider("g", providers.PRESETS[2]["url"], account_url="https://example.com/me")
    assert [link["label"] for link in providers.links(google)] == ["Keys", "Usage", "Account"]
    assert all(p["links"] == [] for p in providers.PRESETS if p["id"] == "custom")


def test_the_providers_endpoint_carries_each_providers_links(server, mac):
    add_acme(server)
    assert call(server, "/api/ai/providers", method="GET")[1]["providers"][0]["links"] == []
    assert call(server, "/api/ai/providers/add", {"name": "router", "url": "https://openrouter.ai/api/v1"})[0] == 200
    by = {p["name"]: p["links"] for p in call(server, "/api/ai/providers", method="GET")[1]["providers"]}
    assert by["router"][0] == {"label": "Keys", "url": "https://openrouter.ai/settings/keys"}


def test_account_url_is_a_provider_setting_that_must_be_a_web_address(tmp_path):
    def load(account):
        path = tmp_path / "w.yaml"
        path.write_text(yaml.safe_dump({"companies": {}, "scoring": {"providers": {
            "acme": {"url": URL, "account_url": account}}}}))
        return config.load(path)
    assert load("https://example.com/me").score_providers[0].account_url == "https://example.com/me"
    with pytest.raises(config.ConfigError, match="account_url"):
        load("javascript:alert(1)")
