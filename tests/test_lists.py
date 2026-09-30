import unittest

from crunch import config
from crunch.lists import formats, parse_list, target_for, weapon_loads
from crunch.lists.newrecruit import split_items
from tests.helpers import FIXTURE_LIST, fixture_wd


class SplitItemsTest(unittest.TestCase):
    def test_counts_points_and_combos(self):
        self.assertEqual(split_items("Bladevanes, 3x Dark Lance [5 pts]"), [("Bladevanes", 1), ("Dark Lance", 3)])
        self.assertEqual(split_items("Big gun and stubber [15 pts] (Stubber, 2x Big gun)"),
                         [("Stubber", 1), ("Big gun", 2)])


class NewRecruitTest(unittest.TestCase):
    def setUp(self):
        self.wd = fixture_wd()
        self.army = parse_list(FIXTURE_LIST, self.wd)

    def test_format_registered(self):
        self.assertIn("newrecruit-text", [f.key for f in formats()])

    def test_header_and_units(self):
        a = self.army
        self.assertEqual((a.faction, a.faction_id, a.points), ("Space Marines", "SM", 300))
        self.assertEqual(a.detachment_names, ["Gladius Task Force"])
        self.assertEqual([u.label for u in a.units],
                         ["Captain", "Apothecary", "Intercessor Squad #1", "Intercessor Squad #2"])
        self.assertEqual(a.unmatched_units, [])

    def test_leader_and_support_defaults(self):
        a, squad = self.army, self.army.units[2]
        self.assertEqual(a.default_attached(squad, self.wd).label, "Captain")
        self.assertEqual(a.default_attached(squad, self.wd, support=True).label, "Apothecary")
        self.assertIsNone(a.default_attached(a.units[3], self.wd))

    def test_weapon_loads_and_target(self):
        squad = self.army.units[2]
        loads = {ld.weapon.name: ld.count for ld in weapon_loads(squad)}
        self.assertEqual(loads, {"Bolt rifle": 5, "Close combat weapon": 5})
        captain = {ld.weapon.name for ld in weapon_loads(self.army.units[0])}
        self.assertEqual(captain, {"Master-crafted bolter", "Power weapon – strike", "Power weapon – sweep"})
        self.assertIn("Warlord", self.army.units[0].unmatched_gear)
        t = target_for(squad, [self.army.units[0], self.army.units[1]])
        self.assertEqual(t.models, 7)
        self.assertEqual(t.default_order()[-2:], [1, 2])     # characters last


@unittest.skipUnless(config.find_data_dir() and (config.LISTS_DIR / "Drukhari.txt").exists(),
                     "needs downloaded Wahapedia data and the lists/ folder")
class RealDataTest(unittest.TestCase):
    def test_every_unit_in_every_list_has_a_datasheet(self):
        from crunch.data import Wahapedia
        wd = Wahapedia()
        for path in sorted(config.LISTS_DIR.glob("*.txt")):
            with self.subTest(list=path.name):
                army = parse_list(path, wd)
                self.assertTrue(army.faction_id)
                self.assertEqual(army.unmatched_units, [])


if __name__ == "__main__":
    unittest.main()
