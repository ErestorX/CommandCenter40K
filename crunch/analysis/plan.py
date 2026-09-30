"""Per-unit test plans for the sweep, saved to user_data/test_plans.json.

A plan says whether a unit takes part, which Leader/Support it uses, which weapons fire, which
phases an attacker is tested in, and which individual scenarios (variants) are tried.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from crunch import config
from crunch.analysis.variants import BASELINE, MELEE, PHASES, RANGED
from crunch.core.models import WeaponLoad
from crunch.data.wahapedia import Wahapedia
from crunch.lists import ArmyList, ListUnit, target_for, weapon_loads

ATTACKER, DEFENDER = "attacker", "defender"
DEFAULT = "(list default)"      # Leader/Support choice meaning "whatever the list says"
NONE = "None"


@dataclass
class UnitPlan:
    included: bool = False
    leader: str = DEFAULT
    support: str = DEFAULT
    # attacker: phase -> tested?; variants per phase. defender: variants under the key "any".
    phases: dict[str, bool] = field(default_factory=lambda: {RANGED: True, MELEE: True})
    variants: dict[str, list[str]] = field(default_factory=dict)
    weapons: dict[str, bool] = field(default_factory=dict)   # "source|weapon name" -> on/off override

    def variant_keys(self, phase: str) -> list[str]:
        return self.variants.setdefault(phase, [BASELINE])

    def toggle_variant(self, phase: str, key: str) -> None:
        keys = self.variant_keys(phase)
        if key in keys:
            keys.remove(key)
        else:
            keys.append(key)


class PlanStore:
    """Plans keyed by list file, role and unit label; saved as JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.USER_DATA_DIR / "test_plans.json"
        self._plans: dict[str, UnitPlan] = {}
        self._load()

    @staticmethod
    def key(army: ArmyList, role: str, unit: ListUnit) -> str:
        return f"{army.path.name}|{role}|{unit.label}"

    def get(self, army: ArmyList, role: str, unit: ListUnit) -> UnitPlan:
        k = self.key(army, role, unit)
        if k not in self._plans:
            p = UnitPlan()
            if role == DEFENDER:
                p.phases = {}
                p.variants = {"any": [BASELINE]}
            self._plans[k] = p
        return self._plans[k]

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, d in raw.items():
            try:
                self._plans[k] = UnitPlan(**d)
            except TypeError:
                continue            # written by an older/newer version: ignore that entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(p) for k, p in self._plans.items()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.path)


# -----------------------------------------------------------------------------
# plan -> engine inputs
# -----------------------------------------------------------------------------
def resolve_attached(army: ArmyList, unit: ListUnit, plan: UnitPlan, wd: Wahapedia) -> list[ListUnit]:
    """Leader then Support character for this plan (list defaults unless overridden)."""
    out = []
    for kind, choice in (("leader", plan.leader), ("support", plan.support)):
        support = kind == "support"
        if choice == DEFAULT:
            u = army.default_attached(unit, wd, support=support)
        elif choice == NONE:
            u = None
        else:
            u = next((o for o in army.attach_options(unit, wd, support) if o.label == choice), None)
        if u:
            out.append(u)
    return out


def weapon_key(ld: WeaponLoad) -> str:
    return f"{ld.source}|{ld.weapon.name}"


def default_on(loads: list[WeaponLoad]) -> dict[str, bool]:
    """Every weapon on, except alternative profiles of the same weapon (first profile only)."""
    seen, out = set(), {}
    for ld in loads:
        group = (ld.source, ld.weapon.base_name, ld.weapon.melee)
        out[weapon_key(ld)] = group not in seen
        seen.add(group)
    return out


def all_loads(unit: ListUnit, attached: list[ListUnit]) -> list[WeaponLoad]:
    loads = weapon_loads(unit)
    for a in attached:
        loads += weapon_loads(a)
    return loads


def active_loads(unit: ListUnit, attached: list[ListUnit], plan: UnitPlan, phase: str) -> list[WeaponLoad]:
    """Weapons that fire in `phase` for this plan."""
    loads = all_loads(unit, attached)
    on = default_on(loads)
    on.update({k: v for k, v in plan.weapons.items() if k in on})
    want_melee = phase == MELEE
    return [ld for ld in loads if ld.weapon.melee == want_melee and on[weapon_key(ld)]]


def unit_points(unit: ListUnit, attached: list[ListUnit]) -> int:
    return unit.points + sum(a.points for a in attached)


def display_name(unit: ListUnit, attached: list[ListUnit]) -> str:
    return " + ".join([unit.label] + [a.label for a in attached])


def defender_target(unit: ListUnit, attached: list[ListUnit]):
    return target_for(unit, attached)


def test_count(role: str, plan: UnitPlan) -> int:
    if role == DEFENDER:
        return len(plan.variant_keys("any"))
    return sum(len(plan.variant_keys(ph)) for ph in PHASES if plan.phases.get(ph))
