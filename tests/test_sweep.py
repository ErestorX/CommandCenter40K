"""Engagement Optimizer: modifier catalogue, test packages, sweep execution and result aggregation."""
import json
import tempfile
from dataclasses import replace
import unittest
from pathlib import Path
from types import SimpleNamespace

from command_center.analysis.plan import DEFENDER, ATTACKER, PlanStore, TestPackage, test_count
from command_center.analysis.results import ResultSet
from command_center.analysis.sweep import AttackerSpec, DefenderSpec, TestRecord, build_cases, run_sweep
from command_center.analysis.variants import (ATTACKER_VARIANTS, DEFENDER_VARIANTS, MELEE, RANGED, combined, for_phase,
                                              known, package_label, toggle, with_value)
from command_center.core import Dice, ModelProfile, Target, TargetGroup, Weapon, WeaponKeywords, WeaponLoad

BOLT = Weapon("Bolt rifle", "Ranged", '24"', Dice(0, 0, 2), 3, 4, 1, Dice(0, 0, 1), WeaponKeywords())
KNIFE = Weapon("Knife", "Melee", "Melee", Dice(0, 0, 3), 3, 4, 0, Dice(0, 0, 1), WeaponKeywords())
BOY = ModelProfile("Boy", '6"', 5, 5, None, 1)
NONE = ()


def boyz(n=10):
    return Target("Boyz", [TargetGroup(BOY, n)], {"infantry"})


def attacker(tests):
    return AttackerSpec("Intercessors", 90, {RANGED: [WeaponLoad(BOLT, 5)], MELEE: [WeaponLoad(KNIFE, 5)]}, tests)


def defender(tests):
    return DefenderSpec("Boyz", 80, boyz(), tests)


class PackageTest(unittest.TestCase):
    def test_numeric_modifiers_add_up_across_sides(self):
        m = combined(["hit+1"], ["hit-1"])
        self.assertEqual((m.hit_mod, m.to_be_hit_mod), (1, -1))
        m = combined(["ap=+1"], ["ap=-1"])
        self.assertEqual((m.extra_ap, m.ap_mod), (1, -1))

    def test_package_applies_every_modifier(self):
        m = combined(["hit+1", "rr_wound_all", "lethal"], ["cover", "fnp=5+"])
        self.assertEqual((m.hit_mod, m.reroll_wounds, m.add_lethal_hits), (1, "fails", True))
        self.assertEqual((m.cover, m.feel_no_pain), (True, 5))

    def test_packages_do_not_leak_between_tests(self):
        combined(["hit+1"], [])
        self.assertEqual(combined([], []).hit_mod, 0)

    def test_strength_vs_toughness_variants(self):
        m = combined(["wound+1_weaker_eq"], ["wound-1_stronger"])
        self.assertEqual((m.wound_plus_if_weaker, m.wound_minus_if_stronger), ("le", "gt"))
        self.assertEqual(m.wound_mod, 0)

    def test_each_side_keeps_its_own_modifier(self):
        m = combined(["wound+1", "skill+1"], ["wound-1", "skill-1"])
        self.assertEqual((m.wound_mod, m.to_be_wounded_mod), (1, -1))
        self.assertEqual((m.skill_mod, m.enemy_skill_mod), (1, -1))

    def test_range_and_granted_abilities(self):
        m = combined(['range=<2"', "rapid_fire=2", "blast=1"], ['hidden=15"', "inv=4+"])
        self.assertEqual((m.effective_range, m.add_rapid_fire.mean, m.add_blast), (1.5, 2, 1))
        self.assertEqual((m.hidden_beyond, m.extra_invuln), (15.0, 4))
        self.assertEqual(combined(['range=18"'], []).effective_range, 18.0)

    def test_modifiers_with_a_value(self):
        m = combined(["crit_hit=4+", "sustained=D3", "crit_wound=5+", "attacks=+D3", "strength=+2", "ap=-1",
                      "damage=+2"],
                     ["ap=-2", "dmg=-2", "fnp=4+", "fnp_against=psychic/mortal", "toughness=+2", "save=-1"])
        self.assertEqual((m.crit_hit_on, str(m.add_sustained_hits), m.crit_wound_on), (4, "D3", 5))
        self.assertEqual((str(m.extra_attacks), m.extra_strength, m.extra_ap, str(m.extra_damage)),
                         ("+D3", 2, -1, "+2"))
        self.assertEqual((m.ap_mod, m.damage_reduction, m.feel_no_pain, m.fnp_against), (-2, 2, 4, "psychic_mortal"))
        self.assertEqual((m.toughness_mod, m.save_char_mod), (2, -1))
        self.assertEqual(combined(["sustained"], ["fnp"]).feel_no_pain, 5)          # no value: the default one

    def test_a_value_has_one_spelling(self):
        a, d = ATTACKER_VARIANTS, DEFENDER_VARIANTS
        cases = [(a["sustained"], "d3", "sustained=D3"), (a["attacks"], "1", "attacks=+1"),
                 (a["attacks"], "d3", "attacks=+D3"), (a["strength"], "2", "strength=+2"),
                 (a["crit_hit"], "4", "crit_hit=4+"), (a["range"], "12", 'range=12"'),
                 (a["range"], '<2"', 'range=<2"'), (a["range"], "1", 'range=<2"'), (a["blast"], "2", "blast=2"),
                 (d["hidden"], "12.5", 'hidden=12.5"'), (d["dmg"], "1", "dmg=-1"), (d["dmg"], "-2", "dmg=-2"),
                 (d["fnp_against"], "Mortal", "fnp_against=mortal"), (d["fnp"], "", "fnp=5+"),
                 (a["lethal"], "", "lethal")]
        for variant, text, mod in cases:
            with self.subTest(mod=mod):
                self.assertEqual(variant.mod(text), mod)
        for variant, text in ((a["sustained"], "x"), (a["attacks"], "0"), (a["strength"], ""[:0] + "0"),
                              (a["crit_hit"], "7+"), (a["range"], "far"), (a["blast"], "-1"),
                              (d["fnp_against"], "everything"), (d["hidden"], "-3")):
            with self.subTest(variant=variant.key, text=text):
                self.assertRaises(ValueError, variant.mod, text)

    def test_labels_show_the_value(self):
        self.assertEqual(package_label(["rapid_fire=D3", 'range=<2"', "attacks=-1", "crit_hit=4+"], ATTACKER_VARIANTS),
                         'Crit hits on 4+, -1 Attacks, Rapid Fire D3, Effective range <2"')
        self.assertEqual(package_label(["inv=4+", 'hidden=12"', "dmg=-1", "fnp_against=psychic"], DEFENDER_VARIANTS),
                         'Hidden beyond 12", -1 Damage, Feel No Pain against psychic, Additional 4+ invulnerable')
        self.assertEqual((ATTACKER_VARIANTS["attacks"].name, DEFENDER_VARIANTS["inv"].name),
                         ("Attacks", "Additional invulnerable"))

    def test_toggle_and_change_a_value(self):
        mods = toggle(["hit+1"], "sustained=2", ATTACKER_VARIANTS)
        self.assertEqual(mods, ["hit+1", "sustained=2"])
        self.assertEqual(with_value(mods, "sustained=D3"), ["hit+1", "sustained=D3"])
        self.assertEqual(with_value(mods, "attacks=+1"), mods)                       # not ticked: nothing changes
        self.assertEqual(toggle(mods, "sustained=1", ATTACKER_VARIANTS), ["hit+1"])  # whatever its value
        self.assertEqual(for_phase(["rapid_fire", "sustained=d3"], ATTACKER_VARIANTS, MELEE), ("sustained=D3",))

    def test_toggle_replaces_alternatives_in_the_same_slot(self):
        keys = toggle([], "rr_hit_1", ATTACKER_VARIANTS)
        keys = toggle(keys, "hit+1", ATTACKER_VARIANTS)
        keys = toggle(keys, "rr_hit_all", ATTACKER_VARIANTS)      # replaces re-roll 1s
        self.assertEqual(keys, ["hit+1", "rr_hit_all"])
        self.assertEqual(toggle(keys, "hit+1", ATTACKER_VARIANTS), ["rr_hit_all"])

    def test_phase_filter_and_label(self):
        pkg = ["plunging", "hit+1", "skill+1"]
        self.assertEqual(for_phase(pkg, ATTACKER_VARIANTS, RANGED), ("hit+1", "skill+1", "plunging"))
        self.assertEqual(for_phase(pkg, ATTACKER_VARIANTS, MELEE), ("hit+1", "skill+1"))
        self.assertEqual(package_label(pkg, ATTACKER_VARIANTS), "+1 to hit, +1 Skill, Plunging Fire")
        self.assertEqual(package_label([], DEFENDER_VARIANTS), "No modifiers")

    def test_keys_are_unique_and_labelled(self):
        for cat in (ATTACKER_VARIANTS, DEFENDER_VARIANTS):
            for k, v in cat.items():
                self.assertEqual(k, v.key)
                self.assertTrue(v.label and v.phases)


class BuildCasesTest(unittest.TestCase):
    def test_every_attacker_test_against_every_defender_test(self):
        # shooting {none, plunging fire}, fight {none, re-roll 1s to hit}; defender {none, -1 AP} -> 4 x 2
        a = attacker({RANGED: [NONE, ("plunging",)], MELEE: [NONE, ("rr_hit_1",)]})
        cases = build_cases([a], [defender([NONE, ("ap=-1",)])])
        self.assertEqual(len(cases), 8)
        self.assertEqual(len({(c.phase, c.att_mods, c.def_mods) for c in cases}), 8)

    def test_a_package_is_one_test(self):
        a = attacker({RANGED: [("hit+1", "rr_hit_1", "lethal")]})
        cases = build_cases([a], [defender([("cover", "fnp=6+")])])
        self.assertEqual(len(cases), 1)
        self.assertEqual((cases[0].att_mods, cases[0].def_mods), (("hit+1", "rr_hit_1", "lethal"), ("cover", "fnp=6+")))

    def test_values_make_different_tests(self):
        a = attacker({RANGED: [("sustained=1",), ("sustained=2",), ("sustained=2", "plunging")]})
        cases = build_cases([a], [defender([("fnp=6+",), ("fnp=5+",)])])
        self.assertEqual(len(cases), 6)
        recs = run_sweep(cases, trials=4_000, workers=1)
        by = {(r.att_test, r.def_test): r.dmg_mean for r in recs}
        self.assertGreater(by[("Sustained Hits 2", "Feel No Pain 6+")], by[("Sustained Hits 1", "Feel No Pain 6+")])
        self.assertGreater(by[("Sustained Hits 1", "Feel No Pain 6+")], by[("Sustained Hits 1", "Feel No Pain 5+")])

    def test_modifiers_of_other_phases_are_dropped_and_duplicates_skipped(self):
        a = attacker({MELEE: [NONE, ("plunging",), ("lethal", "plunging")]})
        cases = build_cases([a], [defender([NONE, ("cover",)])])
        # fight: Plunging Fire does nothing (same as none), cover does nothing (same as none)
        self.assertEqual({c.att_mods for c in cases}, {(), ("lethal",)})
        self.assertEqual({c.def_mods for c in cases}, {()})
        self.assertEqual(len(cases), 2)

    def test_phase_without_weapons_is_skipped(self):
        a = AttackerSpec("Gunline", 100, {RANGED: [WeaponLoad(BOLT, 5)], MELEE: []}, {RANGED: [NONE], MELEE: [NONE]})
        self.assertEqual(len(build_cases([a], [defender([NONE])])), 1)

    def test_tests_share_a_seed(self):
        a = attacker({RANGED: [NONE, ("hit+1",), ("hit+1", "lethal")]})
        cases = build_cases([a], [defender([NONE])])
        self.assertEqual(len({c.seed for c in cases}), 1)


class RunSweepTest(unittest.TestCase):
    def test_records_and_ordering(self):
        a = attacker({RANGED: [NONE, ("hit+1",)]})
        cases = build_cases([a], [defender([NONE, ("cover",)])])
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

    def test_combined_package_beats_its_parts(self):
        a = attacker({RANGED: [("hit+1",), ("rr_wound_all",), ("hit+1", "rr_wound_all")]})
        recs = run_sweep(build_cases([a], [defender([NONE])]), trials=4_000, workers=1)
        by = {r.att_test: r.dmg_mean for r in recs}
        both = by["+1 to hit, Re-roll failed wounds"]
        self.assertGreater(both, by["+1 to hit"])
        self.assertGreater(both, by["Re-roll failed wounds"])

    def test_process_pool_matches_sequential(self):
        a = attacker({RANGED: [NONE], MELEE: [NONE]})
        cases = build_cases([a], [defender([NONE, ("ap=-1",)])])
        seq = run_sweep(cases, trials=1_000, workers=1)
        par = run_sweep(cases, trials=1_000, workers=2)
        self.assertEqual([r.dmg_mean for r in seq], [r.dmg_mean for r in par])

    def test_cancel(self):
        a = attacker({RANGED: [NONE, ("hit+1",)]})
        cases = build_cases([a], [defender([NONE])])
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
            rec(6, "A", "X", "Shooting", "+1 to hit", "No modifiers", 5),
            rec(7, "A", "X", "Shooting", "+1 to hit", "Cover", 3),
        ])

    def test_one_phase_best_test_with_average_defender(self):
        agg = self.rs.pair("A", "X", "dmg_mean", "best", "mean", phase="Shooting")
        self.assertEqual(agg.value, 4)                          # +1 to hit: (5 + 3) / 2
        self.assertEqual(agg.record.att_test, "+1 to hit")      # identifies the winning test

    def test_total_adds_each_phase_best_test(self):
        agg = self.rs.pair("A", "X", "dmg_mean", "best", "mean")
        self.assertEqual(agg.value, 4 + 6)
        self.assertEqual({ph: p.record.att_test for ph, p in agg.parts.items()},
                         {"Shooting": "+1 to hit", "Fight": "No modifiers"})
        self.assertIsNone(agg.record)
        self.assertFalse(agg.exact)
        self.assertEqual(len(agg.records), 6)

    def test_total_of_a_single_phase_is_that_phase(self):
        agg = self.rs.pair("B", "X", "dmg_mean", "best", "mean")
        self.assertEqual((agg.value, agg.record.phase, agg.parts), (3, "Shooting", {}))

    def test_total_is_capped_at_the_whole_unit(self):
        rs = ResultSet([rec(0, "A", "X", "Shooting", "t", "d", 7), rec(1, "A", "X", "Fight", "t", "d", 6)])
        self.assertEqual(rs.pair("A", "X", "dmg_mean", "best", "mean").value, 10)       # 10 wounds
        self.assertEqual(rs.pair("A", "X", "slain_mean", "best", "mean").value, 5)      # 3.5 + 3, 5 models
        self.assertEqual(rs.pair("A", "X", "frac_wounds", "best", "mean").value, 1)

    def test_wipe_chance_is_either_phase(self):
        rs = ResultSet([replace(rec(0, "A", "X", "Shooting", "t", "d", 1), p_wipe=0.5),
                        replace(rec(1, "A", "X", "Fight", "t", "d", 1), p_wipe=0.2)])
        self.assertAlmostEqual(rs.pair("A", "X", "p_wipe", "best", "mean").value, 1 - 0.5 * 0.8)

    def test_defender_best_option(self):
        sc = self.rs.scenarios("A", "X", "dmg_mean", "min")
        self.assertEqual([(ph, a.value) for ph, _, a in sc], [("Fight", 6), ("Shooting", 3), ("Shooting", 2)])
        sc = self.rs.scenarios("A", "X", "dmg_mean", "min", phase="Fight")
        self.assertEqual([(ph, a.value) for ph, _, a in sc], [("Fight", 6)])

    def test_mean_of_tests_is_not_exact(self):
        agg = self.rs.pair("A", "X", "dmg_mean", "mean", "mean", phase="Shooting")
        self.assertAlmostEqual(agg.value, (3 + 4) / 2)
        self.assertFalse(agg.exact)
        self.assertIsNone(agg.record)

    def test_hiding_promotes_next_test(self):
        self.rs.hidden |= {6, 7}
        self.assertEqual(self.rs.pair("A", "X", "dmg_mean", "best", "mean").value, 3 + 6)
        self.rs.hidden |= {2, 3}                                # no Fight left: the total is the Shooting value
        agg = self.rs.pair("A", "X", "dmg_mean", "best", "mean")
        self.assertEqual((agg.record.phase, agg.value), ("Shooting", 3))

    def test_filters_and_matrix(self):
        atts, defs, cells = self.rs.matrix("dmg_mean", "best", "max", phase="Fight")
        self.assertEqual([c[0].value if c[0] else None for c in cells], [6, None])
        self.rs.excluded["phase"].add("Fight")
        atts, defs, cells = self.rs.matrix("dmg_mean", "best", "max")
        self.assertEqual((atts, defs), (["A", "B"], ["X"]))
        self.assertEqual([c[0].value for c in cells], [5, 3])
        self.rs.excluded["attacker"].add("B")
        self.assertEqual(len(self.rs.visible()), 4)


class PlanStoreTest(unittest.TestCase):
    army = SimpleNamespace(path=Path("lists/Mine.txt"))
    unit = SimpleNamespace(label="Intercessors #2")

    def test_ticking_adds_a_baseline_and_unticking_deletes_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = PlanStore(Path(tmp) / "plans.json").get(self.army, ATTACKER, self.unit)
            p.set_included(True, ATTACKER)
            self.assertEqual([(t.mods, t.phases) for t in p.tests], [([], [RANGED, MELEE])])
            self.assertTrue(p.add_test(TestPackage(["hit+1", "lethal"], [RANGED])))
            self.assertFalse(p.add_test(TestPackage(["lethal", "hit+1"], [RANGED])))    # same test
            self.assertEqual(test_count(ATTACKER, p), 3)                                # 2 + 1 phases
            p.set_included(False, ATTACKER)
            self.assertEqual(p.tests, [])
            p.set_included(True, ATTACKER)
            self.assertEqual(len(p.tests), 1)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            s = PlanStore(path)
            p = s.get(self.army, ATTACKER, self.unit)
            p.set_included(True, ATTACKER)
            p.add_test(TestPackage(["rr_hit_1", "lethal"], [MELEE]))
            d = s.get(self.army, DEFENDER, self.unit)
            d.set_included(True, DEFENDER)
            d.add_test(TestPackage(["ap=-1", "fnp=6+"]))
            s.save()
            s2 = PlanStore(path)
            p2 = s2.get(self.army, ATTACKER, self.unit)
            self.assertTrue(p2.included)
            self.assertEqual([(t.mods, t.phases) for t in p2.tests], [([], [RANGED, MELEE]), (["rr_hit_1", "lethal"],
                                                                                            [MELEE])])
            self.assertEqual([t.mods for t in s2.get(self.army, DEFENDER, self.unit).tests], [[], ["ap=-1", "fnp=6+"]])
            self.assertFalse(s2.get(self.army, DEFENDER, SimpleNamespace(label="Other")).included)

    def test_plans_from_the_previous_version_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            old = {"included": True, "leader": "None", "support": "(list default)", "weapons": {"x|Gun": False},
                   "phases": {"ranged": True, "melee": True}, "variants": {"ranged": ["baseline", "cover"]}}
            path.write_text(json.dumps({"Mine.txt|attacker|Intercessors #2": old}), encoding="utf-8")
            p = PlanStore(path).get(self.army, ATTACKER, self.unit)
            self.assertEqual((p.included, p.leader, p.weapons), (True, "None", {"x|Gun": False}))
            self.assertEqual([t.mods for t in p.tests], [[]])          # starts again from "no modifiers"

    def test_modifiers_that_no_longer_exist_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            tests = [{"mods": [], "phases": ["ranged"]}, {"mods": ["stationary"], "phases": ["ranged"]},
                     {"mods": ["half_range", "hit+1"], "phases": ["ranged"]}]
            path.write_text(json.dumps({"Mine.txt|attacker|Intercessors #2": {"included": True, "tests": tests}}),
                            encoding="utf-8")
            p = PlanStore(path).get(self.army, ATTACKER, self.unit)
            self.assertEqual([t.mods for t in p.tests], [[], ["hit+1"]])        # the emptied test is a duplicate

    def test_modifiers_of_the_fixed_value_version_are_rewritten(self):
        self.assertEqual(known(["crit_hit_5", "sustained_1", "a+1", "s+1", "ap+1", "d+1", "lethal", "gone"],
                               ATTACKER_VARIANTS),
                         ["crit_hit=5+", "sustained=1", "attacks=+1", "strength=+1", "ap=+1", "damage=+1", "lethal"])
        self.assertEqual(known(["cover", "ap-1", "dmg-1", "fnp4", "inv5", "t+1", "sv+1", "fnp=9+"], DEFENDER_VARIANTS),
                         ["cover", "ap=-1", "dmg=-1", "fnp=4+", "inv=5+", "toughness=+1", "save=+1"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            tests = [{"mods": ["cover", "ap-1"], "phases": []}, {"mods": ["fnp5"], "phases": []}]
            path.write_text(json.dumps({"Mine.txt|defender|Intercessors #2": {"included": True, "tests": tests}}),
                            encoding="utf-8")
            p = PlanStore(path).get(self.army, DEFENDER, self.unit)
            self.assertEqual([t.mods for t in p.tests], [["cover", "ap=-1"], ["fnp=5+"]])

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertFalse(PlanStore(path).get(SimpleNamespace(path=Path("x.txt")), ATTACKER,
                                                 SimpleNamespace(label="u")).included)


if __name__ == "__main__":
    unittest.main()
