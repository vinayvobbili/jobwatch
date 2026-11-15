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


def test_install_writes_a_login_item_for_this_watchlist(launchd, watchlist, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/opt/tools/bin:/usr/bin:/bin")
    cli.main(["-c", str(watchlist), "service", "install", "--port", "8800"])
    assert "http://jobwatch.localhost:8800/" in capsys.readouterr().out
    job = plistlib.loads(service.plist_path().read_bytes())
    assert job["Label"] == service.LABEL and job["RunAtLoad"] and job["KeepAlive"]
    assert job["ProgramArguments"] == [sys.executable, "-m", "jobwatch.cli", "-c", str(watchlist.resolve()), "ui",
                                       "--no-browser", "--port", "8800"]
    # the shell's PATH: launchd's own lacks Homebrew, and Tailor resume runs node from there
    assert job["EnvironmentVariables"]["PATH"] == "/opt/tools/bin:/usr/bin:/bin"
    assert [c[0] for c in launchd] == ["bootout", "print", "bootstrap"]
    assert service.status() == {"installed": True, "running": True, "pid": 4242, "log": str(service.log_path()),
                                "url": "http://jobwatch.localhost:8800/"}
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


def test_install_needs_a_watchlist(launchd, tmp_path):
    with pytest.raises(SystemExit, match="no watchlist"):
        cli.main(["-c", str(tmp_path / "missing.yaml"), "service", "install"])


def test_an_unknown_system_gets_a_clear_error(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "freebsd14")
    with pytest.raises(SystemExit, match="macOS, Linux and Windows"):
        cli.main(["service", "status"])
    assert service.installed_port() is None


SPAWN_FAILED = ("io.github.jobwatch.ui = {\n\tactive count = 0\n\tstate = not running\n"
                "\tprogram = /opt/app/bin/python\n\tendpoints = {\n\t\tstate = active\n\t}\n"
                "\tjob state = spawn failed\n\tlast exit reason = OS_REASON_CODESIGNING\n}\n")


def test_why_not_running_reads_the_jobs_own_lines():
    why = service.why_not_running(SPAWN_FAILED)
    assert why["job_state"] == "spawn failed" and why["exit_reason"] == "OS_REASON_CODESIGNING"
    assert "jobwatch service install" in why["hint"]
    assert service.why_not_running("\tstate = waiting\n\tjob state = exited\n\tlast exit reason = exited: 1\n") == {
        "job_state": "exited", "exit_reason": "exited: 1"}
    assert service.why_not_running("") == {}


def test_status_says_why_an_installed_job_is_not_running(tmp_path, monkeypatch, watchlist, capsys):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    out = {"text": SPAWN_FAILED, "code": 0}

    def run(cmd, **kwargs):
        if cmd[1] == "print":
            return subprocess.CompletedProcess(cmd, out["code"], out["text"], "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(service.subprocess, "run", run)
    monkeypatch.setattr(service, "_wait_gone", lambda: None)
    service.install(watchlist)
    cli.main(["service", "status"])
    shown = capsys.readouterr().out
    assert "not running: see the log" in shown and "Job state: spawn failed" in shown
    assert "OS_REASON_CODESIGNING" in shown and "jobwatch service install" in shown
    out.update(text="", code=113)  # launchctl print fails: as before
    cli.main(["service", "status"])
    shown = capsys.readouterr().out
    assert "not running: see the log" in shown and "Job state" not in shown and "register" not in shown


# ---- Linux and Windows: the commands and files they would make, with a fake runner (nothing real is run) ----

class FakeRunner:
    """Records each command; answers with the first reply whose words are all in it, else success."""

    def __init__(self):
        self.calls, self.replies = [], []

    def __call__(self, cmd):
        self.calls.append(cmd)
        for words, code, out, err in self.replies:
            if all(w in cmd for w in words):
                return subprocess.CompletedProcess(cmd, code, out, err)
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def linux(tmp_path, monkeypatch):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    runner = FakeRunner()
    monkeypatch.setattr(service, "_run", runner)
    return runner


def test_linux_install_writes_a_user_unit_and_enables_it(linux, watchlist, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/opt/tools/bin:/usr/bin")
    cli.main(["-c", str(watchlist), "service", "install", "--port", "8800"])
    out = capsys.readouterr().out
    assert "http://jobwatch.localhost:8800/" in out and "loginctl enable-linger" in out
    unit = (tmp_path / ".config" / "systemd" / "user" / "jobwatch-ui.service").read_text()
    assert (f"ExecStart={sys.executable} -m jobwatch.cli -c {watchlist.resolve()} ui --no-browser --port 8800\n"
            in unit)
    assert "Environment=PATH=/opt/tools/bin:/usr/bin\n" in unit and "Environment=PYTHONUNBUFFERED=1\n" in unit
    assert "Restart=on-failure\n" in unit and "WantedBy=default.target\n" in unit
    assert f"StandardOutput=append:{tmp_path}/.local/state/jobwatch/ui.log\n" in unit
    assert [c[2:] for c in linux.calls] == [["show-environment"], ["daemon-reload"],
                                            ["enable", "--now", "jobwatch-ui.service"],
                                            ["restart", "jobwatch-ui.service"]]
    assert all(c[:2] == ["systemctl", "--user"] for c in linux.calls)
    assert service.installed_port() == 8800


def test_linux_unit_quotes_paths_with_spaces_and_specials(linux, tmp_path, monkeypatch):
    config = tmp_path / "my jobs" / "100%$ list.yaml"
    config.parent.mkdir()
    config.write_text("companies: []\n")
    monkeypatch.setattr(service.sys, "executable", "/opt/my tools/bin/python3")
    monkeypatch.setenv("PATH", "/opt/my tools/bin:/usr/bin")
    service.install(config)
    unit = service.SystemdBackend().unit_path().read_text()
    escaped = str(config.resolve()).replace("%", "%%").replace("$", "$$")
    assert f'ExecStart="/opt/my tools/bin/python3" -m jobwatch.cli -c "{escaped}" ui --no-browser --port 8765\n' in unit
    assert 'Environment="PATH=/opt/my tools/bin:/usr/bin"\n' in unit
    assert service.installed_port() == 8765


def test_linux_status_uses_is_active(linux, watchlist, capsys):
    service.install(watchlist, 8801)
    linux.replies += [(["is-active"], 0, "active\n", ""), (["--property=MainPID"], 0, "777\n", "")]
    assert service.status() == {"installed": True, "running": True, "pid": 777, "log": str(service.log_path()),
                                "url": "http://jobwatch.localhost:8801/"}
    linux.replies[:] = [(["is-active"], 3, "failed\n", "")]
    s = service.status()
    assert not s["running"] and s["job_state"] == "failed" and "journalctl --user -u jobwatch-ui" in s["hint"]
    cli.main(["service", "status"])
    shown = capsys.readouterr().out
    assert "not running: see the log" in shown and "Job state: failed" in shown and "journalctl" in shown


def test_linux_uninstall_disables_and_removes_the_unit(linux, watchlist, capsys):
    assert service.uninstall() is False and linux.calls == []
    service.install(watchlist)
    linux.calls.clear()
    cli.main(["service", "uninstall"])
    assert "Removed" in capsys.readouterr().out
    assert [c[2:] for c in linux.calls] == [["disable", "--now", "jobwatch-ui.service"], ["daemon-reload"]]
    assert not service.SystemdBackend().unit_path().exists()
    assert service.status()["installed"] is False and service.installed_port() is None


def test_linux_without_systemd_says_what_to_do(linux, watchlist):
    linux.replies.append((["show-environment"], 127, "", "systemctl: command not found"))
    with pytest.raises(SystemExit, match=r"isn't installed.*jobwatch ui --no-browser"):
        cli.main(["-c", str(watchlist), "service", "install"])
    assert not service.SystemdBackend().unit_path().exists()
    linux.replies[:] = [(["show-environment"], 1, "", "Failed to connect to bus: No medium found")]
    with pytest.raises(SystemExit, match=r"user manager isn't running \(Failed to connect.*jobwatch ui --no-browser"):
        cli.main(["-c", str(watchlist), "service", "install"])


def test_a_missing_program_is_exit_code_127(monkeypatch):
    def gone(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(service.subprocess, "run", gone)
    assert service._run(["systemctl", "--user", "x"]).returncode == 127


def test_linux_a_failing_systemctl_step_is_reported(linux, watchlist):
    linux.replies.append((["enable"], 1, "", "Unit is masked"))
    with pytest.raises(SystemExit, match=r"enable --now jobwatch-ui\.service: Unit is masked"):
        cli.main(["-c", str(watchlist), "service", "install"])


@pytest.fixture
def windows(tmp_path, monkeypatch):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local Data"))
    monkeypatch.setenv("USERNAME", "ada")
    monkeypatch.setenv("USERDOMAIN", "INITECH")
    py = tmp_path / "Program Files" / "Python 3" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_text("")
    monkeypatch.setattr(service.sys, "executable", str(py))
    runner = FakeRunner()
    monkeypatch.setattr(service, "_run", runner)
    return runner


def read_task(tmp_path):
    from xml.etree import ElementTree as ET
    raw = (tmp_path / "Local Data" / "jobwatch" / "jobwatch-ui-task.xml").read_bytes()
    assert raw[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 with a byte-order mark
    return ET.fromstring(raw.decode("utf-16")), {"t": service.TASK_NS}


def test_windows_install_makes_a_logon_task_without_admin(windows, tmp_path, capsys):
    cfg = tmp_path / "My Jobs" / "jobwatch.yaml"
    cfg.parent.mkdir()
    cfg.write_text("companies: []\n")
    pythonw = tmp_path / "Program Files" / "Python 3" / "pythonw.exe"
    pythonw.write_text("")
    cli.main(["-c", str(cfg), "service", "install", "--port", "8802"])
    assert "http://jobwatch.localhost:8802/" in capsys.readouterr().out
    xml_file = tmp_path / "Local Data" / "jobwatch" / "jobwatch-ui-task.xml"
    assert windows.calls == [
        ["schtasks", "/End", "/TN", "jobwatch-ui"],
        ["schtasks", "/Create", "/TN", "jobwatch-ui", "/XML", str(xml_file), "/F"],
        ["schtasks", "/Run", "/TN", "jobwatch-ui"]]
    root, ns = read_task(tmp_path)
    assert root.findtext(".//t:Command", namespaces=ns) == str(pythonw)
    assert root.findtext(".//t:Arguments", namespaces=ns) == (
        f'-m jobwatch.cli -c "{cfg.resolve()}" ui --no-browser --port 8802 '
        f'--log "{tmp_path / "Local Data" / "jobwatch" / "ui.log"}"')
    assert root.find(".//t:LogonTrigger", ns) is not None
    assert root.findtext(".//t:RunLevel", namespaces=ns) == "LeastPrivilege"
    assert root.findtext(".//t:RestartOnFailure/t:Count", namespaces=ns) == "999"
    assert root.findtext(".//t:Principal/t:UserId", namespaces=ns) == "INITECH\\ada"
    assert service.installed_port() == 8802


def test_windows_falls_back_to_python_without_pythonw(windows, watchlist):
    service.install(watchlist)
    root, ns = read_task(watchlist.parent)
    assert root.findtext(".//t:Command", namespaces=ns) == service.sys.executable


def test_windows_status_reads_schtasks_output(windows, watchlist):
    windows.replies.append((["/Query"], 1, "", "ERROR: The system cannot find the file specified."))
    assert service.status() == {"installed": False, "running": False, "pid": None, "log": str(service.log_path()),
                                "url": None}
    windows.replies.clear()
    service.install(watchlist, 8803)
    listing = "Folder: \\\nTaskName:      \\jobwatch-ui\nStatus:                               Running\n"
    windows.replies.append((["/Query"], 0, listing, ""))
    s = service.status()
    assert s["installed"] and s["running"] and s["url"] == "http://jobwatch.localhost:8803/"
    assert windows.calls[-1] == ["schtasks", "/Query", "/TN", "jobwatch-ui", "/FO", "LIST", "/V"]
    windows.replies[:] = [(["/Query"], 0, listing.replace("Running", "Ready"), "")]
    s = service.status()
    assert not s["running"] and s["job_state"] == "Ready"


def test_windows_uninstall_ends_deletes_and_removes_the_xml(windows, watchlist, tmp_path, capsys):
    windows.replies.append((["/Query"], 1, "", "ERROR"))
    assert service.uninstall() is False
    windows.replies.clear()
    service.install(watchlist)
    windows.calls.clear()
    cli.main(["service", "uninstall"])
    assert "Removed" in capsys.readouterr().out
    assert windows.calls == [["schtasks", "/Query", "/TN", "jobwatch-ui"], ["schtasks", "/End", "/TN", "jobwatch-ui"],
                             ["schtasks", "/Delete", "/TN", "jobwatch-ui", "/F"]]
    assert not (tmp_path / "Local Data" / "jobwatch" / "jobwatch-ui-task.xml").exists()
    assert service.installed_port() is None


def test_windows_a_failed_create_is_reported(windows, watchlist):
    windows.replies.append((["/Create"], 1, "", "ERROR: Access is denied."))
    with pytest.raises(SystemExit, match="Access is denied"):
        cli.main(["-c", str(watchlist), "service", "install"])


def test_the_ui_log_option_sends_output_to_a_file(tmp_path, monkeypatch, watchlist):
    class Server:
        def serve_forever(self):
            print("hello from the page")
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr("jobwatch.web.serve", lambda *a, **k: Server())
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # restored after the test
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    log = tmp_path / "logs" / "ui.log"
    cli.main(["-c", str(watchlist), "ui", "--no-browser", "--log", str(log)])
    sys.stdout.flush()
    assert "hello from the page" in log.read_text()
