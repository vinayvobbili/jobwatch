"""Snoozed: a job wanted, but not while an application is in progress at its company. It comes back to the queue when
that application ends, or after SNOOZE_DAYS, since many companies never say no."""

import json
from datetime import date, timedelta

import pytest

from jobwatch import config
from jobwatch.models import Job
from jobwatch.store import SNOOZE_DAYS, Store
from jobwatch.watch import queue

from .conftest import TOKEN, request


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def two_roles(store):
    """An application in progress at Globex, and another role there."""
    applied = store.add("Globex", "Staff Engineer", status="applied")
    other = store.add("Globex", "Principal Engineer", status="queued")
    return applied.key, other.key


def status(store, key):
    return store.find(key)[1]["status"]


def test_snoozing_needs_an_application_in_progress_at_the_company(store):
    _, other = two_roles(store)
    elsewhere = store.add("Initech", "Principal Engineer", status="queued")
    with pytest.raises(ValueError, match="no application is in progress at Initech"):
        store.set_status([elsewhere.key], "snoozed")
    assert status(store, elsewhere.key) == "queued"
    store.set_status([other], "snoozed")
    assert status(store, other) == "snoozed"


def test_an_ended_application_does_not_count_as_in_progress(store):
    applied, other = two_roles(store)
    store.set_status([applied], "rejected")
    with pytest.raises(ValueError):
        store.set_status([other], "snoozed")


def test_a_job_does_not_wait_on_itself(store):
    applied, _ = two_roles(store)
    assert store.waiting_on(store.find(applied)[0]) == []


@pytest.mark.parametrize("ending", ["rejected", "withdrawn"])
def test_it_comes_back_to_the_queue_when_the_application_ends(store, ending):
    applied, other = two_roles(store)
    store.set_status([other], "snoozed")
    store.set_status([applied], "screening")
    assert status(store, other) == "snoozed"  # moving along isn't ending
    store.set_status([applied], ending)
    _, rec = store.find(other)
    assert rec["status"] == "queued" and rec["follow_up"] is None
    assert "Back from snooze: your application there ended" in rec["note"]


def test_it_waits_for_every_application_there(store):
    applied, other = two_roles(store)
    second = store.add("Globex", "Security Engineer", status="applied").key
    store.set_status([other], "snoozed")
    store.set_status([applied], "rejected")
    assert status(store, other) == "snoozed"
    store.set_status([second], "rejected")
    assert status(store, other) == "queued"


def test_another_companys_rejection_changes_nothing(store):
    _, other = two_roles(store)
    elsewhere = store.add("Initech", "Staff Engineer", status="applied")
    store.set_status([other], "snoozed")
    store.set_status([elsewhere.key], "rejected")
    assert status(store, other) == "snoozed"


def test_the_timer_is_set_when_snoozed(store):
    _, other = two_roles(store)
    store.set_status([other], "snoozed")
    assert store.find(other)[1]["follow_up"] == (date.today() + timedelta(days=SNOOZE_DAYS)).isoformat()


def test_it_comes_back_when_the_timer_runs_out_though_the_application_says_nothing(store):
    applied, other = two_roles(store)
    store.set_status([other], "snoozed")
    assert store.wake_snoozed() == []
    store.track(other, follow_up=(date.today() - timedelta(days=1)).isoformat())
    assert store.wake_snoozed() == [other]
    _, rec = store.find(other)
    assert rec["status"] == "queued" and rec["follow_up"] is None and "its time was up" in rec["note"]
    assert status(store, applied) == "applied"


def test_the_queue_brings_back_those_whose_time_is_up(watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    _, other = two_roles(store)
    store.set_status([other], "snoozed")
    store.track(other, follow_up=date.today().isoformat())
    assert [e.job.key for e in queue(cfg, store)] == [other]
    store.close()


def test_leaving_a_snooze_by_hand_clears_its_timer(store):
    _, other = two_roles(store)
    store.set_status([other], "snoozed")
    store.set_status([other], "queued")
    assert store.find(other)[1]["follow_up"] is None


def test_an_applications_own_follow_up_is_left_alone(store):
    applied, _ = two_roles(store)
    store.track(applied, follow_up="2030-01-15")
    store.set_status([applied], "screening")
    assert store.find(applied)[1]["follow_up"] == "2030-01-15"


def get(server, path):
    code, body = request(server, "GET", path, headers={"X-Jobwatch-Token": TOKEN})
    return code, json.loads(body)


@pytest.fixture
def tracked(watchlist):
    s = Store(config.load(watchlist).state)
    keys = two_roles(s)
    s.close()
    return keys


def test_the_company_page_gets_job_cards(server, tracked):
    """The same fields as a card on the Queue, with who a job could wait on; no advice on a job applied to."""
    code, c = get(server, "/api/company?q=globex")
    assert code == 200
    by_key = {j["key"]: j for j in c["jobs"]}
    applied, other = by_key[tracked[0]], by_key[tracked[1]]
    for field in ("company", "keywords", "contacts", "warnings", "fit", "unscored", "worth", "can_tailor", "can_score"):
        assert field in other
    assert [a["key"] for a in other["waiting_on"]] == [tracked[0]] and applied["waiting_on"] == []
    assert applied["advice"] is None and applied["verdict"] is None and applied["applied_at"]
    assert "advice" in other


def test_todays_and_the_queues_cards_know_what_a_job_could_wait_on(server, tracked):
    code, jobs = get(server, "/api/queue")
    assert code == 200 and [a["title"] for a in jobs[0]["waiting_on"]] == ["Staff Engineer"]


def mark(server, key, to):
    return request(server, "POST", "/api/mark", {"keys": [key], "status": to}, headers={"X-Jobwatch-Token": TOKEN})


def test_snoozed_jobs_are_listed_with_what_they_wait_on(server, tracked):
    assert mark(server, tracked[1], "snoozed")[0] == 200
    assert get(server, "/api/queue")[1] == []  # out of the queue
    code, listed = get(server, "/api/snoozed")
    assert code == 200 and [j["key"] for j in listed] == [tracked[1]]
    assert listed[0]["waiting_on"][0]["title"] == "Staff Engineer" and listed[0]["back_by"]


def test_snoozing_with_nothing_to_wait_for_says_so(server, tracked):
    mark(server, tracked[0], "rejected")
    code, body = mark(server, tracked[1], "snoozed")
    assert code == 400 and "nothing to wait for" in json.loads(body)["error"]


def test_a_score_for_a_post_naming_one_role_is_read_back_and_one_listing_several_is_not(store):
    """A one-role post's score counts, or it looks unscored forever and the scorer sends it again and again."""
    one = Job(source="hn", company="whoishiring", id="1", title="Staff Engineer", url="https://example.com/1")
    many = Job(source="hn", company="whoishiring", id="2", title="Designer + iOS Developer", url="https://example.com/2")
    store.sync("hn", "whoishiring", [one, many])
    for job in (one, many):
        store.save_score(job.key, "r", {"score": 70})
    assert store.score(one.key, "r")["score"] == 70 and store.score(many.key, "r") is None
    assert set(store.scores("r")) == {one.key}


def test_the_page_has_the_company_tab_and_the_snooze_limit_matches(server):
    page = request(server, "GET", "/")[1].decode()
    assert 'data-tab="company"' in page and "function renderCompany(" in page and "function companyCard(" in page
    assert "function snoozeButton(" in page and "function snoozedPanel(" in page
    assert SNOOZE_DAYS == 21 and 'SNOOZE_LIMIT = "3 weeks"' in page
