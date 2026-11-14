#!/usr/bin/env python3
"""Regenerate the PWA icons (stdlib only): a gold serif "N" on black, like a newspaper masthead.

Usage: python3 scripts/make_icons.py   (writes frontend/public/icon-*.png and apple-touch-icon.png)
"""

import struct
import zlib
from pathlib import Path

BG = (13, 13, 15)  # #0d0d0f, black
FG = (227, 179, 65)  # #e3b341, gold
SS = 3  # supersampling per axis, for smooth edges


def _in_n(x: float, y: float, margin: float) -> bool:
    """Is (x, y) in unit coordinates inside a serif letter N? `margin` is the empty border (maskable icons need more).

    The shape: two thin stems, a thick diagonal from the top-left to the bottom-right, and slab serifs
    (top-left, top-right and bottom-left; the diagonal itself lands on the bottom right)."""
    lo, hi = margin, 1 - margin
    span = hi - lo
    if not (lo <= y <= hi):
        return False
    inset = 0.08 * span  # empty space between the glyph box and the stems
    thin = 0.085 * span  # thin stem width
    thick = 0.30 * span  # diagonal width, measured horizontally
    serif_h = 0.075 * span
    serif_w = 0.08 * span  # how far a serif reaches beyond a stem on each side
    left0, left1 = lo + inset, lo + inset + thin
    right0, right1 = hi - inset - thin, hi - inset
    t = (y - lo) / span
    # diagonal: its centre runs from the left stem (top) to the right stem (bottom)
    c0, c1 = left0 + thick / 2, right1 - thick / 2
    centre = c0 + t * (c1 - c0)
    if abs(x - centre) <= thick / 2 and left0 <= x <= right1:
        return True
    if left0 <= x <= left1 or right0 <= x <= right1:  # the stems
        return True
    top = y <= lo + serif_h
    bottom = y >= hi - serif_h
    if top and (left0 - serif_w <= x <= left1 + serif_w or right0 - serif_w <= x <= right1 + serif_w):
        return True
    return bottom and left0 - serif_w <= x <= left1 + serif_w


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
