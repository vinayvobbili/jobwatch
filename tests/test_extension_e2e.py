"""End to end: the Chrome extension, loaded into Chromium, against demo forms that imitate Greenhouse, Lever and
Ashby (and a generic one) and a fake jobwatch that implements chrome-extension/API.md.

It checks the fills, the resume, the review panel, the draft, that nothing is submitted by the extension, and that an
application the person submits is recorded once the page shows it went through.

Skipped unless Playwright and its Chromium are installed:

    pip install playwright && playwright install chromium
"""

# ruff: noqa: E501  (long selectors and expected form text)
from __future__ import annotations

import contextlib
import struct
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

TOOLS = Path(__file__).resolve().parent.parent / "chrome-extension" / "tools"
sys.path.insert(0, str(TOOLS))
import harness  # noqa: E402
import store_assets  # noqa: E402


@pytest.fixture(scope="module")
def pw():
    with sync_api.sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="module")
def stack(pw):
    with contextlib.ExitStack() as scope:
        try:
            demo = scope.enter_context(harness.demo_stack(pw))
        except harness.BrowserUnavailable as exc:
            pytest.skip(str(exc))
        yield demo


@pytest.fixture
def ext(stack):
    page = stack.extension_page()
    stack.server.submitted.clear()
    stack.server.drafts.clear()
    yield page
    page.close()


def open_form(stack, ext, url: str):
    """The form, in a tab."""
    page = stack.context.new_page()
    page.goto(url)
    return page


@pytest.fixture
def panels(stack):
    """Side panel pages opened by a test; closed afterwards."""
    opened = []
    yield opened
    for p in opened:
        p.close()


def start_panel(stack, panels, url: str):
    """The side panel for the form's tab, after pressing "Fill this application". The panel is the page."""
    panel = harness.side_panel(stack, url)
    panels.append(panel)
    panel.click("#scan")
    panel.wait_for_selector(".row", timeout=20000)
    return panel


def row(panel, text: str):
    return panel.locator(".row").filter(has_text=text).first


def badge(panel, text: str) -> str:
    return row(panel, text).locator(".badge").inner_text()


def ticked(panel, text: str) -> bool:
    return row(panel, text).locator("input[type=checkbox]").is_checked()


def fill_selected(panel):
    panel.evaluate("() => document.getElementById('toast')?.remove()")
    panel.locator("#fill").click()
    panel.wait_for_selector("#toast", timeout=20000)


def state(page) -> dict:
    return page.evaluate("window.__state")


def test_greenhouse_fills_records_and_never_submits(stack, ext, panels):
    url = stack.url("job-boards.greenhouse.io", "/initech/jobs/4001")
    page = open_form(stack, ext, url)
    page.fill("#phone", "+1 555 0199")  # another tool (Chrome autofill, Simplify) got there first
    panel = start_panel(stack, panels, url)

    # the first line says how this works with the other tools
    assert "Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest" in panel.inner_text("body")

    assert badge(panel, "First Name") == "Your details" and ticked(panel, "First Name")
    assert ticked(panel, "Will you now or in the future require")
    assert "Already filled" in row(panel, "Phone").inner_text() and not ticked(panel, "Phone")
    # a past answer to a similar question is offered, with the question it came from, and not ticked
    why = row(panel, "Why do you want to work at Initech")
    assert why.locator(".badge").inner_text() == "Past answer" and not ticked(panel, "Why do you want to work at Initech")
    assert 'From your answer to "Why do you want to work at Globex?"' in why.inner_text()
    assert "Globex, SRE, 2026-09-14" in why.inner_text()
    assert badge(panel, "How did you hear") == "Not found" and not ticked(panel, "How did you hear")
    assert badge(panel, "Resume/CV") == "Resume" and ticked(panel, "Resume/CV")
    assert not ticked(panel, "Preferred pronouns")
    assert badge(panel, "name you'd prefer") == "Your details" and ticked(panel, "name you'd prefer")
    # react-select's hidden required input is not a second question
    assert panel.locator(".row").filter(has_text="legally authorized").count() == 1
    assert panel.locator(".row").filter(has_text="require visa sponsorship").count() == 1
    # a select shows the option it will pick
    assert "Will pick: Decline To Self Identify" in row(panel, "Gender").inner_text()
    assert "Will pick: I don't wish to answer" in row(panel, "Veteran Status").inner_text()

    fill_selected(panel)

    # controlled inputs took the value through real events, not just the DOM property
    assert page.input_value("#first_name") == "Jordan" and state(page)["first_name"] == "Jordan"
    assert state(page)["email"] == "jordan@example.com" and state(page)["last_name"] == "Rivera"
    assert page.input_value("#question_1").startswith("https://www.linkedin.com/")
    assert page.input_value("#question_4") == "2 weeks" and page.input_value("#question_7") == "Jo"
    assert page.input_value("#phone") == "+1 555 0199"  # left alone
    assert page.input_value("#question_5") == ""  # unticked: untouched
    assert page.input_value("#question_6") == "" and page.input_value("#question_3") == ""
    # react-select style dropdowns
    assert page.locator("#auth").locator("xpath=ancestor::div[contains(@class,'select__control')]//div[contains(@class,'single-value')]").inner_text() == "Yes"
    assert state(page)["sponsor"] == "No"
    # selects, with EEO "decline"
    assert page.input_value("#gender") == "Decline To Self Identify"
    assert page.input_value("#hispanic") == "Decline To Self Identify"
    assert page.input_value("#race") == "Decline To Self Identify"
    assert page.input_value("#veteran") == "I don't wish to answer"
    assert page.input_value("#disability") == "I do not want to answer"
    # the resume, onto the file input and the drop zone
    assert state(page)["resume"] == "resume.pdf" and state(page)["dropped"] is True
    assert page.evaluate("document.querySelector('#resume').files[0].size") > 10
    assert page.evaluate("window.__submits") == 0 and stack.server.submitted == []

    # a draft for a question with no answer: never ticked on its own
    r = row(panel, "How did you hear")
    r.get_by_text("Draft with jobwatch").click()
    panel.wait_for_selector(".badge.draft")
    assert badge(panel, "How did you hear") == "Draft" and not ticked(panel, "How did you hear")
    assert stack.server.drafts[0]["question"] == "How did you hear about this job?"
    assert stack.server.drafts[0]["url"] == url

    # the person ticks the past answer, edits nothing, and fills it too
    row(panel, "Why do you want to work at Initech").locator("input[type=checkbox]").check()
    fill_selected(panel)
    assert page.input_value("#question_5") == "I like small teams that own what they run."

    # submitting with a required field empty shows errors and records nothing
    page.fill("#question_4", "")
    page.click("button[type=submit]")
    page.wait_for_selector(".field-error")
    time.sleep(2.5)
    assert stack.server.submitted == []
    # filled in properly, the person's submit goes through and is recorded once, with the page's company and title
    page.fill("#question_4", "Two weeks.")
    page.click("button[type=submit]")
    harness.wait_until(lambda: stack.server.submitted, 15, "the application to be recorded")
    time.sleep(1.5)
    assert len(stack.server.submitted) == 1
    sent = stack.server.submitted[0]
    assert sent["url"] == url and sent["company"] == "Initech" and sent["title"] == "Platform Engineer"
    assert sent["resume"] == "resume.pdf"
    asked = {a["question"]: a["answer"] for a in sent["answers"]}
    assert asked["What is your notice period?"] == "Two weeks."
    assert asked["Why do you want to work at Initech?"] == "I like small teams that own what they run."
    assert asked["Are you legally authorized to work in the United States?"] == "Yes"
    assert not any("Email" in q or "Gender" in q or "Name" in q for q in asked)  # who you are isn't an answer
    # the result of recording reaches the side panel
    panel.wait_for_function("() => document.getElementById('toast')?.textContent.includes('Recorded in jobwatch')")
    page.close()


def test_greenhouse_embedded_in_a_company_page(stack, ext, panels):
    embed = stack.url("boards.greenhouse.io", "/embed/job_app?for=initech&token=4001")
    url = stack.url("careers.initech.example", f"/careers?src={embed}")
    page = open_form(stack, ext, url)
    page.wait_for_selector("iframe")
    page.frame_locator("iframe").locator("#first_name").wait_for()
    panel = start_panel(stack, panels, url)
    assert "Your details" in badge(panel, "First Name")
    fill_selected(panel)
    form = page.frame_locator("iframe")
    assert form.locator("#first_name").input_value() == "Jordan"
    assert form.locator("#gender").input_value() == "Decline To Self Identify"
    assert form.locator("#veteran").input_value() == "I don't wish to answer"
    frame = next(f for f in page.frames if f.url.startswith("http://boards.greenhouse.io"))
    assert frame.evaluate("window.__state.resume") == "resume.pdf" and frame.evaluate("window.__submits") == 0
    page.close()


def test_lever_fills_and_records_after_the_thank_you_page(stack, ext, panels):
    url = stack.url("jobs.lever.co", "/initech/6f1b2c/apply")
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert badge(panel, "Full name") == "Your details" and ticked(panel, "Full name")
    assert badge(panel, "Current company") == "Not found"
    # a label's hidden helper text (a "no results" note, an EEO definition) is not part of the question
    assert row(panel, "Current location").locator(".q").inner_text().strip() == "Current location"
    assert "Will pick: Decline to self-identify" in row(panel, "Race").inner_text()
    # pay is offered but never ticked for you: the person ticks it on purpose
    assert badge(panel, "salary expectations") == "Your details" and not ticked(panel, "salary expectations")
    row(panel, "salary expectations").locator("input[type=checkbox]").check()
    fill_selected(panel)
    assert page.input_value("input[name=name]") == "Jordan Rivera"
    assert page.input_value("input[name=email]") == "jordan@example.com"
    assert page.input_value("input[name=location]") == "Boulder, CO"
    assert page.input_value("input[name='urls[GitHub]']").startswith("https://github.com/")
    assert page.input_value("input[name='cards[3]']") == "180K-200K"
    assert page.is_checked("input[name='cards[1]'][value=Yes]") and page.is_checked("input[name='cards[2]'][value=Yes]")
    assert page.input_value("select[name='eeo[gender]']") == "Decline to self-identify"
    assert page.input_value("select[name='eeo[veteran]']") == "I don't wish to answer"
    assert page.input_value("select[name='eeo[race]']") == "Decline to self-identify"
    assert state(page)["resume"] == "resume.pdf"
    assert page.evaluate("window.__submits") == 0 and stack.server.submitted == []

    page.click("button[type=submit]")  # the person's click; the page then goes to its thank-you address
    harness.wait_until(lambda: stack.server.submitted, 15, "the application to be recorded")
    sent = stack.server.submitted[0]
    assert sent["url"].startswith(url.rsplit("/", 1)[0]) and sent["company"] == "Initech"
    assert sent["title"] == "Platform Engineer"
    assert {"question": "What are your salary expectations?", "answer": "180K-200K"} in sent["answers"]
    # the page moved on to the thank-you address: the rows are for a form that's gone, so the panel asks for a rescan
    panel.wait_for_selector("#scan")
    assert panel.locator(".row").count() == 0 and "changed" in panel.locator(".empty .msg").inner_text()
    panel.wait_for_function("() => document.getElementById('toast')?.textContent.includes('Recorded in jobwatch')")
    page.close()


def test_ashby_fills_buttons_dropdowns_and_records(stack, ext, panels):
    url = stack.url("jobs.ashbyhq.com", "/initech/4f1c9a/application")
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert "Will pick: Prefer not to say" in row(panel, "Gender").inner_text()
    fill_selected(panel)
    assert page.input_value("#_systemfield_name") == "Jordan Rivera" and state(page)["_systemfield_name"] == "Jordan Rivera"
    assert state(page)["auth"] == "Yes" and state(page)["sponsor"] == "No"
    assert page.locator("._yesno_[data-name=auth] button._active_").inner_text() == "Yes"
    assert state(page)["loc"] == "Boulder, CO"
    assert page.input_value("#gender") == "Prefer not to say"
    assert page.input_value("#notice") == "2 weeks"
    assert state(page)["resume"] == "resume.pdf" and page.evaluate("window.__submits") == 0

    page.click("button[type=submit]")
    harness.wait_until(lambda: stack.server.submitted, 15, "the application to be recorded")
    sent = stack.server.submitted[0]
    assert sent["company"] == "Initech" and sent["title"] == "Platform Engineer"
    assert {"question": "Are you legally authorized to work in the United States?", "answer": "Yes"} in sent["answers"]
    page.close()


def test_a_generic_form_a_job_jobwatch_does_not_know(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert "Already filled" in row(panel, "Your city").inner_text()
    assert badge(panel, "Describe a time") == "Past answer" and ticked(panel, "Describe a time")
    fill_selected(panel)
    assert page.input_value("#fn") == "Jordan" and page.input_value("input[name=ln]") == "Rivera"  # label for, wrapping label
    assert page.input_value("input[name=mail]") == "jordan@example.com"  # aria-label
    assert page.input_value("input[name=ph]") == "+1 555 0100"  # aria-labelledby
    assert page.input_value("input[name=li]") == ""  # a guess from the placeholder alone: offered, not ticked
    assert badge(panel, "LinkedIn profile URL") == "Your details" and not ticked(panel, "LinkedIn profile URL")
    assert page.input_value("input[name=c1]") == "Austin"  # already had a value
    assert page.input_value("#country") == "United States of America" and page.input_value("#st") == "Colorado"
    assert page.is_checked("input[name=sp][value='0']") and page.is_checked("input[name=rl][value='1']")  # fieldset legends
    assert page.input_value("#np") == "2 weeks" and page.input_value("#sal") == ""  # pay: offered, not ticked
    assert page.input_value("#exp").startswith("A bad deploy took checkout down")
    assert not page.is_checked("input[name=consent]") and not page.is_checked("input[name=area][value=a]")
    assert page.evaluate("window.__submits") == 0 and stack.server.submitted == []
    page.close()


def test_the_panel_says_when_jobwatch_is_missing(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    try:
        harness.pair(stack, stack.api_url, "")
        panel = harness.side_panel(stack, url)
        panels.append(panel)
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('This needs jobwatch')")
        assert panel.locator("#scan").count() == 0  # nothing to fill from, so no button to press
        # the worker still refuses to scan without a token
        tab = harness.tab_id_for(ext, url)
        reply = ext.evaluate("(tabId) => chrome.runtime.sendMessage({type: 'analyze', tabId})", tab)
        assert not reply["ok"] and "Pair the extension with jobwatch" in reply["error"]
        status = ext.evaluate("chrome.runtime.sendMessage({type: 'status'})")
        assert status["paired"] is False

        harness.pair(stack, stack.api_url, "wrong")  # the panel notices the settings change
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('did not accept the token')")
        assert panel.locator("#scan").count() == 0

        harness.pair(stack, stack.api_url, harness.TOKEN)
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('Paired with jobwatch')")
        panel.wait_for_selector("#scan")
    finally:
        harness.pair(stack, stack.api_url, harness.TOKEN)
        page.close()


def test_nothing_is_put_in_the_page_and_a_new_page_asks_for_a_rescan(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert page.locator("#jobwatch-panel").count() == 0  # the review lives in the side panel, not the page
    page.goto(stack.url("jobs.lever.co", "/initech/6f1b2c/apply"))
    panel.wait_for_selector("#scan")
    assert panel.locator(".row").count() == 0 and "changed" in panel.locator(".empty .msg").inner_text()
    panel.click("#scan")  # and scanning again reads the new page
    panel.wait_for_selector(".row", timeout=20000)
    assert badge(panel, "Full name") == "Your details"
    assert page.evaluate("window.__submits") == 0 and stack.server.submitted == []
    page.close()


def test_a_step_that_replaces_the_form_in_place_is_scanned_again(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/steps.html"
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert row(panel, "First name").count() == 1 and row(panel, "notice period").count() == 0
    page.click("#next")  # Save and Continue: the next step replaces the first, the address stays
    panel.wait_for_selector(".row:has-text('notice period')", timeout=20000)  # no press of the button
    assert row(panel, "First name").count() == 0
    assert page.url == url
    fill_selected(panel)  # and the rows fill this step, not "the page changed"
    assert page.input_value("#np") == "2 weeks"
    assert stack.server.submitted == []
    page.close()


def test_the_panel_follows_the_active_tab(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    panel = stack.extension_page("sidepanel.html")  # not pinned: it reads whichever tab is active
    panels.append(panel)
    page = open_form(stack, ext, url)
    page.bring_to_front()  # the form's tab becomes the active one; the panel follows without being told
    panel.click("#scan")  # it scans the tab it followed to, not a tab it was told about
    panel.wait_for_selector(".row", timeout=20000)
    assert "Already filled" in row(panel, "Your city").inner_text()
    page.close()


def test_store_assets_have_the_sizes_the_web_store_requires(tmp_path, pw):
    try:
        written = {p.name: p for p in store_assets.build(tmp_path, playwright=pw)}
    except harness.BrowserUnavailable as exc:
        pytest.skip(str(exc))
    shots = {f"screenshot-{n}.png" for n in ("1-review", "2-filled", "3-draft", "4-pairing")}
    assert set(written) == shots | {"promo-small.png", "promo-marquee.png", "icon128.png"}
    sizes = {"promo-small.png": store_assets.PROMO, "promo-marquee.png": store_assets.MARQUEE, "icon128.png": (128, 128)}
    for name, path in written.items():
        png = path.read_bytes()
        assert struct.unpack(">II", png[16:24]) == sizes.get(name, store_assets.SCREEN), name
