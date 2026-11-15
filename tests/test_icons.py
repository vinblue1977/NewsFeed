"""The icon generator: the star is centred, and the maskable icon keeps it inside the safe zone."""

import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location("make_icons", Path("scripts/make_icons.py"))
assert spec and spec.loader
icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icons)

SAFE_RADIUS = 0.4  # Android maskable icons keep the middle 80% (a circle of this radius, in canvas units)


def test_the_star_is_centred_and_does_not_fill_the_corners() -> None:
    assert icons._in_star(0.5, 0.5, 0.16)
    assert not icons._in_star(0.1, 0.1, 0.16)
    assert not icons._in_star(0.9, 0.9, 0.16)


def test_the_maskable_icon_keeps_every_vertex_inside_the_safe_zone() -> None:
    span = 1 - 2 * icons.MASKABLE_MARGIN
    for u, v in icons.STAR:
        x, y = icons.MASKABLE_MARGIN + u * span, icons.MASKABLE_MARGIN + v * span
        assert math.hypot(x - 0.5, y - 0.5) <= SAFE_RADIUS


def test_a_png_has_the_requested_size() -> None:
    png = icons._png(24, 0.16)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(png[16:20], "big") == 24 and int.from_bytes(png[20:24], "big") == 24
