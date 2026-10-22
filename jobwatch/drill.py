"""A drill video from a prep sheet: each question asked in one voice, a silent hold to answer it out loud, then
the answer's cue words on screen while a second voice gives the full answer.

Answers come only from what the sheet already holds: answers tightened in mock interviews, drafted outlines with
the stories they cite (stories.yaml), or, for a prep sheet written by hand, its question-and-answer tables. A
question with no answer is left out, never filled in.

The video is made with slidecast (pip install 'jobwatch[video]'): Kokoro speaks on this computer and a headless
browser draws the slides, so nothing is sent anywhere.
"""

from __future__ import annotations

import html as _html
import importlib.util
import re
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .prep import Sheet
from .stories import Story

PAUSE = 75.0                 # seconds to answer out loud; --pause changes it, --no-pause drops it
INTERVIEWER = "am_michael"   # Kokoro voices: one asks, the other answers
ANSWERER = "af_heart"
WIDTH, HEIGHT = 1280, 720
MOST_CUES = 5
CUE_WORDS = 7
_TAG = re.compile(r"^\[(\w+)\] ")
_VOID = ("br", "img", "hr", "meta", "link", "input", "col", "source", "wbr")
_CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium")


@dataclass(frozen=True)
class Card:
    question: str
    answer: str              # spoken in full, by the second voice
    cues: tuple[str, ...]    # on screen while it's spoken


@dataclass(frozen=True)
class Segment:
    """One slide as slidecast gets it: the page, who speaks (none for a silent hold) and what they say."""
    html: str
    voice: str = ""
    line: str = ""
    hold: float = 0.0


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def cues(answer: str) -> tuple[str, ...]:
    """The first words of each sentence, to glance at while the answer is spoken."""
    out = []
    for s in _sentences(answer)[:MOST_CUES]:
        words = s.strip("\"“”'").split()
        out.append(" ".join(words[:CUE_WORDS]).rstrip(",;:") + ("…" if len(words) > CUE_WORDS else ""))
    return tuple(out)


def _point(text: str) -> str:
    text = text.strip()
    return text if re.search(r"[.!?]$", text) else text + "."


def from_sheet(sheet: Sheet, bank: list[Story]) -> list[Card]:
    """Cards from a jobwatch prep sheet: practised answers first, then drafted outlines, each told with the stories
    it cites. Questions drafted without a story, and the generic lists, have no answer to give and are left out."""
    by_id = {s.id: s for s in bank}
    cards, seen = [], set()
    for p in sheet.practised:
        cards.append(Card(p["question"], p["improved"], cues(p["improved"])))
        seen.add(p["question"].lower())
    for d in sheet.drafted:
        if d["no_story"] or not d["outline"] or d["question"].lower() in seen:
            continue
        told = [f"{st.did} The hard part: {st.hard} {_point(st.result)}" for c in d["stories"]
                if (st := by_id.get(c["id"]))]
        answer = " ".join([_point(p) for p in d["outline"]] + told)
        cards.append(Card(d["question"], answer, tuple(d["outline"][:MOST_CUES])))
        seen.add(d["question"].lower())
    return cards


class _Tables(HTMLParser):
    """The rows of a page's tables as (header cells, body rows), and its spoken answers: a question heading
    (<h3 class="q">) with the "say" block under it (<div class="say">), as its paragraphs. Text inside
    class="muted" is left out (on a hand-written sheet that's where sources and asides go, not what you'd
    say), and so is a spoken paragraph with a class="fill" blank in it (a detail only you know, not filled in)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[list[str], list[list[str]]]] = []
        self.spoken: list[tuple[str, list[str]]] = []
        self._cell: list[str] | None = None
        self._row: list[str] = []
        self._head = False
        self._stack: list[tuple[str, bool]] = []   # open elements, and whether each is muted
        self.title = ""
        self._in_title = False
        self._q: list[str] | None = None    # a question heading's text, while it's read
        self._asked = ""                    # the last question heading, until its say block
        self._say: int | None = None        # how deep the say block being read sits in _stack
        self._paras: list[str] = []
        self._para: list[str] | None = None
        self._blank = False                 # the paragraph being read has a fill-in blank

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag not in _VOID:
            self._stack.append((tag, "muted" in classes))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._say is None:
            self._asked = ""  # a heading with no say block under it answers nothing that comes after
            if tag in ("h3", "h4") and "q" in classes:
                self._q = []
        elif tag == "div" and "say" in classes and self._say is None and self._asked:
            self._say, self._paras = len(self._stack), []
        elif tag == "p" and self._say is not None:
            self._para, self._blank = [], False
        if "fill" in classes and self._para is not None:
            self._blank = True
        if tag == "table":
            self.tables.append(([], []))
        elif tag == "tr":
            self._row, self._head = [], False
        elif tag in ("td", "th"):
            self._cell, self._head = [], self._head or tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag in ("title", "h1") and not self.title:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if any(t == tag for t, _ in self._stack):  # close it, and anything left open inside it
            while self._stack.pop()[0] != tag:
                pass
        if tag in ("h3", "h4") and self._q is not None:
            self._asked, self._q = re.sub(r"\s+", " ", "".join(self._q)).strip(), None
        elif tag == "p" and self._para is not None:
            if not self._blank and (text := re.sub(r"\s+", " ", "".join(self._para)).strip()):
                self._paras.append(text)
            self._para = None
        if self._say is not None and len(self._stack) < self._say:  # the say block is closed
            if self._paras:
                self.spoken.append((self._asked, self._paras))
            self._say, self._asked = None, ""
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self.tables and self._row:
            head, rows = self.tables[-1]
            if self._head and not head:
                head.extend(self._row)
            else:
                rows.append(self._row)
        elif tag in ("title", "h1"):
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        muted = any(m for _, m in self._stack)
        if self._cell is not None and not muted:
            self._cell.append(data)
        if self._q is not None:
            self._q.append(data)
        if self._para is not None and not muted:
            self._para.append(data)


_QUOTED = re.compile(r"[\"“](.+?)[\"”]")
_NUMBERED = re.compile(r"^\d+[.)]\s*")
# A paragraph that answers a follow-up ("If she anchors on your current pay: "…"") rather than the question.
_FOLLOW_UP = re.compile(r"^[^\"“]{3,80}:\s*[\"“]")


def _spoken(question: str, paras: list[str]) -> Card | None:
    """A card from a question heading and its say block: the question as quoted in the heading (else the heading,
    unnumbered), the paragraphs that answer it with the quote marks dropped (they're for reading, not saying)."""
    q = m.group(1).strip() if (m := _QUOTED.search(question)) else _NUMBERED.sub("", question).strip()
    answer = re.sub(r"\s+", " ", re.sub(r"[\"“”]", "", " ".join(p for p in paras if not _FOLLOW_UP.match(p)))).strip()
    return Card(q, answer, cues(answer)) if q and answer else None


def from_page(text: str) -> tuple[str, list[Card]]:
    """(title, cards) from a hand-written prep sheet's HTML: every table whose header has a "Question" column and
    an "Answer" column gives one card a row, then every spoken answer (a question heading with a say block; see
    _Tables) one card. A question asked twice keeps its first answer."""
    page = _Tables()
    page.feed(text)
    cards, seen = [], set()
    for head, rows in page.tables:
        low = [h.lower() for h in head]
        q = next((i for i, h in enumerate(low) if "question" in h), None)
        a = next((i for i, h in enumerate(low) if "answer" in h), None)
        if q is None or a is None:
            continue
        for row in rows:
            if max(q, a) >= len(row):
                continue
            question, answer = row[q], row[a].strip().strip("\"“”").strip()
            if question and answer and question.lower() not in seen:
                seen.add(question.lower())
                cards.append(Card(question, answer, cues(answer)))
    for question, paras in page.spoken:
        if (card := _spoken(question, paras)) and card.question.lower() not in seen:
            seen.add(card.question.lower())
            cards.append(card)
    return page.title.strip(), cards


# A gradient per question, so each one looks different from the last.
THEMES = (("#ff6b6b", "#feca57"), ("#5f27cd", "#48dbfb"), ("#0abde3", "#10ac84"), ("#ee5253", "#a55eea"),
          ("#ff9f43", "#ee5253"), ("#1dd1a1", "#2e86de"), ("#f368e0", "#ff9f43"), ("#341f97", "#ff6b6b"),
          ("#00d2d3", "#5f27cd"), ("#feca57", "#10ac84"), ("#2e86de", "#f368e0"))
_CSS = f"body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;" + """overflow:hidden;display:flex;align-items:center;
justify-content:center;position:relative;color:#1d1d2b;background:linear-gradient(135deg,var(--a),var(--b));
font-family:-apple-system,"Segoe UI",Helvetica,sans-serif}
.blob{position:absolute;border-radius:50%;opacity:.25;background:#fff}
.b1{width:520px;height:520px;top:-200px;right:-140px}.b2{width:300px;height:300px;bottom:-120px;left:-80px}
.card{position:relative;width:1060px;background:rgba(255,255,255,.94);border-radius:28px;padding:44px 56px;
box-shadow:0 30px 60px rgba(0,0,0,.25)}
.pill{display:inline-block;background:linear-gradient(90deg,var(--a),var(--b));color:#fff;font-weight:700;
font-size:20px;letter-spacing:1.5px;text-transform:uppercase;padding:8px 18px;border-radius:999px;margin-bottom:18px}
h1{font-size:44px;line-height:1.2;margin:0 0 20px;font-weight:800}.q{font-size:26px;color:#5d5d78;margin:0 0 22px}
.big{font-size:60px;font-weight:800;margin:0 0 14px;color:var(--a);filter:brightness(.85)}
ul{list-style:none;margin:0;padding:0}
li{font-size:28px;line-height:1.35;margin:0 0 12px;padding-left:44px;position:relative;color:#33334d}
li:before{content:"";position:absolute;left:0;top:6px;width:24px;height:24px;border-radius:8px;
background:linear-gradient(135deg,var(--a),var(--b))}
.bar{position:absolute;left:0;bottom:0;height:10px;background:rgba(255,255,255,.9);width:var(--p)}"""


def _page(label: str, body: str, n: int = 0, total: int = 1) -> str:
    """A slide: a white card on question n's gradient, with a bar along the bottom for how far along it is."""
    a, b = THEMES[n % len(THEMES)]
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head>"
            f"<body style='--a:{a};--b:{b};--p:{100 * n / max(total, 1):.0f}%'>"
            "<div class='blob b1'></div><div class='blob b2'></div>"
            f"<div class='card'><div class='pill'>{_html.escape(label)}</div>{body}</div>"
            "<div class='bar'></div></body></html>")


def segments(cards: list[Card], title: str, pause: float = PAUSE) -> list[Segment]:
    """What slidecast gets, in order: a title, then for each card the question, the hold (unless pause is 0) and
    the answer with its cues."""
    e = _html.escape
    how = (f"Answer each one out loud in the {pause:g} seconds after it's asked, then hear the answer."
           if pause else "A quick review: each question, then its answer.")
    out = [Segment(_page("Drill", f"<h1>{e(title)}</h1><p class='q'>{len(cards)} questions. {e(how)}</p>"),
                   INTERVIEWER, f"{len(cards)} questions. {how}")]
    total = len(cards)
    for n, c in enumerate(cards, 1):
        label = f"Question {n} of {total}"
        out.append(Segment(_page(label, f"<h1>{e(c.question)}</h1>", n, total), INTERVIEWER, c.question))
        if pause:
            out.append(Segment(_page(label, f"<p class='big'>Answer out loud</p><p class='q'>{e(c.question)}</p>"
                                            f"<p class='q'>{pause:g} seconds</p>", n, total), hold=pause))
        bullets = "".join(f"<li>{e(x)}</li>" for x in c.cues)
        out.append(Segment(_page(label + " · answer", f"<p class='q'>{e(c.question)}</p><ul>{bullets}</ul>", n,
                                 total), ANSWERER, c.answer))
    return out


class Voices:
    """One Kokoro model speaking each line in the voice its tag names ("[af_heart] Hello.")."""

    def __init__(self, tts):
        self.tts = tts

    def synthesize(self, text: str, out_path: Path) -> float:
        m = _TAG.match(text)
        if m:
            self.tts.voice, text = m.group(1), text[m.end():]
        return self.tts.synthesize(text, out_path)


def _renderer():
    """slidecast's Playwright renderer when it's installed, otherwise a Chrome already on this computer."""
    if importlib.util.find_spec("playwright"):
        return None
    from slidecast import ChromeBinaryRenderer
    chrome = next((p for p in _CHROME if Path(p).exists()), None) or shutil.which("google-chrome") \
        or shutil.which("chromium")
    if not chrome:
        raise SystemExit("a drill needs a browser to draw its slides: pip install 'slidecast[playwright]' "
                         "(then: playwright install chromium), or install Chrome")
    return ChromeBinaryRenderer(chrome)


def render(segs: list[Segment], out: Path, tts=None, renderer=None) -> Path:
    """Write the video. tts and renderer default to Kokoro on this computer and _renderer(); tests pass fakes."""
    if importlib.util.find_spec("slidecast") is None:
        raise SystemExit("a drill video needs slidecast: pip install 'jobwatch[video]'")
    from slidecast import MLXKokoroTTS, Reel
    # A soft bed that dips under the voices, with a chime either end; slidecast composes them here, with numpy.
    reel = Reel(width=WIDTH, height=HEIGHT, tts=Voices(tts or MLXKokoroTTS()),
                renderer=renderer if renderer is not None else _renderer(),
                music="compose", intro="compose", outro="compose", loudness=-16)
    for s in segs:
        if s.voice:
            reel.add(s.html, f"[{s.voice}] {s.line}", tail_pad=0.8)
        else:
            reel.add(s.html, "", min_duration=s.hold)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written beside it, then put in its place: a render stopped part way leaves the last good video, not a broken one.
    part = out.with_name(f".{out.stem}.part{out.suffix}")
    try:
        reel.render(part)
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    return out
