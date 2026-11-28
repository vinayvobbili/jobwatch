"""The interview rounds timeline in a real browser: a new application starts with an empty state that says how to begin,
the first round is added from the dialog with the keyboard, the next round is marked as the current step, a round opens
in a large dialog on top of the Details dialog (Esc closes the top one only), the notes' rounds are offered and never
added on their own, and the Company tab shows the chip and the timeline. Skipped where Playwright or its browser isn't
installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import os
from datetime import date, timedelta

import pytest

from jobwatch import config
from jobwatch.store import Store

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)

KEY = "manual:initech:field-engineer"


def seed(watchlist, **kw):
    store = Store(config.load(watchlist).state)
    store.add("Initech", "Field Engineer", status="interviewing", **kw)
    store.close()


def open_details(page, key=KEY):
    page.goto(page.url.split("#")[0] + "#applied")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.evaluate(f"openDetails({key!r})")
    sync_api.expect(page.locator("#dialog .rounds")).to_be_visible(timeout=10000)


def soon(days=3):
    return (date.today() + timedelta(days=days)).isoformat()


def test_a_new_application_starts_with_an_empty_state_and_the_first_round_is_added_by_keyboard(page, watchlist):
    seed(watchlist)
    open_details(page)
    rounds = page.locator("#dialog .rounds")
    sync_api.expect(rounds.locator(".rempty")).to_contain_text(
        "Add the first round when you have an interview, or set a next step")
    sync_api.expect(rounds.locator(".rnode.later")).to_have_count(0)  # nothing to show until there is a round
    add = rounds.get_by_role("button", name="Add round")
    sync_api.expect(add).to_have_class("btn primary small radd")
    add.click()
    form = rounds.locator("form.rform")
    sync_api.expect(form.get_by_label("Kind of round")).to_be_focused()  # the first field has the keyboard
    form.get_by_label("Kind of round").select_option("panel")
    sync_api.expect(form.locator(".rhelp")).to_contain_text("onsite loop")  # what the kind is
    form.get_by_label("Date").fill(soon())
    form.get_by_label("Time").fill("14:30")
    form.get_by_label("Who you met or will meet").fill("Dana Lee")
    form.get_by_label("Where").select_option("Zoom")
    form.get_by_label("Who you met or will meet").press("Enter")  # Enter saves
    nodes = rounds.locator(".rnode")
    sync_api.expect(nodes).to_have_count(2)  # the round and the dashed "later rounds" node
    sync_api.expect(nodes.nth(0)).to_have_attribute("aria-current", "step")
    sync_api.expect(nodes.nth(0)).to_contain_text("Panel / onsite loop")
    sync_api.expect(nodes.nth(0)).to_contain_text("with Dana Lee")
    sync_api.expect(nodes.nth(0)).to_contain_text("2:30 PM")
    sync_api.expect(nodes.nth(1)).to_contain_text("Later rounds: not scheduled yet")
    sync_api.expect(rounds.locator(".rempty")).to_have_count(0)
    assert page.errors == []
    page.keyboard.press("Escape")  # the list behind shows the chip
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".rchip").first).to_contain_text("Round 1 of ? · next: Panel / onsite loop")


def test_escape_closes_the_cancel_the_form_then_the_round_dialog_then_the_details_one_at_a_time(page, watchlist):
    seed(watchlist, next_step=f"Panel with Dana Lee {soon()}T14:30")
    store = Store(config.load(watchlist).state)
    store.track(KEY, round="panel")
    store.close()
    open_details(page)
    rounds, overlay = page.locator("#dialog .rounds"), page.locator("#overlay")
    rounds.get_by_role("button", name="Add round").click()
    sync_api.expect(rounds.locator("form.rform")).to_have_count(1)
    page.keyboard.press("Escape")  # the form
    sync_api.expect(rounds.locator("form.rform")).to_have_count(0)
    sync_api.expect(overlay).to_be_visible()
    rounds.locator(".rnode.upnext").get_by_role("button", name="Open round 1, Panel / onsite loop").click()
    big = page.locator(".rounds-dialog")
    sync_api.expect(big).to_contain_text("Round 1 · Panel / onsite loop")
    sync_api.expect(big).to_contain_text("Dana Lee")
    page.keyboard.press("Escape")  # the large dialog only
    sync_api.expect(big).to_have_count(0)
    sync_api.expect(overlay).to_be_visible()
    page.keyboard.press("Escape")  # then the Details dialog
    sync_api.expect(overlay).to_be_hidden()
    assert page.errors == []


def test_marking_the_next_round_done_records_how_it_went(page, watchlist):
    seed(watchlist, next_step=f"Intro call {soon(-1)}T10:00", note=None)
    store = Store(config.load(watchlist).state)
    store.track(KEY, round="recruiter_screen")
    store.close()
    open_details(page)
    rounds = page.locator("#dialog .rounds")
    held = rounds.locator(".rnode[data-state=held]")
    sync_api.expect(held).to_contain_text("That time has passed")
    held.get_by_role("button", name="How did it go?").click()
    big = page.locator(".rounds-dialog")
    big.get_by_label("How it went").fill("Went well")
    big.get_by_label("How it went").press("Enter")
    sync_api.expect(big.get_by_role("heading")).to_contain_text("Round 1")
    sync_api.expect(big).to_contain_text("Went well")
    page.keyboard.press("Escape")
    sync_api.expect(rounds.locator(".rnode[data-state=done]")).to_contain_text("Went well")
    sync_api.expect(rounds.locator(".rnode.later")).to_have_count(1)


def test_rounds_in_the_notes_are_offered_not_added_and_can_be_dismissed(page, watchlist):
    seed(watchlist, note="2026-11-12: Recruiter screen with Dana Lee done, went well.")
    open_details(page)
    rounds = page.locator("#dialog .rounds")
    offer = rounds.locator(".rstrip")
    sync_api.expect(offer).to_contain_text("Found 1 round in your notes")
    sync_api.expect(rounds.locator(".rnode")).to_have_count(0)  # nothing was added on its own
    offer.get_by_role("button", name="Not now").click()
    sync_api.expect(rounds.locator(".rstrip")).to_have_count(0)
    page.keyboard.press("Escape")
    open_details(page)  # remembered by the browser
    sync_api.expect(page.locator("#dialog .rounds .rstrip")).to_have_count(0)
    page.evaluate("localStorage.clear()")
    open_details(page)
    page.locator("#dialog .rounds .rstrip").get_by_role("button", name="Review").click()
    sync_api.expect(page.locator(".rounds-dialog")).to_contain_text("nothing is added until you press the button")
    page.locator(".rounds-dialog").get_by_role("button", name="Add rounds to 1 application").click()
    nodes = page.locator("#dialog .rounds .rnode")
    sync_api.expect(nodes.nth(0)).to_contain_text("inferred from your notes")
    sync_api.expect(nodes.nth(0)).to_contain_text("with Dana Lee")


def test_the_applications_page_offers_the_notes_rounds_once_for_everything(page, watchlist):
    seed(watchlist, note="2026-11-12: Recruiter screen with Dana Lee done, went well.")
    page.goto(page.url.split("#")[0] + "#applied")
    page.reload()
    page.wait_for_load_state("networkidle")
    strip = page.locator(".rstrip")
    sync_api.expect(strip).to_contain_text("Found 1 round in your notes across 1 application")
    strip.get_by_role("button", name="Not now").click()
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".rstrip")).to_have_count(0)


def test_the_company_page_shows_the_chip_and_opens_the_timeline(page, watchlist):
    seed(watchlist, next_step=f"Panel {soon()}T14:30")
    store = Store(config.load(watchlist).state)
    store.track(KEY, round="panel")
    store.close()
    page.goto(page.url.split("#")[0] + "#company/Initech")
    page.reload()
    page.wait_for_load_state("networkidle")
    line = page.locator(".rline")
    sync_api.expect(line.locator(".rchip")).to_contain_text("Round 1 of ? · next: Panel / onsite loop")
    line.get_by_role("button", name="Timeline").click()
    sync_api.expect(line.locator(".rnode.upnext")).to_have_count(1)
    sync_api.expect(line.locator(".rnode.later")).to_contain_text("not scheduled yet")
    assert page.errors == []


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_timeline_fits_a_phone_and_honours_reduced_motion(page, watchlist, scheme):
    seed(watchlist, next_step=f"Panel with Dana Lee and Sam Ortiz on Zoom {soon()}T14:30")
    store = Store(config.load(watchlist).state)
    store.track(KEY, round="panel", note="2026-11-12: Recruiter screen with Pat Kim done, went well.")
    store.close()
    page.emulate_media(color_scheme=scheme, reduced_motion="reduce")
    page.set_viewport_size({"width": 390, "height": 800})
    open_details(page)
    sync_api.expect(page.locator("#dialog .rnode.upnext")).to_have_count(1)
    sync_api.expect(page.locator("#dialog .rnode.upnext .rdot")).to_have_css("animation-name", "none")
    wide = page.evaluate("const d = document.getElementById('dialog'); d.scrollWidth - d.clientWidth")
    assert wide <= 1  # nothing scrolls sideways
    if shot := os.environ.get("ROUNDS_SHOT"):  # to look at it: ROUNDS_SHOT=/tmp/x pytest -k phone
        page.locator("#dialog .rounds").screenshot(path=f"{shot}-{scheme}.png")
    assert page.errors == []
