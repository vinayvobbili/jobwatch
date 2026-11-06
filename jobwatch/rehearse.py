"""A rehearsal page from a prep sheet: one question at a time, read aloud, a countdown to answer it out loud
(optionally recorded and played back), then the sheet's answer as a few key points to say in your own words, and a
rating that brings the shaky ones back.

The cards come from drill.from_page, so a hand-written sheet works the same as it does for a drill video. The page
is one self-contained file (static/rehearse.html with the cards embedded): it speaks with the browser's own voice
and keeps any recording in memory, so nothing is sent anywhere and no server runs.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path

from . import drill

TEMPLATE = Path(__file__).parent / "static" / "rehearse.html"
SECONDS = 90   # the answer countdown's default; the page lets you change it


def _json(title: str, cards: list[drill.Card]) -> str:
    """The title and cards as JSON that is safe inside a <script> tag: no "<" survives, so "</script>" and "<!--"
    can't end or hide it."""
    data = {"title": title, "cards": [{"q": c.question, "a": c.answer} for c in cards]}
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def build(title: str, cards: list[drill.Card]) -> str:
    """The page's HTML, with the title and cards filled into the template."""
    fill = {"__TITLE__": _html.escape(title), "__SECONDS__": str(SECONDS), "__CARDS__": _json(title, cards)}
    # One pass, so text in a card that looks like a placeholder is never filled in itself.
    return re.sub("|".join(fill), lambda m: fill[m.group()], TEMPLATE.read_text(encoding="utf-8"))


def write(sheet: Path, out: Path | None = None) -> Path:
    """Write the rehearsal page for a hand-written prep sheet, next to it as <name>-rehearse.html unless out says
    where. Raises ValueError when the sheet has no question with an answer."""
    sheet = Path(sheet).expanduser()
    if not sheet.is_file():
        raise ValueError(f"no such prep sheet: {sheet}")
    title, cards = drill.from_page(sheet.read_text(encoding="utf-8"))
    if not cards:
        raise ValueError(f"no questions with answers in {sheet.name}: it needs a table with a Question and an "
                         "Answer column, or question headings (<h3 class=\"q\">) with a say block")
    out = Path(out).expanduser() if out else sheet.with_name(f"{sheet.stem}-rehearse.html")
    out.write_text(build(title or sheet.stem, cards), encoding="utf-8")
    return out
