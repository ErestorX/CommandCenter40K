"""The Engagement Optimizer, without a screen, on the test fixtures: units and their tests, a run on a
worker thread, and the results explorer. Plans are saved in a temporary folder, never the user's."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from command_center.analysis.army_plans import ArmyPlanStore
from command_center.analysis.plan import PlanStore
from command_center.lists import parse_list
from tests.helpers import FIXTURE_LIST
from tests.test_ui_auspex import wait_until
from tests.test_ui_windows import fixture_context


class OptimizerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.ui.app import App, application
        from command_center.ui.registry import Selection, discover
        cls.tools = {t.key: t for t in discover()}
        cls.qt = application()
        cls.ctx = fixture_context()
        cls.folder = Path(tempfile.mkdtemp())
        cls.ctx._army_plans = ArmyPlanStore(cls.folder / "army_plans.json")
        cls.app = App(cls.ctx)
        cls.app.show()
        cls.selection = Selection(parse_list(FIXTURE_LIST, cls.ctx.wd), parse_list(FIXTURE_LIST, cls.ctx.wd))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        from command_center.ui.tools.optimizer.window import OptimizerWindow
        self.plans = self.folder / f"{self.id()}.json"
        self.win = OptimizerWindow(self.app, self.selection, PlanStore(self.plans))
        self.win.show()
        self.addCleanup(self.win.close)
        self.win.workers_box.setValue(1)                     # in this process: no worker processes in a test
        self.win.trials_box.setCurrentText("2,000 (fast)")

    def plan_two_units(self):
        """Two attackers and two defenders, the first attacker with a second test."""
        left, right = self.win.left, self.win.right
        for panel in (left, right):
            panel._include_all(False)
            for u in [u for u in panel.army.units if u.datasheet][:2]:
                panel.toggle_unit(u.uid)
        left.toggle_mod("rr_hit_1")
        left.add_test()
        return left, right

    def run_tests(self):
        self.win.run()
        self.assertTrue(wait_until(lambda: not self.win._running, 60))
        self.assertIn("Finished", self.win.status.text())
        return self.win.result_windows[-1]

    def test_it_is_a_tool(self):
        self.assertTrue(self.tools["optimizer"].needs_armies)

    def test_units_and_tests(self):
        win = self.win
        left, right = self.plan_two_units()
        self.assertEqual(len(left.selected_units()), 2)
        first = left.unit
        self.assertEqual(len(left.plan(first).tests), 2)                     # the one it was given, and the new one
        self.assertEqual(len(left.tests_tree.keys()), 2)
        self.assertEqual(left.units_tree.row(first.uid).text(0), "✓")
        self.assertIn("2 attacker(s) × 2 defender(s)", win.summary.text())
        self.assertTrue(win.run_btn.isEnabled())
        cases = win._n_cases
        left.add_test()                                                      # the same test again
        self.assertIn("already has that test", left.draft_label.text())
        left.delete_test(1)
        self.assertLess(win._n_cases, cases)
        left._include_all(False)
        self.assertEqual(win._n_cases, 0)
        self.assertFalse(win.run_btn.isEnabled())
        self.assertEqual(left.units_tree.row(first.uid).text(0), "")

    def test_a_value_is_typed_or_picked(self):
        left = self.win.left
        left.nb.setCurrentIndex(1)
        key = next(k for k, v in left.catalogue.items() if v.param and v.param.kind != "choice")
        choices = left.catalogue[key].param.choices
        editor = left.edit_value(key)
        self.assertIs(left.mods_tree.itemWidget(left.mods_tree.row(f"v:{key}"), 2), editor)
        editor.lineEdit().setText(choices[-1])
        QTest.keyClick(editor.lineEdit(), Qt.Key_Return)
        self.assertIsNone(left._editor)
        self.assertEqual(left.values[key], choices[-1])
        self.assertEqual(left.mods_tree.row(f"v:{key}").text(0), "✓")       # given a value: ticked for the next test
        editor = left.edit_value(key)
        editor.lineEdit().setText("not a value")
        QTest.keyClick(editor, Qt.Key_Escape)
        self.assertIsNone(left._editor)
        self.assertEqual(left.values[key], choices[-1])                       # left as it was
        self.assertFalse(left.set_value(key, "not a value"))
        left._clear_draft()
        self.assertEqual(left.mods_tree.row(f"v:{key}").text(0), "·")

    def test_weapons_are_switched_off(self):
        left = self.win.left
        loads, on = left._weapon_rows()
        if not loads:
            self.skipTest("the fixture's first unit has no weapon")
        left.toggle_weapon(0)
        self.assertNotEqual(left._weapon_rows()[1], on)

    def test_plans_are_saved_on_closing(self):
        self.plan_two_units()
        self.assertFalse(self.plans.exists())
        self.win.close()
        self.assertTrue(self.plans.exists())
        self.assertEqual(len(PlanStore(self.plans).get(self.win.left.army, "attacker", self.win.left.unit).tests), 2)

    def test_run_and_results(self):
        from command_center.ui.tools.optimizer.results import FROM, INTO, MATRIX, PLAN, TABLE
        left, right = self.plan_two_units()
        cases = self.win._n_cases
        res = self.run_tests()
        self.addCleanup(res.close)
        self.assertTrue(res.isVisible())
        self.assertEqual(len(res.rs.records), cases)
        self.assertEqual(self.win.progress.value(), cases)
        self.assertTrue(self.win.results_btn.isEnabled())
        self.assertIn(f"{cases:,} of {cases:,} tests shown", res.count_lbl.text())

        # the army plan: shown first, and saved for the other windows
        self.assertEqual(res.nb.currentIndex(), PLAN)
        self.assertEqual(len(res.plan_atts.keys()), 2)
        self.assertEqual(len(res.plan_defs.keys()), 2)
        saved = self.ctx.army_plans.get(self.selection.attacker.path, self.selection.defender.path)
        self.assertEqual(len(saved.entries), 2)
        res.plan_slider.setValue(8)
        self.assertEqual(res.weight_lbl.text(), "80% wounds · 20% points")
        self.assertTrue(wait_until(lambda: not res._plan_timer.isActive()))
        self.assertEqual(self.ctx.army_plans.get(self.selection.attacker.path, self.selection.defender.path).settings["weight"], 0.8)

        # the matrix: a click lists a pairing's tests, a right click hides them
        res.nb.setCurrentIndex(MATRIX)
        self.assertEqual((len(res.heat.rows), len(res.heat.cols)), (2, 2))
        res._cell_click(0, 1)
        self.assertEqual(res.pair_selected, (res.heat.rows[0], res.heat.cols[1]))
        bars = len(res.detail.items)
        self.assertGreater(bars, 0)
        res.detail.on_click(res.detail.items[0].key)                          # a bar: that test is hidden
        self.assertEqual(len(res.detail.items), bars - 1)
        self.assertIn("1 hidden", res.count_lbl.text())
        res._cell_hide(1, 0)
        self.assertIsNone(res.heat.values[1][0])
        self.assertTrue(res.unhide_btn.isEnabled())
        res.unhide()
        self.assertIsNotNone(res.heat.values[1][0])
        self.assertFalse(res.unhide_btn.isEnabled())

        # the rankings: a unit's best test, or every one of them
        for tab, name in ((INTO, "into"), (FROM, "from")):
            res.nb.setCurrentIndex(tab)
            pivot, shown, chart = getattr(res, f"rank_{name}")
            self.assertEqual(pivot.count(), 2)
            self.assertEqual(len(chart.items), 2)
            shown.setCurrentText("All")
            res.show_tests("All")
            self.assertGreater(len(chart.items), 2)
            shown.setCurrentText("Worst")
            res.show_tests("Worst")
            self.assertEqual(res.am, "worst")                                 # the top bar's choice, set from here
            self.assertEqual(len(chart.items), 2)
            chart.on_click(chart.items[0].key)                                # hidden: the next one takes its place
            self.assertEqual(len(chart.items), 2)
            res.unhide()

        # filters apply to every view
        res.toggle_filter("phase", "Fight")
        self.assertTrue(all(r.phase == "Shooting" for r in res.rs.visible()))
        res.toggle_filter("phase", None)                                      # the whole filter: everything back
        self.assertEqual(len(res.rs.visible()), cases)

        # the table: sorted by a heading, a row hidden by its tick
        res.nb.setCurrentIndex(TABLE)
        self.assertEqual(len(res.table.keys()), cases)
        res.sort("attacker")
        names = [res.table.topLevelItem(i).text(1) for i in range(cases)]
        self.assertEqual(names, sorted(names))
        res.sort("attacker")
        self.assertEqual([res.table.topLevelItem(i).text(1) for i in range(cases)], sorted(names, reverse=True))
        record = res.table.keys()[0]
        res.toggle_hidden(record)
        self.assertEqual(res.table.row(record).text(0), "")
        self.assertEqual(len(res.rs.visible()), cases - 1)
        for widget in (res.heat, res.detail, res.rank_into[2], res):
            self.assertFalse(widget.grab().isNull())                          # everything paints

    def test_cancel(self):
        self.plan_two_units()
        self.win.run()
        self.win.cancel()
        self.assertTrue(wait_until(lambda: not self.win._running, 60))
        self.assertIn("Cancelled", self.win.status.text())
        self.assertTrue(self.win.run_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
