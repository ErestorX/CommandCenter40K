"""A battlefield layout drawn as a scene: deployment zones, terrain, objectives, measurements, the line
between the two territories. The scene is in board inches, y up, and drawn once per layout: the view
scales it to the space it gets, keeping the board's 60" x 44" proportions.

Texts that must stay readable whatever the scale (edge names, measurements) are in pixels (PixelText);
an objective's number grows with its marker.

show_territory: the line between the two players' territories (command_center.deploy.territory).
role_names: what the two sides are called on the map ("attacker" and "defender" unless changed)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsScene, QGraphicsView, QSizePolicy, QStackedWidget, QVBoxLayout)

from command_center.deploy.placement import BOARD_H, BOARD_W
from command_center.deploy.territory import territory_line
from command_center.ui.theme import C, font_family
from command_center.ui.widgets import Panel, label

ZONE_FILL = {"attacker": "#f1d3d3", "defender": "#d3dff0"}
ZONE_INK = {"attacker": "#a3262a", "defender": "#1f5288"}
BOARD_FILL, BOARD_INK = "#f7f5ef", "#1d1c1a"       # a light board on the dark window: its own inks
AREA_FILL, AREA_LINE = "#ddd6c8", "#9b9384"
FEATURE_FILL = {"DENSE": "#5f584d", "LIGHT": "#a8a092"}
OBJ_FILL = {"central": "#1d1c1a", "expansion": "#3c7d45"}
OBJ_RADIUS = 0.9                                    # inches
MEASURE = "#6e6a63"
TERRITORY_INK, TERRITORY_DASH = "#1d1c1a", (5, 2.5)     # dashes in widths of the line
NO_PEN = QPen(Qt.NoPen)


def polygon(points) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def line_pen(color: str, width: float = 1.0, dash=None) -> QPen:
    """A line as wide in pixels whatever the board's scale."""
    pen = QPen(QColor(color), width)
    pen.setCosmetic(True)
    if dash:
        pen.setDashPattern(list(dash))
    return pen


def objective_fill(o: dict) -> str:
    if o.get("type") == "home":
        return ZONE_INK.get(o.get("owner") or "", "#1d1c1a")
    return OBJ_FILL.get(o.get("type", ""), "#1d1c1a")


class PixelText(QGraphicsItem):
    """A text centred on a point of the board, its size in pixels whatever the board's scale. `offset`
    moves it by so many pixels, `angle` turns it (degrees clockwise), `back` paints a box behind it
    (a colour, or one with its opacity: "#rrggbb", or QColor). `width`: it wraps at that many pixels."""

    def __init__(self, text: str, x: float, y: float, color: str, size: int = 8, bold: bool = False,
                 offset: tuple[float, float] = (0, 0), angle: float = 0, back=None, width: float = 0,
                 align: Qt.AlignmentFlag = Qt.AlignHCenter):
        super().__init__()
        self.text, self.color, self.offset, self.angle, self.back = text, QColor(color), offset, angle, back
        self.font = QFont(font_family(), size)
        self.font.setBold(bold)
        self.flags_ = int(align | Qt.AlignVCenter | Qt.TextWordWrap)
        self.box = QFontMetricsF(self.font).boundingRect(QRectF(0, 0, width or 10_000, 10_000), self.flags_, text
                                                         ).adjusted(-2, 0, 2, 0)
        self.box.moveCenter(QPointF(0, 0))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setPos(x, y)

    def boundingRect(self) -> QRectF:
        reach = max(self.box.width(), self.box.height()) / 2 + 2        # room to be turned in
        return QRectF(-reach, -reach, 2 * reach, 2 * reach).translated(*self.offset)

    def paint(self, painter: QPainter, option, widget=None):
        painter.translate(*self.offset)
        painter.rotate(self.angle)
        if self.back:
            painter.fillRect(self.box, QColor(self.back))
        painter.setFont(self.font)
        painter.setPen(self.color)
        painter.drawText(self.box.adjusted(2, 0, -2, 0), self.flags_, self.text)

    @property
    def size(self) -> tuple[float, float]:
        """Its width and height, in pixels."""
        return self.box.width(), self.box.height()


class BoardView(QGraphicsView):
    """Shows the whole scene (the board, unless more is drawn with it), as large as its room allows.
    `scaled` is emitted when that size changed."""

    scaled = Signal()

    def __init__(self):
        board = QGraphicsScene(0, 0, BOARD_W, BOARD_H)
        super().__init__(board)
        self.board = board                                          # kept: a view does not own its scene
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor(C["panel"]))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)       # whatever room it is given
        self.scale(1, -1)                                           # y up, as the layouts are written

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self.scaled.emit()

    @property
    def pixels_per_inch(self) -> float:
        return self.transform().m11()


class LayoutMap(Panel):
    view_class = BoardView          # what shows the scene: a map with more to it has its own

    def __init__(self):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(0)
        self.title = label("", "h2")
        col.addWidget(self.title)
        self.sub = label("", "muted")
        col.addWidget(self.sub)
        col.addSpacing(4)
        self.view = self.view_class()
        self.scene = self.view.board
        self.note = label("", "muted", wrap=True, align=Qt.AlignCenter)        # shown when there is no layout
        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.note)
        col.addWidget(self.stack, 1)
        self.layout_data: dict | None = None
        self.message = ""
        self.show_measurements = False
        self.show_territory = False                                 # the line between the two territories
        self.role_names = {"attacker": "attacker", "defender": "defender"}      # as written on the map

    def set_layout(self, layout: dict | None, message: str = "", show_measurements: bool | None = None):
        self.layout_data, self.message = layout, message
        if show_measurements is not None:
            self.show_measurements = show_measurements
        self.title.setText(f"Layout {layout.get('variant', '')}" if layout else "")
        self._show_sub()
        self.draw()

    def _show_sub(self, text: str = ""):
        lay = self.layout_data
        default = (f"{lay['id']}  ·  {self.role_names['attacker']} deploys {lay.get('attacker_edge', '?')}, "
                   f"{self.role_names['defender']} {lay.get('defender_edge', '?')}") if lay else ""
        self.sub.setText(text or default)

    # ---------------------------------------------------------------- drawing
    def draw(self):
        scene, lay = self.scene, self.layout_data
        scene.clear()
        self.note.setText(self.message)
        self.stack.setCurrentWidget(self.view if lay else self.note)
        if not lay:
            return
        scene.addRect(0, 0, BOARD_W, BOARD_H, NO_PEN, QColor(BOARD_FILL))
        for side in ("attacker", "defender"):
            for poly in lay.get("deployment_zones", {}).get(side, []):
                if len(poly) >= 3:
                    scene.addPolygon(polygon(poly), NO_PEN, QColor(ZONE_FILL[side]))
        areas = lay.get("terrain", [])
        for area in areas:                              # every footprint first, so none hides a feature
            for fp in area.get("footprints", []):
                if len(fp.get("points", [])) >= 3:
                    scene.addPolygon(polygon(fp["points"]), line_pen(AREA_LINE), QColor(AREA_FILL))
        for area in areas:
            for f in area.get("features", []):
                if len(f.get("points", [])) >= 3:
                    scene.addPolygon(polygon(f["points"]), NO_PEN, QColor(FEATURE_FILL.get(f.get("category"), "#8a857a")))
        if self.show_territory:
            line = territory_line(lay)
            if line:
                scene.addLine(*line[0], *line[1], line_pen(TERRITORY_INK, 2, TERRITORY_DASH))
        if self.show_measurements:
            m = lay.get("measurements", {})
            for x1, y1, x2, y2 in m.get("lines", []):
                scene.addLine(x1, y1, x2, y2, line_pen(MEASURE, 1, (3, 2)))
            for lb in m.get("labels", []):
                scene.addItem(PixelText(lb["text"], lb["x"], lb["y"], BOARD_INK, back=BOARD_FILL))
        for o in lay.get("objectives", []):
            x, y = o["position"]
            scene.addEllipse(x - OBJ_RADIUS, y - OBJ_RADIUS, 2 * OBJ_RADIUS, 2 * OBJ_RADIUS,
                             line_pen("white", 2), QColor(objective_fill(o)))
            scene.addPath(self._number(str(o["number"]), x, y), NO_PEN, QBrush(QColor("white")))
        scene.addRect(0, 0, BOARD_W, BOARD_H, line_pen(BOARD_INK))
        self._edge_labels()

    @staticmethod
    def _number(text: str, x: float, y: float) -> QPainterPath:
        """An objective's number as a shape in inches, centred on its marker: it grows with it."""
        font = QFont(font_family(), 100)
        font.setBold(True)
        path = QPainterPath()
        path.addText(0, 0, font, text)
        box = path.boundingRect()
        k = OBJ_RADIUS / QFontMetricsF(font).capHeight()            # a capital as tall as the marker's radius
        to_board = QTransform().translate(x, y).scale(k, -k).translate(-box.center().x(), -box.center().y())
        return to_board.map(path)

    def _edge_labels(self):
        """ATTACKER / DEFENDER written inside the board along each side's deployment edge."""
        spots = {"left": (0, BOARD_H / 2, (10, 0), -90), "right": (BOARD_W, BOARD_H / 2, (-10, 0), 90),
                 "bottom": (BOARD_W / 2, 0, (0, -9), 0), "top": (BOARD_W / 2, BOARD_H, (0, 9), 0)}
        for side in ("attacker", "defender"):
            edge = self.layout_data.get(f"{side}_edge", "")
            if edge in spots:
                x, y, offset, angle = spots[edge]
                self.scene.addItem(PixelText(self.role_names[side].upper(), x, y, ZONE_INK[side], bold=True,
                                             offset=offset, angle=angle))
