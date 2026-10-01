"""Base sizes and unit footprints, in inches.

A model's base comes from Wahapedia's `base_size` ("40mm", "170 x 109mm flying base", ...). Models
without one ("Use model": vehicles on their hull, "Unique", blank) get an estimated oval from their
Wounds, flagged `estimated`.

A unit of several models is drawn as one ellipse holding every base with 1" between neighbours:
each base is grown by 0.5" all round (half of the 1" gap on each side), the grown areas are added
up and divided by the density of a tight hexagonal packing, and the ellipse of that area (with
ASPECT between its axes) loses the 0.5" margin again on its outside. It is never smaller than the
unit's largest base.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

MM = 1 / 25.4                     # inches per millimetre
GAP = 1.0                         # inches between the bases of a unit
PACKING = math.pi / (2 * math.sqrt(3))     # ~0.907: circles in a hexagonal packing
ASPECT = 1.5                      # long axis / short axis of a multi-model unit's ellipse

# (max Wounds, base) for models without an official base size: rough hull sizes, mm
_ESTIMATES = [(3, (40, 40)), (6, (60, 60)), (9, (105, 70)), (13, (120, 92)), (19, (170, 109)),
              (25, (200, 130)), (10 ** 9, (250, 160))]


@dataclass(frozen=True)
class Base:
    w: float                      # inches, long axis
    h: float                      # inches, short axis (== w for a round base)
    estimated: bool = False
    text: str = ""                # as written in the data

    @property
    def round(self) -> bool:
        return abs(self.w - self.h) < 1e-9

    @property
    def area(self) -> float:
        return math.pi * self.w * self.h / 4

    def grown_area(self, margin: float) -> float:
        return math.pi * (self.w + 2 * margin) * (self.h + 2 * margin) / 4


@dataclass(frozen=True)
class Footprint:
    w: float                      # inches, ellipse (or base) long axis
    h: float
    models: int
    estimated: bool               # at least one base size is an estimate
    description: str              # "10 models: 9x 25mm, 1x 32mm"


def parse_base(text: str, wounds: int = 1) -> Base:
    """ "40mm" / "120 x 92mm flying base" -> Base in inches; anything else is estimated from Wounds."""
    t = (text or "").lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", t)
    if m:
        a, b = sorted((float(m.group(1)), float(m.group(2))), reverse=True)
        return Base(a * MM, b * MM, False, text)
    m = re.search(r"(\d+(?:\.\d+)?)\s*mm", t)
    if m:
        d = float(m.group(1)) * MM
        return Base(d, d, False, text)
    a, b = next(size for limit, size in _ESTIMATES if wounds <= limit)
    return Base(a * MM, b * MM, True, text)


def _mm(b: Base) -> str:
    if b.estimated:
        return f"~{b.w / MM:.0f}x{b.h / MM:.0f}mm"
    return f"{b.w / MM:g}mm" if b.round else f"{b.w / MM:g}x{b.h / MM:g}mm"


def unit_footprint(bases: list[tuple[Base, int]]) -> Footprint:
    """The ellipse a unit of `bases` [(base, count)] takes on the table (a lone model: its base)."""
    bases = [(b, n) for b, n in bases if n > 0]
    count = sum(n for _, n in bases)
    estimated = any(b.estimated for b, _ in bases)
    kinds: dict[str, int] = {}
    for b, n in bases:
        kinds[_mm(b)] = kinds.get(_mm(b), 0) + n
    desc = ", ".join(f"{n}x {k}" for k, n in kinds.items())
    if count == 0:
        return Footprint(1.0, 1.0, 0, True, "no models")
    if count == 1:
        b = bases[0][0]
        return Footprint(b.w, b.h, 1, estimated, f"1 model: {_mm(b)}")
    area = sum(b.grown_area(GAP / 2) * n for b, n in bases) / PACKING
    short = math.sqrt(4 * area / (math.pi * ASPECT))
    w, h = ASPECT * short - GAP, short - GAP              # take off the outer half-gaps
    biggest = max((b for b, _ in bases), key=lambda b: b.area)
    return Footprint(max(w, biggest.w), max(h, biggest.h), count, estimated, f"{count} models: {desc}")
