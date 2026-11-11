"""Editing a hand-written prep sheet in the browser (the Edit pill in the sheet's player.js).

The page sends only the cells, list items and paragraphs you changed, each with its key: the element's place among
the sheet's <td>, <li> and <p> elements, in document order (script, style, video, svg, template, pre and textarea
leave out what's inside them). The page can't send its DOM, since player.js adds elements of its own, so the key is
all that maps an edit back to the file. This module counts the same elements in the file with the standard HTML
parser, swaps each one's inner HTML for the sanitized new text, and writes the file back with the previous version
kept beside it as <name>.html.bak (one level).

After a save, the sheet's rehearse page is rebuilt, scripts/prep_blocks.py --check (when the sheet's repo has it)
reports problems, and a drill video that exists is rendered again in the background (DrillQueue).
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from . import interviews, rehearse

EDITABLE = ("td", "li", "p")
SKIP_INSIDE = frozenset({"script", "style", "video", "svg", "template", "pre", "textarea"})
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                  "wbr"})
# an element that holds one of these (or is one) is structure: its own text isn't edited, the parts inside are
BLOCKS = frozenset({"table", "thead", "tbody", "tfoot", "tr", "th", "td", "ul", "ol", "li", "p", "div", "pre",
                    "video", "section", "article", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "details"})
MAX_EDITS = 500
DRILL_SETTLE = 20.0  # seconds without another save before the drill video is rendered
CHECK_TIMEOUT = 60


class EditError(ValueError):
    """An edit that can't be applied; the message says why, for the page."""


def norm(text: str) -> str:
    """Text with its whitespace collapsed: how an element's words are compared."""
    return " ".join(text.split())


@dataclass
class Slot:
    key: int
    start: int            # where the inner HTML begins
    end: int | None = None   # where it ends; None: the element was never closed
    leaf: bool = True     # holds no table, list, paragraph... of its own
    text: list[str] = field(default_factory=list)

    @property
    def words(self) -> str:
        return norm("".join(self.text))


class _Scan(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [0]
        for m in re.finditer("\n", source):
            self.lines.append(m.end())
        self.stack: list[tuple[str, Slot | None]] = []
        self.slots: list[Slot] = []

    def at(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        if tag in BLOCKS:
            for _, slot in self.stack:
                if slot:
                    slot.leaf = False
        slot = None
        if tag in EDITABLE and not any(t in SKIP_INSIDE for t, _ in self.stack):
            slot = Slot(len(self.slots), self.at() + len(self.get_starttag_text() or ""))
            self.slots.append(slot)
        self.stack.append((tag, slot))

    def handle_startendtag(self, tag, attrs):
        pass  # <p/> holds nothing

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if slot := self.stack[i][1]:
                    slot.end = self.at()
                del self.stack[i:]  # anything left open inside it stays unclosed
                return

    def handle_data(self, data):
        for _, slot in self.stack:
            if slot:
                slot.text.append(data)


def slots(source: str) -> list[Slot]:
    """The sheet's <td>, <li> and <p> elements in document order; a slot's key is its place in this list."""
    scan = _Scan(source)
    scan.feed(source)
    scan.close()
    return scan.slots


# -- sanitizing: what an edit may carry is inline formatting and nothing else

INLINE = frozenset({"b", "i", "em", "strong", "br", "a", "code", "span"})
DROP_WITH_CONTENT = frozenset({"script", "style", "template", "svg", "iframe", "object", "embed", "noscript", "title"})
SAFE_SCHEMES = ("", "http", "https", "mailto")


def _safe_href(href: str) -> str | None:
    flat = re.sub(r"[\x00-\x20\x7f]+", "", href)  # "java\nscript:" is still javascript:
    return href.strip() if urlparse(flat).scheme.lower() in SAFE_SCHEMES else None


class _Clean(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.dropping = 0

    def _break(self):
        if self.out and self.out[-1] != "<br>":
            self.out.append("<br>")

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.dropping += 1
        elif self.dropping:
            return
        elif tag == "br":
            self.out.append("<br>")
        elif tag in ("div", "p", "li", "tr"):  # Enter in an editable cell makes a <div>: it is a line break
            self._break()
        elif tag in INLINE:
            attr = ""
            for name, value in attrs:
                value = value or ""
                if tag == "a" and name == "href" and (href := _safe_href(value)) is not None:
                    attr += f' href="{html.escape(href)}"'
                elif tag == "span" and name == "class" and re.fullmatch(r"[\w\- ]{1,60}", value):
                    attr += f' class="{value}"'
            self.out.append(f"<{tag}{attr}>")
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.dropping = max(0, self.dropping - 1)
        elif not self.dropping and tag in self.open:
            while self.open:
                self.out.append(f"</{(last := self.open.pop())}>")
                if last == tag:
                    break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(html.escape(data, quote=False))


def sanitize(fragment: str) -> str:
    """An edit's HTML with only inline formatting left (b, i, em, strong, br, a with a web or mail href, code, and
    span with a class). Scripts and their text, event handlers, styles and every other tag or attribute go; the
    text of a dropped tag stays."""
    clean = _Clean()
    clean.feed(fragment)
    clean.close()
    while clean.open:
        clean.out.append(f"</{clean.open.pop()}>")
    out = "".join(clean.out)
    return re.sub(r"^(?:<br>)+|(?:<br>)+$", "", out)


# -- applying edits

def apply_edits(source: str, edits: list[dict]) -> str:
    """The sheet with each edit's inner HTML swapped in. An edit is {key, html} and may carry `was`, the element's
    text when the page loaded: if the file's no longer says that, the sheet changed under the page and nothing is
    applied."""
    if not isinstance(edits, list) or not edits:
        raise EditError("there is nothing to save")
    if len(edits) > MAX_EDITS:
        raise EditError(f"too many edits at once ({MAX_EDITS} at most)")
    found = slots(source)
    chosen: dict[int, str] = {}
    for e in edits:
        key = e.get("key") if isinstance(e, dict) else None
        if not isinstance(key, int) or isinstance(key, bool) or not 0 <= key < len(found):
            raise EditError(f"no element {key!r} in this sheet; reload the page")
        if key in chosen:
            raise EditError(f"element {key} is in the edits twice")
        slot = found[key]
        if slot.end is None or not slot.leaf:
            raise EditError(f"element {key} is part of the sheet's structure, not text")
        if not isinstance(e.get("html"), str):
            raise EditError(f"element {key} has no html")
        if isinstance(e.get("was"), str) and norm(e["was"]) != slot.words:
            raise EditError(f"element {key} changed since the page loaded; reload the page")
        chosen[key] = sanitize(e["html"])
    out = source
    for key in sorted(chosen, reverse=True):  # from the end, so earlier offsets hold
        slot = found[key]
        out = out[:slot.start] + chosen[key] + out[slot.end:]
    if len(slots(out)) != len(found):  # an edit can't add or remove an element, whatever it held
        raise EditError("the edits changed the sheet's structure; nothing was saved")
    return out


def sheet_path(folder: Path | None, name: str) -> Path:
    """The prep sheet `name` in the sheets folder, to edit: an HTML file directly in the folder, not a rehearse
    page (those are built from the sheet). Raises EditError otherwise."""
    if not isinstance(name, str):
        raise EditError("name the sheet")
    try:
        path, ctype = interviews.sheet_file(folder, name)
    except FileNotFoundError as e:
        raise EditError(str(e)) from None
    if not ctype.startswith("text/html") or path.stem.endswith("-rehearse"):
        raise EditError(f"{name} isn't a prep sheet that can be edited")
    return path


def write_sheet(path: Path, text: str):
    """Replace the file atomically, keeping what it held as <name>.bak (the one previous version)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    shutil.copymode(path, tmp)
    shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)


def save(folder: Path | None, name: str, edits: list[dict]) -> Path:
    """Apply `edits` to the sheet `name` and write it; returns its path. Raises EditError."""
    path = sheet_path(folder, name)
    new = apply_edits(path.read_bytes().decode("utf-8"), edits)
    write_sheet(path, new)
    return path


# -- after a save

def rebuild_rehearse(sheet: Path) -> str | None:
    """Build the sheet's rehearse page again, when it has one: None when done or nothing to rebuild, else why not."""
    page = sheet.with_name(f"{sheet.stem}-rehearse.html")
    if not page.is_file():
        return None
    try:
        rehearse.write(sheet, page)
    except (ValueError, OSError) as e:
        return f"the rehearse page was not rebuilt: {e}"
    return None


def check_blocks(sheet: Path) -> list[str]:
    """Problems scripts/prep_blocks.py --check finds, from the repo the sheet lives in (prep/ beside scripts/);
    none when the repo doesn't have it."""
    script = sheet.parent.parent / "scripts" / "prep_blocks.py"
    if not script.is_file():
        return []
    try:
        done = subprocess.run([sys.executable, str(script), str(sheet), "--check"], capture_output=True, text=True,
                              timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"the sheet check did not run: {type(e).__name__}"]
    if done.returncode == 0:
        return []
    return [line.strip() for line in (done.stdout + done.stderr).splitlines() if line.strip()] or [
        f"the sheet check failed (exit {done.returncode})"]


def drill_video(sheet: Path) -> Path:
    return sheet.with_name(f"{sheet.stem}-drill.mp4")


Runner = Callable[[Path, str], "str | None"]  # (sheet, cache cap) -> None when done, else why not


def render_drill(sheet: Path, cache_max: str, config: Path | None = None) -> str | None:
    """`jobwatch prep <sheet> --drill <sheet>-drill.mp4 --no-pause` at nice 15, to a file beside the video that
    replaces it when the render finishes (a failed one leaves the old video). slidecast keeps each card's clip, so
    only the changed cards are made again; its cache cap comes from SLIDECAST_CACHE_MAX, which a launchd job doesn't
    have, so it's passed on from prep.cache_max."""
    out = drill_video(sheet)
    tmp = out.with_name(f"{out.stem}.rendering.mp4")
    cmd = ["nice", "-n", "15", sys.executable, "-m", "jobwatch.cli", *(["-c", str(config)] if config else []),
           "prep", str(sheet), "--drill", str(tmp), "--no-pause"]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([env.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])
    if cache_max:
        env["SLIDECAST_CACHE_MAX"] = cache_max
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=4 * 3600)
        if done.returncode == 0 and tmp.is_file():
            os.replace(tmp, out)
            return None
        tail = [line for line in (done.stderr or done.stdout).splitlines() if line.strip()][-3:]
        return " ".join(tail) or f"exit {done.returncode}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{type(e).__name__}: {e}"
    finally:
        tmp.unlink(missing_ok=True)


class DrillQueue:
    """Drill videos to render again, one at a time. A sheet saved several times, even while its video is rendering,
    is rendered once more after the last save (a sheet is waiting at most once), and a render starts only after
    `settle` seconds with no new save, so a rehearsal's run of edits becomes one render."""

    def __init__(self, run: Runner, log: Callable[..., None], settle: float = DRILL_SETTLE):
        self.run, self.log, self.settle = run, log, settle
        self._lock = threading.Lock()
        self._pending: dict[Path, str] = {}
        self._last = 0.0
        self._thread: threading.Thread | None = None

    def kick(self, sheet: Path, cache_max: str = "") -> bool:
        """Queue the sheet's drill video for a new render; False (and nothing queued) when it has no video yet."""
        if not drill_video(sheet).is_file():
            return False
        with self._lock:
            self._pending[sheet] = cache_max
            self._last = time.monotonic()
            if not self._thread:
                self._thread = threading.Thread(target=self._work, name="jobwatch-drill", daemon=True)
                self._thread.start()
        return True

    def waiting(self) -> list[Path]:
        with self._lock:
            return list(self._pending)

    def wait(self, timeout: float | None = None):
        if t := self._thread:
            t.join(timeout)

    def _work(self):
        try:
            while True:
                with self._lock:
                    idle = time.monotonic() - self._last
                    if not self._pending:
                        self._thread = None
                        return
                if idle < self.settle:
                    time.sleep(self.settle - idle)
                    continue
                self.drain()
        except Exception as e:  # never take the page down
            print(f"jobwatch: drill queue stopped: {type(e).__name__}: {e}", file=sys.stderr)
            with self._lock:
                self._thread = None

    def drain(self):
        """Render what's waiting, one sheet at a time."""
        while True:
            with self._lock:
                if not self._pending:
                    return
                sheet = next(iter(self._pending))
                cache_max = self._pending.pop(sheet)
            started = time.monotonic()
            try:
                why = self.run(sheet, cache_max)
            except Exception as e:
                why = f"{type(e).__name__}: {e}"
            if why:
                self.log("prep", f"The drill video for {sheet.name} was not rendered", ok=False, detail=[why],
                         by="background")
            else:
                took = round(time.monotonic() - started)
                after = f" in {took // 60} min {took % 60} s" if took >= 60 else f" in {took} s" if took else ""
                self.log("prep", f"Rendered the drill video for {sheet.name}{after}", by="background")
