"""Deployer back end: mission data access (MissionBook) and the compact army view."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from crunch.data.layouts import parse_layouts
from crunch.data.missionbook import MissionBook
from crunch.data.missions import parse_deck
from crunch.lists import parse_list
from tests.helpers import FIXTURES, FIXTURE_LIST, fixture_wd


def build_json_dir() -> Path:
    """missions/json/ as `crunch fetch` writes it, from the test fixtures."""
    d = Path(tempfile.mkdtemp())
    deck = parse_deck((FIXTURES / "wahapedia" / "mission_deck.html").read_text(encoding="utf-8"))
    for key, rows in deck.items():
        (d / f"{key}.json").write_text(json.dumps(rows), encoding="utf-8")
    ri = FIXTURES / "rapidingress"
    data = parse_layouts((ri / "terrain-data-11e.js").read_text(encoding="utf-8"),
                         (ri / "measurements-11e.js").read_text(encoding="utf-8"))
    (d / "layouts.json").write_text(json.dumps(data), encoding="utf-8")
    return d


class MissionBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = build_json_dir()
        cls.book = MissionBook(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_dispositions(self):
        self.assertTrue(self.book.available)
        self.assertEqual(self.book.dispositions,
                         ["Take and Hold", "Purge the Foe", "Disruption", "Reconnaissance", "Priority Assets"])
        self.assertEqual(self.book.disposition("priority ASSETS"), "Priority Assets")
        self.assertIsNone(self.book.disposition("Unknown"))
        self.assertIsNone(self.book.disposition(""))

    def test_layouts_in_either_order(self):
        self.assertEqual([l["id"] for l in self.book.layouts_for("Take and Hold", "Purge the Foe")], ["PF-TH-B"])
        self.assertEqual([l["id"] for l in self.book.layouts_for("Purge the Foe", "Take and Hold")], ["PF-TH-B"])
        self.assertEqual([l["id"] for l in self.book.layouts_for("Take and Hold", "Take and Hold")], ["TH-TH-A"])
        self.assertEqual(self.book.layouts_for("Disruption", "Disruption"), [])

    def test_primary_mission_for_each_side(self):
        self.assertEqual(self.book.primary_mission("Take and Hold", "Take and Hold")["name"], "BATTLEFIELD DOMINANCE")
        self.assertEqual(self.book.primary_mission("Purge the Foe", "Reconnaissance")["name"], "CONSECRATE")
        self.assertIsNone(self.book.primary_mission("Reconnaissance", "Purge the Foe"))    # not in the fixture

    def test_mission_named_by_a_layout_only(self):
        # the fixture has no Unstoppable Force card, but the PF-TH layout names it
        m = self.book.primary_mission("Purge the Foe", "Take and Hold")
        self.assertEqual((m["name"], m["scoring"]), ("Unstoppable Force", []))

    def test_missing_data(self):
        book = MissionBook(self.dir / "nowhere")
        self.assertFalse(book.available)
        self.assertEqual((book.layouts_for("Take and Hold", "Take and Hold"), book.dispositions), ([], []))


class ArmyRowsTest(unittest.TestCase):
    def test_leaders_and_support_merge_into_their_unit(self):
        try:
            from crunch.ui.tools.deployer.side_panel import army_rows
        except ImportError:                               # no tkinter
            self.skipTest("tkinter not available")
        wd = fixture_wd()
        rows = army_rows(parse_list(FIXTURE_LIST, wd), wd)
        # 5 Intercessors + Captain + Apothecary; 80 + 80 + 70 pts
        self.assertEqual(rows[0], ("Intercessor Squad #1 + Captain + Apothecary", 7, 230))
        self.assertEqual(rows[1][0], "Intercessor Squad #2")
        self.assertEqual(sum(r[2] for r in rows), 300)


if __name__ == "__main__":
    unittest.main()
