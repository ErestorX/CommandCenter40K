"""Weapon abilities parsed from Wahapedia's wargear descriptions ("[LETHAL HITS], [ANTI-INFANTRY 4+]" ...).

Abilities that can be qualified ("LETHAL HITS: non-MONSTER/VEHICLE") keep the qualifier as a string;
`target_matches` decides whether it applies against a given target.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields

from command_center.core.dice import Dice
from command_center.util import strip_html


def target_matches(cond: str, target_keywords: set[str]) -> bool:
    """cond "" = always; "infantry"; "monster/vehicle"; "non-monster/vehicle"."""
    if not cond:
        return True
    neg = cond.startswith("non-")
    wanted = {k.strip() for k in cond[4 if neg else 0:].split("/") if k.strip()}
    hit = bool(wanted & target_keywords)
    return not hit if neg else hit


@dataclass
class WeaponKeywords:
    # abilities that can carry a target qualifier store it as a string ("" = always, None = absent)
    lethal_hits: str | None = None
    devastating_wounds: str | None = None
    sustained_hits: tuple[Dice, str] | None = None
    anti: list[tuple[str, int]] = field(default_factory=list)   # [("infantry", 4)]
    torrent: bool = False
    twin_linked: bool = False
    heavy: bool = False
    lance: bool = False
    ignores_cover: bool = False
    precision: bool = False
    indirect_fire: bool = False
    conversion: bool = False
    assault: bool = False
    pistol: bool = False
    hazardous: bool = False
    extra_attacks: bool = False
    one_shot: bool = False
    psychic: bool = False
    close_quarters: bool = False
    blast: int = 0            # [BLAST] = 1, [BLAST X] = X
    cleave: int = 0
    melta: int = 0
    rapid_fire: Dice = field(default_factory=Dice)
    other: list[str] = field(default_factory=list)

    def tags(self) -> list[str]:
        t = []
        q = lambda c: f" ({c})" if c else ""
        if self.lethal_hits is not None:
            t.append("Lethal Hits" + q(self.lethal_hits))
        if self.sustained_hits:
            t.append(f"Sustained Hits {self.sustained_hits[0]}" + q(self.sustained_hits[1]))
        if self.devastating_wounds is not None:
            t.append("Dev Wounds" + q(self.devastating_wounds))
        t += [f"Anti-{k} {n}+" for k, n in self.anti]
        for name in ("torrent", "twin_linked", "heavy", "lance", "ignores_cover", "precision",
                     "indirect_fire", "conversion", "assault", "pistol", "hazardous",
                     "extra_attacks", "one_shot", "psychic", "close_quarters"):
            if getattr(self, name):
                t.append(name.replace("_", " ").title().replace("Twin Linked", "Twin-linked"))
        if self.blast:
            t.append("Blast" + (f" {self.blast}" if self.blast > 1 else ""))
        if self.cleave:
            t.append(f"Cleave {self.cleave}")
        if self.melta:
            t.append(f"Melta {self.melta}")
        if self.rapid_fire:
            t.append(f"Rapid Fire {self.rapid_fire}")
        return t + self.other


_BOOL_KW = {f.name for f in fields(WeaponKeywords) if f.type in ("bool", bool)}


def parse_weapon_keywords(description: str) -> WeaponKeywords:
    kw = WeaponKeywords()
    for raw in re.split(r"[,\[\]]", strip_html(description).lower()):
        tok = raw.strip()
        if not tok:
            continue
        base, cond = tok, ""
        if ":" in tok:
            base, cond = (p.strip() for p in tok.split(":", 1))
        if m := re.match(r"anti-(.+?)\s+(\d)\+?$", base):
            kw.anti.append((m.group(1).strip(), int(m.group(2))))
        elif m := re.match(r"sustained hits\s+(\S+)$", base):
            kw.sustained_hits = (Dice.parse(m.group(1)), cond)
        elif base == "lethal hits":
            kw.lethal_hits = cond
        elif base == "devastating wounds":
            kw.devastating_wounds = cond
        elif m := re.match(r"rapid fire\s+(\S+)$", base):
            kw.rapid_fire = Dice.parse(m.group(1))
        elif m := re.match(r"melta\s+(\d+)$", base):
            kw.melta = int(m.group(1))
        elif m := re.match(r"blast(?:\s+(\d+))?$", base):
            kw.blast = int(m.group(1) or 1)
        elif m := re.match(r"cleave\s+(\d+)$", base):
            kw.cleave = int(m.group(1))
        else:
            name = base.replace("-", "_").replace(" ", "_")
            if name in _BOOL_KW:
                setattr(kw, name, True)
            else:
                kw.other.append(tok.title())
    return kw
