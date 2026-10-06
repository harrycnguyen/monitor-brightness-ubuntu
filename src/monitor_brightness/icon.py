"""A drawn tray icon (sun with rays), so it shows even if the icon theme has no suitable name."""

from __future__ import annotations

import math

SIZES = (22, 32, 48)
_COLOR = (235, 235, 235)  # light grey: Ubuntu's top bar is dark
_SS = 4  # samples per pixel side, for smooth edges


def _coverage(x: float, y: float, s: int) -> float:
    """Share of the pixel at (x, y) covered by the sun, for an icon of size s."""
    hit = 0
    for i in range(_SS):
        for j in range(_SS):
            dx = (x + (i + 0.5) / _SS) / s - 0.5
            dy = (y + (j + 0.5) / _SS) / s - 0.5
            if math.hypot(dx, dy) <= 0.2:
                hit += 1
                continue
            for k in range(8):
                a = k * math.pi / 4
                along = dx * math.cos(a) + dy * math.sin(a)
                across = abs(-dx * math.sin(a) + dy * math.cos(a))
                if 0.31 <= along <= 0.46 and across <= 0.04:
                    hit += 1
                    break
    return hit / (_SS * _SS)


def render(s: int) -> bytes:
    """ARGB32 pixels, network byte order (A, R, G, B), row by row."""
    out = bytearray()
    for y in range(s):
        for x in range(s):
            out += bytes((round(255 * _coverage(x, y, s)), *_COLOR))
    return bytes(out)


def pixmaps() -> list[tuple[int, int, bytes]]:
    return [(s, s, render(s)) for s in SIZES]
