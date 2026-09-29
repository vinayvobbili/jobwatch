"""Screenshot every tab of `jobwatch ui`, light and dark, desktop and phone width, to check how the page looks.

    pip install playwright && python -m playwright install chromium
    python scripts/screenshots.py -c path/to/jobwatch.yaml -o shots/

Opening Today marks its new jobs as seen, as in the browser: point -c at a copy of your watchlist (with its own
`state:`) to keep your real history as it is.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from jobwatch import chat
from jobwatch.web import serve

SIZES = {"wide": (1920, 1080), "desktop": (1280, 900), "phone": (390, 844)}
TABS = ("today", "queue", "applied", "settings")

# The chat scenes show this canned reply: screenshots never call a model.
CANNED = ("Three stand out:\n\n1. **The best fit** matches most of your must-haves.\n"
          "2. **The newest** was posted this week, so apply early.\n3. **The best-paid** lists the highest range.\n\n"
          "Want me to compare their gaps with your resume?")


def canned_chat():
    def reply(backend, system, messages):
        for word in CANNED.split(" "):
            yield word + " "
    chat.check = lambda backend: None
    chat.reply = reply


def ask_first_suggestion(page, open_with: str | None):
    """Open a chat with this button, click its first suggested question and wait for the reply."""
    if open_with:
        page.get_by_role("button", name=open_with).first.click(timeout=5000)
    page.locator(".suggest button").first.click(timeout=5000)
    page.wait_for_function("document.querySelectorAll('.msg.bot').length && !document.querySelector('.send.stop')",
                           timeout=10000)
    page.wait_for_timeout(400)


def shoot(config: Path, out: Path, themes=("light", "dark"), sizes=tuple(SIZES), full_page: bool = True):
    out.mkdir(parents=True, exist_ok=True)
    canned_chat()
    server = serve(config, port=0, open_browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for theme in themes:
                for size in sizes:
                    w, h = SIZES[size]
                    page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=theme,
                                            device_scale_factor=2 if size == "phone" else 1)
                    errors = []
                    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                    for tab in TABS:
                        page.goto(f"{url}#{tab}")
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(1200)  # let entrance animations settle
                        page.screenshot(path=out / f"{tab}-{theme}-{size}.png", full_page=full_page)
                    # The dialogs and forms that only open on a click.
                    for tab, button, name in (("applied", "Add an application", "applied-add"),
                                              ("today", "Details", "details")):
                        page.goto(f"{url}#{tab}")
                        try:
                            page.get_by_role("button", name=button).first.click(timeout=5000)
                        except PlaywrightTimeout:
                            continue  # nothing to open, e.g. no jobs today
                        page.wait_for_timeout(600)
                        page.screenshot(path=out / f"{name}-{theme}-{size}.png")
                    # Chat: Today's floating panel, then the column in a job's details, each after one question.
                    for name, button in (("chat-home", "Ask jobwatch"), ("chat-job", "Details")):
                        page.goto("about:blank")  # a fresh page: the same URL again would keep a dialog open
                        page.goto(f"{url}#today")
                        try:
                            ask_first_suggestion(page, button)
                        except PlaywrightTimeout as e:
                            print(f"{theme}/{size}: skipped {name}: {e.message.splitlines()[0]}")
                            continue
                        page.screenshot(path=out / f"{name}-{theme}-{size}.png")
                    for e in errors:
                        print(f"{theme}/{size}: page error: {e}")
                    page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"Wrote screenshots to {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, default=Path("shots"))
    ap.add_argument("--theme", choices=["light", "dark"], action="append")
    ap.add_argument("--size", choices=list(SIZES), action="append")
    ap.add_argument("--viewport", action="store_true", help="only the visible part, not the whole page")
    args = ap.parse_args()
    shoot(args.config, args.out, tuple(args.theme or ("light", "dark")), tuple(args.size or SIZES),
          full_page=not args.viewport)


if __name__ == "__main__":
    main()
