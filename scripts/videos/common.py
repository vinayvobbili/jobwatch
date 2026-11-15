"""What every video's scenes share: a seeded demo served by `jobwatch ui`, a scene (what is said, and what the
mouse does while it is said), and the timing that keeps a clip as long as its narration.

Everything is made up (Acme, Globex, Initech...): nothing reads a real watchlist, reaches a job board or calls a model.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))  # screenshots.py, demo/seed.py

from demo import seed  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from screenshots import canned_chat, hide_folder, serving  # noqa: E402

WORDS_PER_SECOND = 2.55  # Kokoro's af_heart, a little slower than it speaks, so a clip never ends before its line
LEAD = 0.6  # a beat before the voice has anything to look at


def seconds_to_say(text: str) -> float:
    """How long a narration takes, about: the clip is held at least this long."""
    return len(text.split()) / WORDS_PER_SECOND + LEAD


@dataclass
class Demo:
    """A served demo: its address, its watchlist folder, and the browser to record it in."""

    url: str
    folder: Path
    browser: object
    extra: dict = field(default_factory=dict)

    @property
    def stack(self):
        """The extension's demo stack (see demo_running(extension=True))."""
        return self.extra["stack"]

    def hide_path(self, page) -> None:
        hide_folder(page, self.folder)


@dataclass
class Scene:
    """One narrated clip: open `start` (a tab, or a path in the page), say `say`, and do `run(rec, demo)` meanwhile."""

    say: str
    run: Callable | None = None
    start: str | Callable = "today"  # a tab ("today", "settings/ai"), a URL, or a function of the Demo giving one
    min_seconds: float = 0.0
    name: str = ""
    demo: str | None = None  # "plain", "more" or "empty": which demo this scene runs on (default: the video's)
    html: str = ""  # a card instead of a recording: an animated page, shown for `seconds`
    seconds: float = 5.0

    def url(self, demo: Demo) -> str:
        start = self.start(demo) if callable(self.start) else self.start
        return start if start.startswith("http") else f"{demo.url}#{start}"


TAGLINE = "Your job hunt shouldn't be a full-time job."


@dataclass
class Video:
    """A video: its title card, the problem it opens on, and the scenes of the walkthrough.

    name: the file stem (`jobwatch-demo`, `jobwatch-01-getting-started`). subtitle: under the title card's logo.
    problem: lines for the animated problem scene, and `problem_say` is its narration. demo: which demo to seed (see
    demo_running), unless a scene says otherwise. extension: load the Chrome extension. max_seconds: the length
    this video must stay under.
    """

    name: str
    subtitle: str
    problem: list[str]
    problem_say: str
    scenes: list[Scene]
    demo: str = "plain"  # "plain", "more" (comps, contacts, interviews, a package) or "empty" (first-run onboarding)
    extension: bool = False
    max_seconds: float = 120.0

    def kind(self, scene: Scene) -> str:
        return scene.demo or self.demo


VIEW = {"viewport": {"width": 1536, "height": 864}, "device_scale_factor": 1.25, "color_scheme": "light"}
VIDEO_SIZE = {"width": 1920, "height": 1080}
EXTENSION_TOOLS = SCRIPTS.parent / "chrome-extension" / "tools"


@contextmanager
def demo_running(more: bool = False, empty: bool = False, extension: bool = False, record: Path | None = None
                 ) -> Iterator[Demo]:
    """The demo seeded into a fresh folder and served on a free port, with Chromium ready.

    more: the tutorials' extra records (comps, contacts, interviews, a saved package). empty: no companies, so the
    page opens on first-run onboarding. extension: Chromium with the jobwatch extension loaded and paired to the
    extension's stand-in jobwatch (chrome-extension/tools), and the demo form and LinkedIn list pages served: the
    stack is `demo.stack`. record: a folder for the screen recordings (omit it for a dry run).
    The chat shows a canned reply and nothing calls a model or a board.
    """
    with tempfile.TemporaryDirectory(prefix="jobwatch-video-") as tmp:
        folder = Path(tmp) / "demo"
        if empty:
            folder.mkdir()
            (folder / "jobwatch.yaml").write_text(
                "companies: []\nfilters:\n  titles: []\ndisplay:\n  theme: light\nstate: state/state.db\n"
                "cache: cache\nfetch_every: off\n")
            config = folder / "jobwatch.yaml"
        else:
            config = seed.seed(folder, more=more)
        canned_chat((SCRIPTS / "demo" / "chat-reply.md").read_text(encoding="utf-8"))
        with serving(config) as url, sync_playwright() as p:
            if not extension:
                browser = p.chromium.launch()
                try:
                    yield Demo(url=url, folder=folder, browser=browser)
                finally:
                    browser.close()
                return
            sys.path.insert(0, str(EXTENSION_TOOLS))
            import harness  # chrome-extension/tools: the demo forms, the stand-in jobwatch, Chromium with the extension

            options = dict(VIEW, expose_panel=True)
            if record:
                options.update(record_video_dir=str(record), record_video_size=VIDEO_SIZE)
            with harness.demo_stack(p, **options) as stack:
                yield Demo(url=url, folder=folder, browser=stack.context, extra={"stack": stack})
