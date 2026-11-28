import json
import sqlite3
import time

import pytest

from jobwatch import cli, config, timing
from jobwatch.web import App


class FakeClock:
    """Each call of the clock moves it on by the next step (ms), so a measured call lasts exactly that long."""

    def __init__(self, durations_ms):
        self.steps, self.now, self.reading = iter(durations_ms), 0.0, False

    def __call__(self):
        if self.reading:  # the second reading of a pair: the call took its step
            self.now += next(self.steps) / 1000
        self.reading = not self.reading
        return self.now


def test_calls_lists_the_pages_paths_and_leaves_company_out_without_one():
    paths = [p for _, p in timing.calls()]
    assert "/api/digest?part=list" in paths and "/api/hidden" in paths and "/api/counts" in paths
    assert "/api/digest" not in paths and "/api/calendar" not in paths   # the page asks for the list and the extra
    assert not any("company" in p for p in paths)
    assert ("Company", "/api/company?q=Globex%20%26%20Co") in timing.calls(["company"], "Globex & Co")
    assert [t for t, _ in timing.calls(["QUEUE"])] == ["Queue"] * 4
    assert [t for t, _ in timing.calls(["today"], combined=True)] == ["Today"] * 3 + ["Today (one call)"]
    with pytest.raises(ValueError, match="no tab named nope"):
        timing.calls(["nope"])


def test_measure_ranks_slowest_first_with_a_fake_clock():
    sizes = {"/api/digest?part=list": (200, 2048), "/api/queue?part=list": (200, 1024), "/api/pace": (200, 10)}
    # digest runs 900, 100, 100; queue 50, 60, 70; pace 1, 2, 3 (ms)
    clock = FakeClock([900, 100, 100, 50, 60, 70, 1, 2, 3])
    rows = timing.measure(lambda path: sizes[path], [("Today", "/api/digest?part=list"),
                                                      ("Queue", "/api/queue?part=list"), ("Queue", "/api/pace")],
                          runs=3, clock=clock)
    assert [(r.path, round(r.median)) for r in rows] == [("/api/digest?part=list", 100), ("/api/queue?part=list", 60),
                                                         ("/api/pace", 2)]
    assert [round(m) for m in rows[0].ms] == [900, 100, 100] and rows[0].kb == 2
    text = timing.render(rows)
    assert text.index("/api/digest") < text.index("/api/queue") < text.index("/api/pace")
    assert "Today: /api/digest?part=list" in text and "draws its head and placeholders at 0 ms" in text


def timed(tab, path, *ms):
    t = timing.Timing(tab, path)
    t.ms = list(ms)
    return t


def test_a_tab_waits_only_on_what_its_first_data_needs():
    rows = [timed("Today", "/api/digest?part=list", 800), timed("Today", "/api/digest?part=extra", 9000),
            timed("Today", "/api/hidden", 500), timed("Queue", "/api/queue?part=list", 300),
            timed("Queue", "/api/queue?part=extra", 4000), timed("Queue", "/api/pace", 20),
            timed("Referrals", "/api/referrals", 1200), timed("Settings", "/api/settings", 30),
            timed("Today (one call)", "/api/digest", 9500)]
    got = {w["tab"]: w for w in timing.waits(rows)}
    assert got["Today"] == {"tab": "Today", "first_data_ms": 800, "complete_ms": 9000,
                            "waits_on": ["/api/digest?part=list"]}
    assert got["Queue"]["first_data_ms"] == 300 and got["Queue"]["complete_ms"] == 4000
    assert got["Referrals"]["first_data_ms"] == got["Referrals"]["complete_ms"] == 1200   # one call: waits on all
    assert got["Settings"]["first_data_ms"] == 0 and got["Settings"]["waits_on"] == []   # draws from what it has
    assert got["Today (one call)"]["first_data_ms"] == 9500                    # the old form waits for it all
    assert next(w["tab"] for w in timing.waits(rows)) == "Today (one call)"    # slowest first


def test_measure_stops_repeating_a_failing_call_and_says_why():
    def get(path):
        if path == "/api/gone":
            return 404, 20
        raise ConnectionRefusedError("refused")
    rows = {r.path: r for r in timing.measure(get, [("A", "/api/gone"), ("B", "/api/down")], runs=3)}
    assert rows["/api/gone"].error == "HTTP 404" and len(rows["/api/gone"].ms) == 1
    assert rows["/api/down"].error.startswith("ConnectionRefusedError") and rows["/api/down"].ms == []


def test_timing_command_times_the_page_over_a_tiny_store(watchlist, web, capsys):
    App(watchlist).post_fetch({})
    cli.main(["-c", str(watchlist), "timing", "-n", "2", "--json", "--tab", "Today", "--tab", "Queue",
              "--tab", "Applications"])
    out = json.loads(capsys.readouterr().out)["calls"]
    assert {c["path"] for c in out} == {"/api/digest?part=list", "/api/digest?part=extra", "/api/hidden",
                                        "/api/queue?part=list", "/api/queue?part=extra", "/api/pace",
                                        "/api/snoozed", "/api/applications"}
    assert all(len(c["runs"]) == 2 and not c["error"] for c in out)
    assert [c["median_ms"] for c in out] == sorted((c["median_ms"] for c in out), reverse=True)


def test_timing_command_prints_the_table(watchlist, web, capsys):
    App(watchlist).post_fetch({})
    cli.main(["-c", str(watchlist), "timing", "-n", "1", "--tab", "Settings"])
    out = capsys.readouterr().out
    assert "Settings: /api/settings" in out and "Settings: nothing" in out


def test_timing_over_a_copy_leaves_the_real_store_alone(watchlist, web, capsys):
    App(watchlist).post_fetch({})
    state = config.load(watchlist).state
    before = state.read_bytes()
    cli.main(["-c", str(watchlist), "timing", "--copy", "-n", "1", "--json", "--tab", "Today", "--combined"])
    out = json.loads(capsys.readouterr().out)
    assert {t["tab"] for t in out["tabs"]} == {"Today", "Today (one call)"}
    assert not any(c["error"] for c in out["calls"])
    assert state.read_bytes() == before            # Today marks its jobs seen: on the copy, not here


def test_the_copy_is_a_whole_store_and_the_original_is_only_read(watchlist, web, tmp_path):
    App(watchlist).post_fetch({})
    state = config.load(watchlist).state
    copied = timing.copy_store(state, tmp_path / "copy.db")
    with sqlite3.connect(copied) as db, sqlite3.connect(state) as orig:
        count = "SELECT COUNT(*) FROM jobs"
        assert db.execute(count).fetchone() == orig.execute(count).fetchone()


def test_cold_start_lists_each_step_in_order_and_what_the_indexes_save(watchlist, web, tmp_path, capsys):
    App(watchlist).post_fetch({})
    copied = timing.copy_store(config.load(watchlist).state, tmp_path / "copy.db")
    steps = timing.cold_start(watchlist, copied)
    assert list(steps) == ["listening", "page first byte", "first API answer", "Today's list (first data)",
                           "by-status lookup before indexes", "indexes built", "by-status lookup after indexes"]
    first = [steps[k] for k in ("listening", "page first byte", "first API answer", "Today's list (first data)")]
    assert first == sorted(first)                  # each is from the start, so they only grow
    assert "jobs_status" in " ".join(r[0] for r in sqlite3.connect(copied).execute(
        "SELECT name FROM sqlite_master WHERE type='index'"))
    assert "Today's list (first data)" in timing.render_cold(steps)
    with pytest.raises(SystemExit, match=r"--cold .* --copy"):
        cli.main(["-c", str(watchlist), "timing", "--cold"])


def test_ui_copy_serves_the_page_over_a_copy_and_changes_nothing_in_the_store(watchlist, web, monkeypatch, capsys):
    import http.client
    import threading

    App(watchlist).post_fetch({})
    state = config.load(watchlist).state
    before = state.read_bytes()
    opened = []
    monkeypatch.setattr("jobwatch.cli.webbrowser.open", opened.append)
    stop = threading.Event()
    monkeypatch.setattr(cli, "wait_for_interrupt", stop.wait)  # the wait for Ctrl+C
    answered = []

    def ask():  # the browser opening the page, then Ctrl+C
        for _ in range(200):
            if opened:
                port = int(opened[0].rsplit(":", 1)[1].rstrip("/"))
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                conn.request("GET", "/", headers={"Host": f"jobwatch.localhost:{port}"})
                answered.append(conn.getresponse().status)
                conn.close()
                break
            time.sleep(0.05)
        stop.set()

    t = threading.Thread(target=ask)
    t.start()
    cli.main(["-c", str(watchlist), "ui", "--copy", "--port", "0"])
    t.join(10)
    assert answered == [200] and opened and ".localhost:" in opened[0]
    assert state.read_bytes() == before


def test_profile_names_where_a_call_spends_its_time(watchlist, web):
    app = App(watchlist)
    app.post_fetch({})
    text = timing.profile(app, "/api/queue?part=list")
    assert "get_queue" in text and "cumulative" in text and "internal time" in text
