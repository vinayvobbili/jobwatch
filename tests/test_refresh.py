"""The page checks the boards by itself on the watchlist's schedule (fetch_every), one check at a time, and says
on Today when they were last checked."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from jobwatch import config, watch
from jobwatch import web as ui
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request

FIT = {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}


def setting(watchlist, **raw_settings):
    raw = yaml.safe_load(watchlist.read_text())
    watchlist.write_text(yaml.safe_dump({**raw, **raw_settings}))
    return watchlist


def last_fetch_was(store, ago: timedelta):
    with store.db:
        store.db.execute("UPDATE fetches SET at=?", ((datetime.now(timezone.utc) - ago).isoformat(),))


@pytest.mark.parametrize("raw, want", [
    (None, timedelta(hours=6)), ("6h", timedelta(hours=6)), ("90m", timedelta(minutes=90)),
    ("1d", timedelta(days=1)), (3, timedelta(hours=3)), ("12 hours", timedelta(hours=12)),
    ("off", None), (False, None), (0, None), ("0", None), ("never", None),
])
def test_fetch_every(watchlist, raw, want):
    if raw is not None:
        setting(watchlist, fetch_every=raw)
    assert config.load(watchlist).fetch_every == want


@pytest.mark.parametrize("raw, why", [("30m", "at least 1h"), ("soon", "looks like"), (True, "looks like")])
def test_fetch_every_that_isnt_one(watchlist, raw, why):
    setting(watchlist, fetch_every=raw)
    with pytest.raises(config.ConfigError, match=why):
        config.load(watchlist)


def test_a_bare_off_in_the_file_turns_it_off(watchlist):
    watchlist.write_text(watchlist.read_text() + "fetch_every: off\n")  # YAML reads it as false
    assert config.load(watchlist).fetch_every is None
    assert App(watchlist).get_settings({})["fetch_every"] == "off"


def test_every_fetch_is_recorded_and_one_that_read_nothing_doesnt_count(watchlist, web):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    assert store.last_fetch() is None
    watch.fetch_all(cfg, store)
    last = store.last_fetch()
    assert (last["boards"], last["jobs"], last["new"], last["errors"]) == (3, 5, 5, {})
    assert datetime.now(timezone.utc) - last["at"] < timedelta(minutes=1)
    web.responses.clear()  # no network: every board fails
    watch.fetch_all(cfg, store)
    assert store.last_fetch()["at"] == last["at"]
    store.close()


def test_a_check_is_due_when_the_last_is_older_than_fetch_every(watchlist, web):
    app = App(watchlist, background=True)
    r = app.refresher
    assert r.due()  # never checked
    app.post_fetch({})
    assert not r.due()
    store = Store(config.load(watchlist).state)
    last_fetch_was(store, timedelta(hours=5))
    assert not r.due()
    last_fetch_was(store, timedelta(hours=6, minutes=1))
    assert r.due()
    r.tried = datetime.now(timezone.utc) - timedelta(minutes=5)  # a scheduled check just started (and failed)
    assert not r.due()
    r.tried = None
    setting(watchlist, fetch_every="off")
    assert not r.due()
    setting(watchlist, fetch_every="1d")
    assert not r.due()
    store.close()


def test_no_check_without_a_watchlist_or_boards(tmp_path, watchlist):
    assert not App(tmp_path / "none.yaml").refresher.due()
    watchlist.write_text("companies: []\n")
    assert not App(watchlist).refresher.due()
    watchlist.write_text("companies: [nosuch:acme]\nfetch_every: 30m\n")  # a broken watchlist: no check, quietly
    assert not App(watchlist).refresher.due()


def test_a_click_while_a_check_runs_waits_for_it(watchlist, web, monkeypatch):
    """Never two checks at once: the second gets the first one's counts, and no board is asked twice."""
    started, release, calls = threading.Event(), threading.Event(), []

    def slow(cfg, store, **kw):
        calls.append(1)
        started.set()
        release.wait(10)
        return watch.fetch_all(cfg, store, **kw)

    monkeypatch.setattr(ui, "fetch_all", slow)
    app = App(watchlist, background=True)
    got = {}
    first = threading.Thread(target=lambda: got.update(first=app.refresher.fetch()))
    first.start()
    assert started.wait(10) and app.refresher.running
    second = threading.Thread(target=lambda: got.update(second=app.post_fetch({})))
    second.start()
    deadline = time.monotonic() + 10
    while not app.refresher._current._condition._waiters:  # the click is waiting on the running check
        assert time.monotonic() < deadline
        time.sleep(0.01)
    release.set()
    first.join(10)
    second.join(10)
    assert len(calls) == 1 and got["first"] == got["second"] and got["first"]["new"] == 5
    assert not app.refresher.running


def test_the_schedule_checks_at_start_and_new_jobs_get_scored(watchlist, web, monkeypatch):
    (watchlist.parent / "cv.md").write_text("Python, LLMs, RAG")
    setting(watchlist, resume="cv.md")
    asked = []
    monkeypatch.setattr(watch, "score_jobs", lambda jobs, *a, **kw: (asked.extend(j.key for j in jobs)
                                                                    or {j.key: FIT for j in jobs}, {}))
    app = App(watchlist, background=True)
    app.refresher.tick = 0.05
    app.refresher.start()
    try:
        deadline = time.monotonic() + 10
        while not app.get_checked({})["at"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        time.sleep(0.2)  # a few more ticks: not due again
        assert web.calls.count("https://api.lever.co/v0/postings/globex?mode=json") == 1
    finally:
        app.refresher.stop(10)
    app.scorer.wait(10)
    assert "ashby:initech:c1" in asked  # the background scorer picked up the scheduled check's new jobs


def test_a_scheduled_check_that_fails_is_tried_again_later(watchlist, web, monkeypatch, capsys):
    def boom(cfg, store, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ui, "fetch_all", boom)
    app = App(watchlist, background=True)
    app.refresher.tick = 0.02
    app.refresher.start()
    time.sleep(0.2)
    app.refresher.stop(10)
    assert app.refresher.error == "RuntimeError: disk full"
    assert capsys.readouterr().err.count("scheduled check for new jobs failed") == 1  # once per RETRY, not per tick
    assert not app.refresher.running


def test_today_says_when_the_boards_were_checked(watchlist, web):
    app = App(watchlist, background=True)
    c = app.get_digest({})["checked"]
    assert (c["at"], c["running"], c["every_hours"]) == (None, False, None)  # the schedule isn't running here
    app.post_fetch({})
    c = app.get_checked({})
    assert c["at"] and c["new"] == 5 and c["errors"] == {} and c["warnings"] == {}
    app.refresher._thread = threading.current_thread()  # as if started
    assert app.get_checked({})["every_hours"] == 6
    app.refresher._thread = None


def test_the_page_checks_when_it_starts(server, watchlist):
    """serve() starts the schedule: the boards are checked at once (never checked before), and /api/checked says
    when."""
    ok = {"X-Jobwatch-Token": TOKEN}
    deadline = time.monotonic() + 10
    while True:
        status, data = request(server, "GET", "/api/checked", headers=ok)
        c = __import__("json").loads(data)
        if c["at"] and not c["running"]:
            break
        assert status == 200 and time.monotonic() < deadline
        time.sleep(0.05)
    assert c["every_hours"] == 6 and c["new"] == 5
    page = request(server, "GET", "/")[1].decode()
    assert "Boards checked" in page and "checking now…" in page and "/api/checked" in page


def test_settings_save_fetch_every(watchlist, web):
    app = App(watchlist)
    assert app.get_settings({})["fetch_every"] is None  # not set: the default
    app.post_settings({"fetch_every": "12h"})
    assert config.load(watchlist).fetch_every == timedelta(hours=12) and app.get_settings({})["fetch_every"] == "12h"
    app.post_settings({"fetch_every": "off"})
    assert config.load(watchlist).fetch_every is None
    with pytest.raises(config.ConfigError, match="at least 1h"):
        app.post_settings({"fetch_every": "5m"})
    app.post_settings({"fetch_every": None})
    assert config.load(watchlist).fetch_every == config.FETCH_EVERY  # back to the default


def test_an_older_state_file_gains_the_new_tables(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE jobs (key TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL, "
                     "data TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed TEXT, "
                     "status TEXT NOT NULL DEFAULT 'new', status_at TEXT, note TEXT);")
    db.close()
    s = Store(path)
    assert s.last_fetch() is None and s.hosted_page("ashby", "initech") is None
    s.record_fetch(1, 2, 0, {}, {"ashby:initech": "offline"})
    s.save_hosted_page("ashby", "initech", False)
    s.close()
    s = Store(path)
    assert s.last_fetch()["warnings"] == {"ashby:initech": "offline"} and s.hosted_page("ashby", "initech")[0] is False
    s.close()
