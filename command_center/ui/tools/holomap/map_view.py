"""A battlefield layout drawn on a canvas: deployment zones, terrain, objectives, measurements, and
the units placed on it. Scales to the space it gets, keeping the board's 60" x 44" proportions.

Units are tokens (a base, or the ellipse of a whole unit) that start at a random spot in their
side's deployment zone and can be dragged anywhere on the board, stopping at its edges. They are
half see-through (command_center.ui.translucent: Tk has no transparency) so terrain shows underneath. A click
selects a token, a double click turns it 30 degrees clockwise, a right click releases the selection.

For the selected unit the map can also draw its movement rings (move, advance, charge: lines at that
distance from its footprint edge), the shortest line from it to each objective, an objective being
the whole terrain its marker stands on (command_center.deploy.objectives), and its line of sight: what it can
see up to its longest weapon range (command_center.deploy.sight), with a circle per weapon range; with the
planned targets shown too, the part of it reaching its 1st target (and 2nd, with "plan2") is green.

The map can also draw arrows to planned targets (the Engagement Optimizer's army plan): set_plan_links() gives
the pairs; the "plan" overlay shows the selected unit's 1st target (or, for a selected defender, the
attackers aiming at it), "plan2" adds 2nd targets, "planall" shows every attacker's.

With show_territory, the line between the two players' territories is drawn (command_center.deploy.territory).
role_names: what the two sides are called on the map ("attacker" and "defender" unless changed)."""
from __future__ import annotations

import random
import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from command_center.deploy import Footprint
from command_center.deploy.movement import rings
from command_center.deploy.objectives import distance_to_region, objective_regions
from command_center.deploy.placement import clamp, ellipse_polygon, extent, offset_ellipse, random_spot
from command_center.deploy.sight import GO_TO_GROUND_RANGE, HIDDEN_RANGE, Obstacles, cast, fans, reaching_fans
from command_center.deploy.territory import territory_line
from command_center.ui.theme import C, font_family
from command_center.ui.translucent import STIPPLES, shade

BOARD_W, BOARD_H = 60.0, 44.0
ZONE_FILL = {"attacker": "#f1d3d3", "defender": "#d3dff0"}
ZONE_INK = {"attacker": "#a3262a", "defender": "#1f5288"}
BOARD_FILL, BOARD_INK = "#f7f5ef", "#1d1c1a"       # a light board on the dark window: its own inks
AREA_FILL, AREA_LINE = "#ddd6c8", "#9b9384"
FEATURE_FILL = {"DENSE": "#5f584d", "LIGHT": "#a8a092"}
OBJ_FILL = {"central": "#1d1c1a", "expansion": "#3c7d45"}
MEASURE = "#6e6a63"
TERRITORY_INK, TERRITORY_DASH = "#1d1c1a", (10, 5)
TOKEN = {"attacker": ("#c9474b", "#6b1417"), "defender": ("#3d73b3", "#12304f")}   # fill, outline
TOKEN_STIPPLE = "gray50"          # half the pixels filled: terrain stays visible underneath
SELECTED = "#e0a800"
ROTATE_STEP = 30                  # degrees clockwise per double click
RING_INK = ["#2f7d32", "#c26a00", "#7b3fa0"]      # innermost ring first
DISTANCE_INK = "#1d1c1a"
DISTANCE_DASH = (8, 3, 2, 3)      # dash-dot: visible without hiding the terrain
SIGHT_FILL, SIGHT_STIPPLE = "#6e6a63", "gray12"   # very light grey: an eighth of the pixels
RANGE_INK = "#55524c"
TARGET_FILL, TARGET_STIPPLE = "#2e9e44", "gray25"   # faint green: the sight reaching its planned target(s)
PLAN_INK = ZONE_INK["attacker"]
OVERLAY_DELAY = 30                # ms between overlay redraws while dragging
OVERLAYS = ("move", "advance", "charge", "objectives", "plan", "plan2", "planall", "sight", "hidden", "ground")


@dataclass
class Token:
    key: str
    role: str
    label: str
    footprint: Footprint
    move: float = 0.0           # inches
    ranges: tuple[float, ...] = ()   # ranged weapon ranges, inches
    x: float = 0.0              # centre, board inches
    y: float = 0.0
    angle: float = 0.0          # degrees clockwise, as seen from above

    @property
    def box(self) -> tuple[float, float]:
        """Width and height the turned footprint takes on the board."""
        return extent(self.footprint.w, self.footprint.h, self.angle)


LABEL_WIDTH = 110                 # pixels: longer board labels wrap onto another line


def compact_label(name: str) -> str:
    """Board label: the unit without a trailing "Squad", attached characters on a second line.
    "Bladeguard Veteran Squad + Sanguinary Priest" -> "Bladeguard Veteran\\n+ Sanguinary Priest"."""
    parts = [p.strip() for p in name.split(" + ")]
    first = re.sub(r"\s+Squad\b", "", parts[0])
    return first + ("\n+ " + " + ".join(parts[1:]) if len(parts) > 1 else "")


def objective_fill(o: dict) -> str:
    if o.get("type") == "home":
        return ZONE_INK.get(o.get("owner") or "", "#1d1c1a")
    return OBJ_FILL.get(o.get("type", ""), "#1d1c1a")


class LayoutMap(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, style="Panel.TFrame", padding=6)
        self.title = ttk.Label(self, text="", style="H2.TLabel")
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, text="", style="Muted.TLabel")
        self.sub.pack(anchor="w")
        self.cv = tk.Canvas(self, bg=C["panel"], highlightthickness=0)
        self.cv.pack(fill="both", expand=True, pady=(4, 0))
        self.layout: dict | None = None
        self.message = ""
        self.show_measurements = False
        self.show_territory = False                                 # the line between the two territories
        self.role_names = {"attacker": "attacker", "defender": "defender"}      # as written on the map
        self.tokens: dict[str, Token] = {}
        self._geom: tuple[float, float, float] | None = None       # origin x, origin y, pixels per inch
        self._drag: tuple[str, float, float] | None = None         # token key, grab offset (inches)
        self.rng = random.Random()
        self.selected: str | None = None
        self.on_select = None                                       # callback(map, key or None)
        self.overlays: dict[str, bool] = {name: False for name in OVERLAYS}
        self.regions: list[dict] = []                               # objectives as terrain, per layout
        self.obstacles: Obstacles | None = None                    # what blocks line of sight, per layout
        self.plan_links: list[tuple[str, str, str]] = []           # (attacker key, target key, rank)
        self._overlay_job = None
        self.cv.bind("<Configure>", lambda e: self.draw())
        # bound on the canvas, finding the token under the pointer: selecting redraws the token, and
        # Tk's "current" item stays empty until the pointer moves again
        self.cv.bind("<ButtonPress-1>", self._press)
        # clicks 2 and 4 of a quick run are each a double click: turn on those, not on click 3
        self.cv.bind("<Double-Button-1>", self._rotate)
        self.cv.bind("<Triple-Button-1>", lambda e: None)
        self.cv.bind("<Quadruple-Button-1>", self._rotate)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Button-3>", lambda e: self._select(None))
        self.cv.bind("<Button-2>", lambda e: self._select(None))       # right button on macOS
        self.cv.tag_bind("token", "<Enter>", self._hover)
        self.cv.tag_bind("token", "<Leave>", lambda e: self._show_sub())

    def set_layout(self, layout: dict | None, message: str = "", show_measurements: bool | None = None):
        changed = (layout or {}).get("id") != (self.layout or {}).get("id")
        self.layout, self.message = layout, message
        if show_measurements is not None:
            self.show_measurements = show_measurements
        self.title.configure(text=f"Layout {layout.get('variant', '')}" if layout else "")
        self._show_sub()
        if changed:                                   # new board: every unit starts again in its zone
            self.regions = objective_regions(layout) if layout else []
            self.obstacles = Obstacles.from_layout(layout) if layout else None
            for t in self.tokens.values():
                self._place(t)
        self.draw()

    def _show_sub(self, text: str = ""):
        lay = self.layout
        default = (f"{lay['id']}  ·  {self.role_names['attacker']} deploys {lay.get('attacker_edge', '?')}, "
                   f"{self.role_names['defender']} {lay.get('defender_edge', '?')}") if lay else ""
        self.sub.configure(text=text or default)

    # ---------------------------------------------------------------- units
    def add_token(self, key: str, role: str, label: str, footprint: Footprint, move: float = 0.0,
                  ranges: tuple[float, ...] = ()):
        t = Token(key, role, label, footprint, move, tuple(ranges))
        self._place(t)
        self.tokens[key] = t
        self._draw_tokens()

    def remove_token(self, key: str):
        if self.tokens.pop(key, None):
            self.cv.delete(f"key:{key}")
            if self.selected == key:
                self._select(None)

    def _place(self, t: Token):
        zones = (self.layout or {}).get("deployment_zones", {}).get(t.role, [])
        others = [(o.x, o.y, *o.box) for o in self.tokens.values() if o is not t]
        t.x, t.y = random_spot(zones, *t.box, self.rng, avoid=others)

    # ---------------------------------------------------------------- selection
    def set_selected(self, key: str | None):
        """Show `key` as selected (None: nothing), without telling anyone."""
        if key != self.selected:
            self.selected = key if key in self.tokens else None
            self._draw_tokens()

    def _select(self, key: str | None):
        self.set_selected(key)
        if self.on_select:
            self.on_select(self, self.selected)

    def _rotate(self, e):
        self._press(e)               # a double click's second press replaces the plain press: still grab it
        key = self._key_at(e.x, e.y)
        if key in self.tokens:
            t = self.tokens[key]
            t.angle = (t.angle + ROTATE_STEP) % 360
            t.x, t.y = clamp(t.x, t.y, *t.box)             # turning can push it past an edge
            self._draw_tokens()

    def _key_at_current(self) -> str | None:
        for tag in self.cv.gettags("current"):
            if tag.startswith("key:"):
                return tag[4:]
        return None

    def _key_at(self, x: float, y: float) -> str | None:
        """The topmost token at canvas point (x, y)."""
        for item in reversed(self.cv.find_overlapping(x, y, x, y)):
            for tag in self.cv.gettags(item):
                if tag.startswith("key:"):
                    return tag[4:]
        return None

    def _press(self, e):
        key = self._key_at(e.x, e.y)
        if key and self._geom:
            t = self.tokens[key]
            bx, by = self._to_board(e.x, e.y)
            self._drag = (key, bx - t.x, by - t.y)
            self._select(key)
            self.cv.tag_raise(f"key:{key}")

    def _motion(self, e):
        if not self._drag or not self._geom or self._drag[0] not in self.tokens:
            return
        key, dx, dy = self._drag
        t = self.tokens[key]
        bx, by = self._to_board(e.x, e.y)
        nx, ny = clamp(bx - dx, by - dy, *t.box)
        k = self._geom[2]
        self.cv.move(f"key:{key}", (nx - t.x) * k, -(ny - t.y) * k)
        t.x, t.y = nx, ny
        self._schedule_overlays()

    def _release(self, e=None):
        """End of a drag: draw the overlays for where the unit ended up, now."""
        self._drag = None
        if self._overlay_job is not None:
            self.after_cancel(self._overlay_job)
            self._redraw_overlays()

    def _schedule_overlays(self):
        """While dragging, redraw the overlays at most every OVERLAY_DELAY ms: the unit itself moves
        at once, mouse events don't queue up behind line of sight computations."""
        if self._overlay_job is None:
            self._overlay_job = self.after(OVERLAY_DELAY, self._redraw_overlays)

    def _redraw_overlays(self):
        self._overlay_job = None
        self._draw_overlays()
        self._draw_plan_links()

    def _hover(self, e):
        key = self._key_at_current()
        if key in self.tokens:
            t = self.tokens[key]
            fp = t.footprint
            size = f'{fp.w:.1f}"' if abs(fp.w - fp.h) < 1e-6 else f'{fp.w:.1f}" x {fp.h:.1f}"'
            self._show_sub(f"{t.label}  ·  {fp.description}  ·  {size}"
                           + (f"  ·  turned {t.angle:.0f}°" if t.angle else "")
                           + ("  ·  base size estimated" if fp.estimated else ""))

    def _to_px(self, x: float, y: float) -> tuple[float, float]:
        ox, oy, k = self._geom
        return ox + x * k, oy + (BOARD_H - y) * k

    def _to_board(self, px: float, py: float) -> tuple[float, float]:
        ox, oy, k = self._geom
        return (px - ox) / k, BOARD_H - (py - oy) / k

    # ---------------------------------------------------------------- selected unit's overlays
    def set_overlays(self, **flags: bool):
        self.overlays.update(flags)
        self._draw_overlays()
        self._draw_plan_links()

    # ---------------------------------------------------------------- planned targets
    def set_plan_links(self, links: list[tuple[str, str, str]]):
        """(attacker token key, target token key, "primary" | "secondary") for every planned target."""
        self.plan_links = list(links)
        self._draw_plan_links()

    def _draw_plan_links(self):
        """Arrows from attackers to their planned targets placed on this board, edge to edge: solid to
        the 1st target, dashed to the 2nd (with "plan2"); the selected unit's only, unless "planall".
        Under the units, over the terrain."""
        cv = self.cv
        cv.delete("planlink")
        if not self.overlays["plan"] or not self._geom or not self.layout:
            return
        fam = font_family()
        tags = ("planlink",)
        for a_key, d_key, rank in self.plan_links:
            if rank == "secondary" and not self.overlays["plan2"]:
                continue
            if not self.overlays["planall"] and self.selected not in (a_key, d_key):
                continue
            a, d = self.tokens.get(a_key), self.tokens.get(d_key)
            if not a or not d:
                continue
            outline_a = ellipse_polygon(a.x, a.y, a.footprint.w, a.footprint.h, a.angle, n=36)
            outline_d = ellipse_polygon(d.x, d.y, d.footprint.w, d.footprint.h, d.angle, n=36)
            dist, p, q = distance_to_region(outline_a, [outline_d])
            if dist <= 0:                                   # touching: centre to centre
                p, q = (a.x, a.y), (d.x, d.y)
            first = rank == "primary"
            cv.create_line(*self._to_px(*p), *self._to_px(*q), fill=PLAN_INK, width=2.5 if first else 1.5,
                           dash="" if first else (6, 4), arrow="last", arrowshape=(10, 12, 4), tags=tags)
            mid = self._to_px((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            self._halo_text(*mid, "1st" if first else "2nd", PLAN_INK, fam, tags)
        cv.tag_raise("token")

    def _draw_overlays(self):
        """Movement rings and objective distances of the selected unit, under the tokens."""
        cv = self.cv
        cv.delete("overlay")
        t = self.tokens.get(self.selected or "")
        if not t or not self._geom or not self.layout:
            return
        fam = font_family()
        tags = ("overlay",)
        fp = t.footprint
        if self.overlays["sight"] and t.ranges and self.obstacles:
            outline = ellipse_polygon(t.x, t.y, fp.w, fp.h, t.angle, n=72)
            hidden = None
            if self.overlays["hidden"]:
                hidden = GO_TO_GROUND_RANGE if self.overlays["ground"] else HIDDEN_RANGE
            rays = cast(outline, max(t.ranges), self.obstacles, hidden=hidden)
            shade(cv, [[c for p in fan for c in self._to_px(*p)] for fan in fans(rays)],     # union: what it sees
                  SIGHT_FILL, SIGHT_STIPPLE, tags)
            if rays is not None and self.overlays["plan"]:      # what of it reaches its targets: green
                reaching = []
                for a_key, d_key, rank in self.plan_links:
                    d = self.tokens.get(d_key)
                    if a_key != t.key or not d or (rank == "secondary" and not self.overlays["plan2"]):
                        continue
                    target = ellipse_polygon(d.x, d.y, d.footprint.w, d.footprint.h, d.angle, n=36)
                    for fan in reaching_fans(rays, target):
                        pts = [c for p in fan for c in self._to_px(*p)]
                        if len(fan) > 2:
                            reaching.append(pts)
                        else:                                 # a lone ray
                            cv.create_line(pts, fill=TARGET_FILL, stipple=TARGET_STIPPLE, tags=tags)
                shade(cv, reaching, TARGET_FILL, TARGET_STIPPLE, tags)
            # each circle's distance written where it faces the board centre: on the board, spread out
            cx, cy = BOARD_W / 2 - t.x, BOARD_H / 2 - t.y
            norm = (cx * cx + cy * cy) ** 0.5 or 1.0
            for r in t.ranges:
                pts = offset_ellipse(t.x, t.y, fp.w, fp.h, t.angle, r)
                cv.create_polygon([c for p in pts for c in self._to_px(*p)], fill="", outline=RANGE_INK,
                                  width=1, smooth=True, tags=tags)
                at = max(pts, key=lambda p: ((p[0] - t.x) * cx + (p[1] - t.y) * cy) / norm)
                self._halo_text(*self._to_px(*at), f'{r:g}"', RANGE_INK, fam, tags)
        for (label, d), ink in zip(rings(t.move, self.overlays["move"], self.overlays["advance"],
                                         self.overlays["charge"]), RING_INK):
            pts = offset_ellipse(t.x, t.y, fp.w, fp.h, t.angle, d)
            cv.create_polygon([c for p in pts for c in self._to_px(*p)], fill="", outline=ink, width=2,
                              dash=(6, 3), smooth=True, tags=tags)
            top = max(pts, key=lambda p: p[1])                     # write it at the ring's top
            self._halo_text(*self._to_px(*top), label, ink, fam, tags, anchor="s")
        if self.overlays["objectives"]:
            outline = ellipse_polygon(t.x, t.y, fp.w, fp.h, t.angle, n=36)
            for r in self.regions:
                d, near, far = distance_to_region(outline, r["polygons"])
                if d > 0:                                   # unit edge to the objective's terrain edge
                    cv.create_line(*self._to_px(*near), *self._to_px(*far), fill=DISTANCE_INK, width=1.5,
                                   dash=DISTANCE_DASH, tags=tags)
                    at = self._to_px((near[0] + far[0]) / 2, (near[1] + far[1]) / 2)
                else:                                       # on the objective's terrain already
                    at = self._to_px(*r["position"])
                self._halo_text(*at, f'{d:.1f}"', DISTANCE_INK, fam, tags)
        cv.tag_raise("token")

    def _halo_text(self, x, y, text, ink, fam, tags, anchor="center"):
        label = self.cv.create_text(x, y, text=text, fill=ink, font=(fam, 8, "bold"), anchor=anchor, tags=tags)
        bb = self.cv.bbox(label)
        (left, top), (right, bottom) = self._to_px(0, BOARD_H), self._to_px(BOARD_W, 0)
        dx = max(0, left + 2 - bb[0]) - max(0, bb[2] - right + 2)            # keep it on the board
        dy = max(0, top + 2 - bb[1]) - max(0, bb[3] - bottom + 2)
        if dx or dy:
            self.cv.move(label, dx, dy)
            bb = self.cv.bbox(label)
        halo = self.cv.create_rectangle(bb[0] - 2, bb[1], bb[2] + 2, bb[3], fill="white", outline="", tags=tags)
        self.cv.tag_lower(halo, label)

    def _draw_tokens(self):
        cv = self.cv
        cv.delete("token")
        self._draw_overlays()
        if not self._geom or not self.layout:
            return
        k = self._geom[2]
        fam = font_family()
        order = sorted(self.tokens.values(), key=lambda t: t.key == self.selected)   # selected on top
        for t in order:
            x, y = self._to_px(t.x, t.y)
            fill, line = TOKEN[t.role]
            chosen = t.key == self.selected
            tags = ("token", f"key:{t.key}")
            outline = [c for p in ellipse_polygon(t.x, t.y, t.footprint.w, t.footprint.h, t.angle)
                       for c in self._to_px(*p)]
            if chosen:
                cv.create_polygon(outline, fill="", outline=SELECTED, width=5, smooth=True, tags=tags)
            if not STIPPLES:                     # macOS: the fill as an image, under an outline of its own
                shade(cv, [outline], fill, TOKEN_STIPPLE, tags)
            cv.create_polygon(outline, fill=fill if STIPPLES else "", stipple=TOKEN_STIPPLE, outline=line, width=1.5,
                              smooth=True, dash=(4, 2) if t.footprint.estimated else "", tags=tags)
            bw, bh = (d * k for d in t.box)
            label = cv.create_text(x, y, text=compact_label(t.label), fill=line, font=(fam, 8, "bold"),
                                   width=max(LABEL_WIDTH, bw), tags=tags)
            self._place_label(label, x, y, bw, bh, self.layout.get(f"{t.role}_edge", "bottom"))
            bb = cv.bbox(label)
            halo = cv.create_rectangle(bb[0] - 2, bb[1], bb[2] + 2, bb[3], fill="white", outline="",
                                       stipple="gray75", tags=tags)
            cv.tag_lower(halo, label)
        self._draw_plan_links()

    def _place_label(self, label, x, y, bw, bh, edge: str):
        """Put a unit's label outside its base, on the side of its player's board edge (attacker at the
        bottom: below the base); on the other side if it would leave the board; never past an edge."""
        cv = self.cv
        (left, top), (right, bottom) = self._to_px(0, BOARD_H), self._to_px(BOARD_W, 0)
        spots = {"bottom": ("n", "center", x, y + bh / 2 + 2), "top": ("s", "center", x, y - bh / 2 - 2),
                 "left": ("e", "right", x - bw / 2 - 3, y), "right": ("w", "left", x + bw / 2 + 3, y)}
        opposite = {"bottom": "top", "top": "bottom", "left": "right", "right": "left"}
        edge = edge if edge in spots else "bottom"
        for side in (edge, opposite[edge]):
            anchor, justify, lx, ly = spots[side]
            cv.itemconfigure(label, anchor=anchor, justify=justify)
            cv.coords(label, lx, ly)
            bb = cv.bbox(label)
            if left <= bb[0] and bb[2] <= right and top <= bb[1] and bb[3] <= bottom:
                break
        bb = cv.bbox(label)
        dx = max(0, left + 2 - bb[0]) - max(0, bb[2] - right + 2)               # keep it on the board
        dy = max(0, top + 2 - bb[1]) - max(0, bb[3] - bottom + 2)
        if dx or dy:
            cv.move(label, dx, dy)

    # ---------------------------------------------------------------- drawing
    def draw(self):
        cv = self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        fam = font_family()
        if not self.layout:
            self._geom = None
            if self.message:
                cv.create_text(W / 2, H / 2, text=self.message, fill=C["muted"], font=(fam, 10), width=W - 20)
            return
        pad = 4
        k = min((W - 2 * pad) / BOARD_W, (H - 2 * pad) / BOARD_H)
        if k <= 0:
            return
        ox = (W - BOARD_W * k) / 2
        oy = (H - BOARD_H * k) / 2
        self._geom = (ox, oy, k)

        def xy(p):                                     # board inches (y up) -> canvas pixels
            return ox + p[0] * k, oy + (BOARD_H - p[1]) * k

        def flat(points):
            return [c for p in points for c in xy(p)]

        cv.create_rectangle(ox, oy, ox + BOARD_W * k, oy + BOARD_H * k, fill=BOARD_FILL, outline="")
        lay = self.layout
        for side in ("attacker", "defender"):
            for poly in lay.get("deployment_zones", {}).get(side, []):
                if len(poly) >= 3:
                    cv.create_polygon(flat(poly), fill=ZONE_FILL[side], outline="")
        areas = lay.get("terrain", [])
        for area in areas:                              # every footprint first, so none hides a feature
            for fp in area.get("footprints", []):
                if len(fp.get("points", [])) >= 3:
                    cv.create_polygon(flat(fp["points"]), fill=AREA_FILL, outline=AREA_LINE)
        for area in areas:
            for f in area.get("features", []):
                if len(f.get("points", [])) >= 3:
                    cv.create_polygon(flat(f["points"]), fill=FEATURE_FILL.get(f.get("category"), "#8a857a"),
                                      outline="")
        if self.show_territory:
            line = territory_line(lay)
            if line:
                cv.create_line(*xy(line[0]), *xy(line[1]), fill=TERRITORY_INK, width=2, dash=TERRITORY_DASH)
        if self.show_measurements:
            m = lay.get("measurements", {})
            for x1, y1, x2, y2 in m.get("lines", []):
                cv.create_line(*xy((x1, y1)), *xy((x2, y2)), fill=MEASURE, dash=(3, 2))
            size = max(7, min(9, int(k * 1.1)))
            for lb in m.get("labels", []):
                x, y = xy((lb["x"], lb["y"]))
                t = cv.create_text(x, y, text=lb["text"], fill=BOARD_INK, font=(fam, size))
                bb = cv.bbox(t)
                r = cv.create_rectangle(bb[0] - 1, bb[1], bb[2] + 1, bb[3], fill=BOARD_FILL, outline="")
                cv.tag_raise(t, r)
        r = max(6.0, 0.9 * k)
        for o in lay.get("objectives", []):
            x, y = xy(o["position"])
            cv.create_oval(x - r, y - r, x + r, y + r, fill=objective_fill(o), outline="white", width=2)
            cv.create_text(x, y, text=str(o["number"]), fill="white", font=(fam, max(7, int(r * 0.9)), "bold"))
        cv.create_rectangle(ox, oy, ox + BOARD_W * k, oy + BOARD_H * k, outline=BOARD_INK)
        self._edge_labels(ox, oy, k, fam)
        self._draw_tokens()

    def _edge_labels(self, ox, oy, k, fam):
        """ATTACKER / DEFENDER written inside the board along each side's deployment edge."""
        w, h = BOARD_W * k, BOARD_H * k
        spots = {"left": (ox + 10, oy + h / 2, 90), "right": (ox + w - 10, oy + h / 2, 270),
                 "bottom": (ox + w / 2, oy + h - 9, 0), "top": (ox + w / 2, oy + 9, 0)}
        for side in ("attacker", "defender"):
            edge = self.layout.get(f"{side}_edge", "")
            if edge in spots:
                x, y, angle = spots[edge]
                self.cv.create_text(x, y, text=self.role_names[side].upper(), angle=angle, fill=ZONE_INK[side],
                                    font=(fam, 8, "bold"))


def legend(master) -> ttk.Frame:
    """Key to the map colours."""
    f = ttk.Frame(master, style="Flat.TFrame")
    fam = font_family()
    rows = [("zone", ZONE_FILL["attacker"], "Attacker deployment zone"),
            ("zone", ZONE_FILL["defender"], "Defender deployment zone"),
            ("area", AREA_FILL, "Terrain area"),
            ("area", FEATURE_FILL["DENSE"], "Dense terrain feature"),
            ("area", FEATURE_FILL["LIGHT"], "Light terrain feature"),
            ("obj", ZONE_INK["attacker"], "Attacker home objective"),
            ("obj", ZONE_INK["defender"], "Defender home objective"),
            ("obj", OBJ_FILL["expansion"], "Expansion objective"),
            ("obj", OBJ_FILL["central"], "Central objective")]
    for kind, color, text in rows:
        row = ttk.Frame(f, style="Flat.TFrame")
        row.pack(anchor="w")
        sw = tk.Canvas(row, width=18, height=14, bg=C["panel"], highlightthickness=0)
        if kind == "obj":
            sw.create_oval(3, 1, 15, 13, fill=color, outline="white")
        else:
            sw.create_rectangle(1, 2, 17, 12, fill=color, outline=AREA_LINE if kind == "area" else "")
        sw.pack(side="left")
        ttk.Label(row, text=text, style="Panel.TLabel", font=(fam, 9)).pack(side="left", padx=(4, 0))
    return f
