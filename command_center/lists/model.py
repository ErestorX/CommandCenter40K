"""Format-independent army list: what every parser produces."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from command_center.core.models import Unit
from command_center.data.wahapedia import Wahapedia
from command_center.util import norm


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
    force_disposition: str = ""        # "Priority Assets" (sets the primary mission and battlefield layouts)

    def unit(self, uid: int) -> ListUnit:
        return next(u for u in self.units if u.uid == uid)

    def attach_options(self, bodyguard: ListUnit, wd: Wahapedia, support: bool = False) -> list[ListUnit]:
        """Characters in this list that can be attached to `bodyguard` (Leaders, or Support characters)."""
        if not bodyguard.datasheet:
            return []
        return [u for u in self.units
                if u is not bodyguard and u.is_character and u.datasheet and u.is_support == support
                and wd.can_lead(u.datasheet.id, bodyguard.datasheet.id)]

    def refers_to(self, ref: str, unit: ListUnit) -> bool:
        """Does a list reference like "Blood Angels Captain[2]" (or plain "Archon") mean `unit`?"""
        m = re.match(r"^(.*?)\s*\[(\d+)\]\s*$", ref or "")
        base, idx = (m.group(1), int(m.group(2))) if m else (ref or "", None)
        if norm(base) != norm(unit.name):
            return False
        if idx is None:
            return True
        same = [u for u in self.units if norm(u.name) == norm(unit.name)]
        return unit in same and same.index(unit) + 1 == idx

    def default_attached(self, bodyguard: ListUnit, wd: Wahapedia, support: bool = False) -> ListUnit | None:
        """The Leader (or Support character) the list attaches to this unit, if any.

        Uses the bodyguard's "Led by / Leader / Supported by" lines, or failing that a character's
        "Leading / Supporting" line pointing at this unit."""
        options = self.attach_options(bodyguard, wd, support)
        for ref in bodyguard.attached_names:
            named = [u for u in options if self.refers_to(ref, u)]
            best = [u for u in named if not u.leading_name or self.refers_to(u.leading_name, bodyguard)]
            if best or named:
                return (best or named)[0]
        for u in options:        # only a character line that can mean this unit and no other
            if (u.leading_name and self.refers_to(u.leading_name, bodyguard)
                    and self._unambiguous(u.leading_name)
                    and not any(self.refers_to(r, u) for o in self.units if o is not bodyguard
                                for r in o.attached_names)):
                return u
        return None

    def _unambiguous(self, ref: str) -> bool:
        """True if the reference has an index or names a unit that appears only once."""
        if re.search(r"\[\d+\]\s*$", ref or ""):
            return True
        return sum(norm(u.name) == norm(ref) for u in self.units) == 1

    @property
    def detachment_names(self) -> list[str]:
        clean = re.sub(r"\s*\[[^\]]*\]", "", self.detachment)
        return [d.strip() for d in clean.split(",") if d.strip()]

    @property
    def unmatched_units(self) -> list[str]:
        return [u.name for u in self.units if not u.datasheet]
