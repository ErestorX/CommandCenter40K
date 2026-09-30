"""Army plan: give every attacker a 1st and a 2nd target so the army as a whole does the most work.

A unit realistically engages one or two targets in a game. Each attacker -> defender pairing gets a
score mixing two heuristics, each scaled to 0..1 by its best value:
  - share of the defender's wounds removed ("did it kill the thing?"),
  - points removed per 100 points of attacker ("was it worth the points?").
`weight` is the share of the first (1 = wounds only, 0 = points only).

The plan maximises, in this order:
  1. the number of defenders targeted at least once (1st or 2nd target);
  2. the total score, where a 2nd target counts for SECONDARY_WEIGHT of a 1st one, and a defender's
     score is scaled down when the attackers sent at it remove more than all its wounds (overkill).
Search: local search (re-choose one attacker's two targets, or swap a target between two attackers)
from a greedy plan, a coverage-first plan and a few seeded random plans. Deterministic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

SECONDARY_WEIGHT = 0.5
Pair = tuple[str, str]


@dataclass
class Assignment:
    attacker: str
    primary: str | None
    secondary: str | None


@dataclass
class ArmyPlan:
    assignments: list[Assignment]
    uncovered: list[str]                        # defenders nobody targets (only if there are too few slots)
    score: float
    scores: dict[Pair, float] = field(default_factory=dict)      # the combined 0..1 heuristic per pairing


def pair_scores(frac: dict[Pair, float], ppp: dict[Pair, float], weight: float) -> dict[Pair, float]:
    """Mix the two heuristics, each scaled by its best value."""
    fmax = max(frac.values(), default=0) or 1.0
    pmax = max(ppp.values(), default=0) or 1.0
    return {k: weight * frac[k] / fmax + (1 - weight) * ppp.get(k, 0.0) / pmax for k in frac}


def _value(plan: dict[str, tuple], score: dict[Pair, float], frac: dict[Pair, float]) -> tuple[int, float]:
    """(defenders targeted, total score) of a whole plan."""
    st = _State(score, frac)
    for a, targets in plan.items():
        st.apply(a, targets, +1)
    return st.value()


class _State:
    """Per-defender sums, so a move only recomputes the defenders it touches."""

    def __init__(self, score, frac):
        self.score, self.frac = score, frac
        self.v: dict[str, float] = {}         # weighted score sent at the defender
        self.load: dict[str, float] = {}      # weighted share of its wounds sent at it
        self.n: dict[str, int] = {}           # attackers targeting it

    def apply(self, a: str, targets: tuple, sign: int):
        for w, d in zip((1.0, SECONDARY_WEIGHT), targets):
            if d is not None:
                self.v[d] = self.v.get(d, 0.0) + sign * w * self.score[a, d]
                self.load[d] = self.load.get(d, 0.0) + sign * w * self.frac[a, d]
                self.n[d] = self.n.get(d, 0) + sign

    def worth(self, d: str) -> float:
        if not self.n.get(d):
            return 0.0
        v, load = self.v[d], self.load[d]
        return v / load if load > 1 else v    # overkill: the surplus counts for nothing

    def value(self) -> tuple[int, float]:
        return sum(1 for c in self.n.values() if c), sum(self.worth(d) for d in self.n)

    def delta(self, changes: list[tuple[str, tuple, tuple]]) -> tuple[int, float]:
        """Change in value if each (attacker, old targets, new targets) were applied."""
        touched = {d for _, old, new in changes for d in old + new if d is not None}
        before = (sum(1 for d in touched if self.n.get(d)), sum(self.worth(d) for d in touched))
        for a, old, new in changes:
            self.apply(a, old, -1)
            self.apply(a, new, +1)
        after = (sum(1 for d in touched if self.n.get(d)), sum(self.worth(d) for d in touched))
        for a, old, new in reversed(changes):
            self.apply(a, new, -1)
            self.apply(a, old, +1)
        return after[0] - before[0], after[1] - before[1]


def _better(d: tuple[int, float]) -> bool:
    return d[0] > 0 or (d[0] == 0 and d[1] > 1e-12)


def _add(x: tuple[int, float], y: tuple[int, float]) -> tuple[int, float]:
    return x[0] + y[0], x[1] + y[1]


def _best_targets(st: _State, a: str, reach: list[str]) -> tuple:
    """Best (1st, 2nd) targets for `a` with everyone else fixed (a must be removed from st).
    The two targets are different defenders, so their gains are independent: pick each from the top 2."""
    def gain(d, w):
        before = (1 if st.n.get(d) else 0, st.worth(d))
        st.v[d] = st.v.get(d, 0.0) + w * st.score[a, d]
        st.load[d] = st.load.get(d, 0.0) + w * st.frac[a, d]
        st.n[d] = st.n.get(d, 0) + 1
        after = (1, st.worth(d))
        st.v[d] -= w * st.score[a, d]
        st.load[d] -= w * st.frac[a, d]
        st.n[d] -= 1
        return after[0] - before[0], after[1] - before[1]
    first = sorted(((gain(d, 1.0), d) for d in reach), reverse=True)
    if len(reach) == 1:
        return first[0][0], (reach[0], None)
    second = sorted(((gain(d, SECONDARY_WEIGHT), d) for d in reach), reverse=True)[:2]
    return max((_add(g1, g2), (d1, d2)) for g1, d1 in first[:2] for g2, d2 in second if d1 != d2)


def _valid(t: tuple, reach: list[str]) -> bool:
    if t[1] is None:
        return len(reach) == 1 and t[0] in reach
    return t[0] != t[1] and t[0] in reach and t[1] in reach


def _local_search(plan: dict[str, tuple], reach: dict[str, list[str]], score, frac) -> dict[str, tuple]:
    st = _State(score, frac)
    for a, t in plan.items():
        st.apply(a, t, +1)
    atts = list(plan)
    improved = True
    while improved:
        improved = False
        # re-choose one attacker's two targets
        for a in atts:
            st.apply(a, plan[a], -1)
            here = st.delta([(a, (None, None), plan[a])])
            gain, best = _best_targets(st, a, reach[a])
            if best != plan[a] and _better((gain[0] - here[0], gain[1] - here[1])):
                plan[a], improved = best, True
            st.apply(a, plan[a], +1)
        # swap one target between two attackers
        for i, a in enumerate(atts):
            for b in atts[i + 1:]:
                for ia in range(2):
                    for ib in range(2):
                        ta, tb = list(plan[a]), list(plan[b])
                        ta[ia], tb[ib] = tb[ib], ta[ia]
                        ta, tb = tuple(ta), tuple(tb)
                        if (ta == plan[a] or not _valid(ta, reach[a]) or not _valid(tb, reach[b])
                                or not _better(st.delta([(a, plan[a], ta), (b, plan[b], tb)]))):
                            continue
                        st.apply(a, plan[a], -1), st.apply(b, plan[b], -1)
                        st.apply(a, ta, +1), st.apply(b, tb, +1)
                        plan[a], plan[b], improved = ta, tb, True
    return plan


RESTARTS = 12


def plan_army(attackers: list[str], defenders: list[str], frac: dict[Pair, float], ppp: dict[Pair, float],
              weight: float = 0.5) -> ArmyPlan:
    """frac / ppp: share of wounds and points per 100 for every pairing that has results."""
    score = pair_scores(frac, ppp, weight)
    reach = {a: [d for d in defenders if (a, d) in score] for a in attackers}
    atts = [a for a in attackers if reach[a]]
    if not atts:
        return ArmyPlan([Assignment(a, None, None) for a in attackers], list(defenders), 0.0, score)

    def ranked(a):
        return sorted((d for d in defenders if (a, d) in score), key=lambda d: -score[a, d])

    starts = []
    # 1. every attacker on its two best targets
    starts.append({a: tuple((ranked(a) + [None])[:2]) for a in atts})
    # 2. coverage first: hardest-to-reach defenders get their best free attacker, then fill up
    slots = {a: [] for a in atts}
    for d in sorted(defenders, key=lambda d: sum((a, d) in score for a in atts)):
        free = [a for a in atts if (a, d) in score and len(slots[a]) < 2]
        if free:
            slots[max(free, key=lambda a: score[a, d])].append(d)
    for a in atts:
        for d in ranked(a):
            if len(slots[a]) >= 2:
                break
            if d not in slots[a]:
                slots[a].append(d)
        slots[a].sort(key=lambda d: -score[a, d])
    starts.append({a: tuple((slots[a] + [None])[:2]) for a in atts})
    # 3. a few random plans (fixed seed: the same results always give the same plan)
    rng = random.Random(0)
    starts += [{a: tuple((rng.sample(reach[a], min(2, len(reach[a]))) + [None])[:2]) for a in atts}
               for _ in range(RESTARTS)]

    best, best_val = None, None
    for plan in starts:
        plan = _local_search(dict(plan), reach, score, frac)
        val = _value(plan, score, frac)
        if best_val is None or val[0] > best_val[0] or (val[0] == best_val[0] and val[1] > best_val[1] + 1e-12):
            best, best_val = plan, val

    targeted = {d for ts in best.values() for d in ts if d}
    return ArmyPlan([Assignment(a, *best.get(a, (None, None))) for a in attackers],
                    [d for d in defenders if d not in targeted], best_val[1], score)
