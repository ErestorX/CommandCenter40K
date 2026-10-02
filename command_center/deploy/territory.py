"""Territories: a player's territory is the half of the battlefield that includes that player's
deployment zone. The line between the two halves runs through the centre of the board: along the
zones' long slanted edge when they have one (diagonal deployments), else across the board between
the two players' battlefield edges."""
from __future__ import annotations

from math import hypot

from command_center.deploy.placement import BOARD_H, BOARD_W

Point = tuple[float, float]
SLANT_MIN = 15.0            # inches: a slanted zone edge this long is a diagonal deployment, not a rounded corner


def _slant(layout: dict) -> Point | None:
    """The direction of the attacker zone's long slanted edge, if it has one."""
    for poly in layout.get("deployment_zones", {}).get("attacker", []):
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) > 1 and abs(dy) > 1 and hypot(dx, dy) >= SLANT_MIN:
                return dx, dy
    return None


def territory_line(layout: dict) -> tuple[Point, Point] | None:
    """The two ends, on the board's edges, of the line between the players' territories; None when the
    layout doesn't tell (no slanted zone, and no known battlefield edges)."""
    cx, cy = BOARD_W / 2, BOARD_H / 2
    d = _slant(layout)
    if d is None:
        edge = layout.get("attacker_edge")
        if edge in ("left", "right"):
            d = (0.0, 1.0)
        elif edge in ("bottom", "top"):
            d = (1.0, 0.0)
        else:
            return None
    dx, dy = d
    t = min(cx / abs(dx) if dx else float("inf"), cy / abs(dy) if dy else float("inf"))     # up to the first edge met
    return (cx - t * dx, cy - t * dy), (cx + t * dx, cy + t * dy)
