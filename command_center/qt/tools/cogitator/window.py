"""The Disposition Cogitator: every Force Disposition pitted against every other. In the left two
fifths, a matrix with a row and a column per disposition; each cell names the primary mission its
row's disposition plays against its column's, and the one played in return, each in its disposition's
colour (command_center.ui.palette.disposition_colors), as are the headings. Clicking a cell shows the
pairing's Estimate in the right three fifths (command_center.qt.tools.cogitator.estimate): the two
primary missions to score, and the pairing's layouts; the cell is outlined. A pairing has one
Estimate: the two cells that are each other's mirror across the diagonal show the same one, with the
upper cell's row disposition as Player 1. The Estimate shown at first is Battlefield Dominance's.

In a cell's bottom right corner, "1st o / 2nd o": how hard the matchup is for the row's disposition
(Player 1, in the upper triangle) when it goes first, and when it goes second. A circle's colour
comes from the saved Estimate's margin (the row's primary VP less the column's), in five groups
relative to every other margin on the matrix, from red (the hardest) to green (the easiest); it stays
empty without a saved Estimate. The colours follow the Estimates as they are edited.

It needs no army list: the launcher opens it whatever is selected."""
from __future__ import annotations

from string import capwords
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from command_center.deploy.estimates import difficulty
from command_center.qt.registry import Selection, register_tool
from command_center.qt.screen import available
from command_center.qt.theme import C, DIFFICULTY_COLORS, NO_ESTIMATE, display_family, disposition_colors, font_family
from command_center.qt.tools.cogitator.estimate import EstimatePanel
from command_center.qt.toolwindow import ToolWindow
from command_center.qt.widgets import Panel, button, label, restyle

if TYPE_CHECKING:
    from command_center.qt.app import App


FIRST_SHOWN = "Battlefield Dominance"      # the primary mission whose Estimate is shown at first
MATRIX, ESTIMATE = 2, 3                    # how the window's width is shared: two fifths, three fifths
HEADINGS = 118                             # width of the matrix's column of row headings
CELL_HEIGHT = 84                           # a cell's height, at least


def _hyphenated(word: str, font: QFontMetrics, room: int) -> str:
    """`word`, cut in two with a hyphen if it is wider than `room`: where a heading would otherwise be
    wrapped in the middle of it, wherever the line ends."""
    if font.horizontalAdvance(word) <= room:
        return word
    cut = next((n for n in range(len(word) - 2, 2, -1) if font.horizontalAdvance(word[:n] + "-") <= room),
               len(word) // 2)
    cut = min(cut, len(word) * 2 // 3)                        # not just its last letters on the second line
    return f"{word[:cut]}-\n{word[cut:]}"


class Dots(QWidget):
    """Words and circles in a row: "1st o / 2nd o", or the key to the circles' colours. A part that is a
    colour ("#rrggbb") is a circle; any other is written. set_color changes a circle."""

    DOT, GAP = 10, 5

    def __init__(self, parts: list[str]):
        super().__init__()
        self.parts = list(parts)
        self.text_font = QFont(font_family(), 9)
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


class Cell(Panel):
    """A box of the matrix: clicked anywhere, it says so."""

    clicked = Signal()

    def __init__(self):
        super().__init__("cell")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class CogitatorWindow(ToolWindow):
    title_text = "Disposition Cogitator"

    def __init__(self, app: "App", selection: Selection | None):
        super().__init__(app, selection)
        self.estimate: EstimatePanel | None = None              # the Estimate shown on the right
        self.pair: tuple[str, str] | None = None                # its pairing
        self.cells: dict[tuple[int, int], Cell] = {}
        # the difficulty circles: (row, column, the row's disposition goes first) -> their row, which circle
        self.dots: dict[tuple[int, int, bool], tuple[Dots, int]] = {}
        body = QVBoxLayout(self)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(button("← Command Center", self.back))
        top.addWidget(label("Disposition Cogitator", "h1"))
        top.addStretch(1)
        body.addLayout(top)
        split = QHBoxLayout()
        split.setSpacing(8)
        body.addLayout(split, 1)
        left = QWidget()                                        # the matrix, in the middle of its two fifths
        self.right = QWidget()
        for side, share in ((left, MATRIX), (self.right, ESTIMATE)):
            side.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # the shares, whatever they hold
            split.addWidget(side, share)
        self.right_box = QVBoxLayout(self.right)
        self.right_box.setContentsMargins(0, 0, 0, 0)
        middle = QVBoxLayout(left)
        middle.setContentsMargins(0, 0, 0, 0)
        # the window fills the screen: its width is the screen's
        self.matrix = self._build_matrix((available(app).width() - 24) * MATRIX // (MATRIX + ESTIMATE))
        middle.addWidget(self.matrix, 0, Qt.AlignCenter)
        self.show_difficulty()
        if self.ctx.missions.dispositions:
            self.open_estimate(*self._first_pairing())

    def _first_pairing(self) -> tuple[str, str]:
        """The pairing played with FIRST_SHOWN (the first one of the matrix if no mission has that name)."""
        book = self.ctx.missions
        names = book.dispositions
        pairs = [(own, opponent) for r, own in enumerate(names) for opponent in names[r:]]
        played = lambda a, b: (book.primary_mission(a, b) or {}).get("name", "").lower() == FIRST_SHOWN.lower()
        return next((p for p in pairs if played(*p) or played(*p[::-1])), pairs[0])

    def _build_matrix(self, width: int) -> Panel:
        """width: what the matrix may take; its cells are as wide as that allows, 170 at most."""
        book = self.ctx.missions
        names = book.dispositions
        f = Panel()
        g = QGridLayout(f)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(6)
        if not names:
            g.addWidget(label("No mission data yet: run  python -m command_center fetch", "muted"), 0, 0)
            return f
        cell_w = max(96, min(170, (width - 28 - HEADINGS - 6) // len(names) - 6))
        hint = label("Click a matchup for its Estimate", "muted", wrap=True)
        hint.setFixedWidth(HEADINGS)
        g.addWidget(hint, 0, 0, Qt.AlignBottom)
        heading = QFont(display_family(), 10)
        heading.setBold(True)
        room = min(cell_w, HEADINGS) - 16
        for i, name in enumerate(names):
            ink, tint = disposition_colors(name)
            text = " ".join(_hyphenated(word, QFontMetrics(heading), room) for word in name.upper().split())
            for row, col, w, align in ((0, 1 + i, cell_w, Qt.AlignCenter), (1 + i, 0, HEADINGS, Qt.AlignRight | Qt.AlignVCenter)):
                badge = QLabel(text)
                badge.setFont(heading)
                badge.setWordWrap(True)
                badge.setAlignment(align)
                badge.setFixedWidth(w)
                badge.setStyleSheet(f"background: {tint}; color: {ink}; padding: 3px 6px;")
                g.addWidget(badge, row, col)
        for r, own in enumerate(names):
            for c, opponent in enumerate(names):
                mine, theirs = book.primary_mission(own, opponent), book.primary_mission(opponent, own)
                cell = self.cells[r, c] = Cell()
                cell.setFixedWidth(cell_w)
                col = QVBoxLayout(cell)
                col.setContentsMargins(8, 6, 8, 6)
                col.setSpacing(0)
                col.addWidget(label(capwords(mine["name"]) if mine else "?", "total", wrap=True,
                                    color=disposition_colors(own)[0]))
                if own == opponent:
                    col.addWidget(label("mirror", "muted"))
                else:
                    col.addWidget(label(f"vs {capwords(theirs['name'])}" if theirs else "", "muted", wrap=True,
                                        color=disposition_colors(opponent)[0]))
                col.addStretch(1)
                dots = Dots(["1st", NO_ESTIMATE, "/  2nd", NO_ESTIMATE])     # a circle per turn order of the row's
                self.dots[r, c, True], self.dots[r, c, False] = (dots, 0), (dots, 1)
                col.addWidget(dots, 0, Qt.AlignRight)
                pair = (own, opponent) if r <= c else (opponent, own)       # as its upper-triangle cell
                cell.clicked.connect(lambda pair=pair: self.open_estimate(*pair))
                g.addWidget(cell, 1 + r, 1 + c)
        height = max(CELL_HEIGHT, *(cell.heightForWidth(cell_w) for cell in self.cells.values()))
        for cell in self.cells.values():                        # every pairing in a box of the same size
            cell.setFixedHeight(height)
        last = 1 + len(names)
        g.addWidget(label("1st / 2nd: the row's disposition going first / second, from its Estimates", "muted"),
                    last, 0, 1, last, Qt.AlignRight)
        # what the circles' colours mean
        g.addWidget(Dots(["hardest", *DIFFICULTY_COLORS, "easiest", "  ", NO_ESTIMATE, "no Estimate yet"]),
                    last + 1, 0, 1, last, Qt.AlignRight)
        return f

    def show_difficulty(self):
        """Colour the circles from the saved Estimates: each one's margin for the row's disposition, in
        five groups relative to all the others."""
        names = self.ctx.missions.dispositions
        groups = difficulty(self.ctx.missions, self.ctx.estimates)
        for (r, c, goes_first), (dots, n) in self.dots.items():
            group = groups.get((names[r], names[c], goes_first))
            dots.set_color(n, NO_ESTIMATE if group is None else DIFFICULTY_COLORS[group])

    def open_estimate(self, first: str, second: str):
        """Show the Estimate of a pairing (Player 1's disposition, Player 2's) on the right, in place of the
        one that was there, and outline its cells: the pairing's and its mirror across the diagonal."""
        if self.pair == (first, second):
            return
        if self.estimate is not None:
            self.right_box.removeWidget(self.estimate)
            self.estimate.deleteLater()
        self.pair = (first, second)
        self.estimate = EstimatePanel(self, first, second)
        self.right_box.addWidget(self.estimate)
        names = self.ctx.missions.dispositions
        shown = {(names.index(first), names.index(second)), (names.index(second), names.index(first))}
        for at, cell in self.cells.items():
            restyle(cell, on=at in shown)


@register_tool("cogitator", "Disposition Cogitator", "Every Force Disposition against every other: the primary "
               "missions of each pairing, and its Estimate: the primaries to score, the layouts.", order=5, needs_armies=False)
def open_cogitator(app: "App", selection: Selection | None) -> CogitatorWindow:
    return CogitatorWindow(app, selection)
