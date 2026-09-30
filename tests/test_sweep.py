"""Unit finder: scenario catalogue, test planning, sweep execution and result aggregation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from crunch.analysis.plan import DEFENDER, ATTACKER, PlanStore
from crunch.analysis.results import ResultSet
from crunch.analysis.sweep import AttackerSpec, DefenderSpec, TestRecord, build_cases, run_sweep
from crunch.analysis.variants import ATTACKER_VARIANTS, DEFENDER_VARIANTS, MELEE, RANGED, combined
from crunch.core import Dice, ModelProfile, Target, TargetGroup, Weapon, WeaponKeywords, WeaponLoad

BOLT = Weapon("Bolt rifle", "Ranged", '24"', Dice(0, 0, 2), 3, 4, 1, Dice(0, 0, 1), WeaponKeywords())
KNIFE = Weapon("Knife", "Melee", "Melee", Dice(0, 0, 3), 3, 4, 0, Dice(0, 0, 1), WeaponKeywords())
BOY = ModelProfile("Boy", '6"', 5, 5, None, 1)


def boyz(n=10):
    return Target("Boyz", [TargetGroup(BOY, n)], {"infantry"})


def attacker(variants):
    return AttackerSpec("Intercessors", 90, {RANGED: [WeaponLoad(BOLT, 5)], MELEE: [WeaponLoad(KNIFE, 5)]},
                        variants)


class VariantTest(unittest.TestCase):
    def test_numeric_modifiers_add_up_across_sides(self):
        m = combined(ATTACKER_VARIANTS["hit+1"], DEFENDER_VARIANTS["hit-1"])
        self.assertEqual(m.hit_mod, 0)
        m = combined(ATTACKER_VARIANTS["ap+1"], DEFENDER_VARIANTS["ap-1"])
        self.assertEqual((m.extra_ap, m.ap_mod), (1, -1))

    def test_variants_do_not_leak_between_tests(self):
        combined(ATTACKER_VARIANTS["hit+1"], DEFENDER_VARIANTS["baseline"])
        self.assertEqual(combined(ATTACKER_VARIANTS["baseline"], DEFENDER_VARIANTS["baseline"]).hit_mod, 0)

    def test_strength_vs_toughness_variants(self):
        m = combined(ATTACKER_VARIANTS["wound+1_weaker_eq"], DEFENDER_VARIANTS["wound-1_stronger"])
        self.assertEqual((m.wound_plus_if_weaker, m.wound_minus_if_stronger), ("le", "gt"))
        self.assertEqual(m.wound_mod, 0)

    def test_keys_are_unique_and_labelled(self):
        for cat in (ATTACKER_VARIANTS, DEFENDER_VARIANTS):
            for k, v in cat.items():
                self.assertEqual(k, v.key)
                self.assertTrue(v.label and v.phases)


class BuildCasesTest(unittest.TestCase):
    def test_users_example_makes_eight_tests(self):
        # attacker: shooting {no mods, cover}, fight {no mods, re-roll 1s to hit}; defender: {no mods, -1 AP}
        a = attacker({RANGED: ["baseline", "cover"], MELEE: ["baseline", "rr_hit_1"]})
        d = DefenderSpec("Boyz", 80, boyz(), ["baseline", "ap-1"])
        cases = build_cases([a], [d])
        self.assertEqual(len(cases), 8)
        self.assertEqual(len({(c.phase, c.att_variant, c.def_variant) for c in cases}), 8)

    def test_phase_specific_variants_are_skipped(self):
        a = attacker({RANGED: ["baseline", "charged"], MELEE: ["baseline", "stationary"]})
        d = DefenderSpec("Boyz", 80, boyz(), ["baseline", "cover"])   # cover: shooting only
        cases = build_cases([a], [d])
        # shooting: 1 attacker x 2 defender; fight: 1 attacker x 1 defender
        self.assertEqual(len(cases), 3)

    def test_phase_without_weapons_is_skipped(self):
        a = AttackerSpec("Gunline", 100, {RANGED: [WeaponLoad(BOLT, 5)], MELEE: []},
                         {RANGED: ["baseline"], MELEE: ["baseline"]})
        self.assertEqual(len(build_cases([a], [DefenderSpec("Boyz", 80, boyz(), ["baseline"])])), 1)

    def test_scenarios_share_a_seed(self):
        a = attacker({RANGED: ["baseline", "hit+1"]})
        cases = build_cases([a], [DefenderSpec("Boyz", 80, boyz(), ["baseline"])])
        self.assertEqual(len({c.seed for c in cases}), 1)


class RunSweepTest(unittest.TestCase):
    def test_records_and_ordering(self):
        a = attacker({RANGED: ["baseline", "hit+1"]})
        cases = build_cases([a], [DefenderSpec("Boyz", 80, boyz(), ["baseline", "cover"])])
        recs = run_sweep(cases, trials=4_000, workers=1)
        self.assertEqual([r.id for r in recs], [c.id for c in cases])
        self.assertFalse(any(r.error for r in recs))
        by = {(r.att_test, r.def_test): r.dmg_mean for r in recs}
        # 10 attacks, 3+ hit, 5+ wound, 6+ save
        self.assertAlmostEqual(by[("No modifiers", "No modifiers")], 10 * 4 / 6 * 2 / 6 * 5 / 6, delta=0.1)
        self.assertGreater(by[("+1 to hit", "No modifiers")], by[("No modifiers", "No modifiers")])
        self.assertLess(by[("No modifiers", "Cover")], by[("No modifiers", "No modifiers")])
        # +1 to hit cancels cover
        self.assertAlmostEqual(by[("+1 to hit", "Cover")], by[("No modifiers", "No modifiers")], delta=1e-9)
        r = recs[0]
        self.assertAlmostEqual(r.pts_removed, 80 * r.slain_mean / 10)

    def test_process_pool_matches_sequential(self):
        a = attacker({RANGED: ["baseline"], MELEE: ["baseline"]})
        cases = build_cases([a], [DefenderSpec("Boyz", 80, boyz(), ["baseline", "ap-1"])])
        seq = run_sweep(cases, trials=1_000, workers=1)
        par = run_sweep(cases, trials=1_000, workers=2)
        self.assertEqual([r.dmg_mean for r in seq], [r.dmg_mean for r in par])

    def test_cancel(self):
        a = attacker({RANGED: ["baseline", "hit+1"]})
        cases = build_cases([a], [DefenderSpec("Boyz", 80, boyz(), ["baseline"])])
        self.assertLess(len(run_sweep(cases, trials=500, workers=1, cancelled=lambda: True)), len(cases))


def rec(i, att, dfn, phase, at, dt, dmg):
    return TestRecord(i, att, dfn, phase, at, dt, 100, 100, 5, 10, dmg, 1, dmg - 1, dmg + 1, dmg / 2, 0, 5,
                      0, dmg / 10, dmg * 10, dmg * 10)


class ResultSetTest(unittest.TestCase):
    def setUp(self):
        self.rs = ResultSet([
            rec(0, "A", "X", "Shooting", "No modifiers", "No modifiers", 4),
            rec(1, "A", "X", "Shooting", "No modifiers", "Cover", 2),
            rec(2, "A", "X", "Fight", "No modifiers", "No modifiers", 6),
            rec(3, "A", "X", "Fight", "No modifiers", "Cover", 6),
            rec(4, "B", "X", "Shooting", "No modifiers", "No modifiers", 3),
            rec(5, "B", "X", "Shooting", "No modifiers", "Cover", 3),
        ])

    def test_best_scenario_with_average_defender(self):
        agg = self.rs.pair("A", "X", "dmg_mean", "best", "mean")
        self.assertEqual(agg.value, 6)
        self.assertEqual(agg.record.phase, "Fight")        # identifies the winning scenario

    def test_defender_best_option(self):
        sc = self.rs.scenarios("A", "X", "dmg_mean", "min")
        self.assertEqual([(ph, a.value) for ph, _, a in sc], [("Fight", 6), ("Shooting", 2)])

    def test_mean_of_scenarios_is_not_exact(self):
        agg = self.rs.pair("A", "X", "dmg_mean", "mean", "mean")
        self.assertAlmostEqual(agg.value, (3 + 6) / 2)
        self.assertFalse(agg.exact)
        self.assertIsNone(agg.record)

    def test_hiding_promotes_next_scenario(self):
        self.rs.hidden |= {2, 3}
        agg = self.rs.pair("A", "X", "dmg_mean", "best", "mean")
        self.assertEqual((agg.record.phase, agg.value), ("Shooting", 3))

    def test_filters_and_matrix(self):
        self.rs.excluded["phase"].add("Fight")
        atts, defs, cells = self.rs.matrix("dmg_mean", "best", "max")
        self.assertEqual((atts, defs), (["A", "B"], ["X"]))
        self.assertEqual([c[0].value for c in cells], [4, 3])
        self.rs.excluded["attacker"].add("B")
        self.assertEqual(len(self.rs.visible()), 2)


class PlanStoreTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            army = SimpleNamespace(path=Path("lists/Mine.txt"))
            unit = SimpleNamespace(label="Intercessors #2")
            s = PlanStore(path)
            p = s.get(army, ATTACKER, unit)
            p.included = True
            p.toggle_variant(MELEE, "rr_hit_1")
            s.get(army, DEFENDER, unit).toggle_variant("any", "ap-1")
            s.save()
            s2 = PlanStore(path)
            p2 = s2.get(army, ATTACKER, unit)
            self.assertTrue(p2.included)
            self.assertEqual(p2.variant_keys(MELEE), ["baseline", "rr_hit_1"])
            self.assertEqual(s2.get(army, DEFENDER, unit).variant_keys("any"), ["baseline", "ap-1"])
            self.assertFalse(s2.get(army, DEFENDER, SimpleNamespace(label="Other")).included)

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertFalse(PlanStore(path).get(SimpleNamespace(path=Path("x.txt")), ATTACKER,
                                                 SimpleNamespace(label="u")).included)


if __name__ == "__main__":
    unittest.main()
