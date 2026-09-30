"""
NewRecruit text export parser.

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
from pathlib import Path

from crunch.data.wahapedia import Wahapedia
from crunch.lists.model import ArmyList, ListModel, ListUnit
from crunch.lists.registry import register_parser

UNIT_RE = re.compile(r"^(?P<name>[^•\[].*?)\s*\[(?P<pts>\d+)\s*pts?\](?:\s*:\s*(?P<gear>.*))?$")
MODEL_RE = re.compile(r"^(?P<n>\d+)x\s+(?P<name>.+?)(?:\s*\[\d+\s*pts?\])?\s*:\s*(?P<gear>.*)$")
PTS_RE = re.compile(r"\s*\[[^\]]*pts?[^\]]*\]", re.I)


def detect(text: str) -> bool:
    """NewRecruit text exports have '## Category [N pts]' sections or a 'Created with newrecruit' footer."""
    return "newrecruit" in text.lower() or bool(re.search(r"^##\s.+\[\d+\s*pts", text, re.M))


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


def parse(text: str, path: Path, wd: Wahapedia) -> ArmyList:
    """Parse the text; datasheets are linked afterwards by crunch.lists.linking."""
    lines = text.splitlines()
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

    return ArmyList(path, title, faction, faction_id, detachment, int(pts.group(1)) if pts else 0, units)


register_parser("newrecruit-text", "NewRecruit text export", detect, parse)
