"""Small reusable widgets: the ones every window is built from, with their style (command_center.ui.theme)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHeaderView, QLabel, QPushButton,
                               QRadioButton, QSizePolicy, QStyle, QStyleOptionComboBox, QTreeWidget, QTreeWidgetItem, QWidget)

from command_center.ui.palette import C


def restyle(widget: QWidget, **properties) -> None:
    """Change properties the style sheet looks at (role, on, state...) on a widget already shown."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text: str = "", role: str | None = None, wrap: bool = False, color: str | None = None,
          align: Qt.AlignmentFlag | None = None) -> QLabel:
    """A text: `role` is its style (h1, h2, muted, small, total, att, def, a badge...), `color` its ink
    when it is not the role's."""
    lb = QLabel(text)
    lb.setTextFormat(Qt.PlainText)
    if role:
        lb.setProperty("role", role)
    if wrap:
        lb.setWordWrap(True)
    if color:
        lb.setStyleSheet(f"color: {color};")
    if align is not None:
        lb.setAlignment(align)
    return lb


def button(text: str, command: Callable[[], None], role: str | None = None, tip: str = "") -> QPushButton:
    """A bevelled button; role "accent": in red, for what moves on."""
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if tip:
        b.setToolTip(tip)
    b.clicked.connect(lambda: command())
    return b


class Panel(QFrame):
    """A charcoal panel with a thin border, to put a layout in. role "cell": a black box on a panel."""

    def __init__(self, role: str = "panel"):
        super().__init__()
        self.setProperty("role", role)


class _Marked:
    """A tick box or a radio button drawn for the dark theme: an inset box (round for a radio button)
    with a light mark, then its text. The system's own are dark on dark."""

    BOX, GAP = 14, 6
    round_box = False

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text = self.GAP + fm.horizontalAdvance(self.text()) + 2 if self.text() else 0
        return QSize(self.BOX + text, max(self.BOX + 4, fm.height() + 2))

    minimumSizeHint = sizeHint

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, live = self.isChecked(), self.isEnabled()
        box = QRectF(0.5, (self.height() - self.BOX) / 2 + 0.5, self.BOX - 1, self.BOX - 1)
        p.setPen(QColor(C["line"]))
        p.setBrush(QColor(C["grid"] if not live else C["raised"] if self.underMouse() else C["field"]))
        ink = QColor(C["ink"] if live else C["dim"])
        if self.round_box:
            p.drawEllipse(box)
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(ink)
                p.drawEllipse(box.center(), 3, 3)
        else:
            p.drawRect(box)
            if on:
                p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                x, y = box.left(), box.top()
                p.drawPolyline([QPointF(x + 3, y + 7), QPointF(x + 5.5, y + 9.5), QPointF(x + 10, y + 3.5)])
        if self.text():
            p.setPen(ink)
            p.drawText(self.rect().adjusted(self.BOX + self.GAP, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text())

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()


class Tick(_Marked, QCheckBox):
    """A tick box."""


class Choice(_Marked, QRadioButton):
    """A radio button: one of a group is chosen."""

    round_box = True


def pct(x: float) -> str:
    return f"{x:.0%}" if x < 0.995 or x == 1 else ">99%"


class Table(QTreeWidget):
    """A table with headings. columns: (key, title) pairs; widths: a column's width in pixels, negative for
    one that takes the room left (at least that wide). rows: how many it shows; `fixed`: no more, no less.
    A row may be given a key, to find it by (keys, selected_key, select). `reordered` is emitted after the
    user dragged a row to another place (allow_reorder)."""

    reordered = Signal()

    def __init__(self, columns, widths, rows: int = 6, fixed: bool = False, selectable: bool = True):
        super().__init__()
        self.setColumnCount(len(columns))
        self.setHeaderLabels([title for _, title in columns])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SingleSelection if selectable else QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        head = self.header()
        head.setStretchLastSection(False)
        head.setSectionsMovable(False)
        head.setSectionsClickable(False)
        head.setMinimumSectionSize(16)
        self.centred = []
        for i, w in enumerate(widths):
            head.setSectionResizeMode(i, QHeaderView.Stretch if w < 0 else QHeaderView.Fixed)
            if w > 0:
                self.setColumnWidth(i, w)
            self.centred.append(i > 0 and w > 0)
            head.model().setHeaderData(i, Qt.Horizontal, int(Qt.AlignCenter if self.centred[i] else Qt.AlignLeft | Qt.AlignVCenter),
                                       Qt.TextAlignmentRole)
        self.setMinimumWidth(sum(abs(w) for w in widths) // 2)
        self.fixed = fixed
        self.set_rows(rows)

    def set_rows(self, rows: int):
        """Show `rows` rows: exactly, for a fixed table; at least, for one that grows with its room."""
        height = self.header().sizeHint().height() + rows * self.row_height + 2 * self.frameWidth()
        if self.fixed:
            self.setFixedHeight(height)
        else:
            self.setMinimumHeight(height)

    @property
    def row_height(self) -> int:
        return self.fontMetrics().height() + 6

    def clear_rows(self):
        self.clear()

    def add_row(self, values, key=None, color: str | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([str(v) for v in values])
        item.setData(0, Qt.UserRole, key)
        item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)         # rows are moved between rows, not into one
        for i, centred in enumerate(self.centred):
            if centred:
                item.setTextAlignment(i, Qt.AlignCenter)
            elif len(item.text(i)) > 20:
                item.setToolTip(i, item.text(i))                    # in full, where its column may cut it short
            if color:
                item.setForeground(i, QColor(color))
        self.addTopLevelItem(item)
        return item

    def keys(self) -> list:
        return [self.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.topLevelItemCount())]

    def row(self, key) -> QTreeWidgetItem | None:
        """The row with this key."""
        keys = self.keys()
        return self.topLevelItem(keys.index(key)) if key in keys else None

    def set_row(self, key, values, color: str | None = None):
        """Write a row again, where it is. color None: the table's own ink."""
        item = self.row(key)
        for i, v in enumerate(values):
            item.setText(i, str(v))
            item.setData(i, Qt.ForegroundRole, QColor(color) if color else None)

    def set_cell(self, key, column: int, text):
        self.row(key).setText(column, str(text))

    def sort_by_heading(self, on_sort: Callable[[int], None]):
        """A click on a column's heading calls on_sort(column): the table's owner puts the rows in order."""
        self.header().setSectionsClickable(True)
        self.header().sectionClicked.connect(on_sort)

    def selected_key(self):
        items = self.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else None

    def select(self, key) -> None:
        """Select the row with this key and bring it in view; no one is told."""
        self.blockSignals(True)
        self.clearSelection()
        if key in self.keys():
            item = self.topLevelItem(self.keys().index(key))
            item.setSelected(True)
            self.scrollToItem(item)
        self.blockSignals(False)

    def allow_reorder(self):
        """Rows can be dragged to another place in the table."""
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def move_row(self, key, to: int):
        """Put a row at another place, as a drag would."""
        self.insertTopLevelItem(to, self.takeTopLevelItem(self.keys().index(key)))
        self.reordered.emit()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class Dots(QWidget):
    """Words and circles in a row: "1st o / 2nd o", or the key to the circles' colours. A part that is a
    colour ("#rrggbb") is a circle; any other is written. set_color changes a circle."""

    DOT, GAP = 10, 5

    def __init__(self, parts: list[str]):
        super().__init__()
        self.parts = list(parts)
        self.text_font = QFont(self.font())
        self.text_font.setPointSize(9)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_color(self, n: int, color: str):
        """Fill the nth circle (0: the first)."""
        at = [i for i, part in enumerate(self.parts) if part.startswith("#")][n]
        if self.parts[at] != color:
            self.parts[at] = color
            self.update()

    def _widths(self) -> list[int]:
        fm = QFontMetrics(self.text_font)
        return [self.DOT if part.startswith("#") else fm.horizontalAdvance(part) for part in self.parts]

    def sizeHint(self) -> QSize:
        widths = self._widths()
        return QSize(sum(widths) + self.GAP * (len(widths) - 1) + 2, 16)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.text_font)
        x = 1
        for part, w in zip(self.parts, self._widths()):
            p.setPen(QColor(C["muted"]))
            if part.startswith("#"):
                p.setBrush(QColor(part))
                p.drawEllipse(QRectF(x + 0.5, 3.5, self.DOT - 1, self.DOT - 1))
            else:
                p.drawText(QRectF(x, 0, w, 16), Qt.AlignLeft | Qt.AlignVCenter, part)
            x += w + self.GAP


class Combo(QComboBox):
    """A drop-down in the theme's colours, with its arrow drawn (a styled one has none of its own).

    wheel: False where the wheel must scroll what the drop-down is on, and never change its value.
    on_popup: called just before its list opens, to fill it with what can be chosen now."""

    wheel = True
    on_popup: Callable[[], None] | None = None

    def wheelEvent(self, event):
        if self.wheel:
            super().wheelEvent(event)
        else:
            event.ignore()                      # passed on to what holds it

    def showPopup(self):
        if self.on_popup:
            self.on_popup()
        super().showPopup()

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        box = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(box.center()) + QPointF(0.5, 1)
        arrow = QPainterPath()
        arrow.moveTo(c.x() - 3.5, c.y() - 2)
        arrow.lineTo(c.x() + 3.5, c.y() - 2)
        arrow.lineTo(c.x(), c.y() + 2.5)
        arrow.closeSubpath()
        p.fillPath(arrow, QColor(C["ink"] if self.isEnabled() else C["dim"]))


class EyeButton(QWidget):
    """Small drawn 'eye' icon button (no emoji fonts needed)."""

    def __init__(self, command: Callable[[], None], tip: str = ""):
        super().__init__()
        self.command = command
        self.setFixedSize(24, 16)
        self.setCursor(Qt.PointingHandCursor)
        if tip:
            self.setToolTip(tip)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(C["att"] if self.underMouse() else C["muted"]), 1.6))
        lid = QPainterPath()
        lid.moveTo(2, 8)
        lid.quadTo(12, -3, 22, 8)
        lid.quadTo(12, 19, 2, 8)
        p.drawPath(lid)
        p.drawEllipse(QPointF(12, 8), 3.5, 3.5)
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(12, 8), 1.5, 1.5)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.command()


def rule() -> QFrame:
    """A thin vertical line between two groups of a row."""
    line = QFrame()
    line.setProperty("role", "rule")
    line.setFixedWidth(1)
    return line
