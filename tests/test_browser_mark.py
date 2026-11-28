"""A button on a Today card answers the moment it is pressed, in a real browser (headless Chromium through Playwright):
the card dims and its buttons turn off while the server works, the pressed one says what it is doing, a second click
does nothing, and a request that fails puts everything back with the reason. The /api/mark answer is held in the
browser by route interception, so the test decides how long the server takes. Skipped where Playwright or its browser
isn't installed (`pip install -e ".[browser]"` then `playwright install chromium`)."""

import re

import pytest

from .conftest import TOKEN, request

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"no Chromium for Playwright: {e.message.splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def today(browser, server):
    """Today with the fake boards' jobs (Acme, Globex, Initech) on it; `page.marks` holds each held /api/mark request
    (see `hold`), `page.errors` the script errors."""
    assert request(server, "POST", "/api/fetch", {}, headers={"X-Jobwatch-Token": TOKEN})[0] == 200
    page = browser.new_page()
    page.errors, page.marks = [], []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    yield page
    page.close()


def hold(page):
    """Keep every POST to /api/mark in the browser until the test answers it (page.marks[i])."""
    page.route("**/api/mark", lambda route: page.marks.append(route))


def first_card(page):
    """The top job's card, found again by its id (`.first` would be the next card once this one leaves)."""
    first = page.locator(".card.job").first
    expect(first).to_be_visible()
    return page.locator(f'[id="{first.get_attribute("id")}"]')


def test_queue_shows_it_was_pressed_at_once_and_a_second_click_does_nothing(today):
    hold(today)
    card = first_card(today)
    queue = card.locator(".act-queue")
    queue.click()
    expect(card).to_have_class(re.compile(r"\bpending\b"))
    expect(queue).to_have_text(re.compile(r"^Queuing… \d+s$"))  # the word, then the seconds it has been waiting
    expect(queue).to_have_class(re.compile(r"\bbusy\b"))
    expect(queue).to_be_disabled()
    expect(card.locator(".act-skip")).to_be_disabled()
    expect(card.locator(".act-details")).to_be_disabled()
    queue.click(force=True)  # a second click on a disabled button goes nowhere
    today.wait_for_timeout(200)
    assert len(today.marks) == 1
    today.marks[0].continue_()  # the server answers: the card leaves, with its toast
    expect(card).to_have_count(0)
    expect(today.locator("#toastText")).to_contain_text("Queued")
    assert today.errors == []


def test_skip_says_what_it_is_doing(today):
    hold(today)
    card = first_card(today)
    card.locator(".act-skip").click()
    expect(card.locator(".act-skip")).to_have_text(re.compile(r"^Skipping… \d+s$"))
    expect(card.locator(".act-queue")).to_be_disabled()
    today.marks[0].continue_()
    expect(card).to_have_count(0)


def test_a_failed_mark_puts_the_card_back_and_says_why(today):
    today.route("**/api/mark", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"error": "the store is busy"}'))
    card = first_card(today)
    queue = card.locator(".act-queue")
    queue.click()
    expect(today.locator("#toastText")).to_have_text("the store is busy")
    expect(card).not_to_have_class(re.compile(r"\bpending\b"))
    expect(queue).to_have_text("Queue")
    expect(queue).to_be_enabled()
    expect(card.locator(".act-skip")).to_be_enabled()
    expect(card.locator(".busy-spin")).to_have_count(0)
    assert today.errors == []


def test_a_request_that_cannot_reach_the_server_puts_the_card_back_too(today):
    today.route("**/api/mark", lambda route: route.abort())
    card = first_card(today)
    card.locator(".act-queue").click()
    expect(today.locator("#toastText")).not_to_be_empty()
    expect(card).not_to_have_class(re.compile(r"\bpending\b"))
    expect(card.locator(".act-queue")).to_be_enabled()
