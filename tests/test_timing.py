import json

import pytest

from jobwatch import cli, timing
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
    assert "/api/digest" in paths and "/api/hidden" in paths and "/api/counts" in paths
    assert not any("company" in p for p in paths)
    assert ("Company", "/api/company?q=Globex%20%26%20Co") in timing.calls(["company"], "Globex & Co")
    assert [t for t, _ in timing.calls(["QUEUE"])] == ["Queue"] * 3
    with pytest.raises(ValueError, match="no tab named nope"):
        timing.calls(["nope"])


def test_measure_ranks_slowest_first_with_a_fake_clock():
    sizes = {"/api/digest": (200, 2048), "/api/queue": (200, 1024), "/api/pace": (200, 10)}
    # digest runs 900, 100, 100; queue 50, 60, 70; pace 1, 2, 3 (ms)
    clock = FakeClock([900, 100, 100, 50, 60, 70, 1, 2, 3])
    rows = timing.measure(lambda path: sizes[path], [("Today", "/api/digest"), ("Queue", "/api/queue"),
                                                      ("Queue", "/api/pace")], runs=3, clock=clock)
    assert [(r.path, round(r.median)) for r in rows] == [("/api/digest", 100), ("/api/queue", 60), ("/api/pace", 2)]
    assert [round(m) for m in rows[0].ms] == [900, 100, 100] and rows[0].kb == 2
    text = timing.render(rows)
    assert text.index("/api/digest") < text.index("/api/queue") < text.index("/api/pace")
    assert "tab totals: Today 0.1s, Queue 0.1s" in text


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
    assert {c["path"] for c in out} == {"/api/digest", "/api/hidden", "/api/queue", "/api/pace", "/api/snoozed",
                                        "/api/applications", "/api/calendar"}
    assert all(len(c["runs"]) == 2 and not c["error"] for c in out)
    assert [c["median_ms"] for c in out] == sorted((c["median_ms"] for c in out), reverse=True)


def test_timing_command_prints_the_table(watchlist, web, capsys):
    App(watchlist).post_fetch({})
    cli.main(["-c", str(watchlist), "timing", "-n", "1", "--tab", "Settings"])
    out = capsys.readouterr().out
    assert "Settings: /api/settings" in out and "tab totals: Settings" in out
