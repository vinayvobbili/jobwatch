"""The demo video's frame layout: a step's encode reads only the step's own frames. The first frame of the next step
(another size: a full-stage page is taller than the form) used to slip into the sequence now and then and stop the
encode with "Padded dimensions cannot be smaller than input dimensions"."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "chrome-extension" / "tools"
FFMPEG = shutil.which("ffmpeg")

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")


@pytest.fixture
def demo_video(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    sys.modules.pop("demo_video", None)
    import demo_video

    return demo_video


def frame(path: Path, size: tuple) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s={size[0]}x{size[1]}",
                    "-frames:v", "1", str(path)], check=True)


@pytest.fixture
def recorded(tmp_path):
    """Frames 0-5: a step of three form frames (3-5 are 88x66), after a step of taller full-stage pages (0-2), and
    one more taller page right after it (6)."""
    frames = tmp_path / "frames"
    frames.mkdir()
    for n in range(7):
        frame(frames / f"form_{n:05d}.png", (88, 66) if 3 <= n <= 5 else (128, 71))
    return frames


def test_the_step_gets_only_its_own_frames_numbered_from_zero(demo_video, recorded, tmp_path):
    step = demo_video.Step("fill", "", first_frame=3, frames=3)
    own = demo_video.link_step_frames(recorded, step, ("form_%05d.png",), tmp_path / "own")
    assert sorted(p.name for p in own.iterdir()) == ["form_00000.png", "form_00001.png", "form_00002.png"]
    assert (own / "form_00000.png").resolve() == (recorded / "form_00003.png").resolve()


def test_the_step_encodes_through_a_pad_sized_for_its_own_frames(demo_video, recorded, tmp_path):
    step = demo_video.Step("fill", "", first_frame=3, frames=3)
    own = demo_video.link_step_frames(recorded, step, ("form_%05d.png",), tmp_path / "own")
    out = tmp_path / "out.mp4"
    done = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", "5", "-i", str(own / "form_%05d.png"),
                           "-vf", "pad=88:66:0:0", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    counted = subprocess.run([FFMPEG, "-i", str(out), "-f", "null", "-"], capture_output=True, text=True).stderr
    assert "frame=    3" in counted


def test_the_old_start_number_read_ran_on_into_the_next_step(recorded, tmp_path):
    """What the fix avoids: from frame 3 with no end, the sequence carries on into the taller page and the pad fails."""
    done = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", "5", "-start_number", "3",
                           "-i", str(recorded / "form_%05d.png"), "-vf", "pad=88:66:0:0", str(tmp_path / "o.mp4")],
                          capture_output=True, text=True)
    assert done.returncode != 0 and "Padded dimensions cannot be smaller" in done.stderr
