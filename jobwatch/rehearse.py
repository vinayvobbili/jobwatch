"""A rehearsal page from a prep sheet: one question at a time, read aloud, a countdown to answer it out loud
(optionally recorded and played back), then the sheet's answer as a few key points to say in your own words, and a
rating that brings the shaky ones back.

The cards come from drill.from_page, so a hand-written sheet works the same as it does for a drill video. The page
is one self-contained file (static/rehearse.html with the cards embedded): it speaks with the browser's own voice
and keeps any recording in memory.

Its mic ("Say it") is the one exception to staying on the page: when `jobwatch ui` runs, the recording goes to it
(/rehearse/transcribe), and from it only to the speech-to-text endpoint (the watchlist's speech.url, see speech.py);
nothing is kept. How it sounded is counted here, in code (feedback): pace, filler words, length against the target,
whether the first sentence is a headline, the sheet answer's key terms said or missed, and long pauses. Each try's
numbers stay in the browser, so a card shows the trend.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path

from . import APP_HOST, drill, mock

TEMPLATE = Path(__file__).parent / "static" / "rehearse.html"
SECONDS = 90   # the answer countdown's default; the page lets you change it
UI = f"http://{APP_HOST}:8765"  # where `jobwatch ui` listens by default; the page's mic posts to it

TARGET = mock.TARGET        # seconds a story should run
PACE = mock.PACE            # words a minute that sound natural
HEADLINE_WORDS = 20         # a first sentence longer than this buries the point
PAUSE = 2.0                 # seconds of silence between segments that count as a long pause
MOST_TERMS = 12             # key terms taken from the sheet's answer, longest first
# A first sentence that opens like this is clearing the throat, not stating the point.
_WARMUP = re.compile(r"^\W*(?:so|well|okay|ok|um+|uh+|yeah|right|great question|that's a (?:great|good) question|"
                     r"let me (?:think|start)|i think|i guess|basically|honestly)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# Words that carry no point of their own in a spoken answer.
_STOP = set("""i me my mine we us our you your he she they them their it its this that these those
a an the and or but so if then than as at by for from in into of on onto to up with without about over under
was were is are be been being am do does did done have has had having can could would should will shall may might
must just also very really quite much many more most some any all each every both few other such only own same
not no nor too again there here when where why how what which who whom whose while because until after before
during through between out off down once one two three get got make made take took went go going gone say said
like know thing things lot lots kind sort way ways time times yes yeah okay ok um uh well right""".split())


def _json(title: str, cards: list[drill.Card]) -> str:
    """The title and cards as JSON that is safe inside a <script> tag: no "<" survives, so "</script>" and "<!--"
    can't end or hide it."""
    data = {"title": title, "cards": [{"q": c.question, "a": c.answer} for c in cards]}
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def build(title: str, cards: list[drill.Card], ui: str = UI) -> str:
    """The page's HTML, with the title and cards filled into the template. ui is `jobwatch ui`'s address, which the
    mic sends recordings to."""
    fill = {"__TITLE__": _html.escape(title), "__SECONDS__": str(SECONDS), "__CARDS__": _json(title, cards),
            "__UI__": json.dumps(ui.rstrip("/")).replace("<", "\\u003c")}
    # One pass, so text in a card that looks like a placeholder is never filled in itself.
    return re.sub("|".join(fill), lambda m: fill[m.group()], TEMPLATE.read_text(encoding="utf-8"))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'+#.-]*[a-z0-9+#]|[a-z0-9]", text.lower())


def _stem(word: str) -> str:
    """A crude stem, so a plural or a tense still counts: numbers as they are, else without an -s, -ed or -ing
    ending or a final e (queue and queues meet), cut to six letters."""
    word = word.removesuffix("'s").replace("'", "")
    if word[:1].isdigit():
        return word
    return (re.sub(r"e$", "", re.sub(r"(?:ing|ed|s)$", "", word)) if len(word) > 4 else word)[:6]


def terms(answer: str, most: int = MOST_TERMS) -> list[str]:
    """The sheet answer's key terms: its content words (no stop words, three letters or more) and numbers, in the
    order they come, keeping the `most` longest (a number always counts: it's the result to say)."""
    seen: dict[str, str] = {}
    for w in _words(answer):
        w = w.removesuffix("'s")
        if w in _STOP or "'" in w or (len(w) < 3 and not w[:1].isdigit()):
            continue   # a contraction (can't, we're) is never the point
        seen.setdefault(_stem(w), w)
    order = list(seen.values())
    keep = set(sorted(order, key=lambda w: (not w[:1].isdigit(), -len(w)))[:most])
    return [w for w in order if w in keep]


def _headline(transcript: str, answer: str, segments: list | None = None) -> dict:
    """{sentence, words, ok, why}: whether the first sentence is a headline, short and on the point (it shares a
    key term with the sheet answer's own first sentence, or with the answer when that has none). A transcript with
    no sentence ends (speech-to-text sometimes leaves them out) takes its first segment, the first phrase said."""
    first = (_SENTENCE.split(transcript.strip(), 1) or [""])[0].strip()
    if not re.search(r"[.!?]", transcript) and segments:
        first = str(segments[0].get("text") or "").strip() or first
    n = len(first.split())
    lead = terms((_SENTENCE.split(answer.strip(), 1) or [""])[0]) or terms(answer)
    said = {_stem(w) for w in _words(first)}
    on_point = not lead or any(_stem(t) in said for t in lead)
    why = []
    if not first:
        why.append("nothing was said")
    else:
        if _WARMUP.match(first):
            why.append("it opens with a warm-up; lead with the point")
        if n > HEADLINE_WORDS:
            why.append(f"{n} words; keep the first sentence under {HEADLINE_WORDS}")
        if not on_point:
            why.append("it doesn't say the point yet (" + ", ".join(lead[:3]) + ")")
    return {"sentence": first, "words": n, "ok": not why, "why": "; ".join(why)}


def _pauses(segments: list) -> list[dict]:
    """Silences of PAUSE seconds or more between segments: {at (seconds in), seconds, after (the words before)}."""
    out, last = [], None
    for s in segments:
        if not isinstance(s, dict):
            continue
        try:
            start, end = float(s.get("start")), float(s.get("end"))
        except (TypeError, ValueError):
            continue
        if last is not None and start - last[0] >= PAUSE:
            words = str(last[1] or "").split()
            out.append({"at": round(last[0], 1), "seconds": round(start - last[0], 1),
                        "after": " ".join(words[-6:])})
        last = (end, s.get("text"))
    return out


def feedback(transcript: str, answer: str, seconds: float = 0, segments: list | None = None,
             target: tuple[int, int] = TARGET) -> dict:
    """How a spoken try sounded, counted in code (no model): {words, seconds, wpm, pace (slow, ok, fast or
    untimed), pace_target, fillers {word: count}, filler_count, length (short, ok, long or untimed), target,
    headline {...}, terms {hit, missed, coverage (percent)}, pauses [...], timed_pauses (whether the transcript gave
    timestamps), tips [what to change, most important first]}. answer is the sheet's answer to the same question."""
    row = mock.delivery({"answer": transcript, "seconds": seconds})
    seconds = row["seconds"]
    length = "untimed" if seconds < 1 else "short" if seconds < target[0] else "long" if seconds > target[1] else "ok"
    wpm = row["wpm"]
    pace = "untimed" if wpm is None else "slow" if wpm < PACE[0] else "fast" if wpm > PACE[1] else "ok"
    key = terms(answer)
    said = {_stem(w) for w in _words(transcript)}
    hit = [t for t in key if _stem(t) in said]
    missed = [t for t in key if _stem(t) not in said]
    timed = [s for s in segments or [] if isinstance(s, dict) and "start" in s and "end" in s]
    pauses = _pauses(timed)
    head = _headline(transcript, answer, timed)
    tips = []
    if not head["ok"]:
        tips.append("Open with a headline: " + head["why"] + ".")
    if missed and len(hit) * 2 < len(key):
        tips.append("Say the key points: " + ", ".join(missed[:5]) + ".")
    if length == "short":
        tips.append(f"Run longer: {round(seconds)} s, aim for {target[0]} to {target[1]} s.")
    elif length == "long":
        tips.append(f"Tighten it: {round(seconds)} s, aim for {target[0]} to {target[1]} s.")
    if row["filler_count"] >= 3:
        top = sorted(row["fillers"].items(), key=lambda kv: -kv[1])[0][0]
        tips.append(f"{row['filler_count']} filler words (mostly \"{top}\"): pause instead.")
    if pace == "fast":
        tips.append(f"Slow down: {wpm} words a minute, aim for {PACE[0]} to {PACE[1]}.")
    elif pace == "slow":
        tips.append(f"Pick up the pace: {wpm} words a minute, aim for {PACE[0]} to {PACE[1]}.")
    if len(pauses) >= 2:
        tips.append(f"{len(pauses)} long pauses: know the next beat of the story before you start.")
    return {"words": row["words"], "seconds": seconds, "wpm": wpm, "pace": pace, "pace_target": list(PACE),
            "fillers": row["fillers"],
            "filler_count": row["filler_count"], "length": length, "target": list(target), "headline": head,
            "terms": {"hit": hit, "missed": missed, "coverage": round(100 * len(hit) / len(key)) if key else None},
            "pauses": pauses, "timed_pauses": bool(timed), "tips": tips}


def write(sheet: Path, out: Path | None = None, ui: str = UI) -> Path:
    """Write the rehearsal page for a hand-written prep sheet, next to it as <name>-rehearse.html unless out says
    where; its mic sends recordings to `jobwatch ui` at ui. Raises ValueError when the sheet has no question with an
    answer."""
    sheet = Path(sheet).expanduser()
    if not sheet.is_file():
        raise ValueError(f"no such prep sheet: {sheet}")
    title, cards = drill.from_page(sheet.read_text(encoding="utf-8"))
    if not cards:
        raise ValueError(f"no questions with answers in {sheet.name}: it needs a table with a Question and an "
                         "Answer column, or question headings (<h3 class=\"q\">) with a say block")
    out = Path(out).expanduser() if out else sheet.with_name(f"{sheet.stem}-rehearse.html")
    out.write_text(build(title or sheet.stem, cards, ui), encoding="utf-8")
    return out
