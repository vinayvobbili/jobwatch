"""scripts/check_videos.py: reading the videos off a rendered page, and telling a faststart MP4 from one that isn't."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_videos.py"


@pytest.fixture
def check():
    spec = importlib.util.spec_from_file_location("check_videos", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_video_urls_unescaped_in_order_once_each(check):
    a = "https://private-user-images.example/1/9-11111111-2222-3333-4444-555555555555.mp4?jwt=x&amp;y=1"
    b = "https://private-user-images.example/1/9-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp4?jwt=z"
    page = (f'<p><video src="{a}" controls></video></p><video muted src="{b}"></video>'
            f'<video src="{a.replace("jwt=x", "jwt=other")}"></video><img src="{b}">')
    assert check.video_urls(page) == [a.replace("&amp;", "&"), b]


def box(kind: bytes, body: bytes = b"") -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def test_faststart_is_moov_before_mdat(check):
    assert check.faststart(box(b"ftyp", b"isom") + box(b"moov", b"x" * 20) + box(b"mdat", b"y" * 50))
    assert not check.faststart(box(b"ftyp", b"isom") + box(b"mdat", b"y" * 50) + box(b"moov"))
    assert not check.faststart(b"\x00\x00\x00\x02junk")
