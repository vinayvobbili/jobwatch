"""Checking that queued jobs and applications are still posted, and what to look at before applying."""

import json
from dataclasses import replace

import pytest

from jobwatch import cli, config, dupes, report, sources
from jobwatch.filters import Filters
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.watch import check_postings, find_repost, queue

from .conftest import LEVER, RESPONSES, FakeWeb
from .test_big_boards import WD, wd_detail, wd_posting
from .test_linkedin import no_linkedin

LEVER_API = "https://api.lever.co/v0/postings/globex?mode=json"


def test_closed_and_reopened_postings_are_recorded(watchlist, web):
    cli.main(["-c", str(watchlist), "fetch"])
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    store.set_status(["lever:globex:aaaa-1111"], "applied")
    store.set_status(["ashby:initech:c1"], "queued")
    store.add("Umbrella", "Field Engineer")                                   # nothing to check it on
    store.add("Hooli", "Staff Engineer", url="https://www.linkedin.com/jobs/view/4123456789/")  # never read
    web.responses[LEVER_API] = [LEVER[1]]                                       # aaaa-1111 is gone
    page = no_linkedin(lambda url: "")
    got = {c.job.key: (c.result, c.detail) for c in check_postings(store, page=page)}
    assert got["lever:globex:aaaa-1111"] == ("closed", "")
    assert got["ashby:initech:c1"] == ("open", "")
    assert got["manual:umbrella:field-engineer"] == ("unknown", "no link jobwatch can read")
    assert got["manual:hooli:staff-engineer"] == ("unknown", "jobwatch can't read that site: check it yourself")
    assert store.find("lever:globex:aaaa-1111")[1]["closed"]
    again = {c.job.key: c for c in check_postings(store, page=page)}
    assert again["lever:globex:aaaa-1111"].result == "closed" and again["lever:globex:aaaa-1111"].detail.startswith(
        "since 20")
    web.responses[LEVER_API] = LEVER
    again = {c.job.key: c.result for c in check_postings(store, page=page)}
    assert again["lever:globex:aaaa-1111"] == "reopened" and again["manual:hooli:staff-engineer"] == "unknown"
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


def test_a_closed_posting_reposted_under_a_new_id_is_found(watchlist, web):
    cli.main(["-c", str(watchlist), "fetch"])
    store = Store(config.load(watchlist).state)
    store.set_status(["lever:globex:aaaa-1111"], "applied")
    repost = {**LEVER[0], "id": "cccc-3333", "hostedUrl": "https://jobs.lever.co/globex/cccc-3333"}
    web.responses[LEVER_API] = [LEVER[1], repost]  # the old req came down; the same title is back under a new one
    said = "reposted as cccc-3333: https://jobs.lever.co/globex/cccc-3333"
    [c] = [c for c in check_postings(store) if c.job.key == "lever:globex:aaaa-1111"]
    assert (c.result, c.detail) == ("closed", said)
    assert store.find("lever:globex:aaaa-1111")[1]["note"].endswith(
        "Reposted as cccc-3333: https://jobs.lever.co/globex/cccc-3333")
    match = dupes.check(store, "lever:globex:cccc-3333")  # the new posting warns: you applied to the old one
    assert match and match.reposted and match.other.key == "lever:globex:aaaa-1111"
    [c] = [c for c in check_postings(store) if c.job.key == "lever:globex:aaaa-1111"]
    assert c.detail.startswith("since 20") and c.detail.endswith("; " + said)  # still said, noted once
    assert store.find("lever:globex:aaaa-1111")[1]["note"].count("Reposted as") == 1


def test_a_repost_on_a_searched_board_is_read_in_full(tmp_path):
    title = "Detection Platform Engineer - Manager"
    old, new = wd_posting("0412345", title), wd_posting("0418765", title)
    web = FakeWeb({f"{WD}/jobs": lambda body: {"total": 1, "jobPostings": [new] if body["searchText"] == title
                                                and body["offset"] == 0 else []},
                   WD + old["externalPath"]: wd_detail(old), WD + new["externalPath"]: wd_detail(new)})
    store = Store(tmp_path / "state.db")  # applying keeps the posting next to it
    applied = sources.posting("https://initech.wd5.myworkdayjobs.com/External" + old["externalPath"], web)
    store.keep(applied)
    store.set_status([applied.key], "applied")
    del web.responses[WD + old["externalPath"]]  # taken down
    [c] = check_postings(store, get=web)
    assert c.result == "closed" and c.detail.startswith("reposted as R0418765: https://initech.wd5.myworkdayjobs.com/")
    kept, rec = store.find("workday:initech.wd5/External:R0418765")
    assert "Detection engineering" in kept.description and rec["status"] == "new"  # read in full, yours to queue
    match = dupes.check(store, kept.key)
    assert match.reposted and match.old_req == "412345" and match.other.key == applied.key


def test_one_word_titles_and_unreadable_boards_find_no_repost(watchlist, web, tmp_path):
    store = Store(tmp_path / "state.db")
    job = Job(source="lever", company="globex", id="aaaa-1111", title="Engineer", url="https://jobs.lever.co/x")
    web.responses[LEVER_API] = [{**LEVER[0], "id": "dddd-4444", "text": "Engineer"}]
    assert find_repost(store, job, get=web) is None  # one word: too common to call it the same opening
    web.responses[LEVER_API] = sources.SourceError("HTTP 500")
    assert find_repost(store, replace(job, title=LEVER[0]["text"]), get=web) is None
    assert find_repost(store, replace(job, source="manual"), get=web) is None


def test_warnings_before_applying(watchlist, web, tmp_path):
    raw = watchlist.read_text().replace("  max_age_days: 30\n", "  max_age_days: 30\n  min_salary: 220000\n"
                                        "  flags: {'models? in Python': 'stack', clearance: clearance}\n")
    watchlist.write_text(raw)
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "queue", "aaaa-1111", "bbbb-2222", "c1"])
    cfg = config.load(watchlist)
    got = {e.job.id: e.warnings for e in queue(cfg, Store(cfg.state))}
    assert got["aaaa-1111"] == ["pay $150K–$210K is below $220K", "stack: “models in Python”"]
    # queued by hand: the filters never passed it (its $60–$80 an hour comes to $125K–$166K a year)
    assert got["bbbb-2222"][:2] == ["pay $125K–$166K is below $220K", "location: Toronto, ON"]
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
    assert "Staff Data Engineer" in [j["title"] for j in mcp.get_digest(mark_shown=False)["jobs"]]
    assert mcp.mark_job("c1", "queued").endswith(": queued")
    queued = mcp.list_queued_jobs()
    assert [q["key"] for q in queued] == ["ashby:initech:c1"] and queued[0]["warnings"] == []
    assert mcp.add_application("Umbrella", "Field Engineer", applied_on="2026-01-02").startswith(
        "manual:umbrella:field-engineer: applied")
    assert [a["key"] for a in mcp.list_applications()] == ["manual:umbrella:field-engineer"]
    assert {j["key"] for j in mcp.list_jobs("queued")} == {"ashby:initech:c1"}
    assert {c["key"]: c["result"] for c in mcp.check_postings()} == {
        "ashby:initech:c1": "open", "manual:umbrella:field-engineer": "unknown"}
    assert mcp.get_interview_prep("c1")["title"] == "Staff Data Engineer"
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
