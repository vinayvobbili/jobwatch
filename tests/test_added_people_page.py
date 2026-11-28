# ruff: noqa: F811, E501  (a test's `page` argument is the fixture imported from test_browser; the node scripts keep long lines)
"""Adding a person by hand, in the page (static/index.html): the toolbar's "Add a person" and a card's "+ Add" open one large dialog
(Esc closes, Tab stays inside, it stacks above the others), name and company are required, a person already listed is flagged as it is
typed, and a saved person is on the company's card with the muted Ask? pill, the "added by hand" tag and a toast with Undo; their
dialog edits or deletes them (a LinkedIn connection's has no Delete). Headless Chromium through Playwright, skipped where it isn't
installed. Every person and company is made up."""

import pytest

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_referrals_page import card, company_names, open_referrals, quiet_page, referrals_page, row  # noqa: F401 (fixtures)


def add_button(page):
    return page.get_by_role("button", name="Add a person", exact=True)


def dialog(page):
    return page.locator(".person-dialog")


def fill_in(page, name="Rae Quinn", company="Umbrella", **more):
    box = dialog(page)
    box.locator("input[name=name]").fill(name)
    box.locator("input[name=company]").fill(company)
    for key, value in more.items():
        box.locator(f"[name={key}]").fill(value)


def test_the_toolbar_button_opens_a_large_dialog_that_esc_closes_and_tab_stays_inside(referrals_page):
    page = referrals_page
    button = add_button(page)
    button.click()
    sync_api.expect(dialog(page)).to_be_visible()
    sync_api.expect(dialog(page).get_by_role("heading", name="Add a person")).to_be_visible()
    sync_api.expect(dialog(page).locator("input[name=name]")).to_be_focused()
    box = dialog(page).bounding_box()
    assert box["width"] > 700 and box["height"] > 500  # the large dialog, not a popover
    for _ in range(30):  # Tab never leaves it
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('.person-dialog')")
    page.keyboard.press("Escape")
    sync_api.expect(dialog(page)).to_have_count(0)
    sync_api.expect(button).to_be_focused()
    assert page.errors == []


def test_it_stacks_above_a_company_dialog_and_esc_closes_only_the_top_one(referrals_page):
    page = referrals_page
    card(page, "Initech").get_by_role("button", name="Add a person at Initech").click()
    sync_api.expect(dialog(page)).to_be_visible()
    sync_api.expect(dialog(page).locator("input[name=company]")).to_have_value("Initech")
    page.keyboard.press("Escape")
    sync_api.expect(dialog(page)).to_have_count(0)
    card(page, "Initech").locator(".ref-know").click()
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(1)
    row_name = page.locator(".ref-dialog .ref-p .pp-namebtn").first
    row_name.click()
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(2)
    page.keyboard.press("Escape")
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(1)
    assert page.errors == []


def test_name_and_company_are_required(referrals_page):
    page = referrals_page
    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.url.endswith("/api/referrals/add") else None)
    add_button(page).click()
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(dialog(page)).to_contain_text("Their name is needed.")
    sync_api.expect(dialog(page)).to_contain_text("Where they work is needed.")
    sync_api.expect(dialog(page).locator("input[name=name]")).to_be_focused()
    assert sent == []
    fill_in(page, name="Rae Quinn", company="")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(dialog(page)).to_contain_text("Where they work is needed.")
    sync_api.expect(dialog(page).locator("input[name=company]")).to_be_focused()
    assert sent == [] and page.errors == []


def test_the_company_suggests_tracked_names_and_takes_any_text(referrals_page):
    page = referrals_page
    add_button(page).click()
    options = page.evaluate("[...document.querySelectorAll('#addp-companies option')].map(o => o.value)")
    assert {"Initech", "Umbrella"} <= set(options)
    fill_in(page, company="Hooli Labs")  # not tracked: free text is fine
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(page.locator("#toastText")).to_contain_text("Added Rae Quinn at Hooli Labs.")
    sync_api.expect(page.locator("#toastText")).to_contain_text("No job you track is at Hooli Labs yet")
    assert page.errors == []


def test_someone_already_listed_is_flagged_as_you_type_and_not_saved(referrals_page):
    page = referrals_page
    add_button(page).click()
    fill_in(page, name="ana  li", company="Initech Inc")
    warning = dialog(page).locator(".addp-dup")
    sync_api.expect(warning).to_have_text("Already in your connections: Ana Li at Initech.")
    sync_api.expect(dialog(page).get_by_role("button", name="Add person")).to_be_disabled()
    dialog(page).locator("input[name=company]").fill("Umbrella")  # someone else's company: fine
    sync_api.expect(warning).to_be_hidden()
    sync_api.expect(dialog(page).get_by_role("button", name="Add person")).to_be_enabled()
    assert page.errors == []


def test_a_saved_person_is_on_the_card_with_the_ask_pill_the_tag_and_a_toast_with_undo(referrals_page):
    page = referrals_page
    add_button(page).click()
    fill_in(page, name="Rae Quinn", company="Umbrella Corporation", title="Designer", note="met at a meetup")
    dialog(page).get_by_role("radio", name="WhatsApp").click()
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(dialog(page)).to_have_count(0)
    sync_api.expect(page.locator("#toastText")).to_have_text("Added Rae Quinn at Umbrella Corporation.")
    sync_api.expect(page.locator("#toastUndo")).to_have_text("Undo")
    rae = row(page, "Rae Quinn")
    sync_api.expect(rae).to_have_count(1)
    sync_api.expect(rae.locator(".ref-hand")).to_have_text("added by hand")
    sync_api.expect(rae.locator(".ref-pill")).to_have_text("Ask?")
    sync_api.expect(rae.get_by_role("button", name="Rae Quinn: no preference. Change")).to_be_visible()
    sync_api.expect(rae.locator(".pp-notetxt")).to_have_text("reach on WhatsApp; met at a meetup")
    sync_api.expect(rae.locator(".pp-sub")).to_have_text("Designer")
    sync_api.expect(card(page, "Umbrella").locator(".ref-know")).to_have_attribute("aria-label", "2 people you know")
    page.locator("#toastUndo").click()
    sync_api.expect(row(page, "Rae Quinn")).to_have_count(0)
    sync_api.expect(card(page, "Umbrella").locator(".ref-know")).to_have_attribute("aria-label", "1 person you know")
    assert page.errors == []


def test_the_toast_lasts_eight_seconds(referrals_page):
    page = referrals_page
    page.clock.install()
    card(page, "Umbrella").get_by_role("button", name="Add a person at Umbrella").click()
    fill_in(page, company="Umbrella")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(page.locator("#toastUndo")).to_be_visible()
    page.clock.run_for(7000)
    sync_api.expect(page.locator("#toastUndo")).to_be_visible()
    page.clock.run_for(1500)
    sync_api.expect(page.locator("#toast")).to_be_hidden()


def test_a_card_add_button_fills_the_company_in_and_the_person_shows_on_that_card(referrals_page):
    page = referrals_page
    card(page, "Globex").get_by_role("button", name="Add a person at Globex").click()
    sync_api.expect(dialog(page).locator("input[name=company]")).to_have_value("Globex Corporation")
    dialog(page).locator("input[name=name]").fill("Sam Ortiz")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(card(page, "Globex").locator(".ref-p", has_text="Sam Ortiz")).to_have_count(1)
    assert page.errors == []


def test_their_dialog_edits_and_deletes_them_and_a_connection_cannot_be_deleted(referrals_page):
    page = referrals_page
    add_button(page).click()
    fill_in(page, name="Rae Quinn", company="Umbrella", note="met at a meetup")
    dialog(page).get_by_role("radio", name="Email").click()
    dialog(page).locator("input[name=email]").fill("rae@example.com")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(row(page, "Rae Quinn")).to_have_count(1)
    # a connection's dialog has the choice and a note, and no Delete
    row(page, "Dee Park").locator(".pp-namebtn").click()
    sync_api.expect(page.locator(".ref-dialog").get_by_role("heading", name="Dee Park")).to_be_visible()
    sync_api.expect(page.get_by_role("button", name="Delete")).to_have_count(0)
    sync_api.expect(page.get_by_text("Added by hand", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")
    # their own
    row(page, "Rae Quinn").locator(".pp-namebtn").click()
    person = page.locator(".ref-dialog")
    sync_api.expect(person).to_contain_text("rae@example.com")
    sync_api.expect(person).to_contain_text("met at a meetup")
    sync_api.expect(person.locator(".ref-note")).to_have_count(0)  # the note is edited with their details
    person.get_by_role("button", name="Edit").click()
    sync_api.expect(dialog(page).get_by_role("heading", name="Change Rae Quinn")).to_be_visible()
    sync_api.expect(dialog(page).locator("input[name=email]")).to_have_value("rae@example.com")
    sync_api.expect(dialog(page).get_by_role("radio", name="Email")).to_have_attribute("aria-checked", "true")
    dialog(page).locator("input[name=title]").fill("Staff Designer")
    dialog(page).get_by_role("button", name="Save").click()
    sync_api.expect(page.locator("#toastText")).to_have_text("Saved")
    sync_api.expect(person.locator(".ref-fact", has_text="Title")).to_contain_text("Staff Designer")
    # their choice is the same three-way control
    person.get_by_role("radio", name="Ask first").click()
    sync_api.expect(row(page, "Rae Quinn").locator(".ref-pill")).to_have_text("★ Ask first")
    person.get_by_role("button", name="Delete").click()
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(0)
    sync_api.expect(row(page, "Rae Quinn")).to_have_count(0)
    sync_api.expect(page.locator("#toastText")).to_have_text("Removed Rae Quinn.")
    page.locator("#toastUndo").click()  # back, with their details and their choice
    rae = row(page, "Rae Quinn")
    sync_api.expect(rae).to_have_count(1)
    sync_api.expect(rae.locator(".ref-pill")).to_have_text("★ Ask first")
    sync_api.expect(rae.locator(".pp-sub")).to_have_text("Staff Designer")
    assert page.errors == []


def test_with_no_linkedin_data_a_person_can_still_be_added(page, watchlist):
    open_referrals(page, watchlist, connections=None, wait_for_cards=False)
    sync_api.expect(page.locator(".ref-first")).to_be_visible()
    add_button(page).click()
    fill_in(page, name="Rae Quinn", company="Initech")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(page.locator(".card.ref", has_text="Initech").locator(".ref-p", has_text="Rae Quinn")).to_have_count(1)
    sync_api.expect(page.locator(".ref-first")).to_have_count(0)
    assert page.errors == []


def test_the_company_tab_adds_a_person_there(referrals_page):
    page = referrals_page
    page.goto(page.url.split("#")[0] + "#company/Initech")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Add a person at Initech").click()
    sync_api.expect(dialog(page).locator("input[name=company]")).to_have_value("Initech")
    dialog(page).locator("input[name=name]").fill("Rae Quinn")
    dialog(page).get_by_role("button", name="Add person").click()
    sync_api.expect(page.locator(".panel", has_text="People you know").get_by_text("Rae Quinn")).to_be_visible()
    sync_api.expect(page.locator(".panel", has_text="People you know")).to_contain_text("added by hand")
    assert page.errors == []


def test_a_company_with_a_person_added_by_hand_stays_under_hide_no_good_fits_and_the_person_is_counted(quiet_page):
    page = quiet_page
    page.get_by_role("button", name="Hide companies with no good fits").click()
    assert not any(n.startswith("Hooli") for n in company_names(page))  # a fit of 30 is under the minimum: hidden
    add_button(page).click()
    fill_in(page, name="Rae Quinn", company="Hooli")
    dialog(page).get_by_role("button", name="Add person").click()
    kept = card(page, "Hooli")
    sync_api.expect(kept).to_be_visible()  # the person was put there on purpose: the card stays
    sync_api.expect(kept.locator(".ref-know")).to_have_attribute("aria-label", "2 people you know")  # Hooli's connection and Rae
    sync_api.expect(kept.locator(".ref-p", has_text="Rae Quinn")).to_have_count(1)
    assert any(n.startswith("Stark") for n in company_names(page)) is False  # others with no good fit stay hidden
    assert page.errors == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_dialog_and_the_tag_read_in_both_themes(referrals_page, theme):
    page = referrals_page
    page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
    add_button(page).click()
    fill_in(page, name="Rae Quinn", company="Umbrella")
    colors = page.evaluate("""() => {
      const bg = e => getComputedStyle(e).backgroundColor, input = document.querySelector('.person-dialog input[name=name]');
      return { box: bg(document.querySelector('.person-dialog')), input: bg(input), text: getComputedStyle(input).color };
    }""")
    assert colors["input"] != colors["text"] and colors["box"] != colors["text"]
    dialog(page).get_by_role("button", name="Add person").click()
    tag = row(page, "Rae Quinn").locator(".ref-hand")
    sync_api.expect(tag).to_be_visible()
    assert tag.bounding_box()["width"] > 40
    assert page.errors == []
