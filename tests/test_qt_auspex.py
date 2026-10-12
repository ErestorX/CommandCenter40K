"""The Qt Armies Auspex, without a screen, on the test fixtures: a unit against another, simulated on a
worker thread, and what changes the simulation."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

try:
    from PySide6.QtCore import QEventLoop, QTimer
    HAVE_QT = True
except ImportError:          # the Qt front end is optional until it has every tool (docs/qt_migration.md)
    HAVE_QT = False

from command_center.core import Modifiers
from command_center.lists import parse_list
from tests.helpers import FIXTURE_LIST
from tests.test_qt_windows import fixture_context


def wait_until(done, seconds: float = 10.0) -> bool:
    """Let Qt's event loop run until done() is true. Qt's own waiting, not QTest.qWait: that one keeps
    Python's lock, and a worker thread would hardly run."""
    for _ in range(int(seconds * 50)):
        if done():
            return True
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return done()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AuspexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.qt.app import App, application
        from command_center.qt.registry import Selection, discover
        discover()
        cls.qt = application()
        cls.ctx = fixture_context()
        cls.ctx.settings.trials = 2_000
        cls.app = App(cls.ctx)
        cls.app.show()
        army = parse_list(FIXTURE_LIST, cls.ctx.wd)
        cls.selection = Selection(army, parse_list(FIXTURE_LIST, cls.ctx.wd))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.win = self.app.open_tool("auspex", self.selection)
        self.addCleanup(self.win.close)
        self.assertTrue(self.simulated())

    def simulated(self) -> bool:
        """Wait for the simulation that was asked for, and for nothing else to be asked."""
        win = self.win
        shown = lambda: not win._timer.isActive() and win.results.status.text() != "Computing…"
        return wait_until(shown)

    def again(self) -> bool:
        self.win.results.status.setText("Computing…")
        return self.simulated()

    def test_a_result_is_shown(self):
        r = self.win.results
        self.assertIn("simulated attacks", r.status.text())
        self.assertIn("→", r.title_lbl.text())
        self.assertIsNotNone(r.result)
        self.assertEqual(r.result.trials, 2_000)
        self.assertNotEqual(r.cards["dmg"][0].text(), "–")
        self.assertGreater(len(r.breakdown.keys()), 0)
        self.assertTrue(r.chart_title.text())
        self.assertFalse(r.chart.grab().isNull())

    def test_units_and_models(self):
        left = self.win.left
        self.assertIsNotNone(left.unit)
        self.assertEqual(left.units_tree.selected_key(), left.unit.uid)
        self.assertEqual(len(left.units_tree.keys()), len(left.army.units))
        self.assertGreater(len(left.models_tree.keys()), 0)
        other = next(u for u in left.army.units if u.datasheet and u.uid != left.unit.uid)
        left.units_tree.select(other.uid)
        left.on_unit()
        self.assertIs(left.unit, other)
        self.assertTrue(self.again())
        self.assertIn(other.label, self.win.results.title_lbl.text())

    def test_phase_and_weapons(self):
        win, left = self.win, self.win.left
        ranged = len(left.phase_loads())
        win.set_phase("fight")
        self.assertTrue(win.results.phase_buttons["fight"].isChecked())
        self.assertTrue(all(ld.weapon.melee for ld in left.phase_loads()))
        self.assertTrue(self.again())
        win.results.phase_buttons["shooting"].click()
        self.assertEqual(win.phase, "shooting")
        self.assertEqual(len(left.phase_loads()), ranged)
        for row in range(len(left.phase_loads())):               # every weapon switched off
            if left.checked[left.phase_loads()[row].source, left.phase_loads()[row].weapon.name]:
                left.toggle_weapon(row)
        self.assertEqual(left.selected_loads(), [])
        self.assertTrue(self.again())
        self.assertIn("No ranged weapons selected", win.results.status.text())
        self.assertIsNone(win.results.result)

    def test_modifiers(self):
        left, right = self.win.left, self.win.right
        left.checks["add_lethal_hits"].setChecked(True)
        left.fields["extra_attacks"][0].setText("+1")
        left.fields["extra_strength"][0].setText("x")             # not a number: shown as such, and ignored
        left._range_box.setEditText('12"')
        right.checks["cover"].setChecked(True)
        right.vars["feel_no_pain"]                                # a drop-down's value is read from it
        m = Modifiers()
        left.apply_mods(m)
        right.apply_mods(m)
        self.assertTrue(m.add_lethal_hits and m.cover)
        self.assertEqual((m.effective_range, m.extra_strength), (12.0, 0))
        self.assertEqual(left.fields["extra_strength"][0].property("state"), "bad")
        self.assertEqual(left.fields["extra_attacks"][0].property("state"), "")
        self.assertFalse(left._spotted.isEnabled())
        left.checks["not_visible"].setChecked(True)
        self.assertTrue(left._spotted.isEnabled())
        left._spotted.setChecked(True)
        left.checks["not_visible"].setChecked(False)
        self.assertFalse(left._spotted.isChecked())               # "Spotted" goes with a target that is not visible
        self.assertTrue(self.again())
        self.assertIn("cover", self.win.results.status.text())

    def test_allocation_order(self):
        right = self.win.right
        keys = right.alloc_tree.keys()
        self.assertEqual(keys, right.order_keys)
        if len(keys) < 2:
            self.skipTest("the fixture's defender is a single model")
        right.alloc_tree.move_row(keys[-1], 0)                    # as a drag to the top would
        self.assertEqual(right.order_keys, [keys[-1]] + keys[:-1])
        self.assertEqual(right.alloc_tree.topLevelItem(0).text(0), "1")
        right._reset_order()
        self.assertEqual(right.order_keys, keys)

    def test_swap(self):
        win = self.win
        before = (win.left.unit.label, win.right.unit.label)
        win.set_phase("fight")
        win.swap()
        self.assertEqual((win.left.role, win.right.role), ("attacker", "defender"))
        self.assertEqual((win.left.unit.label, win.right.unit.label), before[::-1])
        self.assertTrue(win.results.phase_buttons["fight"].isChecked())      # the phase stays
        self.assertTrue(self.again())
        self.assertIn("simulated attacks", win.results.status.text())

    def test_rules_windows_open(self):
        from command_center.qt.richtext import RichTextWindow
        self.win.left._show_abilities()
        shown = self.win.findChildren(RichTextWindow)
        self.assertEqual(len(shown), 1)
        self.assertIn(self.win.left.unit.label, shown[0].windowTitle())
        shown[0].close()


if __name__ == "__main__":
    unittest.main()
