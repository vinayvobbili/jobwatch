"""A company's logo on a card goes to the Company tab, as the company's name does, in a real browser: Today, Queue,
Applications (cards and table) and Interviews have it as a button named "See everything at <company>", a click or Enter
or Space opens the Company tab and nothing else (no Details dialog), and the Company tab's own head has no
logo link (Referrals' cards route their logo themselves and keep a plain monogram). Skipped where
Playwright or its browser isn't installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
from datetime import date, timedelta

import pytest

from jobwatch import config
from jobwatch.store import Store

from .test_browser import browser, jobs, page, sync_api, watchlist  # noqa: F401 (fixtures)


def seed(watchlist, company="Initech", title="Field Engineer", **kw):
    store = Store(config.load(watchlist).state)
    job = store.add(company, title, **kw)
    store.close()
    return job


def show(page, tab):
    page.goto(page.url.split("#")[0] + "#" + tab)
    page.reload()
    page.wait_for_load_state("networkidle")


def logo(page, company="Initech"):
    return page.get_by_role("button", name=f"See everything at {company}", exact=True).first


def assert_on_company_tab(page, company="Initech"):
    sync_api.expect(page.locator(".pagehead h1")).to_have_text(company)
    assert page.url.endswith(f"#company/{company}")
    assert page.locator("#overlay").evaluate("e => getComputedStyle(e).display") == "none"  # no Details dialog
    assert page.errors == []


def today_card(page, company="Acme"):
    show(page, "today")
    card = page.locator(".card.job", has=page.locator("b.co", has_text=company)).first
    sync_api.expect(card).to_be_visible()
    return card


def test_the_logo_on_a_today_card_opens_the_company_tab_like_the_name(jobs, page):
    card = today_card(page)
    button = card.locator("button.mono-link")
    sync_api.expect(button).to_have_attribute("aria-label", "See everything at Acme")
    sync_api.expect(button).to_have_attribute("type", "button")
    assert button.evaluate("e => getComputedStyle(e).cursor") == "pointer"
    button.click()
    assert_on_company_tab(page, "Acme")


@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_the_logo_opens_the_company_tab_from_the_keyboard(jobs, page, key):
    button = today_card(page).locator("button.mono-link")
    button.focus()
    sync_api.expect(button).to_be_focused()  # in the tab order
    button.press(key)
    assert_on_company_tab(page, "Acme")


def test_the_logo_and_the_name_say_the_same_thing_and_the_name_still_works(jobs, page):
    card = today_card(page)
    sync_api.expect(card.locator("b.co")).to_have_attribute("title", "See everything at Acme")
    sync_api.expect(card.locator("button.mono-link")).to_have_attribute("title", "See everything at Acme")
    card.locator("b.co").click()
    assert_on_company_tab(page, "Acme")


def test_the_logo_on_a_queue_card_opens_the_company_tab(page, watchlist):
    seed(watchlist, status="queued")
    show(page, "queue")
    logo(page).click()
    assert_on_company_tab(page)


def test_the_logo_on_an_application_card_opens_the_company_tab(page, watchlist):
    seed(watchlist, status="applied")
    show(page, "applied")
    logo(page).click()
    assert_on_company_tab(page)


def test_the_logo_in_the_applications_table_opens_the_company_tab(page, watchlist):
    seed(watchlist, status="applied")
    show(page, "applied")
    page.evaluate("appView.view = 'table'; render()")
    row = page.locator("table.apps tbody tr").first
    sync_api.expect(row).to_be_visible()
    row.locator("button.mono-link").click()
    assert_on_company_tab(page)


def test_the_logo_on_an_interview_card_opens_the_company_tab_and_not_its_details(page, watchlist):
    soon = (date.today() + timedelta(days=2)).isoformat()
    seed(watchlist, status="interviewing", next_step="Phone screen", follow_up=soon)
    show(page, "interviews")
    card = page.locator(".card.interview").first
    sync_api.expect(card).to_be_visible()
    card.locator("button.mono-link").click()
    assert_on_company_tab(page)  # the card itself opens Details; the logo must not


def test_the_company_tabs_own_head_has_no_logo_link(page, watchlist):
    seed(watchlist, status="queued")
    open_company = page.url.split("#")[0] + "#company/Initech"
    page.goto(open_company)
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".pagehead h1")).to_have_text("Initech")
    assert page.locator(".pagehead .mono, .pagehead .mono-link").count() == 0
    assert page.errors == []
