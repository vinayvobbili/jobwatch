"""A job from a board that has no posting text (a VC portfolio board lists a job with its link alone) gets its text
from a page the person gives, or from its own link, without its link ever changing. A job added by hand is as it was.
Every company, job and address is made up."""

import json

import pytest

from jobwatch import config, sources, watch
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import ApiError, App

BOARD = "fund.example/jobs/portfolio-jobs/"
KEY = f"vc:{BOARD}:globex-77"
LISTING = "https://jobs.fund.example/companies/globex/jobs/77"  # the fund's own page: lists the job, isn't its posting
OWN_PAGE = "https://globex.example/job-detail/4711/"
TEXT = "Build detection pipelines in Python. You have 5+ years of experience. Pay: $150,000 - $190,000 a year. " * 3


def page(description: str = TEXT) -> str:
    data = {"@type": "JobPosting", "title": "Staff Python Engineer", "description": description,
            "hiringOrganization": {"name": "Globex"}, "datePosted": "2026-11-20"}
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body>hi</body></html>'


@pytest.fixture
def pages(monkeypatch, web):
    """Pages by address: sources.get_text serves them (robots.txt allows all), anything else is a 404."""
    served = {OWN_PAGE: page()}

    def get(url, timeout=30):
        if url.endswith("/robots.txt"):
            return ""
        if url not in served:
            raise sources.NotFound(url)
        return served[url]

    monkeypatch.setattr(sources, "get_text", get)
    return served


@pytest.fixture
def app(watchlist):
    return App(watchlist)


def add_board_job(app, url: str = LISTING) -> str:
    job = Job(source="vc", company=BOARD, id="globex-77", title="Staff Python Engineer", url=url, company_name="Globex")
    store = Store(config.load(app.path).state)
    try:
        store.keep(job)
    finally:
        store.close()
    return job.key


def job_of(app, key):
    store = Store(config.load(app.path).state)
    try:
        return store.find(key)[0]
    finally:
        store.close()


def test_a_page_given_for_a_board_job_gives_its_text_and_leaves_its_link(app, pages):
    key = add_board_job(app)
    assert key == KEY
    r = app.post_posting({"key": key, "url": OWN_PAGE})
    assert r["has_text"] is True and "scoring" in r and "board" not in r
    assert r["said"] == f"Read {len(TEXT.strip()):,} characters from globex.example; the job's link stays the board's"
    job = job_of(app, key)
    assert job.url == LISTING and job.description.startswith("Build detection pipelines")
    assert job.salary_min == 150_000  # the pay fills in as it does for any posting read from its link
    assert job.posted is not None


def test_a_board_jobs_own_link_is_read_for_its_text(app, pages):
    own = "https://globex.example/careers/77"
    pages[own] = page("Own link. " * 40)
    key = add_board_job(app, own)
    r = app.post_posting({"key": key, "url": own})
    assert r["said"] == "Read 399 characters from globex.example; the job's link stays the board's"
    assert job_of(app, key).url == own and job_of(app, key).description.startswith("Own link.")


def test_pasted_text_is_saved_for_a_board_job_and_its_link_stays(app, pages):
    key = add_board_job(app)
    r = app.post_posting({"key": key, "text": "Build agents in Python. 5+ years."})
    assert r["said"] == "Saved the pasted text; the job's link stays the board's" and r["has_text"] is True
    job = job_of(app, key)
    assert job.url == LISTING and job.description == "Build agents in Python. 5+ years."


def test_a_page_that_cant_be_read_says_why_and_to_paste_the_text(app, pages):
    key = add_board_job(app)
    with pytest.raises(ApiError) as e:
        app.post_posting({"key": key, "url": "https://globex.example/gone"})
    said = str(e.value)
    assert "Globex: Staff Python Engineer" in said and "globex.example" in said and "Paste its text" in said
    assert key not in said
    pages["https://globex.example/plain"] = "<html><body>Jobs at Globex</body></html>"
    with pytest.raises(ApiError, match="no JobPosting markup"):
        app.post_posting({"key": key, "url": "https://globex.example/plain"})
    assert job_of(app, key).description == "" and job_of(app, key).url == LISTING


def test_robots_txt_is_kept_to(app, pages, monkeypatch):
    key = add_board_job(app)
    get = sources.get_text

    def closed(url, timeout=30):
        return "User-agent: *\nDisallow: /job-detail/" if url.endswith("/robots.txt") else get(url)

    monkeypatch.setattr(sources, "get_text", closed)
    with pytest.raises(ApiError, match=r"robots\.txt doesn't allow"):
        app.post_posting({"key": key, "url": OWN_PAGE})


def test_linkedin_and_indeed_are_left_to_the_browser_extension(app, pages):
    key = add_board_job(app)
    with pytest.raises(ApiError, match="signed-in browser"):
        app.post_posting({"key": key, "url": "https://www.linkedin.com/jobs/view/4000000001/"})


def test_a_board_job_with_neither_link_nor_text_is_asked_for_one(app, pages):
    key = add_board_job(app)
    with pytest.raises(ApiError, match="Globex: Staff Python Engineer"):
        app.post_posting({"key": key})


def test_a_board_job_that_has_its_text_keeps_it(app, pages):
    key = add_board_job(app)
    app.post_posting({"key": key, "text": "The first text."})
    with pytest.raises(ApiError, match="already has its posting text"):
        app.post_posting({"key": key, "url": OWN_PAGE})
    with pytest.raises(ApiError, match="Globex: Staff Python Engineer comes from its board"):
        app.post_posting({"key": key, "text": "Another."})
    assert job_of(app, key).description == "The first text."


def test_a_job_added_by_hand_is_as_it_was(app, pages):
    key = app.post_add({"company": "Umbrella", "title": "Data Engineer", "status": "queued"})["key"]
    r = app.post_posting({"key": key, "text": "Build pipelines. 3+ years."})
    assert r == {"key": key, "said": "text saved", "has_text": True}
    other = app.post_add({"company": "Initech", "title": "Staff Python Engineer", "status": "queued"})["key"]
    r = app.post_posting({"key": other, "url": OWN_PAGE})
    assert r["said"].startswith("link saved") and job_of(app, other).url == OWN_PAGE  # its link is set, as before
    with pytest.raises(ApiError, match="send a link to the posting, or its text"):
        app.post_posting({"key": other})


def test_a_board_jobs_link_cant_be_changed_anywhere_else(app, pages):
    """The rule stays: set_url and set_link refuse a board job, in words that name it (never its key)."""
    key = add_board_job(app)
    store = Store(config.load(app.path).state)
    try:
        for change in (lambda: store.set_url(key, OWN_PAGE), lambda: watch.set_link(store, key, OWN_PAGE)):
            with pytest.raises(ValueError, match="Globex: Staff Python Engineer comes from its board") as e:
                change()
            assert key not in str(e.value)
        assert store.find(key)[0].url == LISTING
    finally:
        store.close()


def test_read_text_takes_the_page_reader_as_get(app, pages):
    """watch.read_text on its own: a link without its scheme, and a reader of the caller's."""
    key = add_board_job(app)
    store = Store(config.load(app.path).state)

    def get(url, timeout=30):
        return "" if url.endswith("robots.txt") else page()

    try:
        said = watch.read_text(store, key, "globex.example/job-detail/4711/", get=get)
        assert said.startswith("Read ") and "from globex.example" in said
    finally:
        store.close()
