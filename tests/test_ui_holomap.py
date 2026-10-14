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
from command_center.deploy.games import GameStore
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
        cls.selection = Selection(parse_list(FIXTURE_LIST, cls.ctx.armies), parse_list(FIXTURE_LIST, cls.ctx.armies))

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def setUp(self):
        self.ctx._games = GameStore(Path(tempfile.mkdtemp()))              # each test its own game: none saved before it
        self.win = self.app.open_tool("holomap", self.selection)
        self.win.setWindowState(Qt.WindowNoState)
        self.win.resize(1500, 900)
        self.addCleanup(self.shut, self.win)
        self.assertTrue(wait_until(lambda: not self.win._arrange_timer.isActive()))
        self.qt.processEvents()

    @staticmethod
    def shut(win):
        """Close a window, if it is still there (a test may have closed it to open it again)."""
        try:
            win.close()
        except RuntimeError:
            pass

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
        m.rotate(key, 45)
        m.rotate(key, -15)                                                 # and back a little, the other way
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
        self.assertEqual(m.menu_actions(key)[0].name, TO_RESERVES)

        m.menu_actions(key)[0].do()                                        # as the menu's entry does
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
        m.rotate(key, 45)                                                  # turned: still in its half
        w, h = t.box
        self.assertTrue(x0 <= t.x - w / 2 + 1e-9 and t.x + w / 2 <= x1 + 1e-9 and t.y + h / 2 <= RESERVE_TOP + 1e-9)
        self.assertNotIn(key, {k for mm in win.maps[1:] for k, tt in mm.tokens.items() if tt.reserve})      # this map only

        m.to_reserves(defenders[0])                                        # the defender's are on the right
        d = m.tokens[defenders[0]]
        self.assertGreaterEqual(d.x - d.box[0] / 2 + 1e-9, reserve_half("defender")[0])
        m.pick(attackers[1] if attackers[1] != key else attackers[0])      # from the board, a unit in reserve is not seen
        self.assertNotIn(defenders[0], m.seen)

        m.pick(key)
        self.assertEqual(m.menu_actions(key)[0].name, TO_BOARD)
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

    def test_a_unit_is_turned_from_its_menu(self):
        from command_center.ui.tools.holomap.map_view import ROTATE
        attackers, _ = self.place()
        m, key = self.win.maps[0], attackers[0]
        t = m.tokens[key]
        m.move_token(key, 30, 22)
        entries = m.menu_actions(key)
        names = [e.name for e in entries]
        at = names.index(ROTATE)
        self.assertIsNone(entries[at].do)                                  # a heading: nothing to choose
        self.assertEqual(names[at + 1:at + 5], ["↻  15°", "↻  45°", "↺  15°", "↺  45°"])
        turns = [e.do for e in entries[at + 1:at + 5]]
        turns[0]()
        self.assertEqual(t.angle, 15)                                      # clockwise
        turns[1]()
        self.assertEqual(t.angle, 60)
        turns[2]()
        self.assertEqual(t.angle, 45)                                      # counter-clockwise
        turns[3]()
        turns[3]()
        self.assertEqual(t.angle, 315)
        self.assertEqual(m.selected, None)                                 # turning selects nothing by itself
        at_unit = m.view.mapFromScene(m.items[key].pos())                  # a double click no longer turns it
        QTest.mouseDClick(m.view.viewport(), Qt.LeftButton, pos=at_unit)
        self.assertEqual(t.angle, 315)
        m.to_reserves(key)                                                 # in reserve too
        self.assertEqual([e.name for e in m.menu_actions(key)][at + 1:at + 5], names[at + 1:at + 5])

    def test_formations(self):
        from command_center.deploy.bases import COMPACT, FORMATIONS, LINE, SPACED, SPREAD, TUBE
        from command_center.ui.tools.holomap.map_view import FORMATION
        attackers, _ = self.place(4)
        m = self.win.maps[0]
        key = next((k for k in attackers if m.tokens[k].footprint.models > 1), None)
        if key is None:
            self.skipTest("the fixture's attackers are single models")
        t = m.tokens[key]
        m.move_token(key, 30, 22)
        entries = m.menu_actions(key)
        at = [e.name for e in entries].index(FORMATION)
        self.assertIsNone(entries[at].do)
        choices = entries[at + 1:at + 5]
        self.assertEqual([e.name for e in choices], ["Compact", '1" space', "Max spread", "Line spread"])
        self.assertEqual([e.ticked for e in choices], [False, True, False, False])     # as it starts: 1" apart
        spaced = (t.footprint.w, t.footprint.h)
        area = lambda: t.footprint.w * t.footprint.h

        choices[0].do()                                                    # Compact: smaller
        self.assertEqual(t.formation, COMPACT)
        self.assertLess(t.footprint.w, spaced[0])
        self.assertEqual([e.ticked for e in m.menu_actions(key)[at + 1:at + 5]], [True, False, False, False])
        self.assertEqual((t.x, t.y), (30, 22))                             # where it stood
        compact = area()
        m.set_formation(key, SPREAD)                                       # Max spread: larger than 1" apart
        self.assertGreater(area(), spaced[0] * spaced[1])
        self.assertGreater(area(), compact)
        m.set_formation(key, LINE)                                         # Line spread: a tube
        self.assertEqual(t.footprint.shape, TUBE)
        self.assertGreater(t.footprint.w, t.footprint.h)
        self.assertEqual(len(m.items[key].polygon()), 36)
        m.describe(t)
        self.assertIn("line spread", m.sub.text())
        m.move_token(key, 500, 22)                                         # a tube stops at the edges as an ellipse does
        self.assertAlmostEqual(t.x, BOARD_W - t.box[0] / 2)
        m.rotate(key, 45)
        w, h = t.box
        self.assertTrue(w / 2 - 1e-6 <= t.x <= BOARD_W - w / 2 + 1e-6 and h / 2 - 1e-6 <= t.y <= BOARD_H - h / 2 + 1e-6)
        for name in ("move", "objectives", "sight"):                       # what is drawn for it follows its shape
            self.win.overlay_ticks[name].setChecked(True)
        m.pick(key)
        self.assertGreater(len(m._overlay_items), 0)
        self.assertFalse(m.grab().isNull())
        m.set_formation(key, SPACED)                                       # back as it started
        self.assertEqual((t.footprint.w, t.footprint.h), spaced)
        m.set_formation(key, "no such formation")
        self.assertEqual(t.formation, SPACED)
        self.assertEqual(self.win.maps[1].tokens[key].formation, SPACED)   # each board its own
        self.assertEqual(set(FORMATIONS), {COMPACT, SPACED, SPREAD, LINE})

        lone = next((k for k in m.tokens if m.tokens[k].footprint.models == 1), None)
        if lone:                                                           # a lone model has no formation to choose
            self.assertNotIn(FORMATION, [e.name for e in m.menu_actions(lone)])

    def test_a_unit_loses_models_and_is_destroyed(self):
        from command_center.deploy.bases import unit_footprint
        from command_center.ui.tools.holomap.map_view import (ADD_MODEL, DESTROYED, FORMATION, FULL_STRENGTH, GONE, LOSE_MODEL,
                                                              TOKEN, UNIT)
        attackers, _ = self.place(4)
        m = self.win.maps[0]
        key = next((k for k in attackers if m.tokens[k].footprint.models > 2), None)
        if key is None:
            self.skipTest("the fixture's attackers have two models at most")
        t, item = m.tokens[key], m.items[key]
        m.move_token(key, 30, 22)
        started, full = t.strength, (t.footprint.w, t.footprint.h)
        self.assertEqual((t.models, t.lost), (started, 0))

        def unit_entries():
            entries = m.menu_actions(key)
            at = [e.name for e in entries].index(UNIT)
            self.assertEqual([e.name for e in entries[at + 1:]], [LOSE_MODEL, ADD_MODEL, FULL_STRENGTH, DESTROYED])
            return entries[at + 1:]
        lose, add, full_strength, destroy = unit_entries()
        self.assertEqual((lose.enabled, add.enabled, full_strength.enabled, destroy.enabled),
                         (True, False, False, True))                       # at full strength: none to give back
        self.assertIsNone(item._count)

        lose.do()                                                          # one model fewer: a smaller token, its count above
        self.assertEqual((t.models, t.footprint.models), (started - 1, started - 1))
        self.assertLess(t.footprint.w * t.footprint.h, full[0] * full[1])
        self.assertEqual(item._count.text, f"{started - 1}/{started}")
        self.assertIs(item._count.parentItem(), item)
        self.assertEqual((t.x, t.y), (30, 22))                             # where it stood
        self.assertTrue(unit_entries()[1].enabled)
        self.assertEqual(t.footprint, unit_footprint(t.bases_left(), t.formation))
        add = unit_entries()[1]
        add.do()                                                           # and back: as it started
        self.assertEqual((t.models, (t.footprint.w, t.footprint.h)), (started, full))
        self.assertIsNone(item._count)
        m.add_model(key)                                                   # never more than it started with
        self.assertEqual(t.models, started)

        for _ in range(started - 1):                                       # down to its last model
            m.lose_model(key)
        self.assertEqual((t.models, t.destroyed), (1, False))
        self.assertNotIn(FORMATION, [e.name for e in m.menu_actions(key)])     # one model: no formation to choose
        m.lose_model(key)                                                  # its last one: destroyed
        self.assertTrue(t.destroyed and t.reserve)                         # grey, and off to the reserves
        self.assertEqual((t.models, item._count.text), (0, f"0/{started}"))
        self.assertEqual(item.brush().color().name(), GONE[0])
        self.assertLess(item.brush().color().alphaF(), 0.3)
        lose, add, full_strength, destroy = unit_entries()
        self.assertEqual((lose.enabled, add.enabled, full_strength.enabled, destroy.enabled), (False, True, True, False))
        m.to_board(key)                                                    # it can be put back on the board, still grey
        self.assertTrue(t.destroyed and not t.reserve)
        self.win.overlay_ticks["move"].setChecked(True)
        m.pick(key)
        self.assertEqual(m._overlay_items, [])                             # nothing is measured from it
        m.add_model(key)                                                   # a model back: its colour too
        self.assertEqual((t.destroyed, t.models), (False, 1))
        self.assertEqual(item.brush().color().name(), TOKEN[t.role][0])
        self.assertEqual(item._count.text, f"1/{started}")
        self.assertGreater(len(m._overlay_items), 0)

        for _ in range(started):
            m.add_model(key)
        self.assertEqual((t.models, (t.footprint.w, t.footprint.h)), (started, full))
        unit_entries()[3].do()                                             # Destroyed, straight from full strength
        self.assertTrue(t.destroyed and t.reserve and t.models == 0)
        self.assertEqual((t.footprint.w, t.footprint.h), full)             # it keeps the size it had
        unit_entries()[2].do()                                             # Full strength: every model back at once
        self.assertEqual((t.models, t.destroyed, t.reserve), (started, False, True))       # where it is: still in reserve
        self.assertEqual(item.brush().color().name(), TOKEN[t.role][0])
        self.assertIsNone(item._count)
        m.to_board(key)
        for _ in range(3):
            m.lose_model(key)
        m.restore(key)                                                     # and from a few models down
        self.assertEqual((t.models, (t.footprint.w, t.footprint.h)), (started, full))
        m.restore(key)                                                     # nothing to give back: nothing happens
        self.assertEqual(t.models, started)
        self.assertEqual(self.win.maps[1].tokens[key].models, started)     # each board its own

    def reopen(self):
        """Close the Field Holomap and open it again on the same two lists, as another run of the app would."""
        self.win.close()
        self.win = self.app.open_tool("holomap", self.selection)
        self.win.setWindowState(Qt.WindowNoState)
        self.win.resize(1500, 900)
        self.addCleanup(self.shut, self.win)
        self.assertTrue(wait_until(lambda: not self.win._arrange_timer.isActive()))
        return self.win

    def test_the_game_is_kept(self):
        win = self.win
        path = self.ctx.games.path(self.selection.attacker.path, self.selection.defender.path)
        self.assertFalse(path.exists())                                    # nothing to keep yet
        attackers, defenders = self.place()
        m = win.maps[0]
        moved, turned, reserve, gone = attackers[0], attackers[1], defenders[0], defenders[1]
        big = next((k for k in attackers + defenders if m.tokens[k].strength > 2), None)
        m.move_token(moved, 31.5, 20.25)
        m.rotate(turned, 45)
        m.move_token(reserve, 12, 30)
        m.to_reserves(reserve)
        if big:
            m.set_formation(big, "line")
            m.lose_model(big)
        m.destroy(gone)
        for name in ("sight", "move"):                                     # ways of looking at the board: not kept
            win.overlay_ticks[name].setChecked(True)
        win.measure.setChecked(True)
        m.pick(moved)
        win.shown[2].setChecked(False)
        self.assertTrue(wait_until(lambda: not win._save_timer.isActive() and path.exists()))     # saved as it changes
        was = {k: (round(t.x, 3), round(t.y, 3), t.angle, t.reserve, t.formation, t.lost, t.destroyed,
                   round(t.footprint.w, 6), round(t.footprint.h, 6), t.footprint.shape) for k, t in m.tokens.items()}
        others = [(k, round(t.x, 3), round(t.y, 3)) for k, t in win.maps[1].tokens.items()] if win.maps[1].layout_data else None

        win = self.reopen()
        m = win.maps[0]
        self.assertEqual(set(win.placed), set(attackers + defenders))      # the same units on the maps, ticked in the roster
        for role, keys in (("attacker", attackers), ("defender", defenders)):
            for key in keys:
                self.assertEqual(win.side.trees[role].row(key.split(":")[1]).text(0), "✓")
        now = {k: (round(t.x, 3), round(t.y, 3), t.angle, t.reserve, t.formation, t.lost, t.destroyed,
                   round(t.footprint.w, 6), round(t.footprint.h, 6), t.footprint.shape) for k, t in m.tokens.items()}
        self.assertEqual(now, was)                                         # each where it stood, and as it was
        self.assertEqual((m.tokens[moved].x, m.tokens[moved].y, m.tokens[turned].angle), (31.5, 20.25, 45))
        self.assertTrue(m.tokens[reserve].reserve and m.tokens[reserve].board_spot == (12.0, 30.0))
        self.assertTrue(m.tokens[gone].destroyed and m.tokens[gone].reserve)
        self.assertEqual((m.items[moved].x(), m.items[moved].y()), (31.5, 20.25))       # and drawn there
        if big:
            self.assertEqual((m.tokens[big].formation, m.tokens[big].lost), ("line", 1))
            self.assertIsNotNone(m.items[big]._count)
        if others is not None:                                             # each layout its own places
            self.assertEqual([(k, round(t.x, 3), round(t.y, 3)) for k, t in win.maps[1].tokens.items()], others)
        self.assertEqual([tick.isChecked() for tick in win.shown], [True, True, False])
        self.assertFalse(win.maps[2].isVisible())
        self.assertFalse(win.measure.isChecked() or win.overlay_ticks["sight"].isChecked())     # not kept
        self.assertIsNone(win.selected)
        self.assertFalse(win._save_timer.isActive())                       # putting it back is not a change to save

        m.to_board(reserve)                                                # back where it stood before the reserves
        self.assertEqual((m.tokens[reserve].x, m.tokens[reserve].y), (12.0, 30.0))
        win.side.toggle("attacker", moved.split(":")[1])                   # a unit taken off the maps stays off
        win = self.reopen()
        self.assertNotIn(moved, win.placed)
        self.assertEqual(win.side.trees["attacker"].row(moved.split(":")[1]).text(0), "")
        self.assertFalse(win.maps[0].tokens[reserve].reserve)

    def test_the_score_sheet_is_kept(self):
        win = self.win
        oracle = win.open_score_oracle()
        a = oracle.scores["attacker"]
        oracle.names["attacker"].setText("Hugo")
        oracle.cells["defender"]["went_first"].setChecked(True)
        oracle.cells["attacker"]["battle_ready"].setChecked(False)
        (i, col), _ = next(iter(oracle.cells["attacker"]["primary"].shown.items()))
        oracle.cells["attacker"]["primary"]._score(i, col, 1)
        oracle._add_secondary("attacker")
        boxes, pick = oracle.cells["attacker"]["secondary_boxes"][0]
        boxes[1].setCurrentText("4")
        pick(1)
        QTest.mouseClick(oracle.cells["attacker"]["cp"]["CP gained", 0].layout().itemAt(2).widget(), Qt.LeftButton)
        sheet = (a.primary_total, a.secondary_total, a.secondaries[0].name, list(a.cp_gained), a.total, oracle.score_lbl.text())
        self.assertGreater(a.primary_total, 0)

        oracle.close()                                                     # closed and opened again: the same sheet
        self.assertTrue(wait_until(lambda: win.oracle is None))
        oracle = win.open_score_oracle()
        a, d = oracle.scores["attacker"], oracle.scores["defender"]
        self.assertEqual((a.primary_total, a.secondary_total, a.secondaries[0].name, list(a.cp_gained), a.total,
                          oracle.score_lbl.text()), sheet)
        self.assertEqual((a.name, oracle.names["attacker"].text(), a.battle_ready, d.went_first), ("Hugo", "Hugo", False, True))
        self.assertTrue(oracle.cells["defender"]["went_first"].isChecked())
        self.assertFalse(oracle.cells["attacker"]["battle_ready"].isChecked())
        self.assertEqual(oracle.cells["attacker"]["cp"]["CP gained", 0].count.text(), "1")

        win = self.reopen()                                                # and with the whole window closed in between
        oracle = win.open_score_oracle()
        a = oracle.scores["attacker"]
        self.assertEqual((a.primary_total, a.secondary_total, a.secondaries[0].name, list(a.cp_gained), a.total,
                          oracle.score_lbl.text()), sheet)
        self.assertIn("HUGO", oracle.result_lbl.text() + oracle.names["attacker"].text().upper())

        oracle.reset(ask=False)                                            # from nothing again; the names stay
        a = oracle.scores["attacker"]
        self.assertEqual((a.total - (10 if a.battle_ready else 0), a.secondaries, a.name), (0, [], "Hugo"))
        win = self.reopen()
        self.assertEqual(win.open_score_oracle().scores["attacker"].secondaries, [])

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
