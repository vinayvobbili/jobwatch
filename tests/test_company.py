"""Looking up a company across every tab: matched by name or domain, under any status, closed postings too."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jobwatch import cli, company, config
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import TOKEN, request

CONNECTIONS = """First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ana,Li,https://www.linkedin.com/in/example-ana,,Acme Robotics,Staff Engineer,02 Mar 2024
"""


@pytest.fixture
def cfg(watchlist):
    return config.load(watchlist)


@pytest.fixture
def store(cfg):
    s = Store(cfg.state)
    yield s
    s.close()


def board_job(id_, title, company_="Globex", source="lever", board="globex", **kw):
    return Job(source=source, company=board, id=id_, title=title, url=f"https://jobs.example/{board}/{id_}",
               company_name=company_, posted=datetime(2026, 9, 1, tzinfo=timezone.utc), **kw)


@pytest.fixture
def tracked(store):
    """Acme Robotics: one interview by hand, one skipped, one closed posting never acted on. Globex: two open
    roles on its watched board. Hooli: an application whose board isn't watched."""
    store.add("Acme Robotics", "Perception Engineer", status="interviewing", applied="2026-09-10",
              note="phone screen done", next_step="onsite", follow_up="2026-10-20")
    skipped = store.add("Acme Robotics", "Sales Lead", status="skipped")
    store.sync("lever", "globex", [board_job("g1", "Platform Engineer"), board_job("g2", "Data Engineer")])
    store.sync("lever", "acme", [board_job("a1", "Old Role", "Acme Robotics", board="acme")])
    store.sync("lever", "acme", [])  # closes it
    store.add("Hooli Inc", "Staff Engineer", status="applied", applied="2026-09-01")
    return skipped


# -- matching

@pytest.mark.parametrize("text, key", [
    ("Acme Robotics, Inc.", "acmerobotics"), ("acme robotics", "acmerobotics"), ("ACME-ROBOTICS", "acmerobotics"),
    ("acme.com", "acme"), ("https://www.acme.com/careers", "acme"), ("jobs.acme.co.uk", "acme"),
    ("Acme Inc", "acme"), ("  acme ", "acme"),
])
def test_a_search_is_set_aside_like_a_company_name(text, key):
    assert company.query_key(text) == key


def test_search_finds_a_company_under_any_status_and_ranks_the_exact_name_first(store, tracked):
    store.add("Acme", "Designer", status="queued")
    names = [c["name"] for c in company.search(store, "acme")]
    assert names == ["Acme", "Acme Robotics"]  # the same name, then one that starts with it
    robotics = company.search(store, "Acme Robotics Inc")[0]
    assert robotics["name"] == "Acme Robotics" and robotics["exact"]
    assert (robotics["applications"], robotics["skipped"], robotics["open"], robotics["jobs"]) == (1, 1, 0, 3)
    assert [c["name"] for c in company.search(store, "robotics")] == ["Acme Robotics"]  # part of a name
    assert [c["name"] for c in company.search(store, "hooli.com")] == ["Hooli Inc"]  # a domain
    assert company.search(store, "globex")[0]["open"] == 2  # roles on a board, not acted on
    assert company.search(store, "a") == [] and company.search(store, "nobody") == []


def test_a_board_name_finds_its_company(store):
    store.sync("greenhouse", "initech", [board_job("i1", "Support Engineer", "", source="greenhouse",
                                                   board="initech")])
    assert [c["name"] for c in company.search(store, "initech")] == ["initech"]


# -- the view

def test_view_lists_every_status_with_dates_and_next_steps(cfg, store, tracked):
    v = company.view(cfg, store, "acme.com")
    assert v["company"] == "Acme Robotics" and v["also"] == []
    assert v["counts"] == {"interviewing": 1, "skipped": 1}
    assert [j["status"] for j in v["jobs"]] == ["interviewing", "skipped"]
    first = v["jobs"][0]
    assert (first["title"], first["applied_at"], first["next_step"], first["follow_up"], first["note"]) == (
        "Perception Engineer", "2026-09-10", "onsite", "2026-10-20", "phone screen done")
    assert v["closed_unacted"] == 1 and v["more_open"] == 0  # the closed posting nobody acted on is counted only
    assert v["watch"]["watched"] is False and v["watch"]["add_board"] == {
        "entry": "lever:acme", "name": "Acme Robotics"}


def test_view_of_an_unknown_company_is_none(cfg, store, tracked):
    assert company.view(cfg, store, "nobody") is None
    assert "No tracked job" in company.text(None, "nobody")


def test_a_watched_board_has_no_hint_and_lists_its_open_roles(cfg, store, tracked):
    v = company.view(cfg, store, "globex")
    assert v["watch"] == {"watched": True, "entry": None, "command": None, "add_board": None, "careers": None,
                          "suggested": False}
    assert sorted(j["title"] for j in v["jobs"]) == ["Data Engineer", "Platform Engineer"]
    assert {j["status"] for j in v["jobs"]} == {"new"} and v["jobs"][0]["posted"] == "2026-09-01"


def test_open_roles_not_acted_on_are_capped(cfg, store, monkeypatch):
    monkeypatch.setattr(company, "OPEN_SHOWN", 2)
    store.sync("lever", "globex", [board_job(f"g{i}", f"Engineer {i}") for i in range(5)])
    v = company.view(cfg, store, "globex")
    assert len(v["jobs"]) == 2 and v["more_open"] == 3


def test_open_roles_the_title_filters_leave_out_are_only_counted(watchlist, store):
    """A big board (a pharmacy chain's) lists nurses next to engineers: only the titles you'd look at show, but a
    role you acted on shows whatever its title."""
    watchlist.write_text(watchlist.read_text().replace("filters:\n", "filters:\n  titles: [engineer]\n"))
    cfg = config.load(watchlist)
    store.sync("lever", "globex", [board_job("g1", "Staff Engineer"), board_job("g2", "Registered Nurse"),
                                   board_job("g3", "Case Manager Nurse"), board_job("g4", "Store Manager")])
    store.set_status(["lever:globex:g4"], "skipped")
    v = company.view(cfg, store, "globex")
    assert sorted(j["title"] for j in v["jobs"]) == ["Staff Engineer", "Store Manager"]
    assert v["off_title"] == 2 and v["more_open"] == 0 and v["counts"] == {"new": 1, "skipped": 1}
    assert "2 open roles your title filters leave out not listed" in company.text(v, "globex")


def test_an_unwatched_board_says_what_to_add(cfg, store):
    store.sync("greenhouse", "umbrella", [board_job("u1", "Analyst", "Umbrella", source="greenhouse",
                                                    board="umbrella")])
    store.set_status(["greenhouse:umbrella:u1"], "queued")
    w = company.view(cfg, store, "umbrella")["watch"]
    assert w["add_board"] == {"entry": "greenhouse:umbrella", "name": "Umbrella"}
    assert w["watched"] is False and w["careers"] and "find" in w["command"]


def test_a_package_a_duplicate_and_contacts_show_up(cfg, store, tracked, tmp_path, watchlist):
    job, _ = store.find("acme-robotics:perception-engineer")
    store.package(job.key).write(note="cover letter")
    store.add("Acme Robotics", "Perception Engineer (Remote)", status="queued")
    (tmp_path / "Connections.csv").write_text(CONNECTIONS, encoding="utf-8")
    watchlist.write_text(watchlist.read_text() + "connections: Connections.csv\n")
    v = company.view(config.load(watchlist), store, "acme robotics")
    by_key = {j["key"]: j for j in v["jobs"]}
    assert by_key[job.key]["has_package"] and by_key[job.key]["package"]["note"]
    queued = next(j for j in v["jobs"] if j["status"] == "queued")
    assert queued["duplicate_of"]["key"] == job.key and not queued["has_package"]
    assert [p["name"] for p in v["contacts"]] == ["Ana Li"]


def test_text_reads_well(cfg, store, tracked):
    out = company.text(company.view(cfg, store, "acme"), "acme")
    assert out.startswith("# Acme Robotics\n2 jobs: 1 interviewing, 1 skipped.")
    assert "applied 2026-09-10" in out and "Next: onsite · follow up 2026-10-20" in out
    assert "Note: phone screen done" in out and "1 closed posting you never acted on not listed" in out
    assert "Not watched" in out and "Find someone who could refer you" in out


def test_text_words_a_follow_up_like_the_rest(cfg, store, tracked):
    job = company.view(cfg, store, "acme")["jobs"][0]

    def lines(**changes):
        return company._line({**job, **changes})

    assert "    Next: onsite · follow up 2026-10-20" in lines(due=False)
    assert "    Due: onsite · follow up 2026-10-20" in lines(due=True)
    assert "    Next: follow up 2026-10-20" in lines(next_step=None)
    assert "    Next: onsite" in lines(follow_up=None) and "    Next: onsite by" not in lines(follow_up=None)


def test_text_shows_a_compact_note_and_json_keeps_all_of_it(cfg, store, tracked):
    key = store.find("acme-robotics:perception-engineer")[0].key
    store.add_note(key, "2026-09-12: recruiter called, " + "long story " * 60)
    store.add_note(key, "2026-10-01: asked for availability " + "x" * 400)
    v = company.view(cfg, store, "acme")
    out = company.text(v, "acme")
    note = next(line for line in out.splitlines() if line.startswith("    Note:"))
    assert "2026-10-01: asked for availability" in note and "phone screen done" not in note
    assert "long story" not in note and "…" in note and len(note) < 330
    assert f"`jobwatch show {key}`" in note and "--format json" in note
    full = next(j["note"] for j in v["jobs"] if j["key"] == key)
    assert "phone screen done" in full and "long story" in full and "2026-10-01" in full  # JSON stays whole


def test_a_short_note_prints_whole_and_a_single_long_one_is_cut(cfg, store, tracked):
    assert company.note_preview("phone screen done") == ("phone screen done", False)
    assert company.note_preview("2026-09-01: a. 2026-09-02: b") == ("2026-09-02: b", True)
    shown, cut = company.note_preview("word " * 100)
    assert cut and len(shown) == company.NOTE_SHOWN and shown.endswith("…")


# -- the command, the MCP tool and the page

def test_company_command(watchlist, tracked, capsys):
    cli.main(["-c", str(watchlist), "company", "Acme", "Robotics"])
    assert "# Acme Robotics" in capsys.readouterr().out
    cli.main(["-c", str(watchlist), "company", "hooli.com", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["company"] == "Hooli Inc" and data["jobs"][0]["status"] == "applied"
    cli.main(["-c", str(watchlist), "company", "nobody"])
    assert "No tracked job is at a company matching 'nobody'" in capsys.readouterr().out


def test_get_company_tool(watchlist, tracked, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    ToolError = pytest.importorskip("mcp.server.mcpserver.exceptions").ToolError
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    v = mcp.get_company("acme")
    assert v["company"] == "Acme Robotics" and v["jobs"][0]["status"] == "interviewing"
    with pytest.raises(ToolError, match="no tracked job"):
        mcp.get_company("nobody")
    assert "get_company" in {t.name for t in asyncio.run(mcp.server.list_tools())}


def test_get_company_says_why_when_no_company_matches(watchlist, tracked, monkeypatch):
    """The server hands a client the text of a ToolError only: any other exception reached it as a bare "Error
    executing tool get_company"."""
    mcp = pytest.importorskip("jobwatch.mcp_server")
    errors = pytest.importorskip("mcp.server.mcpserver.exceptions")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    with pytest.raises(errors.ToolError) as e:
        asyncio.run(mcp.server.call_tool("get_company", {"name": "Nobody"}))
    assert str(e.value) == "Error executing tool get_company: no tracked job is at a company matching 'Nobody'"
    assert not isinstance(e.value, errors.UnexpectedToolError)


def test_company_endpoints(server, watchlist, tracked):
    status, body = request(server, "GET", "/api/companies?q=acm", headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and next(c["name"] for c in json.loads(body)) == "Acme Robotics"
    status, body = request(server, "GET", "/api/company?q=acme%20robotics", headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and json.loads(body)["jobs"][0]["title"] == "Perception Engineer"
    status, body = request(server, "GET", "/api/company?q=nobody", headers={"X-Jobwatch-Token": TOKEN})
    assert status == 404 and "no tracked job" in json.loads(body)["error"]
    assert request(server, "GET", "/api/company?q=acme")[0] in (401, 403)  # needs the page's token


def test_page_has_the_company_search(server):
    """A search box in the header on every tab, focused by `/`, and a hint where a tab's own search finds nothing."""
    page = request(server, "GET", "/")[1].decode()
    assert 'id="jump"' in page and 'e.key !== "/"' in page and "function openCompany(" in page
    assert 'api("/api/companies?q="' in page and 'api("/api/company?q="' in page
    assert "elsewhere(v.q)" in page and "elsewhere(appView.q)" in page
