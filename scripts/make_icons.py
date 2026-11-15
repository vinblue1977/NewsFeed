#!/usr/bin/env python3
"""Regenerate the PWA icons (stdlib only): a gold four-point star on deep navy.

Usage: python3 scripts/make_icons.py   (writes frontend/public/icon-*.png and apple-touch-icon.png)
"""

import struct
import zlib
from pathlib import Path

BG = (16, 24, 43)  # #10182b, deep navy
FG = (227, 179, 65)  # #e3b341, gold
SS = 3  # supersampling per axis, for smooth edges
# A four-point star (N for north and news): 8 vertices on a 0..1 grid, the tips on the axes and the inner corners in between.
MASKABLE_MARGIN = 0.15  # the tips then sit 0.35 from the centre, inside the 0.4-radius safe zone every Android mask keeps
STAR = [(0.5, 0), (0.6, 0.35), (1, 0.5), (0.6, 0.65), (0.5, 1), (0.4, 0.65), (0, 0.5), (0.4, 0.35)]


def _in_star(x: float, y: float, margin: float) -> bool:
    """Is (x, y) in unit coordinates inside the star? `margin` is the empty border (maskable icons need more)."""
    span = 1 - 2 * margin
    u, v = (x - margin) / span, (y - margin) / span
    inside = False
    for i, (x1, y1) in enumerate(STAR):  # even-odd ray casting
        x2, y2 = STAR[(i + 1) % len(STAR)]
        if (y1 > v) != (y2 > v) and u < x1 + (v - y1) / (y2 - y1) * (x2 - x1):
            inside = not inside
    return inside


def _png(size: int, margin: float) -> bytes:
    rows = bytearray()
    for py in range(size):
        rows.append(0)
        for px in range(size):
            hits = sum(
                _in_star((px + (i + 0.5) / SS) / size, (py + (j + 0.5) / SS) / size, margin) for i in range(SS) for j in range(SS)
            )
            a = hits / (SS * SS)
            rows.extend(round(BG[c] + (FG[c] - BG[c]) * a) for c in range(3))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "frontend" / "public"
    for name, size, margin in [
        ("apple-touch-icon.png", 180, 0.16),  # iOS rounds the corners itself, so it is square and opaque
        ("icon-192.png", 192, 0.16),
        ("icon-512.png", 512, 0.16),
        ("icon-maskable-512.png", 512, MASKABLE_MARGIN),  # content inside the safe zone
    ]:
        (out / name).write_bytes(_png(size, margin))
        print("wrote", out / name)


if __name__ == "__main__":
    main()
