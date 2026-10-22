"""Whom to ask for a referral: people marked Use sort first, Don't use are never suggested (like connections_skip), the
note travels with the person; the Referrals tab's rows, `jobwatch referrals` and the rate_contact tool. No network:
the boards are canned (the `web` fixture) and the connections are made-up."""

import json

import pytest

from jobwatch import advice, cli, config, referrals, watch
from jobwatch.contacts import Contacts, key_for, person_key
from jobwatch.store import Store

from .conftest import TOKEN, request
from .test_contacts import CONNECTIONS, add_connections

ANA, BO = "example-ana", "example-bo"
TIES = {ANA: {"messages": 3, "last_message": "2022-03-01"}, BO: {"messages": 9}}


@pytest.fixture
def connections(tmp_path):
    path = tmp_path / "Connections.csv"
    path.write_text(CONNECTIONS, encoding="utf-8")
    return path


def names(contacts, company="Initech"):
    return [p["name"] for p in contacts.at(company)]


def test_people_are_keyed_by_profile_then_by_name():
    assert person_key({"name": "Ana Li", "url": "https://www.linkedin.com/in/Example-Ana/"}) == ANA
    assert person_key({"name": "Ana  LI", "url": ""}) == "name:ana li"
    assert key_for("linkedin.com/in/example-ana") == ANA and key_for("Ana Li") == "name:ana li"


def test_use_sorts_first_ahead_of_tie_strength(connections):
    people = Contacts.load(connections).everyone
    assert names(Contacts(people, TIES)) == ["Bo Chen", "Ana Li"]  # Bo is the closer tie
    fb = {ANA: {"verdict": "use", "note": "answers fast"}}
    first = Contacts(people, TIES, feedback=fb).at("Initech")[0]
    assert first["name"] == "Ana Li" and first["note"] == "answers fast" and first["verdict"] == "use"


def test_skip_is_never_suggested_and_connections_skip_still_works(connections):
    people = Contacts.load(connections).everyone
    c = Contacts(people, TIES, skip=["Bo Chen"], feedback={ANA: {"verdict": "skip", "note": "never replies"}})
    assert names(c) == []
    assert {p["name"]: p["from_file"] for p in c.left_out("Initech")} == {"Ana Li": False, "Bo Chen": True}
    assert c.find("Ana Li")["note"] == "never replies"


def test_find_by_name_link_or_key_and_says_when_it_cant(connections):
    c = Contacts.load(connections)
    assert c.find("ana li")["key"] == c.find("https://www.linkedin.com/in/example-ana")["key"] == c.find(ANA)["key"]
    with pytest.raises(ValueError, match="no connection"):
        c.find("Nobody Here")
    twins = Contacts([{"name": "Ana Li", "url": "", "company": "X"}, {"name": "Ana Li", "url": "", "company": "Y"}])
    with pytest.raises(ValueError, match="2 connections"):
        twins.find("Ana Li")


def test_store_sets_replaces_clears_and_lists(tmp_path):
    store = Store(tmp_path / "s.db")
    store.rate_contact(ANA, "use", " answers fast ")
    store.rate_contact(BO, "skip")
    store.rate_contact(ANA, "skip", "moved teams")  # replaces
    fb = store.contact_feedback()
    assert fb[ANA]["verdict"] == "skip" and fb[ANA]["note"] == "moved teams" and fb[BO]["note"] == ""
    assert store.clear_contact(ANA) and not store.clear_contact(ANA)
    assert list(store.contact_feedback()) == [BO]
    with pytest.raises(ValueError, match="verdict"):
        store.rate_contact(BO, "maybe")
    store.close()


def test_the_flow_loads_feedback_and_advice_shows_the_note(web, watchlist, connections):
    add_connections(watchlist, connections)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.rate_contact(ANA, "use", "reach on WhatsApp")
    watch.fetch_all(cfg, store)
    assert names(watch.load_contacts(cfg))[0] == "Ana Li"
    store.rate_contact(BO, "skip")
    assert names(watch.load_contacts(cfg)) == ["Ana Li"]
    entries = [e for e in watch.build_digest(cfg, store).entries if e.contacts]
    assert entries and entries[0].contacts[0]["note"] == "reach on WhatsApp"
    text = advice.advise(cfg, entries[0], advice.History(store))
    assert "you know Ana Li there: ask for a referral first (reach on WhatsApp)" in text.line
    store.close()


def test_view_lists_people_at_tracked_companies(web, watchlist, connections):
    add_connections(watchlist, connections)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    v = referrals.view(cfg, store)
    assert v["has_connections"] and {p["name"] for p in v["people"]} == {"Ana Li", "Bo Chen", "Cy Diaz"}
    ana = next(p for p in v["people"] if p["name"] == "Ana Li")
    assert ana["jobs"] and ana["jobs"][0]["company"] == "Initech"  # Umbrella's Dee Park has no tracked job
    referrals.rate(cfg, store, "Cy Diaz", "skip", "never replies")
    v = referrals.view(cfg, store)
    assert [p["name"] for p in v["skipped"]] == ["Cy Diaz"] and v["skipped"][0]["note"] == "never replies"
    assert "Cy Diaz" not in {p["name"] for p in v["people"]}
    assert "[don't use] Cy Diaz" in referrals.text(v)
    store.close()


def test_view_without_a_connections_file(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    assert referrals.view(cfg, store) == {"people": [], "skipped": [], "has_connections": False}
    with pytest.raises(ValueError, match="no connections file"):
        referrals.rate(cfg, store, "Ana Li", "use")
    store.close()


def test_cli_lists_rates_and_clears(web, watchlist, connections, capsys):
    add_connections(watchlist, connections)
    c = ["-c", str(watchlist)]
    cli.main([*c, "fetch"])
    capsys.readouterr()
    cli.main([*c, "referrals", "--use", "Bo Chen", "--note", "reach on WhatsApp", "--skip", "Ana Li"])
    assert "Bo Chen sorts first" in capsys.readouterr().out
    cli.main([*c, "referrals"])
    out = capsys.readouterr().out
    assert "[use] Bo Chen" in out and "reach on WhatsApp" in out and out.index("Bo Chen") < out.index("Cy Diaz")
    assert "Not suggested (1)" in out and "[don't use] Ana Li" in out
    cli.main([*c, "referrals", "--clear", "Ana Li", "--clear", "Bo Chen"])
    capsys.readouterr()
    cli.main([*c, "referrals", "--format", "json"])
    v = json.loads(capsys.readouterr().out)
    assert v["skipped"] == [] and all(p["verdict"] == "" for p in v["people"])
    with pytest.raises(SystemExit, match="no connection matches"):
        cli.main([*c, "referrals", "--use", "Nobody Here"])


def test_the_tab_and_its_routes(server, watchlist, connections):
    add_connections(watchlist, connections)
    ok = {"X-Jobwatch-Token": TOKEN}
    assert '<button data-tab="referrals">Referrals</button>' in request(server, "GET", "/")[1].decode()
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, body = request(server, "GET", "/api/referrals", headers=ok)
    assert status == 200 and json.loads(body)["has_connections"] and json.loads(body)["people"]
    status, body = request(server, "POST", "/api/referrals/rate",
                           {"who": ANA, "verdict": "skip", "note": "never replies"}, headers=ok)
    assert status == 200 and json.loads(body)["verdict"] == "skip"
    v = json.loads(request(server, "GET", "/api/referrals", headers=ok)[1])
    assert [p["name"] for p in v["skipped"]] == ["Ana Li"]
    status, body = request(server, "POST", "/api/referrals/rate", {"who": "Nobody", "verdict": "use"}, headers=ok)
    assert status == 400 and "no connection" in json.loads(body)["error"]
    status, _ = request(server, "POST", "/api/referrals/rate", {"who": ANA, "verdict": "clear"}, headers=ok)
    assert status == 200 and not json.loads(request(server, "GET", "/api/referrals", headers=ok)[1])["skipped"]


def test_rate_contact_tool(web, watchlist, connections, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    add_connections(watchlist, connections)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    got = mcp.rate_contact("Ana Li", "use", "reach on WhatsApp")
    assert got["verdict"] == "use" and got["note"] == "reach on WhatsApp" and got["company"] == "Initech, Inc."
    assert mcp.rate_contact("Ana Li", "clear")["verdict"] == ""
    with pytest.raises(mcp.ToolError, match="no connection"):
        mcp.rate_contact("Nobody", "skip")
