import unittest

from crunch.core import Dice, parse_weapon_keywords, target_matches


class DiceTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(Dice.parse("3"), Dice(0, 0, 3))
        self.assertEqual(Dice.parse("D6"), Dice(1, 6, 0))
        self.assertEqual(Dice.parse("2D3"), Dice(2, 3, 0))
        self.assertEqual(Dice.parse("d6+3"), Dice(1, 6, 3))
        self.assertFalse(Dice.parse("-"))
        with self.assertRaises(ValueError):
            Dice.parse("lots")

    def test_mean_and_str(self):
        self.assertEqual(Dice.parse("D6+1").mean, 4.5)
        self.assertEqual(Dice.parse("2D3").mean, 4.0)
        self.assertEqual(str(Dice.parse("D6+2")), "D6+2")


class KeywordTest(unittest.TestCase):
    def test_common_abilities(self):
        kw = parse_weapon_keywords("anti-infantry 3+, heavy, sustained hits 1, blast, twin-linked, melta 2")
        self.assertEqual(kw.anti, [("infantry", 3)])
        self.assertTrue(kw.heavy and kw.twin_linked)
        self.assertEqual(kw.sustained_hits[0], Dice(0, 0, 1))
        self.assertEqual(kw.blast, 1)
        self.assertEqual(kw.melta, 2)

    def test_eleventh_edition_forms(self):
        kw = parse_weapon_keywords("<b>LETHAL HITS: non-MONSTER/VEHICLE</b>, blast 2, cleave 1, conversion, "
                                   "devastating wounds: infantry, rapid fire d6+3")
        self.assertEqual(kw.lethal_hits, "non-monster/vehicle")
        self.assertEqual(kw.devastating_wounds, "infantry")
        self.assertEqual((kw.blast, kw.cleave), (2, 1))
        self.assertTrue(kw.conversion)
        self.assertEqual(kw.rapid_fire, Dice(1, 6, 3))

    def test_target_qualifiers(self):
        self.assertTrue(target_matches("", {"vehicle"}))
        self.assertTrue(target_matches("infantry", {"infantry", "character"}))
        self.assertFalse(target_matches("non-monster/vehicle", {"vehicle"}))
        self.assertTrue(target_matches("non-monster/vehicle", {"infantry"}))


if __name__ == "__main__":
    unittest.main()
