"""Parts of a score sheet shared by the windows that show one (the Score Oracle, the Disposition
Cogitator's Estimates): two players' grids face to face in a scrolling area, and the rows of a primary
mission in such a grid.

A grid has the texts in column 0, a column per battle round and one for the end of the battle
(columns 1 to COLUMNS), then a column for totals. Its texts wrap to the width the grid leaves them."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QWidget

from command_center.deploy.scoring import COLUMNS, END, PRIMARY_MAX, PlayerScore
from command_center.qt.theme import C
from command_center.qt.widgets import Panel, Tick, button, label, restyle

OVER_INK = C["warn"]                               # VP lost to a cap
WIDE = 2 + COLUMNS                                 # the columns a text spanning a grid takes


class FaceToFace(QScrollArea):
    """Two grids side by side, one per player, as wide as each other, scrolling together when they are
    taller than the room they get."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)                           # the sheet is as wide as the area, and at least as tall
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sheet = QWidget()
        self.row = QHBoxLayout(sheet)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.panels: list[Panel | None] = [None, None]
        for i in range(2):
            self.clear(i)
        self.setWidget(sheet)

    def clear(self, i: int) -> QGridLayout:
        """A player's grid, empty, to build it again."""
        panel = Panel()
        panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # half the sheet each, whatever they hold
        g = QGridLayout(panel)
        g.setContentsMargins(10, 10, 10, 10)
        g.setHorizontalSpacing(2)
        g.setVerticalSpacing(2)
        g.setColumnStretch(0, 1)
        old = self.panels[i]
        if old is None:
            self.row.addWidget(panel, 1)
        else:
            self.row.replaceWidget(old, panel)
            self.row.setStretch(i, 1)
            old.deleteLater()
        self.panels[i] = panel
        return g


def column_headers(g: QGridLayout, row: int = 0):
    """The round numbers, then the end of the battle, above their columns."""
    for col in range(COLUMNS):
        g.addWidget(label("End" if col == END else str(col + 1), "muted"), row, 1 + col, Qt.AlignCenter)


def summary_row(g: QGridLayout, row: int, title: str, n: int) -> tuple[QLabel, list[QLabel], QLabel]:
    """A section's heading: its name, a label per column for the VP counted there, one for its total."""
    lb = label(title, "total", wrap=True)
    g.addWidget(lb, row, 0)
    rounds = []
    for col in range(n):
        t = label("", "total", align=Qt.AlignCenter)
        t.setMinimumWidth(30)
        g.addWidget(t, row, 1 + col)
        rounds.append(t)
    total = label("", "total")
    g.addWidget(total, row, 1 + COLUMNS)
    for w in (lb, *rounds, total):
        w.setContentsMargins(6 if w is total else 0, 10, 0, 2)
    return lb, rounds, total


def show_vp(lb: QLabel, points: int, over: bool):
    """The VP counted in a column; with a "!" when more were scored than the round's cap."""
    lb.setText(f"{points}!" if over else str(points) if points else "")
    lb.setStyleSheet(f"color: {OVER_INK if over else C['ink']};")


class PrimaryRows:
    """A player's primary mission in a grid, from `row` down: its heading (the VP counted per column, the
    total), then a row per scoring option of its card, under its block's heading: a tick box where the
    option is scored once, a - n + counter where it is scored "for each ...". Without options (the
    mission isn't known), a row of VP cells to fill by hand.

    next_row: the first free row under it.
    on_change: called after each edit; refresh() then shows the totals."""

    def __init__(self, g: QGridLayout, row: int, score: PlayerScore, title: str, on_change: Callable[[], None]):
        self.score, self.on_change = score, on_change
        self.shown: dict[tuple[int, int], Callable[[int], None]] = {}      # (option, column) -> show a count
        _, self.rounds, self.total = summary_row(g, row, title, COLUMNS)
        row += 1
        if not score.options:
            g.addWidget(label("VP scored", "muted"), row, 0)
            self._round_cells(g, row, score.primary)
            self.next_row = row + 1
            return
        block = None
        for i, opt in enumerate(score.options):
            if opt.block != block:                              # "Second battle round onwards · End of your turn."
                block = opt.block
                head = label("  ·  ".join(t for t in (opt.round.capitalize(), opt.when) if t), "muted", wrap=True)
                head.setContentsMargins(0, 5, 0, 0)
                g.addWidget(head, row, 0, 1, WIDE)
                row += 1
            text = f"{'or ' if opt.group != i else ''}{'+' if opt.additional else ''}{opt.vp}VP  {opt.text}"
            lb = label(text, "small", wrap=True)
            lb.setContentsMargins(8, 0, 0, 0)
            g.addWidget(lb, row, 0)
            for col in opt.columns:
                w = self._tick(i, col) if opt.tick else self._counter(i, col)
                g.addWidget(w, row, 1 + col, Qt.AlignCenter)
            row += 1
        self.next_row = row

    def refresh(self):
        s = self.score
        for col, lb in enumerate(self.rounds):
            show_vp(lb, s.primary_vp(col), s.primary_over(col))
        self.total.setText(f"{s.primary_total}/{PRIMARY_MAX}")

    def _score(self, i: int, col: int, n: int):
        """An option is scored n times in a column; ticks and counters then show the sheet's state
        (scoring an option unticks its alternatives)."""
        self.score.score(i, col, n)
        for (j, c), show in self.shown.items():
            if c == col:
                show(self.score.counts[j][c])
        self.on_change()

    def _tick(self, i: int, col: int) -> Tick:
        box = Tick()
        box.setChecked(bool(self.score.counts[i][col]))

        def show(n: int):                                       # as the sheet says: without scoring again
            box.blockSignals(True)
            box.setChecked(bool(n))
            box.blockSignals(False)
        self.shown[i, col] = show
        box.toggled.connect(lambda on: self._score(i, col, int(on)))
        return box

    def _counter(self, i: int, col: int) -> QWidget:
        """- n +: how many times an option is scored in a column."""
        f = QWidget()
        row = QHBoxLayout(f)
        row.setContentsMargins(3, 0, 3, 0)
        row.setSpacing(0)
        count = label(str(self.score.counts[i][col]), align=Qt.AlignCenter)
        count.setMinimumWidth(20)
        self.shown[i, col] = lambda n: count.setText(str(n))
        for text, step in (("−", -1), ("", 0), ("+", 1)):
            if not step:
                row.addWidget(count)
                continue
            row.addWidget(button(text, lambda step=step: self._score(i, col, self.score.counts[i][col] + step), "step"))
        return f

    def _round_cells(self, g: QGridLayout, row: int, values: list[str]):
        """A cell per column of `values`, editing them in place: a number, "-" or nothing."""
        for r in range(len(values)):
            e = QLineEdit(values[r])
            e.setMaxLength(3)
            e.setFixedWidth(34)
            e.setAlignment(Qt.AlignCenter)
            e.setProperty("state", self._cell_state(values[r]))
            g.addWidget(e, row, 1 + r, Qt.AlignCenter)
            e.textChanged.connect(lambda text, e=e, r=r: self._on_cell(values, r, text, e))

    @staticmethod
    def _cell_state(text: str) -> str:
        """How a cell is shown: empty, holding a value, or holding what is not one."""
        if not text:
            return ""
        return "done" if text == "-" or text.isdigit() else "bad"

    def _on_cell(self, values: list[str], r: int, text: str, e: QLineEdit):
        text = text.strip()
        state = self._cell_state(text)
        restyle(e, state=state)
        values[r] = "" if state == "bad" else text
        self.on_change()
