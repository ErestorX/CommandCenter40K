"""
army_list.py - read a NewRecruit text export and link it to Wahapedia datasheets.

Supports the default NewRecruit "text" export:

    Xenos - Drukhari - Emo Elves - [1995 pts]
    ## Battleline [260 pts]
    Kabalite Warriors [110 pts]:
    • 1x Sybarite: Phantasm Grenade Launcher, Power Weapon, Blast Pistol
    • 5x Kabalite Warrior: Close Combat Weapon, Splinter rifle
      • Leader: Archon
    Ravager [125 pts]: Bladevanes, 3x Dark Lance [5 pts]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mathhammer import (Target, TargetGroup, Unit, Wahapedia, Weapon, WeaponLoad, norm)

UNIT_RE = re.compile(r"^(?P<name>[^•\[].*?)\s*\[(?P<pts>\d+)\s*pts?\](?:\s*:\s*(?P<gear>.*))?$")
MODEL_RE = re.compile(r"^(?P<n>\d+)x\s+(?P<name>.+?)(?:\s*\[\d+\s*pts?\])?\s*:\s*(?P<gear>.*)$")
PTS_RE = re.compile(r"\s*\[[^\]]*pts?[^\]]*\]", re.I)


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


# -----------------------------------------------------------------------------
# parsing
# -----------------------------------------------------------------------------
def split_items(text: str) -> list[tuple[str, int]]:
    """'2x Twin meltagun, Volcano lance, X and Y (2x A, B) [15 pts]' -> [(name, count)]"""
    items, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    out = []
    for it in items:
        it = PTS_RE.sub("", it).strip()
        if not it:
            continue
        inner = re.search(r"\((.+)\)\s*$", it)
        if inner:                                  # "combo name (A, 2x B)" -> A, B x2
            out += split_items(inner.group(1))
            continue
        m = re.match(r"^(\d+)\s*x?\s+(.+)$", it)
        if m:
            out.append((m.group(2).strip(), int(m.group(1))))
        else:
            out.append((it, 1))
    return out


def parse_list(path: str | Path, wd: Wahapedia) -> ArmyList:
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    title = next((l.strip() for l in lines if l.strip()), path.stem)
    head = PTS_RE.sub("", title).strip(" -")
    parts = [p.strip() for p in head.split(" - ") if p.strip()]
    faction_id, faction = None, parts[0] if parts else ""
    for p in parts:                                  # "Xenos - Drukhari - Emo Elves"
        fid = wd.faction_id(p)
        if fid:
            faction_id, faction = fid, p
            break
    pts = re.search(r"\[(\d+)\s*pts", title)

    units: list[ListUnit] = []
    category, detachment, in_config = "", "", False
    current: ListUnit | None = None
    for raw in lines[1:]:
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("# ") or s.startswith("Created with") or s == "Show/Hide Options":
            continue
        if s.startswith("## "):
            category = PTS_RE.sub("", s[3:]).strip()
            in_config = category.lower() == "configuration"
            current = None
            continue
        if in_config:
            if s.lower().startswith("detachment"):
                detachment = PTS_RE.sub("", s.split(":", 1)[-1]).strip()
            continue
        if s.startswith("•"):
            body = s.lstrip("•").strip()
            if current is None:
                continue
            low = body.lower()
            if re.match(r"(leaders?|support|supported by|attached)\s*:", low):
                current.attached_names += [n.strip() for n in body.split(":", 1)[1].split(",") if n.strip()]
            elif re.match(r"(leading|supporting|attached to)\s*:", low):
                current.leading_name = body.split(":", 1)[1].strip()
            elif m := MODEL_RE.match(body):
                current.models.append(ListModel(m["name"].strip(), int(m["n"]), split_items(m["gear"])))
            continue
        m = UNIT_RE.match(s)
        if m:
            current = ListUnit(len(units), m["name"].strip(), int(m["pts"]), category, [],
                               split_items(m["gear"] or ""))
            units.append(current)

    # link to datasheets + unique labels
    seen: dict[str, int] = {}
    totals = {}
    for u in units:
        totals[u.name] = totals.get(u.name, 0) + 1
    for u in units:
        did = wd.find(u.name, faction_id)
        u.datasheet = wd.unit(did) if did else None
        seen[u.name] = seen.get(u.name, 0) + 1
        u.label = u.name + (f" #{seen[u.name]}" if totals[u.name] > 1 else "")
        if u.datasheet:
            u.unmatched_gear = sorted({n for n, _ in _all_gear(u) if not match_weapon(n, u.datasheet)})

    return ArmyList(path, title, faction, faction_id, detachment, int(pts.group(1)) if pts else 0, units)


# -----------------------------------------------------------------------------
# linking list gear to datasheet weapons
# -----------------------------------------------------------------------------
def _all_gear(u: ListUnit) -> list[tuple[str, int]]:
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
    for name, cnt in _all_gear(u):
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
