"""Painted charts: a heatmap, a horizontal bar chart and a stem chart (the last two with whiskers), all
with hover tooltips and click callbacks. Colours follow one rule each: magnitude = one blue ramp, identity =
fixed categorical slots, text = ink colours (never the series colour).

Each chart is a scrolling area around a surface it paints: the surface is as large as the chart needs,
and the area scrolls it when it doesn't fit."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QToolTip, QWidget

from command_center.ui.theme import C, font_family
from command_center.ui.palette import RAMP, SLOTS, ramp_color  # noqa: F401

INK = C["ink"]
INK_2 = C["muted"]
INK_3 = C["dim"]
GRID = C["grid"]
SURFACE = C["panel"]
MISSING = C["field"]
WRAP = int(Qt.TextWordWrap)


class _Surface(QWidget):
    """What a chart is painted on, and where its mouse events come from."""

    def __init__(self, chart: "Chart"):
        super().__init__()
        self.chart = chart
        self.setMouseTracking(True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        self.chart.paint(p)

    def mouseMoveEvent(self, event):
        self.chart.moved(event.position(), event.globalPosition().toPoint())

    def mousePressEvent(self, event):
        self.chart.pressed(event.position(), event.button())

    def leaveEvent(self, event):
        self.chart.left()


class Chart(QScrollArea):
    """A chart's scrolling area. A chart says how large its surface must be (extent), paints it (paint),
    and answers the mouse (moved, pressed, left)."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)                   # the surface: the area's size, or its own if larger
        self.surface = _Surface(self)
        self.setWidget(self.surface)
        self.fmt: Callable[[float], str] = lambda v: f"{v:.1f}"

    def face(self, size: int = 9, bold: bool = False) -> QFont:
        f = QFont(font_family(), size)
        f.setBold(bold)
        return f

    @property
    def room(self) -> tuple[int, int]:
        """The width and height the area shows at once."""
        return self.viewport().width(), self.viewport().height()

    def redraw(self):
        """After the data or the room changed: the surface's size, and its picture."""
        w, h = self.extent()
        self.surface.setMinimumSize(int(w), int(h))
        self.surface.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.redraw()

    def tip(self, at, lines: list[str]):
        if lines:
            QToolTip.showText(at, "\n".join(lines), self.surface)
        else:
            QToolTip.hideText()

    @staticmethod
    def text(p: QPainter, rect: QRectF, flags, text: str, ink: str, font: QFont):
        p.setFont(font)
        p.setPen(QColor(ink))
        p.drawText(rect, int(flags), text)

    def legend_row(self, p: QPainter, x: float, legend: list[tuple[str, str]]):
        """Identity is never colour alone (every item also has its label): the key to the colours, on one line."""
        font = self.face(9)
        for name, color in legend:
            p.fillRect(QRectF(x, 8, 10, 10), QColor(color))
            w = QFontMetricsF(font).horizontalAdvance(name)
            self.text(p, QRectF(x + 14, 4, w + 2, 18), Qt.AlignLeft | Qt.AlignVCenter, name, INK_2, font)
            x += 14 + w + 16

    # for a chart to define
    def extent(self) -> tuple[float, float]:
        return 10, 10

    def paint(self, p: QPainter):
        pass

    def moved(self, pos: QPointF, screen_pos):
        pass

    def pressed(self, pos: QPointF, button):
        pass

    def left(self):
        QToolTip.hideText()


# =============================================================================
# heatmap
# =============================================================================
class Heatmap(Chart):
    """rows x cols grid of values on the blue ramp. Scrolls when it doesn't fit."""

    HEAD, CELL = 64, 30                # height of the column headings, of a row

    def __init__(self, on_click: Callable[[int, int], None] | None = None,
                 on_right_click: Callable[[int, int], None] | None = None):
        super().__init__()
        self.on_click, self.on_right_click = on_click, on_right_click
        self.rows: list[str] = []
        self.cols: list[str] = []
        self.values: list[list[float | None]] = []
        self.tips: list[list[list[str]]] = []
        self.caption = ""
        self.selected: tuple[int, int] | None = None

    def set_data(self, rows, cols, values, tips, fmt=None, caption: str = ""):
        self.rows, self.cols, self.values, self.tips = rows, cols, values, tips
        if fmt:
            self.fmt = fmt
        self.caption = caption
        if self.selected and (self.selected[0] >= len(rows) or self.selected[1] >= len(cols)):
            self.selected = None
        self.redraw()

    def _geom(self) -> tuple[float, float]:
        """The width of the row headings, and of a column."""
        W = max(self.room[0], 300)
        row_w = min(260, max(140, int(W * 0.24)))
        return row_w, max(64, min(130, (W - row_w - 20) // max(1, len(self.cols))))

    def extent(self):
        if not self.rows or not self.cols:
            return 10, 10
        row_w, cw = self._geom()
        return row_w + len(self.cols) * cw + 20, self.HEAD + len(self.rows) * self.CELL + 18 + 40

    def paint(self, p: QPainter):
        if not self.rows or not self.cols:
            self.text(p, QRectF(20, 20, 600, 20), Qt.AlignLeft, "Nothing to show: all tests are filtered out or hidden.",
                      INK_2, self.face(10))
            return
        (row_w, cw), ch, small, bold = self._geom(), self.CELL, self.face(9), self.face(9, True)
        vals = [v for r in self.values for v in r if v is not None]
        vmin, vmax = (min(vals), max(vals)) if vals else (0.0, 1.0)
        span = (vmax - vmin) or 1.0
        for j, c in enumerate(self.cols):
            self.text(p, QRectF(row_w + j * cw + 3, 0, cw - 6, self.HEAD - 6), Qt.AlignHCenter | Qt.AlignBottom | WRAP,
                      c, INK, small)
        for i, r in enumerate(self.rows):
            y = self.HEAD + i * ch
            self.text(p, QRectF(4, y, row_w - 12, ch), Qt.AlignRight | Qt.AlignVCenter | WRAP, r, INK, small)
            for j in range(len(self.cols)):
                v = self.values[i][j]
                if v is None:
                    fill, ink, txt = MISSING, INK_3, "–"
                else:
                    fill, ink = ramp_color((v - vmin) / span)
                    txt = self.fmt(v)
                cell = QRectF(row_w + j * cw + 1, y + 1, cw - 2, ch - 2)
                p.fillRect(cell, QColor(fill))
                self.text(p, cell, Qt.AlignCenter, txt, ink, bold)
        if self.selected:
            i, j = self.selected
            p.setPen(QPen(QColor(INK), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(row_w + j * cw, self.HEAD + i * ch, cw, ch))
        # legend: the ramp with its end values
        ly = self.HEAD + len(self.rows) * ch + 18
        lw = min(260, len(self.cols) * cw)
        seg = lw / len(RAMP)
        for k, col in enumerate(RAMP):
            p.fillRect(QRectF(row_w + k * seg, ly, seg + 0.5, 10), QColor(col))
        tiny = self.face(8)
        self.text(p, QRectF(row_w, ly + 13, lw, 14), Qt.AlignLeft | Qt.AlignTop, self.fmt(vmin), INK_2, tiny)
        self.text(p, QRectF(row_w, ly + 13, lw, 14), Qt.AlignRight | Qt.AlignTop, self.fmt(vmax), INK_2, tiny)
        if self.caption:
            self.text(p, QRectF(row_w + lw + 12, ly - 3, 600, 16), Qt.AlignLeft | Qt.AlignVCenter, self.caption, INK_2, tiny)

    def cell_at(self, pos: QPointF) -> tuple[int, int] | None:
        if not self.rows or not self.cols:
            return None
        row_w, cw = self._geom()
        j, i = int((pos.x() - row_w) // cw), int((pos.y() - self.HEAD) // self.CELL)
        if pos.x() < row_w or pos.y() < self.HEAD or not (0 <= i < len(self.rows)) or not (0 <= j < len(self.cols)):
            return None
        return i, j

    def cell_centre(self, i: int, j: int) -> QPointF:
        row_w, cw = self._geom()
        return QPointF(row_w + (j + 0.5) * cw, self.HEAD + (i + 0.5) * self.CELL)

    def moved(self, pos, screen_pos):
        c = self.cell_at(pos)
        self.tip(screen_pos, self.tips[c[0]][c[1]] if c else [])

    def pressed(self, pos, button):
        c = self.cell_at(pos)
        cb = self.on_click if button == Qt.LeftButton else self.on_right_click if button == Qt.RightButton else None
        if c and cb:
            if cb is self.on_click:
                self.selected = c
            cb(*c)
            self.redraw()


# =============================================================================
# horizontal bars with whiskers
# =============================================================================
@dataclass
class BarItem:
    key: object
    label: str
    value: float
    lo: float | None = None           # whisker (e.g. 5th percentile)
    hi: float | None = None           # whisker (e.g. 95th percentile)
    color: str = SLOTS[0]
    sublabel: str = ""
    tip: list[str] = field(default_factory=list)
    segments: list[tuple[float, str]] = field(default_factory=list)   # stacked (share, colour); shares sum to 1


class _Items(Chart):
    """What the bar chart and the stem chart share: their items, the one under the pointer, a click on one."""

    def __init__(self, on_click: Callable[[object], None] | None = None):
        super().__init__()
        self.on_click = on_click
        self.items: list[BarItem] = []
        self.legend: list[tuple[str, str]] = []
        self.empty_text = "Nothing to show."
        self._hovered = None

    def set_data(self, items: list[BarItem], fmt=None, legend=None, empty_text: str = ""):
        self.items = items
        if fmt:
            self.fmt = fmt
        self.legend = legend or []
        if empty_text:
            self.empty_text = empty_text
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.redraw()

    @property
    def top_value(self) -> float:
        return max(max(it.value, it.hi if it.hi is not None else it.value) for it in self.items) or 1.0

    def paint_empty(self, p: QPainter):
        self.text(p, QRectF(20, 20, 800, 20), Qt.AlignLeft, self.empty_text, INK_2, self.face(10))

    def item_at(self, pos: QPointF) -> BarItem | None:
        return None

    def _hover(self, key):
        if key is not self._hovered:
            self._hovered = key
            self.surface.update()

    def moved(self, pos, screen_pos):
        it = self.item_at(pos)
        self._hover(it.key if it else None)
        self.tip(screen_pos, it.tip if it else [])

    def pressed(self, pos, button):
        it = self.item_at(pos)
        if it and self.on_click and button == Qt.LeftButton:
            QToolTip.hideText()
            self.on_click(it.key)

    def left(self):
        super().left()
        self._hover(None)


class BarChart(_Items):
    """Sorted horizontal bars. Click a bar -> on_click(key). Scrolls vertically."""

    ROW = 30

    def __init__(self, on_click: Callable[[object], None] | None = None):
        super().__init__(on_click)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    @property
    def _top(self) -> int:
        return 26 if self.legend else 8

    def extent(self):
        return 10, (self._top + len(self.items) * self.ROW + 10) if self.items else 10

    def paint(self, p: QPainter):
        if not self.items:
            self.paint_empty(p)
            return
        W = max(self.room[0], 300)
        label_w = min(330, max(160, int(W * 0.38)))
        value_w = 56
        x0, x1 = label_w + 8, W - value_w - 8
        top, bottom = self._top, self._top + len(self.items) * self.ROW
        scale = (x1 - x0) / self.top_value
        self.legend_row(p, x0, self.legend)
        p.setPen(QColor(GRID))                                  # recessive vertical grid
        for k in range(1, 5):
            gx = x0 + (x1 - x0) * k / 4
            p.drawLine(QPointF(gx, top), QPointF(gx, bottom))
        small, tiny, bold = self.face(9), self.face(8), self.face(9, True)
        for n, it in enumerate(self.items):
            y = top + n * self.ROW
            if self._hovered is not None and self._hovered is it.key:
                p.fillRect(QRectF(0, y, W, self.ROW), QColor(GRID))
            if it.sublabel:
                self.text(p, QRectF(0, y + 1, label_w, 16), Qt.AlignRight | Qt.AlignVCenter, it.label, INK, small)
                self.text(p, QRectF(0, y + 15, label_w, 14), Qt.AlignRight | Qt.AlignVCenter, it.sublabel, INK_2, tiny)
            else:
                self.text(p, QRectF(0, y, label_w, self.ROW), Qt.AlignRight | Qt.AlignVCenter, it.label, INK, small)
            bx = x0 + max(1.0, it.value * scale)
            sx = x0
            for share, color in it.segments or [(1.0, it.color)]:
                ex = sx + (bx - x0) * share
                p.fillRect(QRectF(sx, y + 8, ex - sx, self.ROW - 16), QColor(color))
                sx = ex
            if it.lo is not None and it.hi is not None and it.hi > it.lo:
                lo, hi, cy = x0 + it.lo * scale, x0 + it.hi * scale, y + self.ROW / 2
                p.setPen(QColor(INK_2))
                p.drawLine(QPointF(lo, cy), QPointF(hi, cy))
                p.drawLine(QPointF(lo, cy - 4), QPointF(lo, cy + 4))
                p.drawLine(QPointF(hi, cy - 4), QPointF(hi, cy + 4))
            self.text(p, QRectF(x1, y, W - 8 - x1, self.ROW), Qt.AlignRight | Qt.AlignVCenter, self.fmt(it.value), INK, bold)
        p.setPen(QColor(INK_3))
        p.drawLine(QPointF(x0, top), QPointF(x0, bottom))

    def item_at(self, pos):
        n = int((pos.y() - self._top) // self.ROW)
        return self.items[n] if pos.y() >= self._top and 0 <= n < len(self.items) else None


# =============================================================================
# stems lined up along a baseline, with whiskers
# =============================================================================
class StemChart(_Items):
    """A stem per item (BarItem), side by side on a horizontal baseline, in the order given: a line as
    tall as the value with a dot at its tip, the value above, the item's label and sublabel under the
    baseline. Stacked segments colour the stem from the baseline up. Click a stem -> on_click(key).
    Scrolls horizontally when the stems don't fit."""

    COLUMN = 104          # the least width of an item's column
    TICKS = 4
    AXIS = 52             # the value scale, left of the first stem

    def __init__(self, on_click: Callable[[object], None] | None = None):
        super().__init__(on_click)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def wheelEvent(self, event):                                # the wheel moves along the stems
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y())

    def _geom(self) -> tuple[float, float, float, float, float]:
        """A column's width; the height of the labels, of what is under the baseline; the top of the
        tallest stem's room; the baseline."""
        W, H = max(self.room[0], 300), max(self.room[1], 240)
        cw = max(self.COLUMN, min(240, (W - self.AXIS - 12) / len(self.items)))

        def height(text: str, font: QFont) -> float:
            return QFontMetricsF(font).boundingRect(QRectF(0, 0, cw - 10, 10_000), int(Qt.AlignHCenter) | WRAP, text).height()
        # the labels first: the room they take under the baseline decides the height left for the stems
        label_h = max(height(it.label, self.face(9)) for it in self.items)
        below = label_h + max((height(it.sublabel, self.face(8)) if it.sublabel else 0) for it in self.items) + 16
        top = (30 if self.legend else 10) + 22                  # room for the value above the tallest stem
        return cw, label_h, below, top, max(top + 80, H - below - 4)

    def extent(self):
        if not self.items:
            return 10, 10
        cw, _, below, _, base = self._geom()
        return self.AXIS + len(self.items) * cw + 12, base + below + 4

    def paint(self, p: QPainter):
        if not self.items:
            self.paint_empty(p)
            return
        cw, label_h, below, top, base = self._geom()
        axis, vmax = self.AXIS, self.top_value
        scale = (base - top) / vmax
        right = axis + len(self.items) * cw
        small, tiny, bold = self.face(9), self.face(8), self.face(9, True)
        for n, it in enumerate(self.items):                     # under everything: the column the pointer is on
            if self._hovered is not None and self._hovered is it.key:
                p.fillRect(QRectF(axis + n * cw, top - 22, cw, base + below - top + 22), QColor(GRID))
        self.legend_row(p, axis, self.legend)
        for k in range(self.TICKS + 1):                         # a recessive grid, with the scale's values
            gy = base - (base - top) * k / self.TICKS
            if k:
                p.setPen(QColor(GRID))
                p.drawLine(QPointF(axis, gy), QPointF(right, gy))
            self.text(p, QRectF(0, gy - 8, axis - 6, 16), Qt.AlignRight | Qt.AlignVCenter, self.fmt(vmax * k / self.TICKS),
                      INK_2, tiny)
        for n, it in enumerate(self.items):
            x0 = axis + n * cw
            x = x0 + cw / 2
            tip_y = base - max(1.0, it.value * scale)
            head = tip_y
            if it.lo is not None and it.hi is not None and it.hi > it.lo:     # the whisker, behind the stem
                lo, hi = base - it.lo * scale, base - it.hi * scale
                p.setPen(QColor(INK_2))
                p.drawLine(QPointF(x, lo), QPointF(x, hi))
                p.drawLine(QPointF(x - 5, lo), QPointF(x + 5, lo))
                p.drawLine(QPointF(x - 5, hi), QPointF(x + 5, hi))
                head = min(head, hi)
            color, sy = it.color, base
            for share, color in it.segments or [(1.0, it.color)]:
                ey = sy - (base - tip_y) * share
                p.setPen(QPen(QColor(color), 3, Qt.SolidLine, Qt.FlatCap))
                p.drawLine(QPointF(x, sy), QPointF(x, ey))
                sy = ey
            p.setPen(QColor(SURFACE))
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x, tip_y), 5, 5)
            self.text(p, QRectF(x0, head - 8 - 18, cw, 18), Qt.AlignHCenter | Qt.AlignBottom, self.fmt(it.value), INK, bold)
            self.text(p, QRectF(x0 + 5, base + 8, cw - 10, label_h + 2), Qt.AlignHCenter | Qt.AlignTop | WRAP, it.label,
                      INK, small)
            if it.sublabel:
                self.text(p, QRectF(x0 + 5, base + 10 + label_h, cw - 10, below), Qt.AlignHCenter | Qt.AlignTop | WRAP,
                          it.sublabel, INK_2, tiny)
        p.setPen(QColor(INK_3))
        p.drawLine(QPointF(axis, base), QPointF(right, base))

    def item_at(self, pos):
        if not self.items:
            return None
        n = int((pos.x() - self.AXIS) // self._geom()[0])
        return self.items[n] if pos.x() >= self.AXIS and 0 <= n < len(self.items) else None
