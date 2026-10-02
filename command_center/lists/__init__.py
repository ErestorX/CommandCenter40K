"""Army lists: parse any registered format, then link units to Wahapedia datasheets.

    from command_center.lists import parse_list
    army = parse_list("lists/Drukhari.txt", wd)
"""
from __future__ import annotations

from pathlib import Path

from command_center.data.wahapedia import Wahapedia
from command_center.lists import newrecruit  # noqa: F401  (registers the format)
from command_center.lists.linking import all_gear, link_datasheets, match_weapon, target_for, weapon_loads
from command_center.lists.model import ArmyList, ListModel, ListUnit
from command_center.lists.registry import formats, pick_format, register_parser


def parse_list(path: str | Path, wd: Wahapedia) -> ArmyList:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    fmt = pick_format(text)
    return link_datasheets(fmt.parse(text, path, wd), wd)


__all__ = ["parse_list", "ArmyList", "ListUnit", "ListModel", "weapon_loads", "target_for", "match_weapon",
           "all_gear", "link_datasheets", "register_parser", "formats"]
