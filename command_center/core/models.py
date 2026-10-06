"""Game objects the engine works on: weapons, model profiles, units, and what gets simulated."""
from __future__ import annotations

import re
from dataclasses import dataclass

from command_center.core.dice import Dice
from command_center.core.keywords import WeaponKeywords
from command_center.util import norm


# -----------------------------------------------------------------------------
# datasheet-level objects
# -----------------------------------------------------------------------------
@dataclass
class Weapon:
    name: str
    type: str            # "Ranged" / "Melee"
    range: str
    A: Dice
    skill: int | None    # BS/WS target (None = N/A, e.g. Torrent)
    S: int
    AP: int              # stored as a positive number: AP-2 -> 2
    D: Dice
    keywords: WeaponKeywords

    @property
    def melee(self) -> bool:
        return self.type.lower() == "melee"

    @property
    def max_range(self) -> float | None:
        """Range in inches ('24"' -> 24.0); None when it has none written (Melee, N/A)."""
        m = re.search(r"\d+(?:\.\d+)?", self.range)
        return float(m.group()) if m else None

    @property
    def base_name(self) -> str:
        """'Plasma decimator – supercharge' -> 'Plasma decimator'."""
        return re.split(r"\s+[–—-]\s+", self.name, maxsplit=1)[0]

    def summary(self) -> str:
        sk = f"{self.skill}+" if self.skill else "N/A"
        tags = ", ".join(self.keywords.tags())
        return (f"{self.name} [{self.type}] A{self.A} {'WS' if self.melee else 'BS'}{sk} "
                f"S{self.S} AP-{self.AP} D{self.D}" + (f"  <{tags}>" if tags else ""))


@dataclass
class ModelProfile:
    name: str
    M: str
    T: int
    Sv: int
    inv: int | None
    W: int
    base: str = ""       # base size as Wahapedia writes it: "32mm", "120 x 92mm", "Use model"


@dataclass
class Unit:
    id: str
    name: str
    faction_id: str
    models: list[ModelProfile]
    weapons: list[Weapon]
    keywords: set[str]
    is_support: bool = False

    @property
    def is_character(self) -> bool:
        return "character" in self.keywords

    def profile(self, model_name: str = "") -> ModelProfile:
        n = norm(model_name)
        for m in self.models:
            if n and norm(m.name) in (n, n.rstrip("s")):
                return m
        return self.models[0]


# -----------------------------------------------------------------------------
# what gets simulated
# -----------------------------------------------------------------------------
@dataclass
class WeaponLoad:
    weapon: Weapon
    count: int          # number of models/instances firing this weapon
    source: str = ""    # which unit it belongs to (for display)


@dataclass
class TargetGroup:
    profile: ModelProfile
    count: int
    character: bool = False
    label: str = ""


@dataclass
class Target:
    name: str
    groups: list[TargetGroup]
    keywords: set[str]
    model_order: list[int] | None = None   # group index of each model, in allocation order
    precision_pos: int | None = None       # position in model_order that [PRECISION] attacks go to first

    @property
    def models(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def toughness(self) -> int:
        """Toughness held by the majority of non-CHARACTER models (ties: the higher value)."""
        body = [g for g in self.groups if not g.character] or self.groups
        votes: dict[int, int] = {}
        for g in body:
            votes[g.profile.T] = votes.get(g.profile.T, 0) + g.count
        return max(votes, key=lambda t: (votes[t], t))

    def default_order(self) -> list[int]:
        """Non-CHARACTER models first, CHARACTERs last."""
        body = [i for i, g in enumerate(self.groups) if not g.character for _ in range(g.count)]
        chars = [i for i, g in enumerate(self.groups) if g.character for _ in range(g.count)]
        return body + chars

    def order(self) -> list[int]:
        o = self.model_order
        if o is None or sorted(o) != sorted(self.default_order()):
            return self.default_order()
        return list(o)
