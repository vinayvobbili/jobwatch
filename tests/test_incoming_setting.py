import json

import pytest

from jobwatch import config

from .conftest import TOKEN, request


def _with(watchlist, body):
    watchlist.write_text(watchlist.read_text() + body)


def test_absent_means_every_source_is_on(watchlist):
    cfg = config.load(watchlist)
    assert cfg.incoming.sources == config.INCOMING_SOURCES
    assert cfg.incoming.gmail_account == ""


def test_a_source_switched_off_and_the_address_are_read(watchlist):
    _with(watchlist, "incoming:\n  sources: {whatsapp: false, linkedin: false}\n  gmail_account: you@example.com\n")
    cfg = config.load(watchlist)
    assert cfg.incoming.sources == ("texts", "gmail")
    assert cfg.incoming.gmail_account == "you@example.com"


@pytest.mark.parametrize("body, says", [
    ("incoming: {source: {texts: false}}\n", "unknown incoming setting"),
    ("incoming: {sources: nope}\n", "incoming.sources looks like"),
    ("incoming: {sources: {sms: false}}\n", "unknown incoming.sources setting"),
    ("incoming: {sources: {texts: maybe}}\n", "incoming.sources.texts is true or false"),
    ("incoming: {gmail_account: globex}\n", "incoming.gmail_account is an email address"),
])
def test_a_bad_setting_is_a_config_error(watchlist, body, says):
    _with(watchlist, body)
    with pytest.raises(config.ConfigError, match=says):
        config.load(watchlist)


def test_settings_saves_and_clears_the_section(server, watchlist):
    headers = {"X-Jobwatch-Token": TOKEN}
    body = {"incoming": {"sources": {"texts": True, "whatsapp": False, "gmail": True, "linkedin": True},
                         "gmail_account": "you@example.com"}}
    assert request(server, "POST", "/api/settings", body, headers=headers)[0] == 200
    cfg = config.load(watchlist)
    assert cfg.incoming.sources == ("texts", "gmail", "linkedin")
    assert cfg.incoming.gmail_account == "you@example.com"
    _, raw = request(server, "GET", "/api/settings", headers=headers)
    got = json.loads(raw)
    assert got["incoming"]["gmail_account"] == "you@example.com"
    assert got["defaults"]["incoming"]["sources"] == dict.fromkeys(config.INCOMING_SOURCES, True)
    assert request(server, "POST", "/api/settings", {"incoming": None}, headers=headers)[0] == 200
    assert config.load(watchlist).incoming.sources == config.INCOMING_SOURCES


def test_the_settings_page_has_the_card_and_no_password_field(server):
    page = request(server, "GET", "/")[1].decode()
    assert 'setCard("incoming"' in page
    assert "jw-incoming --set-password" in page
