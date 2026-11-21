"""The Activity tab's rows link to the jobs they are about, in a real browser: a Scored row's company and title open the
job's card on its tab (Queue, Applications), scrolled to and highlighted; a job with no card opens its details; a row
about several jobs folds out a list of links. Skipped where Playwright or its browser isn't installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import re

import pytest

from jobwatch import config
from jobwatch.store import Store

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)


@pytest.fixture
def seeded(watchlist, page):
    """Three made-up jobs (queued, screening, skipped) with the rows about them, then the Activity tab."""
    store = Store(config.load(watchlist).state)
    queued = store.add("Initech", "Principal Architect", status="queued", description="Design systems. " * 30)
    screening = store.add("Globex", "Staff Engineer", status="screening")
    skipped = store.add("Umbrella", "Data Lead", status="skipped")
    store.log("score", "Scored 88/100 Initech: Principal Architect (model-x)", jobs=[queued.key])
    store.log("score", "Scored 61/100 Globex: Staff Engineer (model-x)", jobs=[screening.key])
    store.log("score", "Scored 20/100 Umbrella: Data Lead (model-x)", jobs=[skipped.key])
    store.log("boards", "Found 2 postings taken down",
              detail=["Initech: Principal Architect", "Globex: Staff Engineer"], jobs=[queued.key, screening.key])
    store.close()
    page.goto(page.url.split("#")[0] + "#activity")
    page.wait_for_load_state("networkidle")
    return queued, screening, skipped


def scored_list(page):
    page.get_by_role("button", name="Scored", exact=True).click()
    page.wait_for_load_state("networkidle")


def test_a_scored_row_opens_its_jobs_card_on_the_queue_and_highlights_it(page, seeded):
    queued, _, _ = seeded
    scored_list(page)
    row = page.locator(".act", has_text="Scored 88/100")
    row.get_by_role("link", name="Initech: Principal Architect").click()
    card = page.locator(f'[id="job-{queued.key}"]')
    sync_api.expect(card).to_be_visible()
    sync_api.expect(card).to_have_class(re.compile(r"\bping\b"))
    sync_api.expect(page.locator('#tabs button[data-tab="queue"]')).to_have_class(re.compile(r"\bon\b"))
    assert page.errors == []


def test_an_applications_row_opens_its_card_on_applications(page, seeded):
    _, screening, _ = seeded
    scored_list(page)
    page.locator(".act", has_text="Scored 61/100").get_by_role("button", name="open card").click()
    card = page.locator(f'.card.app[data-key="{screening.key}"]')
    sync_api.expect(card).to_be_visible()
    sync_api.expect(card).to_have_class(re.compile(r"\bping\b"))
    assert page.errors == []


def test_a_job_with_no_card_opens_its_details(page, seeded):
    scored_list(page)
    page.locator(".act", has_text="Scored 20/100").get_by_role("link", name="Umbrella: Data Lead").click()
    sync_api.expect(page.locator("#dialog")).to_contain_text("Data Lead")
    assert page.errors == []


def test_a_row_about_several_jobs_folds_out_a_list_of_links(page, seeded):
    _, screening, _ = seeded
    row = page.locator(".act", has_text="Found 2 postings taken down")
    row.locator("details.act-jobs summary").click()
    links = row.locator("details.act-jobs a")
    assert links.all_inner_texts() == ["Initech: Principal Architect", "Globex: Staff Engineer"]
    links.nth(1).click()
    sync_api.expect(page.locator(f'.card.app[data-key="{screening.key}"]')).to_be_visible()
    assert page.errors == []
