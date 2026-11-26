"""The Who to contact block on a job's card, in a real browser: it lists the people the posting names and the people you
know there, with LinkedIn searches to open, and drafts a note you can copy (a LinkedIn note within 300 characters and
an email). Nothing is sent. Skipped where Playwright or its browser isn't installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import re

import pytest

from jobwatch import chat, config
from jobwatch.store import Store

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)

POSTING = """Platform Engineer at Initech.

Hiring Manager: Jane Okafor, Director of Platform
Recruiter: Sam Lee <sam.lee@initech.example>

You will build the platform. Python and AWS in production.
"""


@pytest.fixture
def queued(watchlist, page, monkeypatch):
    """A queued job whose posting names two people, no model running, and the Queue tab open on it."""
    def down(*a):
        raise chat.ChatUnavailable("no model in tests")

    monkeypatch.setattr(chat, "check", down)
    (watchlist.parent / "Connections.csv").write_text(
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Ana,Li,https://www.linkedin.com/in/example-ana,,Initech,Staff Engineer,01 Jan 2024\n")
    config.save(watchlist, {"connections": "Connections.csv"})
    store = Store(config.load(watchlist).state)
    job = store.add("Initech", "Platform Engineer", status="queued", description=POSTING)
    store.close()
    page.goto(page.url.split("#")[0] + "#queue")
    page.wait_for_load_state("networkidle")
    return job


def test_the_block_lists_people_and_searches_and_drafts_a_note_to_copy(page, queued):
    card = page.locator(f'[id="job-{queued.key}"]')
    sync_api.expect(card).to_be_visible()
    card.get_by_role("button", name="Who to contact").click()
    block = card.locator(".who")
    sync_api.expect(block.locator(".who-person").first).to_contain_text("Jane Okafor")
    sync_api.expect(block.locator(".who-person").first).to_contain_text("Hiring manager")
    sync_api.expect(block.locator(".who-person").nth(1)).to_contain_text("Sam Lee")
    sync_api.expect(block.locator(".who-person", has_text="Ana Li")).to_contain_text("you know them")
    links = block.locator(".who-search a")
    sync_api.expect(links).to_have_count(4)
    assert all("linkedin.com/search/results/people" in (links.nth(i).get_attribute("href") or "") for i in range(4))
    assert block.locator("textarea").count() == 0   # nothing is drafted until asked

    block.get_by_role("button", name="Write a note to Jane").click()
    note = block.locator("textarea.who-linkedin")
    sync_api.expect(note).to_have_value(re.compile(r"^Hi Jane, .*short chat about the role\?$"))
    assert len(note.input_value()) <= 300
    sync_api.expect(block.locator(".who-count")).to_contain_text("/300")
    sync_api.expect(block.locator("input.who-subject")).to_have_value("The Platform Engineer role at Initech")
    sync_api.expect(block.locator("textarea.who-body")).to_have_value(re.compile(r"^Hi Jane,"))
    sync_api.expect(block.locator(".problems")).to_contain_text("fixed template")
    sync_api.expect(block.get_by_text("A draft: read it and send it yourself.")).to_be_visible()

    block.get_by_role("button", name="Write a note to Ana").click()
    sync_api.expect(block.locator("textarea.who-linkedin")).to_have_value(
        re.compile(r"Hi Ana, I found the Platform Engineer role at Initech and thought of you.*refer me"))
    assert page.errors == []


def test_the_block_says_when_nothing_names_anyone_and_offers_the_searches(page, watchlist):
    store = Store(config.load(watchlist).state)
    job = store.add("Umbrella", "Data Analyst", status="queued", description="Analyze data. No names here.")
    store.close()
    page.goto(page.url.split("#")[0] + "#queue")
    page.wait_for_load_state("networkidle")
    card = page.locator(f'[id="job-{job.key}"]')
    card.get_by_role("button", name="Who to contact").click()
    sync_api.expect(card.locator(".who")).to_contain_text("No one is named")
    sync_api.expect(card.locator(".who-search a")).to_have_count(4)
    assert page.errors == []
