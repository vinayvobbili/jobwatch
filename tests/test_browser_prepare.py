"""The Queue card's one Prepare button in a real browser (headless Chromium through Playwright): it runs the resume,
the ATS check and the cover letter in that order, keeps each result with the job, and says why a step that can't run
didn't. Resume-kit, the PDF reader and the model are faked in this process (the page's server runs in it); nothing
leaves the test. Skipped where Playwright or its browser isn't installed (`pip install -e ".[browser]"` then
`playwright install chromium`)."""

import pytest

from jobwatch import ats, chat, config, cover, tailor
from jobwatch.store import Store

from .conftest import TOKEN, request
from .test_tailor import FakeKit

sync_api = pytest.importorskip("playwright.sync_api")

KEY = "ashby:initech:c1"  # Initech, Staff Data Engineer: the demo job on the test server's fake board
CARD = f'[id="job-{KEY}"]'
RESUME = """Jordan Rivera
jordan@example.com  3035550142

Experience
Platform Engineer, Globex (2019-2024)
- Built agents and RAG pipelines in Python, with evaluation suites that gate every release
- Cut deploy time from 40 minutes to 9 by caching builds and splitting the monorepo into services
- Mentored four engineers and ran the quarterly capacity review with finance

Education
BS Computer Science, Boulder, CO

Skills
Python, RAG, evaluation, agents, Staff Data Engineer, Kubernetes, Terraform
"""
LETTER = ("Hello Initech team,\n\nI built agents and RAG pipelines at Globex, which is the work this role asks for. "
          "I would like to talk about the data platform at Initech. Thank you for your time. "
          + "Plain words fill the length. " * 30)


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
def queued(server, watchlist):
    """The server with the fake boards fetched and the Initech job queued, a resume set and resume-kit faked."""
    (watchlist.parent / "resume.txt").write_text(RESUME)
    watchlist.write_text(watchlist.read_text() + "resume: resume.txt\n")
    assert request(server, "POST", "/api/fetch", {}, headers={"X-Jobwatch-Token": TOKEN})[0] == 200
    store = Store(config.load(watchlist).state)
    store.set_status([KEY], "queued", None)
    store.close()
    return server


@pytest.fixture
def steps(monkeypatch):
    """Resume-kit, the PDF reader and the model, faked, each noting when it ran: the order Prepare runs them in."""
    events: list[str] = []
    kit = FakeKit()
    real = kit.__call__

    def run(argv, **kw):
        if argv[1] in ("draft", "build"):
            events.append(f"resume {argv[1]}")
        return real(argv, **kw)

    monkeypatch.setattr(tailor.subprocess, "run", run)
    monkeypatch.setattr(tailor.shutil, "which", lambda name: "/bin/" + name.rsplit("/", 1)[-1])
    monkeypatch.setattr(tailor, "ready", lambda setting: True)

    def read(path):
        events.append(f"ats read {path.name}")
        return RESUME, "pdftotext"
    monkeypatch.setattr(ats, "read_file", read)
    monkeypatch.setattr(cover, "resume_text", lambda path: RESUME)  # the fake kit's PDF has no text to read

    def reply(backend, system, messages, model="", max_tokens=0):
        events.append("cover draft")
        yield LETTER
        yield {"output_tokens": 9}
    monkeypatch.setattr(chat, "check", lambda *a: None)
    monkeypatch.setattr(chat, "reply", reply)
    return events


@pytest.fixture
def page(browser, queued, steps):  # the fakes are in place before the page asks whether resume-kit is set up
    page = browser.new_page()
    page.set_default_timeout(20000)  # every wait is bounded: a stuck step fails its test, never hangs the run
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("response", lambda r: r.status >= 400 and page.errors.append(f"{r.status} {r.url}"))
    page.goto(f"http://127.0.0.1:{queued}/#queue")
    page.locator(CARD).wait_for(timeout=15000)
    yield page
    page.close()


def step_panel(card, step: str):
    """A step's result panel (the chip above it carries the same data-step)."""
    return card.locator(f'div[data-step="{step}"]')


def chips(page) -> list[tuple[str, str]]:
    return [(c.get_attribute("data-state"), c.inner_text()) for c in page.locator(f"{CARD} .prep-chip").all()]


def test_the_card_has_one_prepare_button_in_place_of_the_three(page):
    card = page.locator(CARD)
    assert card.get_by_role("button", name="Prepare", exact=True).count() == 1
    for gone in ("Tailor resume", "Rebuild resume", "ATS check", "Cover letter"):
        assert card.get_by_role("button", name=gone, exact=True).count() == 0, gone
    for kept in ("I applied", "Remove from queue", "Details"):
        assert card.get_by_role("button", name=kept, exact=True).count() == 1, kept
    assert card.get_by_role("link", name="Apply ↗").count() == 1
    assert card.locator(".prepare").is_hidden()  # nothing to show until it has run (this job has no resume yet)
    assert page.errors == []


def test_prepare_runs_resume_then_ats_check_then_cover_letter_and_keeps_them(page, queued, steps, watchlist):
    card = page.locator(CARD)
    button = card.get_by_role("button", name="Prepare", exact=True)
    assert "Local model; nothing is sent" in button.get_attribute("title")
    button.click()
    sync_api.expect(card.get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)
    # the order: the resume is built before the ATS check reads it, and the letter is written last
    assert steps == ["resume draft", "resume build", "ats read Jordan_Rivera_Resume_X.pdf", "cover draft"]
    states = chips(page)
    assert [s for s, _ in states] == ["ok", "ok", "ok"], states
    assert states[0][1] == "Resume drafted" and states[1][1].startswith("ATS ") and states[2][1] == "Cover letter v1"
    # each result is on the card: the resume to open, the ATS score, the letter to copy
    assert "Jordan_Rivera_Resume_X.pdf" in step_panel(card, "tailor").inner_text()
    assert step_panel(card, "ats").locator(".badge").inner_text().startswith("ATS ")
    assert "not tailored" not in step_panel(card, "ats").inner_text()  # it read the tailored one
    assert step_panel(card, "cover").locator("textarea").input_value().startswith("Hello Initech team,")
    assert card.get_by_role("button", name="Prepare again").is_enabled()
    # and kept with the job, where the old buttons kept them
    store = Store(config.load(watchlist).state)
    try:
        assert store.package(KEY).resume().name == "Jordan_Rivera_Resume_X.pdf"
        assert [v["version"] for v in cover.versions(store, KEY)] == [1]
    finally:
        store.close()
    assert page.errors == []
    # a reload shows the resume that is kept; a second press rebuilds it, checks it and writes version 2
    page.reload()
    page.locator(CARD).wait_for(timeout=15000)
    assert "Jordan_Rivera_Resume_X.pdf" in page.locator(f"{CARD} .prepare").inner_text()
    page.locator(CARD).get_by_role("button", name="Prepare", exact=True).click()
    sync_api.expect(page.locator(CARD).get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)
    assert chips(page)[2][1] == "Cover letter v2" and steps.count("cover draft") == 2
    assert "resume draft" == steps[0] and steps.count("resume draft") == 1  # rebuilt, not redrafted


def test_a_step_that_cannot_run_says_why_and_the_steps_after_it_still_run(page, queued, steps, monkeypatch, watchlist):
    monkeypatch.setattr(tailor, "ready", lambda setting: False)

    def unavailable(*a):
        raise chat.ChatUnavailable("the local model isn't running: start it with `local-llm`")
    monkeypatch.setattr(chat, "check", unavailable)
    page.reload()
    page.locator(CARD).wait_for(timeout=15000)
    card = page.locator(CARD)
    card.get_by_role("button", name="Prepare", exact=True).click()
    sync_api.expect(card.get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)
    states = chips(page)
    # no resume-kit: the resume step is skipped, and the general resume is what the ATS check reads; no model: a warning
    assert [s for s, _ in states] == ["skip", "ok", "warn"], states
    assert states[0][1] == "Resume: set up resume-kit" and states[2][1] == "Cover letter: no draft"
    assert "Tailoring needs resume-kit" in step_panel(card, "tailor").inner_text()
    assert "general resume" in step_panel(card, "ats").inner_text()
    assert "local model isn't running" in step_panel(card, "cover").inner_text()
    assert step_panel(card, "cover").locator("textarea").count() == 0
    assert steps == ["ats read resume.txt"]  # nothing was built or drafted
    assert card.get_by_role("button", name="Prepare again").is_enabled()
    assert page.errors == []


def test_a_step_that_fails_is_marked_and_the_next_one_still_runs(page, queued, steps, monkeypatch):
    def broken(path):
        raise ValueError("Can't read the PDF's text: install poppler (`brew install poppler`).")
    monkeypatch.setattr(ats, "read_file", broken)
    card = page.locator(CARD)
    card.get_by_role("button", name="Prepare", exact=True).click()
    sync_api.expect(card.get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)
    states = chips(page)
    assert [s for s, _ in states] == ["ok", "err", "ok"], states
    assert states[1][1] == "ATS check failed"
    assert "install poppler" in step_panel(card, "ats").inner_text()
    assert step_panel(card, "cover").locator("textarea").input_value().startswith("Hello Initech team,")


def test_the_company_page_card_has_the_same_one_button(page, queued):
    page.goto(f"http://127.0.0.1:{queued}/#company/Initech")
    card = page.locator(CARD)
    card.wait_for(timeout=15000)
    assert card.get_by_role("button", name="Prepare", exact=True).count() == 1
    for gone in ("Tailor resume", "ATS check", "Cover letter"):
        assert card.get_by_role("button", name=gone, exact=True).count() == 0, gone
    assert page.errors == []
