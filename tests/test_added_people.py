"""People added by hand (someone who isn't a LinkedIn connection): kept in the state file, listed wherever connections
are, matched to a company like them, ranked as a close tie, removable (they only), never dropped by a fresh LinkedIn
export. No network: the boards are canned (the `web` fixture) and every person and company is made up."""

import io
import json
import zipfile

import pytest

from jobwatch import advice, cli, company, config, contacts, outreach, referrals, watch
from jobwatch.contacts import ADDED_STRENGTH, REACH, Contacts, clean_person, hand_note
from jobwatch.store import Store

from .conftest import TOKEN, request
from .test_contacts import add_connections
from .test_referrals import ANA, TIES, connections  # noqa: F401 (fixture)

RAE = "name:rae quinn"


@pytest.fixture
def cfg_store(web, watchlist, connections):  # noqa: F811
    add_connections(watchlist, connections)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    yield cfg, store
    store.close()


def test_a_person_is_checked_and_tidied():
    got = clean_person("  Rae   Quinn ", " Initech  Inc ", "Designer", " met at a meetup ", "WhatsApp",
                       "linkedin.com/in/Example-Rae/", "rae@example.com", " 555-0100 ")
    assert got == {"name": "Rae Quinn", "company": "Initech Inc", "position": "Designer", "about": "met at a meetup",
                   "reach": "whatsapp", "url": "https://www.linkedin.com/in/example-rae",
                   "email": "rae@example.com", "phone": "555-0100"}
    for bad, match in [({"name": " "}, "needs a name"), ({"company": " , "}, "needs a company"),
                       ({"reach": "pigeon"}, "must be one of"),
                       ({"url": "https://example.com/rae"}, "linkedin.com/in/"), ({"email": "rae"}, "isn't an email"),
                       ({"note": "x" * 201}, "200 characters")]:
        with pytest.raises(ValueError, match=match):
            clean_person(**{"name": "Rae Quinn", "company": "Initech", **bad})


def test_the_store_adds_changes_and_removes(tmp_path):
    store = Store(tmp_path / "s.db")
    p = store.add_person("Rae Quinn", "Initech", note="met at a meetup", reach="email", added_at="2030-01-02T03:04:05")
    assert p["key"] == RAE and p["position"] == "" and p["about"] == "met at a meetup"
    assert p["added_at"] == "2030-01-02T03:04:05"
    with pytest.raises(ValueError, match="already added by hand"):
        store.add_person("rae  QUINN", "Globex")
    store.rate_contact(RAE, "use")
    # a link changes the key: the choice made about them follows
    got = store.update_person(RAE, title="Staff Designer", url="linkedin.com/in/example-rae", note="")
    assert got["key"] == "example-rae" and got["position"] == "Staff Designer" and got["about"] == ""
    assert got["reach"] == "email" and [p["name"] for p in store.added_people()] == ["Rae Quinn"]
    assert list(store.contact_feedback()) == ["example-rae"]
    with pytest.raises(ValueError, match="no one added"):
        store.update_person(RAE, title="x")
    assert store.remove_person("example-rae") and not store.remove_person("example-rae")
    assert store.added_people() == [] and store.contact_feedback() == {}
    store.close()


def test_they_match_a_company_by_its_normalized_name_like_a_connection():
    hand = [{"name": "Rae Quinn", "company": "Globex Corporation", "position": "Designer"},
            {"name": "Sam Ortiz", "company": "Initech, Inc."}]
    c = Contacts([{"name": "Cy Diaz", "company": "Globex", "url": "", "position": ""}], added=hand)
    assert [p["name"] for p in c.at("globex")] == ["Rae Quinn", "Cy Diaz"]  # a close tie ranks above an unmeasured one
    assert [p["name"] for p in c.at("Initech Inc", "initech")] == ["Sam Ortiz"]
    rae, cy = c.at("Globex")
    assert rae["by_hand"] and rae["why"] == "added by hand" and rae["strength"] == ADDED_STRENGTH and not cy["by_hand"]


def test_a_hand_added_person_ranks_like_someone_you_messaged(connections):  # noqa: F811
    people = Contacts.load(connections).everyone
    hand = [{"name": "Rae Quinn", "company": "Initech"}]
    # Bo (9 messages) is closer; Ana (3) is not as close as someone you added on purpose
    assert [p["name"] for p in Contacts(people, TIES, added=hand).at("Initech")] == ["Bo Chen", "Rae Quinn", "Ana Li"]
    chosen = Contacts(people, TIES, added=hand, feedback={ANA: {"verdict": "use", "note": ""}}).at("Initech")
    assert chosen[0]["name"] == "Ana Li"  # Ask first still leads
    # a message or two on LinkedIn doesn't lower them; a long correspondence adds up
    few = Contacts(people, {**TIES, RAE: {"messages": 2}}, added=hand).at("Initech")
    assert next(p for p in few if p["name"] == "Rae Quinn")["strength"] == ADDED_STRENGTH
    many = Contacts(people, {**TIES, RAE: {"messages": 20}}, added=hand).at("Initech")[0]
    assert many["name"] == "Rae Quinn" and many["strength"] == 20 and many["why"] == "messaged 20×; added by hand"


def test_the_note_is_how_you_reach_them_and_your_words():
    assert hand_note({"reach": "whatsapp", "about": "not on LinkedIn"}) == "reach on WhatsApp; not on LinkedIn"
    assert hand_note({"reach": "", "about": " met at a meetup "}) == "met at a meetup" and hand_note({}) == ""
    assert set(REACH) == {"whatsapp", "text", "email", "phone", "in person"}


def test_they_reach_every_place_connections_do(cfg_store):
    cfg, store = cfg_store
    p = referrals.add(cfg, store, "Rae Quinn", "Initech Inc.", "Designer", "met at a meetup", "whatsapp",
                      email="rae@example.com")
    assert p["tracked"] and p["by_hand"] and p["key"] == RAE and p["note"] == "reach on WhatsApp; met at a meetup"
    # the Referrals payload: the person row with their jobs, and the same row in the terminal list
    v = referrals.view(cfg, store)
    rae = next(r for r in v["people"] if r["name"] == "Rae Quinn")
    assert rae["jobs"] and rae["by_hand"] and rae["added_at"] and rae["email"] == "rae@example.com"
    assert rae["position"] == "Designer" and rae["why"] == "added by hand"
    text = referrals.text(v)
    assert "Rae Quinn (Designer), Initech Inc. [added by hand] - reach on WhatsApp; met at a meetup" in text
    assert "<rae@example.com>" in text
    # who to contact for a job: the person, with their email, as someone you know there
    who = outreach.who(cfg, store, rae["jobs"][0]["key"])
    found = next(x for x in who["people"] if x["name"] == "Rae Quinn")
    assert found["source"] == "connection" and found["email"] == "rae@example.com" and "added by hand" in found["why"]
    assert who["has_connections"]
    # the Company tab's people panel
    assert "Rae Quinn" in [c["name"] for c in company.view(cfg, store, "Initech")["contacts"]]
    # "You know" lines (the digest and queue entries), and the advice line once they are chosen first
    store.rate_contact(RAE, "use")
    entries = [e for e in watch.build_digest(cfg, store).entries if e.contacts]
    entry = next(e for e in entries if e.contacts[0]["name"] == "Rae Quinn")
    assert advice.advise(cfg, entry, advice.History(store)).line.count(
        "you know Rae Quinn there: ask for a referral first (reach on WhatsApp; met at a meetup)") == 1


def test_the_choices_and_notes_work_for_them(cfg_store):
    cfg, store = cfg_store
    referrals.add(cfg, store, "Rae Quinn", "Initech", note="met at a meetup")
    got = referrals.rate(cfg, store, "Rae Quinn", "use", "met at a meetup")  # a pill's key press sends it back
    assert got["verdict"] == "use" and got["note"] == "met at a meetup"
    assert store.added_person(RAE)["about"] == "met at a meetup" and store.contact_feedback()[RAE]["note"] == ""
    assert referrals.rate(cfg, store, "Rae Quinn", "use", "friend of a friend")["note"] == "friend of a friend"
    assert store.added_person(RAE)["about"] == "friend of a friend"
    referrals.rate(cfg, store, "Rae Quinn", "skip")
    v = referrals.view(cfg, store)
    assert [p["name"] for p in v["skipped"]] == ["Rae Quinn"] and v["skipped"][0]["note"] == "friend of a friend"
    assert referrals.rate(cfg, store, "Rae Quinn", "clear")["note"] == "friend of a friend"  # their own words stay
    assert not store.contact_feedback()


def test_a_duplicate_is_refused_and_says_so(cfg_store):
    cfg, store = cfg_store
    with pytest.raises(referrals.AlreadyKnown, match=r"Already in your connections: Ana Li at Initech, Inc\."):
        referrals.add(cfg, store, "ana  li", "INITECH Corporation")
    with pytest.raises(ValueError, match="Already in your connections"):
        referrals.add(cfg, store, "Ana Li", "initech")
    referrals.add(cfg, store, "Rae Quinn", "Initech")
    with pytest.raises(referrals.AlreadyKnown, match="Already added by hand: Rae Quinn at Initech"):
        referrals.add(cfg, store, "Rae Quinn", "Initech Inc")
    assert referrals.duplicate(cfg, "Rae Quinn", "Globex") is None  # the same name elsewhere is not the same listing
    assert referrals.duplicate(cfg, "Rae Quinn", "Initech, Inc.")["by_hand"]


def test_remove_is_for_hand_added_people_only(cfg_store):
    cfg, store = cfg_store
    referrals.add(cfg, store, "Rae Quinn", "Initech")
    referrals.rate(cfg, store, "Rae Quinn", "use")
    with pytest.raises(ValueError, match=r"Ana Li is one of your LinkedIn connections.*only skipped"):
        referrals.remove(cfg, store, "Ana Li")
    assert referrals.remove(cfg, store, "Rae Quinn")["company"] == "Initech"
    assert "Rae Quinn" not in {p["name"] for p in referrals.view(cfg, store)["people"]} and not store.contact_feedback()
    with pytest.raises(ValueError, match="no connection matches"):
        referrals.remove(cfg, store, "Rae Quinn")
    with pytest.raises(ValueError, match="LinkedIn connections: they can't be changed"):
        referrals.update(cfg, store, "Ana Li", title="x")


def test_a_fresh_linkedin_export_does_not_drop_them(cfg_store, connections):  # noqa: F811
    cfg, store = cfg_store
    referrals.add(cfg, store, "Rae Quinn", "Initech", "Designer")
    # a new Connections.csv written over the old one ...
    connections.write_text("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                           "Eve,Ng,https://www.linkedin.com/in/example-eve,,Initech,Architect,\n", encoding="utf-8")
    names = [p["name"] for p in watch.load_contacts(cfg).at("Initech")]
    assert names == ["Rae Quinn", "Eve Ng"] and "Ana Li" not in names
    # ... and one imported from LinkedIn's archive in the page's upload
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Connections.csv", "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                    "Fay,Ito,https://www.linkedin.com/in/example-fay,,Initech,Analyst,\n")
    contacts.import_archive(archive.getvalue(), connections.parent)
    assert [p["name"] for p in watch.load_contacts(cfg).at("Initech")] == ["Rae Quinn", "Fay Ito"]


def test_they_work_with_no_connections_file_at_all(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    assert watch.load_contacts(cfg) is None
    assert referrals.view(cfg, store)["has_connections"] is False
    watch.fetch_all(cfg, store)
    assert referrals.add(cfg, store, "Rae Quinn", "Initech")["tracked"]
    v = referrals.view(cfg, store)
    assert v["has_connections"] and [r["name"] for r in v["people"]] == ["Rae Quinn"] and v["people"][0]["jobs"]
    assert referrals.add(cfg, store, "Sam Ortiz", "Nowhere Labs")["tracked"] is False
    assert "Sam Ortiz" not in [r["name"] for r in referrals.view(cfg, store)["people"]]  # no job there yet
    store.close()


def test_cli_adds_lists_and_removes(web, watchlist, connections, capsys):  # noqa: F811
    add_connections(watchlist, connections)
    c = ["-c", str(watchlist)]
    cli.main([*c, "fetch"])
    capsys.readouterr()
    cli.main([*c, "referrals", "--add", "Rae Quinn", "--company", "Initech Inc.", "--title", "Designer",
              "--note", "met at a meetup", "--reach", "in person", "--email", "rae@example.com", "--phone", "555-0100"])
    assert "Added Rae Quinn at Initech Inc. (added by hand)." in capsys.readouterr().out
    cli.main([*c, "referrals"])
    out = capsys.readouterr().out
    assert "Rae Quinn (Designer), Initech Inc. [added by hand] - see in person; met at a meetup" in out
    assert "<rae@example.com, 555-0100>" in out and "Ana Li" in out
    cli.main([*c, "referrals", "--add", "Sam Ortiz", "--company", "Nowhere Labs"])
    assert "No job you track is at Nowhere Labs yet" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="Already in your connections: Ana Li"):
        cli.main([*c, "referrals", "--add", "Ana Li", "--company", "Initech"])
    with pytest.raises(SystemExit, match="needs --company"):
        cli.main([*c, "referrals", "--add", "Sam Ortiz"])
    with pytest.raises(SystemExit, match="only skipped"):
        cli.main([*c, "referrals", "--remove", "Ana Li"])
    cli.main([*c, "referrals", "--remove", "Rae Quinn"])
    assert "Removed Rae Quinn (Initech Inc.)." in capsys.readouterr().out
    cli.main([*c, "referrals", "--format", "json"])
    assert "Rae Quinn" not in {p["name"] for p in json.loads(capsys.readouterr().out)["people"]}


def test_the_page_routes_add_check_edit_and_remove(server, watchlist, connections):  # noqa: F811
    add_connections(watchlist, connections)
    ok = {"X-Jobwatch-Token": TOKEN}
    post = lambda path, body: request(server, "POST", "/api/referrals/" + path, body, headers=ok)  # noqa: E731
    request(server, "POST", "/api/fetch", {}, headers=ok)
    status, body = post("add", {"name": "Rae Quinn", "company": "Initech", "title": "Designer", "reach": "whatsapp"})
    added = json.loads(body)
    assert status == 200 and added["key"] == RAE and added["tracked"] and added["by_hand"] and added["added_at"]
    assert added["note"] == "reach on WhatsApp" and added["position"] == "Designer"
    status, body = post("add", {"name": "rae quinn", "company": "Initech Inc."})
    assert status == 409 and "Already added by hand: Rae Quinn" in json.loads(body)["error"]
    status, body = post("add", {"name": "Ana Li", "company": "Initech"})
    assert status == 409 and "Already in your connections" in json.loads(body)["error"]
    assert post("add", {"name": "", "company": "Initech"})[0] == 400
    assert post("add", {"name": "Sam Ortiz", "company": "Initech", "reach": "pigeon"})[0] == 400
    dup = json.loads(request(server, "GET", "/api/referrals/duplicate?name=Ana+Li&company=Initech", headers=ok)[1])
    assert dup == {"duplicate": {"name": "Ana Li", "company": "Initech, Inc.", "by_hand": False}}
    elsewhere = request(server, "GET", "/api/referrals/duplicate?name=Ana+Li&company=Globex", headers=ok)[1]
    assert json.loads(elsewhere) == {"duplicate": None}
    v = json.loads(request(server, "GET", "/api/referrals", headers=ok)[1])
    assert "Rae Quinn" in {p["name"] for p in v["people"]}
    status, body = post("person", {"who": RAE, "title": "Staff Designer", "note": "met at a meetup"})
    edited = json.loads(body)
    assert status == 200 and edited["position"] == "Staff Designer"
    assert edited["note"] == "reach on WhatsApp; met at a meetup" and edited["added_at"] == added["added_at"]
    assert post("person", {"who": ANA, "title": "x"})[0] == 400
    assert post("remove", {"who": ANA})[0] == 400
    status, body = post("remove", {"who": RAE})
    gone = json.loads(body)
    assert status == 200 and gone["name"] == "Rae Quinn"
    # Undo puts them back as they were, on the day they were added
    status, body = post("add", {"name": gone["name"], "company": gone["company"], "title": gone["position"],
                                "note": gone["about"], "reach": gone["reach"], "added_at": gone["added_at"]})
    assert status == 200 and json.loads(body)["added_at"] == added["added_at"]
    assert post("remove", {"who": "Nobody"})[0] == 400


def test_the_tools_add_and_remove_a_contact(web, watchlist, connections, monkeypatch):  # noqa: F811
    mcp = pytest.importorskip("jobwatch.mcp_server")
    add_connections(watchlist, connections)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    got = mcp.add_contact("Rae Quinn", "Globex Corporation", note="met at a meetup", reach="text")
    assert got["name"] == "Rae Quinn" and got["note"] == "reach by text; met at a meetup" and got["tracked"] is False
    assert got["position"] == "" and got["email"] == "" and got["added_at"]
    assert mcp.rate_contact("Rae Quinn", "use")["verdict"] == "use"
    with pytest.raises(mcp.ToolError, match="Already added by hand"):
        mcp.add_contact("Rae Quinn", "Globex")
    with pytest.raises(mcp.ToolError, match="Already in your connections"):
        mcp.add_contact("Cy Diaz", "Globex")
    with pytest.raises(mcp.ToolError, match="only skipped"):
        mcp.remove_contact("Cy Diaz")
    assert mcp.remove_contact("Rae Quinn") == {"name": "Rae Quinn", "company": "Globex Corporation"}
    with pytest.raises(mcp.ToolError, match="no connection matches"):
        mcp.remove_contact("Rae Quinn")
