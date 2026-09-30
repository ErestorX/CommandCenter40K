"""Modifiers applied to one attack sequence.

This is also the target schema for abilities/stratagems extracted from rules text: an effect
should be expressible as field changes here (plus conditions) to be simulated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class Modifiers:
    # --- attacker ---
    hit_mod: int = 0                 # +1 / -1 to hit (net capped at +/-1)
    wound_mod: int = 0               # +1 / -1 to wound (capped at +/-1)
    reroll_hits: str = "none"        # none | ones | fails
    reroll_wounds: str = "none"      # none | ones | fails
    crit_hit_on: int = 6
    crit_wound_on: int = 6
    extra_ap: int = 0
    extra_damage: int = 0
    extra_attacks: int = 0           # per model
    add_lethal_hits: bool = False
    add_sustained_hits: int = 0
    add_devastating_wounds: bool = False
    add_twin_linked: bool = False
    # --- situation ---
    stationary: bool = False         # Heavy
    charged: bool = False            # Lance
    half_range: bool = False         # Melta, Rapid Fire
    beyond_12: bool = False          # Conversion
    not_visible: bool = False        # Indirect Fire: target gets cover, hits of 1-5 fail, no hit re-rolls
    # --- defender ---
    cover: bool = False
    save_mod: int = 0
    invuln_override: int | None = None
    feel_no_pain: int | None = None
    damage_reduction: int = 0
    halve_damage: bool = False
    toughness_mod: int = 0

    @classmethod
    def from_pairs(cls, pairs: list[str]) -> "Modifiers":
        m = cls()
        for p in pairs:
            k, _, v = p.partition("=")
            k = k.strip()
            if not hasattr(m, k):
                raise KeyError(f"Unknown modifier {k!r}. Valid: {', '.join(f.name for f in fields(cls))}")
            cur = getattr(m, k)
            if isinstance(cur, bool):
                val = v.strip().lower() in ("1", "true", "yes", "y", "")
            elif isinstance(cur, str):
                val = v.strip()
            else:
                val = int(v) if v.strip() else None
            setattr(m, k, val)
        return m

    def tags(self) -> list[str]:
        default = Modifiers()
        return [f"{k}={v}" for k, v in asdict(self).items() if v != getattr(default, k)]
