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
import panel_states  # noqa: E402
import store_assets  # noqa: E402
from fake_server import State  # noqa: E402

FEATURES = State().features  # what the fake jobwatch's /ext/ping says, put back after a test changes it


def test_the_fake_jobwatch_offers_what_the_real_one_does():
    from jobwatch.web import EXT_FEATURES

    assert set(FEATURES) == set(EXT_FEATURES)  # else a panel test sees fewer tiles than the real panel has


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
    stack.server.answers.clear()
    stack.server.drafts.clear()
    for calls in (stack.server.contexts, stack.server.ats_calls, stack.server.covers, stack.server.tailors):
        calls.clear()
    stack.server.tailored = False
    stack.server.ats_answer, stack.server.cover_answer, stack.server.cover_delay = {}, {}, 0.0
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
    # ...but the answers as they stood are kept at once (the person's own edits, not the scan's), and that doesn't
    # record an application
    harness.wait_until(lambda: stack.server.answers, 15, "the answers to be kept at Submit")
    first = {a["question"]: a["answer"] for a in stack.server.answers[0]["answers"]}
    assert first["Why do you want to work at Initech?"] == "I like small teams that own what they run."
    assert "What is your notice period?" not in first  # the person emptied it
    panel.wait_for_function(
        "() => document.getElementById('toast')?.textContent.includes('Answers saved to your jobwatch application')")
    # filled in properly, the person's submit goes through and is recorded once, with the page's company and title
    page.fill("#question_4", "Two weeks.")
    page.click("button[type=submit]")
    harness.wait_until(lambda: stack.server.submitted, 15, "the application to be recorded")
    time.sleep(1.5)
    assert len(stack.server.submitted) == 1
    assert len(stack.server.answers) == 2  # a second snapshot, which jobwatch keeps in the same package
    assert {a["question"]: a["answer"] for a in stack.server.answers[1]["answers"]}[
        "What is your notice period?"] == "Two weeks."
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
    assert page.input_value("input[name='cards[3]']") == "180K-190K"
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
    assert {"question": "What are your salary expectations?", "answer": "180K-190K"} in sent["answers"]
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


def test_a_question_in_its_own_box_above_the_field_is_read(stack, ext, panels):
    """Rippling-style custom questions: the question is a paragraph in a sibling box a few levels above the field."""
    url = f"http://127.0.0.1:{stack.site_port}/nested.html"
    page = open_form(stack, ext, url)
    panel = start_panel(stack, panels, url)
    assert row(panel, "Which agentic tools have you used hands-on").count() == 1
    assert row(panel, "how hooks, skills, plugins, or MCP servers work").count() == 1  # a long question too
    assert panel.locator(".row").filter(has_text="field 8").count() == 0  # never named after its id
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
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('paired ')")
        panel.wait_for_selector("#scan")
        assert panel.locator("#posting").count() == 1
    finally:
        harness.pair(stack, stack.api_url, harness.TOKEN)
        page.close()


def test_an_older_jobwatch_without_the_posting_call_gets_no_posting_button(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    stack.server.features = []  # what jobwatch 0.8.0's /ext/ping says: no features
    try:
        harness.pair(stack, stack.api_url, "")
        panel = harness.side_panel(stack, url)
        panels.append(panel)
        harness.pair(stack, stack.api_url, harness.TOKEN)
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('paired ')")
        panel.wait_for_selector("#scan")  # filling still works
        assert panel.locator("#posting").count() == 0  # its call would fail on that jobwatch
    finally:
        stack.server.features = list(FEATURES)
        harness.pair(stack, stack.api_url, harness.TOKEN)
        page.close()


# --- Draft reply, on a demo LinkedIn conversation (demo/linkedin-messages.html) ---------------------------


@pytest.fixture
def reply_stack(stack):
    """The fake jobwatch's reply answer, put back after the test."""
    server = stack.server
    server.replies.clear()
    yield stack
    server.reply_answer = {}
    server.reply_status = 200
    server.reply_delay = 0.0
    server.features = list(FEATURES)


def reply_panel(stack, ext, panels, query: str = ""):
    """A demo conversation in a tab and the panel for it, with Draft reply showing. Returns (page, panel)."""
    url = stack.url("www.linkedin.com", f"/messaging/thread/2-abc/{query}")
    page = open_form(stack, ext, url)
    panel = harness.side_panel(stack, url)
    panels.append(panel)
    panel.wait_for_selector("#reply", state="visible", timeout=20000)
    return page, panel


def put_in_box(panel):
    panel.evaluate("() => document.getElementById('toast')?.remove()")
    panel.click("#reply-fill")
    panel.wait_for_selector("#toast", timeout=20000)
    return panel.inner_text("#toast")


def test_draft_reply_reads_the_open_thread_shows_where_it_was_written_and_never_sends(reply_stack, ext, panels):
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-text", timeout=60000)
        sent = reply_stack.server.replies[-1]
        assert sent["sender"] == "Dana Whitfield"
        assert sent["thread"].startswith("Dana Whitfield, Nov 12, 9:41 AM\nHi Jordan, I'm a recruiter at Northwind Talent.")
        assert "Jordan Rivera, Nov 12, 10:15 AM\nThanks Dana. Which client" in sent["thread"]
        assert sent["thread"].count("\n\n") == 3  # four messages, nothing else on the page
        # the panel says it was written on this Mac, shows the draft, the check-this notes and no warning
        assert "did not leave" in panel.inner_text("#reply-where")
        assert "pill local" in panel.get_attribute("#reply-where", "class")
        assert panel.input_value("#reply-text").startswith("Thanks Dana.")
        assert "Check this before you send" in panel.inner_text(".rows")
        assert panel.locator(".warnrow").count() == 0
        # it goes in LinkedIn's box (edited text included), and nothing is sent
        panel.fill("#reply-text", "Thanks Dana. Thursday works. What is the client and the range?")
        assert "In the message box" in put_in_box(panel)
        assert page.inner_text("[role=textbox]") == "Thanks Dana. Thursday works. What is the client and the range?"
        assert page.evaluate("[window.__clicks, window.__sent]") == [0, 0]
    finally:
        page.close()


@pytest.mark.parametrize("query", ["?live", "?nobox", "?overlay", "?live&overlay", "?shadow", "?live&shadow"])
def test_draft_reply_finds_the_thread_on_the_current_site_shape(reply_stack, ext, panels, query):
    page, panel = reply_panel(reply_stack, ext, panels, query)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-text", timeout=60000)
        sent = reply_stack.server.replies[-1]
        assert sent["sender"] == "Dana Whitfield"
        assert sent["thread"].count("\n\n") == 3
        assert "No conversation is open" not in panel.inner_text("#view")
        if query in ("?live", "?shadow", "?live&shadow"):  # filling is checked where there is one box; ?shadow is LinkedIn's bubble inside a shadow root
            assert "In the message box" in put_in_box(panel)
            assert page.evaluate("[window.__clicks, window.__sent]") == [0, 0]
            if "shadow" in query:
                assert page.evaluate("document.getElementById('interop-outlet').shadowRoot.querySelector('[contenteditable]').textContent").strip() != ""
    finally:
        page.close()


@pytest.mark.parametrize("query", ["?inmail", "?inmail&live", "?bare", "?frame", "?inmail&frame"])
def test_draft_reply_reads_an_inmail_a_page_without_linkedins_class_names_and_a_thread_in_a_frame(reply_stack, ext, panels, query):
    """The InMail shape (a subject above a message with line breaks), a page whose class names are all gone (structure
    and roles only) and a thread drawn in a frame: each is read, each reply goes in the box, and nothing is sent."""
    page, panel = reply_panel(reply_stack, ext, panels, query)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-text", timeout=60000)
        thread = reply_stack.server.replies[-1]["thread"]
        assert "No conversation is open" not in panel.inner_text("#view")
        if "inmail" in query:
            assert reply_stack.server.replies[-1]["sender"] == "Dana Whitfield"
            assert thread == ("Dana Whitfield, Today, 9:41 AM\nHi Jordan,\n\nI'm a recruiter at Northwind Talent hiring a Platform Engineer "
                              "for a client.\n\nWould you be open to a quick call this week?")
        else:
            assert "Hi Jordan, I'm a recruiter at Northwind Talent." in thread
            assert "The range is 140-150K base. Are you free Thursday?" in thread
            assert "Write a message" not in thread  # the box's own paragraph is not a message
        panel.fill("#reply-text", "Thanks Dana. Thursday works.")
        assert "In the message box" in put_in_box(panel)
        scope = page.frame_locator("#thread-frame") if "frame" in query else page
        assert scope.locator("[contenteditable]").inner_text() == "Thanks Dana. Thursday works."  # ?live has no role on the box
        if "frame" not in query:
            assert page.evaluate("[window.__clicks, window.__sent]") == [0, 0]
        else:
            assert page.frames[1].evaluate("[window.__clicks, window.__sent]") == [0, 0]
    finally:
        page.close()


def test_a_slow_draft_shows_a_spinner_and_a_ticking_counter_that_stop_when_it_returns(reply_stack, ext, panels):
    reply_stack.server.reply_delay = 3.5
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#view .spinner")
        assert panel.inner_text("#elapsed") in ("0s", "1s")
        panel.wait_for_function("() => ['2s', '3s'].includes(document.getElementById('elapsed')?.textContent)", timeout=10000)
        panel.wait_for_selector("#reply-text", timeout=20000)
        assert panel.locator("#elapsed").count() == 0 and panel.locator(".spinner").count() == 0
    finally:
        page.close()


def test_the_counter_stops_when_the_draft_fails(reply_stack, ext, panels):
    reply_stack.server.reply_delay = 1.5
    reply_stack.server.reply_status = 500
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#elapsed")
        panel.wait_for_function("() => document.getElementById('view').textContent.includes('the model is not answering')", timeout=20000)
        assert panel.locator("#elapsed").count() == 0
    finally:
        page.close()


def test_draft_reply_warns_when_the_thread_went_to_a_cloud_model(reply_stack, ext, panels):
    reply_stack.server.reply_answer = {"local": False, "model": "claude-test", "warnings": ["They asked for your pay: it is not in the draft."]}
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-text", timeout=60000)
        assert "pill cloud" in panel.get_attribute("#reply-where", "class")
        assert "sent to claude-test, off this Mac" in panel.inner_text("#reply-where")
        assert "They asked for your pay" in panel.inner_text(".warnrow")
    finally:
        page.close()


def test_draft_reply_without_a_draft_shows_only_the_warning(reply_stack, ext, panels):
    reply_stack.server.reply_answer = {"drafted": False, "reply": "", "notes": [], "warnings": ["Their message says no AI replies: write this one yourself."]}
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector(".warnrow", timeout=60000)
        assert panel.locator("#reply-text").count() == 0 and panel.locator("#reply-fill").count() == 0
        assert "write this one yourself" in panel.inner_text(".warnrow")
    finally:
        page.close()


def test_draft_reply_when_the_users_message_is_last_offers_a_follow_up_only_on_request(reply_stack, ext, panels):
    reply_stack.server.reply_answer = {"drafted": False, "waiting": True, "reply": "", "notes": [],
                                       "warnings": ["Your message is the last one; there is nothing to reply to yet."]}
    page, panel = reply_panel(reply_stack, ext, panels)
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-followup", timeout=60000)
        assert "nothing to reply to yet" in panel.inner_text(".warnrow") and panel.locator("#reply-text").count() == 0
        assert reply_stack.server.replies[-1]["followup"] is False
        assert reply_stack.server.replies[-1]["last"] == "Dana Whitfield"  # who wrote the thread's last message (the demo's)
        reply_stack.server.reply_answer = {"followup": True}
        panel.click("#reply-followup")
        panel.wait_for_selector("#reply-text", timeout=60000)
        assert reply_stack.server.replies[-1]["followup"] is True
        assert panel.locator("#reply-followup").count() == 0
    finally:
        page.close()


def test_draft_reply_says_when_the_server_fails_or_two_conversations_are_open(reply_stack, ext, panels):
    reply_stack.server.reply_status = 500
    page, panel = reply_panel(reply_stack, ext, panels, "?two")
    try:
        panel.click("#reply")
        # The progress line ("Reading the open conversation...") is a .msg too: wait for the words, not the class.
        panel.wait_for_function("() => document.getElementById('view').textContent.includes('More than one conversation is open')",
                                timeout=20000)
        assert "More than one conversation is open" in panel.inner_text("#view")
        assert reply_stack.server.replies == []  # nothing was sent while it was unclear which one
        page.click("#bubble [role=textbox]")  # the person picks one by clicking in its box
        panel.click("#reply")
        panel.wait_for_function("() => document.getElementById('view').textContent.includes('the model is not answering')")
        assert reply_stack.server.replies[-1]["sender"] == "Marcus Bell"
    finally:
        page.close()


def test_draft_reply_never_overwrites_what_the_person_typed_and_checks_the_thread(reply_stack, ext, panels):
    page, panel = reply_panel(reply_stack, ext, panels, "?filled")
    try:
        panel.click("#reply")
        panel.wait_for_selector("#reply-text", timeout=60000)
        assert "already has text" in put_in_box(panel)
        assert page.inner_text("[role=textbox]") == "Hi Dana,"
        panel.locator("#reply-replace").wait_for(state="visible")
        panel.evaluate("() => document.getElementById('toast')?.remove()")
        panel.click("#reply-replace")  # the person says to replace it
        panel.wait_for_selector("#toast")
        drafted = panel.input_value("#reply-text")
        assert page.inner_text("[role=textbox]") == drafted
        # a new message arrives meanwhile: the draft no longer answers the thread, so it is not put in the box again
        page.evaluate("() => { const p = document.createElement('p'); p.className = 'msg-s-event-listitem__body'; "
                      "p.textContent = 'Actually, the role is remote.'; document.querySelector('li:last-of-type').append(p); }")
        page.evaluate("() => { document.querySelector('[role=textbox]').innerHTML = ''; }")
        assert "changed" in put_in_box(panel)
        assert page.inner_text("[role=textbox]") == ""
        assert page.evaluate("[window.__clicks, window.__sent]") == [0, 0]
    finally:
        page.close()


def test_an_older_jobwatch_without_the_reply_call_gets_no_draft_reply_button(reply_stack, ext, panels):
    reply_stack.server.features = ["posting"]
    url = reply_stack.url("www.linkedin.com", "/messaging/thread/2-abc/")
    page = open_form(reply_stack, ext, url)
    try:
        panel = harness.side_panel(reply_stack, url)
        panels.append(panel)
        panel.wait_for_selector("#scan")
        assert panel.locator("#reply").count() == 0
    finally:
        page.close()


# --- ATS check and Cover letter, on the company's own careers page (demo/cover.html, demo/cover-file.html) -----------


def careers_panel(stack, ext, panels, path: str = "/openings/platform-engineer"):
    """The company's careers page for the demo job in a tab, and the panel for it. Returns (page, panel, url)."""
    url = stack.url("careers.initech.example", path)
    page = open_form(stack, ext, url)
    panel = harness.side_panel(stack, url)
    panels.append(panel)
    panel.wait_for_selector("#lead")
    return page, panel, url


def toast_text(panel) -> str:
    panel.wait_for_selector("#toast", timeout=20000)
    return panel.inner_text("#toast")


def test_the_page_company_and_title_go_to_jobwatch_so_it_can_tell_the_job(stack, ext, panels):
    page, panel, url = careers_panel(stack, ext, panels)
    try:
        panel.click("#scan")
        panel.wait_for_selector(".row", timeout=20000)
        assert stack.server.contexts[-1] == {"url": url, "company": "Initech", "title": "Platform Engineer"}
    finally:
        page.close()


def test_ats_check_shows_what_a_screener_would_miss_and_tailors_on_request(stack, ext, panels):
    page, panel, url = careers_panel(stack, ext, panels)
    try:
        assert "dim" not in panel.get_attribute("#ats", "class") and "dim" not in panel.get_attribute("#cover", "class")
        panel.click("#ats")
        panel.wait_for_selector("#ats-score", timeout=20000)
        sent = stack.server.ats_calls[-1]
        assert sent == {"url": url, "company": "Initech", "title": "Platform Engineer"}
        assert panel.inner_text("#ats-score") == "ATS 50%: 2 of 4 keywords found"
        assert "pill cloud" in panel.get_attribute("#ats-score", "class")  # under 70: a warning colour
        assert row(panel, "What a screener would miss").locator(".kw").all_inner_texts() == ["Terraform *", "Kafka"]
        assert row(panel, "Found in the resume").locator(".kw").all_inner_texts() == ["Python *", "Kubernetes *"]
        assert "not tailored" in panel.inner_text("#ats-file")
        assert panel.locator("#matched-by").count() == 0
        assert "Initech" in panel.inner_text("#where")
        # the general resume was read, so a tailored one is offered; pressing it tailors, then checks that one
        panel.click("#ats-tailor")
        panel.wait_for_function("() => document.getElementById('ats-file')?.textContent.includes('tailored for this job')", timeout=20000)
        assert stack.server.tailors[-1]["company"] == "Initech" and "Jordan_Rivera_Initech.pdf" in panel.inner_text("#ats-file")
        assert panel.locator("#ats-tailor").count() == 0
        panel.click("#ats-again")
        panel.wait_for_selector("#ats-score", timeout=20000)
        assert len(stack.server.ats_calls) == 3
        assert page.evaluate("window.__submits") == 0 and stack.server.submitted == []
    finally:
        page.close()


def test_the_panel_says_when_a_job_was_matched_only_by_its_company_and_title(stack, ext, panels):
    stack.server.ats_answer = stack.server.cover_answer = {"matched_by": "name"}
    page, panel, url = careers_panel(stack, ext, panels)
    try:
        panel.click("#ats")
        panel.wait_for_selector("#matched-by", timeout=20000)
        assert "company and title" in panel.inner_text("#matched-by") and "Check it is the right one" in panel.inner_text("#matched-by")
        cover = harness.side_panel(stack, url)  # a second panel for the same tab
        panels.append(cover)
        cover.click("#cover")
        cover.wait_for_selector("#matched-by", timeout=30000)
        assert "company and title" in cover.inner_text("#matched-by")
    finally:
        page.close()


def test_a_page_for_a_job_jobwatch_does_not_track_says_what_to_do(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    try:
        panel = harness.side_panel(stack, url)
        panels.append(panel)
        panel.wait_for_selector("#ats")
        assert "dim" in panel.get_attribute("#ats", "class")  # not a job's page, but the tile still works
        for tile in ("ats", "cover"):
            panel.click(f"#{tile}")
            panel.wait_for_selector(".empty.home .msg", timeout=20000)
            assert "doesn't track this job yet: save the posting to jobwatch first" in panel.inner_text(".empty.home .msg")
            panel.wait_for_selector("#ats")
    finally:
        page.close()


def test_cover_letter_is_drafted_shown_and_put_in_the_form_but_never_submitted(stack, ext, panels):
    stack.server.cover_delay = 1.5
    page, panel, url = careers_panel(stack, ext, panels)
    try:
        panel.click("#cover")
        panel.wait_for_selector(".spinner")  # a slow local model shows the working view with its counter
        panel.wait_for_selector("#cover-text", timeout=30000)
        sent = stack.server.covers[-1]
        assert (sent["url"], sent["company"], sent["title"]) == (url, "Initech", "Platform Engineer")
        assert panel.input_value("#cover-text").startswith("Hello Initech team,")
        assert "pill local" in panel.get_attribute("#cover-where", "class") and "Nothing left it" in panel.inner_text("#cover-where")
        assert "Saved with the job as version 1" in panel.inner_text(".rows")
        assert "cover letter box" in panel.inner_text("#cover-box") and page.input_value("#cl") == ""  # nothing is put in until asked
        # the person edits the draft; what goes in the box is the edit
        panel.fill("#cover-text", "Hello Initech team,\n\nMy own words.")
        panel.click("#cover-fill")
        assert "In the cover letter box" in toast_text(panel)
        assert page.input_value("#cl") == "Hello Initech team,\n\nMy own words."
        assert page.evaluate("window.__submits") == 0 and stack.server.submitted == [] and stack.server.answers == []
        # another tone and a lean: a second version, asked for with those
        panel.select_option("#cover-tone", "warm")
        panel.fill("#cover-emphasis", "my platform work")
        panel.click("#cover-again")
        panel.wait_for_function("() => document.getElementById('cover-text') && document.getElementById('cover-tone').value === 'warm'", timeout=30000)
        assert (stack.server.covers[-1]["tone"], stack.server.covers[-1]["emphasis"]) == ("warm", "my platform work")
        assert "version 2" in panel.inner_text(".rows") and panel.input_value("#cover-emphasis") == "my platform work"
        panel.evaluate("() => document.getElementById('toast')?.remove()")
        panel.click("#cover-copy")
        assert toast_text(panel) in ("Copied.", "Couldn't copy. Select the text and copy it.")
    finally:
        page.close()


def test_cover_letter_leaves_what_the_person_typed_until_asked_to_replace_it(stack, ext, panels):
    page, panel, _url = careers_panel(stack, ext, panels, "/openings/platform-engineer?typed")
    try:
        panel.click("#cover")
        panel.wait_for_selector("#cover-text", timeout=30000)
        assert "text in it already" in panel.inner_text("#cover-box")
        assert panel.locator("#cover-replace").is_hidden()
        panel.click("#cover-fill")
        assert "already has text" in toast_text(panel)
        assert page.input_value("#cl") == "Already typed by the person."
        panel.locator("#cover-replace").wait_for(state="visible")
        panel.evaluate("() => document.getElementById('toast')?.remove()")
        panel.click("#cover-replace")
        assert "In the cover letter box" in toast_text(panel)
        assert page.input_value("#cl").startswith("Hello Initech team,")
        assert page.evaluate("window.__submits") == 0
    finally:
        page.close()


def test_a_form_that_takes_the_cover_letter_as_a_file_gets_no_fill_button(stack, ext, panels):
    page, panel, _url = careers_panel(stack, ext, panels, "/openings/file")
    try:
        panel.click("#cover")
        panel.wait_for_selector("#cover-text", timeout=30000)
        assert panel.locator("#cover-fill").count() == 0 and panel.locator("#cover-copy").count() == 1
        assert "as a file" in panel.inner_text("#cover-box")
        assert page.evaluate("document.getElementById('cl').files.length") == 0
    finally:
        page.close()


def test_a_page_with_no_cover_letter_box_offers_only_copy(stack, ext, panels):
    page, panel, _url = careers_panel(stack, ext, panels, "/careers")  # the embedded Greenhouse form: no such box
    try:
        panel.click("#cover")
        panel.wait_for_selector("#cover-text", timeout=30000)
        assert panel.locator("#cover-fill").count() == 0 and "No cover letter box" in panel.inner_text("#cover-box")
    finally:
        page.close()


def test_a_cover_letter_written_by_a_cloud_model_says_so_and_no_draft_shows_only_why(stack, ext, panels):
    stack.server.cover_answer = {"local": False, "model": "a-cloud-model"}
    page, panel, _url = careers_panel(stack, ext, panels)
    try:
        panel.click("#cover")
        panel.wait_for_selector("#cover-text", timeout=30000)
        assert "pill cloud" in panel.get_attribute("#cover-where", "class")
        assert "written by a-cloud-model, off this Mac" in panel.inner_text("#cover-where")
        stack.server.cover_answer = {"drafted": False, "letter": "", "version": None, "model": None,
                                     "warnings": ["No draft: the local model isn't running. Start it with `local-llm`, then draft again."]}
        panel.click("#cover-again")
        panel.wait_for_selector(".warnrow", timeout=30000)
        assert "local model isn't running" in panel.inner_text(".warnrow")
        assert panel.locator("#cover-text").count() == 0 and panel.locator("#cover-fill").count() == 0
        assert panel.locator("#cover-again").count() == 1
    finally:
        page.close()


def test_an_older_jobwatch_gets_no_ats_or_cover_tile(stack, ext, panels):
    url = stack.url("careers.initech.example", "/openings/platform-engineer")
    page = open_form(stack, ext, url)
    stack.server.features = ["posting", "reply", "import-list"]  # jobwatch 0.12: no ats, no cover
    try:
        harness.pair(stack, stack.api_url, "")
        panel = harness.side_panel(stack, url)
        panels.append(panel)
        harness.pair(stack, stack.api_url, harness.TOKEN)
        panel.wait_for_function("() => document.getElementById('pair').textContent.includes('paired ')")
        panel.wait_for_selector("#scan")
        assert panel.locator("#ats").count() == 0 and panel.locator("#cover").count() == 0
        # a call made anyway: that jobwatch answers an unknown path "not found", and the worker says to update it
        tab = harness.tab_id_for(ext, url)
        for call, name in (("ats", "ATS check"), ("cover", "Cover letter")):
            reply = ext.evaluate("([type, tabId]) => chrome.runtime.sendMessage({type, tabId})", [call, tab])
            assert reply["ok"] is False and f"too old for {name}. Update jobwatch" in reply["error"]
    finally:
        stack.server.features = list(FEATURES)
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
    shots = {f"screenshot-{n}.png" for n in ("1-review", "2-filled", "3-draft", "4-pairing", "5-list-import", "6-imported")}
    assert set(written) == shots | {"promo-small.png", "promo-marquee.png", "icon128.png"}
    sizes = {"promo-small.png": store_assets.PROMO, "promo-marquee.png": store_assets.MARQUEE, "icon128.png": (128, 128)}
    for name, path in written.items():
        png = path.read_bytes()
        assert struct.unpack(">II", png[16:24]) == sizes.get(name, store_assets.SCREEN), name


def test_the_panel_leads_with_the_page_and_dims_the_tiles_that_do_not_suit_it(stack, ext, panels):
    form = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, form)
    try:
        panel = harness.side_panel(stack, form)
        panels.append(panel)
        panel.wait_for_selector("#lead")
        assert "idle" in panel.get_attribute("#lead", "class") and panel.locator("#lead-go").count() == 0
        assert panel.locator(".tile").count() >= 4  # every action stays, dimmed
        assert "dim" in panel.get_attribute("#scan", "class")
        lever = stack.url("jobs.lever.co", "/initech/6f1b2c/apply")
        page.goto(lever)
        panel = harness.side_panel(stack, lever)
        panels.append(panel)
        panel.wait_for_selector("#lead.form")
        assert panel.inner_text("#lead h2") == "Application form" and "Initech" in panel.inner_text("#lead .detail")
        assert "dim" not in panel.get_attribute("#scan", "class") and "dim" in panel.get_attribute("#reply", "class")
        panel.click("#lead-go")  # the lead card's button does what the Fill tile does
        panel.wait_for_selector(".row", timeout=20000)
    finally:
        page.close()


def test_the_theme_chosen_in_settings_is_the_one_the_panel_wears(stack, ext, panels):
    url = f"http://127.0.0.1:{stack.site_port}/generic.html"
    page = open_form(stack, ext, url)
    try:
        panel = harness.side_panel(stack, url)
        panels.append(panel)
        panel.wait_for_selector("#lead")
        assert panel.evaluate("document.documentElement.getAttribute('data-theme')") is None  # System first
        options = stack.extension_page("options.html")
        options.select_option("#theme", "dark")
        panel.wait_for_function("document.documentElement.getAttribute('data-theme') === 'dark'")
        options.select_option("#theme", "system")
        panel.wait_for_function("document.documentElement.getAttribute('data-theme') === null")
        options.close()
    finally:
        page.close()


def test_panel_states_are_captured_for_every_kind_of_page(tmp_path, pw):
    try:
        written = {p.name for p in panel_states.capture(tmp_path, playwright=pw)}
    except harness.BrowserUnavailable as exc:
        pytest.skip(str(exc))
    assert {f"panel-{k}-{t}-narrow.png" for k in ("form", "thread", "list", "posting", "idle") for t in ("light", "dark")} <= written
    assert {"panel-list-light-wide.png", "panel-not-paired-light-narrow.png", "options-light.png"} <= written
    assert all((tmp_path / name).stat().st_size > 2000 for name in written)


def test_demo_video_is_a_narrated_1280x800_mp4(tmp_path, pw):
    slidecast = pytest.importorskip("slidecast")
    try:
        ffmpeg = slidecast.find_ffmpeg()
    except slidecast.FFmpegNotFound:
        pytest.skip("ffmpeg not available")
    import subprocess

    import demo_video

    try:
        out = demo_video.record(tmp_path / "demo.mp4", voice="silent", playwright=pw)
    except harness.BrowserUnavailable as exc:
        pytest.skip(str(exc))
    probe = subprocess.run([ffmpeg, "-i", str(out)], capture_output=True, text=True).stderr
    assert "1280x800" in probe and "Audio: aac" in probe
    # The hook, the steps from the extensions page to Submit, the trust, start and end cards: about two minutes.
    assert demo_video.TITLE_SECONDS + 20 < slidecast.probe_duration(out, ffmpeg=ffmpeg) < 150
    assert (tmp_path / "demo_poster.jpg").is_file()


# --- Read posting from jobwatch's own page: a tab behind this one, only that card changes ----------------------

LINKEDIN_TABS = "async () => (await chrome.tabs.query({url: '*://www.linkedin.com/*'})).map((t) => ({id: t.id, active: t.active}))"


def read_from_jobwatch(stack, query: str):
    """jobwatch's (demo) Today page, scrolled down to its card, and the card's Read posting pressed for a demo posting."""
    from urllib.parse import quote

    posting = stack.url("www.linkedin.com", f"/jobs/view/4000000001/{query}")
    page = stack.context.new_page()
    page.goto(f"{stack.api_url}/demo/today?posting={quote(posting, safe='')}")
    page.evaluate("() => window.scrollTo(0, 1200)")
    stack.server.postings.clear()
    page.click("#read")
    return page


def test_read_posting_from_jobwatchs_page_opens_behind_and_changes_only_that_card(stack, ext):
    page = read_from_jobwatch(stack, "")
    try:
        tabs = harness.wait_until(lambda: ext.evaluate(LINKEDIN_TABS), what="the posting's tab")
        assert [t["active"] for t in tabs] == [False]  # behind the page, never in front of it
        mine = ext.evaluate("async (u) => (await chrome.tabs.query({})).find((t) => t.url.startsWith(u)).active", stack.api_url)
        assert mine is True
        harness.wait_until(lambda: page.evaluate("() => window.answers.length"), what="the extension's answer")
        assert page.evaluate("() => window.answers[0]") == {
            "type": "jobwatch:read-posting-done", "key": "demo", "ok": True, "closed": True, "has_text": True,
            "said": "Filled in from Greenhouse; scoring now"}
        assert page.inner_text("#state") == "closed"  # the card changed ...
        assert page.evaluate("() => window.scrollY") == 1200  # ... and the page stayed where it was
        (sent,) = stack.server.postings
        assert sent["linkedin"] == "4000000001" and sent["closed"] is True
        assert sent["text"].startswith("For our client, Initech")
        harness.wait_until(lambda: not ext.evaluate(LINKEDIN_TABS), timeout=15, what="the posting's tab to close itself")
    finally:
        page.close()


def test_the_extension_answers_the_pages_ping_with_what_it_can_do(stack, ext):
    """The page picks its way to read from this attribute, which the bridge sets from the service worker's `ping`."""
    page = stack.context.new_page()
    try:
        page.goto(f"{stack.api_url}/demo/today")
        harness.wait_until(lambda: page.evaluate("() => document.documentElement.dataset.jobwatchCaps") is not None,
                           what="the capabilities")
        assert page.evaluate("() => document.documentElement.dataset.jobwatchCaps") == "readInBackground"
    finally:
        page.close()


def test_an_open_posting_read_from_jobwatchs_page_says_so(stack, ext):
    page = read_from_jobwatch(stack, "?open=1")
    try:
        harness.wait_until(lambda: page.evaluate("() => window.answers.length"), what="the extension's answer")
        assert page.inner_text("#state") == "read"
        assert stack.server.postings[0]["closed"] is False
        harness.wait_until(lambda: not ext.evaluate(LINKEDIN_TABS), timeout=15, what="the posting's tab to close itself")
    finally:
        page.close()


def test_a_local_page_that_is_not_jobwatch_cannot_open_tabs_through_the_bridge(stack, ext):
    """Any local page gets the bridge; the extension answers only the one on jobwatch's own address and port."""
    page = stack.context.new_page()
    try:
        page.goto(stack.url("127.0.0.1", "/linkedin-jobs.html"))
        page.evaluate("""(u) => { window.answers = [];
          window.addEventListener('message', (e) => e.data && e.data.type === 'jobwatch:read-posting-done' && window.answers.push(e.data));
          window.postMessage({type: 'jobwatch:read-posting', key: 'x', url: u}, location.origin); }""",
                      stack.url("www.linkedin.com", "/jobs/view/4000000001/"))
        harness.wait_until(lambda: page.evaluate("() => window.answers.length"), what="the refusal")
        answer = page.evaluate("() => window.answers[0]")
        assert answer["ok"] is False and "Only your own jobwatch page" in answer["error"]
        assert ext.evaluate(LINKEDIN_TABS) == []
    finally:
        page.close()
