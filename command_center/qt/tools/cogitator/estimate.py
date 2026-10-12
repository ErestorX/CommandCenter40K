"""The Estimate: the Disposition Cogitator's panel for one pairing of Force Dispositions, Player 1's
against Player 2's, to the right of its matrix.

Top half, the two players face to face with the primary mission each plays in the pairing, as on the
Score Oracle's sheet: a row per scoring option, to tick or count per battle round, and the VP it adds
up to; under them, the actions of the mission's card, in full. Bottom half, the pairing's three battlefield layouts, with the deployment zones and the line
between the two territories; Player 1 has the layouts' attacker side, Player 2 the defender's.

A pairing has two Estimates: one with Player 1 going first, one with Player 2. The header switches
between them (Player 1 first to begin with). In a mirror pairing they are the same Estimate with the
two players swapped: what is scored for the player going first shows on whoever goes first. Each is
saved at every change (ctx.estimates, command_center.deploy.estimates) and shown again the next time;
the Score Oracle can import the one matching its game."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from command_center.deploy.estimates import PLAYERS, saved_scores
from command_center.deploy.scoring import PlayerScore
from command_center.qt.views.board import LayoutMap
from command_center.qt.views.scoresheet import WIDE, FaceToFace, PrimaryRows, column_headers
from command_center.qt.widgets import Choice, Panel, label

if TYPE_CHECKING:
    from command_center.qt.tools.cogitator.window import CogitatorWindow

SIDES = (("att", "att-badge"), ("def", "def-badge"))     # Player 1, Player 2: its name's style, its badge's


class EstimatePanel(QWidget):
    def __init__(self, cogitator: "CogitatorWindow", first: str, second: str):
        """first, second: Player 1's and Player 2's Force Dispositions."""
        super().__init__()
        book = cogitator.ctx.missions
        self.cogitator = cogitator
        self.store = cogitator.ctx.estimates
        self.pair = (first, second)
        pairing = ((first, second), (second, first))

        # one Estimate per player going first: each its own two scores, as saved
        self.scores: list[list[PlayerScore]] = []
        for goes_first in range(2):
            self.names, scores, _ = saved_scores(book, self.store, first, second, goes_first)
            self.scores.append(scores)
        if first == second:                                     # mirror: one Estimate, its players swapped
            self.scores[1] = self.scores[0][::-1]
        self.goes_first = 0                                     # the Estimate shown: the player going first
        # the actions of each player's primary mission, as on its card
        self.actions = [(book.primary_mission(*p) or {}).get("actions", []) for p in pairing]

        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.turn_labels: list[QLabel] = []
        body.addWidget(self._build_header(pairing))
        self.faces = FaceToFace()
        self.primaries: list[PrimaryRows | None] = [None, None]

        maps = QWidget()
        row = QHBoxLayout(maps)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        layouts = book.layouts_for(first, second)
        self.maps: list[LayoutMap] = []
        for c in range(3):
            m = LayoutMap()
            m.show_territory = True
            m.role_names = dict(zip(("attacker", "defender"), PLAYERS))
            m.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)      # a third each
            m.set_layout(layouts[c] if c < len(layouts) else None,
                         "" if layouts or c else f"No layouts found for {first} vs {second}.")
            row.addWidget(m, 1)
            self.maps.append(m)
        for half in (self.faces, maps):                         # the primaries above, the maps below: half each
            half.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
            body.addWidget(half, 1)
        self._show_estimate()

    def _build_header(self, pairing) -> Panel:
        """Each player: its name, Force Disposition and primary mission, and whether it goes first. Between
        them, who goes first: the Estimate shown."""
        head = Panel()
        g = QGridLayout(head)
        g.setContentsMargins(14, 8, 14, 8)
        g.setHorizontalSpacing(20)
        g.setVerticalSpacing(4)
        for c in (0, 2):
            g.setColumnStretch(c, 1)
        for c, i, align in ((0, 0, Qt.AlignLeft), (2, 1, Qt.AlignRight)):
            top = QHBoxLayout()
            top.setSpacing(8)
            turn = label("", "muted")
            parts = [label(PLAYERS[i].upper(), SIDES[i][0]), label(pairing[i][0].upper(), SIDES[i][1]), turn]
            self.turn_labels.append(turn)
            if align == Qt.AlignRight:                          # mirrored on the right
                top.addStretch(1)
                parts.reverse()
            for w in parts:
                top.addWidget(w)
            if align == Qt.AlignLeft:
                top.addStretch(1)
            g.addLayout(top, 0, c)
            g.addWidget(label(self.names[i], "h2"), 1, c, align)
        pick = QHBoxLayout()
        pick.setSpacing(6)
        pick.addWidget(label("Goes first"))
        self.first_buttons = QButtonGroup(self)
        for i, player in enumerate(PLAYERS):
            b = Choice(player)
            b.setChecked(i == self.goes_first)
            self.first_buttons.addButton(b, i)
            pick.addWidget(b)
        self.first_buttons.idClicked.connect(self._show_estimate)
        g.addLayout(pick, 0, 1, Qt.AlignCenter)
        g.addWidget(label("Mirror: one Estimate, the same whoever goes first, saved as you go"
                          if pairing[0][0] == pairing[0][1] else "One Estimate per player going first, each saved as you go",
                          "muted"), 1, 1, Qt.AlignCenter)
        return head

    def _show_estimate(self, goes_first: int | None = None):
        """The Estimate of the player going first: who goes first next to the names, and its two primaries."""
        if goes_first is not None:
            self.goes_first = goes_first
        for i, lb in enumerate(self.turn_labels):
            lb.setText("goes first" if i == self.goes_first else "goes second")
        for i, score in enumerate(self.scores[self.goes_first]):
            g = self.faces.clear(i)
            g.addWidget(label(PLAYERS[i].upper(), SIDES[i][0]), 0, 0)
            column_headers(g)
            rows = self.primaries[i] = PrimaryRows(g, 1, score, self.names[i], on_change=lambda i=i: self._changed(i))
            row = self._show_actions(g, rows.next_row, i)
            g.setRowStretch(row, 1)                             # space below, not between the rows
            rows.refresh()

    def _show_actions(self, g: QGridLayout, row: int, i: int) -> int:
        """The actions of a player's mission, from `row` down: each one's name and type, then its card's lines
        (starts, units, use limit, completes, effect...). Returns the first free row under them."""
        def line(text: str, role: str, top: int):
            nonlocal row
            lb = label(text, role, wrap=True)
            lb.setContentsMargins(0, top, 0, 2)
            g.addWidget(lb, row, 0, 1, WIDE)
            row += 1
        for a in self.actions[i]:
            line(f"{a.get('name', '').title()}  ·  {a.get('type', '').capitalize()}", "total", 12)
            for key, text in a.items():
                if key not in ("name", "type"):
                    line(f"{key.replace('_', ' ').capitalize()}: {text}", "muted", 0)
        return row

    def _changed(self, i: int):
        """A player's scoring changed: its totals, the Estimate saved, and the matrix's difficulty colours."""
        self.primaries[i].refresh()
        self.store.put(*self.pair, self.goes_first, self.names, self.scores[self.goes_first])
        self.cogitator.show_difficulty()
