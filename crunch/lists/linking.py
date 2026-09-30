"""Link a parsed army list to Wahapedia datasheets, and turn list units into what the engine needs."""
from __future__ import annotations

import re

from crunch.core.models import Target, TargetGroup, Unit, Weapon, WeaponLoad
from crunch.data.wahapedia import Wahapedia
from crunch.lists.model import ArmyList, ListUnit
from crunch.util import norm


def link_datasheets(army: ArmyList, wd: Wahapedia) -> ArmyList:
    """Attach a datasheet to every unit, give duplicates unique labels, note unmatched wargear."""
    seen: dict[str, int] = {}
    totals: dict[str, int] = {}
    for u in army.units:
        totals[u.name] = totals.get(u.name, 0) + 1
    for u in army.units:
        did = wd.find(u.name, army.faction_id)
        u.datasheet = wd.unit(did) if did else None
        seen[u.name] = seen.get(u.name, 0) + 1
        u.label = u.name + (f" #{seen[u.name]}" if totals[u.name] > 1 else "")
        if u.datasheet:
            u.unmatched_gear = sorted({n for n, _ in all_gear(u) if not match_weapon(n, u.datasheet)})
    return army


def all_gear(u: ListUnit) -> list[tuple[str, int]]:
    g = [(n, c) for n, c in u.unit_gear]
    for m in u.models:
        g += [(n, c * m.count) for n, c in m.gear]
    return g


def _keys(name: str) -> set[str]:
    k = norm(name)
    return {k, k.rstrip("s"), re.sub(r"s(?=[a-z]*$)", "", k)}


def match_weapon(item: str, ds: Unit) -> list[Weapon]:
    """All weapon profiles on the datasheet that a list item refers to."""
    keys = _keys(item)
    hits = [w for w in ds.weapons if _keys(w.name) & keys or _keys(w.base_name) & keys]
    if hits:
        return hits
    if " and " in item.lower():                  # "Bladevanes and chainsnares" / "1 Blast pistol and 1 Power weapon"
        out = []
        for part in re.split(r"\s+and\s+", item, flags=re.I):
            part = re.sub(r"^\d+\s*x?\s+", "", part.strip())
            out += match_weapon(part, ds)
        return out
    return []


def weapon_loads(u: ListUnit, source: str = "") -> list[WeaponLoad]:
    """Weapons the unit carries, with how many models/instances have each profile."""
    if not u.datasheet:
        return []
    counts: dict[str, int] = {}
    order: dict[str, Weapon] = {}
    for name, cnt in all_gear(u):
        for w in match_weapon(name, u.datasheet):
            counts[w.name] = counts.get(w.name, 0) + cnt
            order.setdefault(w.name, w)
    if not order:   # gear not itemised in the list (e.g. "Melee Weapons"): assume the datasheet loadout
        for w in u.datasheet.weapons:
            counts[w.name] = u.model_count
            order[w.name] = w
    return [WeaponLoad(order[n], counts[n], source or u.label) for n in order]


def target_for(bodyguard: ListUnit, attached: list[ListUnit] | None = None) -> Target:
    """Defending unit as allocation groups: bodyguard profiles, then attached characters."""
    attached = [a for a in (attached or []) if a]
    groups: list[TargetGroup] = []

    def add(u: ListUnit, character: bool):
        ds = u.datasheet
        if not ds:
            return
        if not u.models:
            groups.append(TargetGroup(ds.models[0], 1, character, u.label))
            return
        merged: dict[str, TargetGroup] = {}
        for m in u.models:
            p = ds.profile(m.name)
            if p.name in merged:
                merged[p.name].count += m.count
            else:
                merged[p.name] = TargetGroup(p, m.count, character, p.name.title() if p.name.isupper() else p.name)
        groups.extend(merged.values())

    add(bodyguard, bodyguard.is_character and not attached)
    kws = set(bodyguard.datasheet.keywords) if bodyguard.datasheet else set()
    name = bodyguard.label
    for a in attached:
        if a.datasheet:
            add(a, True)
            kws |= a.datasheet.keywords
            name += f" + {a.label}"
    return Target(name, groups, kws)
