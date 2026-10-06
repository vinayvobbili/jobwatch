#!/usr/bin/env python3
"""Check that the MCP server starts and lists its tools, the way a directory's build check does.

    scripts/mcp_smoke.py                    # runs the server from this checkout (uv run --extra mcp)
    scripts/mcp_smoke.py --docker           # builds the committed HEAD in a Glama-like image and runs it there
    scripts/mcp_smoke.py --docker --build-step "uv sync"   # try a different build step
    scripts/mcp_smoke.py -- python -m x     # any command that speaks MCP over stdio

It sends initialize and tools/list over stdio and fails unless the server answers with at least one tool.
--docker builds from `git archive HEAD` (so commit first) on Glama's base image and Python, with the same
build step to put in Glama's Dockerfile settings (BUILD_STEP below). Glama also wraps the server in
mcp-proxy; that part is theirs and isn't reproduced. The server's command and console script come from
pyproject.toml. Standard library only, so the same file works in any of these packages.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "debian:trixie-slim"  # Glama's default base
PYTHON = "3.14"                    # and its default Python
BUILD_STEP = "uv sync --extra mcp"  # the console script needs the mcp extra; plain `uv sync` leaves it out
PROTOCOL = "2025-06-18"


def mcp_script(root: Path) -> str:
    """The console script that starts the MCP server: the one named *-mcp in [project.scripts]."""
    text = (root / "pyproject.toml").read_text()
    section = re.search(r"^\[project\.scripts\]\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    names = re.findall(r"^([\w.-]+-mcp)\s*=", section.group(1), re.M) if section else []
    if not names:
        raise SystemExit("mcp_smoke: no *-mcp script in [project.scripts]")
    return names[0]


def dockerfile(script: str, base: str = BASE_IMAGE, python: str = PYTHON, build_step: str = BUILD_STEP) -> str:
    return f"""FROM {base}
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \\
 && curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh \\
 && uv python install {python} --default --preview \\
 && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN {build_step}
CMD ["uv", "run", "{script}"]
"""


def requests() -> str:
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                    "clientInfo": {"name": "mcp_smoke", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    return "".join(json.dumps(m) + "\n" for m in msgs)


def parse(stdout: str) -> tuple[dict, list[str]]:
    """The server's info and its tool names, from its replies; raises with what it said otherwise."""
    replies = {}
    for line in stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and "id" in msg:
            replies[msg["id"]] = msg
    for i in (1, 2):
        if i not in replies:
            raise RuntimeError(f"no reply to {'initialize' if i == 1 else 'tools/list'}")
        if "error" in replies[i]:
            raise RuntimeError(f"error reply: {replies[i]['error']}")
    return replies[1]["result"].get("serverInfo", {}), [t["name"] for t in replies[2]["result"].get("tools", [])]


def handshake(cmd: list[str], timeout: float = 120) -> tuple[dict, list[str]]:
    # stdin closes after tools/list, which ends a stdio server once it has answered.
    run = subprocess.run(cmd, input=requests(), capture_output=True, text=True, timeout=timeout, check=False)
    try:
        return parse(run.stdout)
    except RuntimeError as e:
        tail = "\n".join(run.stderr.splitlines()[-15:])
        raise SystemExit(f"mcp_smoke: {e}\n--- stderr (last lines)\n{tail}") from None


def docker_command(root: Path, script: str, tag: str, build_step: str = BUILD_STEP) -> list[str]:
    """Build HEAD into an image (Glama-like) and return the command that runs the server in it."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", "HEAD"],
                                 capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        (Path(tmp) / "Dockerfile").write_text(dockerfile(script, build_step=build_step))
        subprocess.run(["docker", "build", "-q", "-t", tag, tmp], check=True, stdout=subprocess.DEVNULL)
    return ["docker", "run", "-i", "--rm", tag]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docker", action="store_true", help="build HEAD in a Glama-like image and run it there")
    ap.add_argument("--build-step", default=BUILD_STEP, help=f"the image's build step (default: {BUILD_STEP})")
    ap.add_argument("--print-dockerfile", action="store_true", help="print the Dockerfile --docker uses and stop")
    ap.add_argument("cmd", nargs="*", help="the server command, after -- (default: this checkout's *-mcp script)")
    args = ap.parse_args(argv)
    script = mcp_script(ROOT)
    if args.print_dockerfile:
        print(dockerfile(script, build_step=args.build_step), end="")
        return 0
    if args.cmd:
        cmd = args.cmd
    elif args.docker:
        cmd = docker_command(ROOT, script, f"{script}-smoke", args.build_step)
    else:
        cmd = ["uv", "run", "--project", str(ROOT), "--extra", "mcp", script]
    info, tools = handshake(cmd)
    if not tools:
        raise SystemExit(f"mcp_smoke: {info.get('name', 'server')} started but lists no tools")
    print(f"{info.get('name')} {info.get('version')}: {len(tools)} tools ({', '.join(tools)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
