"""Screenshots for the tutorial videos (scripts/tutorials/README.md), from made-up data only.

    python scripts/tutorials/shots.py OUT        # writes OUT/tut-shots/

The daily routine's screenshots come from scripts/demo (`screenshots.py --demo`); this makes first-run onboarding's
from an empty watchlist (made here, in OUT/empty), Settings' AI tab from the demo's watchlist (OUT/demo, seeded
first by make-tutorials), and the guide pages' (queue, applications, interviews, comps, referrals...) from
OUT/demo-more, the demo seeded with `--more`. Typed answers are made-up too. Nothing calls a
model or a job board: onboarding's "Suggest titles" is never pressed, and the chat shows a canned reply.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/: screenshots.py and demo/
from demo.seed import RESUME
from screenshots import DEMO_VIEW, canned_chat, hide_folder, open_tab, serving

EMPTY = """\
# jobwatch DEMO watchlist with no companies yet: opens first-run onboarding.
companies: []
filters:
  titles: []
display:
  theme: light
state: state/state.db
cache: cache
"""
ABOUT = "Senior software engineer. I want to build LLM products again, and I'd rather join a smaller company."


def seed_empty(folder: Path) -> Path:
    """A watchlist with nothing in it, in `folder` (made by this script, so replaced each time)."""
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / "jobwatch.yaml"
    config.write_text(EMPTY, encoding="utf-8")
    return config


def click(page, name: str, *, exact: bool = False):
    page.get_by_role("button", name=name, exact=exact).first.click(timeout=5000)
    page.wait_for_timeout(700)


def onboarding(config: Path, out: Path):
    """first-run.png (step 1), jobs.png, companies.png and ai.png (step 4, the AI tiles opened)."""
    canned_chat()
    with serving(config) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=DEMO_VIEW, color_scheme="light", device_scale_factor=2)
        open_tab(page, url, "today")
        page.get_by_placeholder("e.g. Staff engineer", exact=False).fill(ABOUT)
        page.get_by_placeholder("or paste the text of your resume", exact=False).fill(RESUME)
        page.screenshot(path=out / "first-run.png")
        click(page, "Save and continue")
        page.wait_for_timeout(600)
        page.screenshot(path=out / "jobs.png")
        click(page, "Skip for now")  # jobs: nothing typed that needs a model
        page.screenshot(path=out / "companies.png")
        click(page, "Skip for now")
        page.locator("summary", has_text="AI: fit scores").click(timeout=5000)
        page.wait_for_timeout(900)
        top_of(page, ".ai-tiles")
        page.screenshot(path=out / "ai.png")
        browser.close()


def top_of(page, selector: str, margin: int = 16):
    """Scroll so the element (a Playwright selector: CSS, or text=...) starts just under whatever stays stuck at the
    top (the header, a tab bar): the slides show the shot from its top."""
    page.locator(selector).first.evaluate("""(el, m) => {
        window.scrollBy(0, el.getBoundingClientRect().top);
        const stuck = [...document.querySelectorAll("body *")].filter(e => {
            const p = getComputedStyle(e).position, r = e.getBoundingClientRect();
            return (p === "sticky" || p === "fixed") && r.height > 0 && r.top < innerHeight / 3 &&
                r.height < innerHeight / 3;  // a bar stuck under the header counts too
        });
        window.scrollBy(0, -(Math.max(0, ...stuck.map(e => e.getBoundingClientRect().bottom)) + m));
    }""", margin)
    page.wait_for_timeout(400)


def settings_ai(config: Path, out: Path):
    """ai-settings.png: Settings' AI tab with the demo's watchlist, the three tiles in a row and the fallback chain."""
    with serving(config) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=DEMO_VIEW, color_scheme="light", device_scale_factor=2)
        open_tab(page, url, "settings/ai")
        page.wait_for_selector(".ai-tile .state.ready, .ai-tile .state.setup", timeout=10000)
        top_of(page, ".ai-tiles")
        page.screenshot(path=out / "ai-settings.png")
        browser.close()


def card_of(page, company: str):
    """The application or job card for this company on the page."""
    return page.locator(".card", has_text=company).first


def guide(config: Path, out: Path):
    """The guide pages' tabs, from the demo seeded with --more (comps, contacts, interviews, a saved package...):
    queue*.png, applied*.png, suggest.png, interviews.png, company.png, sent.png, prep*.png, comps.png and
    referrals.png. Nothing is typed that needs a model, and the chat is canned."""
    canned_chat()
    with serving(config) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=DEMO_VIEW, color_scheme="light", device_scale_factor=2)

        def go(tab: str):
            open_tab(page, url, tab)
            hide_folder(page, config.parent)

        def snap(name: str):
            page.screenshot(path=out / f"{name}.png")

        go("queue")
        snap("queue")
        go("queue")
        click(page, "Add a job")
        page.get_by_placeholder("Company", exact=True).fill("Umbrella")
        page.get_by_placeholder("Job title", exact=True).fill("Staff Engineer")
        snap("queue-add")
        go("applied")
        click(page, "Add an application")
        page.get_by_placeholder("Company", exact=True).fill("Umbrella")
        page.get_by_placeholder("Job title", exact=True).fill("Principal Engineer")
        snap("applied-add")
        go("today")
        page.locator(".panel", has_text="Companies to watch").last.screenshot(path=out / "suggest.png")

        go("applied")
        snap("applied")
        click(page, "Table")
        snap("applied-table")
        click(page, "Cards")  # the page remembers the choice
        go("applied")
        top_of(page, ".card:has-text('Soylent')", margin=60)  # the quiet one, and the group's heading above it
        snap("applied-quiet")
        go("interviews")
        snap("interviews")
        go("today")
        page.locator("#jump").fill("initech")
        page.wait_for_timeout(800)
        snap("company-search")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
        snap("company")

        go("applied")
        card_of(page, "Initech").get_by_role("button", name="Details").click(timeout=5000)
        page.wait_for_timeout(900)
        top_of(page, "text=What you sent")
        snap("sent")
        page.get_by_role("button", name="Prep sheet").first.click(timeout=5000)
        page.wait_for_timeout(1200)
        snap("prep")
        page.get_by_role("heading", name="Practised answers").scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(500)
        snap("prep-practised")

        go("comps")
        snap("comps")
        top_of(page, "text=Include applications still at applied")
        snap("comps-table")
        go("referrals")
        snap("referrals")
        browser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, nargs="?", default=Path(__file__).resolve().parent.parent / "demo" / "out")
    args = ap.parse_args()
    out = args.out.expanduser().resolve()
    shots = out / "tut-shots"
    shots.mkdir(parents=True, exist_ok=True)
    onboarding(seed_empty(out / "empty"), shots)
    settings_ai(out / "demo" / "jobwatch.yaml", shots)  # the demo's, seeded by make-tutorials
    guide(out / "demo-more" / "jobwatch.yaml", shots)   # and the one with the tutorials' extras (seed.py --more)
    print(f"Wrote the tutorials' screenshots to {shots}")


if __name__ == "__main__":
    main()
