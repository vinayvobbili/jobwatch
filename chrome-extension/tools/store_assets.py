"""Generate the Chrome Web Store listing images from the real extension.

    python chrome-extension/tools/store_assets.py          # -> dist/store/

Runs the demo stack (see harness.py): the fake jobwatch with its made-up details, the demo Greenhouse form served
under the board's address, and Chromium with the extension loaded. It captures what a person sees and composes the
images the store asks for:

    screenshot-1-review.png    1280x800   the review rows after "Fill this application", form on the left
    screenshot-2-filled.png    1280x800   the form after "Fill selected"
    screenshot-3-draft.png     1280x800   a drafted answer, waiting to be ticked
    screenshot-4-pairing.png   1280x800   the options page, where the extension is paired
    screenshot-5-list-import.png 1280x800  a LinkedIn list of jobs, with the import button and passive mode
    screenshot-6-imported.png  1280x800   what the import did: coverage per site
    promo-small.png           440x280    small promo tile
    promo-marquee.png          1400x560   marquee promo tile (used if the store features it)
    icon128.png                128x128    store icon

Needs Playwright with Chromium. Everything shown is the fake server's data (Jordan Rivera, Initech); nothing real.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import shutil
import tempfile
from pathlib import Path

import harness

REPO_DIR = harness.EXTENSION_DIR.parent
SCREEN = (1280, 800)
PROMO = (440, 280)
MARQUEE = (1400, 560)
CAPTION_H = 88
PANEL_W = 400  # a realistic docked width for Chrome's side panel
BODY_H = SCREEN[1] - CAPTION_H
FORM_W = SCREEN[0] - PANEL_W
PITCH = "Fills job applications from your own jobwatch, and leaves the Submit button to you."

STAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; }}
  body {{ background: linear-gradient(120deg, #5a5cf2, #a24af0); font: 15px/1.4 system-ui, sans-serif; color: #fff; }}
  header {{ height: {cap}px; display: flex; flex-direction: column; justify-content: center; padding: 0 36px; }}
  h1 {{ margin: 0; font-size: 27px; font-weight: 700; letter-spacing: -0.01em; }}
  p {{ margin: 4px 0 0; font-size: 16px; opacity: 0.92; }}
  .shots {{ display: flex; height: {body}px; justify-content: center; background: #fff; overflow: hidden; }}
  .shots.one {{ background: linear-gradient(180deg, #e9eafc, #f3e9fb); align-items: flex-start; padding-top: 28px;
               box-sizing: border-box; }}
  img {{ display: block; }}
  .one img {{ border-radius: 12px; box-shadow: 0 12px 36px rgb(60 40 140 / 0.3); }}
  .split img + img {{ box-shadow: -1px 0 0 #d9dcea; }}
</style></head><body>
  <header><h1>{title}</h1><p>{subtitle}</p></header>
  <div class="shots {kind}">{images}</div>
</body></html>"""

BRAND_CSS = """
  html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; }}
  body {{ background: radial-gradient(520px 300px at 85% -10%, rgb(236 72 153 / 0.35), transparent 65%),
                      linear-gradient(135deg, #4f52e8, #9b3fe8); color: #fff;
          font: 15px/1.35 -apple-system, "Segoe UI", system-ui, sans-serif; box-sizing: border-box; }}
  .brand img {{ box-shadow: 0 0 0 2px rgb(255 255 255 / 0.55); }}
  h1 {{ margin: 0; font-weight: 800; letter-spacing: -0.02em; }}
"""

PROMO_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>""" + BRAND_CSS + """
  body {{ display: flex; flex-direction: column; justify-content: center; padding: 0 32px; }}
  .brand {{ display: flex; align-items: center; gap: 14px; }}
  .brand img {{ width: 64px; height: 64px; border-radius: 14px; }}
  h1 {{ font-size: 36px; }}
  p {{ margin: 18px 0 0; font-size: 17px; }}
  .never {{ margin-top: 14px; font-size: 13px; font-weight: 700; letter-spacing: 0.04em; opacity: 0.85; }}
</style></head><body>
  <div class="brand"><img src="{icon}"><h1>jobwatch</h1></div>
  <p>{pitch}</p>
  <div class="never">NEVER SUBMITS. NOTHING LEAVES YOUR COMPUTER.</div>
</body></html>"""

MARQUEE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>""" + BRAND_CSS + """
  body {{ display: flex; gap: 72px; padding: 0 88px; }}
  .copy {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
  .brand {{ display: flex; align-items: center; gap: 22px; }}
  .brand img {{ width: 96px; height: 96px; border-radius: 20px; box-shadow: 0 0 0 3px rgb(255 255 255 / 0.55); }}
  h1 {{ font-size: 64px; }}
  p {{ margin: 30px 0 0; font-size: 28px; line-height: 1.3; max-width: 640px; }}
  .shot {{ margin-top: 56px; width: {panel}px; height: {shot_h}px; object-fit: cover; object-position: top;
           border-radius: 12px 12px 0 0; box-shadow: 0 12px 40px rgb(0 0 0 / 0.35); align-self: flex-start; }}
</style></head><body>
  <div class="copy">
    <div class="brand"><img src="{icon}"><h1>jobwatch</h1></div>
    <p>{pitch}</p>
  </div>
  <img class="shot" src="{shot}">
</body></html>"""


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def stage_html(title: str, subtitle: str, shots, size=SCREEN) -> str:
    """A caption band over one capture, or over two side by side (the form, then the side panel)."""
    images = "".join(f'<img src="{data_uri(p)}">' for p in shots)
    return STAGE.format(w=size[0], h=size[1], cap=CAPTION_H, body=size[1] - CAPTION_H, title=title,
                        subtitle=subtitle, images=images, kind="split" if len(shots) > 1 else "one")


def render(context, html: str, size, target: Path) -> Path:
    page = context.new_page()
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.set_content(html)
    page.screenshot(path=str(target))
    page.close()
    return target


def compose(context, title: str, subtitle: str, shots, target: Path) -> Path:
    """One 1280x800 store screenshot."""
    return render(context, stage_html(title, subtitle, shots), SCREEN, target)


def promo_small_html(icon: Path) -> str:
    return PROMO_HTML.format(w=PROMO[0], h=PROMO[1], icon=data_uri(icon), pitch=PITCH)


def promo_marquee_html(icon: Path, shot: Path) -> str:
    return MARQUEE_HTML.format(w=MARQUEE[0], h=MARQUEE[1], panel=PANEL_W, shot_h=MARQUEE[1] - 56,
                               icon=data_uri(icon), shot=data_uri(shot), pitch=PITCH)


def scroll_to(page, selector: str, text: str, block: str = "start") -> None:
    """Scroll the first `selector` element containing `text` into view (inside any scrolling ancestor)."""
    page.evaluate("""([sel, text, block]) => {
        const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.includes(text));
        el.scrollIntoView({block});
    }""", [selector, text, block])


def build(out_dir: Path, headless: bool = True, playwright=None) -> list:
    """Write every listing image into `out_dir`. Pass `playwright` to reuse a running one."""
    with contextlib.ExitStack() as scope:
        if playwright is None:
            from playwright.sync_api import sync_playwright

            playwright = scope.enter_context(sync_playwright())
        return _capture(playwright, out_dir, headless)


def _capture(pw, out_dir: Path, headless: bool) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as tmp, harness.demo_stack(pw, headless) as stack:
        tmp = Path(tmp)
        ctx = stack.context
        url = stack.url("job-boards.greenhouse.io", "/initech/jobs/4001")
        form = ctx.new_page()
        form.emulate_media(color_scheme="light")
        form.set_viewport_size({"width": FORM_W, "height": BODY_H})
        form.goto(url)
        panel = harness.side_panel(stack, url)
        panel.emulate_media(color_scheme="light")
        panel.set_viewport_size({"width": PANEL_W, "height": BODY_H})
        panel.click("#scan")
        panel.wait_for_selector(".row", timeout=20000)

        def shot(page, name):
            page.wait_for_timeout(500)  # rows rise in; let them settle
            page.screenshot(path=str(tmp / name))
            return tmp / name

        # 1. the review rows, with the form's matching fields beside them. The marquee wants the panel's top.
        top = shot(panel, "panel-top.png")
        panel.evaluate("document.body.style.zoom = 0.8")  # Chrome's 80% zoom, so every kind of row fits
        scroll_to(panel, ".row", "Website")
        scroll_to(form, "label", "Website")
        written.append(compose(
            ctx, "Review every field before anything is filled",
            "Your details and answers from earlier applications, each marked with where it came from.",
            [shot(form, "form-1.png"), shot(panel, "panel-1.png")], out_dir / "screenshot-1-review.png"))

        # 2. after Fill selected: the form is filled, nothing is submitted
        panel.evaluate("document.body.style.zoom = 1")
        panel.locator("#fill").click()
        panel.wait_for_selector("#toast", timeout=20000)
        form.evaluate("window.scrollTo(0, 0)")
        scroll_to(panel, ".row", "Resume/CV")
        written.append(compose(
            ctx, "Fill selected writes the ticked rows into the form",
            "Real events, so Greenhouse, Lever and Ashby see them. It never clicks Submit: that is yours to press.",
            [shot(form, "form-2.png"), shot(panel, "panel-2.png")], out_dir / "screenshot-2-filled.png"))

        # 3. a free-text question drafted for this job (made-up text that reads like a real draft), unticked
        stack.server.draft_answer = (
            "Initech's platform team owns the paved road every product team ships on, and that is the work I like "
            "most. At Globex I moved 40 services onto one deploy pipeline and cut release time from a day to an "
            "hour, mostly by deleting steps nobody could explain.\n\nI'd bring the same habit here: measure where "
            "engineers wait, then remove the wait.")
        panel.locator(".row").filter(has_text="Why do you want").get_by_text("Draft with jobwatch").click()
        panel.wait_for_selector(".badge.draft")
        scroll_to(form, "label", "Why do you want")
        scroll_to(panel, ".row", "Why do you want")
        written.append(compose(
            ctx, "Drafts the questions you have not answered before",
            "Written by your own jobwatch from your resume and the posting. Never filled until you tick it.",
            [shot(form, "form-3.png"), shot(panel, "panel-3.png")], out_dir / "screenshot-3-draft.png"))

        # 4. the options page: paired with the local jobwatch
        options = stack.extension_page("options.html")
        options.emulate_media(color_scheme="light")
        options.set_viewport_size({"width": 760, "height": 460})
        options.click("#test")
        options.wait_for_selector("#result.ok", timeout=10000)
        options.fill("#serverUrl", "http://127.0.0.1:8765")  # the usual address, not the fake server's random port
        options.wait_for_timeout(500)
        options.screenshot(path=str(tmp / "options.png"))
        written.append(compose(
            ctx, "Paired with the jobwatch on your own computer",
            "Paste the token from jobwatch's Settings once. The extension talks only to 127.0.0.1.",
            [tmp / "options.png"], out_dir / "screenshot-4-pairing.png"))

        # 5 and 6. a LinkedIn list of made-up jobs: passive mode has noted them, then Import sends them to jobwatch
        stack.server.features = ["posting", "import-list"]
        list_url = stack.url("www.linkedin.com", "/jobs/collections/recommended")
        jobs = ctx.new_page()
        jobs.emulate_media(color_scheme="light")
        jobs.set_viewport_size({"width": FORM_W, "height": BODY_H})
        jobs.goto(list_url)
        side = harness.side_panel(stack, list_url)
        side.emulate_media(color_scheme="light")
        side.set_viewport_size({"width": PANEL_W, "height": BODY_H})
        side.wait_for_selector("#passive-import", state="visible", timeout=20000)  # passive mode noted the cards
        written.append(compose(
            ctx, "Import the jobs on a LinkedIn or Indeed list",
            "Press the button on a list you have open, or import the jobs noted while you browsed.",
            [shot(jobs, "list-5.png"), shot(side, "side-5.png")], out_dir / "screenshot-5-list-import.png"))
        side.locator("#passive-import").click()
        side.wait_for_selector(".row .badge", timeout=20000)
        written.append(compose(
            ctx, "See which jobs jobwatch already had",
            "The jobs go only to the jobwatch on your own computer, which tracks the new ones.",
            [shot(jobs, "list-6.png"), shot(side, "side-6.png")], out_dir / "screenshot-6-imported.png"))

        icon = harness.EXTENSION_DIR / "icons" / "icon128.png"
        written.append(render(ctx, promo_small_html(icon), PROMO, out_dir / "promo-small.png"))
        written.append(render(ctx, promo_marquee_html(icon, top), MARQUEE, out_dir / "promo-marquee.png"))
        written.append(Path(shutil.copy(icon, out_dir / "icon128.png")))
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_DIR / "dist" / "store",
                        help="output directory (default: dist/store/)")
    parser.add_argument("--headed", action="store_true", help="show the browser while capturing")
    args = parser.parse_args(argv)
    for path in build(args.out, headless=not args.headed):
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
