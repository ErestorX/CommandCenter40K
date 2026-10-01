"""Line of sight from a unit's base, by casting rays (numpy, so it can follow a drag).

Rays leave from points sampled around the base outline, every direction facing outward, up to the
unit's longest weapon range. Along each ray:
  - a DENSE terrain feature (the dark grey walls) stops it where it hits;
  - terrain (the ruin bases) can be seen into but not through: a ray may cross one terrain edge and
    stops at the next one; from a point inside terrain it may cross two (out of its own ruin, into
    another). A piece of terrain counts as one whole: an area made of several footprints, and areas
    joined along an edge (crunch.deploy.objectives), have no inner borders - only entering or leaving
    the whole piece counts (see piece_crossings).
Light features don't block (as in the source's own line-of-sight data); the board edges do.
Elevation is ignored.

Hidden (an option): nothing inside a terrain area can be seen from more than HIDDEN_RANGE away
(GO_TO_GROUND_RANGE with Go to Ground). A ray entering a terrain area (not just leaving the one it
starts in) stops at that distance from its source, or at the area's edge if it reaches it beyond that.
Board coordinates in inches."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from crunch.deploy.objectives import terrain_pieces
from crunch.deploy.placement import BOARD_H, BOARD_W, inside

BOARD_EDGES = [((0, 0), (BOARD_W, 0)), ((BOARD_W, 0), (BOARD_W, BOARD_H)), ((BOARD_W, BOARD_H), (0, BOARD_H)),
               ((0, BOARD_H), (0, 0))]

ORIGINS = 24          # points sampled around the base
DIRECTIONS = 180      # rays per point, every 2 degrees (only those facing outward are cast)
EPS = 1e-6
GAP_CLOSE = 0.3       # inches: a gap this narrow between two footprints of a piece is a seam, not ground
HIDDEN_RANGE = 15.0         # inches
GO_TO_GROUND_RANGE = 12.0   # inches: Hidden, with Go to Ground


@dataclass
class Obstacles:
    dense: tuple[np.ndarray, np.ndarray]        # segment starts, ends (N x 2)
    edges: tuple[np.ndarray, np.ndarray]        # every footprint edge
    edge_poly: np.ndarray                       # footprint each edge belongs to
    footprints: list[list[tuple[float, float]]]
    poly_piece: list[int]                       # piece of terrain each footprint belongs to

    @classmethod
    def from_layout(cls, layout: dict) -> "Obstacles":
        dense, edges, edge_poly, footprints, poly_piece = list(BOARD_EDGES), [], [], [], []
        piece_of = {a: n for n, piece in enumerate(terrain_pieces(layout)) for a in piece}
        for area in layout.get("terrain", []):
            for fp in area.get("footprints", []):
                poly = [tuple(p) for p in (fp.get("los_points") or fp.get("points") or [])]
                if len(poly) >= 3 and fp.get("obscuring", True):
                    edges += list(zip(poly, poly[1:] + poly[:1]))
                    edge_poly += [len(footprints)] * len(poly)
                    footprints.append(poly)
                    poly_piece.append(piece_of.get(area["area"], -1 - len(footprints)))
            for f in area.get("features", []):
                poly = [tuple(p) for p in (f.get("los_points") or f.get("points") or [])]
                if len(poly) >= 3 and f.get("category") == "DENSE":
                    dense += list(zip(poly, poly[1:] + poly[:1]))

        def arrays(segs):
            if not segs:
                return np.zeros((0, 2)), np.zeros((0, 2))
            a = np.array([s[0] for s in segs], float)
            b = np.array([s[1] for s in segs], float)
            return a, b
        return cls(arrays(dense), arrays(edges), np.array(edge_poly, int), footprints, poly_piece)


def _hits(origins: np.ndarray, dirs: np.ndarray, segs: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """Distance along each ray (R) to each segment (S) it crosses, inf where it doesn't: R x S."""
    a, b = segs
    if len(a) == 0:
        return np.full((len(origins), 0), np.inf)
    e = b - a                                                      # S x 2
    denom = dirs[:, None, 0] * e[None, :, 1] - dirs[:, None, 1] * e[None, :, 0]          # R x S
    ao = a[None, :, :] - origins[:, None, :]                       # R x S x 2
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ao[..., 0] * e[None, :, 1] - ao[..., 1] * e[None, :, 0]) / denom
        u = (ao[..., 0] * dirs[:, None, 1] - ao[..., 1] * dirs[:, None, 0]) / denom
    ok = (np.abs(denom) > EPS) & (t > EPS) & (u >= 0) & (u <= 1)
    return np.where(ok, t, np.inf)


def piece_crossings(O: np.ndarray, D: np.ndarray, obstacles: Obstacles) -> list[list[float]]:
    """For each ray, the distances at which it enters or leaves a piece of terrain, in order.

    A piece is all its footprints together: crossing from one of its footprints into another isn't
    crossing its edge. Footprints of a piece rarely meet exactly, so a stretch outside them shorter
    than GAP_CLOSE (a seam between them) still counts as inside. A ray starting inside a piece has
    no crossing where it starts: its first one is where it leaves."""
    hits = _hits(O, D, obstacles.edges)
    uniq, inv = np.unique(O, axis=0, return_inverse=True)
    start_inside = [{k for k, fp in enumerate(obstacles.footprints) if inside(tuple(u), fp)} for u in uniq]
    out = []
    for r in range(len(O)):
        row = hits[r]
        idx = np.nonzero(np.isfinite(row))[0]
        polys = set(start_inside[inv.flat[r]])
        count: dict[int, int] = {}
        opened: dict[int, float] = {}
        for k in polys:
            pc = obstacles.poly_piece[k]
            count[pc] = count.get(pc, 0) + 1
            opened[pc] = 0.0
        spans: dict[int, list[list[float]]] = {}
        for e in idx[np.argsort(row[idx])]:
            t, k = float(row[e]), int(obstacles.edge_poly[e])
            pc = obstacles.poly_piece[k]
            if k in polys:                                    # leaving this footprint
                polys.discard(k)
                count[pc] -= 1
                if count[pc] == 0:
                    spans.setdefault(pc, []).append([opened.pop(pc), t])
            else:                                             # entering it
                polys.add(k)
                count[pc] = count.get(pc, 0) + 1
                if count[pc] == 1:
                    opened[pc] = t
        for pc, t0 in opened.items():
            spans.setdefault(pc, []).append([t0, math.inf])
        cross = []
        for pieces_spans in spans.values():
            pieces_spans.sort()
            merged = [pieces_spans[0]]
            for a, b in pieces_spans[1:]:
                if a - merged[-1][1] < GAP_CLOSE:             # a seam between two of its footprints
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            for a, b in merged:
                if a > EPS:
                    cross.append(a)
                if math.isfinite(b):
                    cross.append(b)
        out.append(sorted(cross))
    return out


def ray_lengths(O: np.ndarray, D: np.ndarray, allowed: np.ndarray, max_range: float,
                obstacles: Obstacles, hidden: float | None = None) -> np.ndarray:
    """How far each ray (origin O, unit direction D) sees: up to max_range, stopped by dense terrain,
    and by the terrain edge after the `allowed` ones it may cross (1, or 2 from inside a ruin).
    hidden: a distance (HIDDEN_RANGE, GO_TO_GROUND_RANGE) at which a ray entering terrain stops,
    or at that terrain's edge if further; None: no such limit."""
    length = np.full(len(O), float(max_range))
    dense = _hits(O, D, obstacles.dense)
    if dense.shape[1]:
        length = np.minimum(length, dense.min(axis=1))
    if len(obstacles.edges[0]):
        for r, cross in enumerate(piece_crossings(O, D, obstacles)):
            a = int(allowed[r])
            if len(cross) > a:
                length[r] = min(length[r], cross[a])
            if hidden is not None and len(cross) >= a:
                # entering: the 1st edge crossed from outside, the 2nd from inside a ruin (the 1st leaves it)
                length[r] = min(length[r], max(cross[a - 1], hidden))
    return length


def visibility(outline: list[tuple[float, float]], max_range: float, obstacles: Obstacles,
               origins: int = ORIGINS, directions: int = DIRECTIONS,
               hidden: float | None = None) -> list[list[tuple[float, float]]]:
    """For points around a unit's outline, the fan of what each sees: [origin, end of ray 1, ...]
    with rays in angle order (a polygon to draw). Their union is the unit's line of sight."""
    if max_range <= 0 or len(outline) < 3:
        return []
    pts = np.array(outline, float)
    step = max(1, len(pts) // origins)
    idx = np.arange(0, len(pts), step)
    centre = pts.mean(axis=0)
    angles = np.linspace(0, 2 * math.pi, directions, endpoint=False)
    all_dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)            # D x 2

    rays_o, rays_d, owner, allowed = [], [], [], []
    for n, i in enumerate(idx):
        o = pts[i]
        out = o - centre                                                      # outward, roughly
        out /= np.linalg.norm(out) or 1.0
        keep = all_dirs @ out > -0.2
        k = int(keep.sum())
        rays_o.append(np.repeat(o[None, :], k, axis=0))
        rays_d.append(all_dirs[keep])
        owner += [n] * k
        inside_one = any(inside(tuple(o), fp) for fp in obstacles.footprints)
        allowed += [2 if inside_one else 1] * k
    O, D = np.concatenate(rays_o), np.concatenate(rays_d)
    owner, allowed = np.array(owner), np.array(allowed)
    ends = O + D * ray_lengths(O, D, allowed, max_range, obstacles, hidden)[:, None]

    fans = []
    for n, i in enumerate(idx):
        sel = owner == n
        o = pts[i]
        e, d = ends[sel], D[sel]
        order = np.argsort(np.arctan2(d[:, 1], d[:, 0]))
        fans.append([tuple(o)] + [tuple(p) for p in e[order]])
    return fans
