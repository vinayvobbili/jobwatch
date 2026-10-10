"""Today's picks (display.today) and the daily pace (pace.daily, pace.max): the watchlist, the digest, the page."""

import json
import os
import time
from datetime import date

import pytest
import yaml

from jobwatch import cli, config
from jobwatch.store import Store
from jobwatch.watch import pace, save_job
from jobwatch.web import App

from .conftest import TOKEN, request


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr().out


def add_to(watchlist, text):
    watchlist.write_text(watchlist.read_text() + text)
    return config.load(watchlist)


def test_defaults(watchlist):
    cfg = config.load(watchlist)
    assert cfg.today == 10 and (cfg.pace.daily, cfg.pace.max) == (3, 5)


def test_settings_are_read(watchlist):
    cfg = add_to(watchlist, "display: {today: 3}\npace: {daily: 2, max: 4}\n")
    assert cfg.today == 3 and (cfg.pace.daily, cfg.pace.max) == (2, 4)


def test_daily_alone_raises_max_with_it(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies: [lever:globex]\npace: {daily: 8}\n")
    assert (config.load(p).pace.daily, config.load(p).pace.max) == (8, 8)
    p.write_text("companies: [lever:globex]\npace: {daily: 0}\ndisplay: {today: 0}\n")
    cfg = config.load(p)
    assert cfg.pace.daily == 0 and cfg.today == 0  # off: every match, no pace


@pytest.mark.parametrize("text, error", [
    ("display: {today: -1}", r"display\.today must be a whole number"),
    ("display: {today: ten}", r"display\.today must be a whole number, 0 or more \(0 shows every match\)"),
    ("display: {today: true}", r"display\.today"),
    ("pace: fast", r"pace looks like \{daily: 3, max: 5\}"),
    ("pace: {daily: 2.5}", r"pace\.daily must be a whole number, 0 or more \(0 turns the pace off\)"),
    ("pace: {daily: 4, max: 2}", r"pace\.max .* can't be less than pace\.daily"),
    ("pace: {often: 1}", r"unknown pace setting\(s\): often"),
])
def test_bad_values_are_config_errors(tmp_path, text, error):
    p = tmp_path / "c.yaml"
    p.write_text(f"companies: [lever:globex]\n{text}\n")
    with pytest.raises(config.ConfigError, match=error):
        config.load(p)


def test_the_example_documents_both(tmp_path):
    """The example's commented display and pace sections load as written once uncommented."""
    text = config.EXAMPLE
    for line in ("# display:", "#   today: 10", "# pace:", "#   daily: 3", "#   max: 5"):
        assert line in text
        text = text.replace(line, line[2:], 1)
    p = tmp_path / "c.yaml"
    p.write_text(text)
    cfg = config.load(p)
    assert cfg.today == 10 and (cfg.pace.daily, cfg.pace.max) == (3, 5)


# -- the digest: the top display.today, the rest a flag away

def test_digest_lists_the_top_picks(web, watchlist, capsys):
    add_to(watchlist, "display: {today: 2}\n")
    c = ("-c", str(watchlist))
    run(capsys, *c, "fetch")
    out = run(capsys, *c, "digest")
    assert "Top 2 of 3 matching job(s)." in out and out.count("\n### ") == 2
    assert out.rstrip().endswith("1 more match: `jobwatch digest --all`")
    # Only the listed ones were shown: the one left out comes up next time.
    again = run(capsys, *c, "digest")
    assert "1 matching job(s)." in again and "more match" not in again
    every = run(capsys, *c, "digest", "--all")
    assert "3 matching job(s)." in every and every.count("\n### ") == 3 and "more match" not in every
    assert "Top 1 of 3" in run(capsys, *c, "digest", "--all", "--limit", "1")


def test_digest_today_zero_lists_every_match(web, watchlist, capsys):
    add_to(watchlist, "display: {today: 0}\n")
    run(capsys, "-c", str(watchlist), "fetch")
    out = run(capsys, "-c", str(watchlist), "digest")
    assert "3 matching job(s)." in out and "more match" not in out


def test_digest_json_says_how_many_matched(web, watchlist, capsys):
    add_to(watchlist, "display: {today: 1}\n")
    run(capsys, "-c", str(watchlist), "fetch")
    d = json.loads(run(capsys, "-c", str(watchlist), "digest", "--format", "json"))
    assert len(d["jobs"]) == 1 and d["total"] == 3


def test_mcp_digest_defaults_to_display_today(web, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    add_to(watchlist, "display: {today: 2}\npace: {daily: 1, max: 2}\n")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    mcp.fetch_jobs()
    d = mcp.get_digest(mark_shown=False)
    assert len(d["jobs"]) == 2 and d["total"] == 3
    assert d["pace"] == {"applied": 0, "daily": 1, "max": 2, "met": False, "at_max": False,
                         "line": "Applied today: 0 of 1"}
    assert len(mcp.get_digest(limit=3, mark_shown=False)["jobs"]) == 3


# -- the pace: applications whose day applied is today, on this computer's clock

def applied(store, title, on):
    job, _ = save_job(store, company="Acme Robotics", title=title, status="applied", applied=on)
    return job


def test_pace_counts_today_not_yesterday(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    try:
        today = date(2026, 10, 10)
        applied(store, "Robot Wrangler", "2026-10-09")
        assert pace(cfg, store, today)["line"] == "Applied today: 0 of 3"
        applied(store, "Gripper Engineer", "2026-10-10")
        later = applied(store, "Sensor Lead", "2026-10-10")
        store.set_status([later.key], "screening")  # still sent today
        p = pace(cfg, store, today)
        assert (p["applied"], p["met"], p["line"]) == (2, False, "Applied today: 2 of 3")
        applied(store, "Arm Calibrator", "2026-10-10")
        p = pace(cfg, store, today)
        assert (p["met"], p["at_max"], p["line"]) == (True, False, "Applied today: 3. That's your 3 for today.")
        applied(store, "Path Planner", "2026-10-10")
        applied(store, "Fleet Operator", "2026-10-10")
        p = pace(cfg, store, today)
        assert p["at_max"] and p["line"].endswith("the rest can wait until tomorrow.")
        store.set_status([later.key], "queued")  # back before applying: no longer sent
        assert pace(cfg, store, today)["applied"] == 4
    finally:
        store.close()


def test_pace_off(watchlist):
    cfg = add_to(watchlist, "pace: {daily: 0}\n")
    store = Store(cfg.state)
    try:
        applied(store, "Robot Wrangler", "today")
        assert pace(cfg, store) is None
    finally:
        store.close()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
@pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])  # UTC+14 and UTC-11
def test_pace_uses_the_local_day(watchlist, tz):
    """Marked applied now, it counts as today on this computer's clock wherever it is, never UTC's day."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        cfg = config.load(watchlist)
        store = Store(cfg.state)
        try:
            job = applied(store, "Robot Wrangler", None)
            assert store.find(job.key)[1]["applied_at"] == date.today().isoformat()
            assert pace(cfg, store)["applied"] == 1
        finally:
            store.close()
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


# -- the page: Today and the queue get the picks and the pace; Settings saves both

def test_digest_and_pace_endpoints(watchlist, web):
    add_to(watchlist, "display: {today: 2}\n")
    app = App(watchlist)
    app.post_fetch({})
    d = app.get_digest({})
    assert len(d["jobs"]) == 3 and d["picks"] == 2  # every match: the page shows the picks first
    assert d["pace"]["line"] == "Applied today: 0 of 3"
    app.post_mark({"keys": ["c1"], "status": "queued"})
    app.post_mark({"keys": ["c1"], "status": "applied"})
    assert app.get_pace({})["pace"]["applied"] == 1


def test_settings_round_trip(watchlist):
    app = App(watchlist)
    s = app.get_settings({})
    assert s["pace"] == {} and s["display"] == {}
    app.post_settings({"display": {"theme": "dark", "today": 5}, "pace": {"daily": 2, "max": 4}})
    s = app.get_settings({})
    assert s["display"] == {"theme": "dark", "today": 5} and s["pace"] == {"daily": 2, "max": 4}
    cfg = config.load(watchlist)
    assert cfg.today == 5 and (cfg.pace.daily, cfg.pace.max) == (2, 4) and cfg.theme == "dark"
    before = watchlist.read_text()
    with pytest.raises(config.ConfigError, match=r"pace\.max"):
        app.post_settings({"pace": {"daily": 4, "max": 1}})
    with pytest.raises(config.ConfigError, match=r"display\.today"):
        app.post_settings({"display": {"today": "lots"}})
    assert watchlist.read_text() == before
    app.post_settings({"pace": None})  # cleared: back to the defaults
    assert "pace" not in yaml.safe_load(watchlist.read_text()) and config.load(watchlist).pace.daily == 3


def test_page_has_todays_picks_and_the_pace(server):
    page = request(server, "GET", "/")[1].decode()
    assert "function paceLine(" in page and "picks for today" in page
    assert "Show all ${jobs.length} matching jobs" in page
    assert 'api("/api/pace")' in page and "Today shows the top" in page
    status, data = request(server, "GET", "/api/pace", headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and json.loads(data)["pace"]["daily"] == 3
