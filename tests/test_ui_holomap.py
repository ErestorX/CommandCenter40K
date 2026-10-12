"""The Field Holomap and its Score Oracle, without a screen, on the test fixtures: the boards and where
they go, units put on them, dragged and turned, what is drawn for the selected one, and the score sheet."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from command_center.analysis.army_plans import ArmyPlanStore, PlanEntry, PlanTarget, SavedPlan
from command_center.deploy.placement import BOARD_H, BOARD_W
from command_center.lists import parse_list
from tests.helpers import FIXTURE_LIST
from tests.test_ui_auspex import wait_until
from tests.test_ui_windows import fixture_context


class HolomapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.ui.app import App, application
        from command_center.ui.registry import Selection, discover
        cls.tools = {t.key: t for t in discover()}
        cls.qt = application()
        cls.ctx = fixture_context()
        cls.ctx._army_plans = ArmyPlanStore(Path(tempfile.mkdtemp()) / "army_plans.json")
        cls.app = App(cls.ctx)
        cls.app.resize(1500, 900)
        cls.app.show()
        cls.selection = Selection(parse_list(FIXTURE_LIST, cls.ctx.wd), parse_list(FIXTURE_LIST, cls.ctx.wd))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.win = self.app.open_tool("holomap", self.selection)
        self.win.setWindowState(Qt.WindowNoState)
        self.win.resize(1500, 900)
        self.addCleanup(self.win.close)
        self.assertTrue(wait_until(lambda: not self.win._arrange_timer.isActive()))
        self.qt.processEvents()

    def place(self, n: int = 2):
        """n units of each side on the maps; their token keys, attackers first."""
        side = self.win.side
        for role in ("attacker", "defender"):
            for key in list(side.rows[role])[:n]:
                side.toggle(role, key)
        return [k for k in self.win.placed if k.startswith("attacker")], [k for k in self.win.placed if k.startswith("defender")]

    def test_every_tool_is_there(self):
        self.assertEqual(set(self.tools), {"cogitator", "auspex", "optimizer", "holomap"})

    def test_boards_and_info_share_the_room(self):
        win = self.win
        self.assertIn("mirror", win.pairing.text())                        # the fixture list against itself
        self.assertTrue(win.maps[0].layout_data)                           # the fixtures have not all three layouts
        self.assertTrue(all(m.isVisible() for m in win.maps))
        area = win.board_area.rect()
        cells = [m.geometry() for m in win.maps] + [win.info_cell.geometry()]
        for i, a in enumerate(cells):
            self.assertTrue(area.contains(a))
            for b in cells[i + 1:]:
                self.assertFalse(a.intersects(b))                          # nothing over anything else
        before = win.maps[0].width() * win.maps[0].height()
        win.shown[1].setChecked(False)
        win.shown[2].setChecked(False)
        self.assertFalse(win.maps[1].isVisible() or win.maps[2].isVisible())
        self.assertGreater(win.maps[0].width() * win.maps[0].height(), before)     # the one left is larger
        win.shown[1].setChecked(True)
        self.assertTrue(win.maps[1].isVisible())
        for role in ("attacker", "defender"):
            self.assertIn("VP", win.side.texts[role].toPlainText())        # its primary mission's card

    def test_units_on_the_maps(self):
        win = self.win
        attackers, defenders = self.place()
        for m in win.maps:
            self.assertEqual(set(m.tokens), set(attackers + defenders))
            self.assertEqual(set(m.items), set(m.tokens) if m.layout_data else set())     # drawn where there is a board
            for t in m.tokens.values():                                    # on the board, each map its own spot
                self.assertTrue(0 <= t.x <= BOARD_W and 0 <= t.y <= BOARD_H)
        key = attackers[0]
        self.assertEqual(win.side.trees["attacker"].row(key.split(":")[1]).text(0), "✓")
        win.side.toggle("attacker", key.split(":")[1])                     # taken off again
        self.assertTrue(all(key not in m.tokens and key not in m.items for m in win.maps))
        self.assertNotIn(key, win.placed)

    def test_one_selection_for_the_window(self):
        win = self.win
        attackers, defenders = self.place()
        first, second = win.maps[0], win.maps[1]
        first.pick(attackers[0])
        self.assertEqual(win.selected, (first, attackers[0]))
        self.assertEqual(win.side.trees["attacker"].selected_key(), attackers[0].split(":")[1])
        second.pick(defenders[0])                                          # on another map: the first lets go
        self.assertIsNone(first.selected)
        self.assertEqual(win.side.trees["defender"].selected_key(), defenders[0].split(":")[1])
        self.assertIsNone(win.side.trees["attacker"].selected_key())
        second.view.right_clicked.emit()
        self.assertIsNone(win.selected)
        self.assertIsNone(win.side.trees["defender"].selected_key())

    def test_a_unit_is_dragged_and_turned(self):
        attackers, _ = self.place()
        m, key = self.win.maps[0], attackers[0]
        t = m.tokens[key]
        m.move_token(key, 30, 22)
        self.assertEqual((t.x, t.y), (30, 22))
        at = m.view.mapFromScene(m.items[key].pos())
        QTest.mousePress(m.view.viewport(), Qt.LeftButton, pos=at)         # a drag with the mouse
        QTest.mouseMove(m.view.viewport(), at + QPoint(20, 0))
        QTest.mouseMove(m.view.viewport(), at + QPoint(40, 0))
        QTest.mouseRelease(m.view.viewport(), Qt.LeftButton, pos=at + QPoint(40, 0))
        self.assertGreater(t.x, 30)
        self.assertAlmostEqual(t.y, 22, delta=0.5)
        self.assertEqual(m.selected, key)                                  # pressed: selected
        m.move_token(key, 500, -500)                                       # past a corner: it stops at the edges
        w, h = t.box
        self.assertAlmostEqual(t.x, BOARD_W - w / 2)
        self.assertAlmostEqual(t.y, h / 2)
        m.rotate(key)
        self.assertEqual(t.angle, 30)
        w, h = t.box
        self.assertTrue(w / 2 - 1e-6 <= t.x <= BOARD_W - w / 2 + 1e-6 and h / 2 - 1e-6 <= t.y <= BOARD_H - h / 2 + 1e-6)
        m.describe(t)
        self.assertIn("turned 30", m.sub.text())
        m.describe(None)
        self.assertIn(m.layout_data["id"], m.sub.text())
        self.assertEqual(m.items[key].toolTip(), t.label)                  # its whole name, whatever its base has room for

    def test_overlays_of_the_selected_unit(self):
        win = self.win
        attackers, defenders = self.place()
        m = win.maps[0]
        key = next((k for k in attackers if m.tokens[k].ranges), attackers[0])
        m.pick(key)
        self.assertEqual(m._overlay_items, [])
        ticks = win.overlay_ticks
        self.assertFalse(ticks["hidden"].isEnabled() or ticks["plan2"].isEnabled())
        for name in ("move", "advance", "charge"):
            ticks[name].setChecked(True)
        rings = len(m._overlay_items)
        self.assertGreater(rings, 0)
        ticks["objectives"].setChecked(True)
        self.assertGreater(len(m._overlay_items), rings)
        with_distances = len(m._overlay_items)
        ticks["sight"].setChecked(True)
        self.assertTrue(ticks["hidden"].isEnabled())
        self.assertFalse(ticks["ground"].isEnabled())                      # Go to Ground refines Hidden
        if m.tokens[key].ranges:
            self.assertGreater(len(m._overlay_items), with_distances)
        ticks["hidden"].setChecked(True)
        self.assertTrue(ticks["ground"].isEnabled() and m.overlays["hidden"])
        win.measure.setChecked(True)                                       # the board is drawn again: the unit stays
        self.assertIn(key, m.items)
        self.assertGreater(len(m._overlay_items), 0)
        m.view.right_clicked.emit()
        self.assertEqual(m._overlay_items, [])                             # nothing selected: nothing to show
        self.assertFalse(win.grab().isNull())

    def test_line_of_sight_is_a_draft_while_its_unit_moves(self):
        from command_center.deploy import sight
        from command_center.ui.tools.holomap import map_view
        win = self.win
        attackers, _ = self.place()
        m = win.maps[0]
        key = next((k for k in attackers if m.tokens[k].ranges), None)
        if key is None:
            self.skipTest("the fixture's attackers have no ranged weapon")
        cast_with = []                                                     # the points and directions of each cast
        real = map_view.cast

        def cast(outline, reach, obstacles, origins=sight.ORIGINS, directions=sight.DIRECTIONS, hidden=None):
            cast_with.append((origins, directions))
            return real(outline, reach, obstacles, origins, directions, hidden)
        map_view.cast = cast
        self.addCleanup(setattr, map_view, "cast", real)
        full, draft = (sight.ORIGINS, sight.DIRECTIONS), (sight.DRAFT_ORIGINS, sight.DRAFT_DIRECTIONS)
        self.assertGreater(full[0] * full[1], draft[0] * draft[1])
        win.overlay_ticks["sight"].setChecked(True)
        m.pick(key)
        self.assertEqual(cast_with[-1], full)                              # at rest: in full
        m.items[key].setPos(30, 22)                                        # on the move, not let go yet
        self.assertTrue(wait_until(lambda: not m._overlay_timer.isActive()))
        self.assertEqual(cast_with[-1], draft)
        self.assertTrue(m._draft)
        m.token_released()
        self.assertEqual(cast_with[-1], full)                              # let go: in full again
        self.assertFalse(m._draft)
        before = len(cast_with)
        m.token_released()                                                 # a plain click: nothing to draw again
        self.assertEqual(len(cast_with), before)

    def test_reserves(self):
        from command_center.ui.tools.holomap.map_view import (RESERVE_BOTTOM, RESERVE_TOP, TO_BOARD, TO_RESERVES,
                                                              reserve_half)
        win = self.win
        attackers, defenders = self.place()
        m = win.maps[0]
        key = next((k for k in attackers if m.tokens[k].ranges), attackers[0])
        t = m.tokens[key]
        m.move_token(key, 20, 22)
        for name in ("move", "objectives", "sight"):
            win.overlay_ticks[name].setChecked(True)
        m.pick(key)
        self.assertGreater(len(m._overlay_items), 0)
        self.assertEqual([name for name, _ in m.menu_actions(key)], [TO_RESERVES])

        m.menu_actions(key)[0][1]()                                        # as the menu's entry does
        self.assertTrue(t.reserve)
        self.assertEqual(t.board_spot, (20, 22))
        x0, x1, y0, y1 = reserve_half("attacker")
        w, h = t.box
        self.assertTrue(x0 <= t.x - w / 2 + 1e-9 and t.x + w / 2 <= x1 + 1e-9)          # in its side's half, under the board
        self.assertTrue(RESERVE_BOTTOM <= t.y - h / 2 + 1e-9 and t.y + h / 2 <= RESERVE_TOP + 1e-9)
        self.assertEqual(m.selected, key)
        self.assertEqual(m._overlay_items, [])                             # no rings, distances or line of sight from there
        self.assertEqual((m.items[key].x(), m.items[key].y()), (t.x, t.y))
        m.move_token(key, 50, 30)                                          # dragged at the board and the other half
        self.assertTrue(x0 <= t.x - w / 2 + 1e-9 and t.x + w / 2 <= x1 + 1e-9 and t.y + h / 2 <= RESERVE_TOP + 1e-9)
        m.rotate(key)                                                      # turned: still in its half
        w, h = t.box
        self.assertTrue(x0 <= t.x - w / 2 + 1e-9 and t.x + w / 2 <= x1 + 1e-9 and t.y + h / 2 <= RESERVE_TOP + 1e-9)
        self.assertNotIn(key, {k for mm in win.maps[1:] for k, tt in mm.tokens.items() if tt.reserve})      # this map only

        m.to_reserves(defenders[0])                                        # the defender's are on the right
        d = m.tokens[defenders[0]]
        self.assertGreaterEqual(d.x - d.box[0] / 2 + 1e-9, reserve_half("defender")[0])
        m.pick(attackers[1] if attackers[1] != key else attackers[0])      # from the board, a unit in reserve is not seen
        self.assertNotIn(defenders[0], m.seen)

        m.pick(key)
        self.assertEqual([name for name, _ in m.menu_actions(key)], [TO_BOARD])
        m.to_board(key)
        self.assertFalse(t.reserve)
        w, h = t.box
        self.assertTrue(w / 2 - 1e-6 <= t.x <= BOARD_W - w / 2 + 1e-6 and h / 2 - 1e-6 <= t.y <= BOARD_H - h / 2 + 1e-6)
        self.assertGreater(len(m._overlay_items), 0)                       # on the board again: its overlays too
        win.measure.setChecked(True)                                       # the board is drawn again: who is in reserve stays
        self.assertTrue(m.tokens[defenders[0]].reserve and defenders[0] in m.items)

    def test_planned_targets_reach_into_the_reserves(self):
        win = self.win
        attackers, defenders = self.place()
        rows = win.placed
        name = lambda key: rows[key].units[0].label or rows[key].units[0].name
        a, d = name(attackers[0]), name(defenders[0])
        self.ctx.army_plans.put(SavedPlan(self.selection.attacker.path.name, self.selection.defender.path.name,
                                          [PlanEntry(a, [a], PlanTarget(d, [d], 0.5, 40.0), None)], [], {}))
        m = win.maps[0]
        win.overlay_ticks["plan"].setChecked(True)
        m.pick(attackers[0])
        on_board = len(m._link_items)
        self.assertGreater(on_board, 0)
        m.to_reserves(attackers[0])                                        # the attacker in reserve: its arrow is still drawn
        self.assertEqual(len(m._link_items), on_board)
        m.to_reserves(defenders[0])                                        # and to a target in reserve
        self.assertEqual(len(m._link_items), on_board)

    def test_right_button(self):
        from PySide6.QtCore import QPoint
        attackers, _ = self.place()
        m = self.win.maps[0]
        key = attackers[0]
        m.move_token(key, 30, 22)
        m.pick(key)
        on_unit = m.view.mapFromScene(m.items[key].pos())
        self.assertEqual(m.view.token_at(on_unit), key)
        QTest.mousePress(m.view.viewport(), Qt.RightButton, pos=on_unit)   # on a unit: its menu follows, it stays selected
        self.assertEqual(m.selected, key)
        asked = []
        m.view.menu_asked.disconnect(m.token_menu)                         # the menu itself would wait for a choice
        m.view.menu_asked.connect(lambda k, at: asked.append(k))
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtWidgets import QApplication
        QApplication.sendEvent(m.view.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, on_unit,
                                                                    m.view.viewport().mapToGlobal(on_unit)))
        self.assertEqual(asked, [key])
        off = m.view.mapFromScene(1, 1)
        self.assertIsNone(m.view.token_at(off))
        QTest.mousePress(m.view.viewport(), Qt.RightButton, pos=off)       # on no unit: the selection is released
        self.assertIsNone(m.selected)
        QApplication.sendEvent(m.view.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, off, m.view.viewport().mapToGlobal(off)))
        self.assertEqual(asked, [key])                                     # and no menu

    def test_a_name_is_fitted_in_its_base(self):
        from command_center.ui.tools.holomap.map_view import ELLIPSIS, LABEL_SIZES, compact_label, fit_label
        self.assertEqual(compact_label("Intercessor Squad + Librarian"), "Intercessor + Librarian")
        name = "Meganobz + Warboss in Mega Armour"
        font, lines, height = fit_label(name, 150, 60)                     # a large base: all of it, at the largest size
        self.assertEqual((font.pointSize(), " ".join(lines)), (LABEL_SIZES[0], name))
        font, lines, _ = fit_label(name, 60, 30)                           # a smaller one: all of it still, smaller or on more lines
        self.assertEqual(" ".join(lines), name)
        self.assertTrue(font.pointSize() < LABEL_SIZES[0] or len(lines) > 1)
        font, lines, height = fit_label(name, 34, 14)                      # too small for it: what fits, then an ellipsis
        self.assertEqual(font.pointSize(), LABEL_SIZES[-1])
        self.assertTrue(lines[-1].endswith(ELLIPSIS))
        self.assertTrue(name.startswith(" ".join(lines).rstrip(ELLIPSIS).rstrip()))
        self.assertLessEqual(len(lines) * height, 2 * 14)                  # never taller than the base
        self.assertIsNone(fit_label(name, 4, 3))                           # no room for a letter
        self.assertIsNone(fit_label("", 100, 100))
        from PySide6.QtGui import QFontMetricsF
        for a, b in ((150, 60), (60, 30), (34, 14), (20, 20), (90, 12)):   # every line inside the ellipse, at its own height
            fitted = fit_label(name, a, b)
            if fitted:
                font, lines, height = fitted
                for i, line in enumerate(lines):
                    edge = abs(i - (len(lines) - 1) / 2) * height + height / 2
                    self.assertLess(edge, b)
                    self.assertLessEqual(QFontMetricsF(font).horizontalAdvance(line), 2 * a * (1 - (edge / b) ** 2) ** 0.5 + 0.5)

    def test_enemy_units_in_the_line_of_sight_glow(self):
        win = self.win
        attackers, defenders = self.place()
        m = win.maps[0]
        key = next((k for k in attackers if m.tokens[k].ranges), None)
        if key is None:
            self.skipTest("the fixture's attackers have no ranged weapon")
        reach = max(m.tokens[key].ranges)
        m.move_token(key, 10, 22)
        m.move_token(defenders[0], 10 + min(reach, 12) / 2 + 4, 22)        # next to it, nothing between: seen
        m.move_token(attackers[1], 10, 30)                                 # one of its own side, as near
        m.pick(key)
        self.assertEqual(m.seen, set())                                    # line of sight is not shown yet
        before = len(m._overlay_items)
        win.overlay_ticks["sight"].setChecked(True)
        self.assertIn(defenders[0], m.seen)
        self.assertTrue(m.seen <= set(defenders))                          # enemy units only, never its own side
        self.assertGreater(len(m._overlay_items), before + len(m.seen))
        m.pick(defenders[0])                                               # the other way round: from the defender
        self.assertTrue(m.seen <= set(attackers))
        win.overlay_ticks["sight"].setChecked(False)
        self.assertEqual(m.seen, set())

    def test_planned_targets(self):
        win = self.win
        self.assertTrue(win.plan_note.isVisibleTo(win))                    # no army plan yet: said so
        attackers, defenders = self.place()
        rows = win.placed
        name = lambda key: rows[key].units[0].label or rows[key].units[0].name
        a, d1, d2 = name(attackers[0]), name(defenders[0]), name(defenders[1])
        self.ctx.army_plans.put(SavedPlan(self.selection.attacker.path.name, self.selection.defender.path.name,
                                          [PlanEntry(a, [a], PlanTarget(d1, [d1], 0.5, 40.0), PlanTarget(d2, [d2], 0.3, 20.0))],
                                          [], {}))
        self.assertIsNotNone(win.plan)                                     # the window heard of it
        m = win.maps[0]
        self.assertEqual(sorted(m.plan_links), sorted([(attackers[0], defenders[0], "primary"),
                                                       (attackers[0], defenders[1], "secondary")]))
        self.assertFalse(win.plan_note.isVisibleTo(win))
        win.overlay_ticks["plan"].setChecked(True)
        self.assertEqual(m._link_items, [])                                # the selected unit's only, and none is
        m.pick(attackers[0])
        first = len(m._link_items)
        self.assertGreater(first, 0)
        win.overlay_ticks["plan2"].setChecked(True)
        self.assertGreater(len(m._link_items), first)
        m.view.right_clicked.emit()
        win.overlay_ticks["planall"].setChecked(True)
        self.assertGreater(len(m._link_items), first)                      # every attacker's, with no selection

    def test_score_oracle(self):
        win = self.win
        oracle = win.open_score_oracle()
        self.assertIs(win.open_score_oracle(), oracle)                     # one per Field Holomap
        self.assertTrue(oracle.isVisible())
        a, d = oracle.scores["attacker"], oracle.scores["defender"]
        cells = oracle.cells["attacker"]
        self.assertTrue(a.options)                                         # its primary mission's scoring options
        self.assertEqual(oracle.score_lbl.text(), "10 - 10")
        self.assertEqual(oracle.result_lbl.text(), "DRAW")

        cells["went_first"].setChecked(True)
        oracle.cells["defender"]["went_first"].setChecked(True)            # only one player goes first
        self.assertFalse(oracle.cells["attacker"]["went_first"].isChecked())
        self.assertTrue(d.went_first and not a.went_first)

        (i, col), _ = next(iter(cells["primary"].shown.items()))
        cells["primary"]._score(i, col, 1)
        self.assertGreater(a.primary_total, 0)
        self.assertEqual(cells["primary"].total.text(), f"{a.primary_total}/45")
        self.assertIn("ATTACKER WINS", oracle.result_lbl.text())
        oracle.names["attacker"].setText("Hugo")
        self.assertIn("HUGO WINS", oracle.result_lbl.text())

        oracle._add_secondary("attacker")
        cells = oracle.cells["attacker"]                                   # its grid was built again
        self.assertEqual(len(cells["secondary_names"]), 1)
        self.assertTrue(a.secondaries[0].name)                             # drawn among the fixture's missions
        boxes, pick = cells["secondary_boxes"][0]
        boxes[1].setCurrentText("5")
        pick(1)
        self.assertEqual(a.secondary_total, 5)
        self.assertEqual(cells["secondary_total"].text(), "5/45")
        self.assertEqual([b.isEnabled() for b in boxes], [False, True, False, False, False])   # scored: the row is closed
        oracle._remove_secondary("attacker", 0)
        self.assertEqual(a.secondary_total, 0)

        cells = oracle.cells["attacker"]
        gained = cells["cp"]["CP gained", 0]
        QTest.mouseClick(gained.layout().itemAt(2).widget(), Qt.LeftButton)       # its "+"
        self.assertEqual(a.cp_gained[0], 1)
        self.assertEqual(gained.count.text(), "1")
        self.assertEqual(cells["cp_remaining"][0].text(), str(a.cp_remaining(0)))

        oracle.import_estimate()
        self.assertTrue(oracle.import_note.text())                         # what was done, or what is missing
        self.assertFalse(oracle.grab().isNull())
        oracle.close()
        self.assertTrue(wait_until(lambda: win.oracle is None))
        self.assertIsNot(win.open_score_oracle(), oracle)                  # closed: a new sheet


if __name__ == "__main__":
    unittest.main()
