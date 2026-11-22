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
    """A step's result panel (the chip above it carries the same data-step). It's folded away until its chip is
    pressed: `shown` opens it first."""
    return card.locator(f'div[data-step="{step}"]')


def shown(card, step: str):
    """A step's result panel, opened by its chip if it isn't open yet."""
    chip = card.locator(f'button.prep-chip[data-step="{step}"]')
    if chip.get_attribute("aria-expanded") != "true":
        chip.click()
    panel = step_panel(card, step)
    sync_api.expect(panel).to_be_visible()
    return panel


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
    assert all(step_panel(card, s).is_hidden() for s in ("tailor", "ats", "cover"))  # folded until a chip is pressed
    assert "Jordan_Rivera_Resume_X.pdf" in shown(card, "tailor").inner_text()
    assert shown(card, "ats").locator(".badge").inner_text().startswith("ATS ")
    assert "not tailored" not in step_panel(card, "ats").inner_text()  # it read the tailored one
    assert shown(card, "cover").locator("textarea").input_value().startswith("Hello Initech team,")
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
    assert [c.inner_text() for c in page.locator(f"{CARD} .prep-chip:visible").all()] == ["Resume"]  # only what's kept
    assert "Jordan_Rivera_Resume_X.pdf" in shown(page.locator(CARD), "tailor").inner_text()
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
    assert "Tailoring needs resume-kit" in shown(card, "tailor").inner_text()
    assert "general resume" in shown(card, "ats").inner_text()
    assert "local model isn't running" in shown(card, "cover").inner_text()
    assert step_panel(card, "cover").locator("textarea").count() == 0
    assert steps == ["ats read resume.txt"]  # nothing was built or drafted
    assert card.get_by_role("button", name="Prepare again").is_enabled()
    assert page.errors == []


def test_a_step_that_fails_is_marked_and_the_next_one_still_runs(page, queued, steps, monkeypatch):
    def broken(path):
        raise ValueError("Can't read the PDF's text. Install poppler (`brew install poppler`) and press Prepare again.")
    monkeypatch.setattr(ats, "read_file", broken)
    card = page.locator(CARD)
    card.get_by_role("button", name="Prepare", exact=True).click()
    sync_api.expect(card.get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)
    states = chips(page)
    assert [s for s, _ in states] == ["ok", "err", "ok"], states
    assert states[1][1] == "ATS check failed"
    assert "brew install poppler" in shown(card, "ats").inner_text()  # the whole message is in the panel
    tip = card.locator('button.prep-chip[data-step="ats"]').get_attribute("title")
    assert "Can't read the PDF's text." in tip and "poppler" not in tip  # the tooltip has the first sentence only
    assert step_panel(card, "cover").locator("textarea").input_value().startswith("Hello Initech team,")


def test_the_company_page_card_has_the_same_one_button(page, queued):
    page.goto(f"http://127.0.0.1:{queued}/#company/Initech")
    card = page.locator(CARD)
    card.wait_for(timeout=15000)
    assert card.get_by_role("button", name="Prepare", exact=True).count() == 1
    for gone in ("Tailor resume", "ATS check", "Cover letter"):
        assert card.get_by_role("button", name=gone, exact=True).count() == 0, gone
    assert page.errors == []


# -- layout: one card with all three results beside ordinary ones --

OTHERS = ["greenhouse:acme:101", "lever:globex:aaaa-1111"]


@pytest.fixture
def crowd(browser, queued, steps, watchlist):
    """Three queued jobs (the Initech one that will carry Prepare results, two ordinary ones) and a page opener."""
    store = Store(config.load(watchlist).state)
    store.set_status(OTHERS, "queued", None)
    store.close()
    pages = []

    def open_queue(width: int):
        page = browser.new_page(viewport={"width": width, "height": 1100})
        pages.append(page)
        page.set_default_timeout(20000)
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{queued}/#queue")
        page.locator(CARD).wait_for(timeout=15000)
        sync_api.expect(page.locator(".card.job")).to_have_count(3)
        return page
    yield open_queue
    for p in pages:
        p.close()


def heights(page) -> dict[str, int]:
    return page.evaluate(
        "Object.fromEntries([...document.querySelectorAll('.card.job')].map(c => [c.id, c.offsetHeight]))")


def prepare(page):
    card = page.locator(CARD)
    card.get_by_role("button", name="Prepare", exact=True).click()
    sync_api.expect(card.get_by_role("button", name="Prepare again")).to_be_visible(timeout=60000)


def test_a_card_with_prepare_results_does_not_stretch_its_neighbours(crowd):
    page = crowd(1999)
    before = heights(page)
    prepare(page)
    card = page.locator(CARD)
    after = heights(page)
    # (a) the ordinary cards keep their own height, collapsed or with a panel open
    others = [k for k in before if k != f"job-{KEY}"]
    assert len(others) == 2
    for k in others:
        assert abs(after[k] - before[k]) <= 2, (k, before, after)
    # (b) folded away, the results add a row of chips, not a page
    own = f"job-{KEY}"
    assert after[own] - before[own] <= 120, (before, after)
    # (c) each chip opens its panel; one at a time; aria-expanded follows
    chip = lambda s: card.locator(f'button.prep-chip[data-step="{s}"]')  # noqa: E731
    assert [chip(s).get_attribute("aria-expanded") for s in ("tailor", "ats", "cover")] == ["false"] * 3
    chip("ats").click()
    assert chip("ats").get_attribute("aria-expanded") == "true"
    sync_api.expect(step_panel(card, "ats")).to_be_visible()
    assert chip("ats").get_attribute("aria-controls") == step_panel(card, "ats").get_attribute("id")
    chip("cover").click()
    assert [chip(s).get_attribute("aria-expanded") for s in ("tailor", "ats", "cover")] == ["false", "false", "true"]
    sync_api.expect(step_panel(card, "ats")).to_be_hidden()
    sync_api.expect(step_panel(card, "cover")).to_be_visible()
    cover = step_panel(card, "cover")
    assert cover.bounding_box()["height"] <= 322  # its own scroll, never the card's growth
    assert cover.locator("textarea").is_visible()
    for name in ("Draft another", "Copy"):
        assert cover.get_by_role("button", name=name, exact=True).is_visible()
    assert cover.get_by_role("combobox", name="Tone").is_visible() and cover.get_by_label("Emphasis").is_visible()
    opened = heights(page)
    assert opened[own] - before[own] <= 420, (before, opened)
    for k in others:
        assert abs(opened[k] - before[k]) <= 2, (k, before, opened)
    chip("cover").click()  # pressing the open chip folds it away
    assert chip("cover").get_attribute("aria-expanded") == "false"
    sync_api.expect(cover).to_be_hidden()
    # keyboard: Tab to a chip, Enter or Space opens it
    chip("ats").focus()
    page.keyboard.press("Enter")
    assert chip("ats").get_attribute("aria-expanded") == "true"
    page.keyboard.press("Space")
    assert chip("ats").get_attribute("aria-expanded") == "false"
    assert page.errors == []


@pytest.mark.parametrize("width", [1999, 1280])
def test_the_grid_never_scrolls_sideways_in_any_width_setting(crowd, width):
    page = crowd(width)
    prepare(page)
    card = page.locator(CARD)
    card.locator('button.prep-chip[data-step="cover"]').click()
    for setting in ("standard", "wide", "full"):
        page.evaluate("s => document.documentElement.dataset.width = s", setting)
        over = page.evaluate("""() => {
            const g = document.querySelector('.grid-cards'), edge = g.getBoundingClientRect().right;
            const right = Math.max(...[...g.children].map(c => c.getBoundingClientRect().right));
            return [document.documentElement.scrollWidth - innerWidth, g.scrollWidth - g.clientWidth, right - edge];
        }""")
        assert all(o <= 1 for o in over), (width, setting, over)
        assert page.locator(".card.job").count() == 3
    assert page.errors == []


def test_a_redraw_of_the_queue_keeps_the_open_panel_and_the_letter_being_edited(crowd):
    page = crowd(1280)
    prepare(page)
    card = page.locator(CARD)
    card.locator('button.prep-chip[data-step="cover"]').click()
    box = card.locator("textarea")
    box.fill("My own edit of the letter.")
    page.get_by_role("button", name="Worth it", exact=True).click()  # draws the cards again
    page.get_by_role("button", name="Oldest first", exact=True).click()
    card = page.locator(CARD)
    assert card.locator('button.prep-chip[data-step="cover"]').get_attribute("aria-expanded") == "true"
    assert card.locator("textarea").input_value() == "My own edit of the letter."
    assert card.get_by_role("button", name="Prepare again").is_enabled()
    assert page.errors == []
