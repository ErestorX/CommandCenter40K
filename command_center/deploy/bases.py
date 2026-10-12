"""Base sizes and unit footprints, in inches.

A model's base comes from Wahapedia's `base_size` ("40mm", "170 x 109mm flying base", ...). Models
without one ("Use model": vehicles on their hull, "Unique", blank) get an estimated oval from their
Wounds, flagged `estimated`.

A unit of several models is drawn as one shape holding every base, in one of four formations
(FORMATIONS; a lone model is its base in all of them):

  spaced   1" between neighbours, the formation units start in: each base is grown by 0.5" all round
           (half of the 1" gap on each side), the grown areas are added up and divided by the density
           of a tight hexagonal packing, and the ellipse of that area (with ASPECT between its axes)
           loses the 0.5" margin again on its outside.
  compact  the same with no gap: every base touching its neighbours, as tight as bases pack.
  spread   the same with up to COHERENCY (2") between neighbours, as far as the unit may spread: every
           model within REACH (9") of every other, so no further across than REACH plus its two
           largest bases. A unit that would be longer is rounder instead; one too large for that
           even as a circle has its gaps narrowed until it fits.
  line     the same limits, in a tube (a rectangle with round ends): the models in a row, up to 2"
           apart, as long as REACH allows; those that don't fit in one row, even touching, make more
           rows, as few as it takes.

A footprint is never smaller than the unit's largest base. Two models that touch are as long as
their two bases, which an ellipse of their area would not be.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

MM = 1 / 25.4                     # inches per millimetre
GAP = 1.0                         # inches between the bases of a unit
PACKING = math.pi / (2 * math.sqrt(3))     # ~0.907: circles in a hexagonal packing
ASPECT = 1.5                      # long axis / short axis of a multi-model unit's ellipse
COHERENCY = 2.0                   # inches: the most there may be between a model and its nearest neighbour
REACH = 9.0                       # inches: the most there may be between any two models of a unit

COMPACT, SPACED, SPREAD, LINE = "compact", "spaced", "spread", "line"
FORMATIONS = {COMPACT: "Compact", SPACED: '1" space', SPREAD: "Max spread", LINE: "Line spread"}     # and their names
ELLIPSE, TUBE = "ellipse", "tube"                                  # a footprint's shape

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
    shape: str = ELLIPSE          # TUBE: a rectangle w long with round ends, h across


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


def _ellipse(bases: list[tuple[Base, int]], gap: float) -> tuple[float, float]:
    """The axes of the ellipse holding the bases with `gap` between neighbours."""
    area = sum(b.grown_area(gap / 2) * n for b, n in bases) / PACKING
    short = math.sqrt(4 * area / (math.pi * ASPECT))
    return ASPECT * short - gap, short - gap              # take off the outer half-gaps


def _across(bases: list[tuple[Base, int]]) -> float:
    """How far across a unit may be: REACH between its two farthest models, and those two models."""
    longest = sorted((b.w for b, n in bases for _ in range(min(n, 2))), reverse=True)[:2]
    return REACH + sum(longest)


def _spread(bases: list[tuple[Base, int]]) -> tuple[float, float]:
    """The ellipse of a unit spread as far as it may: up to COHERENCY between neighbours, no further
    across than _across. Too long for that, it is rounder; too large even as a circle, its gaps narrow."""
    limit = _across(bases)
    gap = COHERENCY
    while gap > 0:
        w, h = _ellipse(bases, gap)
        if w > limit:                                     # the same area, no longer than allowed
            h = (w + gap) * (h + gap) / (limit + gap) - gap
            w = limit
        if h <= limit:
            return w, h
        gap = round(gap - 0.05, 2)
    return _ellipse(bases, 0)


def _line(bases: list[tuple[Base, int]]) -> tuple[float, float]:
    """The tube of a unit in a row: up to COHERENCY between neighbours, no longer than _across; as few
    rows as hold the models touching, their gaps as wide as the length then allows."""
    count = sum(n for _, n in bases)
    along = sum(b.w * n for b, n in bases)                # the models side by side, touching
    width = max(b.h for b, _ in bases)
    limit = _across(bases)
    rows = max(1, math.ceil(along / limit - 1e-9))
    per_row = math.ceil(count / rows)
    row = along / count * per_row
    gap = min(COHERENCY, (limit - row) / (per_row - 1)) if per_row > 1 else 0.0
    gap = max(gap, 0.0)
    return row + gap * (per_row - 1), rows * width + gap * (rows - 1)


def unit_footprint(bases: list[tuple[Base, int]], formation: str = SPACED) -> Footprint:
    """What a unit of `bases` [(base, count)] takes on the table in a formation (a lone model: its base)."""
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
    tight = _ellipse(bases, 0)
    if count == 2:                                        # two bases side by side: an ellipse of their area is too short
        tight = (sum(b.w * n for b, n in bases), max(b.h for b, _ in bases))
    w, h = {COMPACT: lambda: tight, SPREAD: lambda: _spread(bases), LINE: lambda: _line(bases)}.get(
        formation, lambda: _ellipse(bases, GAP))()
    shape = TUBE if formation == LINE else ELLIPSE
    if shape == TUBE and math.pi * h * h / 4 + (w - h) * h < math.pi * tight[0] * tight[1] / 4:
        w, h, shape = *tight, ELLIPSE                     # too many models for a row within reach: as compact
    if formation == SPREAD:
        w, h = max(w, tight[0]), max(h, tight[1])
    biggest = max((b for b, _ in bases), key=lambda b: b.area)
    return Footprint(max(w, biggest.w), max(h, biggest.h), count, estimated, f"{count} models: {desc}", shape)
