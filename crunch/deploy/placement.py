"""Where a unit's footprint can go on the board: random spots inside a deployment zone, and keeping
a dragged footprint on the board. Board coordinates in inches, origin bottom-left, y up."""
from __future__ import annotations

import math
import random

BOARD_W, BOARD_H = 60.0, 44.0
Point = tuple[float, float]


def inside(pt: Point, poly: list) -> bool:
    """Point in polygon (even-odd rule)."""
    x, y = pt
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def ellipse_outline(x: float, y: float, w: float, h: float, n: int = 12) -> list[Point]:
    return [(x + w / 2 * math.cos(2 * math.pi * i / n), y + h / 2 * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def extent(w: float, h: float, angle: float = 0.0) -> tuple[float, float]:
    """Width and height of the box around a w x h ellipse turned by `angle` degrees."""
    a, b, t = w / 2, h / 2, math.radians(angle)
    return (2 * math.sqrt((a * math.cos(t)) ** 2 + (b * math.sin(t)) ** 2),
            2 * math.sqrt((a * math.sin(t)) ** 2 + (b * math.cos(t)) ** 2))


def ellipse_polygon(x: float, y: float, w: float, h: float, angle: float = 0.0, n: int = 36) -> list[Point]:
    """Outline of a w x h ellipse centred at (x, y), turned `angle` degrees clockwise on the board
    as seen from above (board y points up)."""
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    out = []
    for i in range(n):
        u, v = w / 2 * math.cos(2 * math.pi * i / n), h / 2 * math.sin(2 * math.pi * i / n)
        out.append((x + u * c + v * s, y - u * s + v * c))      # clockwise with y up
    return out


def clamp(x: float, y: float, w: float, h: float) -> Point:
    """Keep a w x h footprint centred at (x, y) on the board: it bumps into the edges."""
    return (min(max(x, w / 2), BOARD_W - w / 2) if w < BOARD_W else BOARD_W / 2,
            min(max(y, h / 2), BOARD_H - h / 2) if h < BOARD_H else BOARD_H / 2)


def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float], gap: float = 0.0) -> bool:
    """Do two boxes (centre x, centre y, width, height) come within `gap` of each other?"""
    return abs(a[0] - b[0]) < (a[2] + b[2]) / 2 + gap and abs(a[1] - b[1]) < (a[3] + b[3]) / 2 + gap


def random_spot(zones: list[list], w: float, h: float, rng: random.Random | None = None,
                tries: int = 400, avoid: list[tuple[float, float, float, float]] | None = None) -> Point:
    """A random centre for a w x h footprint wholly inside one of `zones`, clear of the `avoid` boxes
    (centre x, centre y, width, height) when there is room; failing that, anywhere wholly inside a
    zone; then a centre inside a zone; then the middle of the zones. Always on the board."""
    if avoid:
        rng = rng or random.Random()
        clear = random_spot(zones, w, h, rng, tries, None)
        for _ in range(tries // 4):
            if not any(overlaps((*clear, w, h), b, gap=0.5) for b in avoid):
                return clear
            clear = random_spot(zones, w, h, rng, 60, None)
        return clear
    rng = rng or random.Random()
    zones = [z for z in zones if len(z) >= 3]
    if not zones:
        return clamp(BOARD_W / 2, BOARD_H / 2, w, h)
    xs = [p[0] for z in zones for p in z]
    ys = [p[1] for z in zones for p in z]
    box = (max(min(xs), w / 2), min(max(xs), BOARD_W - w / 2), max(min(ys), h / 2), min(max(ys), BOARD_H - h / 2))

    def sample() -> Point:
        lo_x, hi_x, lo_y, hi_y = box
        return (rng.uniform(lo_x, hi_x) if lo_x < hi_x else (lo_x + hi_x) / 2,
                rng.uniform(lo_y, hi_y) if lo_y < hi_y else (lo_y + hi_y) / 2)

    for _ in range(tries):
        c = sample()
        for z in zones:
            if inside(c, z) and all(inside(p, z) for p in ellipse_outline(*c, w, h)):
                return clamp(*c, w, h)
    for _ in range(tries):
        c = sample()
        if any(inside(c, z) for z in zones):
            return clamp(*c, w, h)
    return clamp((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, w, h)
