"""Screenshot a static site (a folder with index.html) at 1440px and 375px, with the settings popover open.

    python scripts/site_shots.py SITE_DIR OUT_DIR [PREFIX]

Writes PREFIX-{1440,375}-hero.png, PREFIX-{1440,375}-popover.png and PREFIX-{1440,375}-tile.png (when a .tile exists),
and prints the horizontal overflow at each width (0 means none). Needs playwright (pip install playwright).
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

WIDTHS = {1440: 900, 375: 800}


def shoot(site: Path, out: Path, prefix: str = "site") -> dict[str, int]:
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    out.mkdir(parents=True, exist_ok=True)
    overflow = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in WIDTHS.items():
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url)
                page.wait_for_timeout(1000)  # let the rise-in animations finish
                page.screenshot(path=str(out / f"{prefix}-{width}-hero.png"))
                overflow[str(width)] = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                if page.locator(".tile").count():
                    page.locator(".tiles").first.screenshot(path=str(out / f"{prefix}-{width}-tile.png"))
                page.click("#gear")
                page.wait_for_timeout(400)
                page.screenshot(path=str(out / f"{prefix}-{width}-popover.png"))
                page.keyboard.press("Escape")
                assert page.get_attribute("#gear", "aria-expanded") == "false"
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return overflow


if __name__ == "__main__":
    site, out = Path(sys.argv[1]), Path(sys.argv[2])
    print(shoot(site, out, sys.argv[3] if len(sys.argv) > 3 else "site"))
