"""Progressive loading in a real browser (headless Chromium through Playwright): a tab draws its head and placeholders
at once while its data is held back, fills in as each call is let through, shows its last data on a revisit and
refreshes behind it, and a late answer for a tab already left draws nothing. A call is held by keeping its route and
letting it go later. The data is made up. Skipped where Playwright or its browser isn't installed."""

import json
import time

import pytest

from jobwatch import config
from jobwatch.store import Store

from .test_browser import browser, jobs, sync_api, watchlist  # noqa: F401  (the same two fake boards and browser)

expect = sync_api.expect


class Held:
    """The calls of a page that match `wanted` are kept, not answered, until `release()`."""

    def __init__(self, page, wanted):
        self.routes = []
        page.route(lambda url: wanted in url, lambda route: self.routes.append(route))

    def seen(self, page):
        deadline = time.monotonic() + 10
        while not self.routes and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert self.routes, "the page never asked"

    def release(self):
        routes, self.routes = self.routes, []
        for r in routes:
            r.continue_()

    def fail(self, error):
        routes, self.routes = self.routes, []
        for r in routes:
            r.fulfill(status=500, content_type="application/json", body=json.dumps({"error": error}))


@pytest.fixture
def opened(browser, server, jobs):  # noqa: F811
    """A way to open the page on a tab with some calls held: opened("today", hold=["part=list"])."""
    pages = []

    def open_(tab, hold=(), **kw):
        page = browser.new_page(**kw)
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.held = {h: Held(page, h) for h in hold}
        page.goto(f"http://127.0.0.1:{server}/#{tab}")
        pages.append(page)
        return page

    yield open_
    for p in pages:
        for held in p.held.values():
            held.release()
        p.close()


def queue_two(watchlist):  # noqa: F811
    store = Store(config.load(watchlist).state)
    try:
        keys = [j.key for j, _ in store.jobs(("new",))][:2]
        store.set_status(keys, "queued")
    finally:
        store.close()
    return keys


def test_today_draws_its_head_filters_and_placeholders_before_any_data(opened):
    page = opened("today", hold=["part=list", "part=extra", "/api/hidden"])
    page.held["part=list"].seen(page)
    expect(page.locator("main .eyebrow")).to_have_text("Today")        # the head, at once
    expect(page.locator("main h1")).to_contain_text("ranked and ready")
    expect(page.locator("main .fbar")).to_be_visible()                  # the filter line, from the page's settings
    assert page.locator("main .skel-card").count() >= 3                 # placeholders where the cards go
    assert page.locator("main .card.job").count() == 0
    assert page.locator("main .hero .skel-stat").count() >= 1           # and where the tiles go


def test_today_fills_in_as_each_call_lands_the_list_before_the_extra(opened):
    page = opened("today", hold=["part=list", "part=extra", "/api/hidden"])
    page.held["part=list"].seen(page)
    page.held["part=list"].release()
    expect(page.locator("main .card.job").first).to_be_visible(timeout=10000)   # cards, with the extra still held
    assert page.locator("main .skel-card").count() == 0
    assert page.held["part=extra"].routes and page.held["/api/hidden"].routes
    page.held["part=extra"].release()
    page.held["/api/hidden"].release()
    page.wait_for_timeout(500)
    assert page.locator("main .card.job").count() > 0 and page.errors == []


def test_the_queue_shows_its_steps_at_once_and_its_cards_with_the_list(opened, watchlist):  # noqa: F811
    queue_two(watchlist)
    page = opened("queue", hold=["/api/queue?part=list", "/api/queue?part=extra"])
    page.held["/api/queue?part=list"].seen(page)
    expect(page.locator("main h1")).to_have_text("Apply queue")
    expect(page.locator("main .panel h4", has_text="For each job")).to_be_visible()   # static parts, now
    assert page.locator("main .skel-card").count() >= 1
    page.held["/api/queue?part=list"].release()
    expect(page.locator("main .card.job")).to_have_count(2, timeout=10000)
    assert page.held["/api/queue?part=extra"].routes                      # still on its way
    page.held["/api/queue?part=extra"].release()
    page.wait_for_timeout(300)
    assert page.locator("main .card.job").count() == 2 and page.errors == []


@pytest.mark.parametrize("tab, path, head", [("applied", "/api/applications", "Applications"),
                                             ("interviews", "/api/interviews", "Interviews"),
                                             ("referrals", "/api/referrals", "Referrals"),
                                             ("skills", "/api/skills", "Skills to build"),
                                             ("comps", "/api/comps", "Comps"),
                                             ("activity", "/api/activity?", "Activity")])
def test_every_data_tab_has_its_head_and_placeholders_while_it_waits(opened, tab, path, head):
    page = opened(tab, hold=[path])
    page.held[path].seen(page)
    expect(page.locator("main h1")).to_have_text(head)
    assert page.locator("main .skel").count() >= 1
    page.held[path].release()
    expect(page.locator("main .skel")).to_have_count(0, timeout=10000)
    assert page.errors == []


def test_the_company_page_has_its_box_and_placeholders_while_its_jobs_load(opened):
    page = opened("company/Acme", hold=["/api/company"])
    page.held["/api/company"].seen(page)
    expect(page.locator("main h1")).to_have_text("Company")
    assert page.locator("main .skel").count() >= 1
    page.held["/api/company"].release()
    expect(page.locator("main h1")).to_have_text("Acme", timeout=10000)


def test_a_late_answer_for_a_tab_already_left_draws_nothing(opened):
    page = opened("today", hold=["part=list"])
    page.held["part=list"].seen(page)
    page.locator('nav [data-tab="queue"]').click()
    expect(page.locator("main h1")).to_have_text("Apply queue", timeout=10000)
    page.held["part=list"].release()           # Today's answer comes after the user has gone to the Queue
    page.wait_for_timeout(800)
    expect(page.locator("main h1")).to_have_text("Apply queue")
    assert "ranked and ready" not in page.locator("main").inner_text() and page.errors == []


def test_a_revisit_shows_the_last_data_at_once_and_refreshes_behind_it(opened):
    page = opened("today")
    expect(page.locator("main .card.job").first).to_be_visible(timeout=10000)
    page.wait_for_timeout(800)                                           # its calls have all landed and been kept
    page.locator('nav [data-tab="skills"]').click()
    expect(page.locator("main h1")).to_have_text("Skills to build", timeout=10000)
    held = Held(page, "part=list")
    page.locator('nav [data-tab="today"]').click()
    held.seen(page)
    expect(page.locator("main .card.job").first).to_be_visible()         # the last data, with the new call held
    assert page.locator("main .skel-card").count() == 0
    expect(page.locator("#updating")).to_contain_text("Updating")
    held.release()
    expect(page.locator("#updating")).to_be_hidden(timeout=10000)
    assert page.errors == []


def test_a_part_that_fails_says_so_where_it_goes_with_retry_and_the_rest_stays(opened):
    page = opened("today", hold=["part=extra"])
    page.held["part=extra"].seen(page)
    page.held["part=extra"].fail("the scorer is busy")
    expect(page.locator("main .part-error")).to_contain_text("Couldn't load each job's pay and advice", timeout=10000)
    assert "the scorer is busy" in page.locator("main .part-error").inner_text()
    expect(page.locator("main .card.job").first).to_be_visible()         # the list is still there
    page.unroute_all()
    page.locator("main .part-error button", has_text="Retry").click()
    expect(page.locator("main .part-error")).to_have_count(0, timeout=10000)
    assert page.locator("main .card.job").count() > 0


def test_a_tab_that_cannot_load_is_never_a_blank_pane(opened):
    page = opened("referrals", hold=["/api/referrals"])
    page.held["/api/referrals"].seen(page)
    page.held["/api/referrals"].fail("no connections file")
    expect(page.locator("main .part-error")).to_contain_text("no connections file", timeout=10000)
    expect(page.locator("main h1")).to_have_text("Referrals")            # the head stays
    page.unroute_all()
    page.locator("main .part-error button", has_text="Retry").click()
    expect(page.locator("main .part-error")).to_have_count(0, timeout=10000)


def test_the_page_says_it_is_starting_until_the_api_answers(opened):
    page = opened("today", hold=["/api/settings"])
    page.held["/api/settings"].seen(page)
    expect(page.locator("main h1")).to_have_text("jobwatch")             # the shell in the HTML
    assert page.locator("main .skel").count() >= 1
    expect(page.locator("#startNote")).to_contain_text("Starting")
    page.held["/api/settings"].release()
    expect(page.locator("main .eyebrow")).to_have_text("Today", timeout=10000)


def test_placeholders_hold_still_under_reduced_motion(opened):
    page = opened("today", hold=["part=list"], reduced_motion="reduce")
    page.held["part=list"].seen(page)
    expect(page.locator("main .skel-card").first).to_be_visible()
    assert page.locator("main .skel-card .skel").first.evaluate(
        "el => getComputedStyle(el, '::after').display") == "none"
    page2 = opened("today", hold=["part=list"], reduced_motion="no-preference")
    page2.held["part=list"].seen(page2)
    assert page2.locator("main .skel-card .skel").first.evaluate(
        "el => getComputedStyle(el, '::after').animationName") == "skel-sweep"
