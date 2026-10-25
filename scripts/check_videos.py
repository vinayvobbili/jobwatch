"""Check every video the README shows on GitHub: it downloads, plays to the end, and is the file we made.

    python scripts/check_videos.py                        # the repo page, logged out
    python scripts/check_videos.py --page URL             # another page (a guide page on github.com)

GitHub renders each user-attachments link as a <video> whose src is a short-lived signed URL, so the page is
fetched fresh and each video downloaded at once. Each is probed with ffprobe (duration of the container and of
each stream, whether the moov atom comes first so a browser can start playing before the end arrives) and
matched by content to docs/tutorials/*.mp4 and docs/jobwatch-demo.mp4. Exits 1 when one fails to download or probe.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = "https://github.com/vinayvobbili/jobwatch"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
ASSET = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def video_urls(page: str) -> list[str]:
    """Each <video>'s src on a rendered page, unescaped, in page order, once each (by asset id)."""
    seen, urls = set(), []
    for src in re.findall(r'<video\b[^>]*\bsrc="([^"]+)"', page):
        src = html.unescape(src)
        key = (ASSET.search(src) or [src])[0]
        if key not in seen:
            seen.add(key)
            urls.append(src)
    return urls


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        return r.read()


def faststart(data: bytes) -> bool:
    """True when the moov box comes before mdat (a browser can play while the rest downloads)."""
    i = 0
    while i + 8 <= len(data):
        size, kind = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
        if kind in (b"moov", b"mdat"):
            return kind == b"moov"
        if size == 1:
            size = int.from_bytes(data[i + 8:i + 16], "big")
        if size < 8:
            return False
        i += size
    return False


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "ffprobe failed")
    info = json.loads(out.stdout)
    streams = {s["codec_type"]: float(s.get("duration") or 0) for s in info.get("streams", [])}
    return {"duration": float(info["format"]["duration"]), **streams}


def local_files() -> dict[str, str]:
    """sha256 → path, for the videos we made."""
    files = [*sorted((ROOT / "docs" / "tutorials").glob("*.mp4")), ROOT / "docs" / "jobwatch-demo.mp4"]
    return {hashlib.sha256(f.read_bytes()).hexdigest(): str(f.relative_to(ROOT)) for f in files if f.exists()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", default=PAGE)
    args = ap.parse_args(argv)
    urls = video_urls(fetch(args.page).decode("utf-8", "replace"))
    if not urls:
        print(f"no videos on {args.page}")
        return 1
    ours, bad = local_files(), 0
    with tempfile.TemporaryDirectory() as tmp:
        for n, url in enumerate(urls, 1):
            asset = (ASSET.search(url) or ["?"])[0]
            try:
                data = fetch(url)
                path = Path(tmp) / f"{n}.mp4"
                path.write_bytes(data)
                p = probe(path)
            except Exception as e:  # report each video and go on
                bad += 1
                print(f"{n}. {asset}  FAILED: {e}")
                continue
            match = ours.get(hashlib.sha256(data).hexdigest(), "not one of ours (re-encoded or another file)")
            streams = "  ".join(f"{k} {v:.1f}s" for k, v in p.items() if k != "duration")
            start = "moov first" if faststart(data) else "moov at the end"
            print(f"{n}. {asset}  {len(data) / 1e6:.1f} MB  {p['duration']:.1f}s ({streams})  {start}  = {match}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
