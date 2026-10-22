"""The agent skill (skills/jobwatch/SKILL.md) that tells an agent when and how to use the MCP tools: its front
matter is what marketplaces read, and every tool it names is one the server has."""

import asyncio
import re
from pathlib import Path

import pytest
import yaml

mcp = pytest.importorskip("jobwatch.mcp_server")
SKILL = Path(__file__).parent.parent / "skills" / "jobwatch" / "SKILL.md"


def test_the_skill_has_a_name_and_a_description():
    front = yaml.safe_load(SKILL.read_text().split("---")[1])
    assert front["name"] == "jobwatch" and len(front["description"]) > 100


def test_the_skill_names_only_tools_the_server_has_and_every_one_of_them():
    tools = {t.name for t in asyncio.run(mcp.server.list_tools())}
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", SKILL.read_text())) - {"story_gaps", "duplicate_of"}
    assert named == tools
