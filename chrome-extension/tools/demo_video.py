"""Record a narrated walkthrough of the extension as an MP4.

    pip install "slidecast[playwright]"     # and ffmpeg on PATH (or slidecast[ffmpeg])
    python chrome-extension/tools/demo_video.py              # -> dist/store/jobwatch-extension-demo.mp4
    python chrome-extension/tools/demo_video.py --voice "Ava (Premium)"

Runs the demo stack (see harness.py): the fake jobwatch with its made-up details (Jordan Rivera, Initech) and the
demo Greenhouse form. It drives the real side panel the way a person would: Fill this application, Fill selected,
then Save this posting. Each step is captured frame by frame, with the form and the panel side by side under a
caption, and encoded as a clip. slidecast then narrates the clips (holding a clip's last frame while the voice
finishes), adds the end card and fades, and writes one 1280x800 MP4 for YouTube and the store listing.

Run it as its own process. Nothing is uploaded.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import harness
import store_assets

FPS = 15
INTRO_SECONDS = 1.2  # the title card's first silent beat: the intro sting's hit lands, then the hook is spoken
TITLE_NARRATION = ("Every job application asks the same questions again, and the essays take the longest. "
                   "The jobwatch Chrome extension answers them for you.")
SIZE = store_assets.SCREEN
CAPTION_H = store_assets.CAPTION_H
TAIL_PAD = 0.5  # silence after a step's voice
FULL_STAGE = {"installed", "jobs", "resume"}  # steps recorded as one page across the stage
# a short line still gets time to look at
MIN_SECONDS = {"installed": 5.0, "jobs": 7.5, "resume": 4.0, "draft": 10.0, "submit": 8.0}
GUTTER = 28  # a safe margin on the right: players and thumbnails that crop a few pixels must not cut the panel
PANEL_W = store_assets.PANEL_W - GUTTER  # the panel's own width; its right-edge colour is smeared across the gutter
BODY_H = store_assets.BODY_H
FORM_W = store_assets.FORM_W
FORM_URL = ("job-boards.greenhouse.io", "/initech/jobs/4001")
REPO_URL = "github.com/vinayvobbili/jobwatch"
SAY_LIKE = {r"\bjobwatch\b": "job watch"}  # how the voice should pronounce the name

CAPTION_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; background: transparent; }}
  header {{ height: {cap}px; background: linear-gradient(120deg, #5a5cf2, #a24af0); color: #fff;
            font: 15px/1.4 system-ui, sans-serif; display: flex; flex-direction: column;
            justify-content: center; padding: 0 36px; }}
  h1 {{ margin: 0; font-size: 27px; font-weight: 700; letter-spacing: -0.01em; }}
  p {{ margin: 4px 0 0; font-size: 16px; opacity: 0.92; }}
</style></head><body><header><h1>{title}</h1><p>{subtitle}</p></header></body></html>"""

# The title and end cards use jobwatch's palette (scripts/demo/build.py, jobwatch/static/index.html): dark violet
# with a soft glow, gradient accents and a mint code chip.
CARD_CSS = """
  html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; }}
  body {{ color: #f4f3ff; text-align: center; font: 15px/1.4 -apple-system, "SF Pro Display", system-ui, sans-serif;
          background: radial-gradient(900px 520px at 85% -10%, #4b2bb8 0%, transparent 60%),
                      radial-gradient(700px 480px at -10% 110%, #1f3fb0 0%, transparent 55%), #0e0d1f;
          display: flex; flex-direction: column; align-items: center; justify-content: center; }}
  .glow {{ position: absolute; left: 50%; top: 46%; width: 760px; height: 460px; margin: -230px 0 0 -380px;
           background: radial-gradient(closest-side, rgb(176 92 246 / 0.38), transparent); filter: blur(30px); }}
  .logo {{ position: relative; width: 112px; height: 112px; margin-bottom: 30px; border-radius: 30px;
           box-shadow: 0 0 60px rgb(176 92 246 / 0.55); }}
  .logo img {{ width: 112px; height: 112px; border-radius: 30px; }}
  h1 {{ position: relative; margin: 0; font-size: 62px; font-weight: 800; letter-spacing: -0.02em; }}
  h1 b {{ background: linear-gradient(90deg, #b9a8ff, #f08cff); -webkit-background-clip: text; color: transparent; }}
  p {{ position: relative; margin: 20px 0 0; font-size: 27px; color: #cfcbe8; max-width: 940px; line-height: 1.4; }}
  .chips {{ position: relative; display: flex; gap: 12px; margin-top: 34px; }}
  .chips span {{ border: 1px solid rgb(185 168 255 / 0.45); color: #dcd5ff; border-radius: 999px; padding: 8px 18px;
                 font-size: 18px; background: rgb(109 92 255 / 0.14); }}
  code {{ position: relative; margin-top: 30px; font: 600 22px ui-monospace, Menlo, monospace; color: #7ee2a8;
          background: rgb(0 0 0 / 0.35); border: 1px solid rgb(255 255 255 / 0.15); border-radius: 12px;
          padding: 12px 26px; }}
"""

TITLE_HTML = ("""<!doctype html><html><head><meta charset="utf-8"><style>""" + CARD_CSS + """</style></head><body>
  <div class="glow"></div>
  <div class="logo"><img src="{icon}"></div>
  <h1><b>jobwatch</b>: Application Filler</h1>
  <p>Fills the application for you. You check it, and press Submit yourself.</p>
</body></html>""")

END_HTML = ("""<!doctype html><html><head><meta charset="utf-8"><style>""" + CARD_CSS + """</style></head><body>
  <div class="glow"></div>
  <div class="logo"><img src="{icon}"></div>
  <h1><b>jobwatch</b>: Application Filler</h1>
  <p>A free, open-source Chrome extension. You review every field, and press Submit yourself.</p>
  <div class="chips"><span>Chrome extension</span><span>PyPI: jobwatch</span><span>GitHub</span></div>
  <code>{url}</code>
</body></html>""")

# The extension has no standalone mode: it pairs with a jobwatch running on the same computer (README, API.md Pairing).
START_HTML = ("""<!doctype html><html><head><meta charset="utf-8"><style>""" + CARD_CSS + """
  h2 {{ position: relative; margin: 0 0 34px; font-size: 54px; font-weight: 800; letter-spacing: -0.02em; }}
  h2 b {{ background: linear-gradient(90deg, #b9a8ff, #f08cff); -webkit-background-clip: text; color: transparent; }}
  ol {{ position: relative; list-style: none; margin: 0; padding: 0; text-align: left; counter-reset: s; }}
  li {{ counter-increment: s; display: flex; align-items: center; gap: 22px; margin: 0 0 20px; font-size: 27px;
        color: #e6e2fb; }}
  li::before {{ content: counter(s); flex: none; width: 46px; height: 46px; border-radius: 50%; font-weight: 800;
                font-size: 24px; display: flex; align-items: center; justify-content: center; color: #fff;
                background: linear-gradient(135deg, #6d5cff, #c04af0); box-shadow: 0 0 24px rgb(176 92 246 / 0.5); }}
  li code {{ margin: 0; padding: 4px 12px; font-size: 24px; }}
  li small {{ color: #a9a4cf; font-size: 20px; }}
</style></head><body>
  <div class="glow"></div>
  <h2>Get <b>started</b></h2>
  <ol>
    <li><span><code>pip install jobwatch</code> then <code>jobwatch ui</code>
        <small>(runs on your computer)</small></span></li>
    <li><span>Add <b>jobwatch: Application Filler</b> to Chrome</span></li>
    <li><span>Paste the token from jobwatch's Settings into the extension's options</span></li>
    <li><span>Open an application, click the icon, press <b>Fill this application</b></span></li>
  </ol>
</body></html>""")

START_NARRATION = ("It takes a minute. Install jobwatch from PyPI and run jobwatch ui. Add the extension, "
                   "and paste the token from jobwatch's settings into its options. "
                   "Then open an application, and press Fill.")

END_NARRATION = ("Fill your next application in seconds. jobwatch is free and open source, on PyPI and GitHub. "
                 "Less typing, more applying. Good luck out there!")

# What the viewer should trust, each line true of the product: it fills only what you tick (page.js fill, sidepanel.js),
# never clicks Submit (page.js refuses submit buttons), is MIT licensed, and the extension talks only to the
# jobwatch on your own computer (PRIVACY.md); a draft is written by the model chosen in jobwatch's Settings.
TRUST_HTML = ("""<!doctype html><html><head><meta charset="utf-8"><style>""" + CARD_CSS + """
  h2 {{ position: relative; margin: 0 0 30px; font-size: 54px; font-weight: 800; letter-spacing: -0.02em; }}
  h2 b {{ background: linear-gradient(90deg, #b9a8ff, #f08cff); -webkit-background-clip: text; color: transparent; }}
  ul {{ position: relative; list-style: none; margin: 0; padding: 0; text-align: left; }}
  li {{ display: flex; align-items: center; gap: 20px; margin: 0 0 20px; font-size: 30px; color: #e6e2fb; }}
  li::before {{ content: "\\2713"; flex: none; width: 46px; height: 46px; border-radius: 50%; font-weight: 800;
                font-size: 26px; display: flex; align-items: center; justify-content: center; color: #fff;
                background: linear-gradient(135deg, #6d5cff, #c04af0); box-shadow: 0 0 24px rgb(176 92 246 / 0.5); }}
</style></head><body>
  <div class="glow"></div>
  <h2>You stay in <b>control</b></h2>
  <ul>
    <li>You review every field before it is filled</li>
    <li>It never presses Submit: that is yours</li>
    <li>Free and open source</li>
    <li>It talks only to the jobwatch on your own computer</li>
  </ul>
</body></html>""")

TRUST_NARRATION = ("You review every field, and it never presses Submit. It is free and open source, "
                   "and the extension talks only to the jobwatch on your own computer.")

CURSOR_JS = """() => {
  if (document.getElementById('__demo_cursor')) return;
  const c = document.createElement('div');
  c.id = '__demo_cursor';
  c.style.cssText = 'position:fixed;z-index:2147483647;left:-40px;top:-40px;width:22px;height:22px;' +
    'margin:-11px 0 0 -11px;border-radius:50%;background:rgb(31 35 40 / 0.35);border:2px solid #fff;' +
    'box-shadow:0 1px 5px rgb(0 0 0 / 0.45);pointer-events:none;transition:transform .08s';
  document.documentElement.appendChild(c);
}"""


@dataclass
class Step:
    key: str
    narration: str
    first_frame: int
    frames: int = 0
    full: bool = False  # one page across the whole stage (no side panel), e.g. chrome://extensions
    caption: Path | None = None  # a still caption for a replayed step (its frames come from another step's)


class Recorder:
    """Captures the form and the side panel together, one frame per call, split into steps."""

    def __init__(self, ctx, form, panel, work: Path):
        self.ctx, self.form, self.panel, self.work = ctx, form, panel, work
        self.frames = work / "frames"
        self.frames.mkdir()
        self.count = 0
        self.steps = []
        self.layer = None
        self.cursor = (PANEL_W / 2, BODY_H / 2)
        self.durations = {}  # step key -> seconds of narration plus tail, measured before recording
        self.budget = 0
        self.stage = None  # a full-stage page being recorded instead of the form and panel
        self.fill = None  # measure_fill's numbers

    def caption(self, key: str, title: str, subtitle: str) -> Path:
        """The caption strip as an image. It is only CAPTION_H tall, so it can never cover the page or the panel."""
        page = self.ctx.new_page()
        page.set_viewport_size({"width": SIZE[0], "height": CAPTION_H})
        page.set_content(CAPTION_HTML.format(w=SIZE[0], h=CAPTION_H, cap=CAPTION_H, title=title, subtitle=subtitle))
        path = self.work / f"caption-{key}.png"
        page.screenshot(path=str(path), omit_background=True)
        page.close()
        return path

    def step(self, key: str, title: str, subtitle: str, narration: str) -> None:
        """Start a new step: a new caption on screen and a new narrated clip."""
        self.finish_step()
        self.layer = self.caption(key, title, subtitle)
        self.steps.append(Step(key, narration, self.count, full=key in FULL_STAGE))
        self.budget = round(self.durations.get(key, 0) * FPS)

    def left(self, end_hold: float = 0.4) -> int:
        """Frames still to record so this step's picture runs as long as its narration (less a short end hold)."""
        return max(0, self.budget - self.steps[-1].frames - round(end_hold * FPS))

    def measure_fill(self) -> None:
        """How long Fill selected really took (in the panel, from the click to its last row filled), how many fields it
        filled, and how many of them are essays: the numbers the opening flash quotes. Measured, never assumed."""
        got = self.panel.evaluate("() => window.__fill")
        essays = self.form.evaluate(
            "() => [...document.querySelectorAll('textarea')].filter(t => t.value.length > 150).length")
        if got and got["t0"] is not None and got["t1"] is not None:
            self.fill = {"seconds": (got["t1"] - got["t0"]) / 1000, "fields": got["n"], "essays": essays,
                         "first": self.steps[-1].first_frame, "frames": self.steps[-1].frames}

    def finish_step(self) -> None:
        """Hold the last picture for whatever the narration still needs, so a clip is never shorter than its voice."""
        if self.steps:
            self.hold(self.left(0) / FPS)

    def frame(self) -> None:
        name = f"{self.count:05d}"
        if self.stage:
            self.stage.screenshot(path=str(self.frames / f"form_{name}.jpg"), type="jpeg", quality=92)
        else:
            self.form.screenshot(path=str(self.frames / f"form_{name}.jpg"), type="jpeg", quality=92)
            self.panel.screenshot(path=str(self.frames / f"panel_{name}.jpg"), type="jpeg", quality=92)
        os.link(self.layer, self.frames / f"layer_{name}.png")
        self.count += 1
        self.steps[-1].frames += 1

    def hold(self, seconds: float) -> None:
        for _ in range(round(seconds * FPS)):
            self.frame()

    def until(self, done, timeout: float = 60) -> None:
        for _ in range(round(timeout * FPS)):
            if done():
                return
            self.frame()
        raise AssertionError("the demo got stuck waiting")

    # --- the pointer, which headless screenshots don't show ------------------------------

    def _put_cursor(self, x: float, y: float, pressed: bool = False) -> None:
        self.panel.evaluate(
            "([x, y, p]) => { const c = document.getElementById('__demo_cursor');"
            " c.style.left = x + 'px'; c.style.top = y + 'px'; c.style.transform = p ? 'scale(.7)' : ''; }",
            [x, y, pressed],
        )
        self.cursor = (x, y)

    def point(self, locator, frames: int = 9) -> None:
        box = locator.bounding_box()
        x, y = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        x0, y0 = self.cursor
        for i in range(1, frames + 1):
            t = i / frames
            ease = t * t * (3 - 2 * t)
            self._put_cursor(x0 + (x - x0) * ease, y0 + (y - y0) * ease)
            self.frame()

    def click(self, locator) -> None:
        self.point(locator)
        self._put_cursor(*self.cursor, pressed=True)
        self.frame()
        locator.click()
        self._put_cursor(*self.cursor)
        self.frame()

    def scroll_panel(self, dy: int, steps: int = 10) -> None:
        self.panel.mouse.move(*self.cursor)
        for _ in range(steps):
            self.panel.mouse.wheel(0, dy / steps)
            self.frame()

    def scroll_form(self, y: int, steps: int = 18) -> None:
        start = self.form.evaluate("() => window.scrollY")
        for i in range(1, steps + 1):
            t = i / steps
            self.form.evaluate("(y) => window.scrollTo(0, y)", start + (y - start) * t * t * (3 - 2 * t))
            self.frame()

    # The form scrolls its window; the panel scrolls its field list (.scroll), under the fixed header and footer.
    def _top(self, page) -> float:
        return page.evaluate("() => (document.querySelector('.scroll') || document.scrollingElement).scrollTop")

    def _to(self, page, y: float) -> None:
        page.evaluate("(y) => (document.querySelector('.scroll') || document.scrollingElement).scrollTo(0, y)", y)

    def extent(self, page) -> float:
        """How far `page` can scroll."""
        return page.evaluate("() => { const e = document.querySelector('.scroll') || document.scrollingElement;"
                             " return Math.max(0, e.scrollHeight - e.clientHeight); }")

    def glide(self, frames: int, form_y: float | None = None, panel_y: float | None = None) -> None:
        """Ease the form and/or the panel's list from where they are to the given scroll positions.

        The pages move together, so the field the voice is on is on screen in both.
        """
        moves = [(p, self._top(p), y) for p, y in ((self.form, form_y), (self.panel, panel_y)) if y is not None]
        for i in range(1, max(1, frames) + 1):
            t = i / max(1, frames)
            ease = t * t * (3 - 2 * t)
            for p, y0, y1 in moves:
                self._to(p, y0 + (y1 - y0) * ease)
            self.frame()

    def essay_at(self, text: str) -> tuple:
        """Scroll positions that put the essay question containing `text` near the top of the form and the panel."""
        fy = self.form.locator("label", has_text=text).evaluate(
            "(e) => e.getBoundingClientRect().top + document.scrollingElement.scrollTop") - 24
        py = self.panel.locator(".row", has_text=text).evaluate(
            "(e) => { const s = document.querySelector('.scroll');"
            " return e.getBoundingClientRect().top - s.getBoundingClientRect().top + s.scrollTop; }") - 8
        return max(0, fy), max(0, py)

    def open_panel(self, stack, url: str):
        """A fresh side panel on the form's tab, as when the person opens it again; the old one is closed."""
        old = self.panel
        self.panel = harness.side_panel(stack, url)
        self.panel.emulate_media(color_scheme="light")
        self.panel.set_viewport_size({"width": PANEL_W, "height": BODY_H})
        self.panel.wait_for_selector("#scan")
        self.panel.evaluate(CURSOR_JS)
        if old:
            old.close()
        return self.panel


MEASURE_FILL_JS = """() => {
  const f = window.__fill = { t0: null, t1: null, n: 0 };
  document.getElementById('fill').addEventListener('click', () => {
    f.t0 = performance.now();
    f.n = document.querySelectorAll('.row input[type=checkbox]:checked').length;
  }, true);
  new MutationObserver(() => {
    const done = document.querySelectorAll('.row .meta.good').length;
    if (f.t0 !== null && f.t1 === null && done >= f.n) f.t1 = performance.now();
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
}"""

HIGHLIGHT_JS ="""(e) => {
  e.style.transition = 'box-shadow .6s, outline-color .6s';
  e.style.borderRadius = '14px';
  e.style.outline = '3px solid #8b5cf6';
  e.style.outlineOffset = '4px';
  e.style.boxShadow = '0 0 0 10px rgb(139 92 246 / 0.22), 0 0 36px 8px rgb(176 92 246 / 0.45)';
}"""


def show_installed(rec: Recorder) -> None:
    """chrome://extensions, live, in the browser that has the extension: search "jobwatch", outline its card."""
    rec.step("installed", "Installed in Chrome",
             "It sits with your other extensions, ready on any job application page.", NARRATION["installed"])
    page = rec.ctx.new_page()
    page.set_viewport_size({"width": SIZE[0], "height": BODY_H})
    page.emulate_media(color_scheme="light")
    page.goto("chrome://extensions")
    page.wait_for_selector("extensions-item")
    # Developer mode off, so the card looks like a normal install (no ID, no "service worker", no Load unpacked).
    page.evaluate("() => chrome.developerPrivate.updateProfileConfiguration({inDeveloperMode: false})")
    page.wait_for_timeout(600)  # the page re-renders the card without the developer details
    rec.stage = page
    rec.hold(1.2)
    box = page.locator("cr-toolbar-search-field input")
    box.click()
    for letter in "jobwatch":  # visibly, letter by letter
        page.keyboard.type(letter)
        rec.hold(0.14)
    rec.hold(0.6)
    page.locator("extensions-item").first.evaluate(HIGHLIGHT_JS)
    rec.hold(max(0.0, rec.left() / FPS))
    rec.finish_step()
    rec.stage = None
    page.close()


def show_resume(rec: Recorder, stack) -> None:
    """The made-up resume (demo/resume.html), with the bullet that the next step's draft will quote outlined."""
    rec.step("resume", "Your resume has the answer",
             "Some form questions have no earlier answer, but your resume does.", NARRATION["resume"])
    page = rec.ctx.new_page()
    page.set_viewport_size({"width": SIZE[0], "height": BODY_H})
    page.emulate_media(color_scheme="light")
    page.goto(stack.url(FORM_URL[0], "/resume.html"))
    rec.stage = page
    rec.hold(1.2)
    page.locator("#k8s").evaluate(HIGHLIGHT_JS)
    rec.hold(max(0.0, rec.left() / FPS))
    rec.finish_step()
    rec.stage = None
    page.close()


def draft_from_resume(rec: Recorder) -> None:
    """"Draft with jobwatch" on a question no earlier answer matches: the product has the chat's model write it from
    the resume (autofill.draft, POST /ext/draft); the panel badges the row "Draft" and holds it unticked, so tick it
    and fill again to see it land in the form."""
    rec.step("draft", "Drafted from your resume",
             "Drafted from your resume, with your real numbers. You read it and edit it before it is filled.",
             NARRATION["draft"])
    row = rec.panel.locator(".row", has_text="Kubernetes")
    rec.glide(18, *rec.essay_at("Kubernetes"))
    rec.hold(1.0)
    rec.click(row.get_by_text("Draft with jobwatch"))
    rec.until(lambda: row.locator("textarea").input_value() != "", timeout=30)
    rec.hold(2.5)  # the drafted answer sits in the panel, to be read
    rec.click(row.locator("input[type=checkbox]"))
    rec.click(rec.panel.locator("#fill"))
    rec.until(lambda: rec.form.locator("#question_11").input_value() != "", timeout=30)
    rec.glide(18, rec.essay_at("Kubernetes")[0])
    rec.hold(max(0.0, rec.left() / FPS))
    rec.finish_step()


NARRATION = {
    "installed": "Add jobwatch to Chrome, and it sits with your other extensions.",
    "jobs": "Here's a job jobwatch found. Let's apply to this one.",
    "intro": ("Here is the application, on the company's own site. "
              "The extension fills it in from your own jobwatch."),
    "scan": ("Open the side panel, and press Fill this application. "
             "It lists every field, and where each answer comes from."),
    "fill": ("Press Fill selected. Your details and your earlier answers go in, even the long essays. "
             "Check everything, and edit anything you like."),
    "resume": "Some questions have no earlier answer. But your resume does.",
    "draft": "jobwatch drafts one from it, using your real numbers, for you to edit.",
    "submit": ("Now press Submit yourself. jobwatch keeps every answer you sent, "
               "ready for next time and for interview prep."),
}


INITECH_KEY = "ashby:initech:c1"  # the demo store's Initech Platform Engineer


@contextlib.contextmanager
def demo_ui(form_url: str):
    """`jobwatch ui` on a throwaway demo store (scripts/demo/seed.py: made-up companies, jobs and resume only), whose
    Initech Platform Engineer posting links to the demo form. Yields the page's URL (jobwatch.localhost:<port>).

    It never touches the real watchlist or store: everything lives in a temp folder, which is checked below to hold
    the demo marker and the config and state before the server starts, and JOBWATCH_CONFIG points at it meanwhile.
    """
    import importlib.util
    import threading

    from jobwatch.web import APP_HOST, serve

    spec = importlib.util.spec_from_file_location("demo_seed", store_assets.REPO_DIR / "scripts" / "demo" / "seed.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    initech = seed.job("ashby", "initech", "Initech", "c1", "Platform Engineer",
                       ["Denver, CO, United States", "Remote, United States"], 190000, 240000, 0, seed.PLATFORM)
    initech.url = form_url
    seed.BOARDS[("ashby", "initech")][0] = initech
    seed.FIT[INITECH_KEY] = (88, 6, 7, ["GPU serving experience"], "Strong match on Python, Kubernetes and Terraform.")
    with tempfile.TemporaryDirectory(prefix="jobwatch-demo-ui-") as tmp:
        root = Path(tmp).resolve()
        config = seed.seed(root / "demo")
        assert config.resolve().is_relative_to(root) and (config.parent / seed.MARK).is_file(), \
            "the demo UI must run on its own throwaway store"
        assert (config.parent / "state" / "state.db").is_file()
        before = os.environ.get("JOBWATCH_CONFIG")
        os.environ["JOBWATCH_CONFIG"] = str(config)
        server = serve(config, port=0, open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield f"http://{APP_HOST}:{server.server_address[1]}/"
        finally:
            server.shutdown()
            server.server_close()
            if before is None:
                os.environ.pop("JOBWATCH_CONFIG", None)
            else:
                os.environ["JOBWATCH_CONFIG"] = before


def show_jobs(rec: Recorder, ui_url: str, form_url: str) -> None:
    """jobwatch's own page: the Initech job in the list, outlined, then the real Apply click opens the form."""
    rec.step("jobs", "A job jobwatch found",
             "It tracks the jobs for you. Pick one, and press Apply to open the company's form.", NARRATION["jobs"])
    page = rec.ctx.new_page()
    page.set_viewport_size({"width": SIZE[0], "height": BODY_H})
    page.emulate_media(color_scheme="light")
    page.goto(ui_url + "#today")
    card = page.locator(f"[id='job-{INITECH_KEY}']")
    card.wait_for()
    page.wait_for_timeout(1500)  # entrance animations
    rec.stage = page
    rec.hold(1.0)
    top = card.evaluate("(e) => e.getBoundingClientRect().top + window.scrollY") - 120
    start = page.evaluate("() => window.scrollY")
    for i in range(1, 25):  # an eased scroll that brings the Initech card up
        t = i / 24
        page.evaluate("(y) => window.scrollTo(0, y)", start + (top - start) * t * t * (3 - 2 * t))
        rec.frame()
    card.evaluate(HIGHLIGHT_JS)
    rec.hold(max(1.5, rec.left() / FPS - 2.0))
    with page.context.expect_page() as opened:
        card.get_by_role("link", name="Apply").click()
    form = opened.value
    form.set_viewport_size({"width": SIZE[0], "height": BODY_H})
    form.wait_for_load_state()
    assert form.url == form_url, f"Apply opened {form.url}, not the demo form"
    rec.stage = form
    rec.hold(1.5)
    rec.finish_step()
    rec.stage = None
    form.close()
    page.close()


def walkthrough(rec: Recorder, stack, url: str, ui_url: str) -> None:
    """What happens, in order, with what the caption shows and the voice says."""
    show_installed(rec)
    show_jobs(rec, ui_url, url)
    rec.step("intro", "A job application on the company's own site",
             "The jobwatch extension fills it from your own jobwatch, on your own computer.",
             NARRATION["intro"])
    rec.hold(0.8)
    n = rec.left()  # the form slides by while the voice talks, and back to the top
    rec.glide(n * 55 // 100, rec.extent(rec.form))
    rec.glide(rec.left(), 0)

    rec.step("scan", "Fill this application",
             "It reads the form and lists every field, with where each answer comes from.",
             NARRATION["scan"])
    rec.click(rec.panel.locator("#scan"))
    rec.until(lambda: rec.panel.locator(".row").count() > 0)
    rec.hold(1.0)
    # The field list and the form glide together, every source badge in turn, pausing on the essay questions.
    n = rec.left()
    rec.glide(n * 30 // 100, *rec.essay_at("Describe a project"))
    rec.hold(n * 22 / 100 / FPS)
    rec.glide(n * 28 // 100, rec.extent(rec.form), rec.extent(rec.panel))
    rec.glide(rec.left(), 0, 0)

    rec.step("fill", "Fill selected",
             "Real events, so the board sees them. It never clicks Submit: that is yours to press.",
             NARRATION["fill"])
    rec.panel.evaluate(MEASURE_FILL_JS)
    rec.click(rec.panel.locator("#fill"))
    rec.until(lambda: rec.panel.locator(".row .meta.good").count() > 0, timeout=30)
    rec.hold(1.0)
    rec.measure_fill()
    # Down through the filled form and the panel's Filled marks, stopping to let the essay answers be read.
    n = rec.left()
    rec.glide(n * 14 // 100, *rec.essay_at("Describe a project"))
    rec.hold(n * 26 / 100 / FPS)
    rec.glide(n * 14 // 100, *rec.essay_at("disagreed with a teammate"))
    rec.hold(n * 22 / 100 / FPS)
    rec.glide(rec.left(), rec.extent(rec.form), rec.extent(rec.panel))

    show_resume(rec, stack)
    draft_from_resume(rec)

    submit_the_form(rec)


def submit_the_form(rec: Recorder) -> None:
    """The person's own Submit click (the extension never presses it). The script in the page snapshots the answers
    at that moment and the service worker sends them to jobwatch (POST /ext/answers), which keeps them in the job's
    package; the panel says so. The demo form then shows its thank-you, which is what lets jobwatch record it."""
    rec.step("submit", "You press Submit",
             "jobwatch keeps every answer you sent, for next time and for interview prep.", NARRATION["submit"])
    button = rec.form.locator("button[type=submit]")
    rec.glide(20, rec.extent(rec.form))
    rec.hold(0.8)
    button.evaluate(HIGHLIGHT_JS)
    rec.hold(1.2)
    button.click()
    rec.until(lambda: rec.panel.locator("#toast").count() > 0, timeout=30)
    rec.hold(max(0.0, rec.left() / FPS))
    rec.finish_step()


def encode_step(ffmpeg: str, frames: Path, step: Step, out: Path) -> Path:
    """One step's frames, composed: white stage, form, panel, caption on top."""
    graph = (
        f"color=c=white:s={SIZE[0]}x{SIZE[1]}:r={FPS}[bg];"
        f"[bg][0:v]overlay=0:{CAPTION_H}:shortest=1[a];"
        f"[1:v]pad={PANEL_W + GUTTER}:{BODY_H}:0:0,fillborders=right={GUTTER}:mode=smear[p];"
        f"[a][p]overlay={FORM_W}:{CAPTION_H}[b];"
        f"[b][2:v]overlay=0:0,format=yuv420p[v]"
    )
    layers = ("form_%05d.jpg", "panel_%05d.jpg", "layer_%05d.png")
    if step.full:  # the page spans the stage: nothing to put beside it
        graph = (f"color=c=white:s={SIZE[0]}x{SIZE[1]}:r={FPS}[bg];[bg][0:v]overlay=0:{CAPTION_H}:shortest=1[a];"
                 f"[a][1:v]overlay=0:0,format=yuv420p[v]")
        layers = (layers[0], layers[2])
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for layer in layers:
        if step.caption and layer.startswith("layer"):
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{step.frames / FPS:.4f}", "-i", str(step.caption)]
            continue
        # -t stops each sequence at the step's last frame; the frames after it may be another kind of step's
        cmd += ["-framerate", str(FPS), "-start_number", str(step.first_frame),
                "-t", f"{(step.frames - 0.5) / FPS:.4f}", "-i", str(frames / layer)]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-frames:v", str(step.frames),
            "-c:v", "libx264", "-crf", "16", "-tune", "stillimage", str(out)]
    subprocess.run(cmd, check=True)
    return out


def make_tts(voice: str):
    import slidecast

    if voice == "silent":
        return slidecast.SilentTTS()
    if voice == "kokoro":  # the house voice, in-process: pip install 'slidecast[mlx]'
        return slidecast.MLXKokoroTTS(voice="af_heart", phonetic=SAY_LIKE)
    if voice == "gtts":
        return slidecast.GTTSTTS(phonetic=SAY_LIKE)
    if shutil.which("say") is None:
        raise SystemExit(f"voice {voice!r} needs macOS `say`; use --voice gtts or --voice silent elsewhere")
    return slidecast.MacSayTTS(voice=voice, phonetic=SAY_LIKE)


def measure_narrations(tts, work: Path) -> dict:
    """Seconds each step's narration takes, plus the clip's tail pad."""
    seconds = {}
    for key, text in NARRATION.items():
        spoken = tts.synthesize(text, work / f"measure-{key}.wav")
        seconds[key] = max((spoken or 0) + TAIL_PAD, MIN_SECONDS.get(key, 0))
    return seconds


def payoff_step(rec: Recorder, tts, work: Path) -> Step | None:
    """A flash of the end result for the start of the video: the filled form and its essays, replayed from the fill
    step's own frames, with what the run measured (fields, essays, seconds). None when nothing was measured."""
    fill = rec.fill
    if not fill or fill["fields"] < 1:
        return None
    seconds = max(1, round(fill["seconds"]))
    spoken = (f"{fill['fields']} fields, including {fill['essays']} essay{'s' if fill['essays'] != 1 else ''}, "
              f"filled in about {seconds} second{'s' if seconds != 1 else ''}.")
    length = (tts.synthesize(spoken, work / "measure-payoff.wav") or 4.0) + TAIL_PAD
    frames = round(max(length, 5.0) * FPS)
    first = fill["first"] + fill["frames"] // 5  # from just after the click: the form fills, then its essays show
    if first + frames > fill["first"] + fill["frames"]:
        first, frames = fill["first"], min(frames, fill["frames"])
    caption = rec.caption("payoff", f"{fill['fields']} fields in about {seconds} second{'s' if seconds != 1 else ''}",
                          "Your details, your earlier answers and your essays, filled in for you to review.")
    return Step("payoff", spoken, first, frames, caption=caption)


def record(target: Path, voice: str = "kokoro", headless: bool = True, playwright=None) -> Path:
    """Record and narrate the walkthrough into `target` (.mp4). Pass `playwright` to reuse one."""
    import slidecast

    ffmpeg = slidecast.find_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as scope:
        if playwright is None:
            from playwright.sync_api import sync_playwright

            playwright = scope.enter_context(sync_playwright())
        work = Path(scope.enter_context(tempfile.TemporaryDirectory()))
        stack = scope.enter_context(harness.demo_stack(playwright, headless))
        ctx = stack.context

        url = stack.url(*FORM_URL)
        form = ctx.new_page()
        form.emulate_media(color_scheme="light")
        form.set_viewport_size({"width": FORM_W, "height": BODY_H})
        form.goto(url)

        # Each step's picture is paced to its narration, so measure the voice first (the same voice renders it).
        tts = make_tts(voice)
        rec = Recorder(ctx, form, None, work)
        rec.durations = measure_narrations(tts, work)
        rec.open_panel(stack, url)
        ui_url = scope.enter_context(demo_ui(url))
        walkthrough(rec, stack, url, ui_url)
        rec.finish_step()

        # The end card is an HTML slide; slidecast renders it with a browser borrowed
        # from this Playwright, since a second sync Playwright can't start inside it.
        browser = playwright.chromium.launch()
        scope.callback(browser.close)
        # An upbeat composed bed (fast beats, ducked hard under the voice), punchy intro and outro stings, -16 LUFS.
        # The intro sting's hit lands first (lead_in), then the hook is spoken over the title card.
        reel = slidecast.Reel(width=SIZE[0], height=SIZE[1], fps=FPS, tts=tts,
                              renderer=slidecast.PlaywrightRenderer(browser=browser),
                              music=slidecast.Music("compose", volume=0.3, fade_in=1.0, fade_out=3.0, duck=True,
                                                    style="upbeat"),
                              intro=slidecast.Sting("compose", volume=0.5),
                              outro=slidecast.Sting("compose", volume=0.7),
                              lead_in=INTRO_SECONDS, loudness=-16)
        icon = store_assets.data_uri(harness.EXTENSION_DIR / "icons" / "icon128.png")
        reel.add(TITLE_HTML.format(w=SIZE[0], h=SIZE[1], icon=icon), TITLE_NARRATION, tail_pad=0.6, min_duration=7.5)
        steps = rec.steps
        if payoff := payoff_step(rec, tts, work):  # the result up front, right after the hook
            steps = [payoff, *steps]
        for step in steps:
            clip = encode_step(ffmpeg, rec.frames, step, work / f"{step.key}.mp4")
            reel.add_clip(clip, step.narration, tail_pad=TAIL_PAD, min_duration=MIN_SECONDS.get(step.key, 0))
        reel.add(TRUST_HTML.format(w=SIZE[0], h=SIZE[1]), TRUST_NARRATION, tail_pad=0.6, min_duration=6.0)
        reel.add(START_HTML.format(w=SIZE[0], h=SIZE[1]), START_NARRATION, tail_pad=0.8, min_duration=4.0)
        reel.add(END_HTML.format(w=SIZE[0], h=SIZE[1], icon=icon, url=REPO_URL), END_NARRATION,
                 tail_pad=1.2, min_duration=4.0)
        return reel.render(target, ffmpeg=ffmpeg, fade_out=1.0, make_poster=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=store_assets.REPO_DIR / "dist" / "store" / "jobwatch-extension-demo.mp4",
                        help="output file (default: dist/store/jobwatch-extension-demo.mp4)")
    parser.add_argument("--voice", default="kokoro",
                        help="'kokoro' (the house voice, default), a macOS voice from `say -v '?'`, "
                             "'gtts', or 'silent'")
    parser.add_argument("--headed", action="store_true", help="show the browser while recording")
    args = parser.parse_args(argv)
    print(f"Wrote {record(args.out, voice=args.voice, headless=not args.headed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
