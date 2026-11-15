"""Keep `jobwatch ui` running: start it when you log in and restart it if it stops.

`jobwatch service install` sets that up with what your system has, one small backend per platform:

- macOS: a launchd agent, ~/Library/LaunchAgents/<LABEL>.plist; output in ~/Library/Logs/jobwatch-ui.log.
- Linux: a systemd user unit, ~/.config/systemd/user/jobwatch-ui.service; output in ~/.local/state/jobwatch/ui.log
  (`loginctl enable-linger $USER` keeps it running when you're logged out).
- Windows: a per-user Task Scheduler task "jobwatch-ui" (no admin rights) that runs at logon, is started again
  within 5 minutes if it has stopped, and shows no console window; output in %LOCALAPPDATA%\\jobwatch\\ui.log.

`uninstall` stops it and removes what install made. The page is then always at http://jobwatch.localhost:<port>/.

Every process is started by `_run`, so the tests fake it.

A service doesn't read your shell profile, so ANTHROPIC_API_KEY set there isn't visible to it: with
`scoring.backend: claude`, chat and scoring from the page need the key in the macOS keychain item named by
`scoring.keychain` (or printed by `scoring.key_command`), in the service's environment (macOS: `launchctl setenv
ANTHROPIC_API_KEY ...`; Linux: `systemctl --user edit jobwatch-ui` with an Environment= line; Windows: a user
environment variable), or `jobwatch ui` run from a terminal instead.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from . import APP_HOST

LABEL = "io.github.jobwatch.ui"
UNIT = "jobwatch-ui.service"  # the systemd user unit
TASK = "jobwatch-ui"          # the Windows scheduled task
WATCH_MINUTES = 5  # Windows: how often Task Scheduler looks for a stopped page and starts it
GONE_WAIT = 15 # seconds to wait for a replaced job to stop before loading the new one

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


class ServiceError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """The one place a process is started. A program that isn't there comes back as exit code 127 rather than
    raising, so each backend can say what to do about it."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: command not found")


def _failed(cmd: list[str], r: subprocess.CompletedProcess) -> ServiceError:
    return ServiceError(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip() or r.returncode}")


def _ui_args(config: Path, port: int) -> list[str]:
    """What every backend runs after the Python: jobwatch, the watchlist by absolute path, no browser tab."""
    return ["-m", "jobwatch.cli", "-c", str(config), "ui", "--no-browser", "--port", str(port)]


def _resolved_config(config: Path) -> Path:
    config = config.expanduser().resolve()
    if not config.is_file():
        raise ServiceError(f"no watchlist at {config}: create one first (`jobwatch init` or `jobwatch ui`)")
    return config


def _url(port) -> str:
    return f"http://{APP_HOST}:{port}/"


# ---- macOS: launchd ----

def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _mac_log() -> Path:
    return Path.home() / "Library" / "Logs" / "jobwatch-ui.log"


def definition(config: Path, port: int) -> dict:
    """The launchd job: this Python and jobwatch, the watchlist by absolute path, no browser tab, and the PATH of
    the shell that installed it (launchd's own is /usr/bin:/bin..., without Homebrew: Tailor resume runs node)."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, *_ui_args(config, port)],
        "RunAtLoad": True,       # at login
        "KeepAlive": True,       # and again if it exits
        "ThrottleInterval": 30,  # not in a tight loop when it can't start (the port is taken, the file is gone)
        "Nice": 10,              # behind what you're doing: fit scoring is never urgent
        "LowPriorityIO": True,
        "StandardOutPath": str(_mac_log()),
        "StandardErrorPath": str(_mac_log()),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "PATH": os.environ.get("PATH", os.defpath)},
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _mac():
    """For the macOS-only launchd jobs that share this module's helpers (the daily backup)."""
    if sys.platform != "darwin":
        raise ServiceError("this sets up a macOS login item; elsewhere, run it from your system's scheduler "
                           "(cron, a systemd timer, Task Scheduler)")


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["launchctl", *args]
    r = _run(cmd)
    if check and r.returncode:
        raise _failed(cmd, r)
    return r


def _wait_gone(seconds: float = GONE_WAIT):
    """Until launchd has let go of the old job: bootout returns while a running page is still stopping, and a
    bootstrap then fails with "Bootstrap failed: 5: Input/output error"."""
    deadline = time.monotonic() + seconds
    while _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0 and time.monotonic() < deadline:
        time.sleep(0.2)


def why_not_running(printed: str) -> dict:
    """The job's own "job state" and "last exit reason" from `launchctl print` text (either may be missing), plus
    a hint when macOS refused to start the program (code signing: often the virtualenv's Python changed)."""
    why = {}
    for key, name in (("job state", "job_state"), ("last exit reason", "exit_reason")):
        m = re.search(rf"^\s*{key} = (.+?)\s*$", printed, re.M)
        if m:
            why[name] = m.group(1)
    if why.get("exit_reason") == "OS_REASON_CODESIGNING" or why.get("job_state") == "spawn failed":
        why["hint"] = ("macOS wouldn't start the program (often the virtualenv's Python changed since install): "
                       "run `jobwatch service install` to register it again.")
    return why


class MacBackend:
    note = ""

    def log_path(self) -> Path:
        return _mac_log()

    def install(self, config: Path, port: int) -> str:
        """Write and load the agent (replacing one installed before); returns the page's address."""
        config = _resolved_config(config)
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path().parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)  # an older version, if any
        _wait_gone()
        with path.open("wb") as f:
            plistlib.dump(definition(config, port), f)
        _launchctl("bootstrap", _domain(), str(path))
        return _url(port)

    def uninstall(self) -> bool:
        """Stop the agent and remove it; False if it wasn't installed."""
        path = plist_path()
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
        if not path.exists():
            return False
        path.unlink()
        return True

    def installed_port(self) -> int | None:
        try:
            args = plistlib.loads(plist_path().read_bytes()).get("ProgramArguments", [])
            return int(args[args.index("--port") + 1])
        except (OSError, ValueError, IndexError, plistlib.InvalidFileException):
            return None

    def status(self) -> dict:
        path = plist_path()
        info = {"installed": path.exists(), "running": False, "pid": None, "log": str(self.log_path()), "url": None}
        if info["installed"]:
            args = plistlib.loads(path.read_bytes()).get("ProgramArguments", [])
            if "--port" in args:
                info["url"] = _url(args[args.index("--port") + 1])
        r = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
        # The job's own lines come first; nested sections (sockets, endpoints) have "state = active" of their own.
        state = re.search(r"^\s*state = (\w+)", r.stdout, re.M)
        pid = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
        info["running"] = bool(state and state.group(1) == "running")
        info["pid"] = int(pid.group(1)) if pid else None
        if info["installed"] and not info["running"] and r.returncode == 0:
            info.update(why_not_running(r.stdout))
        return info


# ---- Linux: a systemd user unit ----

def _systemd_quote(arg: str) -> str:
    """One word of an ExecStart= or Environment= line: as it is when it has only plain characters, else in double
    quotes with systemd's escapes (a backslash, a quote, % for specifiers, $ for variables)."""
    if re.fullmatch(r"[A-Za-z0-9_@+=:,./-]+", arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


class SystemdBackend:
    """`systemctl --user`: a unit under ~/.config/systemd/user, enabled for default.target (your login)."""

    note = "To keep it running when you're logged out too, run `loginctl enable-linger $USER` once."

    def __init__(self, run=None):
        self._run = run or (lambda cmd: _run(cmd))

    def unit_path(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / UNIT

    def log_path(self) -> Path:
        return Path.home() / ".local" / "state" / "jobwatch" / "ui.log"

    def unit(self, config: Path, port: int) -> str:
        """The unit: this Python and jobwatch, the watchlist by absolute path, no browser tab, and the PATH of the
        shell that installed it (a user unit's own is short, without ~/.local/bin or Homebrew)."""
        exec_start = " ".join(_systemd_quote(a) for a in [sys.executable, *_ui_args(config, port)])
        env = ["PYTHONUNBUFFERED=1", f"PATH={os.environ.get('PATH', os.defpath)}"]
        log = self.log_path()
        return ("[Unit]\n"
                "Description=jobwatch ui: the job search page\n"
                "\n[Service]\n"
                f"ExecStart={exec_start}\n"
                + "".join(f"Environment={_systemd_quote(e)}\n" for e in env)
                + "Restart=on-failure\n"
                "RestartSec=30\n"  # not in a tight loop when it can't start (the port is taken, the file is gone)
                "Nice=10\n"        # behind what you're doing: fit scoring is never urgent
                "IOSchedulingPriority=7\n"
                f"StandardOutput=append:{log}\n"
                f"StandardError=append:{log}\n"
                "\n[Install]\n"
                "WantedBy=default.target\n")

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["systemctl", "--user", *args]
        r = self._run(cmd)
        if check and r.returncode:
            raise _failed(cmd, r)
        return r

    def _need_systemd(self):
        r = self._run(["systemctl", "--user", "show-environment"])
        if r.returncode:
            why = ("`systemctl` isn't installed" if r.returncode == 127
                   else f"systemd's user manager isn't running ({(r.stderr or r.stdout).strip() or r.returncode})")
            raise ServiceError(f"{why}: this system can't keep jobwatch running as a service (a container, or WSL "
                               "without systemd?). Run `jobwatch ui --no-browser` yourself, from whatever starts "
                               "things on your system")

    def install(self, config: Path, port: int) -> str:
        config = _resolved_config(config)
        self._need_systemd()
        path = self.unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path().parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.unit(config, port))
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", UNIT)
        self._systemctl("restart", UNIT)  # enable --now leaves a page already running (an older install) as it was
        return _url(port)

    def uninstall(self) -> bool:
        path = self.unit_path()
        if not path.exists():
            return False
        self._systemctl("disable", "--now", UNIT, check=False)
        path.unlink()
        self._systemctl("daemon-reload", check=False)
        return True

    def installed_port(self) -> int | None:
        try:
            m = re.search(r"^ExecStart=.* --port (\d+)\s*$", self.unit_path().read_text(), re.M)
        except OSError:
            return None
        return int(m.group(1)) if m else None

    def status(self) -> dict:
        info = {"installed": self.unit_path().exists(), "running": False, "pid": None, "log": str(self.log_path()),
                "url": None}
        if not info["installed"]:
            return info
        port = self.installed_port()
        info["url"] = _url(port) if port else None
        state = self._systemctl("is-active", UNIT, check=False).stdout.strip()  # active, inactive, failed, ...
        info["running"] = state == "active"
        if info["running"]:
            pid = self._systemctl("show", UNIT, "--property=MainPID", "--value", check=False).stdout.strip()
            info["pid"] = int(pid) if pid.isdigit() and int(pid) else None
        elif state:
            info["job_state"] = state
            info["hint"] = f"`journalctl --user -u {UNIT}` has what it printed before it stopped."
        return info


# ---- Windows: a per-user scheduled task ----

def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


class TaskSchedulerBackend:
    """`schtasks`: a task for your user, at logon, with limited rights (no admin). It is made from an XML file,
    the one way to ask for a restart on failure or a repeating trigger, and runs pythonw, which has no console
    window, so the page's output goes to the log through `jobwatch ui --log`. A repeating trigger starts a page
    that has stopped. Status reads schtasks' English labels."""

    note = ""

    def __init__(self, run=None):
        self._run = run or (lambda cmd: _run(cmd))

    def _dir(self) -> Path:
        return _local_appdata() / "jobwatch"

    def xml_path(self) -> Path:
        return self._dir() / "jobwatch-ui-task.xml"

    def log_path(self) -> Path:
        return self._dir() / "ui.log"

    @staticmethod
    def _program() -> str:
        """pythonw.exe beside this Python (no console window), else this Python itself."""
        exe = Path(sys.executable)
        w = exe.with_name("pythonw.exe")
        return str(w if w.exists() else exe)

    def task_xml(self, config: Path, port: int) -> str:
        args = subprocess.list2cmdline([*_ui_args(config, port), "--log", str(self.log_path())])
        user, domain = os.environ.get("USERNAME", ""), os.environ.get("USERDOMAIN", "")
        who = escape(f"{domain}\\{user}" if user and domain else user)
        user_id = f"<UserId>{who}</UserId>" if who else ""
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            f'<Task version="1.4" xmlns="{TASK_NS}">\n'
            "  <RegistrationInfo><Description>jobwatch ui: the job search page, from logon</Description>"
            "</RegistrationInfo>\n"
            # At logon, and again every WATCH_MINUTES: IgnoreNew leaves a running page alone, so a tick only starts
            # one that has stopped. RestartOnFailure alone doesn't: on a real Windows runner a killed pythonw was
            # not restarted (Task Scheduler counts the exit as the task completing).
            "  <Triggers>"
            f"<LogonTrigger><Enabled>true</Enabled>{user_id}</LogonTrigger>"
            "<TimeTrigger><StartBoundary>2024-01-01T00:00:00</StartBoundary><Enabled>true</Enabled>"
            f"<Repetition><Interval>PT{WATCH_MINUTES}M</Interval></Repetition></TimeTrigger>"
            "</Triggers>\n"
            f'  <Principals><Principal id="Author">{user_id}<LogonType>InteractiveToken</LogonType>'
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <StartWhenAvailable>true</StartWhenAvailable>\n"
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "    <Priority>7</Priority>\n"  # below normal: fit scoring is never urgent
            "    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>\n"
            "    <Enabled>true</Enabled>\n"
            "  </Settings>\n"
            f'  <Actions Context="Author"><Exec><Command>{escape(self._program())}</Command>'
            f"<Arguments>{escape(args)}</Arguments></Exec></Actions>\n"
            "</Task>\n")

    def _schtasks(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["schtasks", *args]
        r = self._run(cmd)
        if check and r.returncode:
            raise _failed(cmd, r)
        return r

    def install(self, config: Path, port: int) -> str:
        config = _resolved_config(config)
        self.xml_path().parent.mkdir(parents=True, exist_ok=True)
        self._schtasks("/End", "/TN", TASK, check=False)  # an older version still running, if any
        # UTF-16 with a byte-order mark is what schtasks reads reliably
        self.xml_path().write_bytes(self.task_xml(config, port).encode("utf-16"))
        self._schtasks("/Create", "/TN", TASK, "/XML", str(self.xml_path()), "/F")
        self._schtasks("/Run", "/TN", TASK)
        return _url(port)

    def uninstall(self) -> bool:
        installed = self._schtasks("/Query", "/TN", TASK, check=False).returncode == 0
        if installed:
            self._schtasks("/End", "/TN", TASK, check=False)
            self._schtasks("/Delete", "/TN", TASK, "/F")
        had_file = self.xml_path().exists()
        self.xml_path().unlink(missing_ok=True)
        return installed or had_file

    def installed_port(self) -> int | None:
        try:
            root = ET.fromstring(self.xml_path().read_bytes().decode("utf-16"))
        except (OSError, ValueError, ET.ParseError):
            return None
        m = re.search(r"--port (\d+)", root.findtext(f".//{{{TASK_NS}}}Arguments") or "")
        return int(m.group(1)) if m else None

    def status(self) -> dict:
        info = {"installed": False, "running": False, "pid": None, "log": str(self.log_path()), "url": None}
        r = self._schtasks("/Query", "/TN", TASK, "/FO", "LIST", "/V", check=False)
        if r.returncode:
            return info
        info["installed"] = True
        port = self.installed_port()
        info["url"] = _url(port) if port else None
        m = re.search(r"^Status:\s*(.+?)\s*$", r.stdout, re.M)
        state = m.group(1) if m else ""
        info["running"] = state == "Running"
        if not info["running"] and state:
            info["job_state"] = state
        return info


# ---- one interface, chosen by platform ----

def backend():
    if sys.platform == "darwin":
        return MacBackend()
    if sys.platform.startswith("linux"):
        return SystemdBackend()
    if sys.platform == "win32":
        return TaskSchedulerBackend()
    raise ServiceError("`jobwatch service` works on macOS, Linux and Windows; elsewhere, start `jobwatch ui "
                       "--no-browser` from your system's service manager")


def log_path() -> Path:
    return backend().log_path()


def note() -> str:
    """A line to print after a successful install (empty when there is none)."""
    return backend().note


def install(config: Path, port: int = 8765) -> str:
    """Set up and start the service (replacing one installed before); returns the page's address."""
    return backend().install(config, port)


def uninstall() -> bool:
    """Stop the service and remove it; False if it wasn't installed."""
    return backend().uninstall()


def installed_port() -> int | None:
    """The port the installed service serves on, or None (not installed, or no service on this system)."""
    try:
        return backend().installed_port()
    except ServiceError:
        return None


def status() -> dict:
    return backend().status()
