import plistlib
import subprocess
import sys

import pytest

from jobwatch import cli, service


@pytest.fixture
def launchd(tmp_path, monkeypatch):
    """A fake home and launchctl: records the calls, reports the job as running once bootstrapped."""
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    calls, loaded = [], []

    def run(cmd, **kwargs):
        calls.append(cmd[1:])
        if cmd[1] == "bootstrap":
            loaded.append(True)
        # Shaped like launchctl print: nested sections have states of their own after the job's.
        out = ("\tstate = running\n\tpid = 4242\n\tendpoints = {\n\t\tstate = active\n\t}\n"
               if cmd[1] == "print" and loaded else "")
        return subprocess.CompletedProcess(cmd, 0 if out or cmd[1] != "print" else 113, out, "")
    monkeypatch.setattr(service.subprocess, "run", run)
    return calls


def test_install_writes_a_login_item_for_this_watchlist(launchd, watchlist, capsys):
    cli.main(["-c", str(watchlist), "service", "install", "--port", "8800"])
    assert "http://127.0.0.1:8800/" in capsys.readouterr().out
    job = plistlib.loads(service.plist_path().read_bytes())
    assert job["Label"] == service.LABEL and job["RunAtLoad"] and job["KeepAlive"]
    assert job["ProgramArguments"] == [sys.executable, "-m", "jobwatch.cli", "-c", str(watchlist.resolve()), "ui",
                                       "--no-browser", "--port", "8800"]
    assert [c[0] for c in launchd] == ["bootout", "print", "bootstrap"]
    assert service.status() == {"installed": True, "running": True, "pid": 4242, "log": str(service.log_path()),
                                "url": "http://127.0.0.1:8800/"}
    cli.main(["service", "uninstall"])
    assert not service.plist_path().exists() and "Removed" in capsys.readouterr().out
    cli.main(["service", "status"])
    assert "Not installed" in capsys.readouterr().out


def test_a_reinstall_waits_for_the_old_page_to_stop(tmp_path, monkeypatch, watchlist):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    calls, stopping = [], [2]  # launchd still lists the old job twice after bootout

    def run(cmd, **kwargs):
        calls.append(cmd[1])
        if cmd[1] == "print":
            stopping[0] -= 1
            return subprocess.CompletedProcess(cmd, 0 if stopping[0] >= 0 else 113, "", "")
        if cmd[1] == "bootstrap" and stopping[0] >= 0:
            return subprocess.CompletedProcess(cmd, 5, "", "Bootstrap failed: 5: Input/output error")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(service.subprocess, "run", run)
    service.install(watchlist)
    assert calls == ["bootout", "print", "print", "print", "bootstrap"]


def test_install_needs_a_watchlist_and_a_mac(launchd, tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="no watchlist"):
        cli.main(["-c", str(tmp_path / "missing.yaml"), "service", "install"])
    monkeypatch.setattr(service.sys, "platform", "linux")
    with pytest.raises(SystemExit, match="macOS"):
        cli.main(["service", "status"])
