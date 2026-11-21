"""/api/counts: the three numbers on the tab bar in one cheap call, the same numbers the page used to work out by
fetching the whole queue, the applications and the interviews after every click."""

import json
from datetime import date, timedelta

import pytest

import jobwatch.web as web_module
from jobwatch import config, watch
from jobwatch.store import Store
from jobwatch.web import App

from .conftest import TOKEN, request

TODAY = date.today()
DAY = timedelta(days=1)


@pytest.fixture
def app(watchlist, web):
    store = Store(config.load(watchlist).state)
    store.add("Initech", "Platform Engineer", status="queued")
    store.add("Globex", "Data Engineer", status="queued")
    store.add("Umbrella", "SRE", status="applied", follow_up=(TODAY - DAY).isoformat())          # due
    store.add("Hooli", "ML Engineer", status="applied", follow_up=(TODAY + 3 * DAY).isoformat())  # not yet
    store.add("Vandelay", "Backend Engineer", status="interviewing", follow_up=TODAY.isoformat(),
              next_step=f"call {TODAY:%m/%d} 2:00 PM")                                            # due, and today
    store.add("Wayne", "Staff Engineer", status="screening", next_step=f"call {TODAY + 2 * DAY:%m/%d} 9:00 AM")
    store.add("Stark", "Analyst", status="rejected", follow_up=(TODAY - DAY).isoformat())         # ended: not due
    store.close()
    return App(watchlist)


def what_the_page_counted(app):
    """The old refreshQueueCount: three full reads and a count of each."""
    apps = app.get_applications({})["applications"]
    return {"queue": len(app.get_queue({})),
            "due": sum(1 for a in apps if a["due"] and not (a["quiet"] and a["quiet"]["long"])),
            "interviews": sum(1 for i in app.get_interviews({})["interviews"]
                              if i["scheduled"] and i["day"] == TODAY.isoformat()),
            "applications": len(apps)}


def test_counts_are_what_the_page_counted_from_the_full_lists(app):
    got = app.get_counts({})
    assert got == what_the_page_counted(app) == {"queue": 2, "due": 2, "interviews": 1, "applications": 5}


def test_counts_follow_the_actions(app):
    queued = [j["key"] for j in app.get_queue({})]
    app.post_mark({"keys": queued[:1], "status": "skipped"})
    assert app.get_counts({})["queue"] == 1 == len(app.get_queue({}))
    app.post_mark({"keys": queued[1:], "status": "applied"})
    assert app.get_counts({}) == what_the_page_counted(app)
    assert app.get_counts({})["queue"] == 0 and app.get_counts({})["applications"] == 6
    app.post_track({"key": queued[1], "follow_up": (TODAY - DAY).isoformat()})
    assert app.get_counts({})["due"] == 3 == what_the_page_counted(app)["due"]


def test_counts_do_not_read_the_queue_or_judge_the_filters(app, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("counts must not build the queue or judge jobs")
    for module, name in ((watch, "queue"), (watch, "entries_for"), (watch, "judged_pass"), (web_module, "queue")):
        monkeypatch.setattr(module, name, refuse)
    assert app.get_counts({})["queue"] == 2


def test_the_page_asks_for_the_counts_and_not_the_queue_after_a_tab_click(server):
    page = request(server, "GET", "/")[1].decode()
    body = page.split("async function refreshQueueCount()")[1].split("\n}\n")[0]
    assert 'api("/api/counts")' in body and "/api/queue" not in body and "/api/applications" not in body
    assert request(server, "GET", "/api/counts", headers={"X-Jobwatch-Token": "wrong"})[0] == 403
    status, data = request(server, "GET", "/api/counts", headers={"X-Jobwatch-Token": TOKEN})
    assert status == 200 and set(json.loads(data)) == {"queue", "due", "interviews", "applications"}
