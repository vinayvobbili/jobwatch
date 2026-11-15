"""Copy the rendered videos into the repo: docs/ and site/ (posters and the tour's animated preview too).

    python scripts/videos/publish.py [--out DIR]

Overwrites docs/jobwatch-demo.mp4, site/jobwatch-demo.{mp4,jpg}, docs/demo.gif, site/demo.gif and, for each tutorial,
docs/tutorials/NAME.mp4, site/tutorials/NAME.mp4 and site/tutorials/NAME.jpg (a poster frame, 640 wide). Each video's
captions (NAME.vtt, see captions.py) go beside its mp4 in site/. `--captions-only` copies only those.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "scripts" / "demo" / "out" / "videos"
TOUR = "jobwatch-demo"
GIF_FROM, GIF_SECONDS = 28.5, 14.0  # the Today tab, after the title and the problem


def tutorial_names(out: Path) -> list[str]:
    """Rendered tutorials, in order (jobwatch-01-..., jobwatch-02-...)."""
    return sorted(p.name for p in out.glob("jobwatch-0[1-9]-*") if (p / f"{p.name}.mp4").exists())


def targets(name: str, root: Path = ROOT) -> list[Path]:
    """Where a video's mp4 goes."""
    if name == TOUR:
        return [root / "docs" / f"{name}.mp4", root / "site" / f"{name}.mp4"]
    return [root / "docs" / "tutorials" / f"{name}.mp4", root / "site" / "tutorials" / f"{name}.mp4"]


def caption_target(name: str, root: Path = ROOT) -> Path:
    """Where a video's captions go: beside its mp4 on the site."""
    return targets(name, root)[1].with_suffix(".vtt")


def frame(video: Path, dest: Path, at: float, width: int) -> None:
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={width}:-1", "-q:v", "3", str(dest)])


def gif(video: Path, dest: Path) -> None:
    filters = "fps=8,scale=800:-1:flags=lanczos"
    palette = "split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(GIF_FROM), "-t", str(GIF_SECONDS), "-i", str(video), "-vf",
         f"{filters},{palette}", str(dest)])


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--captions-only", action="store_true", help="copy only the captions (the .vtt files)")
    args = ap.parse_args(argv)
    names = ([TOUR] if (args.out / TOUR / f"{TOUR}.mp4").exists() else []) + tutorial_names(args.out)
    for name in names:
        video = args.out / name / f"{name}.mp4"
        captions = args.out / name / f"{name}.vtt"
        if captions.exists():
            shutil.copyfile(captions, caption_target(name))
        if args.captions_only:
            print(f"published {name}'s captions")
            continue
        for dest in targets(name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(video, dest)
        site = ROOT / "site"
        if name == TOUR:
            frame(video, site / f"{name}.jpg", 1.5, 960)
            gif(video, ROOT / "docs" / "demo.gif")
            shutil.copyfile(ROOT / "docs" / "demo.gif", site / "demo.gif")
        else:
            frame(video, site / "tutorials" / f"{name}.jpg", 1.5, 640)
        print(f"published {name}")


if __name__ == "__main__":
    main()
