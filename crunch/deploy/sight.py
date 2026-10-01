"""Line of sight from a unit's base, by casting rays (numpy, so it can follow a drag).

Rays leave from points sampled around the base outline, every direction facing outward, up to the
unit's longest weapon range. Along each ray:
  - a DENSE terrain feature (the dark grey walls) stops it where it hits;
  - terrain area footprints (the ruin bases) can be seen into but not through: a ray may cross
    one footprint edge and stops at the next one; from a point inside a footprint it may cross two
    (out of its own ruin, into another).
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

from crunch.deploy.placement import BOARD_H, BOARD_W, inside

BOARD_EDGES = [((0, 0), (BOARD_W, 0)), ((BOARD_W, 0), (BOARD_W, BOARD_H)), ((BOARD_W, BOARD_H), (0, BOARD_H)),
               ((0, BOARD_H), (0, 0))]

ORIGINS = 24          # points sampled around the base
DIRECTIONS = 180      # rays per point, every 2 degrees (only those facing outward are cast)
EPS = 1e-6
HIDDEN_RANGE = 15.0         # inches
GO_TO_GROUND_RANGE = 12.0   # inches: Hidden, with Go to Ground


@dataclass
class Obstacles:
    dense: tuple[np.ndarray, np.ndarray]        # segment starts, ends (N x 2)
    edges: tuple[np.ndarray, np.ndarray]        # footprint edges
    footprints: list[list[tuple[float, float]]]

    @classmethod
    def from_layout(cls, layout: dict) -> "Obstacles":
        dense, edges, footprints = list(BOARD_EDGES), [], []        # sight stops at the board edges
        for area in layout.get("terrain", []):
            for fp in area.get("footprints", []):
                poly = [tuple(p) for p in (fp.get("los_points") or fp.get("points") or [])]
                if len(poly) >= 3 and fp.get("obscuring", True):
                    footprints.append(poly)
                    edges += list(zip(poly, poly[1:] + poly[:1]))
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
        return cls(arrays(dense), arrays(edges), footprints)


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


def ray_lengths(O: np.ndarray, D: np.ndarray, allowed: np.ndarray, max_range: float,
                obstacles: Obstacles, hidden: float | None = None) -> np.ndarray:
    """How far each ray (origin O, unit direction D) sees: up to max_range, stopped by dense terrain,
    and by the footprint edge after the `allowed` ones it may cross (1, or 2 from inside a ruin).
    hidden: a distance (HIDDEN_RANGE, GO_TO_GROUND_RANGE) at which a ray entering a terrain area stops,
    or at that area's edge if further; None: no such limit."""
    length = np.full(len(O), float(max_range))
    dense = _hits(O, D, obstacles.dense)
    if dense.shape[1]:
        length = np.minimum(length, dense.min(axis=1))
    edges = _hits(O, D, obstacles.edges)
    if edges.shape[1]:
        crossings = np.sort(edges, axis=1)
        k = np.minimum(allowed, crossings.shape[1] - 1)
        stop = np.where(allowed < crossings.shape[1], crossings[np.arange(len(O)), k], np.inf)
        length = np.minimum(length, stop)
        if hidden is not None:
            # entering: the 1st edge crossed from outside, the 2nd from inside a ruin (the 1st leaves it)
            e = np.minimum(allowed - 1, crossings.shape[1] - 1)
            enter = np.where(allowed - 1 < crossings.shape[1], crossings[np.arange(len(O)), e], np.inf)
            length = np.minimum(length, np.where(np.isfinite(enter), np.maximum(enter, hidden), np.inf))
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
