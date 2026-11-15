"""WebVTT captions for the videos, from each video's narration and the lengths of its rendered segments.

    python scripts/videos/captions.py [NAME ...] [--out DIR]   # write NAME.vtt next to each rendered video

build.py calls `write_for` after every render, so a rebuilt video gets fresh captions. This command writes them for
videos already rendered, without rendering anything: it reads the segments' lengths (sNNN.mkv) and the spoken lines'
lengths (sNNN.wav) that the render left in OUT/videos/NAME/work. The captions follow what the voice said then, so
write them before editing a narration, and rebuild the video after.

A reel is: a silent title card, the problem, the tagline, one segment per scene, and the title card again. Each
segment's narration starts with the segment; its words are spread over the spoken line's length, a sentence at a time
(a long sentence is cut at its commas, then at spaces), in proportion to the letters each cue holds.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "demo" / "out" / "videos"
MAX_CHARS = 80  # a cue is at most this many letters: two short lines, never a paragraph


def narrations(video, tagline: str) -> list[str]:
    """What each segment of the reel says, in order ("" for a silent card)."""
    return ["", video.problem_say, tagline, *(scene.say for scene in video.scenes), ""]


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """The text in cues of at most `limit` letters: sentence by sentence, a long one at its commas, then at spaces."""
    cues: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        if len(sentence) <= limit:
            cues.append(sentence)
            continue
        pieces = [p for p in re.split(r"(?<=[,:;])\s+", sentence) if p]
        line = ""
        for piece in pieces:
            for chunk in wrap(piece, limit):
                if line and len(line) + 1 + len(chunk) <= limit:
                    line += " " + chunk
                else:
                    if line:
                        cues.append(line)
                    line = chunk
        if line:
            cues.append(line)
    return cues


def wrap(text: str, limit: int) -> list[str]:
    """`text` cut at spaces into chunks of at most `limit` letters (a word longer than that stays whole)."""
    chunks, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > limit:
            chunks.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*chunks, line] if line else chunks


def cues_for(text: str, start: float, seconds: float) -> list[tuple[float, float, str]]:
    """(start, end, text) cues for a line spoken from `start` for `seconds`, the time shared by letters."""
    parts = split_text(text)
    total = sum(len(p) for p in parts)
    cues, at = [], start
    for part in parts:
        end = at + seconds * len(part) / total
        cues.append((at, end, part))
        at = end
    return cues


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def vtt(cues: list[tuple[float, float, str]]) -> str:
    """The cues as a WebVTT file."""
    body = "\n".join(f"{timestamp(a)} --> {timestamp(b)}\n{text}\n" for a, b, text in cues)
    return "WEBVTT\n\n" + body


def captions(lines: list[str], lengths: list[float], speech: list[float]) -> str:
    """The captions of a reel: `lines` the narrations, `lengths` the segments' lengths, `speech` the spoken lengths."""
    if not len(lines) == len(lengths) == len(speech):
        raise ValueError(f"{len(lines)} narrations, {len(lengths)} segments, {len(speech)} spoken lines")
    cues, clock = [], 0.0
    for text, length, spoken in zip(lines, lengths, speech, strict=True):
        if text.strip():
            cues += cues_for(text, clock, min(spoken, length))
        clock += length
    return vtt(cues)


def seconds_of(path: Path) -> float:
    """A media file's length."""
    run = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(run.stdout.strip())


def write_for(video, tagline: str, where: Path) -> Path:
    """Write `where`/NAME.vtt for a rendered video from its work folder (`where`/work); returns the path."""
    work = where / "work"
    lines = narrations(video, tagline)
    lengths = [seconds_of(work / f"s{i:03d}.mkv") for i in range(1, len(lines) + 1)]
    speech = [seconds_of(work / f"s{i:03d}.wav") if text.strip() else 0.0
              for i, text in enumerate(lines, 1)]
    out = where / f"{video.name}.vtt"
    out.write_text(captions(lines, lengths, speech), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import TAGLINE
    from stories import VIDEOS as TOUR
    from tutorials import TUTORIALS

    videos = {**TOUR, **TUTORIALS}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help=f"which videos (default all): {', '.join(videos)}")
    ap.add_argument("--out", type=Path, default=OUT, help="where the videos were rendered")
    args = ap.parse_args(argv)
    unknown = [n for n in args.names if n not in videos]
    if unknown:
        sys.exit(f"no such video: {', '.join(unknown)}")
    for name in args.names or list(videos):
        print(f"Wrote {write_for(videos[name], TAGLINE, args.out.expanduser().resolve() / name)}")


if __name__ == "__main__":
    main()
