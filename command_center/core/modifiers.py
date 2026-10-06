"""Modifiers applied to one attack sequence.

This is also the target schema for abilities/stratagems extracted from rules text: an effect
should be expressible as field changes here (plus conditions) to be simulated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

from command_center.core.dice import Dice, DiceMod


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
    add_blast: int = 0               # grants [BLAST X] / [CLEAVE X]: +X attacks per full 5 models in the target
    add_rapid_fire: Dice = field(default_factory=Dice)       # grants [RAPID FIRE X] to ranged weapons
    skill_mod: int = 0               # +1 improves the attacker's BS/WS by 1 (4+ -> 3+), -1 worsens it
    plunging_fire: bool = False      # Plunging Fire: improve BS of ranged attacks by 1
    ignores_cover: bool = False      # ranged attacks ignore the Benefit of Cover, and see a Hidden target
    ignores_skill_maluses: bool = False     # whatever worsens the BS/WS is ignored (cover, -1 Skill)
    ignores_hit_maluses: bool = False       # negative modifiers to the hit roll are ignored
    ignores_wound_maluses: bool = False     # negative modifiers to the wound roll are ignored
    effective_range: float | None = None    # inches to the target; None = no distance rule comes into play.
    #                                         Below 2": only [CLOSE-QUARTERS] weapons shoot
    not_visible: bool = False        # only [INDIRECT FIRE] weapons shoot: 6s hit, unmodifiable, no hit re-rolls
    spotted: bool = False            # ...unless the target is spotted: hits on a fixed 4+
    # --- defender ---
    cover: bool = False
    hidden_beyond: float | None = None      # Hidden: not visible to attackers further than this many inches
    enemy_skill_mod: int = 0         # defender's modifier to the attackers' BS/WS: -1 worsens it
    to_be_hit_mod: int = 0           # defender's modifier to incoming hit rolls: -1 to be hit
    to_be_wounded_mod: int = 0       # defender's modifier to incoming wound rolls: -1 to be wounded
    save_mod: int = 0                # modifier to the save roll (capped at +1)
    save_char_mod: int = 0           # +1 improves the Save characteristic (3+ -> 2+, never better than 2+)
    wound_minus_if_stronger: str = "none"   # none | gt | ge   -1 to be wounded if S > T (gt) or S >= T (ge)
    ap_mod: int = 0                  # defender-side change to incoming AP: -1 worsens it (AP-2 -> AP-1)
    extra_invuln: int | None = None  # additional invulnerable save: the better of it and the model's own
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
                val = (float(v) if "." in v else int(v)) if v.strip() else None
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
