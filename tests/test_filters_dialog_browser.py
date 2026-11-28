# ruff: noqa: F811, E501  (a test's `page` argument is the fixture imported from test_browser)
"""Today's top in a real browser (headless Chromium through Playwright, skipped where it isn't installed): by default one
slim line, the Filters button with how many filters are in force and what they hide (each kind a peek at those jobs); the
Filters dialog lists the filters in plain words, edits a part in place and saves it like Settings does; "Show the filter
summary on Today" brings the long strip back (remembered in the browser). Filter patterns are read as words ("without
product", never raw regex) and a pattern that is more than words stays whole in a code chip. The data is made up."""

import pytest
import yaml

from .test_browser import browser, jobs, page, sync_api, watchlist  # noqa: F401  (fixtures)

expect = sync_api.expect

# (pattern, the words it looks for, the words it must not have): what a reader should see instead of the regex
WORDS = [
    (r"\b(intern|new grad)\b", ["intern", "new grad"], []),
    (r"^(?!.*(?:product|program|project)).*\b(?:engineer|architect)\b", ["engineer", "architect"], ["product", "program", "project"]),
    (r"(?!.*(engineer|engineering|technolog\w*|ai)).*(director|manager)", ["director", "manager"], ["engineer", "engineering", "technolog…", "ai"]),
    (r"senior\s+(engineer|developer)", ["senior engineer", "senior developer"], []),
    (r"engineers?", ["engineer"], []),
    (r"c\+\+", ["c++"], []),
    (r"full[ -]stack", ["full stack"], []),
    (r"(?i)data scientist", ["data scientist"], []),
    (r"U\.?S\.? citizen", ["US citizen"], []),
    (r"staff.*engineer", ["staff … engineer"], []),
]
# patterns that are more than words: kept whole
ODD = [r"\d{2,4}\+? years", r"(?<=senior )engineer", r"(red", r"[A-Z]{3}", r"engineer(ing)?{2}", r"\b(must|need to) be an? U\.?S\.? citizen\b(?![^.\n]{0,40}\bgreen card)"]


@pytest.mark.parametrize("pattern,words,without", WORDS)
def test_a_pattern_is_read_as_words(page, pattern, words, without):
    got = page.evaluate("p => plainPattern(p)", pattern)
    assert got == {"words": words, "without": without, "odd": False}


@pytest.mark.parametrize("pattern", ODD)
def test_a_pattern_that_is_more_than_words_is_marked_odd(page, pattern):
    assert page.evaluate("p => plainPattern(p)", pattern)["odd"] is True
    assert page.evaluate("p => readableGroups([p])", pattern) == {"groups": [], "odd": [pattern]}


def test_the_summary_line_names_words_and_what_they_leave_out_never_the_regex(page):
    look = r"^(?!.*(?:product|program|project)).*\b(?:engineer|architect|developer|analyst)\b"
    assert page.evaluate("p => readable([p])", look) == "engineer, architect, developer +1 more, without “product”, “program”, “project”"
    assert page.evaluate("p => readable([p], Infinity)", look) == "engineer, architect, developer, analyst, without “product”, “program”, “project”"
    assert page.evaluate("p => readable([p])", r"\d+ years") == "1 custom pattern"
    assert page.evaluate("l => readable(l)", [r"\b(intern|new grad)\b", "contract"]) == "intern, new grad, contract"
    grouped = page.evaluate("l => readableGroups(l)", [r"(?!.*senior)\b(a|b)\b", r"(?!.*senior)c", "d", "[xyz]"])
    assert grouped == {"groups": [{"words": ["a", "b", "c"], "without": ["senior"]}, {"words": ["d"], "without": []}], "odd": ["[xyz]"]}


def test_the_filters_in_force_are_counted(page):
    assert page.evaluate("activeFilters({})") == 0
    assert page.evaluate("activeFilters({titles: ['a'], exclude_titles: ['b'], locations: ['remote'], min_salary: 1, max_age_days: 3, min_fit: 70})") == 6
    assert page.evaluate("activeFilters({titles: [], require_salary: true})") == 1


def slim(page):
    return page.locator("main .fbar.slim")


def dialog(page):
    return page.locator(".filters-dialog")


def test_today_opens_on_one_slim_line_with_the_filters_button_and_what_is_hidden(jobs, page):
    bar = slim(page)
    expect(bar).to_have_count(1)
    expect(page.locator("main .fpart")).to_have_count(0)  # no long summary strip
    button = bar.get_by_role("button", name="Filters, 5 in force")  # titles, not, not in text, places, posted
    expect(button).to_be_visible()
    expect(button).to_have_attribute("title", "What Today leaves out and why")
    expect(button.locator(".fcount")).to_have_text("5")
    expect(bar.locator(".fline")).to_contain_text("hidden by your filters", timeout=10000)
    assert bar.locator(".hchip").count() >= 1
    assert bar.bounding_box()["height"] < 60  # one line, not a block
    assert page.errors == []


def test_the_dialog_says_the_filters_in_plain_words_and_esc_closes_it(jobs, page):
    button = slim(page).get_by_role("button", name="Filters, 5 in force")
    button.click()
    expect(dialog(page)).to_be_visible()
    expect(dialog(page).get_by_role("heading", name="Filters", exact=True)).to_be_visible()
    box = dialog(page).bounding_box()
    assert box["width"] > 700  # the large dialog, not a popover
    titles = dialog(page).locator("[data-part=titles]")
    expect(titles.locator(".chip.pw", has_text="engineer")).to_have_count(1)
    expect(titles.locator("code.pcode").first).to_contain_text("green card")  # a pattern that is more than words, whole
    expect(dialog(page).locator("[data-part=places]")).to_contain_text("Boulder, CO")
    expect(dialog(page).locator("[data-part=age]")).to_contain_text("within 30 days")
    expect(dialog(page).get_by_role("link", name="Same settings as Settings → Your search")).to_have_attribute("href", "#settings/search")
    for _ in range(40):  # Tab never leaves it
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('.filters-dialog')")
    page.keyboard.press("Escape")
    expect(dialog(page)).to_have_count(0)
    expect(button).to_be_focused()
    page.mouse.click(0, 0)  # a click outside closes it too
    slim(page).get_by_role("button", name="Filters, 5 in force").click()
    page.mouse.click(2, 2)
    expect(dialog(page)).to_have_count(0)
    assert page.errors == []


def test_a_part_is_edited_in_place_and_saved_like_settings_then_undone(jobs, page, watchlist):
    slim(page).get_by_role("button", name="Filters, 5 in force").click()
    card = dialog(page).locator("[data-part=titles]")
    card.get_by_role("button", name="Edit titles").click()
    boxes = card.locator("textarea")
    expect(boxes.first).to_be_focused()
    assert boxes.first.input_value().split("\n") == ["engineer", "developer"]
    boxes.first.fill("engineer\nanalyst")
    boxes.nth(1).fill(r"^(?!.*staff).*\b(contract|temp)\b")  # a lookahead is fine to write
    card.get_by_role("button", name="Save").click()
    expect(card.locator(".chip.pw", has_text="analyst")).to_have_count(1, timeout=10000)
    expect(card.locator(".chip.pw.no", has_text="staff")).to_have_count(1)
    expect(card.locator("textarea")).to_have_count(0)
    saved = yaml.safe_load(watchlist.read_text())["filters"]
    assert saved["titles"] == ["engineer", "analyst"] and saved["exclude_titles"] == [r"^(?!.*staff).*\b(contract|temp)\b"]
    assert saved["locations"] == ["remote", "Boulder, CO"] and saved["max_age_days"] == 30  # the other parts are kept
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Undo").click()
    expect(page.get_by_text("Filters put back.")).to_be_visible(timeout=10000)
    assert yaml.safe_load(watchlist.read_text())["filters"]["titles"] == ["engineer", "developer"]
    assert page.errors == []


def test_a_bad_pattern_is_refused_in_the_dialog_in_plain_words(jobs, page, watchlist):
    slim(page).get_by_role("button", name="Filters, 5 in force").click()
    card = dialog(page).locator("[data-part=titles]")
    card.get_by_role("button", name="Edit titles").click()
    card.locator("textarea").first.fill("(engineer")
    card.get_by_role("button", name="Save").click()
    expect(card.locator(".msg.error")).to_contain_text("isn't a valid pattern", timeout=10000)
    assert yaml.safe_load(watchlist.read_text())["filters"]["titles"] == ["engineer", "developer"]
    expect(card.get_by_role("button", name="Save")).to_be_enabled()


def test_a_hidden_chip_peeks_and_its_change_this_filter_opens_that_part_in_edit(jobs, page):
    chip = slim(page).locator(".hchip", has_text="excluded")  # the jobs the "Not" titles leave out
    expect(chip).to_have_count(1, timeout=10000)
    chip.click()
    page.get_by_role("button", name="Change this filter").click()
    expect(dialog(page).locator("[data-part=titles] textarea").nth(1)).to_be_focused()  # the "Leave out titles with" box
    assert page.errors == []


def test_the_summary_strip_comes_back_with_the_setting_and_stays_remembered(jobs, page):
    slim(page).get_by_role("button", name="Filters, 5 in force").click()
    option = dialog(page).get_by_label("Show the filter summary on Today")
    expect(option).not_to_be_checked()  # off by default
    option.check()
    page.keyboard.press("Escape")
    strip = page.locator("main .fbar:not(.slim)")
    expect(strip).to_have_count(1)
    expect(strip.locator(".fpart")).to_have_count(7)  # titles, not, not in text, places, pay, posted, fit
    text = strip.inner_text()
    assert "Titles:" in text and "Places:" in text
    assert "(?!" not in text and "\\b" not in text  # words, never regex
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator("main .fbar:not(.slim)")).to_have_count(1)
    page.locator("main .fbar .fpart", has_text="Places").click()  # a part opens the dialog on that part, in edit
    expect(dialog(page).locator("[data-part=places] textarea").first).to_be_focused()
    dialog(page).get_by_label("Show the filter summary on Today").uncheck()
    page.keyboard.press("Escape")
    expect(slim(page)).to_have_count(1)
    assert page.errors == []


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1500, 900), (420, 800)])
def test_the_dialog_fits_the_window_in_light_and_dark(jobs, page, scheme, size):
    page.emulate_media(color_scheme=scheme)
    page.set_viewport_size({"width": size[0], "height": size[1]})
    slim(page).get_by_role("button", name="Filters, 5 in force").click()
    box = dialog(page).bounding_box()
    assert 0 <= box["x"] and box["x"] + box["width"] <= size[0] + 1
    assert box["y"] + box["height"] <= size[1] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.errors == []
