"""The MCP tools describe themselves fully: every parameter documented, allowed values listed, overlaps routed."""

import asyncio
from typing import get_args

import pytest

from jobwatch import config, sources, store

mcp = pytest.importorskip("jobwatch.mcp_server")
TOOLS = {t.name: t for t in asyncio.run(mcp.server.list_tools())}


def test_every_parameter_is_described():
    missing = [f"{name}.{param}" for name, t in TOOLS.items()
               for param, schema in t.input_schema.get("properties", {}).items() if not schema.get("description")]
    assert not missing


def test_allowed_values_match_the_store_and_config():
    assert get_args(mcp.Status) == store.STATUSES
    assert get_args(mcp.Timeline) == config.TIMELINES


def test_status_lists_its_values():
    schema = TOOLS["mark_job"].input_schema["properties"]["status"]
    values = {v for option in schema.get("anyOf", [schema]) for v in option.get("enum", [])}
    assert values == set(store.STATUSES)


@pytest.mark.parametrize("tool, sibling", [
    ("list_jobs", "list_queued_jobs"), ("list_jobs", "list_applications"), ("list_applications", "list_queued_jobs"),
    ("list_queued_jobs", "list_applications"), ("get_digest", "list_queued_jobs"),
    ("get_job", "get_application_package"), ("get_application_package", "get_interview_prep"),
    ("mark_job", "add_application"), ("add_application", "mark_job"), ("find_board", "add_application"),
    ("find_board", "add_board"), ("add_board", "find_board"), ("list_boards", "add_board"),
    ("fetch_jobs", "get_digest"), ("import_job_alerts", "get_digest"), ("add_application", "import_job_alerts"),
    ("list_suggested_boards", "add_board"), ("list_suggested_boards", "dismiss_suggested_board"),
    ("dismiss_suggested_board", "add_board"), ("add_board", "list_suggested_boards"),
    ("read_status_emails", "mark_job"), ("import_job_alerts", "read_status_emails"),
    ("get_company", "get_job"), ("get_company", "list_applications"), ("get_company", "list_jobs"),
    ("get_interview_prep", "save_story"), ("save_story", "get_interview_prep"),
])
def test_overlapping_tools_point_to_each_other(tool, sibling):
    assert sibling in TOOLS[tool].description


VERBS = {"add", "check", "dismiss", "fetch", "find", "get", "import", "list", "mark", "rate", "read", "remove", "save",
         "set"}


def test_tool_names_start_with_a_verb():
    assert {name for name in TOOLS if name.split("_")[0] not in VERBS} == set()


def test_find_board_says_why_a_link_failed(monkeypatch):
    """A wrong Workday site answers 401: the client reads that, not a bare "Error executing tool find_board"."""
    def refused(company):
        raise sources.SourceError("https://initech.wd1.myworkdayjobs.com/wday/cxs/initech/Jobs/jobs: HTTP 401")

    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setattr(sources, "probe", refused)
    with pytest.raises(mcp.ToolError) as e:
        asyncio.run(mcp.server.call_tool("find_board", {"company": "https://initech.wd1.myworkdayjobs.com/Jobs"}))
    assert str(e.value).endswith("Jobs/jobs: HTTP 401")


def test_a_first_run_without_a_watchlist_says_to_add_a_board(monkeypatch, tmp_path):
    """The desktop extension's user has no terminal for `jobwatch init`: the first board added creates the file."""
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setenv("JOBWATCH_CONFIG", str(tmp_path / "jobwatch.yaml"))
    with pytest.raises(mcp.ToolError, match=r"no watchlist yet.*find_board and add_board"):
        mcp.list_boards()


def test_a_server_whose_code_changed_since_it_started_says_to_restart(monkeypatch):
    monkeypatch.setattr(mcp, "_STARTED", 0)  # every module is newer than this "start"
    with pytest.raises(mcp.ToolError, match="Reconnect"):
        mcp.list_boards()
    monkeypatch.setattr(mcp, "_STARTED", float("inf"))
    assert mcp._changed_since_start() is None
