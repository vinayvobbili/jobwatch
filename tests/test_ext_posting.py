"""POST /ext/posting: the posting the person has open on LinkedIn (or on the company's site) fills in the job
jobwatch has from an alert, or adds one."""

import json

import pytest

from jobwatch import config
from jobwatch.store import Store
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
