"""Registry of army-list formats. Add a format by writing a module with `detect(text)` and
`parse(text, path, wd) -> ArmyList`, calling `register_parser(...)`, and importing it in
command_center/lists/__init__.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from command_center.lists.model import ArmyList


@dataclass(frozen=True)
class ListFormat:
    key: str
    title: str
    detect: Callable[[str], bool]
    parse: Callable[..., ArmyList]


_FORMATS: dict[str, ListFormat] = {}


def register_parser(key: str, title: str, detect: Callable[[str], bool], parse: Callable[..., ArmyList]) -> None:
    _FORMATS[key] = ListFormat(key, title, detect, parse)


def formats() -> list[ListFormat]:
    return list(_FORMATS.values())


def pick_format(text: str) -> ListFormat:
    for f in _FORMATS.values():
        if f.detect(text):
            return f
    if len(_FORMATS) == 1:           # only one format known: let it try
        return next(iter(_FORMATS.values()))
    raise ValueError("Unrecognised army list format. Known: " + ", ".join(f.title for f in _FORMATS.values()))
