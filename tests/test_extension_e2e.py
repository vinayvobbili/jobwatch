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
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

TOOLS = Path(__file__).resolve().parent.parent / "chrome-extension" / "tools"
sys.path.insert(0, str(TOOLS))
import harness  # noqa: E402


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
    """The form in a tab, with the panel opened as the toolbar popup's button does."""
    page = stack.context.new_page()
    page.goto(url)
    return page


def start_panel(ext, page, url: str):
    reply = harness.open_panel(ext, harness.tab_id_for(ext, url))
    assert reply["ok"], reply
    page.wait_for_selector("#jobwatch-panel .row", timeout=20000)
    return page.locator("#jobwatch-panel .panel")


def row(panel, text: str):
    return panel.locator(".row").filter(has_text=text).first


def badge(panel, text: str) -> str:
    return row(panel, text).locator(".badge").inner_text()


def ticked(panel, text: str) -> bool:
    return row(panel, text).locator("input[type=checkbox]").is_checked()


def fill_selected(page, panel):
    panel.locator(".go").click()
    page.wait_for_function(
        "() => document.querySelector('#jobwatch-panel').shadowRoot.querySelector('.toast')", timeout=20000)


def state(page) -> dict:
    return page.evaluate("window.__state")


def test_greenhouse_fills_records_and_never_submits(stack, ext):
    url = stack.url("job-boards.greenhouse.io", "/initech/jobs/4001")
    page = open_form(stack, ext, url)
    page.fill("#phone", "+1 555 0199")  # another tool (Chrome autofill, Simplify) got there first
    panel = start_panel(ext, page, url)

    # the first line says how this works with the other tools
    assert "Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest" in panel.inner_text()

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

    fill_selected(page, panel)

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
    page.wait_for_selector("#jobwatch-panel .badge.draft")
    assert badge(panel, "How did you hear") == "Draft" and not ticked(panel, "How did you hear")
    assert stack.server.drafts[0]["question"] == "How did you hear about this job?"
    assert stack.server.drafts[0]["url"] == url

    # the person ticks the past answer, edits nothing, and fills it too
    row(panel, "Why do you want to work at Initech").locator("input[type=checkbox]").check()
    fill_selected(page, panel)
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
    page.wait_for_function(
        "() => document.querySelector('#jobwatch-panel').shadowRoot.querySelector('.toast')"
        " && document.querySelector('#jobwatch-panel').shadowRoot.querySelector('.toast').textContent.includes('Recorded')")
    page.close()


def test_greenhouse_embedded_in_a_company_page(stack, ext):
    embed = stack.url("boards.greenhouse.io", "/embed/job_app?for=initech&token=4001")
    url = stack.url("careers.initech.example", f"/careers?src={embed}")
    page = open_form(stack, ext, url)
    page.wait_for_selector("iframe")
    page.frame_locator("iframe").locator("#first_name").wait_for()
    panel = start_panel(ext, page, url)
    assert "Your details" in badge(panel, "First Name")
    fill_selected(page, panel)
    form = page.frame_locator("iframe")
    assert form.locator("#first_name").input_value() == "Jordan"
    assert form.locator("#gender").input_value() == "Decline To Self Identify"
    assert form.locator("#veteran").input_value() == "I don't wish to answer"
    frame = next(f for f in page.frames if f.url.startswith("http://boards.greenhouse.io"))
    assert frame.evaluate("window.__state.resume") == "resume.pdf" and frame.evaluate("window.__submits") == 0
    page.close()


def test_lever_fills_and_records_after_the_thank_you_page(stack, ext):
    url = stack.url("jobs.lever.co", "/initech/6f1b2c/apply")
    page = open_form(stack, ext, url)
    panel = start_panel(ext, page, url)
    assert badge(panel, "Full name") == "Your details" and ticked(panel, "Full name")
    assert badge(panel, "Current company") == "Not found"
    # a label's hidden helper text (a "no results" note, an EEO definition) is not part of the question
    assert row(panel, "Current location").locator(".q").inner_text().strip() == "Current location"
    assert "Will pick: Decline to self-identify" in row(panel, "Race").inner_text()
    # pay is offered but never ticked for you: the person ticks it on purpose
    assert badge(panel, "salary expectations") == "Your details" and not ticked(panel, "salary expectations")
    row(panel, "salary expectations").locator("input[type=checkbox]").check()
    fill_selected(page, panel)
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
    page.close()


def test_ashby_fills_buttons_dropdowns_and_records(stack, ext):
    url = stack.url("jobs.ashbyhq.com", "/initech/4f1c9a/application")
    page = open_form(stack, ext, url)
    panel = start_panel(ext, page, url)
    assert "Will pick: Prefer not to say" in row(panel, "Gender").inner_text()
    fill_selected(page, panel)
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


def test_a_generic_form_a_job_jobwatch_does_not_know(stack, ext):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    panel = start_panel(ext, page, url)
    assert "Already filled" in row(panel, "Your city").inner_text()
    assert badge(panel, "Describe a time") == "Past answer" and ticked(panel, "Describe a time")
    fill_selected(page, panel)
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


def test_the_panel_says_when_jobwatch_is_missing(stack, ext):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    try:
        harness.pair(stack, stack.api_url, "")
        reply = harness.open_panel(ext, harness.tab_id_for(ext, url))
        assert reply["ok"]
        page.wait_for_selector("#jobwatch-panel .empty")
        assert "Pair the extension with jobwatch" in page.locator("#jobwatch-panel .empty").inner_text()
        status = ext.evaluate("chrome.runtime.sendMessage({type: 'status'})")
        assert status["paired"] is False

        harness.pair(stack, stack.api_url, "wrong")
        page.locator("#jobwatch-panel .ghost").click()
        harness.open_panel(ext, harness.tab_id_for(ext, url))
        page.wait_for_function("() => document.querySelector('#jobwatch-panel').shadowRoot.querySelector('.empty')"
                               ".textContent.includes('did not accept the token')")
    finally:
        harness.pair(stack, stack.api_url, harness.TOKEN)
        page.close()
