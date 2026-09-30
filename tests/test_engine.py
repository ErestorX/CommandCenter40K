"""Engine behaviour, checked against hand-calculated expectations (Monte Carlo tolerance ~3%)."""
import unittest

from crunch.core import (Dice, ModelProfile, Modifiers, Target, TargetGroup, Weapon, WeaponKeywords, WeaponLoad,
                         simulate, wound_target)

BOLT = Weapon("Bolt rifle", "Ranged", '24"', Dice(0, 0, 2), 3, 4, 1, Dice(0, 0, 1), WeaponKeywords())
BOY = ModelProfile("Boy", '6"', 5, 5, None, 1)


def boyz(n=10):
    return Target("Boyz", [TargetGroup(BOY, n)], {"infantry"})


class WoundTableTest(unittest.TestCase):
    def test_table(self):
        self.assertEqual([wound_target(s, 4) for s in (8, 5, 4, 3, 2)], [2, 3, 4, 5, 6])


class ExpectationTest(unittest.TestCase):
    def test_matches_hand_calculation(self):
        # 10 bolt rifles: 20 attacks, 3+ to hit, 5+ to wound (S4 v T5), 6+ save after AP-1
        r = simulate([WeaponLoad(BOLT, 10)], boyz(), Modifiers(), trials=40_000, seed=1)
        w = r.weapons[0]
        self.assertAlmostEqual(w.attacks, 20, delta=0.01)
        self.assertAlmostEqual(w.hits, 20 * 4 / 6, delta=0.3)
        self.assertAlmostEqual(w.wounds, 20 * 4 / 6 * 2 / 6, delta=0.15)
        self.assertAlmostEqual(r.stats()["damage_mean"], 20 * 4 / 6 * 2 / 6 * 5 / 6, delta=0.12)

    def test_cover_worsens_ballistic_skill(self):
        r = simulate([WeaponLoad(BOLT, 10)], boyz(), Modifiers(cover=True), trials=40_000, seed=2)
        self.assertAlmostEqual(r.weapons[0].hits, 20 * 3 / 6, delta=0.3)

    def test_blast_adds_attacks_per_five_models(self):
        blast = Weapon("Frag", "Ranged", '24"', Dice(0, 0, 1), 3, 4, 0, Dice(0, 0, 1), WeaponKeywords(blast=1))
        r = simulate([WeaponLoad(blast, 1)], boyz(10), Modifiers(), trials=2_000, seed=3)
        self.assertAlmostEqual(r.weapons[0].attacks, 3, delta=0.01)

    def test_overkill_is_lost(self):
        big = Weapon("Lascannon", "Ranged", '48"', Dice(0, 0, 1), 2, 12, 3, Dice(0, 0, 6), WeaponKeywords())
        r = simulate([WeaponLoad(big, 5)], boyz(10), Modifiers(), trials=5_000, seed=4)
        self.assertTrue((r.damage == r.slain).all())      # 1-wound models: 1 damage per model slain


class TargetTest(unittest.TestCase):
    def test_majority_toughness(self):
        a = ModelProfile("a", "", 4, 3, None, 2)
        b = ModelProfile("b", "", 5, 3, None, 2)
        boss = ModelProfile("boss", "", 9, 2, None, 6)
        t = Target("mix", [TargetGroup(a, 2), TargetGroup(b, 3), TargetGroup(boss, 1, True)], set())
        self.assertEqual(t.toughness, 5)

    def test_default_order_puts_characters_last(self):
        t = Target("x", [TargetGroup(BOY, 1, True), TargetGroup(BOY, 2)], set())
        self.assertEqual(t.default_order(), [1, 1, 0])


class AllocationTest(unittest.TestCase):
    def setUp(self):
        self.rangers = ModelProfile("Ranger", "", 3, 4, 5, 1)       # 5+ after AP-1
        self.dominus = ModelProfile("Dominus", "", 4, 2, 5, 4)      # 3+ after AP-1
        self.gun = Weapon("Gun", "Ranged", '24"', Dice(0, 0, 2), 3, 5, 1, Dice(0, 0, 2), WeaponKeywords())

    def unit(self):
        return Target("Rangers+Dominus", [TargetGroup(self.rangers, 10), TargetGroup(self.dominus, 1, True)],
                      {"infantry"})

    def test_lowest_saves_resolved_first_protect_better_saved_character(self):
        # Failed 1s/2s are used up on the bodyguard; the character only sees the high rolls.
        r = simulate([WeaponLoad(self.gun, 25)], self.unit(), Modifiers(), trials=20_000, seed=3)
        self.assertLess(r.stats()["p_character_slain"], 0.2)

    def test_precision_targets_chosen_character(self):
        prec = Weapon("Sniper", "Ranged", '36"', Dice(0, 0, 1), 2, 5, 2, Dice(0, 0, 3),
                      WeaponKeywords(precision=True))
        t = self.unit()
        base = simulate([WeaponLoad(prec, 10)], t, Modifiers(), trials=20_000, seed=5).stats()["p_character_slain"]
        t.precision_pos = 10            # the Dominus is 11th in the default order
        aimed = simulate([WeaponLoad(prec, 10)], t, Modifiers(), trials=20_000, seed=5).stats()["p_character_slain"]
        self.assertLess(base, 0.05)
        self.assertGreater(aimed, 0.5)

    def test_precision_modifier_grants_precision(self):
        sniper = Weapon("Sniper", "Ranged", '36"', Dice(0, 0, 1), 2, 5, 2, Dice(0, 0, 3), WeaponKeywords())
        t = self.unit()
        t.precision_pos = 10
        p = lambda m: simulate([WeaponLoad(sniper, 10)], t, m, trials=20_000, seed=5).stats()["p_character_slain"]
        self.assertLess(p(Modifiers()), 0.05)
        self.assertGreater(p(Modifiers(add_precision=True)), 0.5)

    def test_custom_order_is_respected(self):
        t = self.unit()
        t.model_order = [1] + [0] * 10   # defender puts the Dominus first
        r = simulate([WeaponLoad(self.gun, 25)], t, Modifiers(), trials=10_000, seed=6)
        self.assertGreater(r.stats()["p_character_slain"], 0.5)


if __name__ == "__main__":
    unittest.main()
