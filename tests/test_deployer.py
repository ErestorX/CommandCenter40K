"""Deployer back end: mission data access, the army roster, base sizes, footprints and placement."""
import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from crunch.data.layouts import parse_layouts
from crunch.deploy import parse_base, unit_footprint
from crunch.deploy.placement import clamp, ellipse_polygon, extent, overlaps, random_spot
from crunch.deploy.roster import roster
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


class RosterTest(unittest.TestCase):
    def test_leaders_and_support_merge_into_their_unit(self):
        wd = fixture_wd()
        rows = roster(parse_list(FIXTURE_LIST, wd), wd)
        # 5 Intercessors + Captain + Apothecary; 80 + 80 + 70 pts
        r = rows[0]
        self.assertEqual((r.key, r.name, r.models, r.points),
                         ("u2", "Intercessor Squad #1 + Captain + Apothecary", 7, 230))
        self.assertEqual(rows[1].name, "Intercessor Squad #2")
        self.assertEqual(sum(r.points for r in rows), 300)
        self.assertEqual(r.footprint.models, 7)


class BasesTest(unittest.TestCase):
    def test_parse_base_sizes(self):
        mm = 1 / 25.4
        self.assertEqual((parse_base("40mm").w, parse_base("40mm").h), (40 * mm, 40 * mm))
        b = parse_base("120 x 92mm flying base")
        self.assertEqual((b.w, b.h, b.estimated), (120 * mm, 92 * mm, False))
        self.assertAlmostEqual(parse_base("28.5mm").w, 28.5 * mm)
        self.assertFalse(parse_base("32mm").estimated)
        for text in ("Use model", "", "Unique", "No official base size"):
            with self.subTest(text):
                self.assertTrue(parse_base(text, wounds=12).estimated)
        self.assertLess(parse_base("Use model", 4).w, parse_base("Use model", 16).w)   # bigger for tougher

    def test_single_model_is_its_base(self):
        f = unit_footprint([(parse_base("40mm"), 1)])
        self.assertEqual((f.w, f.h, f.models), (parse_base("40mm").w, parse_base("40mm").w, 1))

    def test_unit_ellipse_grows_with_models_and_spacing(self):
        b = parse_base("32mm")
        f5, f10 = unit_footprint([(b, 5)]), unit_footprint([(b, 10)])
        self.assertAlmostEqual((f5.w + 1) / (f5.h + 1), 1.5, places=6)       # aspect before the outer margin
        self.assertGreater(f10.w * f10.h, f5.w * f5.h)
        # the ellipse holds every base with its 1" spacing: bigger than the bases alone, packed
        self.assertGreater(3.14159 * f10.w * f10.h / 4, 10 * b.area)
        self.assertEqual(f10.description, "10 models: 10x 32mm")
        mixed = unit_footprint([(b, 4), (parse_base("40mm"), 1)])
        self.assertEqual(mixed.description, "5 models: 4x 32mm, 1x 40mm")
        self.assertTrue(unit_footprint([(parse_base("Use model", 10), 2)]).estimated)


class PlacementTest(unittest.TestCase):
    ZONE = [[0, 0], [12, 0], [12, 44], [0, 44]]              # a 12" deep strip along the left edge

    def test_random_spot_keeps_the_footprint_in_the_zone(self):
        rng = random.Random(1)
        for _ in range(50):
            x, y = random_spot([self.ZONE], 6, 4, rng)
            self.assertTrue(3 <= x <= 9 and 2 <= y <= 42, (x, y))

    def test_new_units_avoid_the_ones_already_placed(self):
        rng = random.Random(3)
        placed = []
        for _ in range(8):                          # eight 3" x 3" units fit easily in the strip
            x, y = random_spot([self.ZONE], 3, 3, rng, avoid=placed)
            self.assertFalse(any(overlaps((x, y, 3, 3), b) for b in placed))
            placed.append((x, y, 3, 3))
        # no room left clear of the others: still placed in the zone
        x, y = random_spot([self.ZONE], 11, 40, rng, avoid=placed)
        self.assertTrue(5.5 <= x <= 6.5 and 20 <= y <= 24)

    def test_too_big_for_the_zone_still_lands_on_the_board(self):
        x, y = random_spot([self.ZONE], 20, 10, random.Random(2))
        self.assertTrue(10 <= x <= 50 and 5 <= y <= 39)

    def test_turned_extent(self):
        self.assertEqual(tuple(round(v, 6) for v in extent(6, 4, 0)), (6, 4))
        self.assertEqual(tuple(round(v, 6) for v in extent(6, 4, 90)), (4, 6))
        w, h = extent(6, 4, 30)
        self.assertTrue(4 < w < 6 and 4 < h < 6)
        self.assertEqual(tuple(round(v, 6) for v in extent(3, 3, 30)), (3, 3))     # a round base doesn't change

    def test_rotation_is_clockwise_seen_from_above(self):
        # the long axis's end at +x (east) turns towards -y (south) on a y-up board
        east = ellipse_polygon(0, 0, 6, 2, 0)[0]
        turned = ellipse_polygon(0, 0, 6, 2, 30)[0]
        self.assertEqual(tuple(round(v, 6) for v in east), (3, 0))
        self.assertAlmostEqual(turned[0], 3 * 0.8660254, places=6)
        self.assertAlmostEqual(turned[1], -1.5, places=6)

    def test_clamp_bumps_into_the_edges(self):
        self.assertEqual(clamp(-5, 100, 4, 2), (2, 43))
        self.assertEqual(clamp(30, 20, 4, 2), (30, 20))
        self.assertEqual(clamp(70, -1, 1.5, 1.5), (59.25, 0.75))


if __name__ == "__main__":
    unittest.main()
