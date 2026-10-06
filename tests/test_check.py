"""Checking that queued jobs and applications are still posted, and what to look at before applying."""

import json

import pytest

from jobwatch import cli, config, report, sources
from jobwatch.filters import Filters
from jobwatch.store import Store
from jobwatch.watch import check_postings, queue

from .conftest import LEVER, RESPONSES
from .test_linkedin import page_for

LEVER_API = "https://api.lever.co/v0/postings/globex?mode=json"


def test_closed_and_reopened_postings_are_recorded(watchlist, web):
    cli.main(["-c", str(watchlist), "fetch"])
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.set_status(["lever:globex:aaaa-1111"], "applied")
    store.set_status(["ashby:initech:c1"], "queued")
    store.add("Umbrella", "Field Engineer")                                   # nothing to check it on
    store.add("Hooli", "Staff Engineer", url="https://www.linkedin.com/jobs/view/4123456789/")
    web.responses[LEVER_API] = [LEVER[1]]                                       # aaaa-1111 is gone
    got = {c.job.key: (c.result, c.detail) for c in check_postings(store, page=lambda url: page_for(closed=True))}
    assert got["lever:globex:aaaa-1111"] == ("closed", "")
    assert got["ashby:initech:c1"] == ("open", "")
    assert got["manual:umbrella:field-engineer"] == ("unknown", "no link jobwatch can read")
    assert got["manual:hooli:staff-engineer"][0] == "closed"
    assert store.find("lever:globex:aaaa-1111")[1]["closed"]
    again = {c.job.key: c for c in check_postings(store, page=lambda url: page_for(closed=True))}
    assert again["lever:globex:aaaa-1111"].result == "closed" and again["lever:globex:aaaa-1111"].detail.startswith(
        "since 20")
    web.responses[LEVER_API] = LEVER
    again = {c.job.key: c.result for c in check_postings(store, page=lambda url: page_for())}
    assert again["lever:globex:aaaa-1111"] == "reopened" and again["manual:hooli:staff-engineer"] == "reopened"
    assert not store.find("lever:globex:aaaa-1111")[1]["closed"]
    assert not store.set_closed("lever:globex:aaaa-1111", False)  # no change


def test_a_board_that_cant_be_read_is_unknown(watchlist, web):
    cli.main(["-c", str(watchlist), "fetch"])
    store = Store(config.load(watchlist).state)
    store.set_status(["lever:globex:aaaa-1111"], "applied")
    web.responses[LEVER_API] = sources.SourceError("HTTP 500")
    [c] = check_postings(store)
    assert c.result == "unknown" and "500" in c.detail and not store.find(c.job.key)[1]["closed"]


def test_check_command(watchlist, web, capsys):
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "mark", "applied", "aaaa-1111", "c1"])
    web.responses[LEVER_API] = [LEVER[1]]
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "check"])
    out, err = capsys.readouterr()
    assert out.startswith("closed    lever:globex:aaaa-1111  globex: Machine Learning Engineer")
    assert "c1" not in out and err.strip() == "1 closed, 1 open"
    cli.main(["-c", str(watchlist), "check", "--all", "--status", "applied"])
    assert "open      ashby:initech:c1" in capsys.readouterr().out


def test_warnings_before_applying(watchlist, web, tmp_path):
    raw = watchlist.read_text().replace("  max_age_days: 30\n", "  max_age_days: 30\n  min_salary: 220000\n"
                                        "  flags: {'models? in Python': 'stack', clearance: clearance}\n")
    watchlist.write_text(raw)
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "queue", "aaaa-1111", "bbbb-2222", "c1"])
    cfg = config.load(watchlist)
    got = {e.job.id: e.warnings for e in queue(cfg, Store(cfg.state))}
    assert got["aaaa-1111"] == ["pay $150K–$210K is below $220K", "stack: “models in Python”"]
    assert got["bbbb-2222"][0] == "location: Toronto, ON"  # queued by hand: the filters never passed it
    assert got["c1"] == []
    text = report.queue_markdown(queue(cfg, Store(cfg.state)))
    assert "**Check:** pay $150K–$210K is below $220K; stack: “models in Python”" in text


def test_flags_are_checked_when_loaded():
    assert Filters.from_dict({"flags": {"TS/SCI": "clearance"}}).flags == {"TS/SCI": "clearance"}
    with pytest.raises(ValueError, match="maps a pattern"):
        Filters.from_dict({"flags": ["TS/SCI"]})
    with pytest.raises(ValueError, match="isn't a valid pattern"):
        Filters.from_dict({"flags": {"(unclosed": "oops"}})


def test_every_mcp_tool(watchlist, web, tmp_path, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    assert mcp.find_board("https://jobs.lever.co/globex")[0]["entry"] == "lever:globex"
    assert "new" in mcp.fetch_jobs().lower()
    assert "Staff AI Engineer" in [j["title"] for j in mcp.get_digest(mark_shown=False)["jobs"]]
    assert mcp.mark_job("c1", "queued").endswith(": queued")
    queued = mcp.list_queued_jobs()
    assert [q["key"] for q in queued] == ["ashby:initech:c1"] and queued[0]["warnings"] == []
    assert mcp.add_application("Umbrella", "Field Engineer", applied_on="2026-01-02").startswith(
        "manual:umbrella:field-engineer: applied")
    assert [a["key"] for a in mcp.list_applications()] == ["manual:umbrella:field-engineer"]
    assert {j["key"] for j in mcp.list_jobs("queued")} == {"ashby:initech:c1"}
    assert {c["key"]: c["result"] for c in mcp.check_postings()} == {
        "ashby:initech:c1": "open", "manual:umbrella:field-engineer": "unknown"}
    assert mcp.get_interview_prep("c1")["title"] == "Staff AI Engineer"
    assert "skills" in json.dumps(mcp.list_skill_gaps()).lower()
    assert [b["entry"] for b in mcp.list_boards()["boards"]] == ["greenhouse:acme", "lever:globex", "ashby:initech"]
    assert "workable:hooli" in [b["entry"] for b in mcp.add_board("workable:hooli", "Hooli")["boards"]]
    assert "workable:hooli" not in [b["entry"] for b in mcp.remove_board("workable:hooli")["boards"]]
    names = {t.name: t.annotations for t in __import__("asyncio").run(mcp.server.list_tools())}
    assert all(a is not None for a in names.values()) and names["list_jobs"].read_only_hint
    assert names["mark_job"].destructive_hint and not names["fetch_jobs"].read_only_hint
    assert names["remove_board"].destructive_hint and not names["add_board"].destructive_hint


def test_responses_are_left_alone():
    assert LEVER_API in RESPONSES  # the tests above change their own copy
