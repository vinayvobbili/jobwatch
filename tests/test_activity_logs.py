import json

import pytest

from jobwatch import config, logtail
from jobwatch.web import App

from .conftest import TOKEN, request


def _with_logs(watchlist, tmp_path, body):
    watchlist.write_text(watchlist.read_text() + body)


def test_the_setting_names_each_log_and_expands_its_path(watchlist, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _with_logs(watchlist, tmp_path, "ui:\n  activity_logs:\n    - {name: Globex watcher, path: '~/logs/globex.log'}\n")
    cfg = config.load(watchlist)
    assert [(x.name, x.path) for x in cfg.ui.activity_logs] == [("Globex watcher", tmp_path / "logs" / "globex.log")]


@pytest.mark.parametrize("body, says", [
    ("ui: {activity: []}\n", "unknown ui setting"),
    ("ui: {activity_logs: nope}\n", "ui.activity_logs looks like"),
    ("ui: {activity_logs: [oops]}\n", "entries look like"),
    ("ui: {activity_logs: [{name: A, path: /x, mode: w}]}\n", "unknown ui.activity_logs setting"),
    ("ui: {activity_logs: [{name: A}]}\n", "needs a name and a path"),
    ("ui: {activity_logs: [{name: A, path: /x}, {name: A, path: /y}]}\n", "names A twice"),
])
def test_a_bad_setting_is_a_config_error(watchlist, tmp_path, body, says):
    _with_logs(watchlist, tmp_path, body)
    with pytest.raises(config.ConfigError, match=says):
        config.load(watchlist)


def test_lines_are_parsed_newest_first_with_times_when_present(tmp_path):
    log = tmp_path / "globex.log"
    log.write_text("2026-01-02 03:04:05 polled: 0 queued\n\nno time here\n2026-01-02T03:05 done\n")
    out = logtail.activity_logs([config.ActivityLog("Globex watcher", log)])
    assert out == [{"name": "Globex watcher", "exists": True, "lines": [
        {"at": "2026-01-02T03:05:00", "text": "done"},
        {"at": None, "text": "no time here"},
        {"at": "2026-01-02T03:04:05", "text": "polled: 0 queued"}]}]


def test_only_the_last_fifty_lines_are_kept_and_a_missing_file_is_quiet(tmp_path):
    log = tmp_path / "big.log"
    log.write_text("".join(f"2026-01-02 03:04:{i % 60:02d} line {i}\n" for i in range(200)))
    out = logtail.activity_logs([config.ActivityLog("Big", log), config.ActivityLog("Gone", tmp_path / "gone.log")])
    assert len(out[0]["lines"]) == 50 and out[0]["lines"][0]["text"] == "line 199"
    assert out[1] == {"name": "Gone", "exists": False, "lines": []}


def test_only_configured_logs_are_served(server, watchlist, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the page\n")
    log = tmp_path / "globex.log"
    log.write_text("2026-01-02 03:04:05 hello\n")
    _with_logs(watchlist, tmp_path, f"ui:\n  activity_logs:\n    - {{name: Globex watcher, path: {log}}}\n")
    headers = {"X-Jobwatch-Token": TOKEN}
    status, body = request(server, "GET", f"/api/activity-logs?path={secret}&name=secret", headers=headers)
    logs = json.loads(body)["logs"]
    assert status == 200 and [x["name"] for x in logs] == ["Globex watcher"]
    assert logs[0]["lines"] == [{"at": "2026-01-02T03:04:05", "text": "hello"}]
    assert "not for the page" not in body.decode()
    assert request(server, "POST", "/api/activity-logs", {}, headers=headers)[0] in (404, 405)


def test_no_setting_means_no_logs(watchlist):
    assert App(watchlist).get_activity_logs({}) == {"logs": []}


def test_the_page_shows_a_chip_and_badge_per_log(server):
    page = request(server, "GET", "/")[1].decode()
    assert 'api("/api/activity-logs")' in page and "src-badge" in page and "No log yet" in page
