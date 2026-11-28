"""Progressive loading, the server's half: Today and the Queue answer in two calls (the list at once, what takes longer
after it) that make up exactly what the one call gave, the store's indexes are made after the first answers, and the
startup work waits for the page's first tab. The data is made up."""

import threading
import time

import pytest

from jobwatch import config
from jobwatch.store import Store
from jobwatch.web import ApiError, App


@pytest.fixture
def app(watchlist, web):
    app = App(watchlist)
    app.post_fetch({})
    keys = [j["key"] for j in app.get_digest({})["jobs"]]
    app.post_mark({"keys": keys[:2], "status": "queued"})
    return app


def merged(listed, extra):
    return [{**j, **extra[j["key"]]} for j in listed]


def test_the_queue_in_two_calls_is_the_queue_in_one(app):
    whole = app.get_queue({})
    listed, extra = app.get_queue({"part": ["list"]}), app.get_queue({"part": ["extra"]})
    assert len(whole) == 2
    assert merged(listed, extra) == whole
    # the list has every field a card reads, the slow ones empty; the extra is only the slow ones
    assert all(j["advice"] is None and j["waiting_on"] == [] and j["prepare"] == {} for j in listed)
    assert all(j["can_tailor"] in (True, False) and "title" in j for j in listed)
    assert set(extra) == {j["key"] for j in whole} and all("title" not in x for x in extra.values())


def test_today_in_two_calls_is_today_in_one(app):
    app.get_digest({})  # lists mark what was new as seen: compare once everything has been
    whole = app.get_digest({})
    listed = app.get_digest({"part": ["list"]})
    token = listed.pop("token")
    extra = app.get_digest({"part": ["extra"], "token": [token]})["jobs"]
    assert len(whole["jobs"]) >= 1
    assert merged(listed["jobs"], extra) == whole["jobs"]
    assert {k: v for k, v in listed.items() if k != "jobs"} == {k: v for k, v in whole.items() if k != "jobs"}
    assert all(j["unscored"] is None and j["waiting_on"] == [] and j["advice"] is None for j in listed["jobs"])
    # with no token (or another) the extra call works the jobs out again, to the same answer
    assert app.get_digest({"part": ["extra"], "token": ["nope"]})["jobs"] == extra
    assert app.get_digest({"part": ["extra"]})["jobs"] == extra


def test_a_list_marks_new_jobs_as_seen_and_an_extra_does_not(watchlist, web):
    app = App(watchlist)
    app.post_fetch({})
    first = app.get_digest({"part": ["list"]})
    assert {j["status"] for j in first["jobs"]} == {"new"}
    app.get_digest({"part": ["extra"]})
    assert {j["status"] for j in app.get_digest({"part": ["list"]})["jobs"]} == {"shown"}


def test_an_unknown_part_is_refused(app):
    for call in (app.get_queue, app.get_digest):
        with pytest.raises(ApiError, match="part must be list or extra"):
            call({"part": ["half"]})


def test_the_list_is_quick_because_it_skips_what_the_extra_pays_for(app, monkeypatch):
    # the line the scorer keeps (every job through the filters) is the slow part: only the extra reads it
    seen = []
    monkeypatch.setattr(app.scorer, "reasons", lambda cfg, store: seen.append(1) or {})
    app.get_queue({"part": ["list"]})
    app.get_digest({"part": ["list"]})
    assert seen == []
    app.get_queue({"part": ["extra"]})
    app.get_digest({"part": ["extra"]})
    assert len(seen) == 2


def test_the_store_builds_its_indexes_once(watchlist, web):
    store = Store(config.load(watchlist).state)
    try:
        assert store.ensure_indexes() == ["jobs_status"]
        assert store.ensure_indexes() == []
        plan = " ".join(r[3] for r in store.db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM jobs WHERE status IN ('queued') ORDER BY first_seen DESC"))
        assert "jobs_status" in plan
    finally:
        store.close()


def test_the_page_builds_the_indexes_after_its_first_answers(watchlist, web, monkeypatch):
    monkeypatch.setattr("jobwatch.web.STARTUP_WAIT", 5)
    monkeypatch.setattr("jobwatch.web.STARTUP_DATA_WAIT", 5)
    app = App(watchlist)
    order = []
    monkeypatch.setattr(app, "warm", lambda: order.append("indexes") or [])
    monkeypatch.setattr(app, "score_in_background", lambda: order.append("scoring"))
    monkeypatch.setattr(app, "sync_reminders", lambda: None)
    monkeypatch.setattr(app.refresher, "start", lambda: order.append("schedule"))
    t = threading.Thread(target=app.start_background)
    t.start()
    time.sleep(0.2)
    assert order == []                       # nothing yet: no page has asked
    app.first_call.set()
    time.sleep(0.2)
    assert order == []                       # a page is here, its first tab not answered
    app.first_data.set()
    t.join(5)
    assert not t.is_alive() and set(order) == {"indexes", "scoring", "schedule"}


def test_with_no_page_asking_the_startup_work_starts_anyway(watchlist, web, monkeypatch):
    monkeypatch.setattr("jobwatch.web.STARTUP_WAIT", 0.2)
    app = App(watchlist)
    ran = []
    monkeypatch.setattr(app, "warm", lambda: ran.append(1) or [])
    monkeypatch.setattr(app.refresher, "start", lambda: ran.append(2))
    monkeypatch.setattr(app, "sync_reminders", lambda: None)
    app.start_background()
    assert 2 in ran
