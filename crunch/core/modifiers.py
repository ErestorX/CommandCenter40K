"""Modifiers applied to one attack sequence.

This is also the target schema for abilities/stratagems extracted from rules text: an effect
should be expressible as field changes here (plus conditions) to be simulated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

from crunch.core.dice import Dice, DiceMod


@dataclass
class Modifiers:
    # --- attacker ---
    hit_mod: int = 0                 # attacker's +1 / -1 to hit (net of all hit modifiers capped at +/-1)
    wound_mod: int = 0               # +1 / -1 to wound (capped at +/-1)
    wound_plus_if_weaker: str = "none"      # none | lt | le   +1 to wound if S < T (lt) or S <= T (le)
    reroll_hits: str = "none"        # none | ones | ones_twos | fails   (only failed rolls are re-rolled)
    reroll_wounds: str = "none"      # none | ones | ones_twos | fails
    crit_hit_on: int = 6
    crit_wound_on: int = 6
    extra_strength: int = 0          # added to the weapon's Strength (never below 1)
    extra_ap: int = 0                # +1 improves AP by 1 (AP-1 -> AP-2), -1 worsens it
    extra_damage: DiceMod = field(default_factory=DiceMod)    # added to each attack's Damage ("+1", "+D3", "-1")
    extra_attacks: DiceMod = field(default_factory=DiceMod)   # added to each model's Attacks ("+1", "+D3")
    add_lethal_hits: bool = False
    add_sustained_hits: Dice = field(default_factory=Dice)   # grants [SUSTAINED HITS X]: 1, 2, D3
    add_devastating_wounds: bool = False
    add_precision: bool = False
    # --- situation ---
    stationary: bool = False         # Heavy: +1 to hit rolls
    plunging_fire: bool = False      # Plunging Fire: improve BS of ranged attacks by 1
    charged: bool = False            # Lance
    half_range: bool = False         # Melta, Rapid Fire
    beyond_12: bool = False          # Conversion
    not_visible: bool = False        # Indirect Fire: only 6s hit, unmodifiable, no hit re-rolls
    spotted: bool = False            # ...unless the target is spotted: hits on a fixed 4+
    # --- defender ---
    cover: bool = False
    to_be_hit_mod: int = 0           # defender's modifier to incoming hit rolls: -1 to be hit
    save_mod: int = 0                # modifier to the save roll (capped at +1)
    save_char_mod: int = 0           # +1 improves the Save characteristic (3+ -> 2+, never better than 2+)
    wound_minus_if_stronger: str = "none"   # none | gt | ge   -1 to be wounded if S > T (gt) or S >= T (ge)
    ap_mod: int = 0                  # defender-side change to incoming AP: -1 worsens it (AP-2 -> AP-1)
    invuln_override: int | None = None
    feel_no_pain: int | None = None
    fnp_against: str = "all"         # all | psychic | mortal | psychic_mortal   (mortal = Devastating Wounds)
    damage_reduction: int = 0
    halve_damage: bool = False
    toughness_mod: int = 0           # added to the unit's Toughness

    @classmethod
    def from_pairs(cls, pairs: list[str]) -> "Modifiers":
        m = cls()
        for p in pairs:
            k, _, v = p.partition("=")
            k = k.strip()
            if not hasattr(m, k):
                raise KeyError(f"Unknown modifier {k!r}. Valid: {', '.join(f.name for f in fields(cls))}")
            cur = getattr(m, k)
            if isinstance(cur, DiceMod):
                val = DiceMod.parse(v)
            elif isinstance(cur, Dice):
                val = Dice.parse(v)
            elif isinstance(cur, bool):
                val = v.strip().lower() in ("1", "true", "yes", "y", "")
            elif isinstance(cur, str):
                val = v.strip()
            else:
                val = int(v) if v.strip() else None
            setattr(m, k, val)
        return m

    def tags(self) -> list[str]:
        default = Modifiers()
        out = []
        for f in fields(self):
            v = getattr(self, f.name)
            if v != getattr(default, f.name):
                out.append(f"{f.name}={v}")
        return out
