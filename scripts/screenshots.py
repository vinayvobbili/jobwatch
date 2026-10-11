"""Screenshot every tab of `jobwatch ui`, light and dark, desktop and phone width, to check how the page looks.

    pip install playwright && python -m playwright install chromium
    python scripts/screenshots.py -c path/to/jobwatch.yaml -o shots/
    python scripts/screenshots.py -c path/to/jobwatch.yaml -o shots/ --tab settings --size laptop --size phone

Settings is also taken with every fold open (settings-open-*.png), then saved unchanged: a save the page refuses
is reported, as is a page that scrolls sideways. --pages takes each tab a screen at a time as well, for reading
a long phone page.

Opening Today marks its new jobs as seen, as in the browser: point -c at a copy of your watchlist (with its own
`state:`) to keep your real history as it is.

--demo takes the README demo video's scenes instead (see scripts/demo/README.md): one light page, 1280 px wide
at 2x, named for the slides that use them (today.png, chat.png, prep.png, ...).

The chat scenes show a canned reply (--reply FILE for your own): screenshots never call a model, and never
check the boards.
"""

from __future__ import annotations

import argparse
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from jobwatch import chat
from jobwatch.web import serve

SIZES = {"ultrawide": (2560, 1440), "wide": (1920, 1080), "laptop": (1600, 1000), "desktop": (1280, 900),
         "phone": (390, 844)}
TABS = ("today", "queue", "applied", "skills", "settings")
DEMO_VIEW = {"width": 1280, "height": 760}  # the demo's slides show it 1200 px wide, cropped from the top

CANNED = ("Three stand out:\n\n1. **The best fit** matches most of your must-haves.\n"
          "2. **The newest** was posted this week, so apply early.\n3. **The best-paid** lists the highest range.\n\n"
          "Want me to compare their gaps with your resume?")


def canned_chat(text: str = CANNED):
    """Answer every chat with `text`, streamed a word at a time as a model would."""
    def reply(backend, system, messages, **settings):
        for word in text.split(" "):
            yield word + " "
    chat.check = lambda backend: None
    chat.reply = reply


@contextmanager
def serving(config: Path):
    """`jobwatch ui` for this watchlist on a free port, without opening a browser: yields its URL."""
    server = serve(config, port=0, open_browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def open_tab(page, url: str, tab: str, settle: int = 1200):
    page.goto("about:blank")  # a fresh page each time: the last form or dialog stays open otherwise
    page.goto(f"{url}#{tab}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(settle)  # let entrance animations settle


def fill_package(page):
    """Open the first application's details, attach a sample resume and save one answer, as a person would."""
    page.get_by_role("button", name="Details").first.click(timeout=5000)
    page.locator(".sent input[type=file]").set_input_files(
        {"name": "Resume_Sample.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 sample"}, timeout=5000)
    page.locator(".file").first.wait_for(timeout=5000)
    page.locator(".sent-head button").click()
    page.locator(".qa-edit input").first.fill("Salary expectation")
    page.locator(".qa-edit textarea").first.fill("Open, based on the full package")
    page.get_by_role("button", name="Save", exact=True).click()
    page.locator(".qa dt").first.wait_for(timeout=5000)
    page.wait_for_timeout(400)


def ask_first_suggestion(page, open_with: str | None):
    """Open a chat with this button, click its first suggested question and wait for the reply."""
    if open_with:
        page.get_by_role("button", name=open_with).first.click(timeout=5000)
    page.locator(".suggest button").first.click(timeout=5000)
    page.wait_for_function("document.querySelectorAll('.msg.bot').length && !document.querySelector('.send.stop')",
                           timeout=10000)
    page.wait_for_timeout(400)


def hide_folder(page, folder: Path):
    """Show paths in the watchlist's folder as ~/..., not wherever it happens to live."""
    page.evaluate("""p => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (w.nextNode()) if (w.currentNode.nodeValue.includes(p))
          w.currentNode.nodeValue = w.currentNode.nodeValue.replaceAll(p, '~/'); }""", str(folder) + os.sep)


def screens(page, out: Path, name: str, most: int = 12):
    """The page a screen at a time, scrolled as a person would (name-p1.png, -p2...): a long phone page is too tall
    to read as one picture. Sticky bars show on each, as they do on the phone."""
    tall = page.evaluate("document.documentElement.scrollHeight")
    high = page.viewport_size["height"]
    for n in range(min(most, -(-tall // high))):
        page.evaluate(f"window.scrollTo(0, {n * high})")
        page.wait_for_timeout(150)
        page.screenshot(path=out / f"{name}-p{n + 1}.png")
    page.evaluate("window.scrollTo(0, 0)")


def save_unchanged(page) -> str:
    """Press Save on Settings without changing anything, as a check that what the page shows saves as it is:
    "" when it did, else what the page said."""
    page.locator(".snav .btn.primary").click(timeout=5000)
    page.wait_for_function("!['', 'Saving…'].includes(document.querySelector('.snav span[role=status]').textContent)",
                           timeout=10000)
    said = page.locator(".snav span[role=status]").text_content()
    return "" if said == "Saved." else said


def sideways(page) -> int:
    """How far the page scrolls sideways: 0 when it fits the window, as it must on a phone."""
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


# The dialogs and forms that only open on a click (or a few, in order): (tab, buttons, name).
CLICKS = (("applied", ("Add an application",), "applied-add"),
          ("applied", ("Table",), "applied-table"),
          ("today", ("Show all",), "today-all"),
          ("today", ("Show all", "Next →"), "today-page2"),
          ("today", ("Details",), "details"))
# Settings with its folded editors open (the prompts, the IMAP account), the whole page.
SETTINGS_OPEN = "for (const d of document.querySelectorAll('main details')) d.open = true"


def shoot(config: Path, out: Path, themes=("light", "dark"), sizes=tuple(SIZES), full_page: bool = True,
          reply: str = CANNED, tabs=TABS, pages: bool = False):
    """Each of `tabs` in each theme and size, with the dialogs, forms and chats that open on those tabs.
    pages: each tab a screen at a time as well (see screens)."""
    out.mkdir(parents=True, exist_ok=True)
    folder = config.expanduser().resolve().parent
    canned_chat(reply)
    with serving(config) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in themes:
            for size in sizes:
                w, h = SIZES[size]
                page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=theme,
                                        device_scale_factor=2 if size == "phone" else 1)
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                for tab in tabs:
                    page.goto(f"{url}#{tab}")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1200)  # let entrance animations settle
                    hide_folder(page, folder)
                    page.screenshot(path=out / f"{tab}-{theme}-{size}.png", full_page=full_page)
                    if pages:
                        screens(page, out, f"{tab}-{theme}-{size}")
                    if wide := sideways(page):
                        print(f"{theme}/{size}: {tab} scrolls sideways by {wide}px")
                    if tab == "settings":
                        page.evaluate(SETTINGS_OPEN)
                        page.wait_for_timeout(300)
                        page.screenshot(path=out / f"settings-open-{theme}-{size}.png", full_page=full_page)
                        if said := save_unchanged(page):
                            print(f"{theme}/{size}: saving Settings as they are said: {said}")
                for tab, buttons, name in CLICKS:
                    if tab not in tabs:
                        continue
                    open_tab(page, url, tab, settle=0)
                    try:
                        for button in buttons:
                            page.get_by_role("button", name=button).first.click(timeout=5000)
                    except PlaywrightTimeout:
                        continue  # nothing to open, e.g. no jobs today, or no more than today's picks
                    page.wait_for_timeout(600)
                    page.screenshot(path=out / f"{name}-{theme}-{size}.png")
                # What you sent, on an application's page: attach a file and save an answer through the page.
                if "applied" in tabs:
                    open_tab(page, url, "applied", settle=0)
                    try:
                        fill_package(page)
                        page.screenshot(path=out / f"applied-sent-{theme}-{size}.png")
                    except PlaywrightTimeout as e:
                        print(f"{theme}/{size}: skipped applied-sent: {e.message.splitlines()[0]}")
                # Chat: Today's floating panel, then the column in a job's details, each after one question.
                for name, button in (("chat-home", "Ask jobwatch"), ("chat-job", "Details")) if "today" in tabs else ():
                    open_tab(page, url, "today", settle=0)
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
    print(f"Wrote screenshots to {out}")


def demo(config: Path, out: Path, reply: str = CANNED):
    """The demo video's scenes, from the seeded demo watchlist (scripts/demo/seed.py): every tab, a job's details,
    the chat after one question, and the interviewing application's prep sheet."""
    out.mkdir(parents=True, exist_ok=True)
    config = config.expanduser().resolve()
    canned_chat(reply)
    with serving(config) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=DEMO_VIEW, color_scheme="light", device_scale_factor=2)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for tab in ("settings", "today", "queue", "applied", "skills"):
            open_tab(page, url, tab)
            if tab == "settings":
                hide_folder(page, config.parent)
            page.screenshot(path=out / f"{tab}.png")

        open_tab(page, url, "today")  # the top job's details: fit score, gaps, skills
        page.get_by_role("button", name="Details").first.click(timeout=5000)
        page.wait_for_timeout(900)
        page.screenshot(path=out / "details.png")

        open_tab(page, url, "today")  # the chat panel, after one suggested question
        ask_first_suggestion(page, "Ask jobwatch")
        page.wait_for_timeout(200)
        page.screenshot(path=out / "chat.png")

        open_tab(page, url, "applied")  # the interviewing application, and its prep sheet
        page.get_by_role("button", name="Details").nth(1).click(timeout=5000)
        page.wait_for_timeout(900)
        page.screenshot(path=out / "applied-details.png")
        page.get_by_role("button", name="Prep sheet").first.click(timeout=5000)
        page.wait_for_timeout(1200)
        page.screenshot(path=out / "prep.png")
        page.get_by_role("heading", name="They'll likely ask").scroll_into_view_if_needed()
        page.evaluate("document.evaluate(\"//h3[contains(., 'honest')]\", document, null, 9, null)"
                      ".singleNodeValue?.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(500)
        page.screenshot(path=out / "prep-questions.png")
        for e in errors:
            print("page error:", e)
        browser.close()
    print(f"Wrote the demo's screenshots to {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, default=Path("shots"))
    ap.add_argument("--theme", choices=["light", "dark"], action="append")
    ap.add_argument("--size", choices=list(SIZES), action="append")
    ap.add_argument("--viewport", action="store_true", help="only the visible part, not the whole page")
    ap.add_argument("--tab", choices=TABS, action="append", help="only this tab (and what opens on it)")
    ap.add_argument("--pages", action="store_true", help="each tab a screen at a time too (TAB-THEME-SIZE-p1.png...)")
    ap.add_argument("--demo", action="store_true", help="the README demo video's scenes (scripts/demo)")
    ap.add_argument("--reply", type=Path, metavar="FILE", help="what the chat answers, instead of a generic reply")
    args = ap.parse_args()
    reply = args.reply.read_text(encoding="utf-8").strip() if args.reply else CANNED
    if args.demo:
        return demo(args.config, args.out, reply)
    sizes = tuple(args.size or ("wide", "desktop", "phone"))  # ultrawide only when asked for
    shoot(args.config, args.out, tuple(args.theme or ("light", "dark")), sizes, full_page=not args.viewport,
          reply=reply, tabs=tuple(args.tab or TABS), pages=args.pages)


if __name__ == "__main__":
    main()
