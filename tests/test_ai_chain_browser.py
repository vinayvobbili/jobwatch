"""Settings > AI & fit scores shows the scoring chain in the order a job meets it: a dated Claude step (an API credit
that ends) scores first wherever the watchlist lists it, so it's step 1 with the "Scores first" tag, as
`jobwatch scorers` lists it, and Save writes it back where it was. Skipped where Playwright or its browser isn't
installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import pytest
import yaml

from jobwatch import config

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)

SCORING = """scoring:
  backend: agy
  model: claude-sonnet-5-5-high
  fallback:
  - claude:claude-sonnet-5-5 until 2026-12-20
  - agy:gemini-4-hydrogen-high
  - agy:gemini-4-neon-high
  credit: {daily_usd: 5, total_usd: 85}
"""


@pytest.fixture
def chain(page, watchlist):
    """The AI settings, open on a chain whose dated Claude entry is listed after scoring.backend (agy)."""
    watchlist.write_text(watchlist.read_text() + SCORING)
    page.goto(page.url.split("#")[0] + "#settings/ai")
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".ai-chain .step").first).to_be_visible(timeout=10000)
    return page


def test_the_dated_claude_step_is_first_and_carries_the_scores_first_tag(chain):
    steps = chain.locator(".ai-chain .step")
    sync_api.expect(steps).to_have_count(4)
    assert [s.split("\n")[0] for s in steps.all_inner_texts()] == ["1", "2", "3", "4"]
    sync_api.expect(steps.nth(0)).to_contain_text("Claude API")
    sync_api.expect(steps.nth(0)).to_have_class("link step main")
    sync_api.expect(steps.nth(1)).to_contain_text("Antigravity")
    sync_api.expect(chain.locator(".ai-tile .main-tag")).to_have_count(1)
    sync_api.expect(chain.locator(".ai-tile.on")).to_contain_text("Claude API")
    sync_api.expect(chain.locator(".ai-tile.on .main-tag")).to_have_text("Scores first")
    assert chain.errors == []


def test_a_dated_step_stays_first_and_the_step_after_it_cannot_move_ahead_of_it(chain):
    steps = chain.locator(".ai-chain .step")
    sync_api.expect(steps.nth(0).get_by_role("button", name="Try it earlier")).to_be_disabled()
    sync_api.expect(steps.nth(0).get_by_role("button", name="Try it later")).to_be_disabled()
    sync_api.expect(steps.nth(1).get_by_role("button", name="Try it earlier")).to_be_disabled()
    sync_api.expect(steps.nth(2).get_by_role("button", name="Try it earlier")).to_be_enabled()
    assert chain.errors == []


def test_saving_keeps_the_dated_entry_in_fallback_and_agy_as_the_backend(chain, watchlist):
    chain.get_by_role("button", name="Save settings").first.click()
    sync_api.expect(chain.locator(".snav [role=status]")).to_have_text("Saved.", timeout=10000)
    saved = yaml.safe_load(watchlist.read_text())["scoring"]
    assert saved["backend"] == "agy" and saved["model"] == "claude-sonnet-5-5-high"
    assert saved["fallback"] == ["claude:claude-sonnet-5-5 until 2026-12-20", "agy:gemini-4-hydrogen-high",
                                 "agy:gemini-4-neon-high"]
    assert saved["credit"] == {"daily_usd": 5, "total_usd": 85}
    assert config.load(watchlist).score_fallback[0].endswith("until 2026-12-20")
    assert chain.errors == []
