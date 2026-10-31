"""Render the extension's toolbar/store icons (a check mark on jobwatch's violet gradient tile).

    python chrome-extension/tools/make_icons.py            # writes chrome-extension/icons/

Pure standard library, so it runs anywhere Python does. Rerun it after changing the shape or colours;
the PNGs it writes are committed.
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path

SIZES = (16, 32, 48, 128)
ICONS_DIR = Path(__file__).resolve().parents[1] / "icons"
CORNER = 0.28  # corner radius as a fraction of the tile
STROKE = 0.08  # half-width of the check stroke
CHECK = ((0.26, 0.52), (0.43, 0.69), (0.75, 0.33))  # polyline, unit coordinates
SUPERSAMPLE = 4
FROM, TO = (90, 92, 242), (162, 74, 240)  # the gradient jobwatch's own icon uses


def _segment_distance(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _sample(u: float, v: float):
    """Colour at a unit-square point, or None outside the rounded tile."""
    cx = min(max(u, CORNER), 1 - CORNER)
    cy = min(max(v, CORNER), 1 - CORNER)
    if math.hypot(u - cx, v - cy) > CORNER:
        return None
    d = min(_segment_distance(u, v, CHECK[i], CHECK[i + 1]) for i in range(len(CHECK) - 1))
    if d < STROKE:
        return (255, 255, 255)
    t = (u + v) / 2
    return tuple(round(a + (b - a) * t) for a, b in zip(FROM, TO, strict=True))


def render_png(size: int) -> bytes:
    """An antialiased RGBA PNG of the icon at `size` x `size`."""
    n = size * SUPERSAMPLE
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")  # filter type: none
        for x in range(size):
            r = g = b = a = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    c = _sample((x * SUPERSAMPLE + sx + 0.5) / n, (y * SUPERSAMPLE + sy + 0.5) / n)
                    if c:
                        r, g, b, a = r + c[0], g + c[1], b + c[2], a + 1
            row += bytes((r // a, g // a, b // a, 255 * a // SUPERSAMPLE**2)) if a else bytes(4)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ICONS_DIR, help="output directory")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        (args.out / f"icon{size}.png").write_bytes(render_png(size))
    print(f"Wrote {len(SIZES)} icons to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
