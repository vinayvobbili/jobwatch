"""POST /ext/posting: the posting the person has open on LinkedIn (or on the company's site) fills in the job
jobwatch has from an alert, or adds one."""

import json

import pytest

from jobwatch import config
from jobwatch.store import Store, closed_state
from jobwatch.web import App

from .conftest import TOKEN, request

LI = "https://www.linkedin.com/jobs/view/4000000001/"
LEVER_POSTING = "https://jobs.lever.co/globex/aaaa-1111"


@pytest.fixture
def app(watchlist, web):
    return App(watchlist)


def _job(app, key):
    store = Store(config.load(app.path).state)
    try:
        return store.find(key)
    finally:
        store.close()


def _alert_job(app, company="Globex", title="Machine Learning Engineer", url=LI):
    """A job as an alert email leaves it: title, company and the LinkedIn link, no text (kept as is, not matched to
    the company's board as adding it by hand would)."""
    store = Store(config.load(app.path).state)
    try:
        return store.add(company, title, url=url, status="queued", note="From a LinkedIn job alert").key
    finally:
        store.close()


def test_the_company_posting_fills_in_the_job_from_its_linkedin_id(app):
    key = _alert_job(app)
    got = app.ext_posting({"linkedin": "https://www.linkedin.com/jobs/view/machine-learning-engineer-at-globex-4000000001/",
                           "company": "Globex", "title": "Machine Learning Engineer",
                           "page_url": LEVER_POSTING + "?utm_source=linkedin", "text": "ignored"})
    assert got["key"] == key and not got["added"] and got["has_text"] and got["where"] == "queue"
    assert got["said"] == "Filled in from Lever; scoring now"
    job, rec = _job(app, key)
    assert "Train machine learning models" in job.description and job.url == LEVER_POSTING
    assert rec["status"] == "queued" and "From a LinkedIn job alert" in rec["note"]
    assert f"Found on LinkedIn: {LI}" in rec["note"]
    # The LinkedIn job is still found by its id (its link is the company's now), and isn't read twice.
    again = app.ext_posting({"linkedin": "4000000001", "company": "Globex", "title": "ML Engineer", "text": "x"})
    assert again["key"] == key and "already has" in again["said"] and "scoring" not in again["said"]


def test_the_linkedin_id_and_the_companys_address_are_enough(app):
    """What the extension sends after Apply opens the company's tab: nothing taken from LinkedIn but the job's id."""
    key = _alert_job(app)
    got = app.ext_posting({"linkedin": LI, "page_url": LEVER_POSTING})
    assert got["key"] == key and got["said"] == "Filled in from Lever; scoring now"


def test_an_easy_apply_job_takes_the_text_from_the_page(app):
    key = _alert_job(app, "Umbrella", "Platform Engineer", LI.replace("1/", "2/"))
    got = app.ext_posting({"linkedin": "https://www.linkedin.com/jobs/view/4000000002/", "company": "Umbrella",
                           "title": "Platform Engineer", "text": "  Run our Kubernetes fleet.  "})
    assert got["said"] == "Filled in from the page's text; scoring now"
    job, rec = _job(app, key)
    assert job.description == "Run our Kubernetes fleet." and job.url.endswith("4000000002/")
    assert "browser extension" in rec["note"]


def test_an_indeed_job_is_found_by_its_key_and_gets_the_text_the_extension_read(app):
    """Read posting on an Indeed page: the job's key (jk) finds the job from its alert link, whatever the page's
    title says, and a closed LinkedIn page's note comes along when the site says so."""
    indeed = "https://www.indeed.com/viewjob?jk=9cf96221e712e37e"
    key = _alert_job(app, "Initech", "Cyber Platform Lead", indeed)
    got = app.ext_posting({"indeed": indeed + "&from=serp", "company": "Initech Federal", "title": "Lead",
                           "text": "Run the cyber platform for Initech.", "closed": True})
    assert got["key"] == key and not got["added"] and got["has_text"] and got["where"] == "queue"
    job, rec = _job(app, key)
    assert job.description == "Run the cyber platform for Initech." and job.url == indeed
    assert "not accepting applications" in rec["note"]
    again = app.ext_posting({"indeed": "9cf96221e712e37e", "text": "x"})
    assert again["key"] == key and "already has" in again["said"]
    new = app.ext_posting({"indeed": "ab12cd34ef56ab78", "company": "Globex", "title": "SRE", "text": "Run Globex."})
    assert new["added"] and "ab12cd34ef56ab78" in _job(app, new["key"])[0].url


def test_a_job_without_the_linkedin_link_is_found_by_company_and_title(app):
    key = app.post_add({"company": "Umbrella, Inc.", "title": "Platform Engineer (Remote)", "status": "queued"})["key"]
    got = app.ext_posting({"linkedin": "4000000003", "company": "Umbrella", "title": "Platform Engineer",
                           "page_url": "https://careers.umbrella.example/jobs/42", "text": "Run things."})
    assert got["key"] == key
    job, _ = _job(app, key)
    assert job.url == "https://careers.umbrella.example/jobs/42" and job.description == "Run things."


def test_the_companys_own_page_is_saved_as_the_posting(app):
    key = _alert_job(app, "Umbrella", "Platform Engineer", LI.replace("1/", "2/"))
    got = app.ext_posting({"company": "Umbrella", "title": "Platform Engineer", "text": "Run things.",
                           "page_url": "https://careers.umbrella.example/jobs/42?src=li"})
    assert got["key"] == key
    assert _job(app, key)[0].url == "https://careers.umbrella.example/jobs/42?src=li"


def test_a_posting_jobwatch_doesnt_have_is_added(app):
    got = app.ext_posting({"linkedin": "4000000009", "company": "Initech", "title": "Data Scientist",
                           "text": "Models for Initech."})
    assert got["added"] and got["has_text"] and got["said"].startswith("Added. ")
    job, rec = _job(app, got["key"])
    assert job.description == "Models for Initech." and "4000000009" in job.url and rec["status"] == "queued"
    read = app.ext_posting({"company": "Globex", "title": "Staff Machine Learning Engineer",
                            "page_url": LEVER_POSTING})
    assert read["added"] and read["said"] == "Added. Filled in from Lever; scoring now"
    assert _job(app, read["key"])[0].key == "lever:globex:aaaa-1111"


def test_nothing_to_fill_it_with_says_what_to_do(app):
    _alert_job(app)
    with pytest.raises(ValueError, match="Save this posting to jobwatch"):
        app.ext_posting({"linkedin": "4000000001", "company": "Globex", "title": "Machine Learning Engineer",
                         "page_url": "https://careers.globex.example/apply/7"})
    with pytest.raises(ValueError, match="company and title"):
        app.ext_posting({})


def test_the_extension_posts_it_with_its_token(server):
    token = json.loads(request(server, "GET", "/api/extension", headers={"X-Jobwatch-Token": TOKEN})[1])["token"]
    ok = {"X-Jobwatch-Extension": token}
    body = {"linkedin": "4000000004", "company": "Initech", "title": "Data Scientist", "text": "Models."}
    assert request(server, "POST", "/ext/posting", body)[0] == 403
    status, data = request(server, "POST", "/ext/posting", body, headers=ok)
    assert status == 200 and json.loads(data)["added"]
    status, data = request(server, "POST", "/ext/posting", {}, headers=ok)
    assert status == 400 and "company and title" in json.loads(data)["error"]


CLOSED = {"linkedin": "4000000001", "company": "Globex", "title": "Machine Learning Engineer",
          "text": "Train machine learning models for Globex.", "closed": True}


def test_a_closed_page_marks_a_job_that_already_has_its_text(app):
    """LinkedIn's "No longer accepting applications" must show even when jobwatch had the text already (a job read
    or saved before): the job is marked closed, with a note, and the answer says so."""
    key = _alert_job(app)
    app.ext_posting({"linkedin": "4000000001", "company": "Globex", "title": "Machine Learning Engineer",
                     "text": "Train machine learning models for Globex."})
    assert not _job(app, key)[1]["closed"]
    got = app.ext_posting(CLOSED)
    assert got["key"] == key and got["closed"] is True and "LinkedIn says this posting is closed" in got["said"]
    rec = _job(app, key)[1]
    assert rec["closed"] and closed_state(rec) == "closed"
    assert "LinkedIn says it is not accepting applications any more" in rec["note"]
    again = app.ext_posting(CLOSED)  # a second read adds nothing new, and doesn't add the job twice
    assert again["key"] == key and again["closed"] is True
    assert _job(app, key)[1]["note"].count("not accepting applications") == 1


def test_a_closed_page_marks_a_job_still_without_text_and_a_skipped_one(app):
    key = _alert_job(app)
    store = Store(config.load(app.path).state)
    store.set_status([key], "skipped")
    store.close()
    got = app.ext_posting(CLOSED)
    assert got["key"] == key and got["closed"] and got["has_text"] and got["where"] == "applied"
    job, rec = _job(app, key)
    assert rec["status"] == "skipped" and closed_state(rec) == "closed" and job.description.startswith("Train")


def test_a_closed_page_for_a_job_jobwatch_hasnt_got_adds_it_closed(app):
    got = app.ext_posting({**CLOSED, "linkedin": "4000000077", "company": "Initech"})
    assert got["added"] and got["closed"] and "LinkedIn says this posting is closed" in got["said"]
    assert closed_state(_job(app, got["key"])[1]) == "closed"


def test_an_indeed_closed_page_says_indeed(app):
    got = app.ext_posting({"indeed": "ab12cd34ef56ab78", "company": "Globex", "title": "SRE", "text": "Run Globex.",
                           "closed": True})
    assert "Indeed says this posting is closed" in got["said"]
    assert "Indeed says it is not accepting" in _job(app, got["key"])[1]["note"]


def test_an_open_page_marks_nothing(app):
    key = _alert_job(app)
    got = app.ext_posting({**CLOSED, "closed": False})
    assert not got.get("closed") and "closed" not in got["said"] and not _job(app, key)[1]["closed"]


def test_the_jobs_own_page_open_again_reopens_it(app):
    """Read posting on a job marked closed finds its page taking applications (no closed banner): the mark goes, with
    a note, and the answer says so. A second open read changes nothing more."""
    key = _alert_job(app)
    app.ext_posting(CLOSED)
    got = app.ext_posting({**CLOSED, "linkedin": LI, "closed": False})
    assert got["key"] == key and got["reopened"] and "no longer marked closed" in got["said"]
    rec = _job(app, key)[1]
    assert not rec["closed"] and closed_state(rec) is None
    assert "LinkedIn shows it taking applications again" in rec["note"]
    again = app.ext_posting({**CLOSED, "closed": False})
    assert not again.get("reopened") and _job(app, key)[1]["note"].count("taking applications again") == 1


def test_another_postings_open_page_or_no_closed_word_never_reopens(app):
    """Only the job's own page reopens it: an open posting with the same company and title under another id is
    another opening (added on its own), and a save that says nothing about closed (the popup's) leaves the mark."""
    key = _alert_job(app)
    app.ext_posting(CLOSED)
    other = app.ext_posting({**CLOSED, "linkedin": "4000000055", "closed": False})
    assert other["key"] != key and not other.get("reopened")
    assert closed_state(_job(app, key)[1]) == "closed"
    said = app.ext_posting({k: v for k, v in CLOSED.items() if k != "closed"})
    assert said["key"] == key and not said.get("reopened") and closed_state(_job(app, key)[1]) == "closed"
