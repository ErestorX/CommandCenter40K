"""Catalogue of modifiers the Engagement Optimizer can test, and how a test's modifiers are combined.

A test is a package of modifiers applied together (an empty package = no modifiers). Modifiers that
share a `slot` are alternatives (re-roll 1s / re-roll failed): a package holds at most one of them.
A modifier listed for some phases only is dropped from the package in the other phases.

A modifier that takes a value (Sustained Hits X, Effective range X) has a `param`, and is written
"key=value" in a package ("sustained=D3", 'range=12"'); the others are written by their key alone.

Add a modifier by adding a Variant to ATTACKER_VARIANTS or DEFENDER_VARIANTS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from command_center.core.dice import Dice, DiceMod
from command_center.core.modifiers import Modifiers

RANGED, MELEE = "ranged", "melee"
PHASES = (RANGED, MELEE)
PHASE_LABEL = {RANGED: "Shooting", MELEE: "Fight"}

NO_MODIFIERS = "No modifiers"


@dataclass(frozen=True)
class Param:
    """The value a modifier takes: picked among `choices` or typed."""
    kind: str                     # roll | amount | dice | int | malus | count | inches | range | choice
    choices: tuple[str, ...]
    default: str

    def parse(self, text: str):
        """The value to apply, or raises ValueError. A value that would change nothing is refused."""
        t = str(text).strip()
        if self.kind == "roll":                         # "5+" (or "5"): a roll needed
            n = int(t.rstrip("+"))
            if not 2 <= n <= 6:
                raise ValueError(text)
            return n
        if self.kind == "amount":                       # "1", "D3"
            v = Dice.parse(t)
        elif self.kind == "dice":                       # "+1", "-1", "+D3"
            v = DiceMod.parse(t)
        elif self.kind in ("int", "malus", "count"):    # "+1" / "-1"; a malus is always negative; "2"
            v = int(t.replace(" ", ""))
            v = -abs(v) if self.kind == "malus" else v
            if self.kind == "count" and v < 0:
                raise ValueError(text)
        elif self.kind in ("inches", "range"):          # '15"'; a range can also be '<2"'
            t = t.rstrip('"').strip().replace(",", ".")
            below = self.kind == "range" and t.startswith("<")
            v = float(t[1:]) - 0.5 if below else float(t)
            if v < 0:
                raise ValueError(text)
        elif self.kind == "choice":
            v = next((c for c in self.choices if c.lower() == t.lower()), None)
        else:
            raise ValueError(self.kind)
        if not v:
            raise ValueError(text)
        return v

    def canonical(self, text: str) -> str:
        """One spelling per value ("d3" -> "D3", "1" -> "+1"), so that equal tests compare equal."""
        v = self.parse(text)
        if self.kind == "roll":
            return f"{v}+"
        if self.kind in ("int", "malus"):
            return f"{v:+d}"
        if self.kind in ("inches", "range"):
            return '<2"' if self.kind == "range" and v < 2 else f'{v:g}"'
        return str(v)


@dataclass(frozen=True)
class Variant:
    key: str
    label: str                           # with "{v}" where the value goes, for a modifier that takes one
    group: str
    phases: tuple[str, ...]              # phases where it means something
    apply: Callable[..., None]           # (Modifiers), or (Modifiers, value) with a param
    slot: str = ""                       # variants sharing a slot are alternatives
    param: Param | None = None

    @property
    def name(self) -> str:
        """The label without a value: "Sustained Hits", "Attacks"."""
        return " ".join(self.label.replace("{v}", "").split())

    def label_for(self, value: str = "") -> str:
        return self.label.format(v=value or self.param.default) if self.param else self.label

    def mod(self, value: str = "") -> str:
        """How it is written in a package. Raises ValueError for a value it can't take."""
        return f"{self.key}={self.param.canonical(value or self.param.default)}" if self.param else self.key

    def apply_to(self, m: Modifiers, value: str = "") -> None:
        if self.param:
            self.apply(m, self.param.parse(value or self.param.default))
        else:
            self.apply(m)


def split(mod: str) -> tuple[str, str]:
    """"sustained=D3" -> ("sustained", "D3"); "lethal" -> ("lethal", "")."""
    key, _, value = mod.partition("=")
    return key, value


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


def _value(field: str, convert: Callable = lambda v: v, add: bool = False) -> Callable[[Modifiers, object], None]:
    """Sets (or adds to) one field from the modifier's value."""
    def f(m: Modifiers, v):
        setattr(m, field, getattr(m, field) + convert(v) if add else convert(v))
    return f


def _p(kind: str, default: str, *choices: str) -> Param:
    return Param(kind, choices, default)


BOTH = PHASES
ROLLS = ("6+", "5+", "4+", "3+", "2+")
_A = [
    # hit roll
    Variant("hit+1", "+1 to hit", "Hit", BOTH, _add(hit_mod=1)),
    Variant("rr_hit_1", "Re-roll 1s to hit", "Hit", BOTH, _set(reroll_hits="ones"), "reroll_hits"),
    Variant("rr_hit_12", "Re-roll 1s & 2s to hit", "Hit", BOTH, _set(reroll_hits="ones_twos"), "reroll_hits"),
    Variant("rr_hit_all", "Re-roll failed hits", "Hit", BOTH, _set(reroll_hits="fails"), "reroll_hits"),
    Variant("crit_hit", "Crit hits on {v}", "Hit", BOTH, _value("crit_hit_on"), param=_p("roll", "5+", *ROLLS[1:])),
    Variant("sustained", "Sustained Hits {v}", "Hit", BOTH, _value("add_sustained_hits"),
            param=_p("amount", "1", "1", "2", "D3")),
    Variant("lethal", "Lethal Hits", "Hit", BOTH, _set(add_lethal_hits=True)),
    # wound roll
    Variant("wound+1", "+1 to wound", "Wound", BOTH, _add(wound_mod=1), "wound+1"),
    Variant("wound+1_weaker", "+1 to wound if S < T", "Wound", BOTH, _set(wound_plus_if_weaker="lt"), "wound+1"),
    Variant("wound+1_weaker_eq", "+1 to wound if S <= T", "Wound", BOTH, _set(wound_plus_if_weaker="le"),
            "wound+1"),
    Variant("rr_wound_1", "Re-roll 1s to wound", "Wound", BOTH, _set(reroll_wounds="ones"), "reroll_wounds"),
    Variant("rr_wound_all", "Re-roll failed wounds", "Wound", BOTH, _set(reroll_wounds="fails"), "reroll_wounds"),
    Variant("crit_wound", "Crit wounds on {v}", "Wound", BOTH, _value("crit_wound_on"),
            param=_p("roll", "5+", *ROLLS[1:])),
    Variant("dev", "Devastating Wounds", "Wound", BOTH, _set(add_devastating_wounds=True)),
    # characteristics
    Variant("attacks", "{v} Attacks", "Characteristics", BOTH, _value("extra_attacks"),
            param=_p("dice", "+1", "+1", "+2", "+D3", "-1")),
    Variant("strength", "{v} Strength", "Characteristics", BOTH, _value("extra_strength", add=True),
            param=_p("int", "+1", "+1", "+2", "-1")),
    Variant("ap", "{v} AP", "Characteristics", BOTH, _value("extra_ap", add=True),
            param=_p("int", "+1", "+1", "+2", "-1")),
    Variant("damage", "{v} Damage", "Characteristics", BOTH, _value("extra_damage"),
            param=_p("dice", "+1", "+1", "+2", "+D3", "-1")),
    Variant("blast", "Blast / Cleave {v}", "Characteristics", BOTH, _value("add_blast"),
            param=_p("count", "1", "1", "2", "3")),
    Variant("rapid_fire", "Rapid Fire {v}", "Characteristics", (RANGED,), _value("add_rapid_fire"),
            param=_p("amount", "1", "1", "2", "D3")),
    # skill
    Variant("skill+1", "+1 Skill", "Skill", BOTH, _add(skill_mod=1), "skill"),
    Variant("skill-1", "-1 Skill", "Skill", BOTH, _add(skill_mod=-1), "skill"),
    Variant("plunging", "Plunging Fire", "Skill", (RANGED,), _set(plunging_fire=True)),
    Variant("ignores_cover", "Ignores cover", "Skill", (RANGED,), _set(ignores_cover=True)),
    # ignored maluses
    Variant("ignore_skill", "Ignores Skill maluses", "Ignores", BOTH, _set(ignores_skill_maluses=True)),
    Variant("ignore_hit", "Ignores hit maluses", "Ignores", BOTH, _set(ignores_hit_maluses=True)),
    Variant("ignore_wound", "Ignores wound maluses", "Ignores", BOTH, _set(ignores_wound_maluses=True)),
    # range and visibility: without a range, every weapon shoots and no distance rule comes into play
    Variant("range", "Effective range {v}", "Range", (RANGED,), _value("effective_range"),
            param=_p("range", '12"', '<2"', '6"', '9"', '12"', '18"', '24"', '36"', '48"')),
    Variant("not_visible", "Target not visible", "Range", (RANGED,), _set(not_visible=True), "visibility"),
    Variant("spotted", "Not visible, spotted", "Range", (RANGED,), _set(not_visible=True, spotted=True),
            "visibility"),
]

_D = [
    Variant("cover", "Cover", "Defence", (RANGED,), _set(cover=True)),
    Variant("hidden", "Hidden beyond {v}", "Defence", (RANGED,), _value("hidden_beyond"),
            param=_p("inches", '15"', '9"', '12"', '15"', '18"')),
    Variant("skill-1", "-1 Skill (attackers)", "Defence", BOTH, _add(enemy_skill_mod=-1)),
    Variant("hit-1", "-1 to be hit", "Defence", BOTH, _add(to_be_hit_mod=-1)),
    Variant("wound-1", "-1 to be wounded", "Defence", BOTH, _add(to_be_wounded_mod=-1), "wound-1"),
    Variant("wound-1_stronger", "-1 to be wounded if S > T", "Defence", BOTH, _set(wound_minus_if_stronger="gt"),
            "wound-1"),
    Variant("wound-1_stronger_eq", "-1 to be wounded if S >= T", "Defence", BOTH,
            _set(wound_minus_if_stronger="ge"), "wound-1"),
    Variant("ap", "{v} AP", "Defence", BOTH, _value("ap_mod", add=True), param=_p("int", "-1", "-1", "-2")),
    Variant("dmg", "{v} Damage", "Defence", BOTH, _value("damage_reduction", abs),
            param=_p("malus", "-1", "-1", "-2")),
    Variant("halve", "Halve Damage", "Defence", BOTH, _set(halve_damage=True)),
    Variant("fnp", "Feel No Pain {v}", "Defence", BOTH, _value("feel_no_pain"), param=_p("roll", "5+", *ROLLS)),
    Variant("fnp_against", "Feel No Pain against {v}", "Defence", BOTH,
            _value("fnp_against", lambda v: v.replace("/", "_")),
            param=_p("choice", "mortal", "psychic", "mortal", "psychic/mortal")),
    Variant("inv", "Additional {v} invulnerable", "Defence", BOTH, _value("extra_invuln"),
            param=_p("roll", "5+", *ROLLS)),
    Variant("toughness", "{v} Toughness", "Defence", BOTH, _value("toughness_mod", add=True),
            param=_p("int", "+1", "+1", "+2", "-1")),
    Variant("save", "{v} Save", "Defence", BOTH, _value("save_char_mod", add=True),
            param=_p("int", "+1", "+1", "+2", "-1")),
]

ATTACKER_VARIANTS: dict[str, Variant] = {v.key: v for v in _A}
DEFENDER_VARIANTS: dict[str, Variant] = {v.key: v for v in _D}

# how the modifiers of earlier versions, which had one fixed value each, are written now
_RENAMED = {
    "crit_hit_5": "crit_hit=5+", "sustained_1": "sustained=1", "crit_wound_5": "crit_wound=5+",
    "a+1": "attacks=+1", "s+1": "strength=+1", "ap+1": "ap=+1", "d+1": "damage=+1",
    "ap-1": "ap=-1", "dmg-1": "dmg=-1", "fnp6": "fnp=6+", "fnp5": "fnp=5+", "fnp4": "fnp=4+",
    "inv5": "inv=5+", "inv4": "inv=4+", "t+1": "toughness=+1", "sv+1": "save=+1",
}


def _by_key(mods: Iterable[str]) -> dict[str, str]:
    """key -> value, for the modifiers of a package."""
    return dict(split(m) for m in mods)


def toggle(mods: Iterable[str], mod: str, catalogue: dict[str, Variant]) -> list[str]:
    """Add `mod` to a package (replacing any alternative in its slot), or remove it if its modifier is there."""
    mods = list(mods)
    key = split(mod)[0]
    if key in _by_key(mods):
        return [m for m in mods if split(m)[0] != key]
    slot = catalogue[key].slot
    if slot:
        mods = [m for m in mods if catalogue[split(m)[0]].slot != slot]
    return mods + [mod]


def with_value(mods: Iterable[str], mod: str) -> list[str]:
    """The package with the value of `mod` given to its modifier, if it is there."""
    key = split(mod)[0]
    return [mod if split(m)[0] == key else m for m in mods]


def for_phase(mods: Iterable[str], catalogue: dict[str, Variant], phase: str) -> tuple[str, ...]:
    """The package's modifiers that apply in `phase`, in catalogue order (a canonical form)."""
    values = _by_key(mods)
    return tuple(v.mod(values[k]) for k, v in catalogue.items() if k in values and phase in v.phases)


def known(mods: Iterable[str], catalogue: dict[str, Variant]) -> list[str]:
    """`mods` as they are written now, without those the catalogue no longer has or can't read (plans saved
    by an older version)."""
    out = []
    for m in mods:
        key, value = split(_RENAMED.get(m, m))
        try:
            out.append(catalogue[key].mod(value))
        except (KeyError, ValueError):
            pass
    return out


def package_label(mods: Iterable[str], catalogue: dict[str, Variant]) -> str:
    values = _by_key(mods)
    return ", ".join(v.label_for(values[k]) for k, v in catalogue.items() if k in values) or NO_MODIFIERS


def combined(att_mods: Iterable[str], def_mods: Iterable[str]) -> Modifiers:
    """Modifiers for one test: every attacker modifier of its package, then every defender one."""
    m = Modifiers()
    for catalogue, mods in ((ATTACKER_VARIANTS, att_mods), (DEFENDER_VARIANTS, def_mods)):
        for mod in mods:
            key, value = split(mod)
            catalogue[key].apply_to(m, value)
    return m
