"""Catalogue of individual test scenarios ("variants").

A variant is ONE modifier applied on its own on top of the baseline (no modifiers). Variants are
never combined: ticking three variants for a unit produces three extra tests, not a combination.

Add a scenario by adding a Variant to ATTACKER_VARIANTS or DEFENDER_VARIANTS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from crunch.core.dice import Dice, DiceMod
from crunch.core.modifiers import Modifiers

RANGED, MELEE = "ranged", "melee"
PHASES = (RANGED, MELEE)
PHASE_LABEL = {RANGED: "Shooting", MELEE: "Fight"}

BASELINE = "baseline"


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    group: str
    phases: tuple[str, ...]              # phases where it means something
    apply: Callable[[Modifiers], None]

    def modifiers(self) -> Modifiers:
        m = Modifiers()
        self.apply(m)
        return m


def _set(**kw) -> Callable[[Modifiers], None]:
    def f(m: Modifiers):
        for k, v in kw.items():
            setattr(m, k, v)
    return f


def _add(**kw) -> Callable[[Modifiers], None]:
    """For numeric modifiers that stack between attacker and defender (e.g. +1 hit and -1 to be hit)."""
    def f(m: Modifiers):
        for k, v in kw.items():
            setattr(m, k, getattr(m, k) + v)
    return f


BOTH = PHASES
_A = [
    Variant(BASELINE, "No modifiers", "Baseline", BOTH, _set()),
    # hit roll
    Variant("hit+1", "+1 to hit", "Hit", BOTH, _add(hit_mod=1)),
    Variant("rr_hit_1", "Re-roll 1s to hit", "Hit", BOTH, _set(reroll_hits="ones")),
    Variant("rr_hit_12", "Re-roll 1s & 2s to hit", "Hit", BOTH, _set(reroll_hits="ones_twos")),
    Variant("rr_hit_all", "Re-roll failed hits", "Hit", BOTH, _set(reroll_hits="fails")),
    Variant("crit_hit_5", "Crit hits on 5+", "Hit", BOTH, _set(crit_hit_on=5)),
    Variant("sustained_1", "Sustained Hits 1", "Hit", BOTH, _set(add_sustained_hits=Dice(0, 0, 1))),
    Variant("lethal", "Lethal Hits", "Hit", BOTH, _set(add_lethal_hits=True)),
    # wound roll
    Variant("wound+1", "+1 to wound", "Wound", BOTH, _add(wound_mod=1)),
    Variant("rr_wound_1", "Re-roll 1s to wound", "Wound", BOTH, _set(reroll_wounds="ones")),
    Variant("rr_wound_all", "Re-roll failed wounds", "Wound", BOTH, _set(reroll_wounds="fails")),
    Variant("crit_wound_5", "Crit wounds on 5+", "Wound", BOTH, _set(crit_wound_on=5)),
    Variant("dev", "Devastating Wounds", "Wound", BOTH, _set(add_devastating_wounds=True)),
    # characteristics
    Variant("a+1", "+1 Attack", "Characteristics", BOTH, _set(extra_attacks=DiceMod.parse("+1"))),
    Variant("s+1", "+1 Strength", "Characteristics", BOTH, _add(extra_strength=1)),
    Variant("ap+1", "+1 AP", "Characteristics", BOTH, _add(extra_ap=1)),
    Variant("d+1", "+1 Damage", "Characteristics", BOTH, _set(extra_damage=DiceMod.parse("+1"))),
    # situation
    Variant("stationary", "Remained stationary", "Situation", (RANGED,), _set(stationary=True)),
    Variant("plunging", "Plunging Fire", "Situation", (RANGED,), _set(plunging_fire=True)),
    Variant("half_range", "Within half range", "Situation", (RANGED,), _set(half_range=True)),
    Variant("beyond_12", "Target beyond 12\"", "Situation", (RANGED,), _set(beyond_12=True)),
    Variant("not_visible", "Target not visible", "Situation", (RANGED,), _set(not_visible=True)),
    Variant("spotted", "Not visible, spotted", "Situation", (RANGED,), _set(not_visible=True, spotted=True)),
    Variant("cover", "Target in cover", "Situation", (RANGED,), _set(cover=True)),
    Variant("charged", "Charged", "Situation", (MELEE,), _set(charged=True)),
]

_D = [
    Variant(BASELINE, "No modifiers", "Baseline", BOTH, _set()),
    Variant("cover", "Cover", "Defence", (RANGED,), _set(cover=True)),
    Variant("hit-1", "-1 to be hit", "Defence", BOTH, _add(hit_mod=-1)),
    Variant("wound-1", "-1 to be wounded", "Defence", BOTH, _add(wound_mod=-1)),
    Variant("ap-1", "-1 AP (worsen)", "Defence", BOTH, _add(ap_mod=-1)),
    Variant("dmg-1", "-1 Damage", "Defence", BOTH, _set(damage_reduction=1)),
    Variant("halve", "Halve Damage", "Defence", BOTH, _set(halve_damage=True)),
    Variant("fnp6", "Feel No Pain 6+", "Defence", BOTH, _set(feel_no_pain=6)),
    Variant("fnp5", "Feel No Pain 5+", "Defence", BOTH, _set(feel_no_pain=5)),
    Variant("fnp4", "Feel No Pain 4+", "Defence", BOTH, _set(feel_no_pain=4)),
    Variant("inv5", "5+ invulnerable", "Defence", BOTH, _set(invuln_override=5)),
    Variant("inv4", "4+ invulnerable", "Defence", BOTH, _set(invuln_override=4)),
    Variant("t+1", "+1 Toughness", "Defence", BOTH, _add(toughness_mod=1)),
    Variant("sv+1", "+1 Save", "Defence", BOTH, _add(save_char_mod=1)),
]

ATTACKER_VARIANTS: dict[str, Variant] = {v.key: v for v in _A}
DEFENDER_VARIANTS: dict[str, Variant] = {v.key: v for v in _D}


def combined(att: Variant, dfn: Variant) -> Modifiers:
    """Modifiers for one test: one attacker variant plus one defender variant."""
    m = Modifiers()
    att.apply(m)
    dfn.apply(m)
    return m
