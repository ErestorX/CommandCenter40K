import tempfile
import unittest
from pathlib import Path

from command_center import config
from command_center.lists import formats, parse_list, target_for, weapon_loads
from command_center.lists.library import clean_name, name_problem, save_list, text_problem
from command_center.lists.newrecruit import split_items
from tests.helpers import FIXTURES, FIXTURE_LIST, fixture_wd


class SplitItemsTest(unittest.TestCase):
    def test_counts_points_and_combos(self):
        self.assertEqual(split_items("Bladevanes, 3x Dark Lance [5 pts]"), [("Bladevanes", 1), ("Dark Lance", 3)])
        self.assertEqual(split_items("Big gun and stubber [15 pts] (Stubber, 2x Big gun)"),
                         [("Stubber", 1), ("Big gun", 2)])


class AddListTest(unittest.TestCase):
    """A list pasted in the launcher: checked, then saved next to the others under a new name."""

    def test_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            lists = Path(tmp)
            (lists / "Drukhari.txt").write_text("x", encoding="utf-8")
            self.assertIsNone(name_problem("My new list", lists))
            self.assertIsNone(name_problem("  Drukhari 2  ", lists))
            self.assertIn("name", name_problem("   ", lists))
            self.assertIn("already", name_problem("Drukhari", lists))            # it has to be new
            self.assertIn("already", name_problem("drukhari.TXT", lists))        # whatever the case, or a typed .txt
            self.assertIn("can't contain", name_problem("a/b", lists))
            self.assertIn("can't contain", name_problem("what?", lists))
            self.assertIsNone(name_problem("Anything", lists / "not there yet"))
            self.assertEqual(clean_name("  Blood   Angels v2.txt "), "Blood Angels v2")

    def test_text_is_checked(self):
        wd = fixture_wd()
        text = FIXTURE_LIST.read_text(encoding="utf-8")
        self.assertIsNone(text_problem(text, wd))
        self.assertIn("Paste", text_problem("   \n", wd))
        self.assertIsNotNone(text_problem("just some words, not a list", wd))

    def test_saved_next_to_the_others_and_never_over_one(self):
        text = FIXTURE_LIST.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            lists = Path(tmp) / "lists"                                           # made if missing
            path = save_list("\n" + text + "\n\n", " My Marines.txt ", lists)
            self.assertEqual((path.parent, path.name), (lists, "My Marines.txt"))
            self.assertEqual(path.read_text(encoding="utf-8"), text.strip() + "\n")
            army, same = parse_list(path, fixture_wd()), parse_list(FIXTURE_LIST, fixture_wd())
            self.assertEqual((army.faction, len(army.units)), ("Space Marines", len(same.units)))    # reads back the same
            with self.assertRaises(ValueError):
                save_list("something else", "my marines", lists)
            self.assertEqual(path.read_text(encoding="utf-8"), text.strip() + "\n")       # untouched


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
        self.assertEqual(a.force_disposition, "Take and Hold")
        self.assertEqual(parse_list(FIXTURES / "lists" / "LedBy.txt", self.wd).force_disposition, "")
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
        # one group per list model line; rank-and-file first, sergeant last, then characters
        self.assertEqual([(g.label, g.count) for g in t.groups],
                         [("Intercessor", 4), ("Intercessor Sergeant", 1), ("Captain", 1), ("Apothecary", 1)])
        self.assertEqual(t.default_order(), [0, 0, 0, 0, 1, 2, 3])


class LedByReferencesTest(unittest.TestCase):
    """Newer NewRecruit exports: 'Led by: Captain[1]', 'Leading: Squad[2]', chapter names, same-name lines."""

    def setUp(self):
        self.wd = fixture_wd()
        self.army = parse_list(FIXTURES / "lists" / "LedBy.txt", self.wd)
        self.cap1, self.cap2, self.apo, self.sq1, self.sq2 = self.army.units

    def test_chapter_maps_to_faction(self):
        self.assertEqual((self.army.faction, self.army.faction_id), ("Ultramarines", "SM"))
        self.assertEqual(self.army.detachment_names, ["Gladius Task Force"])

    def test_indexed_references(self):
        self.assertEqual([u.label for u in self.army.units[:2]], ["Captain #1", "Captain #2"])
        self.assertTrue(self.army.refers_to("Captain[1]", self.cap1))
        self.assertFalse(self.army.refers_to("Captain[1]", self.cap2))
        self.assertIs(self.army.default_attached(self.sq2, self.wd), self.cap1)
        self.assertIsNone(self.army.default_attached(self.sq1, self.wd))
        self.assertIs(self.army.default_attached(self.sq1, self.wd, support=True), self.apo)

    def test_same_name_lines_stay_distinct(self):
        t = target_for(self.sq2)
        order = [t.groups[i].label for i in dict.fromkeys(t.default_order())]
        self.assertEqual(order, ["Intercessor", "Intercessor (Auspex)", "Intercessor Sergeant"])
        self.assertEqual(t.models, 5)


@unittest.skipUnless(config.find_data_dir() and any(config.LISTS_DIR.glob("*.txt")),
                     "needs downloaded Wahapedia data and the lists/ folder")
class RealDataTest(unittest.TestCase):
    def test_every_unit_in_every_list_has_a_datasheet(self):
        from command_center.data import Wahapedia
        wd = Wahapedia()
        for path in sorted(config.LISTS_DIR.glob("*.txt")):
            with self.subTest(list=path.name):
                army = parse_list(path, wd)
                self.assertTrue(army.faction_id)
                self.assertEqual(army.unmatched_units, [])


if __name__ == "__main__":
    unittest.main()
