"""Looking up a company across every tab: matched by name or domain, under any status, closed postings too."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from jobwatch import cli, company, config
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import TOKEN, request

FOLLOW_UP = (date.today() + timedelta(days=30)).isoformat()  # ahead of today, whenever the tests run

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


def ago(days):
    """A posting date relative to today: a role a board lists for the first time more than a fortnight after it was
    posted is taken as reposted today (Store.sync), so fixed dates in a test go stale."""
    return (datetime.now(UTC) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def board_job(id_, title, company_="Globex", source="lever", board="globex", **kw):
    kw.setdefault("locations", ["Denver, CO"])  # one of the test watchlist's places
    kw.setdefault("posted", ago(5))
    return Job(source=source, company=board, id=id_, title=title, url=f"https://jobs.example/{board}/{id_}",
               company_name=company_, **kw)


@pytest.fixture
def tracked(store):
    """Acme Robotics: one interview by hand, one skipped, one closed posting never acted on. Globex: two open
    roles on its watched board. Hooli: an application whose board isn't watched."""
    store.add("Acme Robotics", "Perception Engineer", status="interviewing", applied="2026-09-10",
              note="phone screen done", next_step="onsite", follow_up=FOLLOW_UP)
    skipped = store.add("Acme Robotics", "Sales Lead", status="skipped")
    store.sync("lever", "globex", [board_job("g1", "Platform Engineer"), board_job("g2", "Data Engineer")])
    [old] = store.sync("lever", "acme", [board_job("a1", "Old Role", "Acme Robotics", board="acme")])
    store.set_closed(old, True)  # its posting closed
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
        "Perception Engineer", "2026-09-10", "onsite", FOLLOW_UP, "phone screen done")
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
    assert {j["status"] for j in v["jobs"]} == {"new"} and v["jobs"][0]["posted"] == ago(5).date().isoformat()


def test_open_roles_not_acted_on_list_the_latest_posting_first(cfg, store):
    """A board's roles all arrive together when it's first watched, so the order they came says nothing."""
    store.sync("lever", "globex", [
        board_job("g1", "Platform Engineer", posted=datetime(2025, 2, 20, tzinfo=UTC)),
        board_job("g2", "Data Engineer", posted=ago(3)),
        board_job("g3", "Site Reliability Engineer", posted=None),
        board_job("g4", "ML Engineer", posted=ago(10))])
    v = company.view(cfg, store, "globex", every=True)
    assert [j["title"] for j in v["jobs"]] == ["Data Engineer", "ML Engineer", "Platform Engineer",
                                              "Site Reliability Engineer"]
    cfg.focus = [r"\bml\b", "reliability"]  # the work wanted most leads, latest first within it
    v = company.view(cfg, store, "globex", every=True)
    assert [j["title"] for j in v["jobs"]] == ["ML Engineer", "Site Reliability Engineer", "Data Engineer",
                                              "Platform Engineer"]


def test_open_roles_not_acted_on_are_capped(cfg, store, monkeypatch):
    monkeypatch.setattr(company, "OPEN_SHOWN", 2)
    store.sync("lever", "globex", [board_job(f"g{i}", f"Engineer {i}") for i in range(5)])
    v = company.view(cfg, store, "globex")
    assert len(v["jobs"]) == 2 and v["more_open"] == 3


def test_open_roles_the_filters_leave_out_are_only_counted(watchlist, store):
    """A big board (a pharmacy chain's) lists nurses next to engineers: only the titles you'd look at show, but a
    role you acted on shows whatever its title."""
    watchlist.write_text(watchlist.read_text().replace("filters:\n", "filters:\n  titles: [engineer]\n"))
    cfg = config.load(watchlist)
    store.sync("lever", "globex", [board_job("g1", "Staff Engineer"), board_job("g2", "Registered Nurse"),
                                   board_job("g3", "Case Manager Nurse"), board_job("g4", "Store Manager")])
    store.set_status(["lever:globex:g4"], "skipped")
    v = company.view(cfg, store, "globex")
    assert sorted(j["title"] for j in v["jobs"]) == ["Staff Engineer", "Store Manager"]
    assert v["left_out"] == 2 and v["left_out_by"] == {"title": 2} and v["more_open"] == 0
    assert v["counts"] == {"new": 1, "skipped": 1}
    assert "2 open roles your filters leave out (title 2) not listed: --all lists them" in company.text(v, "globex")


def test_roles_in_other_places_or_below_the_pay_are_left_out_but_not_old_ones(cfg, store):
    """Roles elsewhere or under min_salary aren't listed, the way Today hides them; an old posting still open is."""
    cfg.filters.min_salary = 150_000
    store.sync("lever", "globex", [board_job("g1", "Staff Engineer"),
                                   board_job("g2", "Network Engineer", locations=["Omaha, NE"]),
                                   board_job("g3", "Data Engineer", salary_min=90_000, salary_max=120_000),
                                   board_job("g4", "Old Engineer", posted=datetime(2025, 1, 1, tzinfo=UTC))])
    v = company.view(cfg, store, "globex")
    assert sorted(j["title"] for j in v["jobs"]) == ["Old Engineer", "Staff Engineer"]
    assert v["left_out_by"] == {"place": 1, "pay": 1} and v["every"] is False


def test_a_role_with_a_note_or_follow_up_shows_though_the_filters_leave_it_out(cfg, store):
    """A posting that dropped your city while you wait to hear from a referrer: you're still keeping an eye on it."""
    store.sync("lever", "globex", [board_job("g1", "Staff Engineer", locations=["Omaha, NE"]),
                                   board_job("g2", "Data Engineer", locations=["Omaha, NE"])])
    store.track("lever:globex:g1", next_step="hear back from the referrer", follow_up="2026-10-22")
    v = company.view(cfg, store, "globex")
    assert [j["title"] for j in v["jobs"]] == ["Staff Engineer"] and v["left_out_by"] == {"place": 1}


@pytest.mark.parametrize("setting, every, listed", [
    ("matches", None, 1), ("matches", True, 2), ("all", None, 2), ("all", False, 1),
])
def test_display_company_or_every_lists_the_roles_left_out(cfg, store, setting, every, listed):
    cfg.company_view = setting
    store.sync("lever", "globex", [board_job("g1", "Staff Engineer"),
                                   board_job("g2", "Staff Engineer II", locations=["Omaha, NE"])])
    v = company.view(cfg, store, "globex", every)
    assert len(v["jobs"]) == listed and v["left_out"] == 2 - listed


def test_display_company_must_be_a_known_view(watchlist):
    watchlist.write_text(watchlist.read_text() + "display:\n  company: everything\n")
    with pytest.raises(config.ConfigError, match=r"display\.company must be one of matches, all"):
        config.load(watchlist)
    watchlist.write_text(watchlist.read_text().replace("everything", "all"))
    assert config.load(watchlist).company_view == "all"


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
    assert "applied 2026-09-10" in out and f"Next: onsite · follow up {FOLLOW_UP}" in out
    assert "Note: phone screen done" in out and "1 closed posting you never acted on not listed" in out
    assert "Not watched" in out and "Find someone who could refer you" in out


def test_text_words_a_follow_up_like_the_rest(cfg, store, tracked):
    job = company.view(cfg, store, "acme")["jobs"][0]

    def lines(**changes):
        return company._line({**job, **changes})

    assert f"    Next: onsite · follow up {FOLLOW_UP}" in lines(due=False)
    assert f"    Due: onsite · follow up {FOLLOW_UP}" in lines(due=True)
    assert f"    Next: follow up {FOLLOW_UP}" in lines(next_step=None)
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
    assert note.endswith(f"(all of it: `jobwatch show {key}`)")  # one command that runs as written
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


def test_a_name_finds_its_company_however_the_ampersand_is_written(cfg, store, watchlist, monkeypatch):
    """Pied & Piper keys as "piedandpiper": "Pied Piper" and "Pied and Piper" find it too, in search, view and the
    get_company tool, and for the reverse, a company stored as "Globex and Sons" is found by "Globex & Sons"."""
    store.add("Pied & Piper", "Compression Engineer", status="applied", applied="2026-09-01")
    store.add("Initech", "Support Engineer", status="queued")
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    for asked in ("Pied & Piper", "pied piper", "Pied and Piper", "PIED-PIPER", "pied  &  piper"):
        assert [c["name"] for c in company.search(store, asked)] == ["Pied & Piper"], asked
        assert company.view(cfg, store, asked)["jobs"][0]["title"] == "Compression Engineer"
        assert mcp.get_company(asked)["company"] == "Pied & Piper"
    store.add("Globex and Sons", "Designer", status="queued")
    assert [c["name"] for c in company.search(store, "Globex & Sons")] == ["Globex and Sons"]
    assert [c["name"] for c in company.search(store, "globex sons")] == ["Globex and Sons"]


def test_a_looser_spelling_does_not_merge_or_invent_companies(cfg, store):
    store.add("Pied & Piper", "Compression Engineer", status="applied", applied="2026-09-01")
    store.add("Pied Piper Labs", "Analyst", status="applied", applied="2026-09-02")
    store.add("Initech", "Support Engineer", status="queued")
    assert company.search(store, "pied piper")[0]["name"] == "Pied & Piper"  # the same name first
    assert company.search(store, "Initech Globex") == []
    assert company.view(cfg, store, "pied piper")["counts"] == {"applied": 1}  # Labs stays a different company
    assert company.view(cfg, store, "Pied Pipers") is None


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


def test_a_company_is_read_from_its_boards_not_the_whole_table(store, cfg):
    """view() used to parse every job to find a company's: now it reads the boards the company's jobs are on, in
    the order the whole-table read gave (newest first seen, a tie in the order recorded)."""
    store.sync("lever", "globex", [board_job(str(i), f"Role {i}") for i in range(5)])           # one first_seen
    store.sync("greenhouse", "globex", [board_job(str(i), f"Role {i}", source="greenhouse") for i in range(3)])
    store.sync("lever", "globex-eu", [board_job("e1", "EU role", board="globex-eu", company_="Globex")])
    store.sync("lever", "initech", [board_job("i1", "Other", "Initech", board="initech")])
    store.add("Globex", "Hand-added role", status="applied")
    store.set_status(["lever:globex:3"], "queued")
    groups = company._groups(store)
    assert len(groups["globex"]["boards"]) == 4 and groups["initech"]["boards"] == {("lever", "initech")}
    for key, g in groups.items():
        old = [(j.key, r["status"], r["first_seen"]) for j, r in store.iter_jobs(include_closed=True)
               if company.dupes.company_key(j.display_company) == key]
        new = [(j.key, r["status"], r["first_seen"]) for j, r in store.board_rows(g["boards"])
               if company.dupes.company_key(j.display_company) == key]
        assert new == old and new, key
    seen = []
    store.db.set_trace_callback(seen.append)
    got = company.view(cfg, store, "globex", every=True)
    assert got["company"] == "Globex" and len(got["jobs"]) == 10
    # no statement reads every job's text: the whole-table read had no status in it (`... WHERE 1=1 ORDER BY ...`)
    assert not [s for s in seen if "WHERE 1=1" in s and "status IN" not in s]


def test_the_company_groups_are_kept_until_a_write(store):
    store.sync("lever", "globex", [board_job("1", "Role")])
    seen = []
    store.db.set_trace_callback(seen.append)
    company.search(store, "globex")
    company.search(store, "glob")
    assert len([s for s in seen if "GROUP BY source" in s]) == 1
    store.sync("lever", "globex", [board_job("1", "Role"), board_job("2", "Another")])
    assert company.search(store, "globex")[0]["jobs"] == 2
    assert len([s for s in seen if "GROUP BY source" in s]) == 2


def test_page_has_the_company_search(server):
    """A search box at the top of the Company tab, reached by `/` from any tab, and a hint where a tab's own search
    finds nothing."""
    page = request(server, "GET", "/")[1].decode()
    assert 'id: "jump"' in page and 'e.key !== "/"' in page and "function openCompany(" in page
    assert 'class="jump"' not in page.split("<script")[0]  # not in the header
    assert 'pagehead("Company", sub, jumpBox)' in page
    assert 'api("/api/companies?q="' in page and 'api("/api/company?q="' in page
    assert "elsewhere(v.q)" in page and "elsewhere(appView.q)" in page


# -- the posting text search

def test_a_term_is_a_whole_word_and_capitals_match_in_capitals_only():
    itar, us, ear = (company.term_pattern(t) for t in ("ITAR", "U.S. Person", "EAR"))
    assert itar.search("Work is subject to ITAR rules") and not itar.search("a military role")
    assert us.search("All applicants must be u.s.   persons") and not us.search("U.S. Personnel")
    assert ear.search("subject to the EAR.") and not ear.search("a good ear for music")


def test_posting_hits_lists_the_jobs_whose_text_holds_a_term(store, tracked):
    store.sync("lever", "globex", [
        board_job("g3", "Export Engineer", description="All applicants must be U.S. Persons under ITAR."),
        board_job("g4", "Army Liaison", description="Support our military customers."),
        board_job("g5", "Closed Role", description="Subject to ITAR.")])
    closed = "lever:globex:g5"
    store.set_closed(closed, True)
    assert {j["id"] for j in company.posting_hits(store, "globex", ["ITAR"])["jobs"]} == {"g3", "g5"}  # one look
    store.confirm_closed([closed])
    v = company.posting_hits(store, "globex", ["ITAR", "U.S. Person"])
    assert [j["title"] for j in v["jobs"]] == ["Export Engineer"] and v["scanned"] == 4
    assert company.posting_hits(store, "globex", ["ITAR"], include_closed=True)["scanned"] == 5
    store.set_closed("lever:globex:g4", True)  # marked once only
    only = company.posting_hits(store, "globex", ["ITAR"], only_open=True)
    assert [j["id"] for j in only["jobs"]] == ["g3"] and only["scanned"] == 1  # the sync closed g1 and g2 once
    assert [m["term"] for m in v["jobs"][0]["matches"]] == ["ITAR", "U.S. Person"]
    assert "ITAR" in v["jobs"][0]["matches"][0]["snippet"] and v["jobs"][0]["first_seen"]
    assert company.posting_hits(store, "nobody", ["ITAR"]) is None
    with pytest.raises(ValueError, match="at least one term"):
        company.posting_hits(store, "globex", [" "])


def test_posting_hits_counts_a_job_with_no_kept_text(store, tracked):
    store.sync("lever", "globex", [board_job("g3", "Export Engineer", description="Subject to ITAR.")])
    v = company.posting_hits(store, "globex", ["ITAR"])
    assert v["no_text"] == 2 and v["scanned"] == 3  # the two roles of the fixture have none


def test_posting_hits_live_reads_the_page_and_says_what_the_kept_text_lacked(store, tracked):
    store.sync("lever", "globex", [
        board_job("g3", "Export Engineer", description="A plain role."),
        board_job("g4", "Gone Role", description="Subject to ITAR.")])
    pages = {"g3": "A plain role. All applicants must be U.S. Persons under ITAR."}
    v = company.posting_hits(store, "globex", ["ITAR"], only_open=True,
                             live=lambda job: pages.get(job.id, ""))
    by_id = {j["id"]: j for j in v["jobs"]}
    assert set(by_id) == {"g3", "g4"} and v["live"] and v["unreadable"] == ["lever:globex:g4"]
    assert by_id["g3"]["read"] == "live" and by_id["g3"]["in_saved"] == []
    assert by_id["g4"]["read"].startswith("saved") and by_id["g4"]["in_saved"] == ["ITAR"]
    assert "Read: live; the kept text has: none of them" in company.posting_hits_text(v, "globex")


def test_live_text_is_empty_when_the_page_cannot_be_read(monkeypatch):
    job = board_job("g3", "Export Engineer")

    def gone(url, get=None):
        raise company.sources.SourceError("no longer lists the job")
    monkeypatch.setattr(company.sources, "posting", gone)
    assert company.live_text(job) == ""
    monkeypatch.setattr(company.sources, "posting", lambda url, get=None: board_job("g3", "x", description="Hi"))
    assert company.live_text(job) == "Hi"


def test_grep_command(watchlist, store, tracked, capsys):
    store.sync("lever", "globex", [board_job("g3", "Export Engineer", description="Subject to ITAR.")])
    cli.main(["-c", str(watchlist), "grep", "Globex", "-t", "ITAR"])
    out = capsys.readouterr().out
    assert "1 of 3 jobs read name ITAR" in out and "Export Engineer" in out and "Found 'ITAR'" in out
    cli.main(["-c", str(watchlist), "grep", "globex", "-t", "ITAR", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["jobs"][0]["id"] == "g3"
    cli.main(["-c", str(watchlist), "grep", "nobody", "-t", "ITAR"])
    assert "No tracked job is at a company matching 'nobody'" in capsys.readouterr().out
