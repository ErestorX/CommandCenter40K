"""Score Oracle: a floating window next to the Field Holomap holding the game's score sheet.

One per Field Holomap: opening it again brings it to the front; it closes with the Field Holomap.

The sheet puts the two players face to face: a header (players, the WTC result and the VP), then one
grid per player, side by side, with a column per battle round and one for the end of the battle: went
first, Battle Ready, the primary mission, the secondary missions (a row per mission, drawn at random
among those the player hasn't had yet, scored from a drop-down per round), and the CP (gained, used,
remaining). The primary mission has a row per scoring option of its card (command_center.ui.views.scoresheet).
VP above a cap can still be entered: a "!" then shows on the round's total (15 VP a round) or at the
end of the secondary mission's row (5 VP a mission). Scores are kept in
command_center.deploy.scoring.PlayerScore objects (totals, caps, WTC).

"Import Estimate" fills the two primary missions from the Disposition Cogitator's saved Estimate of
the game's pairing, the one with the player ticked "Went first" going first (command_center.deploy.estimates).
The circle next to it has that Estimate's difficulty colour, as on the Cogitator's matrix, from the
attacker's point of view; it is empty when there is no such Estimate, or nobody is ticked yet."""
from __future__ import annotations

import random
from datetime import date
from string import capwords
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from command_center.deploy.estimates import difficulty, game_estimate
from command_center.deploy.scoring import (BATTLE_READY, COLUMNS, PRIMARY_MAX, ROUND_MAX, ROUNDS, SECONDARY_CELLS,
                                           SECONDARY_MAX, SECONDARY_MISSION_MAX, PlayerScore, SecondaryRow,
                                           primary_options, wtc)
from command_center.ui.screen import screen_height
from command_center.ui.theme import C, DIFFICULTY_COLORS, NO_ESTIMATE, display_family
from command_center.ui.views.scoresheet import OVER_INK, Counter, FaceToFace, PrimaryRows, column_headers, show_vp, summary_row
from command_center.ui.widgets import Combo, Dots, Panel, Tick, button, label

if TYPE_CHECKING:
    from command_center.ui.tools.holomap.window import HolomapWindow

ROLES = ("attacker", "defender")
WIN_INK, LOSE_INK = C["good"], C["muted"]


class SheetCombo(Combo):
    """A drop-down of the sheet: the wheel scrolls the sheet, wherever the pointer is, never its value."""

    wheel = False


class ScoreOracle(QWidget):
    def __init__(self, holomap: "HolomapWindow"):
        super().__init__(holomap, Qt.Window)            # floats above the Field Holomap, both usable
        self.holomap = holomap
        self.setWindowTitle("Command Center 40K — Score Oracle")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(1000)
        screen_height(self, 1240, holomap)
        self.scores = {role: PlayerScore(name=role.title()) for role in ROLES}
        self.cells: dict[str, dict] = {role: {} for role in ROLES}
        self.primary_names = {role: "Primary mission" for role in ROLES}

        body = QVBoxLayout(self)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(8)
        body.addWidget(self._build_header())
        self.faces = FaceToFace()                           # face to face: attacker left, defender right
        body.addWidget(self.faces, 1)
        self.footer = label("", "muted", wrap=True)
        body.addWidget(self.footer)
        for role in ROLES:
            self._build_player(role)
        self.refresh()

    # ---------------------------------------------------------------- header
    def _build_header(self) -> Panel:
        h = Panel()
        g = QGridLayout(h)
        g.setContentsMargins(14, 10, 14, 10)
        g.setHorizontalSpacing(20)
        g.setVerticalSpacing(4)
        for c in (0, 2):
            g.setColumnStretch(c, 1)
        g.addWidget(label(date.today().strftime("%B %d, %Y"), "muted"), 0, 0)
        imp = QHBoxLayout()                                 # the Cogitator's Estimate of this game, on demand
        imp.setSpacing(6)
        imp.addStretch(1)
        self.import_note = label("", "muted")
        imp.addWidget(self.import_note)
        imp.addWidget(button("Import Estimate", self.import_estimate))
        self.estimate_dot = Dots([NO_ESTIMATE])
        imp.addWidget(self.estimate_dot)
        g.addLayout(imp, 0, 1, 1, 2)
        self.names: dict[str, QLineEdit] = {}
        self.side_labels = {}
        for col, role, align in ((0, "attacker", Qt.AlignLeft), (2, "defender", Qt.AlignRight)):
            f = QVBoxLayout()
            f.setSpacing(0)
            e = self.names[role] = QLineEdit(self.scores[role].name)
            e.setAlignment(align)
            e.setMaximumWidth(320)
            e.setStyleSheet(f'QLineEdit {{ background: transparent; border: none; padding: 0; font-family: "{display_family()}";'
                            f' font-size: 14pt; font-weight: bold; color: {C["att" if role == "attacker" else "def"]}; }}')
            e.textChanged.connect(lambda _text, role=role: self._on_name(role))
            f.addWidget(e, 0, align)
            lb = self.side_labels[role] = label("", align=align)
            f.addWidget(lb, 0, align)
            g.addLayout(f, 1, col)
        mid = QVBoxLayout()
        mid.setSpacing(0)
        self.score_lbl = label("", align=Qt.AlignCenter)
        self.score_lbl.setStyleSheet("font-size: 30pt; font-weight: bold;")
        self.result_lbl = label("", align=Qt.AlignCenter)
        self.points_lbl = label("", "muted", align=Qt.AlignCenter)
        for w in (self.score_lbl, self.result_lbl, self.points_lbl):
            mid.addWidget(w)
        g.addLayout(mid, 1, 1)
        return h

    # ---------------------------------------------------------------- one player's grid
    def _build_player(self, role: str):
        side = ROLES.index(role)
        g = self.faces.clear(side)
        s = self.scores[role]
        cells = self.cells[role] = {}
        g.addWidget(label(role.upper(), "att" if role == "attacker" else "def"), 0, 0)
        column_headers(g)
        row = 1

        # went first: one tick, for one player
        g.addWidget(label("Went first"), row, 0)
        first = cells["went_first"] = Tick()
        first.setChecked(s.went_first)
        first.toggled.connect(lambda on, role=role: self._on_went_first(role, on))
        g.addWidget(first, row, 1, Qt.AlignCenter)
        row += 1

        # Battle Ready
        g.addWidget(label("Battle Ready"), row, 0)
        ready = Tick()
        ready.setChecked(s.battle_ready)
        ready.toggled.connect(lambda on, s=s: (setattr(s, "battle_ready", on), self.update_totals()))
        g.addWidget(ready, row, 1, Qt.AlignCenter)
        cells["battle_ready"] = ready
        cells["battle_ready_total"] = label("", "total")
        cells["battle_ready_total"].setContentsMargins(6, 0, 0, 0)
        g.addWidget(cells["battle_ready_total"], row, 1 + COLUMNS)
        row += 1

        # primary mission: the VP counted per column, then a row per scoring option
        primary = cells["primary"] = PrimaryRows(g, row, s, self.primary_names[role], self.update_totals)
        row = primary.next_row

        # secondary missions: the VP counted per round, then a row per mission drawn ("!": over its cap)
        _, cells["secondary_rounds"], cells["secondary_total"] = summary_row(g, row, "Secondary missions", ROUNDS)
        row += 1
        cells["secondary_marks"] = []
        cells["secondary_names"] = []
        names = self._secondary_names()
        for i, sec in enumerate(s.secondaries):
            cell = QHBoxLayout()
            cell.setSpacing(2)
            cb = SheetCombo()
            cb.setEditable(not names)                       # no mission known: its name is typed
            cb.addItems(s.unused_secondaries(names, sec) or ([sec.name] if sec.name else []))
            cb.setCurrentText(sec.name)
            # the missions on the player's other rows are left out of the list
            cb.on_popup = lambda cb=cb, sec=sec: self._fill_secondaries(cb, s, sec)
            cb.currentTextChanged.connect(lambda text, sec=sec: setattr(sec, "name", text))
            cell.addWidget(cb, 1)
            cell.addWidget(button("✕", lambda role=role, i=i: self._remove_secondary(role, i), "step"))
            g.addLayout(cell, row, 0)
            cells["secondary_names"].append(cb)
            self._secondary_cells(g, row, sec, cells)
            mark = label("", "total", color=OVER_INK)
            mark.setContentsMargins(6, 0, 0, 0)
            g.addWidget(mark, row, 1 + COLUMNS)
            cells["secondary_marks"].append((sec, mark))
            row += 1
        g.addWidget(button("+ Secondary", lambda role=role: self._add_secondary(role)), row, 0, Qt.AlignLeft)
        row += 1

        # CP: gained and used, counted per round, and what remains
        cells["cp"] = {}
        for title, values in (("CP gained", s.cp_gained), ("CP used", s.cp_spent)):
            lb = label(title)
            lb.setContentsMargins(0, 10 if values is s.cp_gained else 0, 0, 0)
            g.addWidget(lb, row, 0)
            for r in range(ROUNDS):
                counter = cells["cp"][title, r] = self._cp_counter(values, r)
                g.addWidget(counter, row, 1 + r, Qt.AlignBottom | Qt.AlignHCenter)
            row += 1
        g.addWidget(label("Remaining CP"), row, 0)
        cells["cp_remaining"] = []
        for r in range(ROUNDS):
            t = label("", "total", align=Qt.AlignCenter)
            g.addWidget(t, row, 1 + r)
            cells["cp_remaining"].append(t)
        row += 1
        g.setRowStretch(row, 1)                             # space below, not between the rows
        self.update_totals()

    def _fill_secondaries(self, cb: SheetCombo, s: PlayerScore, sec: SecondaryRow):
        """A mission's drop-down, just before it opens: the missions the player has on no other row."""
        names = s.unused_secondaries(self._secondary_names(), sec)
        if names:
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            cb.setCurrentText(sec.name)
            cb.blockSignals(False)

    def _cp_counter(self, values: list[int], r: int) -> Counter:
        """- n +: CP gained (or used) in a round."""
        def step(by: int):
            values[r] = max(0, values[r] + by)
            counter.show_count(values[r])
            self.update_totals()
        counter = Counter(values[r], step)
        return counter

    def _secondary_cells(self, g: QGridLayout, row: int, sec: SecondaryRow, cells: dict):
        """A drop-down per battle round: nothing, "-" (not active), the VP scored, or "x" (discarded).
        Once the mission is scored or discarded, the row's other cells are locked."""
        boxes: list[SheetCombo] = []

        def show():
            for r, cb in enumerate(boxes):
                cb.setCurrentText(sec.rounds[r])
                cb.setEnabled(sec.closed in (None, r))

        def pick(r: int):
            sec.set(r, boxes[r].currentText().strip())
            show()
            self.update_totals()
        for r in range(ROUNDS):
            cb = SheetCombo()
            cb.addItems(SECONDARY_CELLS)
            cb.setFixedWidth(44)
            cb.activated.connect(lambda _i, r=r: pick(r))
            g.addWidget(cb, row, 1 + r, Qt.AlignCenter)
            boxes.append(cb)
        cells.setdefault("secondary_boxes", []).append((boxes, pick))     # a row's drop-downs, and what picking in one does
        show()

    # ---------------------------------------------------------------- edits
    def _on_name(self, role: str):
        self.scores[role].name = self.names[role].text()
        self.update_totals()

    def _on_went_first(self, role: str, on: bool):
        self.scores[role].went_first = on
        if on:                                                # only one player goes first
            other = "defender" if role == "attacker" else "attacker"
            self.scores[other].went_first = False
            tick = self.cells[other]["went_first"]
            tick.blockSignals(True)
            tick.setChecked(False)
            tick.blockSignals(False)
        self.show_estimate()

    def show_estimate(self):
        """The circle by "Import Estimate": the difficulty colour of the Estimate that would be imported,
        for the attacker; empty without one (none saved, or nobody ticked "Went first")."""
        d = self.holomap
        fd = {role: d.side.disposition(role) for role in ROLES}
        first = next((role for role in ROLES if self.scores[role].went_first), None)
        group = None
        if first and all(fd.values()):
            groups = difficulty(d.ctx.missions, d.ctx.estimates)
            group = groups.get((fd["attacker"], fd["defender"], first == "attacker"))
        self.estimate_dot.set_color(0, NO_ESTIMATE if group is None else DIFFICULTY_COLORS[group])

    def import_estimate(self):
        """Fill the two primary missions from the Cogitator's saved Estimate of this game: its pairing of
        Force Dispositions, with the player ticked "Went first" going first. What was scored on the
        primaries is replaced; the note next to the button says what was done, or what is missing."""
        d = self.holomap
        fd = {role: d.side.disposition(role) for role in ROLES}
        first = next((role for role in ROLES if self.scores[role].went_first), None)
        if not all(fd.values()):
            return self.import_note.setText("Both lists need a Force Disposition")
        if first is None:
            return self.import_note.setText("Tick who went first, then import")
        p1, p2, goes_first, attacker_is_p1 = game_estimate(d.ctx.missions.dispositions, fd["attacker"],
                                                          fd["defender"], first == "attacker")
        roles = ROLES if attacker_is_p1 else ROLES[::-1]        # the roles of Player 1 and Player 2
        text = f"{p1} vs {p2}, Player {goes_first + 1} ({roles[goes_first]}) first"
        if not d.ctx.estimates.load(p1, p2, goes_first, [self.primary_names[r] for r in roles],
                                    [self.scores[r] for r in roles]):
            return self.import_note.setText(f"No Estimate saved for {text}")
        for role in ROLES:
            self._build_player(role)
        self.import_note.setText(f"Imported: {text}")

    def _secondary_names(self) -> list[str]:
        return [capwords(m["name"]) for m in self.holomap.ctx.missions.secondary_missions]

    def _add_secondary(self, role: str):
        """A new row, with a mission drawn at random among those the player hasn't had yet."""
        s = self.scores[role]
        left = s.unused_secondaries(self._secondary_names())
        s.secondaries.append(SecondaryRow(random.choice(left) if left else ""))
        self._build_player(role)

    def _remove_secondary(self, role: str, i: int):
        del self.scores[role].secondaries[i]
        self._build_player(role)

    # ---------------------------------------------------------------- totals and the result
    def update_totals(self):
        for role in ROLES:
            s, c = self.scores[role], self.cells[role]
            if "cp_remaining" in c:                             # its grid is built
                c["primary"].refresh()
                for r, lb in enumerate(c["secondary_rounds"]):
                    show_vp(lb, s.secondary_vp(r), s.secondary_over(r))
                for sec, mark in c["secondary_marks"]:
                    mark.setText("!" if sec.over else "")
                for r, lb in enumerate(c["cp_remaining"]):      # up to the last round played
                    left = s.cp_remaining(r)
                    lb.setText(str(left) if s.cp_played(r) else "")
                    lb.setStyleSheet(f"color: {C['att'] if left < 0 else C['ink']};")
                c["secondary_total"].setText(f"{s.secondary_total}/{SECONDARY_MAX}")
                c["battle_ready_total"].setText(f"{BATTLE_READY if s.battle_ready else 0}/{BATTLE_READY}")
        a, d = self.scores["attacker"], self.scores["defender"]
        wa, wd = wtc(a.total, d.total)
        self.score_lbl.setText(f"{wa} - {wd}")
        if a.total == d.total:
            text, ink = "DRAW", LOSE_INK
        else:
            winner = a if a.total > d.total else d
            text, ink = f"{(winner.name or 'Winner').upper()} WINS", WIN_INK
        self.result_lbl.setText(text)
        self.result_lbl.setStyleSheet(f'font-family: "{display_family()}"; font-size: 13pt; font-weight: bold; color: {ink};')
        self.points_lbl.setText(f"WTC  ·  Points: {a.total} - {d.total}")

    def refresh(self):
        """Armies, dispositions and primary missions, as the Field Holomap shows them."""
        d = self.holomap
        armies = {"attacker": d.selection.attacker, "defender": d.selection.defender}
        fd = {role: d.side.disposition(role) for role in ROLES}
        book = d.ctx.missions
        primaries = {}
        for role, other in (("attacker", "defender"), ("defender", "attacker")):
            army = armies[role]
            mission = book.primary_mission(fd[role], fd[other]) if fd[role] and fd[other] else None
            primaries[role] = capwords(mission["name"]) if mission else "Primary mission"
            if primaries[role] != self.primary_names[role]:       # another mission: its own scoring options
                self.primary_names[role] = primaries[role]
                self.scores[role].set_options(primary_options(mission))
                self._build_player(role)
            self.side_labels[role].setText(f"{army.faction or army.path.stem}\n{fd[role] or 'No Force Disposition'}")
        layouts = book.layouts_for(fd["attacker"], fd["defender"]) if all(fd.values()) else []
        self.footer.setText("Warhammer 40,000 11th edition  ·  "
                            + (f"{fd['attacker']} vs {fd['defender']}  ·  " if all(fd.values()) else "")
                            + f"{primaries['attacker']} / {primaries['defender']}"
                            + (f"  ·  layouts {', '.join(l['id'] for l in layouts)}" if layouts else "")
                            + f"\n!  VP above a cap don't count: {ROUND_MAX} per battle round (primary,"
                              f" secondary), {SECONDARY_MISSION_MAX} per secondary mission, {PRIMARY_MAX}"
                              " over the game.")
        self.update_totals()
        self.show_estimate()
