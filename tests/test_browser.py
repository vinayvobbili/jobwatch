"""The page in a real browser (headless Chromium through Playwright), as a person uses it: every tab opens without
a script error, and pressing Save in Settings writes the watchlist back as it was. Skipped where Playwright or its
browser isn't installed (`pip install -e ".[browser]"` then `playwright install chromium`)."""

import pytest
import yaml

from jobwatch import config

sync_api = pytest.importorskip("playwright.sync_api")

TABS = ["today", "interviews", "queue", "applied", "comps", "referrals", "skills", "activity", "settings"]
# Patterns with commas of their own, and a place with one: the Settings boxes once split all three at the comma.
FILTERS = {
    "titles": ["engineer", "developer"],
    "exclude_titles": ["contract"],
    "exclude_text": [r"\b(must|need to) be an? U\.?S\.? citizen\b(?![^.\n]{0,40}\bgreen card)",
                     r"\b0\s*[-–]\s*2 years of experience\b"],
    "locations": ["remote", "Boulder, CO"],
    "max_age_days": 30,
}


@pytest.fixture
def watchlist(tmp_path):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({
        "companies": ["greenhouse:acme", "lever:globex"], "filters": FILTERS,
        "keywords": {"Python": 2, "LLM": 3}, "state": "state.db", "cache": "cache"}))
    return path


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
def page(browser, server):
    """The page, open on Today; `page.errors` collects script errors and failed requests from then on. A company
    with no logo is a 404 by design (the page shows its initials), so those don't count."""
    page = browser.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("response", lambda r: r.status >= 400 and "/logo/" not in r.url and
            page.errors.append(f"{r.status} {r.url}"))
    page.goto(f"http://127.0.0.1:{server}/#today")
    page.wait_for_load_state("networkidle")
    yield page
    page.close()


def test_every_tab_opens_without_a_script_error(page):
    for tab in TABS:
        page.locator(f'nav [data-tab="{tab}"], [data-tab="{tab}"]').first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)
    assert page.errors == []


def test_saving_settings_writes_the_watchlist_back_as_it_was(page, watchlist):
    before = config.load(watchlist).filters
    page.goto(page.url.split("#")[0] + "#settings/search")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Save settings").first.click()
    status = page.locator(".snav [role=status]")
    sync_api.expect(status).to_have_text("Saved.", timeout=10000)
    assert config.load(watchlist).filters == before
    saved = yaml.safe_load(watchlist.read_text())["filters"]
    assert {k: saved[k] for k in FILTERS} == FILTERS
    assert page.errors == []
