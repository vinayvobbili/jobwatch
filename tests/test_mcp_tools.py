"""The MCP tools describe themselves fully: every parameter documented, allowed values listed, overlaps routed."""

import asyncio
from typing import get_args

import pytest

from jobwatch import config, store

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
    ("fetch_jobs", "get_digest"),
])
def test_overlapping_tools_point_to_each_other(tool, sibling):
    assert sibling in TOOLS[tool].description


VERBS = {"add", "check", "fetch", "find", "get", "list", "mark", "remove", "save"}


def test_tool_names_start_with_a_verb():
    assert {name for name in TOOLS if name.split("_")[0] not in VERBS} == set()
