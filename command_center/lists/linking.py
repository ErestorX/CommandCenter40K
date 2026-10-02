"""Link a parsed army list to Wahapedia datasheets, and turn list units into what the engine needs."""
from __future__ import annotations

import re

from command_center.core.models import Target, TargetGroup, Unit, Weapon, WeaponLoad
from command_center.data.wahapedia import Wahapedia
from command_center.lists.model import ArmyList, ListUnit
from command_center.util import norm


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
    """Defending unit as allocation groups: one group per model line of the list (so sergeants and
    special-weapon models stay distinct, each with its datasheet profile), then attached characters.

    Default allocation order (the defender can change it): rank-and-file first, then single
    special-weapon models, the unit's first-listed model (usually the sergeant) last, characters at the end."""
    attached = [a for a in (attached or []) if a]
    groups: list[TargetGroup] = []

    def add(u: ListUnit, character: bool) -> list[TargetGroup]:
        ds = u.datasheet
        if not ds:
            return []
        if not u.models:
            return [TargetGroup(ds.models[0], 1, character, u.label)]
        merged: dict[str, TargetGroup] = {}
        for m, label in zip(u.models, model_labels(u)):
            if label in merged:
                merged[label].count += m.count
            else:
                merged[label] = TargetGroup(ds.profile(m.name), m.count, character, label)
        return list(merged.values())

    body = add(bodyguard, bodyguard.is_character and not attached)
    groups.extend(_bodyguard_order(body))
    kws = set(bodyguard.datasheet.keywords) if bodyguard.datasheet else set()
    name = bodyguard.label
    for a in attached:
        if a.datasheet:
            groups.extend(add(a, True))
            kws |= a.datasheet.keywords
            name += f" + {a.label}"
    return Target(name, groups, kws)


def model_labels(u: ListUnit) -> list[str]:
    """Display label for each model line. Lines sharing a name are told apart by the gear only they
    carry: "Sanguinary Guard (Sanguinary Banner)", "Incursor (Haywire Mine)"."""
    by_name: dict[str, list] = {}
    for m in u.models:
        by_name.setdefault(norm(m.name), []).append(m)
    labels = []
    for m in u.models:
        same = by_name[norm(m.name)]
        if len(same) == 1:
            labels.append(m.name)
            continue
        common = set.intersection(*({norm(g) for g, _ in x.gear} for x in same))
        extra = [g for g, _ in m.gear if norm(g) not in common]
        labels.append(f"{m.name} ({', '.join(extra)})" if extra else m.name)
    return labels


SERGEANT_WORDS = ("sergeant", "sybarite", "hekatrix", "klaivex", "nightfiend", "solarite", "heliarch",
                  "acothyst", "superior", "exarch", "alpha", "nob", "boss", "champion", "leader", "prime")


def _bodyguard_order(groups: list[TargetGroup]) -> list[TargetGroup]:
    """Largest groups first, then single special models; the sergeant (by name, or the first-listed
    single model) goes last."""
    if len(groups) < 2:
        return groups
    named = [g for g in groups if g.count == 1 and any(w in g.label.lower() for w in SERGEANT_WORDS)]
    if named:
        sergeant = named[0]
    elif groups[0].count == 1 and any(g.count > 1 for g in groups[1:]):
        sergeant = groups[0]
    else:
        sergeant = None
    rest = sorted((g for g in groups if g is not sergeant), key=lambda g: -g.count)   # stable
    return rest + ([sergeant] if sergeant else [])
