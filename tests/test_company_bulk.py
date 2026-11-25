"""`company --status --keys` (a company's jobs by status, keys alone for scripts) and `mark STATUS --company NAME`
(a status for every job at a company, the applications left alone), in the CLI and the MCP tools."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from jobwatch import cli, config
from jobwatch.models import Job
from jobwatch.store import Store

NEW = ("ashby:initech:a1", "ashby:initech:a2")
QUEUED, APPLIED, REJECTED = "manual:initech:data-engineer", "manual:initech:staff-engineer", "manual:initech:old-role"


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr()


def board_job(id_, title, company_name="Initech", board="initech", source="ashby"):
    return Job(source=source, company=board, id=id_, title=title, url=f"https://jobs.example/{board}/{id_}",
               company_name=company_name, locations=["Denver, CO"],
               posted=(datetime.now(UTC) - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0))


@pytest.fixture
def initech(watchlist):
    """Initech: two roles on its board not acted on, one queued, one applied to, one rejected. Globex: one role."""
    store = Store(config.load(watchlist).state)
    store.sync("ashby", "initech", [board_job("a1", "Platform Engineer"), board_job("a2", "Data Analyst")])
    store.add("Initech", "Data Engineer", status="queued")
    store.add("Initech", "Staff Engineer", status="applied", applied="2026-09-01", note="referred by Ana")
    store.add("Initech", "Old Role", status="rejected", applied="2026-08-01")
    store.sync("lever", "globex", [board_job("g1", "Platform Engineer", "Globex", "globex", "lever")])
    store.close()
    return ("-c", str(watchlist))


def statuses(watchlist_args):
    store = Store(config.load(watchlist_args[1]).state)
    try:
        return {j.key: rec["status"] for j, rec in store.jobs(None, include_closed=True)}
    finally:
        store.close()


# -- company --status / --keys

def test_keys_prints_the_keys_of_the_jobs_in_a_status_one_a_line(initech, capsys):
    out = run(capsys, *initech, "company", "initech", "--status", "new", "--keys").out
    assert out.endswith("\n") and sorted(out.splitlines()) == list(NEW)  # nothing but keys
    out = run(capsys, *initech, "company", "initech", "--status", "queued", "--status", "applied", "--keys").out
    assert out.splitlines() == [APPLIED, QUEUED]  # open applications first, then queued ones


def test_keys_with_no_job_in_the_status_prints_nothing(initech, capsys):
    assert run(capsys, *initech, "company", "initech", "--status", "offer", "--keys").out == ""


def test_keys_for_an_unknown_company_is_an_error(initech):
    with pytest.raises(SystemExit, match="no tracked job is at a company matching 'nobody'"):
        cli.main([*initech, "company", "nobody", "--status", "new", "--keys"])
    with pytest.raises(SystemExit, match="leave --format json out"):
        cli.main([*initech, "company", "initech", "--keys", "--format", "json"])


def test_a_status_lists_every_job_in_it_closed_postings_and_hidden_roles_too(initech, capsys, monkeypatch):
    from jobwatch import company

    monkeypatch.setattr(company, "OPEN_SHOWN", 1)  # the usual view cuts the open roles; a status doesn't
    assert "and 1 more open roles" in run(capsys, *initech, "company", "initech").out
    out = run(capsys, *initech, "company", "initech", "--status", "new").out
    assert "2 jobs: 2 new." in out and "Platform Engineer" in out and "Data Analyst" in out
    assert "more open roles" not in out and "Staff Engineer" not in out
    assert run(capsys, *initech, "company", "initech", "--status", "offer").out == "No offer job at Initech.\n"
    v = json.loads(run(capsys, *initech, "company", "initech", "--status", "rejected", "--format", "json").out)
    assert [j["key"] for j in v["jobs"]] == [REJECTED] and v["statuses"] == ["rejected"]


# -- mark --company

def test_mark_company_changes_every_job_except_the_applications(initech, capsys):
    out = run(capsys, *initech, "mark", "skipped", "--company", "initech").out
    assert out.splitlines()[0] == f"{QUEUED}: skipped"  # queued ones come before the roles not acted on
    assert sorted(out.splitlines()[1:3]) == [f"{k}: skipped" for k in NEW]
    assert f"Left alone, applied to (--include-active changes them): {APPLIED} (applied), {REJECTED} (rejected)" in out
    got = statuses(initech)
    assert {got[k] for k in (*NEW, QUEUED)} == {"skipped"} and got[APPLIED] == "applied" \
        and got[REJECTED] == "rejected" and got["lever:globex:g1"] == "new"


def test_mark_company_dry_run_changes_nothing(initech, capsys):
    before = statuses(initech)
    out = run(capsys, *initech, "mark", "skipped", "--company", "Initech", "--dry-run").out
    assert f"would mark {NEW[0]}: skipped (was new)" in out and f"would mark {QUEUED}: skipped (was queued)" in out
    assert statuses(initech) == before


def test_mark_company_only_status_limits_it(initech, capsys):
    out = run(capsys, *initech, "mark", "skipped", "--company", "initech", "--only-status", "new").out
    assert sorted(out.splitlines()) == [f"{k}: skipped" for k in NEW]
    assert statuses(initech)[QUEUED] == "queued"


def test_mark_company_skips_the_jobs_already_in_the_status(initech, capsys):
    out = run(capsys, *initech, "mark", "queued", "--company", "initech").out
    assert sorted(out.splitlines()[:2]) == [f"{k}: queued" for k in NEW] and "Already queued: 1." in out


def test_mark_company_include_active_changes_the_applications_too(initech, capsys):
    out = run(capsys, *initech, "mark", "closed", "--company", "initech", "--include-active", "--only-status",
              "applied").out
    assert out == f"{APPLIED}: closed\n"
    assert statuses(initech)[APPLIED] == "closed"


def test_mark_company_refuses_to_look_for_applications_without_include_active(initech):
    with pytest.raises(SystemExit, match="applied: jobs you applied to are only changed with --include-active"):
        cli.main([*initech, "mark", "skipped", "--company", "initech", "--only-status", "applied"])
    assert statuses(initech)[APPLIED] == "applied"


def test_mark_company_add_note_and_next_step_go_on_each_job(initech, capsys):
    run(capsys, *initech, "mark", "queued", "--company", "initech", "--only-status", "new", "--add-note",
        "worth a look", "--follow-up", "+3")
    store = Store(config.load(initech[1]).state)
    try:
        for key in NEW:
            rec = store.find(key)[1]
            assert rec["status"] == "queued" and rec["note"].endswith(": worth a look") and rec["follow_up"]
        assert store.find(APPLIED)[1]["note"] == "referred by Ana"
    finally:
        store.close()


def test_mark_company_needs_one_company_and_a_status(initech, capsys):
    with pytest.raises(SystemExit, match="no tracked job is at a company matching 'nobody'"):
        cli.main([*initech, "mark", "skipped", "--company", "nobody"])
    with pytest.raises(SystemExit, match="give the status alone"):
        cli.main([*initech, "mark", "skipped", NEW[0], "--company", "initech"])
    with pytest.raises(SystemExit, match="--url is for one job"):
        cli.main([*initech, "mark", "skipped", "--company", "initech", "--url", "https://example.com/1"])
    with pytest.raises(SystemExit, match="would erase the note"):
        cli.main([*initech, "mark", "skipped", "--company", "initech", "--note", " "])
    with pytest.raises(SystemExit, match="are for --company"):
        cli.main([*initech, "mark", "skipped", NEW[0], "--dry-run"])
    assert statuses(initech)[NEW[0]] == "new"


def test_mark_company_with_several_matches_asks_for_the_full_name(initech):
    store = Store(config.load(initech[1]).state)
    store.add("Initrode", "Researcher", status="queued")
    store.close()
    cli.main([*initech, "mark", "skipped", "--company", "Initech", "--dry-run"])  # the exact name is enough
    with pytest.raises(SystemExit, match="matches several companies"):
        cli.main([*initech, "mark", "skipped", "--company", "init"])


# -- the MCP tools

mcp = pytest.importorskip("jobwatch.mcp_server")


@pytest.fixture
def served(initech, monkeypatch):
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", initech[1])
    return initech


def test_the_mcp_tool_marks_a_companys_jobs_and_leaves_the_applications(served):
    r = mcp.mark_company_jobs("Initech", "skipped", only_status=["new"], dry_run=True)
    assert r["dry_run"] and sorted(c["key"] for c in r["changed"]) == list(NEW) and r["left_alone"] == []
    assert statuses(served)[NEW[0]] == "new"
    r = mcp.mark_company_jobs("Initech", "skipped", add_note="not a fit")
    assert sorted(c["key"] for c in r["changed"]) == sorted([*NEW, QUEUED])
    assert [j["key"] for j in r["left_alone"]] == [APPLIED, REJECTED]
    assert statuses(served)[QUEUED] == "skipped" and statuses(served)[APPLIED] == "applied"


def test_the_mcp_tool_says_why_it_refuses(served):
    with pytest.raises(mcp.ToolError, match="no tracked job is at a company matching 'nobody'"):
        mcp.mark_company_jobs("nobody", "skipped")
    with pytest.raises(mcp.ToolError, match="only changed with --include-active"):
        mcp.mark_company_jobs("Initech", "skipped", only_status=["applied"])


def test_get_company_takes_statuses(served):
    v = mcp.get_company("initech", status=["queued", "rejected"])
    assert [j["key"] for j in v["jobs"]] == [QUEUED, REJECTED]


def test_the_bulk_statuses_leave_out_the_application_stages():
    from typing import get_args

    from jobwatch.store import STAGES
    assert not set(get_args(mcp.BulkStatus)) & set(STAGES)
    schema = {t.name: t for t in asyncio.run(mcp.server.list_tools())}["mark_company_jobs"].input_schema
    assert set(schema["required"]) == {"name", "status"}
