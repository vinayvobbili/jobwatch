"""Screenshots of the side panel for each page it leads with, in light and dark, narrow and wide.

    python chrome-extension/tools/panel_states.py --out DIR

Runs the demo stack (see harness.py): the fake jobwatch with its made-up details and Chromium with the extension
loaded, one tab per kind of page (an application form, a LinkedIn conversation, a LinkedIn list of jobs, a job
posting, a page with nothing to do), and the panel pinned to each. Also the panel with jobwatch missing, and the
settings page. Nothing real is shown: Jordan Rivera, Initech, Dana Whitfield.

Needs Playwright with Chromium.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import harness

NARROW, WIDE, HEIGHT = 340, 640, 760
THEMES = ("light", "dark")

# (name, host, path): the demo site serves these addresses (harness.ROUTES); a posting is only an address to the panel
PAGES = [
    ("form", "job-boards.greenhouse.io", "/initech/jobs/4001"),
    ("thread", "www.linkedin.com", "/messaging/thread/2-abc/"),
    ("list", "www.linkedin.com", "/jobs/collections/recommended"),
    ("posting", "jobs.lever.co", "/initech/6f1b2c"),
    ("idle", None, "/generic.html"),
]


def capture(out_dir: Path, headless: bool = True, playwright=None) -> list[Path]:
    """Write one image per page kind, theme and width into `out_dir`; returns their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if playwright is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return capture(out_dir, headless, pw)
    written: list[Path] = []
    with harness.demo_stack(playwright, headless) as stack:
        stack.server.features = ["posting", "reply", "import-list", "ats", "cover", "list-ladders"]
        options = stack.extension_page("options.html")
        options.evaluate("() => chrome.storage.local.set({ passiveSeen: Object.fromEntries("
                         "[...Array(7).keys()].map((i) => ['job-' + i, { company: 'Initech' }])) })")
        pages = []
        for name, host, path in PAGES:
            url = stack.url(host, path) if host else f"http://127.0.0.1:{stack.site_port}{path}"
            page = stack.context.new_page()
            page.goto(url)
            pages.append((name, url, page))

        def shoot(name, url, theme, width):
            panel = harness.side_panel(stack, url)
            panel.emulate_media(color_scheme=theme)
            panel.set_viewport_size({"width": width, "height": HEIGHT})
            panel.wait_for_selector("#lead", timeout=20000)
            panel.wait_for_timeout(700)  # cards rise in; let them settle
            target = out_dir / f"panel-{name}-{theme}-{'wide' if width == WIDE else 'narrow'}.png"
            panel.screenshot(path=str(target))
            panel.close()
            written.append(target)

        for name, url, _ in pages:
            for theme in THEMES:
                shoot(name, url, theme, NARROW)
            shoot(name, url, "light", WIDE)

        # jobwatch not running: today's behaviour, a note under the wordmark and no buttons
        harness.pair(stack, stack.api_url, "")
        panel = harness.side_panel(stack, pages[0][1])
        panel.set_viewport_size({"width": NARROW, "height": 420})
        panel.wait_for_selector("#pair.warn", timeout=20000)
        panel.wait_for_timeout(500)
        panel.screenshot(path=str(out_dir / "panel-not-paired-light-narrow.png"))
        written.append(out_dir / "panel-not-paired-light-narrow.png")
        panel.close()
        harness.pair(stack, stack.api_url, harness.TOKEN)

        options.set_viewport_size({"width": 760, "height": 640})
        options.reload()
        options.wait_for_selector("#theme")
        options.wait_for_timeout(500)
        options.screenshot(path=str(out_dir / "options-light.png"))
        written.append(out_dir / "options-light.png")
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--headed", action="store_true", help="show the browser while capturing")
    args = parser.parse_args(argv)
    for path in capture(args.out, headless=not args.headed):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
