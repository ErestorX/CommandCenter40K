"""Army plan: two targets per attacker, every defender covered, overkill avoided."""
import itertools
import random
import unittest

from crunch.analysis.assign import _value, pair_scores, plan_army


def grid(atts, defs, rows):
    return {(a, d): v for a, row in zip(atts, rows) for d, v in zip(defs, row)}


def targets(plan):
    return {s.attacker: (s.primary, s.secondary) for s in plan.assignments}


class PlanArmyTest(unittest.TestCase):
    def test_every_defender_is_targeted(self):
        A, D = ["a1", "a2", "a3"], ["x", "y", "z", "w", "v"]
        frac = grid(A, D, [[.9, .2, .3, .1, .1], [.8, .3, .2, .2, .1], [.7, .1, .1, .3, .2]])
        plan = plan_army(A, D, frac, {k: 50 * v for k, v in frac.items()})
        self.assertEqual(plan.uncovered, [])
        self.assertEqual({d for t in targets(plan).values() for d in t}, set(D))
        for p, s in targets(plan).values():
            self.assertNotEqual(p, s)

    def test_too_few_attackers_reports_uncovered(self):
        frac = {("a", d): v for d, v in zip("xyz", (.5, .4, .1))}
        plan = plan_army(["a"], list("xyz"), frac, frac)
        self.assertEqual(targets(plan), {"a": ("x", "y")})
        self.assertEqual(plan.uncovered, ["z"])

    def test_overkill_spreads_the_attackers(self):
        # both attackers wipe X on their own; sending both at it wastes one
        A, D = ["a1", "a2"], ["x", "y", "z", "w"]
        frac = grid(A, D, [[1.0, .6, .1, .1], [1.0, .5, .1, .1]])
        plan = targets(plan_army(A, D, frac, dict(frac), weight=1.0))
        self.assertEqual(sorted(p for p, _ in plan.values()), ["x", "y"])

    def test_weight_chooses_between_the_heuristics(self):
        # x: kills a lot of a cheap unit; y: a small share of an expensive one, more points
        frac, ppp = {("a", "x"): .9, ("a", "y"): .3}, {("a", "x"): 10.0, ("a", "y"): 40.0}
        self.assertEqual(targets(plan_army(["a"], ["x", "y"], frac, ppp, weight=1.0))["a"][0], "x")
        self.assertEqual(targets(plan_army(["a"], ["x", "y"], frac, ppp, weight=0.0))["a"][0], "y")

    def test_missing_pairings_are_never_used(self):
        frac = {("a", "x"): .5, ("b", "x"): .2, ("b", "y"): .3}
        plan = targets(plan_army(["a", "b"], ["x", "y"], frac, frac))
        self.assertEqual(plan["a"], ("x", None))
        self.assertEqual(set(plan["b"]), {"x", "y"})

    def test_close_to_exhaustive_search(self):
        from itertools import permutations
        for seed in range(40):
            rnd = random.Random(seed)
            A = [f"a{i}" for i in range(rnd.randint(2, 3))]
            D = [f"d{j}" for j in range(rnd.randint(2, 5))]
            frac = {(a, d): rnd.random() ** 2 for a in A for d in D}
            ppp = {(a, d): rnd.random() * 40 for a in A for d in D}
            sc = pair_scores(frac, ppp, 0.5)
            best = max(_value(dict(zip(A, c)), sc, frac)
                       for c in itertools.product(list(permutations(D, 2)), repeat=len(A)))
            got = _value(targets(plan_army(A, D, frac, ppp)), sc, frac)
            with self.subTest(seed=seed):
                self.assertEqual(got[0], best[0])                    # coverage is always optimal
                self.assertGreater(got[1], best[1] * 0.95)

    def test_deterministic(self):
        rnd = random.Random(3)
        A, D = [f"a{i}" for i in range(8)], [f"d{j}" for j in range(9)]
        frac = {(a, d): rnd.random() for a in A for d in D}
        self.assertEqual(targets(plan_army(A, D, frac, frac)), targets(plan_army(A, D, frac, frac)))


if __name__ == "__main__":
    unittest.main()
