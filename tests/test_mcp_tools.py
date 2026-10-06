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
    ("list_jobs", "apply_queue"), ("list_jobs", "applications"), ("applications", "apply_queue"),
    ("apply_queue", "applications"), ("digest", "apply_queue"), ("job_details", "application_package"),
    ("application_package", "interview_prep"), ("mark_job", "add_application"), ("add_application", "mark_job"),
    ("find_board", "add_application"), ("fetch_jobs", "digest"),
])
def test_overlapping_tools_point_to_each_other(tool, sibling):
    assert sibling in TOOLS[tool].description
