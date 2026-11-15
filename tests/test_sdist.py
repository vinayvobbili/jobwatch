"""The sdist stays small: demo and tutorial videos are on GitHub and the home page, not in the PyPI download."""

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 2 * 1024 * 1024  # the sdist was 74 MB with the site's videos in it; the wheel is under 1 MB


def test_sdist_has_no_media_and_stays_small(tmp_path):
    pytest.importorskip("hatchling")
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    subprocess.run([sys.executable, "-m", "hatchling", "build", "-t", "sdist", "-d", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    (sdist,) = tmp_path.glob("jobwatch-*.tar.gz")
    with tarfile.open(sdist) as tar:
        names = tar.getnames()
    media = [n for n in names if n.endswith((".mp4", ".gif"))]
    assert not media, f"videos in the sdist: {media}"
    assert sdist.stat().st_size < LIMIT, f"sdist is {sdist.stat().st_size / 1e6:.1f} MB"
    # what a source install, the plugin and the extension builds read
    for needed in ("pyproject.toml", "README.md", "jobwatch/static/index.html", "chrome-extension/manifest.json",
                   "plugin/.claude-plugin/plugin.json"):
        assert any(n.endswith("/" + needed) for n in names), needed
