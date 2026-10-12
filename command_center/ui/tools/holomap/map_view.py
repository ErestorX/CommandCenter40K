"""A battlefield layout with the units placed on it (the layout itself: command_center.ui.views.board).

Units are tokens (a base, or the ellipse of a whole unit) that start at a random spot in their
side's deployment zone and can be dragged anywhere on the board, stopping at its edges. They are
half see-through so terrain shows underneath. A click selects a token, a right click on no token
releases the selection. A right click on a token opens its menu: to the reserves or back (see
below); under "Rotate", a turn of 15 or 45 degrees, clockwise or counter-clockwise; and, for a unit of
several models, under "Formation", how its models stand, which sets the size and shape of its token
(command_center.deploy.bases: compact, 1" apart as it starts, spread as far as it may, or in a line,
which is a tube and not an ellipse). Each board keeps its own.

Under "Unit", the menu counts the unit's models on that board: "-1 Model" takes one off (those that
are not characters first, the smallest bases first), "+1 Model" puts one back, up to the strength it
started at, and the token is sized again for the models left; while some are missing, "left/started"
is written above it. "Destroyed" takes them all: the token turns grey and fainter and goes to the
reserves (it can be brought back to the board), with nothing measured or seen from it; "+1 Model"
gives it its first model, and its colour, back.

A unit's name is written inside its base, along it, as large as fits and on as many lines as that
takes; what does not fit, even at the smallest size, is cut short with an ellipsis (fit_label). The
whole name is in the token's tooltip, and under the map's title while the pointer is on it.

For the selected unit the map can also draw its movement rings (move, advance, charge: lines at that
distance from its footprint edge), the shortest line from it to each objective, an objective being
the whole terrain its marker stands on (command_center.deploy.objectives), and its line of sight: what it can
see up to its longest weapon range (command_center.deploy.sight), with a circle per weapon range; with the
planned targets shown too, the part of it reaching its 1st target (and 2nd, with "plan2") is green.
Every enemy unit that line of sight gets to, be it by a corner of its base, has a faint glow around it.
While the unit is dragged its line of sight is a draft, cast with fewer rays; it is cast in full as
soon as the unit is let go.

Under the board, a "Reserves and Transports" space, split in half: the attacker's on the left, the
defender's on the right. A unit's menu sends it there, or back to the board where it stood. A unit in reserve is dragged about its half only, and has no rings, distances or
line of sight; arrows to and from planned targets are drawn all the same, and no line of sight
from the board gets to it.

The map can also draw arrows to planned targets (the Engagement Optimizer's army plan): set_plan_links() gives
the pairs; the "plan" overlay shows the selected unit's 1st target (or, for a selected defender, the
attackers aiming at it), "plan2" adds 2nd targets, "planall" shows every attacker's."""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Callable, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem, QGraphicsPolygonItem, QGraphicsRectItem, QMenu,
                               QSizePolicy, QVBoxLayout, QWidget, QWidgetAction)

from command_center.deploy import Footprint
from command_center.deploy.bases import FORMATIONS, SPACED, TUBE, Base, remaining_bases, unit_footprint
from command_center.deploy.movement import rings
from command_center.deploy.objectives import distance_to_region, objective_regions
from command_center.deploy.placement import clamp, extent, offset_outline, outline, overlaps, random_spot
from command_center.deploy.sight import (DRAFT_DIRECTIONS, DRAFT_ORIGINS, GO_TO_GROUND_RANGE, HIDDEN_RANGE, Obstacles,
                                         cast, fans, reaching_fans, sees)
from command_center.ui.theme import C, font_family
from command_center.ui.views.board import (AREA_FILL, AREA_LINE, BOARD_H, BOARD_INK, BOARD_W, FEATURE_FILL, NO_PEN,
                                           OBJ_FILL, ZONE_FILL, ZONE_INK, BoardView, LayoutMap, PixelText, line_pen,
                                           polygon)
from command_center.ui.widgets import label

TOKEN = {"attacker": ("#c9474b", "#6b1417"), "defender": ("#3d73b3", "#12304f")}   # fill, outline
TOKEN_OPACITY = 0.5               # terrain stays visible underneath
SELECTED = "#e0a800"
# the turns a unit's menu offers, under its "Rotate" heading: degrees clockwise, and how each is written
ROTATE = "Rotate"
FORMATION = "Formation"           # the heading of the formations (command_center.deploy.bases.FORMATIONS) in that menu
UNIT, LOSE_MODEL, ADD_MODEL, DESTROYED = "Unit", "-1 Model", "+1 Model", "Destroyed"       # and of the unit's models
GONE = ("#8d8d8d", "#6a6a6a")     # a destroyed unit: fill, outline
GONE_OPACITY = 0.25               # and fainter than a unit still there
COUNT_BACK = QColor(255, 255, 255, 200)       # behind the "left/started" written above a unit short of models
ROTATIONS = ((15, "↻  15°"), (45, "↻  45°"), (-15, "↺  15°"), (-45, "↺  45°"))
RING_INK = ["#2f7d32", "#c26a00", "#7b3fa0"]      # innermost ring first
DISTANCE_INK = "#1d1c1a"
DISTANCE_DASH = (5, 2, 1.5, 2)    # dash-dot, in widths of the line: visible without hiding the terrain
SIGHT_FILL, SIGHT_OPACITY = "#6e6a63", 0.125      # very light grey
RANGE_INK = "#55524c"
TARGET_FILL, TARGET_OPACITY = "#2e9e44", 0.25     # faint green: the sight reaching its planned target(s)
SEEN_FILL, SEEN_OPACITY = "#f2c230", 0.6          # a faint glow around an enemy unit the line of sight gets to
SEEN_GLOW = 0.4                   # inches: how far the glow reaches around the unit
PLAN_INK = ZONE_INK["attacker"]
OVERLAY_DELAY = 30                # ms between overlay redraws while dragging
OVERLAYS = ("move", "advance", "charge", "objectives", "plan", "plan2", "planall", "sight", "hidden", "ground")
LABEL_SIZES = (10, 9, 8, 7, 6)    # points: the sizes a unit's name is tried at inside its base, the largest first
LABEL_MARGIN = 2                  # pixels kept clear between the name and the base's edge
ELLIPSIS = "…"
Z_OVERLAY, Z_LINK, Z_TOKEN, Z_CHOSEN = 5, 6, 10, 20       # what is drawn over what

# the space under the board for units that are not on it, in board inches (y goes up: it is below 0)
RESERVES = "Reserves and Transports"
RESERVE_GAP, RESERVE_H = 1.8, 9.0                 # between the board and it (its name is written there); its height
RESERVE_TOP, RESERVE_BOTTOM = -RESERVE_GAP, -(RESERVE_GAP + RESERVE_H)
DRAWN = (BOARD_W, BOARD_H + RESERVE_GAP + RESERVE_H)      # what a map draws: the board and that space
TO_RESERVES, TO_BOARD = "To Reserves...", "To the board..."     # the unit's menu
Box = tuple[float, float, float, float]           # x from, x to, y from, y to


def reserve_half(role: str) -> Box:
    """A side's half of the reserves space: the attacker's on the left, the defender's on the right."""
    return (0, BOARD_W / 2, RESERVE_BOTTOM, RESERVE_TOP) if role == "attacker" else (BOARD_W / 2, BOARD_W, RESERVE_BOTTOM,
                                                                                    RESERVE_TOP)


def keep_inside(x: float, y: float, w: float, h: float, box: Box) -> tuple[float, float]:
    """Keep a w x h footprint centred at (x, y) inside a box: it bumps into its edges (one too large for
    it sits in its middle)."""
    x0, x1, y0, y1 = box
    return (min(max(x, x0 + w / 2), x1 - w / 2) if w < x1 - x0 else (x0 + x1) / 2,
            min(max(y, y0 + h / 2), y1 - h / 2) if h < y1 - y0 else (y0 + y1) / 2)


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
    reserve: bool = False       # in the reserves space, not on the board
    bases: tuple[tuple[Base, int], ...] = ()      # (base, count) of its models: what its footprint is made from
    formation: str = SPACED     # how its models stand: its footprint's size and shape
    characters: tuple[bool, ...] = ()             # for each line of bases: a character's (the last models to go)
    lost: int = 0               # models it has lost
    destroyed: bool = False     # all of them: grey, until one is given back

    @property
    def strength(self) -> int:
        """The models it started with."""
        return sum(n for _, n in self.bases) if self.bases else self.footprint.models

    @property
    def models(self) -> int:
        """The models it has left."""
        return self.strength - self.lost

    def bases_left(self) -> list[tuple[Base, int]]:
        return remaining_bases(list(self.bases), list(self.characters), self.lost)
    board_spot: tuple[float, float] | None = None       # where it stood on the board, to go back there

    @property
    def box(self) -> tuple[float, float]:
        """Width and height the turned footprint takes on the board."""
        return extent(self.footprint.w, self.footprint.h, self.angle, self.footprint.shape)

    def outline(self, n: int = 36) -> list[tuple[float, float]]:
        """Its edge on the board, where it stands and as it is turned."""
        fp = self.footprint
        return outline(self.x, self.y, fp.w, fp.h, self.angle, n, fp.shape)

    def around(self, d: float) -> list[tuple[float, float]]:
        """The line `d` inches out from its edge."""
        fp = self.footprint
        return offset_outline(self.x, self.y, fp.w, fp.h, self.angle, d, shape=fp.shape)


class MenuEntry(NamedTuple):
    """An entry of a unit's menu: its name and what it does (None: a heading); ticked or not, for a
    choice among several (None: not such a choice); whether it can be chosen now."""
    name: str
    do: Callable[[], None] | None = None
    ticked: bool | None = None
    enabled: bool = True


def compact_label(name: str) -> str:
    """Board label: the unit without a trailing "Squad": "Bladeguard Veteran Squad + Sanguinary Priest" ->
    "Bladeguard Veteran + Sanguinary Priest"."""
    parts = [p.strip() for p in name.split(" + ")]
    return " + ".join([re.sub(r"\s+Squad\b", "", parts[0])] + parts[1:])


def line_widths(n: int, a: float, b: float, line_height: float, tube: bool = False) -> list[float] | None:
    """The widths of n lines of text stacked in the middle of an ellipse of half-axes a (along the lines)
    and b: each as wide as the ellipse is at the line's edge farthest from the centre, less a margin.
    In a tube of that length and width, its straight part is there at every height. None when n lines
    are too tall for it."""
    widths = []
    for i in range(n):
        edge = abs(i - (n - 1) / 2) * line_height + line_height / 2
        if edge >= b:
            return None
        chord = math.sqrt(1 - (edge / b) ** 2)
        widths.append(2 * ((a - b) + b * chord if tube and a > b else a * chord) - 2 * LABEL_MARGIN)
    return widths


def wrap(words: list[str], widths: list[float], width_of) -> tuple[list[str], list[str]]:
    """Fill lines of the given widths with words, in order: the lines, and the words left over."""
    lines, rest = [], list(words)
    for width in widths:
        line = ""
        while rest and width_of((line + " " + rest[0]).strip()) <= width:
            line = (line + " " + rest.pop(0)).strip()
        if not line:                                    # the next word is wider than this line
            break
        lines.append(line)
    return lines, rest


def fit_label(text: str, a: float, b: float, sizes=LABEL_SIZES, family: str = "",
              tube: bool = False) -> tuple[QFont, list[str], float] | None:
    """A name fitted in an ellipse (or a tube) of half-axes a and b pixels, written along a: the font, the lines and
    the height of a line. The largest size at which the whole name fits, on as few lines as that takes;
    at the smallest size, what fits of it, cut short with an ellipsis. None when not even a letter fits."""
    words = text.split()
    if not words:
        return None
    for size in sizes:
        font = QFont(family or font_family(), size)
        font.setBold(True)
        fm = QFontMetricsF(font)
        height = fm.height()
        best: tuple[int, list[str], list[str], list[float]] | None = None      # letters placed, lines, words left, widths
        n = 1
        while (widths := line_widths(n, a, b, height, tube)) is not None:
            lines, rest = wrap(words, widths, fm.horizontalAdvance)
            if not rest:
                return font, lines, height                  # all of it, at this size
            placed = sum(len(line) for line in lines)
            if best is None or placed > best[0]:
                best = (placed, lines, rest, widths)
            n += 1
        if size != sizes[-1] or best is None:
            continue
        _, lines, rest, widths = best                       # the smallest size: what fits, then an ellipsis
        at = max(len(lines) - 1, 0)
        last = fm.elidedText(" ".join(lines[at:] + rest), Qt.ElideRight, widths[at])
        if last.strip(ELLIPSIS).strip():
            return font, lines[:at] + [last], height
    return None


class TokenItem(QGraphicsPolygonItem):
    """A unit on the board: its footprint's outline around where it stands. Qt drags it; the map hears
    of every move, and keeps it on the board."""

    def __init__(self, board: "UnitMap", token: Token):
        super().__init__()
        self.board, self.token = board, token
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(token.label)                    # in full: its base may only have room for a part of it
        self.setPos(token.x, token.y)
        self._name: tuple[tuple, tuple | None] | None = None        # the name as fitted, and the base's size it was fitted to
        self._count: PixelText | None = None                # its models left over those it started with, when some are missing
        self.shape_it()

    def shape_it(self):
        """Its outline, for the angle it is turned at, and its look: selected or not, destroyed or not,
        with its models left over those it started with above it when some are missing."""
        t = self.token
        fp = t.footprint
        self.setPolygon(polygon(outline(0, 0, fp.w, fp.h, t.angle, shape=fp.shape)))
        fill, line = GONE if t.destroyed else TOKEN[t.role]
        chosen = self.board.selected == t.key
        pen = line_pen(SELECTED if chosen else line, 3 if chosen else 1.5, (3, 1.5) if t.footprint.estimated else None)
        self.setPen(pen)
        self.setBrush(see_through(fill, GONE_OPACITY if t.destroyed else TOKEN_OPACITY))
        self.setZValue(Z_CHOSEN if chosen else Z_TOKEN)
        if self._count is not None:
            self._count.setParentItem(None)
            if self._count.scene() is not None:
                self._count.scene().removeItem(self._count)
            self._count = None
        if t.lost:
            count = self._count = PixelText(f"{t.models}/{t.strength}", 0, t.box[1] / 2, line, bold=True, back=COUNT_BACK)
            count.offset = (0, -count.size[1] / 2 - 3)      # above the token, whatever the board's scale
            count.setAcceptedMouseButtons(Qt.NoButton)
            count.setParentItem(self)                       # it goes where the token goes

    def paint(self, painter: QPainter, option, widget=None):
        """The base, then the unit's name inside it, along it: in pixels, whatever the board's scale."""
        super().paint(painter, option, widget)
        t, k = self.token, self.board.view.pixels_per_inch
        if k <= 0:
            return
        a, b = t.footprint.w * k / 2, t.footprint.h * k / 2
        size = (round(a), round(b), t.footprint.shape)
        if self._name is None or self._name[0] != size:       # fitted again only when the base changes size or shape
            self._name = (size, fit_label(compact_label(t.label), a, b, tube=t.footprint.shape == TUBE))
        fitted = self._name[1]
        if not fitted:
            return
        font, lines, height = fitted
        painter.save()
        painter.scale(1 / k, -1 / k)                        # pixels, y down, around the unit's centre
        angle = t.angle % 180                               # along the base, and never upside down
        painter.rotate(angle - 180 if angle > 90 else angle)
        painter.setFont(font)
        painter.setPen(QColor(GONE[1] if t.destroyed else TOKEN[t.role][1]))
        for i, line in enumerate(lines):
            y = (i - (len(lines) - 1) / 2) * height
            painter.drawText(QRectF(-a, y - height / 2, 2 * a, height), Qt.AlignCenter, line)
        painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(*self.board.keep_in(self.token, value.x(), value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.token.x, self.token.y = self.x(), self.y()
            self.board.token_moved(self.token)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.board.pick(self.token.key)
        super().mousePressEvent(event)

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


class UnitView(BoardView):
    """The board's view, with what the right button does: `menu_asked` with the unit it was clicked on
    and where on the screen, `right_clicked` when it was clicked on none."""

    right_clicked = Signal()
    menu_asked = Signal(str, object)

    def token_at(self, pos) -> str | None:
        return next((item.token.key for item in self.items(pos) if isinstance(item, TokenItem)), None)

    def mousePressEvent(self, event):
        if event.button() != Qt.RightButton:
            super().mousePressEvent(event)
        elif self.token_at(event.position().toPoint()) is None:
            self.right_clicked.emit()

    def contextMenuEvent(self, event):
        key = self.token_at(event.pos())
        if key is not None:
            self.menu_asked.emit(key, event.globalPos())


class UnitMap(LayoutMap):
    view_class = UnitView

    def __init__(self):
        super().__init__()
        self.scene.setSceneRect(QRectF(0, RESERVE_BOTTOM, *DRAWN))     # the board, and the reserves under it
        self.tokens: dict[str, Token] = {}
        self.items: dict[str, TokenItem] = {}
        self.rng = random.Random()
        self.selected: str | None = None
        self.on_select = None                                       # callback(map, key or None)
        self.overlays: dict[str, bool] = {name: False for name in OVERLAYS}
        self.regions: list[dict] = []                               # objectives as terrain, per layout
        self.obstacles: Obstacles | None = None                    # what blocks line of sight, per layout
        self.plan_links: list[tuple[str, str, str]] = []           # (attacker key, target key, rank)
        self.seen: set[str] = set()                                 # the enemy units the selected one's line of sight gets to
        self._overlay_items: list[QGraphicsItem] = []
        self._link_items: list[QGraphicsItem] = []
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(lambda: self._redraw_overlays(draft=True))
        self._draft = False                                         # the overlays shown were drawn for a unit on the move
        self.view.scaled.connect(self._rescaled)
        self.view.right_clicked.connect(lambda: self._select(None))
        self.view.menu_asked.connect(self.token_menu)

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
        self.items, self._overlay_items, self._link_items = {}, [], []
        super().draw()
        if self.layout_data:
            # what is drawn for the selected unit (rings, line of sight...) stops at the board's edges:
            # it is drawn in this frame, which cuts what goes past it
            self._on_board = QGraphicsRectItem(0, 0, BOARD_W, BOARD_H)
            self._on_board.setPen(NO_PEN)
            self._on_board.setFlag(QGraphicsItem.ItemClipsChildrenToShape)
            self._on_board.setZValue(Z_OVERLAY)
            self._on_board.setAcceptedMouseButtons(Qt.NoButton)
            self.scene.addItem(self._on_board)
            self._draw_reserves()
            for t in self.tokens.values():
                self._add_item(t)
            self._draw_overlays()
            self._draw_plan_links()

    # ---------------------------------------------------------------- reserves
    def _draw_reserves(self):
        """The space under the board: its name between the two, a half per side, each in its side's colour."""
        scene = self.scene
        scene.addItem(PixelText(RESERVES.upper(), BOARD_W / 2, -RESERVE_GAP / 2, C["muted"], bold=True))
        for role in ("attacker", "defender"):
            x0, x1, y0, y1 = reserve_half(role)
            scene.addRect(x0, y0, x1 - x0, y1 - y0, NO_PEN, QColor(ZONE_FILL[role]))
            name = PixelText(self.role_names[role].upper(), x0, y1, ZONE_INK[role], bold=True)
            w, h = name.size
            name.offset = (w / 2 + 4, h / 2 + 3)                # in its half's top left corner
            scene.addItem(name)
        scene.addRect(0, RESERVE_BOTTOM, BOARD_W, RESERVE_H, line_pen(BOARD_INK))
        scene.addLine(BOARD_W / 2, RESERVE_BOTTOM, BOARD_W / 2, RESERVE_TOP, line_pen(BOARD_INK))

    def keep_in(self, t: Token, x: float, y: float) -> tuple[float, float]:
        """Where a unit asked at (x, y) may stand: on the board, or in its side's half of the reserves."""
        return keep_inside(x, y, *t.box, reserve_half(t.role)) if t.reserve else clamp(x, y, *t.box)

    def _reserve_spot(self, t: Token) -> tuple[float, float]:
        """A spot for a unit in its side's half of the reserves, clear of the units already there when there is room."""
        x0, x1, y0, y1 = reserve_half(t.role)
        w, h = t.box
        others = [(o.x, o.y, *o.box) for o in self.tokens.values() if o is not t and o.reserve and o.role == t.role]
        spot = keep_inside((x0 + x1) / 2, (y0 + y1) / 2, w, h, (x0, x1, y0, y1))
        for _ in range(300):
            spot = keep_inside(self.rng.uniform(x0, x1), self.rng.uniform(y0, y1), w, h, (x0, x1, y0, y1))
            if not any(overlaps((*spot, w, h), o, gap=0.3) for o in others):
                break
        return spot

    def to_reserves(self, key: str):
        """Take a unit off the board, into its side's half of the reserves."""
        t = self.tokens[key]
        if not t.reserve:
            t.board_spot, t.reserve = (t.x, t.y), True
            self._moved_to(t, self._reserve_spot(t))

    def to_board(self, key: str):
        """Put a unit of the reserves back on the board: where it stood, or in its side's deployment zone."""
        t = self.tokens[key]
        if t.reserve:
            t.reserve = False
            if t.board_spot is None:
                self._place(t)
            self._moved_to(t, clamp(*(t.board_spot or (t.x, t.y)), *t.box))

    def _moved_to(self, t: Token, spot: tuple[float, float]):
        t.x, t.y = spot
        if t.key in self.items:
            self.items[t.key].setPos(*spot)
        self._redraw_overlays()

    def menu_actions(self, key: str) -> list[MenuEntry]:
        """What a right click on a unit offers: where it goes, its turns, and, for a unit of several
        models, its formations, the one it is in ticked."""
        t = self.tokens[key]
        entries = [MenuEntry(TO_BOARD, lambda: self.to_board(key)) if t.reserve else
                   MenuEntry(TO_RESERVES, lambda: self.to_reserves(key)), MenuEntry(ROTATE)]
        entries += [MenuEntry(text, lambda degrees=degrees: self.rotate(key, degrees)) for degrees, text in ROTATIONS]
        if t.bases and t.models > 1:
            entries.append(MenuEntry(FORMATION))
            entries += [MenuEntry(text, lambda name=name: self.set_formation(key, name), t.formation == name)
                        for name, text in FORMATIONS.items()]
        if t.bases:
            entries += [MenuEntry(UNIT),
                        MenuEntry(LOSE_MODEL, lambda: self.lose_model(key), enabled=not t.destroyed),
                        MenuEntry(ADD_MODEL, lambda: self.add_model(key), enabled=t.lost > 0),
                        MenuEntry(DESTROYED, lambda: self.destroy(key), enabled=not t.destroyed)]
        return entries

    def lose_model(self, key: str):
        """Take a model off a unit: its last one, and the unit is destroyed."""
        t = self.tokens[key]
        if not t.bases or t.destroyed:
            return
        if t.models <= 1:
            return self.destroy(key)
        t.lost += 1
        self._resized(t)

    def add_model(self, key: str):
        """Give a unit a model back, up to those it started with; a destroyed unit is one no longer."""
        t = self.tokens[key]
        if not t.bases or t.lost <= 0:
            return
        t.lost -= 1
        t.destroyed = False
        self._resized(t)

    def destroy(self, key: str):
        """A unit has lost all its models: grey where it is drawn, and off to the reserves, where it keeps
        the size it had (it can be put back on the board)."""
        t = self.tokens[key]
        if not t.bases or t.destroyed:
            return
        t.destroyed, t.lost = True, t.strength
        if key in self.items:
            self.items[key].shape_it()
        if t.reserve:
            self._redraw_overlays()
        else:
            self.to_reserves(key)

    def _resized(self, t: Token):
        """A unit's models changed: its token is sized again for those it has, in its formation, where it is."""
        t.footprint = unit_footprint(t.bases_left(), t.formation)
        if t.key in self.items:
            self.items[t.key].shape_it()
            self.items[t.key].setPos(*self.keep_in(t, t.x, t.y))
        self._redraw_overlays()

    def set_formation(self, key: str, formation: str):
        """Have a unit's models stand another way: its token takes that formation's size and shape, where it is."""
        t = self.tokens[key]
        if formation not in FORMATIONS or not t.bases or t.models <= 1:
            return
        t.formation, t.footprint = formation, unit_footprint(t.bases_left(), formation)
        if key in self.items:
            self.items[key].shape_it()
            self.items[key].setPos(*self.keep_in(t, t.x, t.y))     # larger, it may have to move in from an edge
        self._redraw_overlays()

    def token_menu(self, key: str, at):
        """The menu of a unit, at a point of the screen; the unit is then the selected one."""
        self.pick(key)
        menu = QMenu(self)
        for name, do, ticked, enabled in self.menu_actions(key):
            if do is None:                              # a heading: a rule, then its name, which can't be chosen
                menu.addSeparator()
                heading = QWidgetAction(menu)
                text = label(name.upper(), "muted")
                text.setContentsMargins(8, 4, 18, 2)
                heading.setDefaultWidget(text)
                heading.setEnabled(False)
                menu.addAction(heading)
            else:
                action = menu.addAction(name)
                action.setEnabled(enabled)
                if ticked is not None:
                    action.setCheckable(True)
                    action.setChecked(ticked)
                action.triggered.connect(lambda _checked=False, do=do: do())
        menu.exec(at)

    # ---------------------------------------------------------------- units
    def add_token(self, key: str, role: str, label: str, footprint: Footprint, move: float = 0.0,
                  ranges: tuple[float, ...] = (), bases=(), characters=()):
        """bases: (base, count) of the unit's models, for it to take other formations than the one of
        `footprint` and to lose models; characters: for each of them, whether it is a character's."""
        t = Token(key, role, label, footprint, move, tuple(ranges), bases=tuple(bases), characters=tuple(characters))
        self._place(t)
        self.tokens[key] = t
        if self.layout_data:
            self._add_item(t)

    def remove_token(self, key: str):
        if self.tokens.pop(key, None):
            item = self.items.pop(key, None)
            if item is not None:
                self.scene.removeItem(item)
            if self.selected == key:
                self._select(None)

    def _place(self, t: Token):
        if t.reserve:                                 # it stays in reserve, on whatever board
            t.board_spot = None
            t.x, t.y = self._reserve_spot(t)
            return
        zones = (self.layout_data or {}).get("deployment_zones", {}).get(t.role, [])
        others = [(o.x, o.y, *o.box) for o in self.tokens.values() if o is not t and not o.reserve]
        t.x, t.y = random_spot(zones, *t.box, self.rng, avoid=others)

    def _add_item(self, t: Token):
        item = self.items[t.key] = TokenItem(self, t)
        self.scene.addItem(item)

    def _rescaled(self):
        """The board is shown at another size: the texts drawn over it are in pixels, and placed again."""
        self._draw_overlays()
        self._draw_plan_links()

    # ---------------------------------------------------------------- selection, moves
    def set_selected(self, key: str | None):
        """Show `key` as selected (None: nothing), without telling anyone."""
        if key != self.selected:
            was, self.selected = self.selected, key if key in self.tokens else None
            for k in (was, self.selected):
                if k in self.items:
                    self.items[k].shape_it()
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

    def rotate(self, key: str, degrees: float):
        """Turn a unit by so many degrees clockwise (counter-clockwise if negative); turning can push it
        past an edge: it is kept where it may stand."""
        t = self.tokens[key]
        t.angle = (t.angle + degrees) % 360
        item = self.items[key]
        item.shape_it()
        item.setPos(*self.keep_in(t, t.x, t.y))
        self._redraw_overlays()

    def move_token(self, key: str, x: float, y: float):
        """Put a unit somewhere on the board, as a drag would (it stops at the edges)."""
        self.items[key].setPos(x, y)
        self.token_released()

    def token_moved(self, t: Token):
        """A unit is being dragged: the overlays follow at most every OVERLAY_DELAY ms, so that mouse events
        don't queue up behind line of sight computations."""
        if not self._overlay_timer.isActive():
            self._overlay_timer.start(OVERLAY_DELAY)

    def token_released(self):
        """End of a drag: draw the overlays for where the unit ended up, now and in full."""
        if self._overlay_timer.isActive() or self._draft:
            self._redraw_overlays()

    def _redraw_overlays(self, draft: bool = False):
        """draft: the unit is still on the move, and this will be drawn again in a moment."""
        self._overlay_timer.stop()
        self._draw_overlays(draft)
        self._draw_plan_links()

    def describe(self, t: Token | None):
        """Under the title: the unit the pointer is on (None: the layout's own line)."""
        if t is None:
            return self._show_sub()
        fp = t.footprint
        size = f'{fp.w:.1f}"' if abs(fp.w - fp.h) < 1e-6 else f'{fp.w:.1f}" x {fp.h:.1f}"'
        self._show_sub(f"{t.label}  ·  {fp.description}  ·  {size}"
                       + (f"  ·  {FORMATIONS[t.formation].lower()}" if t.formation != SPACED else "")
                       + (f"  ·  turned {t.angle:.0f}°" if t.angle else "")
                       + ("  ·  base size estimated" if fp.estimated else ""))

    # ---------------------------------------------------------------- what is drawn over the board
    def _clear(self, items: list):
        for item in items:
            self.scene.removeItem(item)
        items.clear()

    def _add(self, items: list, item: QGraphicsItem, z: float) -> QGraphicsItem:
        item.setZValue(z)
        item.setAcceptedMouseButtons(Qt.NoButton)
        if items is self._overlay_items:                        # the selected unit's: kept to the board
            item.setParentItem(self._on_board)
        elif item.scene() is None:
            self.scene.addItem(item)
        items.append(item)
        return item

    def _halo_text(self, items: list, x: float, y: float, text: str, ink: str, z: float, above: bool = False):
        """A small text on a white box, kept on what the map draws; `above`: it sits on the point, not around it."""
        tag = PixelText(text, 0, 0, ink, bold=True, back="white")
        k = self.view.pixels_per_inch or 1.0
        w, h = (d / k for d in tag.size)
        if above:
            y += h / 2
        tag.setPos(min(max(x, w / 2 + 2 / k), BOARD_W - w / 2 - 2 / k),
                   min(max(y, RESERVE_BOTTOM + h / 2 + 2 / k), BOARD_H - h / 2 - 2 / k))
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
            outline_a, outline_d = a.outline(), d.outline()
            dist, p, q = distance_to_region(outline_a, [outline_d])
            if dist <= 0:                                   # touching: centre to centre
                p, q = (a.x, a.y), (d.x, d.y)
            first = rank == "primary"
            self._add(items, self.scene.addLine(*p, *q, line_pen(PLAN_INK, 2.5 if first else 1.5, None if first else (4, 2.7))),
                      Z_LINK)
            self._add(items, ArrowHead(q, p, PLAN_INK), Z_LINK)
            self._halo_text(items, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2, "1st" if first else "2nd", PLAN_INK, Z_LINK)

    def _draw_overlays(self, draft: bool = False):
        """Movement rings, objective distances and line of sight of the selected unit, under the tokens.
        draft: the line of sight with fewer rays, for a unit being dragged."""
        items = self._overlay_items
        self._clear(items)
        self._draft = draft
        self.seen = set()
        t = self.tokens.get(self.selected or "")
        if not t or not self.layout_data or t.reserve or t.destroyed:       # off the board, or gone: nothing to measure or to see from there
            return
        if self.overlays["sight"] and t.ranges and self.obstacles:
            edge = t.outline(72)
            hidden = None
            if self.overlays["hidden"]:
                hidden = GO_TO_GROUND_RANGE if self.overlays["ground"] else HIDDEN_RANGE
            few = dict(origins=DRAFT_ORIGINS, directions=DRAFT_DIRECTIONS) if draft else {}
            rays = cast(edge, max(t.ranges), self.obstacles, hidden=hidden, **few)
            self._shade(items, fans(rays), SIGHT_FILL, SIGHT_OPACITY, Z_OVERLAY)       # union: what it sees
            for o in self.tokens.values():                      # the enemy units in it: a glow around each
                if o.role != t.role and not o.reserve and not o.destroyed and sees(rays, o.outline()):
                    self.seen.add(o.key)
                    ring = QPainterPath()                       # around the unit, not under it: its own colour stays
                    ring.addPolygon(polygon(o.around(SEEN_GLOW)))
                    ring.closeSubpath()
                    ring.addPolygon(polygon(o.outline()))
                    ring.closeSubpath()
                    glow = QGraphicsPathItem(ring)
                    glow.setPen(NO_PEN)
                    glow.setBrush(see_through(SEEN_FILL, SEEN_OPACITY))
                    self._add(items, glow, Z_OVERLAY + 0.6)
            if rays is not None and self.overlays["plan"]:      # what of it reaches its targets: green
                reaching = []
                for a_key, d_key, rank in self.plan_links:
                    d = self.tokens.get(d_key)
                    if a_key != t.key or not d or d.reserve or (rank == "secondary" and not self.overlays["plan2"]):
                        continue
                    for fan in reaching_fans(rays, d.outline()):
                        if len(fan) > 2:
                            reaching.append(fan)
                        else:                                 # a lone ray
                            self._add(items, self.scene.addLine(*fan[0], *fan[1], line_pen(TARGET_FILL)), Z_OVERLAY)
                self._shade(items, reaching, TARGET_FILL, TARGET_OPACITY, Z_OVERLAY + 0.1)
            # each circle's distance written where it faces the board centre: on the board, spread out
            cx, cy = BOARD_W / 2 - t.x, BOARD_H / 2 - t.y
            norm = (cx * cx + cy * cy) ** 0.5 or 1.0
            for r in t.ranges:
                pts = t.around(r)
                self._add(items, self.scene.addPolygon(polygon(pts), line_pen(RANGE_INK)), Z_OVERLAY + 0.2)
                at = max(pts, key=lambda p: ((p[0] - t.x) * cx + (p[1] - t.y) * cy) / norm)
                self._halo_text(items, *at, f'{r:g}"', RANGE_INK, Z_OVERLAY + 0.2)
        for (name, d), ink in zip(rings(t.move, self.overlays["move"], self.overlays["advance"],
                                        self.overlays["charge"]), RING_INK):
            pts = t.around(d)
            self._add(items, self.scene.addPolygon(polygon(pts), line_pen(ink, 2, (3, 1.5))), Z_OVERLAY + 0.3)
            top = max(pts, key=lambda p: p[1])                     # write it at the ring's top
            self._halo_text(items, *top, name, ink, Z_OVERLAY + 0.3, above=True)
        if self.overlays["objectives"]:
            edge = t.outline()
            for r in self.regions:
                d, near, far = distance_to_region(edge, r["polygons"])
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
