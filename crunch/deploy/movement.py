"""Movement ranges, measured from a unit's footprint edge, in inches.

The rings shown for a unit:
  move                M
  advance             M + ADVANCE                  (the average of D6)
  charge              CHARGE                       (the average of 2D6)
  move and charge     M + CHARGE                   (the charge ring, when move is shown too)
  advance and charge  M + ADVANCE + CHARGE         (the charge ring, when advance is shown too)
"""
from __future__ import annotations

import re

from crunch.core.dice import Dice

ADVANCE = Dice.parse("D6")
CHARGE = Dice.parse("2D6")


def parse_move(text: str) -> float:
    """'6"' -> 6, '20+"' -> 20, '-' -> 0."""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def rings(move: float, show_move: bool, show_advance: bool, show_charge: bool) -> list[tuple[str, float]]:
    """(label, distance from the footprint edge) of each ring to draw, innermost first."""
    out = []
    if show_move and move > 0:
        out.append((f'Move {move:g}"', move))
    if show_advance:
        out.append((f'Advance {move + ADVANCE.mean:g}"', move + ADVANCE.mean))
    if show_charge:
        if show_advance:
            total = move + ADVANCE.mean + CHARGE.mean
            out.append((f'Advance + charge {total:g}"', total))
        elif show_move:
            out.append((f'Move + charge {move + CHARGE.mean:g}"', move + CHARGE.mean))
        else:
            out.append((f'Charge {CHARGE.mean:g}"', CHARGE.mean))
    return out
