"""The Qt front end's shared views, without a screen: the charts, the rich text window and what it does
to Wahapedia's HTML, the rules windows."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # before Qt starts: no screen is needed, none is used

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    HAVE_QT = True
except ImportError:          # the Qt front end is optional until it has every tool (docs/qt_migration.md)
    HAVE_QT = False

from command_center.lists import parse_list
from tests.helpers import FIXTURE_LIST, fixture_wd


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class PrepareTest(unittest.TestCase):
    """Wahapedia's HTML, made ready for the window's document."""

    def prepare(self, text):
        from command_center.qt.richtext import prepare
        return prepare(text)

    def test_images_links_and_styles_go(self):
        out = self.prepare('<a href="/x">Leader</a> <img src="a.png"> <span class="kwb" style="color:red">INFANTRY</span>')
        self.assertEqual(out, 'Leader  <span class="kwb">INFANTRY</span>')

    def test_a_broken_style_goes_too(self):
        self.assertEqual(self.prepare('<div class="BreakInsideAvoid"  style=""">x</div>'), '<div class="BreakInsideAvoid" >x</div>')

    def test_tables_keep_their_lines_wrappers_have_none(self):
        out = self.prepare('<table width="0" border="0"><tr><td><table class="t" border="1" bordercolor="#888">'
                           '<tr><td style="font-size:20px" colspan="2">A</td></tr></table></td></tr></table>')
        self.assertEqual(out.count('<table border="0"'), 1)
        self.assertEqual(out.count('<table border="1"'), 1)
        self.assertIn('<td colspan="2">A</td>', out)
        self.assertNotIn("#888", out)

    def test_empty_lines(self):
        self.assertEqual(self.prepare("can:<br><br><ul><li>a</li></ul><br>Then"), "can:<ul><li>a</li></ul>Then")
        self.assertEqual(self.prepare("a<br><br><br><br>b"), "a<br><br>b")
        self.assertEqual(self.prepare("a<br><br><div>Example</div>"), "a<br><br><div>Example</div>")


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ChartsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.qt.app import application
        cls.qt = application()

    def show(self, chart, width=900, height=420):
        chart.resize(width, height)
        chart.show()
        self.qt.processEvents()
        self.addCleanup(chart.close)
        return chart

    def test_heatmap(self):
        from command_center.qt.charts import Heatmap
        clicks, hidden = [], []
        heat = Heatmap(on_click=lambda i, j: clicks.append((i, j)), on_right_click=lambda i, j: hidden.append((i, j)))
        self.show(heat)
        self.assertIsNone(heat.cell_at(QPointF(400, 200)))                 # nothing to show yet
        heat.grab()                                                        # the empty chart paints
        rows, cols = ["Boyz", "Meganobz"], ["Intercessors", "Terminators", "Redemptor"]
        heat.set_data(rows, cols, [[1.0, None, 3.0], [4.0, 5.0, 6.0]],
                      [[[f"{r} into {c}"] for c in cols] for r in rows], caption="Wounds")
        self.qt.processEvents()
        self.assertEqual(heat.cell_at(heat.cell_centre(1, 2)), (1, 2))
        self.assertIsNone(heat.cell_at(QPointF(5, 5)))                     # the headings
        QTest.mouseClick(heat.surface, Qt.LeftButton, pos=heat.cell_centre(1, 2).toPoint())
        QTest.mouseClick(heat.surface, Qt.RightButton, pos=heat.cell_centre(0, 1).toPoint())
        self.assertEqual((clicks, hidden), ([(1, 2)], [(0, 1)]))
        self.assertEqual(heat.selected, (1, 2))                            # a right click selects nothing
        self.assertFalse(heat.grab().isNull())
        heat.set_data(rows[:1], cols, [[1.0, None, 3.0]], [[["t"]] * 3])
        self.assertIsNone(heat.selected)                                   # its row is gone

    def test_heatmap_scrolls_when_it_does_not_fit(self):
        from command_center.qt.charts import Heatmap
        heat = self.show(Heatmap(), 500, 300)
        n = 30
        heat.set_data([f"unit {i}" for i in range(n)], [f"target {j}" for j in range(n)],
                      [[float(i + j) for j in range(n)] for i in range(n)], [[["t"]] * n] * n)
        self.qt.processEvents()
        self.assertGreater(heat.surface.height(), heat.viewport().height())
        self.assertGreater(heat.surface.width(), heat.viewport().width())

    def items(self, n=6):
        from command_center.qt.charts import SLOTS, BarItem
        return [BarItem(f"k{i}", f"test {i}", 10.0 - i, 5.0 - i / 2, 14.0 - i, sublabel="vs cover", tip=[f"tip {i}"],
                        segments=[(0.5, SLOTS[0]), (0.5, SLOTS[1])] if i % 2 else []) for i in range(n)]

    def test_bar_chart(self):
        from command_center.qt.charts import SLOTS, BarChart
        clicks = []
        bars = self.show(BarChart(on_click=clicks.append))
        bars.grab()
        self.assertIsNone(bars.item_at(QPointF(100, 50)))
        bars.set_data(self.items(), legend=[("shooting", SLOTS[0]), ("fight", SLOTS[1])])
        self.qt.processEvents()
        row = QPoint(300, bars._top + 2 * bars.ROW + 5)
        self.assertEqual(bars.item_at(QPointF(row)).key, "k2")
        self.assertIsNone(bars.item_at(QPointF(300, 4)))                   # the legend
        QTest.mouseClick(bars.surface, Qt.LeftButton, pos=row)
        self.assertEqual(clicks, ["k2"])
        bars.moved(QPointF(row), QPoint(0, 0))
        self.assertEqual(bars._hovered, "k2")
        bars.left()
        self.assertIsNone(bars._hovered)
        self.assertFalse(bars.grab().isNull())
        bars.set_data(self.items(40))
        self.qt.processEvents()
        self.assertGreater(bars.surface.height(), bars.viewport().height())        # scrolls

    def test_stem_chart(self):
        from command_center.qt.charts import StemChart
        clicks = []
        stems = self.show(StemChart(on_click=clicks.append))
        stems.grab()
        stems.set_data(self.items())
        self.qt.processEvents()
        column = stems._geom()[0]
        at = QPoint(int(stems.AXIS + 3.5 * column), 100)
        self.assertEqual(stems.item_at(QPointF(at)).key, "k3")
        self.assertIsNone(stems.item_at(QPointF(10, 100)))                 # the scale
        QTest.mouseClick(stems.surface, Qt.LeftButton, pos=at)
        self.assertEqual(clicks, ["k3"])
        self.assertFalse(stems.grab().isNull())
        stems.set_data(self.items(40))
        self.qt.processEvents()
        self.assertGreater(stems.surface.width(), stems.viewport().width())        # scrolls, along the stems
        self.assertGreaterEqual(stems._geom()[0], stems.COLUMN)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class RichTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from command_center.qt.app import application
        cls.qt = application()

    def test_window_and_search(self):
        from command_center.qt.richtext import RichTextWindow
        w = RichTextWindow(None, "Rules", 700)
        self.addCleanup(w.close)
        w.h1("Orks")
        w.meta("885 pts")
        w.h2("Army rules")
        w.h3("Waaagh!", "once per battle")
        w.html('Friendly <span class="kwb">ORKS</span> units:<br><ul><li>re-roll</li><li>waaagh again</li></ul>')
        w.line("Keywords:", "INFANTRY, ORKS", keywords=True)
        w.cards([{"name": "Orks is never beaten", "cp_cost": "1", "type": "Battle Tactic", "legend": "A legend.",
                  "description": "<b>WHEN:</b> Fight phase. Waaagh!", "turn": "Either", "phase": "Fight"},
                 {"name": "Second", "cp_cost": "2", "description": "<b>WHEN:</b> any time."}])
        w.cards([])
        w.done()
        self.assertTrue(w.isVisible())
        text = w.text.toPlainText()
        for part in ("Orks", "885 pts", "Waaagh!", "once per battle", "re-roll", "INFANTRY, ORKS", "ORKS IS NEVER BEATEN",
                     "1CP", "BATTLE TACTIC", "A legend.", "Either · Fight", "SECOND", "2CP"):
            self.assertIn(part, text)
        w.q.setText("waaagh")
        w.find()
        self.assertEqual(len(w.text.extraSelections()), 3)                 # every match is marked, the card's too
        first = w.text.textCursor().selectionStart()
        w.find()
        second = w.text.textCursor().selectionStart()
        self.assertGreater(second, first)                                  # and the search moves on
        w.find()
        w.find()
        self.assertEqual(w.text.textCursor().selectionStart(), first)      # after the last, the first again
        w.q.setText("nothing like it")
        w.find()
        self.assertEqual(w.text.extraSelections(), [])

    def test_rules_windows(self):
        from command_center.data.rules import RulesBook
        from command_center.qt.views.rules import show_army_rules, show_unit_abilities
        wd = fixture_wd()
        army, book = parse_list(FIXTURE_LIST, wd), RulesBook(wd)
        rules = show_army_rules(None, book, army)
        self.addCleanup(rules.close)
        self.assertIn(army.faction, rules.windowTitle())
        self.assertIn("Army rules", rules.text.toPlainText())
        units = [u for u in army.units if u.datasheet][:2]
        abilities = show_unit_abilities(None, book, units)
        self.addCleanup(abilities.close)
        text = abilities.text.toPlainText()
        for u in units:
            self.assertIn(u.label, text)
        self.assertIn("Keywords:", text)


if __name__ == "__main__":
    unittest.main()
