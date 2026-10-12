"""Small reusable widgets: the ones every window is built from, with their style (command_center.qt.theme)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton, QRadioButton, QWidget

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


def rule() -> QFrame:
    """A thin vertical line between two groups of a row."""
    line = QFrame()
    line.setProperty("role", "rule")
    line.setFixedWidth(1)
    return line
