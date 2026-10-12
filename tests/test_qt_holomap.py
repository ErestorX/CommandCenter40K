"""The Qt Field Holomap and its Score Oracle, without a screen, on the test fixtures: the boards and where
they go, units put on them, dragged and turned, what is drawn for the selected one, and the score sheet."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    HAVE_QT = True
except ImportError:          # the Qt front end is optional until it has every tool (docs/qt_migration.md)
    HAVE_QT = False

from command_center.analysis.army_plans import ArmyPlanStore, PlanEntry, PlanTarget, SavedPlan
from command_center.deploy.placement import BOARD_H, BOARD_W
from command_center.lists import parse_list
from tests.helpers import FIXTURE_LIST
from tests.test_qt_auspex import wait_until
from tests.test_qt_windows import fixture_context


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class HolomapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.qt.app import App, application
        from command_center.qt.registry import Selection, discover
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
        label = m.labels[key]                                              # its label stays on the board
        self.assertTrue(0 <= label.x() <= BOARD_W and 0 <= label.y() <= BOARD_H)

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
