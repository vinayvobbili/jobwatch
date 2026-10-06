"""scripts/mcp_smoke.py: finding the server, the Dockerfile, and a real stdio handshake. No Docker needed."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mcp_smoke.py"


@pytest.fixture
def smoke():
    spec = importlib.util.spec_from_file_location("mcp_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finds_the_mcp_script(smoke, tmp_path):
    assert smoke.mcp_script(SCRIPT.parents[1]) == "jobwatch-mcp"
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\nacme = "acme.cli:main"\n\n[tool.x]\ny-mcp = 1\n')
    with pytest.raises(SystemExit, match="no \\*-mcp script"):
        smoke.mcp_script(tmp_path)


def test_dockerfile_installs_the_mcp_extra(smoke):
    text = smoke.dockerfile("acme-mcp")
    assert text.startswith("FROM debian:trixie-slim")
    assert "RUN uv sync --extra mcp\n" in text and text.endswith('CMD ["uv", "run", "acme-mcp"]\n')


def test_parse_reports_missing_and_error_replies(smoke):
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "acme"}}})
    tools = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}, {"name": "b"}]}})
    assert smoke.parse(f"starting up\n{init}\n{tools}\n") == ({"name": "acme"}, ["a", "b"])
    with pytest.raises(RuntimeError, match="no reply to tools/list"):
        smoke.parse(init)
    with pytest.raises(RuntimeError, match="error reply"):
        smoke.parse(init + "\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"message": "boom"}}))


# Replies to tools/list only after a pause, and exits at end of input without answering what's still pending.
SLOW_SERVER = """
import json, sys, threading, time
def answer(msg):
    time.sleep(0.3)
    result = {"tools": [{"name": "a"}]} if msg["id"] == 2 else {"serverInfo": {"name": "slow"}}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    if "id" in msg:
        threading.Thread(target=answer, args=(msg,), daemon=True).start()
"""


def test_handshake_waits_for_the_reply_before_closing_input(smoke):
    assert smoke.handshake([sys.executable, "-c", SLOW_SERVER], timeout=10) == ({"name": "slow"}, ["a"])


def test_handshake_reports_a_server_that_exits(smoke):
    with pytest.raises(SystemExit, match=r"no reply to initialize(.|\n)*broken"):
        smoke.handshake([sys.executable, "-c", "import sys; sys.exit('broken')"], timeout=10)


def test_handshake_with_the_real_server(smoke, monkeypatch):
    monkeypatch.delenv("JOBWATCH_CONFIG", raising=False)  # the server reads the watchlist only when a tool runs
    info, tools = smoke.handshake([sys.executable, "-m", "jobwatch.mcp_server"], timeout=60)
    assert info["name"] == "jobwatch"
    assert {"fetch_jobs", "digest", "mark_job", "applications"} <= set(tools)
