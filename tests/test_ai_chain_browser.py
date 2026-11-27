"""Settings > AI & fit scores shows the scoring chain in the order a job meets it: a dated Claude step (an API credit
that ends) scores first wherever the watchlist lists it, so it's step 1 with the "Scores first" tag, as
`jobwatch scorers` lists it, and Save writes it back where it was. Skipped where Playwright or its browser isn't
installed."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import json
import re
from datetime import UTC, datetime

import pytest
import yaml

from jobwatch import config
from jobwatch.store import Store

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


PROVIDER = "providers:\n    globex-ai: {url: 'https://api.globex.example/v1'}\n"


def _scored(watchlist, who, n):
    """`n` scores made just now by `who` ("backend:model"), for the counts on the cards."""
    store = Store(config.load(watchlist).state)
    try:
        with store.db:
            for i in range(n):
                store.db.execute("INSERT INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                                 (f"{who}-{i}", "cv.md:1", json.dumps({"score": 70, "scored_by": who}),
                                  datetime.now(UTC).isoformat()))
    finally:
        store.close()


def test_each_provider_shows_its_usage_cost_and_role_on_its_own_card_and_the_fit_scoring_section_is_gone(
        page, watchlist):
    watchlist.write_text(watchlist.read_text() + SCORING.replace("  credit:", "  " + PROVIDER + "  credit:")
                         .replace("  - agy:gemini-4-neon-high", "  - agy:gemini-4-neon-high\n  - globex-ai:big-model"))
    for who, n in [("claude:claude-sonnet-5-5", 3), ("agy:gemini-4-hydrogen-high", 2), ("local:tiny", 1),
                   ("globex-ai:big-model", 4)]:
        _scored(watchlist, who, n)
    page.goto(page.url.split("#")[0] + "#settings/ai")
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".ai-tile .use").first).to_be_visible(timeout=10000)

    def card(backend):
        return page.locator(f".ai-tile:has(.use[data-backend='{backend}'])")

    def counts(backend):
        return [s.replace("\n", " ") for s in card(backend).locator(".use-counts div").all_inner_texts()]

    assert counts("claude") == ["3 Today", "3 Last 7 days", "3 This month"]
    assert counts("agy") == ["2 Today", "2 Last 7 days", "2 This month"]
    assert counts("local") == ["1 Today", "1 Last 7 days", "1 This month"]
    assert counts("globex-ai") == ["4 Today", "4 Last 7 days", "4 This month"]
    sync_api.expect(card("claude").locator(".use-head .chip")).to_have_text("main")
    sync_api.expect(card("agy").locator(".use-head .chip")).to_have_text("fallback")
    sync_api.expect(card("globex-ai").locator(".use-head .chip")).to_have_text("fallback")
    sync_api.expect(card("claude").locator(".use-price")).to_contain_text("this month")
    sync_api.expect(card("claude").locator(".use-notes")).to_contain_text("Batch runs are priced at half")
    sync_api.expect(card("agy").locator(".use-price")).to_have_text("covered by subscription")
    sync_api.expect(card("local").locator(".use-price")).to_have_text("$0 (runs on this computer)")
    sync_api.expect(card("globex-ai")).to_have_class(re.compile(r"\bcompact\b"))
    strip = page.locator(".use-strip")
    sync_api.expect(strip).to_contain_text("Scores in this order")
    sync_api.expect(strip).to_contain_text("Claude API · Sonnet 5.5 → Antigravity")  # the chain as it runs
    sync_api.expect(strip).to_contain_text("Batches API (half price): off")
    sync_api.expect(strip).to_contain_text("Auto: ")
    sync_api.expect(strip).to_contain_text("Background scoring")
    # the section that held these as tiles and a table is gone
    sync_api.expect(page.locator("#set-usage")).to_have_count(0)
    sync_api.expect(page.get_by_text("Fit scoring")).to_have_count(0)
    sync_api.expect(page.locator("table.use, .use-tiles, .use-cost")).to_have_count(0)
    assert page.errors == []


def test_the_batches_switch_follows_the_chain_not_scoring_backend_and_says_the_score_button_stays_instant(
        chain, watchlist):
    box = chain.get_by_label(re.compile("Half price for background scoring"))
    sync_api.expect(box).to_be_enabled()  # Claude scores first through the dated step, though scoring.backend is agy
    sync_api.expect(chain.locator("label", has_text="Half price for background scoring")).to_contain_text(
        "The Score button stays instant")
    box.check()
    chain.get_by_role("button", name="Save settings").first.click()
    sync_api.expect(chain.locator(".snav [role=status]")).to_have_text("Saved.", timeout=10000)
    saved = yaml.safe_load(watchlist.read_text())["scoring"]
    assert saved["batch_api"] is True and saved["backend"] == "agy"
    assert config.load(watchlist).score_batch_api is True
    # Claude no longer first (a step moved ahead of it is not possible past a dated one; take it out): switch goes off
    chain.locator(".ai-chain .step").nth(0).get_by_role("button", name="Take it out").click()
    sync_api.expect(box).to_be_disabled()
    sync_api.expect(chain.locator("label", has_text="Half price for background scoring")).to_contain_text(
        "only when Claude API scores first")
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
