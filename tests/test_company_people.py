# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
"""The Company tab lists the company's people once, in its left panel ("People you know"): its job cards have no
People row (it repeated the same names on every card), but each keeps "Who to contact", which is per job, next to
Details. Other tabs' cards keep their People row. All people, companies and jobs are made up."""

import pytest

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_referrals_page import INITECH, open_referrals


def open_company(page, name):
    page.goto(page.url.split("#")[0] + "#company/" + name)
    page.reload()
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_company_tab_lists_the_people_once_and_its_job_cards_have_no_people_row(page, watchlist, scheme):
    page.emulate_media(color_scheme=scheme)
    open_referrals(page, watchlist)
    open_company(page, "Initech")
    cards = page.locator(".card.job")
    sync_api.expect(cards.first).to_be_visible()
    assert cards.count() >= 3  # several jobs at one company: the case where the names repeated
    panel = page.locator(".panel", has=page.locator("h4", has_text="People you know"))
    sync_api.expect(panel).to_have_count(1)
    sync_api.expect(panel.locator(".person")).to_have_count(5)  # the left panel holds each person...
    sync_api.expect(page.locator("main .ptext", has_text="Ana Li (Staff Engineer)")).to_have_count(1)  # ...once
    sync_api.expect(page.locator("main [data-row=people]")).to_have_count(0)
    sync_api.expect(cards.locator(".person")).to_have_count(0)
    sync_api.expect(cards.locator(".klabel", has_text="People")).to_have_count(0)
    sync_api.expect(page.get_by_text("more on LinkedIn")).to_have_count(1)  # one search link, in the panel
    assert page.errors == []


def test_who_to_contact_is_still_one_button_per_job_beside_details_and_opens_that_jobs_panel(page, watchlist):
    open_referrals(page, watchlist)
    open_company(page, "Initech")
    cards = page.locator(".card.job")
    sync_api.expect(cards.first).to_be_visible()
    for n in range(cards.count()):  # applied, queued and open jobs alike
        foot = cards.nth(n).locator(".jc-foot")
        sync_api.expect(foot.locator(".who-btn")).to_have_count(1)
        sync_api.expect(foot.locator(".act-details")).to_have_count(1)
    card = cards.first
    sync_api.expect(card.locator(".who")).to_be_hidden()
    card.locator(".who-btn").click()
    sync_api.expect(card.locator(".who")).to_be_visible()
    sync_api.expect(card.locator(".who .who-search a").first).to_be_visible()  # LinkedIn searches for that job
    sync_api.expect(card.locator(".who .who-person").first).to_be_visible()  # Initech's people, as people to contact
    sync_api.expect(cards.nth(1).locator(".who")).to_be_hidden()  # only this job's panel opened
    card.locator(".who-btn").click()
    sync_api.expect(card.locator(".who")).to_be_hidden()
    assert page.errors == []


def test_a_company_with_nobody_known_has_only_the_search_and_its_cards_still_offer_who_to_contact(page, watchlist):
    open_referrals(page, watchlist, connections=None, companies=(("Initech", INITECH[:2]),), globex=False,
                   wait_for_cards=False)
    open_company(page, "Initech")
    sync_api.expect(page.locator(".card.job").first).to_be_visible()
    sync_api.expect(page.locator(".panel .person")).to_have_count(0)
    sync_api.expect(page.get_by_text("Find someone who can refer you")).to_have_count(1)  # once, in the panel
    sync_api.expect(page.locator(".card.job .who-btn")).to_have_count(2)
    assert page.errors == []


def test_other_tabs_keep_the_people_row_on_their_cards(page, watchlist):
    open_referrals(page, watchlist)
    page.goto(page.url.split("#")[0] + "#queue")
    page.reload()
    page.wait_for_load_state("networkidle")
    card = page.locator(".card.job").first  # Initech's queued Release Engineer
    sync_api.expect(card).to_be_visible()
    sync_api.expect(card.locator("[data-row=people]")).to_have_count(1)
    sync_api.expect(card.locator("[data-row=people] .who-btn")).to_have_count(1)
    assert page.errors == []
