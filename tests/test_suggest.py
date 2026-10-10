"""Companies to watch: noted from alert imports and `add` when their board isn't watched, ranked by matching jobs
(recent ones counting more), each board looked for once, accepted onto the watchlist or dismissed. No network: the
boards are canned (the `web` fixture)."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import cli, config, suggest
from jobwatch.store import Store
from jobwatch.watch import save_job
from jobwatch.web import App

from .conftest import TOKEN, iso, request
from .test_alerts import FIXTURES, take

UMBRELLA = "https://boards-api.greenhouse.io/v1/boards/umbrella/jobs?content=true"
HOOLI = "https://api.lever.co/v0/postings/hooli?mode=json"


def umbrella_board(web):
    """Umbrella's own Greenhouse board, not on the watchlist, with the job its LinkedIn alert is for."""
    web.responses[UMBRELLA] = {"jobs": [{
        "id": 501, "title": "Field Engineer", "company_name": "Umbrella",
        "absolute_url": "https://job-boards.greenhouse.io/umbrella/jobs/501",
        "location": {"name": "Remote, United States"}, "offices": [], "metadata": [], "departments": [],
        "first_published": iso(2), "content": "&lt;p&gt;Keep the field kit running. Python.&lt;/p&gt;"}]}


def hooli_board(web):
    web.responses[HOOLI] = [{
        "id": "h-1", "text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/hooli/h-1",
        "categories": {"location": "Remote (United States)", "allLocations": ["Remote (United States)"]},
        "workplaceType": "remote", "descriptionPlain": "Python services.", "lists": []}]


def added(cfg, store, company, title, location="Remote"):
    """A job added by hand (`jobwatch add <company> <title>`), the way the CLI, MCP and page add one."""
    return save_job(store, company=company, title=title, status="queued", location=location, boards=cfg.boards)[0]


def came_in(store, key, days_ago):
    store.db.execute("UPDATE unwatched_jobs SET seen_at=? WHERE key=?",
                     ((datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(), key))
    store.db.commit()


def rows(store):
    return {r["company"]: r for r in store.unwatched(dismissed=True)}


# -- Recording

def test_alert_imports_note_unwatched_companies(web, watchlist):
    umbrella_board(web)
    cfg, store, _, _ = take(watchlist, ["linkedin.eml", "builtin.eml", "indeed.eml"])
    got = rows(store)
    assert set(got) == {"umbrella", "hooli", "vandelayindustries"}  # Acme, Globex and Initech are watched
    # The alert's job matched on Umbrella's own board: that board is kept, as the one its jobs are on
    assert (got["umbrella"]["entry"], got["umbrella"]["found_by"]) == ("greenhouse:umbrella", "posting")
    assert [j.key for j, _ in got["umbrella"]["jobs"]] == ["greenhouse:umbrella:501"]
    # Hooli was looked for while importing and nothing was found: kept, so it's not looked for again
    assert (got["hooli"]["entry"], got["hooli"]["found_by"]) == ("", None)
    # Vandelay's job failed the filters, so nothing was looked for
    assert got["vandelayindustries"]["entry"] is None
    assert {s.name for s in suggest.suggestions(cfg, store)} == {"Umbrella", "Hooli"}  # Vandelay's doesn't match


def test_a_dry_run_or_no_follow_import(web, watchlist):
    _, store, _, _ = take(watchlist, ["linkedin.eml"], dry_run=True)
    assert rows(store) == {}
    web.calls.clear()
    _, store, _, pages = take(watchlist, ["linkedin.eml", "indeed.eml"], follow=False)
    assert web.calls == [] and pages.calls == []
    assert {c: r["entry"] for c, r in rows(store).items()} == {"umbrella": None, "vandelayindustries": None}


def test_add_notes_the_company_too(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Initech", "Staff Engineer")  # watched: not noted
    job = added(cfg, store, "Hooli, Inc.", "Platform Engineer")
    assert rows(store)["hooli"]["name"] == "Hooli, Inc." and rows(store)["hooli"]["entry"] is None
    assert [j.key for j, _ in rows(store)["hooli"]["jobs"]] == [job.key]


def test_a_better_board_find_wins(watchlist, tmp_path):
    store = Store(tmp_path / "s.db")
    store.note_unwatched("hooli", "Hooli", "manual:hooli:a", "", None)
    store.set_unwatched_board("hooli", "lever:hooli", "name")       # found by name beats none found
    store.set_unwatched_board("hooli", "ashby:hooli2", "name")      # no better: kept as it was
    assert rows(store)["hooli"]["entry"] == "lever:hooli"
    store.set_unwatched_board("hooli", "greenhouse:hooli", "posting")  # a job is there: best
    store.set_unwatched_board("hooli", "", None)
    assert (rows(store)["hooli"]["entry"], rows(store)["hooli"]["found_by"]) == ("greenhouse:hooli", "posting")


# -- Ranking

def test_ranked_by_matching_jobs_recent_ones_counting_more(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    for title in ("Platform Engineer", "Data Engineer"):
        added(cfg, store, "Umbrella", title)
    old = [added(cfg, store, "Hooli", t) for t in ("Engineer I", "Engineer II", "Engineer III")]
    added(cfg, store, "Vandelay Industries", "Python Developer")
    added(cfg, store, "Vandelay Industries", "Python Developer (Contract)")  # fails the filters: doesn't count
    added(cfg, store, "Wayne Enterprises", "Engineer", location="London")    # every job filtered out: not listed
    for j in old:
        came_in(store, j.key, 120)
    found = suggest.suggestions(cfg, store)
    assert [(s.name, len(s.jobs)) for s in found] == [("Umbrella", 2), ("Vandelay Industries", 1), ("Hooli", 3)]
    assert found[0].sample_titles == ["Data Engineer", "Platform Engineer"]  # newest first
    assert suggest.suggestions(cfg, store, limit=1)[0].name == "Umbrella"
    d = found[1].to_dict()
    assert d["command"] == "jobwatch suggest --add 'Vandelay Industries'" and d["board"] is None
    assert d["looked_up"] is False and d["add_board"] is None


def test_watched_ones_drop_out(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    assert [s.name for s in suggest.suggestions(cfg, store)] == ["Hooli"]
    cfg = config.add_board(watchlist, "lever:hooli")  # watched now, under its own name
    assert suggest.suggestions(cfg, store) == []


# -- Looking for boards

def test_each_board_is_looked_for_once(web, watchlist):
    hooli_board(web)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Vandelay Industries", "Python Developer")
    assert all(s.entry is None for s in suggest.suggestions(cfg, store))  # nothing looked for unless asked
    web.calls.clear()
    found = {s.name: s.to_dict() for s in suggest.suggestions(cfg, store, look=True)}
    assert found["Hooli"]["board"] == "lever:hooli" and found["Hooli"]["board_found"] == "name"
    assert found["Hooli"]["add_board"] == {"entry": "lever:hooli", "name": "Hooli"}
    assert found["Hooli"]["careers"] == "https://jobs.lever.co/hooli"
    assert found["Vandelay Industries"]["board"] is None and found["Vandelay Industries"]["looked_up"]
    assert found["Vandelay Industries"]["command"] == "jobwatch find 'Vandelay Industries'"
    assert web.calls and not [u for u in web.calls if "linkedin" in u or "indeed" in u]
    web.calls.clear()
    suggest.suggestions(cfg, store, look=True)
    assert web.calls == []  # kept: never looked for again


def test_a_board_found_that_is_watched_drops_it(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Initech Labs Group", "Staff Engineer")  # another name for a watched company
    store.set_unwatched_board("initechlabsgroup", "", None)    # (not found under that name by the import)
    store.set_unwatched_board("initechlabsgroup", "ashby:initech", "posting")
    assert suggest.suggestions(cfg, store, look=True) == []


# -- Accepting and dismissing

def test_accept_writes_the_watchlist(web, watchlist):
    umbrella_board(web)
    cfg, store, _, _ = take(watchlist, ["linkedin.eml"])
    before = watchlist.read_text()
    cfg, s = suggest.accept(cfg, store, "umbrella llc")
    assert s.entry == "greenhouse:umbrella"
    assert config.Board("greenhouse", "umbrella", "Umbrella") in config.load(watchlist).boards
    assert watchlist.with_name("jobwatch.yaml.bak").read_text() == before  # rewritten the way add_board does
    assert suggest.suggestions(cfg, store) == []


def test_accept_looks_for_the_board_when_nobody_has(web, watchlist):
    hooli_board(web)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Vandelay Industries", "Python Developer")
    cfg, s = suggest.accept(cfg, store, "Hooli")
    assert s.entry == "lever:hooli" and "lever:hooli" in {b.entry for b in cfg.boards}
    with pytest.raises(ValueError, match="no board found for Vandelay Industries"):
        suggest.accept(cfg, store, "Vandelay Industries")
    with pytest.raises(KeyError, match="no suggested company matches 'Nobody'"):
        suggest.accept(cfg, store, "Nobody")


def test_dismissed_ones_stay_dismissed(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Umbrella", "Field Engineer")
    assert suggest.dismiss(store, "HOOLI").name == "Hooli"
    added(cfg, store, "Hooli", "Data Engineer")  # more of its jobs later
    assert [s.name for s in suggest.suggestions(cfg, store)] == ["Umbrella"]
    assert rows(store)["hooli"]["dismissed_at"] and len(rows(store)["hooli"]["jobs"]) == 2  # jobs still tracked
    with pytest.raises(KeyError):
        suggest.dismiss(store, "Nobody")


# -- An older state file

def test_an_older_state_file_gains_suggestions_from_what_came_in(tmp_path, watchlist):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE jobs (key TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL, "
                     "data TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed TEXT, "
                     "status TEXT NOT NULL DEFAULT 'new', status_at TEXT, note TEXT, applied_at TEXT, "
                     "next_step TEXT, follow_up TEXT, via TEXT);")

    def row(key, source, board, name, title, via, first_seen):
        data = {"source": source, "company": board, "id": key.rsplit(":", 1)[1], "title": title, "url": "",
                "company_name": name, "locations": ["Remote"]}
        db.execute("INSERT INTO jobs (key, source, company, data, first_seen, last_seen, via) VALUES "
                   "(?, ?, ?, ?, ?, ?, ?)", (key, source, board, json.dumps(data), first_seen, first_seen, via))
    row("manual:hooli:platform-engineer", "manual", "hooli", "Hooli", "Platform Engineer", "linkedin-alert", iso(3))
    row("greenhouse:umbrella:501", "greenhouse", "umbrella", "Umbrella", "Field Engineer", "builtin-alert", iso(1))
    row("manual:vandelay-industries:engineer", "manual", "vandelay-industries", "Vandelay Industries", "Engineer",
        None, iso(5))  # added by hand
    row("lever:globex:aaaa-1111", "lever", "globex", "Globex", "Machine Learning Engineer", None, iso(2))  # fetched
    db.commit()
    db.close()

    store = Store(path)
    got = rows(store)
    assert set(got) == {"hooli", "umbrella", "vandelayindustries"}
    assert (got["umbrella"]["entry"], got["umbrella"]["found_by"]) == ("greenhouse:umbrella", "posting")
    assert got["hooli"]["jobs"][0][1] == iso(3)  # when it first came in
    cfg = config.load(watchlist)
    assert [s.name for s in suggest.suggestions(cfg, store)] == ["Umbrella", "Hooli", "Vandelay Industries"]
    store.dismiss_unwatched("hooli")
    store.close()
    store = Store(path)  # opening it again changes nothing
    assert rows(store)["hooli"]["dismissed_at"] and len(rows(store)) == 3
    store.close()


# -- The command, the MCP tools and the page

def test_cli(web, watchlist, capsys):
    hooli_board(web)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Vandelay Industries", "Python Developer")
    store.close()
    cli.main(["-c", str(watchlist), "suggest", "--no-lookup"])
    out = capsys.readouterr().out
    assert "Hooli: 1 matching job, the latest on" in out and "board: not looked for yet" in out
    assert "jobwatch suggest --add Hooli" in out and "jobwatch suggest --dismiss NAME" in out
    cli.main(["-c", str(watchlist), "suggest", "--format", "json"])
    listed = {s["company"]: s for s in json.loads(capsys.readouterr().out)}
    assert listed["Hooli"]["board"] == "lever:hooli" and listed["Vandelay Industries"]["board"] is None
    cli.main(["-c", str(watchlist), "suggest", "--add", "Hooli", "--dismiss", "Vandelay Industries"])
    out = capsys.readouterr().out
    assert "Watching Hooli: lever:hooli is on" in out and "Vandelay Industries won't be suggested again." in out
    assert "lever:hooli" in {b.entry for b in config.load(watchlist).boards}
    cli.main(["-c", str(watchlist), "suggest"])
    assert capsys.readouterr().out.startswith("No companies to suggest")
    with pytest.raises(SystemExit, match="no suggested company matches 'Nobody'"):
        cli.main(["-c", str(watchlist), "suggest", "--add", "Nobody"])


def test_mcp_tools(web, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    umbrella_board(web)
    mcp.import_job_alerts([(FIXTURES / "linkedin.eml").read_text()])
    found = mcp.list_suggested_boards(look_up_boards=False)
    assert [s["company"] for s in found] == ["Umbrella"]
    assert found[0]["add_board"] == {"entry": "greenhouse:umbrella", "name": "Umbrella"}
    assert found[0]["sample_titles"] == ["Field Engineer"] and found[0]["board_found"] == "posting"
    mcp.add_board(**found[0]["add_board"])  # accepting one is add_board with what it gives
    assert mcp.list_suggested_boards() == []
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    store.close()
    assert mcp.dismiss_suggested_board("hooli") == "Hooli won't be suggested again."
    assert mcp.list_suggested_boards(look_up_boards=False) == []


def test_web_endpoints(web, watchlist):
    hooli_board(web)
    app = App(watchlist)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    added(cfg, store, "Hooli", "Platform Engineer")
    added(cfg, store, "Umbrella", "Field Engineer")
    store.close()
    first = app.get_suggestions({})["companies"]
    assert {s["company"] for s in first} == {"Hooli", "Umbrella"} and not any(s["looked_up"] for s in first)
    looked = {s["company"]: s for s in app.get_suggestions({"lookup": ["1"]})["companies"]}
    assert looked["Hooli"]["board"] == "lever:hooli" and looked["Umbrella"]["looked_up"]
    assert app.post_suggestion_add({"company": "Hooli"}) == {"added": "lever:hooli", "name": "Hooli",
                                                             "companies": 4}
    assert any(c["board"] == "hooli" for c in app.get_settings({})["companies"])
    assert app.post_suggestion_dismiss({"company": "Umbrella"}) == {"dismissed": "Umbrella"}
    assert app.get_suggestions({})["companies"] == []


def test_page_has_companies_to_watch(server):
    page = request(server, "GET", "/")[1].decode()
    assert "function toWatchPanel(" in page and 'panel("Companies to watch"' in page
    assert 'class: "to-watch"' in page  # not the chat's .suggest buttons
    assert 'api("/api/suggestions"' in page and '"/api/suggestions/" + what' in page
    ok = {"X-Jobwatch-Token": TOKEN}
    status, data = request(server, "GET", "/api/suggestions", headers=ok)
    assert status == 200 and json.loads(data) == {"companies": []}
    status, data = request(server, "POST", "/api/suggestions/dismiss", {"company": "Nobody"}, headers=ok)
    assert status == 404 and "no suggested company matches" in json.loads(data)["error"]
    assert request(server, "GET", "/api/suggestions", headers={"X-Jobwatch-Token": "wrong"})[0] == 403
