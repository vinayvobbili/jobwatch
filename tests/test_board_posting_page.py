"""The posting form on a card in a real browser (headless Chromium through Playwright): a job from a board with no
posting text offers Read posting, never a link box that can't work; what goes wrong shows under the form until the next
try, in words, never as the job's key; a success shows before the card changes. A job added by hand keeps its form.
Every job, company and address is made up. Skipped where Playwright or its browser isn't installed."""

import json

import pytest

from jobwatch import config, sources, watch
from jobwatch.models import Job
from jobwatch.store import Store

sync_api = pytest.importorskip("playwright.sync_api")

BOARD = "fund.example/jobs/portfolio-jobs/"
LISTING = "https://jobs.fund.example/companies/globex/jobs/77"
OWN = "https://globex.example/careers/77"
OTHER = "https://globex.example/job-detail/4711/"
LABEL = "Link to the company's own posting (only used to read the text)"
DESCRIPTION ="Build detection pipelines in Python. You have 5+ years of experience. " * 4


def posting_page(text: str) -> str:
    data = {"@type": "JobPosting", "title": "Staff Python Engineer", "description": text,
            "hiringOrganization": {"name": "Globex"}}
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script></html>'


@pytest.fixture(autouse=True)
def pages(monkeypatch, web):
    served = {OWN: posting_page(DESCRIPTION), OTHER: posting_page(DESCRIPTION)}

    def get(url, timeout=30):
        if url.endswith("/robots.txt"):
            return ""
        if url not in served:
            raise sources.NotFound(url)
        return served[url]

    monkeypatch.setattr(sources, "get_text", get)

    def score(jobs, *a, **k):  # no model in a test
        return {j.key: {"score": 70, "must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}
                for j in jobs}, {}

    monkeypatch.setattr(watch, "score_jobs", score)


@pytest.fixture
def board_jobs(watchlist):
    """Today: two jobs from a VC board with no text (one whose link is the fund's own page, one whose link is the
    company's posting) and one added by hand."""
    (watchlist.parent / "resume.txt").write_text("Platform engineer with ten years of Python at Initech.")
    watchlist.write_text(watchlist.read_text() + "resume: resume.txt\n")
    store = Store(config.load(watchlist).state)
    try:
        for n, (company, url) in enumerate([("Globex", LISTING), ("Umbrella", OWN)], 1):
            store.keep(Job(source="vc", company=BOARD, id=f"job-{n}", title=f"Staff Python Engineer {n}", url=url,
                           company_name=company, locations=["Remote"], remote=True))
        store.add("Hooli", "Staff Python Engineer 3", status="new", location="Remote",
                  url="https://hooli.example/careers/3")
    finally:
        store.close()
    return watchlist


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"no Chromium for Playwright: {e.message.splitlines()[0]}")
        yield b
        b.close()


def open_today(browser, server):
    page = browser.new_page(viewport={"width": 1100, "height": 800})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    page.locator("[id^=job-]").first.wait_for(timeout=8000)
    return page


def card_of(page, title):
    return page.locator("[id^=job-]", has_text=title)


def job(watchlist, title):
    store = Store(config.load(watchlist).state)
    try:
        return next(j for j, _ in store.iter_jobs(("new", "shown", "queued")) if j.title == title)
    finally:
        store.close()


def test_a_board_job_whose_link_only_lists_it_asks_for_the_companys_own_page(browser, server, board_jobs):
    page = open_today(browser, server)
    try:
        card = card_of(page, "Staff Python Engineer 1")
        assert card.locator("button", has_text="Add the posting").count() == 0  # a control that couldn't work
        card.locator("button.primary", has_text="Read posting").click()
        box = card.get_by_label(LABEL)
        sync_api.expect(box).to_be_visible()
        card.locator("textarea").wait_for()
        # an address that has no posting: the reason stays under the form, in words, with the company and title
        box.fill("https://globex.example/gone")
        card.locator(".post-form button.primary").click()
        alert = card.get_by_role("alert")
        sync_api.expect(alert).to_contain_text("Globex: Staff Python Engineer 1")
        sync_api.expect(alert).to_contain_text("Paste its text here instead")
        assert "vc:" not in alert.inner_text()
        sync_api.expect(page.locator("#toast")).to_contain_text("Globex: Staff Python Engineer 1")
        page.wait_for_timeout(7000)  # the toast has gone; the message under the form has not
        sync_api.expect(alert).to_be_visible()
        # the next try: a page that has the posting
        box.fill(OTHER)
        card.locator(".post-form button.primary").click()
        sync_api.expect(card.locator(".post-form button.primary")).to_have_text("Saved: now scoring")
        sync_api.expect(alert).to_contain_text("the job's link stays the board's")
        sync_api.expect(card.locator("textarea")).to_have_count(0, timeout=5000)  # the card was drawn again
        assert job(board_jobs, "Staff Python Engineer 1").url == LISTING
        assert "Build detection pipelines" in job(board_jobs, "Staff Python Engineer 1").description
        assert page.errors == []
    finally:
        page.close()


def test_a_board_job_whose_link_is_the_posting_reads_it_with_one_press(browser, server, board_jobs):
    page = open_today(browser, server)
    try:
        card = card_of(page, "Staff Python Engineer 2")
        assert card.locator("input[type=url]").count() == 0
        card.locator("button.primary", has_text="Read posting").click()
        sync_api.expect(page.locator("#toast")).to_contain_text("from globex.example; the job's link stays the board's")
        sync_api.expect(card.locator("button", has_text="Read posting")).to_have_count(0, timeout=5000)
        assert job(board_jobs, "Staff Python Engineer 2").url == OWN
        assert "Build detection pipelines" in job(board_jobs, "Staff Python Engineer 2").description
        assert page.errors == []
    finally:
        page.close()


def test_a_board_jobs_text_can_be_pasted(browser, server, board_jobs):
    page = open_today(browser, server)
    try:
        card = card_of(page, "Staff Python Engineer 2")
        card.locator("button", has_text="Paste the text instead").click()
        assert card.locator("input[type=url]").count() == 0  # its link is the board's: no box for another
        card.locator("textarea").fill("Build agents in Python. 5+ years.")
        card.locator(".post-form button.primary", has_text="Save").click()
        sync_api.expect(card.locator("textarea")).to_have_count(0, timeout=5000)
        assert job(board_jobs, "Staff Python Engineer 2").description == "Build agents in Python. 5+ years."
    finally:
        page.close()


def test_a_job_added_by_hand_keeps_its_form(browser, server, board_jobs):
    page = open_today(browser, server)
    try:
        card = card_of(page, "Staff Python Engineer 3")
        card.locator("button", has_text="Add the posting").click()
        sync_api.expect(card.get_by_label("Link to the company's posting")).to_be_visible()
        assert "only used to read" not in card.inner_text()
        card.locator("textarea").fill("Build pipelines. 3+ years.")
        card.locator(".post-form button.primary", has_text="Save").click()
        sync_api.expect(card.locator("textarea")).to_have_count(0, timeout=5000)
        assert job(board_jobs, "Staff Python Engineer 3").description == "Build pipelines. 3+ years."
    finally:
        page.close()
