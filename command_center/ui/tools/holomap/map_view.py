"""A battlefield layout with the units placed on it (the layout itself: command_center.ui.views.board).

Units are tokens (a base, or the ellipse of a whole unit) that start at a random spot in their
side's deployment zone and can be dragged anywhere on the board, stopping at its edges. They are
half see-through so terrain shows underneath. A click selects a token, a double click turns it 30
degrees clockwise, a right click releases the selection.

For the selected unit the map can also draw its movement rings (move, advance, charge: lines at that
distance from its footprint edge), the shortest line from it to each objective, an objective being
the whole terrain its marker stands on (command_center.deploy.objectives), and its line of sight: what it can
see up to its longest weapon range (command_center.deploy.sight), with a circle per weapon range; with the
planned targets shown too, the part of it reaching its 1st target (and 2nd, with "plan2") is green.

The map can also draw arrows to planned targets (the Engagement Optimizer's army plan): set_plan_links() gives
the pairs; the "plan" overlay shows the selected unit's 1st target (or, for a selected defender, the
attackers aiming at it), "plan2" adds 2nd targets, "planall" shows every attacker's."""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem, QGraphicsPolygonItem, QSizePolicy, QVBoxLayout,
                               QWidget)

from command_center.deploy import Footprint
from command_center.deploy.movement import rings
from command_center.deploy.objectives import distance_to_region, objective_regions
from command_center.deploy.placement import clamp, ellipse_polygon, extent, offset_ellipse, random_spot
from command_center.deploy.sight import GO_TO_GROUND_RANGE, HIDDEN_RANGE, Obstacles, cast, fans, reaching_fans
from command_center.ui.theme import C, font_family
from command_center.ui.views.board import (AREA_FILL, AREA_LINE, BOARD_H, BOARD_W, FEATURE_FILL, NO_PEN, OBJ_FILL,
                                           ZONE_FILL, ZONE_INK, LayoutMap, PixelText, line_pen, polygon)

TOKEN = {"attacker": ("#c9474b", "#6b1417"), "defender": ("#3d73b3", "#12304f")}   # fill, outline
TOKEN_OPACITY = 0.5               # terrain stays visible underneath
SELECTED = "#e0a800"
ROTATE_STEP = 30                  # degrees clockwise per double click
RING_INK = ["#2f7d32", "#c26a00", "#7b3fa0"]      # innermost ring first
DISTANCE_INK = "#1d1c1a"
DISTANCE_DASH = (5, 2, 1.5, 2)    # dash-dot, in widths of the line: visible without hiding the terrain
SIGHT_FILL, SIGHT_OPACITY = "#6e6a63", 0.125      # very light grey
RANGE_INK = "#55524c"
TARGET_FILL, TARGET_OPACITY = "#2e9e44", 0.25     # faint green: the sight reaching its planned target(s)
PLAN_INK = ZONE_INK["attacker"]
OVERLAY_DELAY = 30                # ms between overlay redraws while dragging
OVERLAYS = ("move", "advance", "charge", "objectives", "plan", "plan2", "planall", "sight", "hidden", "ground")
LABEL_WIDTH = 110                 # pixels: longer board labels wrap onto another line
HALO = QColor(255, 255, 255, 190)     # behind a unit's label: the board shows through a little
Z_OVERLAY, Z_LINK, Z_TOKEN, Z_CHOSEN = 5, 6, 10, 20       # what is drawn over what


def see_through(color: str, opacity: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(opacity)
    return c


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


def compact_label(name: str) -> str:
    """Board label: the unit without a trailing "Squad", attached characters on a second line.
    "Bladeguard Veteran Squad + Sanguinary Priest" -> "Bladeguard Veteran\\n+ Sanguinary Priest"."""
    parts = [p.strip() for p in name.split(" + ")]
    first = re.sub(r"\s+Squad\b", "", parts[0])
    return first + ("\n+ " + " + ".join(parts[1:]) if len(parts) > 1 else "")


class TokenItem(QGraphicsPolygonItem):
    """A unit on the board: its footprint's outline around where it stands. Qt drags it; the map hears
    of every move, and keeps it on the board."""

    def __init__(self, board: "UnitMap", token: Token):
        super().__init__()
        self.board, self.token = board, token
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setPos(token.x, token.y)
        self.shape_it()

    def shape_it(self):
        """Its outline, for the angle it is turned at, and its look: selected or not."""
        t = self.token
        self.setPolygon(polygon(ellipse_polygon(0, 0, t.footprint.w, t.footprint.h, t.angle)))
        fill, line = TOKEN[t.role]
        chosen = self.board.selected == t.key
        pen = line_pen(SELECTED if chosen else line, 3 if chosen else 1.5, (3, 1.5) if t.footprint.estimated else None)
        self.setPen(pen)
        self.setBrush(see_through(fill, TOKEN_OPACITY))
        self.setZValue(Z_CHOSEN if chosen else Z_TOKEN)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(*clamp(value.x(), value.y(), *self.token.box))
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.token.x, self.token.y = self.x(), self.y()
            self.board.token_moved(self.token)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.board.pick(self.token.key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.board.rotate(self.token.key)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.board.token_released()

    def hoverEnterEvent(self, event):
        self.board.describe(self.token)

    def hoverLeaveEvent(self, event):
        self.board.describe(None)


class ArrowHead(QGraphicsPolygonItem):
    """The head of an arrow ending at a point of the board, its size in pixels whatever the scale."""

    def __init__(self, at, towards, color: str):
        super().__init__(QPolygonF([QPointF(0, 0), QPointF(-12, -4.5), QPointF(-10, 0), QPointF(-12, 4.5)]))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setPen(NO_PEN)
        self.setBrush(QColor(color))
        self.setPos(*at)
        # the board's y goes up, the screen's down
        self.setRotation(math.degrees(math.atan2(-(at[1] - towards[1]), at[0] - towards[0])))


class UnitMap(LayoutMap):
    def __init__(self):
        super().__init__()
        self.tokens: dict[str, Token] = {}
        self.items: dict[str, TokenItem] = {}
        self.labels: dict[str, PixelText] = {}
        self.rng = random.Random()
        self.selected: str | None = None
        self.on_select = None                                       # callback(map, key or None)
        self.overlays: dict[str, bool] = {name: False for name in OVERLAYS}
        self.regions: list[dict] = []                               # objectives as terrain, per layout
        self.obstacles: Obstacles | None = None                    # what blocks line of sight, per layout
        self.plan_links: list[tuple[str, str, str]] = []           # (attacker key, target key, rank)
        self._overlay_items: list[QGraphicsItem] = []
        self._link_items: list[QGraphicsItem] = []
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._redraw_overlays)
        self.view.scaled.connect(self._place_labels)               # labels are in pixels: placed again at a new scale
        self.view.right_clicked.connect(lambda: self._select(None))

    def set_layout(self, layout: dict | None, message: str = "", show_measurements: bool | None = None):
        changed = (layout or {}).get("id") != (self.layout_data or {}).get("id")
        if changed:                                   # new board: every unit starts again in its zone
            self.layout_data = layout
            self.regions = objective_regions(layout) if layout else []
            self.obstacles = Obstacles.from_layout(layout) if layout else None
            for t in self.tokens.values():
                self._place(t)
        super().set_layout(layout, message, show_measurements)

    def draw(self):
        """The layout, then the units on it: drawing the layout clears the scene."""
        self.items, self.labels, self._overlay_items, self._link_items = {}, {}, [], []
        super().draw()
        if self.layout_data:
            for t in self.tokens.values():
                self._add_item(t)
            self._draw_overlays()
            self._draw_plan_links()

    # ---------------------------------------------------------------- units
    def add_token(self, key: str, role: str, label: str, footprint: Footprint, move: float = 0.0,
                  ranges: tuple[float, ...] = ()):
        t = Token(key, role, label, footprint, move, tuple(ranges))
        self._place(t)
        self.tokens[key] = t
        if self.layout_data:
            self._add_item(t)

    def remove_token(self, key: str):
        if self.tokens.pop(key, None):
            for held in (self.items, self.labels):
                item = held.pop(key, None)
                if item is not None:
                    self.scene.removeItem(item)
            if self.selected == key:
                self._select(None)

    def _place(self, t: Token):
        zones = (self.layout_data or {}).get("deployment_zones", {}).get(t.role, [])
        others = [(o.x, o.y, *o.box) for o in self.tokens.values() if o is not t]
        t.x, t.y = random_spot(zones, *t.box, self.rng, avoid=others)

    def _add_item(self, t: Token):
        item = self.items[t.key] = TokenItem(self, t)
        self.scene.addItem(item)
        self._label(t)

    def _label(self, t: Token):
        """A unit's label outside its base, on the side of its player's board edge (attacker at the
        bottom: below the base); on the other side if it would leave the board; never past an edge."""
        old = self.labels.pop(t.key, None)
        if old is not None:
            self.scene.removeItem(old)
        k = self.view.pixels_per_inch or 1.0
        bw, bh = t.box
        edge = (self.layout_data or {}).get(f"{t.role}_edge", "bottom")
        align = {"left": Qt.AlignRight, "right": Qt.AlignLeft}.get(edge, Qt.AlignHCenter)
        tag = PixelText(compact_label(t.label), 0, 0, TOKEN[t.role][1], bold=True, back=HALO, align=align,
                        width=max(LABEL_WIDTH, bw * k))
        w, h = (d / k for d in tag.size)                        # its size in inches, at this scale
        gap = 3 / k
        spots = {"bottom": (t.x, t.y - bh / 2 - gap - h / 2), "top": (t.x, t.y + bh / 2 + gap + h / 2),
                 "left": (t.x - bw / 2 - gap - w / 2, t.y), "right": (t.x + bw / 2 + gap + w / 2, t.y)}
        opposite = {"bottom": "top", "top": "bottom", "left": "right", "right": "left"}
        edge = edge if edge in spots else "bottom"
        x, y = spots[edge]
        if not (w / 2 <= x <= BOARD_W - w / 2 and h / 2 <= y <= BOARD_H - h / 2):
            x, y = spots[opposite[edge]]
        x = min(max(x, w / 2 + gap), BOARD_W - w / 2 - gap) if w < BOARD_W else BOARD_W / 2     # keep it on the board
        y = min(max(y, h / 2 + gap), BOARD_H - h / 2 - gap) if h < BOARD_H else BOARD_H / 2
        tag.setPos(x, y)
        tag.setZValue((Z_CHOSEN if self.selected == t.key else Z_TOKEN) + 0.5)
        tag.setAcceptedMouseButtons(Qt.NoButton)                # a click on it goes to what is under it
        self.scene.addItem(tag)
        self.labels[t.key] = tag

    def _place_labels(self):
        for t in self.tokens.values():
            if t.key in self.items:
                self._label(t)
        self._draw_overlays()                                   # their texts are in pixels too
        self._draw_plan_links()

    # ---------------------------------------------------------------- selection, moves
    def set_selected(self, key: str | None):
        """Show `key` as selected (None: nothing), without telling anyone."""
        if key != self.selected:
            was, self.selected = self.selected, key if key in self.tokens else None
            for k in (was, self.selected):
                if k in self.items:
                    self.items[k].shape_it()
                    self._label(self.tokens[k])
            self._draw_overlays()
            self._draw_plan_links()

    def _select(self, key: str | None):
        self.set_selected(key)
        if self.on_select:
            self.on_select(self, self.selected)

    def pick(self, key: str):
        """A unit was pressed: it is the selected one."""
        if key != self.selected:
            self._select(key)

    def rotate(self, key: str):
        """Turn a unit by a step, clockwise; turning can push it past an edge: it is kept on the board."""
        t = self.tokens[key]
        t.angle = (t.angle + ROTATE_STEP) % 360
        item = self.items[key]
        item.shape_it()
        item.setPos(*clamp(t.x, t.y, *t.box))
        self._label(t)
        self._redraw_overlays()

    def move_token(self, key: str, x: float, y: float):
        """Put a unit somewhere on the board, as a drag would (it stops at the edges)."""
        self.items[key].setPos(x, y)
        self.token_released()

    def token_moved(self, t: Token):
        """A unit is being dragged: its label follows at once; the overlays at most every OVERLAY_DELAY ms,
        so that mouse events don't queue up behind line of sight computations."""
        if t.key in self.labels:
            self._label(t)
        if not self._overlay_timer.isActive():
            self._overlay_timer.start(OVERLAY_DELAY)

    def token_released(self):
        """End of a drag: draw the overlays for where the unit ended up, now."""
        if self._overlay_timer.isActive():
            self._redraw_overlays()

    def _redraw_overlays(self):
        self._overlay_timer.stop()
        self._draw_overlays()
        self._draw_plan_links()

    def describe(self, t: Token | None):
        """Under the title: the unit the pointer is on (None: the layout's own line)."""
        if t is None:
            return self._show_sub()
        fp = t.footprint
        size = f'{fp.w:.1f}"' if abs(fp.w - fp.h) < 1e-6 else f'{fp.w:.1f}" x {fp.h:.1f}"'
        self._show_sub(f"{t.label}  ·  {fp.description}  ·  {size}" + (f"  ·  turned {t.angle:.0f}°" if t.angle else "")
                       + ("  ·  base size estimated" if fp.estimated else ""))

    # ---------------------------------------------------------------- what is drawn over the board
    def _clear(self, items: list):
        for item in items:
            self.scene.removeItem(item)
        items.clear()

    def _add(self, items: list, item: QGraphicsItem, z: float) -> QGraphicsItem:
        item.setZValue(z)
        item.setAcceptedMouseButtons(Qt.NoButton)
        if item.scene() is None:
            self.scene.addItem(item)
        items.append(item)
        return item

    def _halo_text(self, items: list, x: float, y: float, text: str, ink: str, z: float, above: bool = False):
        """A small text on a white box, kept on the board; `above`: it sits on the point, not around it."""
        tag = PixelText(text, 0, 0, ink, bold=True, back="white")
        k = self.view.pixels_per_inch or 1.0
        w, h = (d / k for d in tag.size)
        if above:
            y += h / 2
        tag.setPos(min(max(x, w / 2 + 2 / k), BOARD_W - w / 2 - 2 / k), min(max(y, h / 2 + 2 / k), BOARD_H - h / 2 - 2 / k))
        self._add(items, tag, z + 0.5)

    def _shade(self, items: list, polygons, color: str, opacity: float, z: float):
        """Fill the union of polygons, see-through: one shape, so no darker where they overlap."""
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for points in polygons:
            if len(points) >= 3:
                path.addPolygon(polygon(points))
                path.closeSubpath()
        if not path.isEmpty():
            item = QGraphicsPathItem(path)
            item.setPen(NO_PEN)
            item.setBrush(see_through(color, opacity))
            self._add(items, item, z)

    def set_overlays(self, **flags: bool):
        self.overlays.update(flags)
        self._draw_overlays()
        self._draw_plan_links()

    def set_plan_links(self, links: list[tuple[str, str, str]]):
        """(attacker token key, target token key, "primary" | "secondary") for every planned target."""
        self.plan_links = list(links)
        self._draw_plan_links()

    def _draw_plan_links(self):
        """Arrows from attackers to their planned targets placed on this board, edge to edge: solid to
        the 1st target, dashed to the 2nd (with "plan2"); the selected unit's only, unless "planall".
        Under the units, over the terrain."""
        items = self._link_items
        self._clear(items)
        if not self.overlays["plan"] or not self.layout_data:
            return
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
            self._add(items, self.scene.addLine(*p, *q, line_pen(PLAN_INK, 2.5 if first else 1.5, None if first else (4, 2.7))),
                      Z_LINK)
            self._add(items, ArrowHead(q, p, PLAN_INK), Z_LINK)
            self._halo_text(items, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2, "1st" if first else "2nd", PLAN_INK, Z_LINK)

    def _draw_overlays(self):
        """Movement rings, objective distances and line of sight of the selected unit, under the tokens."""
        items = self._overlay_items
        self._clear(items)
        t = self.tokens.get(self.selected or "")
        if not t or not self.layout_data:
            return
        fp = t.footprint
        if self.overlays["sight"] and t.ranges and self.obstacles:
            outline = ellipse_polygon(t.x, t.y, fp.w, fp.h, t.angle, n=72)
            hidden = None
            if self.overlays["hidden"]:
                hidden = GO_TO_GROUND_RANGE if self.overlays["ground"] else HIDDEN_RANGE
            rays = cast(outline, max(t.ranges), self.obstacles, hidden=hidden)
            self._shade(items, fans(rays), SIGHT_FILL, SIGHT_OPACITY, Z_OVERLAY)       # union: what it sees
            if rays is not None and self.overlays["plan"]:      # what of it reaches its targets: green
                reaching = []
                for a_key, d_key, rank in self.plan_links:
                    d = self.tokens.get(d_key)
                    if a_key != t.key or not d or (rank == "secondary" and not self.overlays["plan2"]):
                        continue
                    target = ellipse_polygon(d.x, d.y, d.footprint.w, d.footprint.h, d.angle, n=36)
                    for fan in reaching_fans(rays, target):
                        if len(fan) > 2:
                            reaching.append(fan)
                        else:                                 # a lone ray
                            self._add(items, self.scene.addLine(*fan[0], *fan[1], line_pen(TARGET_FILL)), Z_OVERLAY)
                self._shade(items, reaching, TARGET_FILL, TARGET_OPACITY, Z_OVERLAY + 0.1)
            # each circle's distance written where it faces the board centre: on the board, spread out
            cx, cy = BOARD_W / 2 - t.x, BOARD_H / 2 - t.y
            norm = (cx * cx + cy * cy) ** 0.5 or 1.0
            for r in t.ranges:
                pts = offset_ellipse(t.x, t.y, fp.w, fp.h, t.angle, r)
                self._add(items, self.scene.addPolygon(polygon(pts), line_pen(RANGE_INK)), Z_OVERLAY + 0.2)
                at = max(pts, key=lambda p: ((p[0] - t.x) * cx + (p[1] - t.y) * cy) / norm)
                self._halo_text(items, *at, f'{r:g}"', RANGE_INK, Z_OVERLAY + 0.2)
        for (name, d), ink in zip(rings(t.move, self.overlays["move"], self.overlays["advance"],
                                        self.overlays["charge"]), RING_INK):
            pts = offset_ellipse(t.x, t.y, fp.w, fp.h, t.angle, d)
            self._add(items, self.scene.addPolygon(polygon(pts), line_pen(ink, 2, (3, 1.5))), Z_OVERLAY + 0.3)
            top = max(pts, key=lambda p: p[1])                     # write it at the ring's top
            self._halo_text(items, *top, name, ink, Z_OVERLAY + 0.3, above=True)
        if self.overlays["objectives"]:
            outline = ellipse_polygon(t.x, t.y, fp.w, fp.h, t.angle, n=36)
            for r in self.regions:
                d, near, far = distance_to_region(outline, r["polygons"])
                if d > 0:                                   # unit edge to the objective's terrain edge
                    self._add(items, self.scene.addLine(*near, *far, line_pen(DISTANCE_INK, 1.5, DISTANCE_DASH)),
                              Z_OVERLAY + 0.4)
                    at = ((near[0] + far[0]) / 2, (near[1] + far[1]) / 2)
                else:                                       # on the objective's terrain already
                    at = r["position"]
                self._halo_text(items, *at, f'{d:.1f}"', DISTANCE_INK, Z_OVERLAY + 0.4)


class Legend(QWidget):
    """Key to the map colours."""

    ROWS = [("zone", ZONE_FILL["attacker"], "Attacker deployment zone"),
            ("zone", ZONE_FILL["defender"], "Defender deployment zone"),
            ("area", AREA_FILL, "Terrain area"),
            ("area", FEATURE_FILL["DENSE"], "Dense terrain feature"),
            ("area", FEATURE_FILL["LIGHT"], "Light terrain feature"),
            ("obj", ZONE_INK["attacker"], "Attacker home objective"),
            ("obj", ZONE_INK["defender"], "Defender home objective"),
            ("obj", OBJ_FILL["expansion"], "Expansion objective"),
            ("obj", OBJ_FILL["central"], "Central objective")]
    ROW = 16

    def __init__(self):
        super().__init__()
        font = self.font()
        font.setFamily(font_family())
        font.setPointSize(9)
        self.setFont(font)
        width = max(self.fontMetrics().horizontalAdvance(text) for _, _, text in self.ROWS)
        self.setFixedSize(24 + width + 2, self.ROW * len(self.ROWS))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for n, (kind, color, text) in enumerate(self.ROWS):
            y = n * self.ROW
            p.setBrush(QColor(color))
            if kind == "obj":
                p.setPen(QColor("white"))
                p.drawEllipse(QRectF(3.5, y + 2.5, 11, 11))
            else:
                p.setPen(QColor(AREA_LINE) if kind == "area" else Qt.NoPen)
                p.drawRect(QRectF(1.5, y + 3.5, 15, 9))
            p.setPen(QColor(C["ink"]))
            p.drawText(QRectF(22, y, self.width() - 22, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, text)
