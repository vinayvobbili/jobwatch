"""Screenshots for the tutorial videos (scripts/tutorials/README.md), from made-up data only.

    python scripts/tutorials/shots.py OUT        # writes OUT/tut-shots/

The daily routine's screenshots come from scripts/demo (`screenshots.py --demo`); this makes first-run onboarding's
from an empty watchlist (made here, in OUT/empty). Typed answers are made-up too. Nothing calls a
model or a job board: onboarding's "Suggest titles" is never pressed, and the chat shows a canned reply.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/: screenshots.py and demo/
from demo.seed import RESUME
from screenshots import DEMO_VIEW, canned_chat, open_tab, serving

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
        page.screenshot(path=out / "ai.png")
        browser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, nargs="?", default=Path(__file__).resolve().parent.parent / "demo" / "out")
    args = ap.parse_args()
    out = args.out.expanduser().resolve()
    shots = out / "tut-shots"
    shots.mkdir(parents=True, exist_ok=True)
    onboarding(seed_empty(out / "empty"), shots)
    print(f"Wrote the tutorials' screenshots to {shots}")


if __name__ == "__main__":
    main()
