"""Saved army plans: the Engagement Optimizer's 1st / 2nd target for every attacker, one plan per pair of army
lists (attacker list, defender list), saved to user_data/army_plans.json each time it is recomputed.

Other windows read it through the shared store (ctx.army_plans):

    plan = ctx.army_plans.get(attacker_list, defender_list)       # SavedPlan or None
    plan.targets_of("Kabalite Warriors")      # [1st target, 2nd target] of the unit's group
    plan.attackers_of("Mephiston")            # [(entry, "primary" | "secondary"), ...]
    unsubscribe = ctx.army_plans.subscribe(callback)   # callback(plan) whenever a plan changes

Units are named as in the lists ("Kabalite Warriors", "Blood Angels Captain #1"); any unit of a
group (a unit and the characters joining it) finds the group.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from command_center import config


def units_of(name: str) -> list[str]:
    """"Kabalite Warriors + Archon" -> ["Kabalite Warriors", "Archon"]."""
    return [p.strip() for p in name.split(" + ") if p.strip()]


@dataclass
class PlanTarget:
    name: str                     # the defending group, as the Engagement Optimizer names it
    units: list[str]              # its units
    frac_wounds: float            # expected share of its wounds removed by the attacker
    pts_per_100: float            # points removed per 100 attacker points


@dataclass
class PlanEntry:
    attacker: str
    units: list[str]
    primary: PlanTarget | None = None
    secondary: PlanTarget | None = None

    @property
    def targets(self) -> list[PlanTarget]:
        return [t for t in (self.primary, self.secondary) if t]


@dataclass
class SavedPlan:
    attacker_list: str            # list file names: the pair this plan belongs to
    defender_list: str
    entries: list[PlanEntry]
    uncovered: list[str] = field(default_factory=list)      # defending groups nobody targets
    settings: dict = field(default_factory=dict)            # phase, attacker / defender modes, weight
    updated: str = ""

    @property
    def key(self) -> str:
        return pair_key(self.attacker_list, self.defender_list)

    def entry_for(self, unit: str) -> PlanEntry | None:
        """The attacking group containing `unit` (a unit name, or a whole group name)."""
        wanted = set(units_of(unit))
        return next((e for e in self.entries if wanted <= set(e.units) or e.attacker == unit), None)

    def targets_of(self, unit: str) -> list[PlanTarget]:
        """1st then 2nd target of the attacking group containing `unit` ([] if it has none)."""
        e = self.entry_for(unit)
        return e.targets if e else []

    def attackers_of(self, unit: str) -> list[tuple[PlanEntry, str]]:
        """Attacking groups sent at the defending group containing `unit`, with "primary"/"secondary"."""
        wanted = set(units_of(unit))
        out = []
        for e in self.entries:
            for rank, t in (("primary", e.primary), ("secondary", e.secondary)):
                if t and (wanted <= set(t.units) or t.name == unit):
                    out.append((e, rank))
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SavedPlan":
        def target(t):
            return PlanTarget(**t) if t else None
        entries = [PlanEntry(e["attacker"], e["units"], target(e.get("primary")), target(e.get("secondary")))
                   for e in d.get("entries", [])]
        return cls(d["attacker_list"], d["defender_list"], entries, d.get("uncovered", []),
                   d.get("settings", {}), d.get("updated", ""))


def pair_key(attacker_list: str | Path, defender_list: str | Path) -> str:
    return f"{Path(attacker_list).name}|{Path(defender_list).name}"


class ArmyPlanStore:
    """Plans keyed by pair of lists, saved as JSON; listeners hear about every change."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.USER_DATA_DIR / "army_plans.json"
        self._plans: dict[str, SavedPlan] = {}
        self._listeners: list[Callable[[SavedPlan], None]] = []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for k, d in raw.items():
            try:
                self._plans[k] = SavedPlan.from_dict(d)
            except (KeyError, TypeError):
                continue                    # unreadable entry: ignore it

    def get(self, attacker_list: str | Path, defender_list: str | Path) -> SavedPlan | None:
        return self._plans.get(pair_key(attacker_list, defender_list))

    def put(self, plan: SavedPlan) -> None:
        """Store, save to disk and tell every listener (unchanged plans are not rewritten)."""
        old = self._plans.get(plan.key)
        if old and _same(old, plan):
            return
        plan.updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._plans[plan.key] = plan
        self.save()
        for fn in list(self._listeners):
            fn(plan)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: p.to_dict() for k, p in self._plans.items()}, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def subscribe(self, listener: Callable[[SavedPlan], None]) -> Callable[[], None]:
        """Call `listener(plan)` on every change; returns the function that unsubscribes it."""
        self._listeners.append(listener)

        def unsubscribe():
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe


def _same(a: SavedPlan, b: SavedPlan) -> bool:
    da, db = a.to_dict(), b.to_dict()
    da.pop("updated"), db.pop("updated")
    return da == db
