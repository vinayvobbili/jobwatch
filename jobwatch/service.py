"""Keep `jobwatch ui` running: start it when you log in and restart it if it stops (a macOS launchd agent).

`jobwatch service install` writes ~/Library/LaunchAgents/<LABEL>.plist and loads it; `uninstall` stops it and
removes the file. The page is then always at http://jobwatch.localhost:<port>/, and its output goes to
~/Library/Logs/jobwatch-ui.log.

A launchd agent doesn't read your shell profile, so ANTHROPIC_API_KEY set there isn't visible to it: with
`scoring.backend: claude`, chat and scoring from the page need the key in the macOS keychain item named by
`scoring.keychain`, in the agent's environment (`launchctl setenv ANTHROPIC_API_KEY ...` for the session), or
`jobwatch ui` run from a terminal instead.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

from . import APP_HOST

LABEL = "io.github.jobwatch.ui"
GONE_WAIT = 15  # seconds to wait for a replaced job to stop before loading the new one


class ServiceError(RuntimeError):
    pass


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-ui.log"


def definition(config: Path, port: int) -> dict:
    """The launchd job: this Python and jobwatch, the watchlist by absolute path, no browser tab."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobwatch.cli", "-c", str(config), "ui", "--no-browser",
                             "--port", str(port)],
        "RunAtLoad": True,       # at login
        "KeepAlive": True,       # and again if it exits
        "ThrottleInterval": 30,  # not in a tight loop when it can't start (the port is taken, the file is gone)
        "Nice": 10,              # behind what you're doing: fit scoring is never urgent
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise ServiceError(f"launchctl {' '.join(args)}: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r


def _mac():
    if sys.platform != "darwin":
        raise ServiceError("`jobwatch service` sets up a macOS login item; elsewhere, start `jobwatch ui "
                           "--no-browser` from your system's service manager (e.g. a systemd user unit)")


def _wait_gone(seconds: float = GONE_WAIT):
    """Until launchd has let go of the old job: bootout returns while a running page is still stopping, and a
    bootstrap then fails with "Bootstrap failed: 5: Input/output error"."""
    deadline = time.monotonic() + seconds
    while _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0 and time.monotonic() < deadline:
        time.sleep(0.2)


def install(config: Path, port: int = 8765) -> str:
    """Write and load the agent (replacing one installed before); returns the page's address."""
    _mac()
    config = config.expanduser().resolve()
    if not config.is_file():
        raise ServiceError(f"no watchlist at {config}: create one first (`jobwatch init` or `jobwatch ui`)")
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)  # an older version, if any
    _wait_gone()
    with path.open("wb") as f:
        plistlib.dump(definition(config, port), f)
    _launchctl("bootstrap", _domain(), str(path))
    return f"http://{APP_HOST}:{port}/"


def uninstall() -> bool:
    """Stop the agent and remove it; False if it wasn't installed."""
    _mac()
    path = plist_path()
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    if not path.exists():
        return False
    path.unlink()
    return True


def status() -> dict:
    _mac()
    path = plist_path()
    info = {"installed": path.exists(), "running": False, "pid": None, "log": str(log_path()), "url": None}
    if info["installed"]:
        args = plistlib.loads(path.read_bytes()).get("ProgramArguments", [])
        if "--port" in args:
            info["url"] = f"http://{APP_HOST}:{args[args.index('--port') + 1]}/"
    r = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
    # The job's own lines come first; nested sections (sockets, endpoints) have "state = active" of their own.
    state = re.search(r"^\s*state = (\w+)", r.stdout, re.M)
    pid = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
    info["running"] = bool(state and state.group(1) == "running")
    info["pid"] = int(pid.group(1)) if pid else None
    return info
