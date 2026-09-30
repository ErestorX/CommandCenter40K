"""Modifier fields: re-roll variants, free-form A/AP/D, defender T/Sv/AP changes."""
import unittest

from crunch.core import (Dice, DiceMod, ModelProfile, Modifiers, Target, TargetGroup, Weapon, WeaponKeywords,
                         WeaponLoad, simulate)

TROOP = ModelProfile("Troop", '6"', 4, 4, None, 1)


def target(profile=TROOP, n=10):
    return Target("t", [TargetGroup(profile, n)], {"infantry"})


def gun(A=1, skill=4, S=4, AP=0, D=1, **kw):
    return Weapon("gun", "Ranged", '24"', Dice.parse(A), skill, S, AP, Dice.parse(D), WeaponKeywords(**kw))


def run(weapon, mods, n=10, tgt=None, seed=1):
    return simulate([WeaponLoad(weapon, n)], tgt or target(), mods, trials=40_000, seed=seed)


class DiceModTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(DiceMod.parse("").mean, 0)
        self.assertEqual(DiceMod.parse("+1").mean, 1)
        self.assertEqual(DiceMod.parse("-1").mean, -1)
        self.assertEqual(DiceMod.parse("D3").mean, 2)
        self.assertEqual(DiceMod.parse("-D3").mean, -2)
        self.assertEqual(str(DiceMod.parse("d6+1")), "+D6+1")
        with self.assertRaises(ValueError):
            DiceMod.parse("+x")


class RerollTest(unittest.TestCase):
    def hits(self, reroll):
        return run(gun(), Modifiers(reroll_hits=reroll)).weapons[0].hits / 10

    def test_variants(self):
        self.assertAlmostEqual(self.hits("none"), 3 / 6, delta=0.01)
        self.assertAlmostEqual(self.hits("ones"), 3 / 6 + 1 / 6 * 3 / 6, delta=0.01)
        self.assertAlmostEqual(self.hits("ones_twos"), 3 / 6 + 2 / 6 * 3 / 6, delta=0.01)
        self.assertAlmostEqual(self.hits("fails"), 3 / 6 + 3 / 6 * 3 / 6, delta=0.01)

    def test_ones_twos_never_rerolls_a_success(self):
        # BS2+: a 2 already hits, so only 1s are re-rolled
        r = run(gun(skill=2), Modifiers(reroll_hits="ones_twos")).weapons[0].hits / 10
        self.assertAlmostEqual(r, 5 / 6 + 1 / 6 * 5 / 6, delta=0.01)


class FreeFieldTest(unittest.TestCase):
    def test_extra_attacks(self):
        self.assertAlmostEqual(run(gun(A=2), Modifiers(extra_attacks=DiceMod.parse("+1"))).weapons[0].attacks, 30,
                               delta=0.01)
        self.assertAlmostEqual(run(gun(A=2), Modifiers(extra_attacks=DiceMod.parse("D3"))).weapons[0].attacks, 40,
                               delta=0.2)
        # Attacks can't drop below 1 per model
        self.assertAlmostEqual(run(gun(A=1), Modifiers(extra_attacks=DiceMod.parse("-1"))).weapons[0].attacks, 10,
                               delta=0.01)

    def test_extra_damage(self):
        big = ModelProfile("Big", "", 4, 7, None, 20)          # no save, lots of wounds: damage = sum of D
        base = run(gun(skill=2), Modifiers(), n=1, tgt=target(big, 1)).stats()["damage_mean"]
        more = run(gun(skill=2), Modifiers(extra_damage=DiceMod.parse("+D3")), n=1,
                   tgt=target(big, 1)).stats()["damage_mean"]
        self.assertAlmostEqual(more / base, 3.0, delta=0.1)     # D1 -> 1 + D3 (mean 3)

    def test_ap_attacker_and_defender(self):
        def unsaved(**m):
            w = run(gun(skill=2, S=8, AP=1), Modifiers(**m)).weapons[0]
            return w.unsaved / w.wounds
        self.assertAlmostEqual(unsaved(), 4 / 6, delta=0.01)                      # 4+ save, AP-1 -> saves on 5+
        self.assertAlmostEqual(unsaved(extra_ap=1), 5 / 6, delta=0.01)            # AP-2 -> saves on 6+
        self.assertAlmostEqual(unsaved(ap_mod=-1), 3 / 6, delta=0.01)             # AP-1 worsened to AP0 -> 4+
        self.assertAlmostEqual(unsaved(ap_mod=-2), 3 / 6, delta=0.01)             # can't go below AP0

    def test_defender_toughness_and_save(self):
        def wound_rate(**m):
            w = run(gun(skill=2, S=4), Modifiers(**m)).weapons[0]
            return w.wounds / w.hits
        self.assertAlmostEqual(wound_rate(), 3 / 6, delta=0.01)                   # S4 v T4
        self.assertAlmostEqual(wound_rate(toughness_mod=1), 2 / 6, delta=0.01)    # S4 v T5
        w = run(gun(skill=2, S=8), Modifiers(save_char_mod=1)).weapons[0]
        self.assertAlmostEqual(w.unsaved / w.wounds, 2 / 6, delta=0.01)           # 4+ improved to 3+


class SustainedHitsTest(unittest.TestCase):
    def test_keeps_the_bigger_sustained_hits(self):
        def hits_per_attack(own=None, extra=""):
            w = gun(sustained_hits=own) if own else gun()                    # BS4+: 3/6 hit, 1/6 crit
            return run(w, Modifiers(add_sustained_hits=Dice.parse(extra))).weapons[0].hits / 10
        cases = [
            ((Dice.parse("2"), ""), "", 5 / 6),         # own Sustained 2
            ((Dice.parse("2"), ""), "1", 5 / 6),        # own 2 beats added 1 (not 2 + 1)
            ((Dice.parse("2"), ""), "3", 1),            # added 3 beats own 2
            (None, "D3", 5 / 6),                        # added only
            ((Dice.parse("3"), "vehicle"), "1", 4 / 6), # own doesn't apply to infantry: added 1
        ]
        for own, extra, expected in cases:
            with self.subTest(own=own, extra=extra):
                self.assertAlmostEqual(hits_per_attack(own, extra), expected, delta=0.01)


class FeelNoPainTest(unittest.TestCase):
    def test_fnp_restricted_to_psychic_or_mortal_wounds(self):
        big = target(ModelProfile("Big", "", 4, 7, None, 40), 1)            # no save: damage = wounds
        normal, psychic = gun(skill=2, S=8), gun(skill=2, S=8, psychic=True)
        mortal = gun(skill=2, S=8, devastating_wounds="")                    # with crit wounds on 2+: all mortal

        def kept(weapon, against, **m):
            dmg = lambda mods: run(weapon, mods, tgt=big).stats()["damage_mean"]
            return dmg(Modifiers(feel_no_pain=4, fnp_against=against, **m)) / dmg(Modifiers(**m))
        cases = [
            (normal, "all", {}, 0.5), (normal, "psychic", {}, 1), (normal, "mortal", {}, 1),
            (normal, "psychic_mortal", {}, 1),
            (psychic, "psychic", {}, 0.5), (psychic, "mortal", {}, 1), (psychic, "psychic_mortal", {}, 0.5),
            (mortal, "mortal", {"crit_wound_on": 2}, 0.5), (mortal, "psychic", {"crit_wound_on": 2}, 1),
            (mortal, "psychic_mortal", {"crit_wound_on": 2}, 0.5),
        ]
        for weapon, against, m, expected in cases:
            with self.subTest(weapon=weapon.keywords.tags(), against=against):
                self.assertAlmostEqual(kept(weapon, against, **m), expected, delta=0.03)


class TagsTest(unittest.TestCase):
    def test_tags_show_changes_only(self):
        m = Modifiers(extra_damage=DiceMod.parse("+D3"), reroll_hits="ones_twos")
        self.assertEqual(sorted(m.tags()), ["extra_damage=+D3", "reroll_hits=ones_twos"])
        self.assertEqual(Modifiers().tags(), [])


if __name__ == "__main__":
    unittest.main()


class SituationTest(unittest.TestCase):
    def hit_rate(self, weapon=None, **m):
        return run(weapon or gun(), Modifiers(**m)).weapons[0].hits / 10

    def test_plunging_fire_improves_bs(self):
        self.assertAlmostEqual(self.hit_rate(plunging_fire=True), 4 / 6, delta=0.01)              # 4+ -> 3+
        self.assertAlmostEqual(self.hit_rate(plunging_fire=True, cover=True), 3 / 6, delta=0.01)  # cancel out
        self.assertAlmostEqual(self.hit_rate(gun(skill=2), plunging_fire=True), 5 / 6, delta=0.01)  # 2+ is the cap

    def test_heavy_is_a_hit_roll_modifier(self):
        heavy = gun(heavy=True)
        self.assertAlmostEqual(self.hit_rate(heavy, stationary=True), 4 / 6, delta=0.01)
        self.assertAlmostEqual(self.hit_rate(heavy, stationary=True, plunging_fire=True), 5 / 6, delta=0.01)
        self.assertAlmostEqual(self.hit_rate(stationary=True), 3 / 6, delta=0.01)   # no [HEAVY]: no bonus

    def test_indirect_fire_unspotted_only_sixes(self):
        indirect = gun(skill=2, indirect_fire=True)
        for m in ({}, {"hit_mod": 1}, {"crit_hit_on": 5}, {"reroll_hits": "fails"}, {"plunging_fire": True}):
            with self.subTest(**m):
                self.assertAlmostEqual(self.hit_rate(indirect, not_visible=True, **m), 1 / 6, delta=0.01)
        self.assertAlmostEqual(self.hit_rate(indirect), 5 / 6, delta=0.01)          # visible: normal BS2+

    def test_indirect_fire_spotted_fixed_four_plus(self):
        indirect = gun(skill=2, indirect_fire=True)
        for m in ({}, {"hit_mod": -1}, {"hit_mod": 1}, {"cover": True}):
            with self.subTest(**m):
                self.assertAlmostEqual(self.hit_rate(indirect, not_visible=True, spotted=True, **m), 3 / 6,
                                       delta=0.01)

    def test_strength_modifier(self):
        def wound_rate(**m):
            w = run(gun(skill=2, S=4), Modifiers(**m)).weapons[0]
            return w.wounds / w.hits
        self.assertAlmostEqual(wound_rate(extra_strength=1), 4 / 6, delta=0.01)    # S5 v T4
        self.assertAlmostEqual(wound_rate(extra_strength=4), 5 / 6, delta=0.01)    # S8 v T4
        self.assertAlmostEqual(wound_rate(extra_strength=-1), 2 / 6, delta=0.01)   # S3 v T4 -> 5+
        self.assertAlmostEqual(wound_rate(extra_strength=-2), 1 / 6, delta=0.01)   # S2 v T4 (half) -> 6+

    def test_wound_mod_depending_on_strength_vs_toughness(self):
        def wound_rate(S, **m):
            w = run(gun(skill=2, S=S), Modifiers(**m)).weapons[0]      # target is T4
            return w.wounds / w.hits
        cases = [
            # defender: -1 to be wounded if S > T / S >= T
            (5, {"wound_minus_if_stronger": "gt"}, 3 / 6),     # S5 v T4: 3+ -> 4+
            (4, {"wound_minus_if_stronger": "gt"}, 3 / 6),     # S4 v T4: not stronger, 4+
            (4, {"wound_minus_if_stronger": "ge"}, 2 / 6),     # S4 v T4: 4+ -> 5+
            (3, {"wound_minus_if_stronger": "ge"}, 2 / 6),     # S3 v T4: weaker, 5+
            # attacker: +1 to wound if S < T / S <= T
            (3, {"wound_plus_if_weaker": "lt"}, 3 / 6),        # S3 v T4: 5+ -> 4+
            (4, {"wound_plus_if_weaker": "lt"}, 3 / 6),        # S4 v T4: not weaker, 4+
            (4, {"wound_plus_if_weaker": "le"}, 4 / 6),        # S4 v T4: 4+ -> 3+
            (5, {"wound_plus_if_weaker": "le"}, 4 / 6),        # S5 v T4: stronger, 3+
            # uses modified characteristics, and both cancel out
            (4, {"wound_minus_if_stronger": "gt", "extra_strength": 1}, 3 / 6),   # S5 v T4: 3+ -> 4+
            (4, {"wound_plus_if_weaker": "lt", "toughness_mod": 1}, 3 / 6),       # S4 v T5: 5+ -> 4+
            (4, {"wound_plus_if_weaker": "le", "wound_minus_if_stronger": "ge"}, 3 / 6),
        ]
        for S, m, expected in cases:
            with self.subTest(S=S, **m):
                self.assertAlmostEqual(wound_rate(S, **m), expected, delta=0.01)
