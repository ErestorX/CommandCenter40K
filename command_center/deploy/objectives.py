"""Objectives as terrain: an objective is the whole terrain area its marker stands on, and terrain
areas touching along an edge (not just at a corner) count as one piece, so as one objective.

Footprints are compared with their line-of-sight outlines (the source's simplified, clean shapes).
Board coordinates in inches."""
from __future__ import annotations

import math

from command_center.deploy.placement import inside

EDGE_TOLERANCE = 0.15     # inches: outlines this close are in contact
MIN_SHARED = 0.5          # inches: shared_edge() threshold for straight edges
MIN_CONTACT = 1.0         # inches of outline in contact for two pieces to count as one (a corner is less)
_PARALLEL = math.sin(math.radians(3))

Poly = list[tuple[float, float]]


def _edges(poly: Poly):
    return zip(poly, poly[1:] + poly[:1])


def _line_distance(p, a, b) -> float:
    (ax, ay), (bx, by) = a, b
    L = math.hypot(bx - ax, by - ay)
    return abs((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) / L if L else math.hypot(p[0] - ax, p[1] - ay)


def shared_edge(p: Poly, q: Poly, tol: float = EDGE_TOLERANCE) -> float:
    """Longest stretch along which an edge of p and an edge of q lie on the same line."""
    best = 0.0
    for a, b in _edges(p):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        for c, d in _edges(q):
            ex, ey = d[0] - c[0], d[1] - c[1]
            M = math.hypot(ex, ey)
            if M < 1e-9 or abs(dx * ey - dy * ex) / (L * M) > _PARALLEL:
                continue
            if _line_distance(c, a, b) > tol or _line_distance(d, a, b) > tol:
                continue
            t = sorted(((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / L for c in (c, d))
            best = max(best, min(L, t[1]) - max(0.0, t[0]))
    return best


def _segments_cross(a, b, c, d) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def overlap(p: Poly, q: Poly) -> bool:
    """Do two polygons share some area (one inside the other, or crossing edges)?"""
    if any(inside(v, q) for v in p) or any(inside(v, p) for v in q):
        return True
    return any(_segments_cross(a, b, c, d) for a, b in _edges(p) for c, d in _edges(q))


def _distance_to_outline(pt, poly: Poly) -> float:
    return min(_nearest_on_segment(pt, a, b)[0] for a, b in _edges(poly))


def contact_length(p: Poly, q: Poly, tol: float = EDGE_TOLERANCE, step: float = 0.05) -> float:
    """Length of p's outline lying on q's outline (within `tol`) or inside q. Ragged ruin outlines
    don't share exact straight edges, so the contact is measured along the outline instead."""
    total = 0.0
    for a, b in _edges(p):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / step))
        for i in range(n):
            f = (i + 0.5) / n
            pt = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
            if inside(pt, q) or _distance_to_outline(pt, q) <= tol:
                total += L / n
    return total


def _near(p: Poly, q: Poly, tol: float = EDGE_TOLERANCE) -> bool:
    """Do the boxes around two polygons come within `tol`?"""
    return not (max(x for x, _ in p) < min(x for x, _ in q) - tol or max(x for x, _ in q) < min(x for x, _ in p) - tol
                or max(y for _, y in p) < min(y for _, y in q) - tol or max(y for _, y in q) < min(y for _, y in p) - tol)


def touching(p: Poly, q: Poly) -> bool:
    """Along an edge (at least MIN_CONTACT of outline in contact), not just at a corner."""
    return _near(p, q) and max(contact_length(p, q), contact_length(q, p)) >= MIN_CONTACT


def _outline(fp: dict) -> Poly:
    return [tuple(pt) for pt in (fp.get("los_points") or fp.get("points") or [])]


def terrain_pieces(layout: dict) -> list[list[str]]:
    """Terrain areas grouped into pieces: areas touching along an edge belong to the same piece."""
    areas = {a["area"]: [_outline(fp) for fp in a.get("footprints", []) if len(_outline(fp)) >= 3]
             for a in layout.get("terrain", [])}
    parent = {a: a for a in areas}

    def root(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    ids = list(areas)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if root(a) != root(b) and any(touching(p, q) for p in areas[a] for q in areas[b]):
                parent[root(b)] = root(a)
    pieces: dict[str, list[str]] = {}
    for a in ids:
        pieces.setdefault(root(a), []).append(a)
    return list(pieces.values())


def objective_regions(layout: dict) -> list[dict]:
    """Each objective with the terrain it covers: {"number", "type", "owner", "areas", "polygons"}."""
    pieces = terrain_pieces(layout)
    outlines = {a["area"]: [_outline(fp) for fp in a.get("footprints", []) if len(_outline(fp)) >= 3]
                for a in layout.get("terrain", [])}
    out = []
    for o in layout.get("objectives", []):
        piece = next((p for p in pieces if o["area"] in p), [o["area"]])
        out.append({"number": o["number"], "type": o.get("type", ""), "owner": o.get("owner"),
                    "position": o["position"], "areas": piece,
                    "polygons": [poly for a in piece for poly in outlines.get(a, [])]})
    return out


def _nearest_on_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    f = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    q = (a[0] + f * dx, a[1] + f * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def distance_to_region(unit: Poly, polygons: list[Poly]) -> tuple[float, tuple, tuple]:
    """Shortest distance between a unit's outline and an objective's terrain, with the two nearest
    points (on the unit, on the terrain). 0 when they overlap."""
    best = (math.inf, unit[0], unit[0])
    for poly in polygons:
        if overlap(unit, poly):
            return 0.0, unit[0], unit[0]
        for v in unit:                                  # unit corners to terrain edges
            for a, b in _edges(poly):
                d, q = _nearest_on_segment(v, a, b)
                if d < best[0]:
                    best = (d, v, q)
        for v in poly:                                  # terrain corners to unit edges
            for a, b in _edges(unit):
                d, q = _nearest_on_segment(v, a, b)
                if d < best[0]:
                    best = (d, q, v)
    return best
