"""An army as it stands on the table: one row per unit, Leaders and Support characters merged into
the unit they join, each with the footprint of all its bases."""
from __future__ import annotations

from dataclasses import dataclass

from crunch.deploy.bases import Base, Footprint, parse_base, unit_footprint
from crunch.deploy.movement import parse_move
from crunch.lists import ArmyList, ListUnit


@dataclass
class RosterRow:
    key: str                      # stable id within the army ("u3": the row of unit uid 3)
    units: list[ListUnit]         # the unit first, then what joins it
    name: str
    models: int
    points: int
    footprint: Footprint
    move: float = 0.0             # inches: the slowest model's Move (a unit moves at its slowest)


def unit_bases(u: ListUnit) -> list[tuple[Base, int]]:
    """(base, count) for each model line of a list unit, from its datasheet's model profiles."""
    ds = u.datasheet
    if not ds:
        return [(parse_base(""), u.model_count)]
    if not u.models:
        p = ds.models[0]
        return [(parse_base(p.base, p.W), u.model_count)]
    out = []
    for m in u.models:
        p = ds.profile(m.name)
        out.append((parse_base(p.base, p.W), m.count))
    return out


def roster(army: ArmyList, wd) -> list[RosterRow]:
    joined: dict[int, list[ListUnit]] = {}
    used: set[int] = set()
    for u in army.units:
        if u.is_character:
            continue
        for support in (False, True):
            c = army.default_attached(u, wd, support=support)
            if c and c.uid not in used:
                joined.setdefault(u.uid, []).append(c)
                used.add(c.uid)
    rows = []
    for u in army.units:
        if u.uid in used:
            continue
        group = [u] + joined.get(u.uid, [])
        name = " + ".join(x.label or x.name for x in group) + ("" if u.datasheet else "  (no datasheet)")
        bases = [b for x in group for b in unit_bases(x)]
        rows.append(RosterRow(f"u{u.uid}", group, name, sum(x.model_count for x in group),
                              sum(x.points for x in group), unit_footprint(bases), unit_move(group)))
    return rows


def unit_move(units: list[ListUnit]) -> float:
    """The slowest Move among the models fielded (0 if none can move)."""
    moves = []
    for u in units:
        ds = u.datasheet
        if not ds:
            continue
        profiles = [ds.profile(m.name) for m in u.models] if u.models else ds.models[:1]
        moves += [parse_move(p.M) for p in profiles]
    moving = [m for m in moves if m > 0]
    return min(moving) if moving else 0.0
