"""Record and render jobwatch's videos: the 1.5-minute tour and the seven tutorials.

    python scripts/videos/build.py --dry                  # screenshots of every scene: check framing, cheaply
    python scripts/videos/build.py [NAME ...] [--out DIR] # record and render (default: every video)
    python scripts/videos/build.py --clips-only           # record the clips, render nothing

Each scene is a screen recording of the real `jobwatch ui` (or the extension's side panel) on made-up data: a cursor
glides to each target, clicks ripple, and nothing may be cut off at the frame's edges (slidecast's framing check
fails the scene). The story, in slidecast's shape: a silent title card, the problem, the tagline at the turn, the
walkthrough, and the title card again. Writes OUT/videos/NAME/ (clips, the video, its poster and its captions,
NAME.vtt) and, for the tour, a 1440p `-youtube.mp4`. See scripts/videos/README.md.
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import sys
from pathlib import Path

import captions
import cards
from common import TAGLINE, Scene, Video, cue_times, demo_running, problem_seconds, seconds_to_say
from slidecast import MLXKokoroTTS, Music, Reel, Sting
from slidecast.recorder import Recorder

OUT = Path(__file__).resolve().parent.parent / "demo" / "out"
PHONETIC = {r"\bjobwatch\b": "job watch", r"\bMCP\b": "M C P", r"\bAPI\b": "A P I", r"\bLinkedIn\b": "LinkedIn"}
TITLE_SECONDS = 3.0
PROBLEM_SECONDS = 7.0


def record_scene(demo, scene: Scene, clip: Path | None, shots: Path | None) -> None:
    """Record one scene to `clip` (or, with `shots`, only screenshot it). The clip lasts as long as its narration."""
    with Recorder.open(demo.browser, scene.url(demo), clip, shots=shots, pace=1.0) as rec:
        if scene.run:
            scene.run(rec, demo)
        rec.hold_until(max(scene.min_seconds, seconds_to_say(scene.say)))


def record(video: Video, work: Path, dry: bool) -> list[Path]:
    """Record every scene of the video; returns the clips (empty for a dry run, which writes screenshots)."""
    clips: list[Path | None] = [None] * len(video.scenes)  # None: a card, not a recording
    raw = None if dry else work / video.name / "raw"  # the extension's browser records into this folder
    if raw:
        shutil.rmtree(raw, ignore_errors=True)
        raw.mkdir(parents=True)
    numbered = [(i, s) for i, s in enumerate(video.scenes, 1) if not s.html]
    # Consecutive scenes on the same demo share one running copy of it.
    for kind, group in itertools.groupby(numbered, key=lambda item: video.kind(item[1])):
        with demo_running(more=kind == "more", empty=kind == "empty", extension=video.extension, record=raw) as demo:
            for i, scene in group:
                name = f"{i:02d}-{scene.name or 'scene'}"
                print(f"  {video.name}: scene {name}", flush=True)
                if dry:
                    record_scene(demo, scene, None, work / "dry" / video.name / name)
                else:
                    clips[i - 1] = work / video.name / "clips" / f"{name}.mp4"
                    record_scene(demo, scene, clips[i - 1], None)
    return clips


def assemble(video: Video, clips: list[Path], work: Path, music: Path | None, youtube: bool) -> Path:
    """The reel: title card, problem, tagline, the clips with their narration, and the title card again."""
    where = work / video.name
    tts = MLXKokoroTTS(voice="af_heart", phonetic=PHONETIC)
    options = {}
    if music:
        options = {"music": Music(str(music / "music_bed.wav"), volume=0.3, fade_in=1.0, fade_out=3.0, duck=True,
                                  duck_db=16),
                   "intro": Sting(str(music / "intro_sting.wav"), volume=0.75),
                   "outro": Sting(str(music / "outro_sting.wav"), volume=0.7)}
    reel = Reel(width=1920, height=1080, fps=25, tts=tts, lead_in=0, loudness=-16, theme=cards.THEME, **options)
    reel.title_card(cards.title_card(video.subtitle), seconds=TITLE_SECONDS)
    seconds = problem_seconds(video.problem_say, PROBLEM_SECONDS)
    delays = cue_times(video.problem_say, video.problem_cues) if video.problem_cues else None
    reel.problem(cards.problem_scene(video.problem, seconds, delays), video.problem_say, seconds=seconds)
    reel.tagline(TAGLINE)
    for scene, clip in zip(video.scenes, clips, strict=True):
        if clip is None:
            reel.add_animated(scene.html, scene.say, seconds=scene.seconds, tail_pad=0.3)
        else:
            reel.add_clip(clip, scene.say, tail_pad=0.3)
    out = where / f"{video.name}.mp4"
    reel.render(out, make_poster=True, workdir=where / "work", youtube=youtube)
    captions.write_for(video, TAGLINE, where)
    return out


def main() -> None:
    from stories import VIDEOS as TOUR
    from tutorials import TUTORIALS

    VIDEOS = {**TOUR, **TUTORIALS}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help=f"which videos (default all): {', '.join(VIDEOS)}")
    ap.add_argument("--out", type=Path, default=OUT / "videos", help="where to write (git ignores the default)")
    ap.add_argument("--dry", action="store_true", help="screenshot each scene instead of recording and rendering")
    ap.add_argument("--clips-only", action="store_true", help="record the clips but don't render the videos")
    ap.add_argument("--music", type=Path, default=OUT, metavar="DIR",
                    help="the folder with music_bed.wav, intro_sting.wav, outro_sting.wav (default: the demo's out/)")
    args = ap.parse_args()
    names = args.names or list(VIDEOS)
    unknown = [n for n in names if n not in VIDEOS]
    if unknown:
        sys.exit(f"no such video: {', '.join(unknown)}")
    work = args.out.expanduser().resolve()
    music = args.music if all((args.music / f).is_file() for f in ("music_bed.wav", "intro_sting.wav",
                                                                    "outro_sting.wav")) else None
    for name in names:
        video = VIDEOS[name]
        if not args.dry:
            shutil.rmtree(work / name / "clips", ignore_errors=True)
        clips = record(video, work, args.dry)
        if args.dry or args.clips_only:
            continue
        out = assemble(video, clips, work, music, youtube=name == "jobwatch-demo")
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
