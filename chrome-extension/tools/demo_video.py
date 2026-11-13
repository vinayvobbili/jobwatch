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
TITLE_NARRATION = ("Tired of typing the same answers into every job application? "
                   "Meet jobwatch, your job-hunt helper. Let's see the Chrome extension fill one in.")
SIZE = store_assets.SCREEN
CAPTION_H = store_assets.CAPTION_H
PANEL_W = store_assets.PANEL_W
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
  <p>A free, open-source Chrome extension. Nothing leaves your computer.</p>
  <div class="chips"><span>Chrome Web Store</span><span>PyPI: jobwatch</span><span>GitHub</span></div>
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
    <li><span>Add <b>jobwatch: Application Filler</b> to Chrome <small>(search the Web Store)</small></span></li>
    <li><span>Paste the token from jobwatch's Settings into the extension's options</span></li>
    <li><span>Open an application, click the icon, press <b>Fill this application</b></span></li>
  </ol>
</body></html>""")

START_NARRATION = ("To get started, install jobwatch from PyPI and run jobwatch ui. Add the extension from the "
                   "Chrome Web Store, and paste the token from jobwatch's settings into its options. "
                   "Then open an application, and press Fill.")

END_NARRATION = ("You press Submit yourself. jobwatch is open source, on PyPI and GitHub. "
                 "Less typing, more applying. Good luck out there!")

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

    def step(self, key: str, title: str, subtitle: str, narration: str) -> None:
        """Start a new step: a new caption on screen and a new narrated clip."""
        page = self.ctx.new_page()
        # The layer is only the caption strip (CAPTION_H tall), so it can never cover the page or the panel.
        page.set_viewport_size({"width": SIZE[0], "height": CAPTION_H})
        page.set_content(CAPTION_HTML.format(w=SIZE[0], h=CAPTION_H, cap=CAPTION_H, title=title, subtitle=subtitle))
        self.layer = self.work / f"caption-{key}.png"
        page.screenshot(path=str(self.layer), omit_background=True)
        page.close()
        self.steps.append(Step(key, narration, self.count))

    def frame(self) -> None:
        name = f"{self.count:05d}"
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


def walkthrough(rec: Recorder, stack, url: str) -> None:
    """What happens, in order, with what the caption shows and the voice says."""
    rec.step("intro", "A job application on the company's own site",
             "The jobwatch extension fills it from your own jobwatch, on your own computer.",
             "Here is a job application, on the company's own site. "
             "The jobwatch extension fills it in from your own jobwatch, on your own computer. "
             "Your details, your earlier answers and your resume stay with you. "
             "Nothing is sent to anyone else.")
    rec.hold(3.0)
    rec.scroll_form(260)
    rec.hold(0.5)
    rec.scroll_form(0)

    rec.step("scan", "Fill this application",
             "It reads the form and lists every field, with where each answer comes from.",
             "Open the side panel, and click Fill this application. "
             "The extension reads the form, and lists every field. "
             "Each row says where its answer came from: your details, an earlier application, or your resume. "
             "A field that already has a value starts unticked, so nothing you typed is overwritten.")
    rec.click(rec.panel.locator("#scan"))
    rec.until(lambda: rec.panel.locator(".row").count() > 0)
    rec.hold(2.5)
    rec.scroll_panel(360, steps=20)
    rec.hold(2.5)
    rec.scroll_panel(-360, steps=20)
    rec.hold(1.5)

    rec.step("fill", "Fill selected",
             "Real events, so the board sees them. It never clicks Submit: that is yours to press.",
             "Check the rows, edit anything you like, and click Fill selected. "
             "The form fills in, the way the site expects, and your resume is attached. "
             "Scroll down and check every field. The extension never presses Submit. That is yours to do.")
    rec.click(rec.panel.locator("#fill"))
    rec.until(lambda: rec.panel.locator(".row .meta.good").count() > 0, timeout=30)
    rec.hold(2.0)
    rec.scroll_form(380, steps=30)
    rec.hold(2.5)
    rec.scroll_form(760, steps=30)
    rec.hold(2.5)

    rec.step("save", "Save this posting",
             "Adds the job to jobwatch, so it is tracked with your application.",
             "When you want to keep the job, click Save this posting. "
             "It reads the page and adds the job to job watch, where you can track it "
             "through to an offer. That is the whole flow.")
    rec.open_panel(stack, url)
    rec.hold(2.0)
    rec.click(rec.panel.locator("#posting"))
    rec.until(lambda: rec.panel.locator(".empty.done").count() > 0, timeout=30)
    rec.hold(4.0)


def encode_step(ffmpeg: str, frames: Path, step: Step, out: Path) -> Path:
    """One step's frames, composed: white stage, form, panel, caption on top."""
    graph = (
        f"color=c=white:s={SIZE[0]}x{SIZE[1]}:r={FPS}[bg];"
        f"[bg][0:v]overlay=0:{CAPTION_H}:shortest=1[a];"
        f"[a][1:v]overlay={FORM_W}:{CAPTION_H}[b];"
        f"[b][2:v]overlay=0:0,format=yuv420p[v]"
    )
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for layer in ("form_%05d.jpg", "panel_%05d.jpg", "layer_%05d.png"):
        cmd += ["-framerate", str(FPS), "-start_number", str(step.first_frame), "-i", str(frames / layer)]
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

        rec = Recorder(ctx, form, None, work)
        rec.open_panel(stack, url)
        walkthrough(rec, stack, url)

        # The end card is an HTML slide; slidecast renders it with a browser borrowed
        # from this Playwright, since a second sync Playwright can't start inside it.
        browser = playwright.chromium.launch()
        scope.callback(browser.close)
        # An upbeat composed bed (fast beats, ducked hard under the voice), punchy intro and outro stings, -16 LUFS.
        # The intro sting's hit lands first (lead_in), then the hook is spoken over the title card.
        reel = slidecast.Reel(width=SIZE[0], height=SIZE[1], fps=FPS, tts=make_tts(voice),
                              renderer=slidecast.PlaywrightRenderer(browser=browser),
                              music=slidecast.Music("compose", volume=0.3, fade_in=1.0, fade_out=3.0, duck=True,
                                                    style="upbeat"),
                              intro=slidecast.Sting("compose", volume=0.5),
                              outro=slidecast.Sting("compose", volume=0.7),
                              lead_in=INTRO_SECONDS, loudness=-16)
        icon = store_assets.data_uri(harness.EXTENSION_DIR / "icons" / "icon128.png")
        reel.add(TITLE_HTML.format(w=SIZE[0], h=SIZE[1], icon=icon), TITLE_NARRATION, tail_pad=0.6, min_duration=7.5)
        for step in rec.steps:
            clip = encode_step(ffmpeg, rec.frames, step, work / f"{step.key}.mp4")
            reel.add_clip(clip, step.narration, tail_pad=0.5)
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
