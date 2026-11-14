#!/usr/bin/env python3
"""Regenerate the PWA icons (stdlib only): a blue "N" on the app's dark background.

Usage: python3 scripts/make_icons.py   (writes frontend/public/icon-*.png and apple-touch-icon.png)
"""

import struct
import zlib
from pathlib import Path

BG = (23, 25, 28)  # #17191c, the app background
FG = (59, 130, 246)  # blue accent
SS = 3  # supersampling per axis, for smooth edges


def _in_n(x: float, y: float, margin: float) -> bool:
    """Is (x, y) in unit coordinates inside the letter N? `margin` is the empty border (maskable icons need more)."""
    lo, hi = margin, 1 - margin
    if not (lo <= y <= hi):
        return False
    w = (hi - lo) * 0.22  # stroke width
    if lo <= x <= lo + w or hi - w <= x <= hi:
        return True
    # diagonal from top-left to bottom-right: a band of horizontal width w around the line
    t = (y - lo) / (hi - lo)
    cx = lo + w / 2 + t * ((hi - w / 2) - (lo + w / 2))
    return abs(x - cx) <= w * 0.6 and lo <= x <= hi


def _png(size: int, margin: float) -> bytes:
    rows = bytearray()
    for py in range(size):
        rows.append(0)
        for px in range(size):
            hits = sum(
                _in_n((px + (i + 0.5) / SS) / size, (py + (j + 0.5) / SS) / size, margin) for i in range(SS) for j in range(SS)
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
        ("apple-touch-icon.png", 180, 0.22),  # iOS rounds the corners itself, so it is square and opaque
        ("icon-192.png", 192, 0.22),
        ("icon-512.png", 512, 0.22),
        ("icon-maskable-512.png", 512, 0.32),  # content inside the safe zone
    ]:
        (out / name).write_bytes(_png(size, margin))
        print("wrote", out / name)


if __name__ == "__main__":
    main()
