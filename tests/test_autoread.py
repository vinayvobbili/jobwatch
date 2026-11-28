"""Reading LinkedIn and Indeed postings by itself (jobwatch/autoread.py): which jobs the extension is handed, the limits
the settings may not pass, what a read stores and what the Activity tab says. Every company, job and address is made
up."""

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from jobwatch import alerts, autoread, config
from jobwatch.store import Store
from jobwatch.web import ApiError, App

from .conftest import TOKEN, request

LI = "https://www.linkedin.com/jobs/view/{}/"
IN = "https://www.indeed.com/viewjob?jk={}"
TEXT = "We are hiring a platform engineer to build services in Python. You will own reliability. " * 4


def turn_on(watchlist, **autoread_settings):
    raw = yaml.safe_load(watchlist.read_text())
    raw["autoread"] = {"enabled": True, **autoread_settings}
    watchlist.write_text(yaml.safe_dump(raw))


def add(store, title, company="Umbrella", url=None, location="Remote (US)", site="linkedin"):
    """A job from an alert, with only its title, company and place."""
    n = len(store.manual_jobs()) + 1
    url = url or (LI.format(4000000000 + n) if site == "linkedin" else IN.format(f"{n:016x}"))
    job = alerts.email_job(alerts.Alert(title, company, location, url=url, site=site, via=f"{site}-alert"))
    store.keep(job)
    store.set_via(job.key, f"{site}-alert")
    return job.key


@pytest.fixture
def state(watchlist):
    store = Store(config.load(watchlist).state)
    yield store
    store.close()


def keys_of(watchlist, state, **kwargs):
    return [j["key"] for j in autoread.queue(config.load(watchlist), state, **kwargs)["jobs"]]


# --- the settings: off at first, and never past the hard ceilings ---------------------------------------------------


def test_it_is_off_until_turned_on_and_then_hands_over_nothing(watchlist, state):
    add(state, "Platform Engineer")
    cfg = config.load(watchlist)
    assert cfg.autoread == config.AutoRead(False, 25, 120, 180)
    assert autoread.queue(cfg, state) == {"enabled": False, "limits": autoread.limits(cfg), "waiting": 0, "jobs": []}
    turn_on(watchlist)
    assert len(autoread.queue(config.load(watchlist), state)["jobs"]) == 1


@pytest.mark.parametrize("setting, match", [
    ({"per_day": 51}, "per_day must be a whole number from 1 to 50"),
    ({"per_day": 0}, "per_day"),
    ({"pause_min": 59}, "pause_min must be a whole number from 60"),
    ({"pause_min": 120, "pause_max": 130}, "at least 30 more than pause_min"),
    ({"enabled": "yes please"}, "autoread.enabled must be on or off"),
    ({"speed": 3}, "unknown autoread setting"),
])
def test_no_setting_goes_past_the_ceilings(watchlist, setting, match):
    raw = yaml.safe_load(watchlist.read_text())
    raw["autoread"] = setting
    watchlist.write_text(yaml.safe_dump(raw))
    with pytest.raises(config.ConfigError, match=match):
        config.load(watchlist)


def test_a_setting_may_tighten_the_defaults_and_loosen_them_up_to_the_ceilings(watchlist):
    turn_on(watchlist, per_day=50, pause_min=600, pause_max=900)
    a = config.load(watchlist).autoread
    assert (a.per_day, a.pause_min, a.pause_max) == (50, 600, 900)
    turn_on(watchlist, per_day=5, pause_min=60)
    a = config.load(watchlist).autoread
    assert (a.per_day, a.pause_min, a.pause_max) == (5, 60, 180)  # a lone pause_min leaves pause_max where it is


def test_the_limits_hold_even_for_a_config_built_by_hand(watchlist):
    cfg = config.load(watchlist)
    cfg.autoread = config.AutoRead(True, 500, 1, 2)
    lim = autoread.limits(cfg)
    assert (lim["per_day"], lim["daily_max"], lim["pause_min"], lim["pause_max"]) == (50, 50, 60, 90)


# --- which jobs ------------------------------------------------------------------------------------------------------


def test_only_jobs_with_no_text_from_linkedin_or_indeed_are_handed_over_best_first(watchlist, state):
    turn_on(watchlist)
    plain = add(state, "Platform Engineer")
    best = add(state, "Python Platform Engineer", site="indeed")
    with_text = add(state, "Python Services Engineer")
    state.set_description(with_text, TEXT)
    elsewhere = add(state, "Platform Engineer II", url="https://umbrella.example/careers/platform-engineer-2")
    got = autoread.queue(config.load(watchlist), state)
    # Python in the title ranks first
    assert [(j["key"], j["site"]) for j in got["jobs"]] == [(best, "indeed"), (plain, "linkedin")]
    assert elsewhere not in keys_of(watchlist, state) and with_text not in keys_of(watchlist, state)
    assert got["waiting"] == 2 and set(got["jobs"][0]) == {"key", "site", "url", "title", "company"}


def test_a_job_the_filters_would_drop_is_never_handed_over(watchlist, state):
    turn_on(watchlist)
    good = add(state, "Platform Engineer")
    add(state, "Platform Engineer (Contract)")   # exclude_titles: contract
    add(state, "Site Reliability Engineer", location="London, UK")  # not a place the watchlist wants
    assert keys_of(watchlist, state) == [good]


def test_closed_skipped_and_snoozed_jobs_are_left_out(watchlist, state):
    turn_on(watchlist)
    good = add(state, "Platform Engineer")
    closed, skipped = add(state, "Data Engineer"), add(state, "Backend Engineer")
    state.set_closed(closed, True)  # marked once: still being checked, so not read either
    state.set_status([skipped], "skipped")
    assert keys_of(watchlist, state) == [good]


def test_a_duplicate_of_a_job_already_acted_on_is_left_out(watchlist, state):
    turn_on(watchlist)
    applied = add(state, "Platform Engineer", company="Hooli")
    state.set_status([applied], "applied")
    again = add(state, "Platform Engineer", company="Hooli", url=LI.format(4000000099))
    other = add(state, "Platform Engineer", company="Pied Piper")
    assert again not in keys_of(watchlist, state)
    assert other in keys_of(watchlist, state)


def test_a_company_whose_own_board_is_watched_gets_its_text_from_the_board(watchlist, state):
    turn_on(watchlist)
    add(state, "Platform Engineer", company="Initech")  # the watchlist's ashby:initech
    add(state, "Platform Engineer", company="Globex")   # lever:globex
    mine = add(state, "Platform Engineer", company="Umbrella")
    assert keys_of(watchlist, state) == [mine]


def test_a_job_tried_lately_waits_and_is_handed_over_again_after_three_days(watchlist, state):
    turn_on(watchlist)
    key = add(state, "Platform Engineer")
    state.set_read_tried(key, "no_text")
    assert keys_of(watchlist, state) == []
    later = datetime.now(UTC) + timedelta(days=3, minutes=1)
    assert keys_of(watchlist, state, now=later) == [key]


def test_queued_jobs_come_before_todays_best(watchlist, state):
    turn_on(watchlist)
    today = add(state, "Python Platform Engineer")
    queued = add(state, "Platform Engineer")
    state.set_status([queued], "queued")
    assert keys_of(watchlist, state) == [queued, today]


def test_the_list_follows_the_reads_left_for_each_site_and_its_length_limit(watchlist, state):
    turn_on(watchlist)
    for n in "ABCDEFG":
        add(state, f"Platform Engineer {n}")
    ind = add(state, "Platform Engineer H", site="indeed")
    both = autoread.queue(config.load(watchlist), state, {"linkedin": 3, "indeed": 3}, limit=99)
    assert len(both["jobs"]) == autoread.QUEUE_MAX and both["waiting"] == 8  # a short list, however many wait
    only_indeed = autoread.queue(config.load(watchlist), state, {"linkedin": 0, "indeed": 5})
    assert [j["key"] for j in only_indeed["jobs"]] == [ind] and only_indeed["waiting"] == 1
    assert autoread.queue(config.load(watchlist), state, {"linkedin": 0, "indeed": 0})["jobs"] == []


# --- what the extension says, and what a read stores ------------------------------------------------------------------


def test_a_read_that_gave_no_text_marks_the_job_tried_and_says_so_in_the_activity_tab(watchlist, state):
    key = add(state, "Platform Engineer")
    autoread.report(state, {"outcome": "no_text", "key": key, "site": "linkedin", "reason": "the page had no posting"})
    assert key in state.read_tried()
    entry = state.activity(kind="mail")[0]
    assert entry["text"] == "Couldn't read Platform Engineer at Umbrella from linkedin.com: the page had no posting"
    assert entry["ok"] is False and [j["key"] for j in entry["jobs"]] == [key]


def test_a_stop_is_a_notable_entry_and_the_persons_own_pause_is_not(watchlist, state):
    autoread.report(state, {"event": "paused",
                            "reason": "Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow."})
    autoread.report(state, {"event": "off"})
    autoread.report(state, {"event": "resumed"})
    stop = state.activity(kind="mail", notable=True)
    assert [e["text"] for e in stop] == ["Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow."]
    assert stop[0]["ok"] is False
    texts = [e["text"] for e in state.activity(kind="mail")]
    assert "Auto-read turned off in the browser extension" in texts and any("resumed" in t for t in texts)


def test_a_report_must_be_one_the_extension_can_make(watchlist, state):
    with pytest.raises(ValueError, match="outcome is one of"):
        autoread.report(state, {"outcome": "great"})
    with pytest.raises(ValueError, match="send an outcome"):
        autoread.report(state, {})


@pytest.fixture
def app(watchlist, web):
    return App(watchlist)


def test_an_automatic_read_is_stored_like_read_posting_and_is_not_scored_at_once(app, watchlist, state, monkeypatch):
    turn_on(watchlist)
    key = add(state, "Platform Engineer")
    scored = []
    monkeypatch.setattr(app, "score_posted_in_background", lambda *a, **k: scored.append(a) or True)
    got = app.ext_posting({"linkedin": "4000000001", "company": "Umbrella", "title": "Platform Engineer",
                           "text": TEXT, "closed": False, "auto": True})
    assert got["key"] == key and got["has_text"] is True and got["scoring"] is False and scored == []
    assert state.find(key)[0].description.strip().startswith("We are hiring")
    assert state.activity(kind="mail")[0]["text"] == "Read Platform Engineer at Umbrella from linkedin.com"
    # the same call by hand (Read posting) asks for the score at once, as before
    state2 = add(state, "Data Engineer")
    app.ext_posting({"linkedin": "4000000002", "company": "Umbrella", "title": "Data Engineer", "text": TEXT})
    assert scored and state2


def test_an_automatic_read_is_refused_while_the_setting_is_off(app, state):
    add(state, "Platform Engineer")
    with pytest.raises(ApiError, match="turn it on in jobwatch's Settings"):
        app.ext_posting({"linkedin": "4000000001", "text": TEXT, "auto": True})


def test_the_extension_asks_over_http_with_its_token_only(server, watchlist):
    turn_on(watchlist)
    store = Store(config.load(watchlist).state)
    try:
        add(store, "Platform Engineer")
    finally:
        store.close()
    token = json.loads(request(server, "GET", "/api/extension", headers={"X-Jobwatch-Token": TOKEN})[1])["token"]
    ok = {"X-Jobwatch-Extension": token}
    assert request(server, "GET", "/ext/read-queue")[0] == 403
    status, data = request(server, "GET", "/ext/read-queue?linkedin=2&indeed=0&limit=1", headers=ok)
    got = json.loads(data)
    assert status == 200 and got["enabled"] is True and len(got["jobs"]) == 1 and got["limits"]["daily_max"] == 50
    assert request(server, "GET", "/ext/read-queue?linkedin=lots", headers=ok)[0] == 400
    status, data = request(server, "POST", "/ext/read-report", {"event": "paused", "reason": "stop"}, headers=ok)
    assert status == 200 and json.loads(data) == {"ok": True}
    assert request(server, "POST", "/ext/read-report", {"outcome": "bogus"}, headers=ok)[0] == 400
    assert "auto-read" in json.loads(request(server, "GET", "/ext/ping", headers=ok)[1])["features"]
