"""The front end's windows, opened without a screen (Qt's "offscreen" platform) on the test fixtures:
the launcher, the dialog that adds a list, the update window, the Disposition Cogitator."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from command_center.context import AppContext
from command_center.data.missionbook import MissionBook
from command_center.deploy.estimates import EstimateStore
from command_center.deploy.games import GameStore
from tests.helpers import FIXTURE_DATA, FIXTURE_LIST
from tests.test_holomap import build_json_dir


def fixture_context() -> AppContext:
    """The app's context on the fixtures: their missions and layouts, Estimates and games saved in a
    temporary folder."""
    ctx = AppContext(FIXTURE_DATA)
    ctx._missions = MissionBook(build_json_dir())
    ctx._estimates = EstimateStore(Path(tempfile.mkdtemp()) / "estimates.json")
    ctx._games = GameStore(Path(tempfile.mkdtemp()))
    ctx.test_plans_path = Path(tempfile.mkdtemp()) / "test_plans.json"
    return ctx


class QtWindowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.ui.app import App, application
        from command_center.ui.registry import discover
        cls.tools = {t.key: t for t in discover()}
        cls.qt = application()
        cls.ctx = fixture_context()
        cls.app = App(cls.ctx)
        cls.app.show()

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def test_tools_are_discovered(self):
        self.assertIn("cogitator", self.tools)
        self.assertFalse(self.tools["cogitator"].needs_armies)         # opens with no list chosen

    def test_theme(self):
        from command_center.ui.theme import C, DISPLAY_FAMILY, display_family
        self.assertEqual(display_family(), DISPLAY_FAMILY)                # loaded from assets/fonts
        self.assertEqual(self.app.palette().window().color().name(), C["bg"])

    def test_demonstration_lists_are_apart_and_own_lists_can_be_deleted(self):
        import shutil

        from command_center.analysis.army_plans import PlanEntry, SavedPlan
        from command_center.lists.library import DEMO_LISTS
        from command_center.ui import launcher as launcher_module
        from command_center.ui.app import App
        from command_center.ui.launcher import DEMO_TAG
        lists = Path(tempfile.mkdtemp()) / "lists"
        lists.mkdir()
        for name in ("Zeta.txt", "Alpha.txt", *DEMO_LISTS):
            shutil.copy(FIXTURE_LIST, lists / name)
        was, launcher_module.LISTS_DIR = launcher_module.LISTS_DIR, lists      # the launcher's folder, for this test
        self.addCleanup(setattr, launcher_module, "LISTS_DIR", was)
        ctx = fixture_context()
        app = App(ctx)
        self.addCleanup(app.close)
        att, dfn = app.launcher.att, app.launcher.dfn
        box = att.listbox
        texts = [box.item(i).text() for i in range(box.count())]
        self.assertEqual(texts, ["Alpha", "Zeta", "", f"DemOrks   {DEMO_TAG}", f"TestMarines   {DEMO_TAG}"])    # the user's first
        self.assertFalse(box.item(2).flags() & Qt.ItemIsSelectable)        # the room between the two: not a list
        self.assertEqual([p.name for p in att.paths], ["Alpha.txt", "Zeta.txt", *DEMO_LISTS])
        self.assertEqual((att.selected_path.name, dfn.selected_path.name), ("Alpha.txt", "Zeta.txt"))    # chosen at first

        att.select(lists / DEMO_LISTS[0])                                  # a demonstration list: not to delete
        self.assertFalse(att.delete_btn.isEnabled())
        att.delete(ask=False)
        self.assertTrue((lists / DEMO_LISTS[0]).exists())
        att.select(FIXTURE_LIST)                                           # nor a file from elsewhere
        self.assertFalse(att.delete_btn.isEnabled())
        att.delete(ask=False)
        self.assertTrue(FIXTURE_LIST.exists())

        ctx.army_plans.put(SavedPlan("Zeta.txt", DEMO_LISTS[0], [PlanEntry("A", ["A"], None, None)], [], {}))
        ctx.games.save(DEMO_LISTS[1], "Zeta.txt", {"units": []})
        ctx.games.save(DEMO_LISTS[0], DEMO_LISTS[1], {"units": []})
        att.select(lists / "Zeta.txt")                                     # one of the user's: deleted, on both sides
        self.assertTrue(att.delete_btn.isEnabled())
        self.assertEqual(dfn.selected_path, lists / "Zeta.txt")
        bin_was, launcher_module.to_bin = launcher_module.to_bin, (lambda path: path.unlink())      # no bin in a test
        self.addCleanup(setattr, launcher_module, "to_bin", bin_was)
        att.delete(ask=False)
        self.assertFalse((lists / "Zeta.txt").exists())
        for picker in (att, dfn):
            self.assertNotIn(lists / "Zeta.txt", picker.paths)
            self.assertIsNone(picker.selected_path)
            self.assertIsNone(picker.army)
            self.assertFalse(picker.delete_btn.isEnabled())
        self.assertIsNone(app.launcher.selection)
        self.assertEqual(ctx.list_data("Zeta.txt"), {"tests": 0, "army plans": 0, "games": 0})     # what was saved for it too
        self.assertEqual(len(ctx.games.of_list(DEMO_LISTS[0])), 1)         # the others' is still there
        self.assertEqual([box.item(i).text() for i in range(box.count())][:3], ["Alpha", "SpaceMarines", ""])    # the file from elsewhere stays listed
        att.delete(ask=False)                                              # nothing selected: nothing happens
        self.assertTrue((lists / "Alpha.txt").exists())

    def test_launcher_picks_lists(self):
        launcher = self.app.launcher
        launcher.att.select(None)
        launcher.dfn.select(None)
        self.assertIsNone(launcher.selection)
        launcher.att.select(FIXTURE_LIST)
        self.assertEqual(launcher.att.selected_path, FIXTURE_LIST)
        self.assertIn("units", launcher.att.preview.text())
        self.assertIsNone(launcher.selection)                              # one side only
        launcher.dfn.select(FIXTURE_LIST)
        self.assertIsNotNone(launcher.selection)
        launcher.att.select(None)
        launcher.swap()
        self.assertEqual((launcher.att.selected_path, launcher.dfn.selected_path), (FIXTURE_LIST, None))
        launcher.att.refresh()                                             # a list from elsewhere stays listed
        self.assertEqual(launcher.att.selected_path, FIXTURE_LIST)

    def test_add_list_refuses_what_is_not_a_list(self):
        from command_center.ui.launcher import AddListDialog
        saved = []
        dialog = AddListDialog(self.app.launcher.att, self.app, "attacker", saved.append)
        dialog.text.setPlainText("not an army list")
        dialog.name.setText("Nothing")
        dialog.save()
        self.assertTrue(dialog.problem.text())
        self.assertEqual(saved, [])
        dialog.reject()

    def test_update_window_reports_and_closes(self):
        from command_center.ui import updater

        class Window(updater.UpdateWindow):
            def _work(self, target):
                self.log("fetching\nmore")
                self.changed = True
        delay, updater.DONE_MS = updater.DONE_MS, 0
        try:
            win = Window(None)
            win.exec()                                                     # comes back by itself
        finally:
            updater.DONE_MS = delay
        self.assertEqual(win.status.text(), "New data downloaded.")
        self.assertEqual(win.bar.value(), 100)

    def test_update_window_says_what_failed(self):
        from command_center.ui import updater

        class Window(updater.UpdateWindow):
            def _work(self, target):
                self.error = "no network"
        delay, updater.FAILED_MS = updater.FAILED_MS, 0
        try:
            win = Window(None)
            win.exec()
        finally:
            updater.FAILED_MS = delay
        self.assertIn("no network", win.status.text())
        self.assertIsNone(win.changed)

    def test_board_draws_a_layout(self):
        from command_center.ui.views.board import LayoutMap
        board = LayoutMap()
        board.show_territory = True
        layout = self.ctx.missions.layouts[0]
        board.set_layout(layout, show_measurements=True)
        self.assertIs(board.stack.currentWidget(), board.view)
        self.assertGreater(len(board.scene.items()), len(layout["objectives"]) * 2)
        self.assertIn(layout["id"], board.sub.text())
        board.set_layout(None, "No layouts found")
        self.assertIs(board.stack.currentWidget(), board.note)
        self.assertEqual(board.scene.items(), [])

    def test_cogitator(self):
        names = self.ctx.missions.dispositions
        size = self.app.launcher.size()
        win = self.app.open_tool("cogitator", None)
        self.assertFalse(self.app.isVisible())                             # the launcher gives way
        self.assertEqual(len(win.cells), len(names) ** 2)
        self.assertIsNotNone(win.estimate)
        first, second = win.pair
        outlined = {at for at, cell in win.cells.items() if cell.property("on")}
        self.assertEqual(outlined, {(names.index(first), names.index(second)), (names.index(second), names.index(first))})

        QTest.mouseClick(win.cells[3, 1], Qt.LeftButton)                   # below the diagonal: its mirror's Estimate
        self.assertEqual(win.pair, (names[1], names[3]))                   # Consecrate, in the fixtures
        self.assertTrue(win.cells[1, 3].property("on") and win.cells[3, 1].property("on"))
        self.assertFalse(win.cells[names.index(first), names.index(second)].property("on"))
        self.assertEqual(len(win.estimate.maps), 3)

        estimate = win.estimate
        scored = next((i for i, s in enumerate(estimate.scores[0]) if s.options), None)
        self.assertIsNotNone(scored, "the fixtures have a mission with scoring options")
        rows, score = estimate.primaries[scored], estimate.scores[0][scored]
        (i, col), show = next(iter(rows.shown.items()))
        before = score.primary_total
        rows._score(i, col, 1)
        self.assertGreater(score.primary_total, before)
        self.assertEqual(rows.total.text(), f"{score.primary_total}/45")
        self.assertTrue(self.ctx.estimates.has(*estimate.pair, 0))         # saved as it is edited
        self.assertFalse(self.ctx.estimates.has(*estimate.pair, 1))

        estimate.first_buttons.button(1).click()                           # the other Estimate: Player 2 first
        self.assertEqual(estimate.goes_first, 1)
        self.assertEqual([lb.text() for lb in estimate.turn_labels], ["goes second", "goes first"])

        win.back()
        self.assertTrue(self.app.isVisible())                              # no tool left open: the launcher is back
        self.assertEqual(self.app.open_windows, [])
        self.assertEqual(self.app.launcher.size(), size)                   # and takes the room it had


if __name__ == "__main__":
    unittest.main()
