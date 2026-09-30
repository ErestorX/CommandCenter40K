"""Format-independent army list: what every parser produces."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from crunch.core.models import Unit
from crunch.data.wahapedia import Wahapedia
from crunch.util import norm


@dataclass
class ListModel:
    name: str
    count: int
    gear: list[tuple[str, int]]


@dataclass
class ListUnit:
    uid: int
    name: str
    points: int
    category: str
    models: list[ListModel]
    unit_gear: list[tuple[str, int]]
    attached_names: list[str] = field(default_factory=list)   # "• Leader: Archon" / "• Support: …" under a bodyguard
    leading_name: str = ""         # "• Leading: Incubi" under a character
    datasheet: Unit | None = None
    label: str = ""                # unique display name ("Ravager #2")
    unmatched_gear: list[str] = field(default_factory=list)

    @property
    def model_count(self) -> int:
        return sum(m.count for m in self.models) or 1

    @property
    def is_character(self) -> bool:
        return bool(self.datasheet and self.datasheet.is_character)

    @property
    def is_support(self) -> bool:
        return bool(self.datasheet and self.datasheet.is_support)


@dataclass
class ArmyList:
    path: Path
    title: str
    faction: str
    faction_id: str | None
    detachment: str
    points: int
    units: list[ListUnit]

    def unit(self, uid: int) -> ListUnit:
        return next(u for u in self.units if u.uid == uid)

    def attach_options(self, bodyguard: ListUnit, wd: Wahapedia, support: bool = False) -> list[ListUnit]:
        """Characters in this list that can be attached to `bodyguard` (Leaders, or Support characters)."""
        if not bodyguard.datasheet:
            return []
        return [u for u in self.units
                if u is not bodyguard and u.is_character and u.datasheet and u.is_support == support
                and wd.can_lead(u.datasheet.id, bodyguard.datasheet.id)]

    def default_attached(self, bodyguard: ListUnit, wd: Wahapedia, support: bool = False) -> ListUnit | None:
        """The Leader (or Support character) the list attaches to this unit, if any."""
        options = self.attach_options(bodyguard, wd, support)
        for name in bodyguard.attached_names:
            exact = [u for u in options if norm(u.name) == norm(name)]
            best = [u for u in exact if norm(u.leading_name) in ("", norm(bodyguard.name))]
            if best or exact:
                return (best or exact)[0]
        return None

    @property
    def detachment_names(self) -> list[str]:
        clean = re.sub(r"\s*\[[^\]]*\]", "", self.detachment)
        return [d.strip() for d in clean.split(",") if d.strip()]

    @property
    def unmatched_units(self) -> list[str]:
        return [u.name for u in self.units if not u.datasheet]
