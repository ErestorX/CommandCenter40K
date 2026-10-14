"""Cut the tests' BSData files (tests/fixtures/bsdata) out of a clone of BSData's repository.

    python scripts/bsdata_fixture.py <wh40k-11e clone>

Keeps, from the Space Marines catalogue, the units the fixture lists name (UNITS), the detachment they
use and its enhancements, and everything those reference (shared entries, profiles, rules), moved into
the one catalogue; the game system keeps its referenced rules. Dropped: Crusade and other groups that
aren't gear (bsdata.NOT_GEAR), modifiers, constraints, costs but points: what the app doesn't read."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_center.data.bsdata import NOT_GEAR, write_index  # noqa: E402

CATALOGUE = "Imperium - Space Marines.json"
SYSTEM = "Warhammer 40,000.json"
UNITS = ("Captain", "Apothecary", "Intercessor Squad")
DETACHMENT = "Gladius Task Force"
DROP = ("modifiers", "modifierGroups", "constraints", "conditions", "conditionGroups", "repeats", "publicationId",
        "page", "comment", "associations")
OUT = ROOT / "tests" / "fixtures" / "bsdata"


def main(repo: Path) -> None:
    files = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in repo.glob("*.json")}
    by_id, home = {}, {}
    for name, doc in files.items():
        def index(n):
            if isinstance(n, dict):
                if "id" in n and "targetId" not in n:
                    by_id.setdefault(n["id"], n)
                    home.setdefault(n["id"], name)
                for v in n.values():
                    index(v)
            elif isinstance(n, list):
                for x in n:
                    index(x)
        index(doc)
    cat = files[CATALOGUE]["catalogue"]
    system = files[SYSTEM]["gameSystem"]

    def clean(n):
        """A copy without what the app doesn't read, nor the links into groups that aren't gear."""
        if isinstance(n, list):
            return [c for c in (clean(x) for x in n) if c is not None]
        if not isinstance(n, dict):
            return n
        if "targetId" in n and n.get("type") == "selectionEntryGroup":
            target = by_id.get(n["targetId"], {})
            if NOT_GEAR.search(n.get("name", "")) or NOT_GEAR.search(target.get("name", "")):
                return None
        out = {k: clean(v) for k, v in n.items() if k not in DROP}
        if "costs" in out:
            out["costs"] = [c for c in out["costs"] if c.get("name") == "pts"]
        return out

    units = [clean(e) for e in cat["sharedSelectionEntries"] if e.get("name") in UNITS and e.get("type") in ("unit", "model")]
    groups = []
    for g in cat["sharedSelectionEntryGroups"]:
        if g["name"] == "Detachment":
            groups.append({**clean({k: v for k, v in g.items() if k != "selectionEntries"}),
                           "selectionEntries": [clean(e) for e in g.get("selectionEntries", []) if e["name"] == DETACHMENT]})
        elif g["name"] == "Enhancements":
            groups.append({**{k: v for k, v in clean(g).items() if k not in ("selectionEntryGroups", "entryLinks")},
                           "selectionEntryGroups": [clean(x) for x in g.get("selectionEntryGroups", [])
                                                    if x["name"] == f"{DETACHMENT} Enhancements"]})
    kept = {"sharedSelectionEntries": units, "sharedSelectionEntryGroups": groups, "sharedProfiles": [], "sharedRules": []}
    system_rules = []
    have = set()

    def collect(n):
        if isinstance(n, dict):
            if "id" in n and "targetId" not in n:
                have.add(n["id"])
            for v in n.values():
                collect(v)
        elif isinstance(n, list):
            for x in n:
                collect(x)

    def targets(n, out):
        if isinstance(n, dict):
            if "targetId" in n:
                out.add(n["targetId"])
            for v in n.values():
                targets(v, out)
        elif isinstance(n, list):
            for x in n:
                targets(x, out)
        return out

    collect(kept)
    todo = targets(kept, set())
    while todo - have:
        for tid in sorted(todo - have):
            have.add(tid)
            node = by_id.get(tid)
            if node is None:
                continue
            node = clean(node)
            if home[tid] == SYSTEM and tid in {r["id"] for r in system.get("sharedRules", [])}:
                system_rules.append(node)
            elif "typeName" in node:
                kept["sharedProfiles"].append(node)
            elif "description" in node and "type" not in node or node.get("type") == "rule":
                kept["sharedRules"].append(node)
            elif node.get("type") in (None, "selectionEntryGroup"):
                kept["sharedSelectionEntryGroups"].append(node)
            else:
                kept["sharedSelectionEntries"].append(node)
            collect(node)
            todo |= targets(node, set())

    header = {k: cat[k] for k in ("name", "id", "battleScribeVersion", "gameSystemId", "gameSystemRevision",
                                  "library", "revision", "type") if k in cat}
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    (OUT / CATALOGUE).write_text(json.dumps({"catalogue": {**header, **kept}}, indent=1, ensure_ascii=False), encoding="utf-8")
    sys_header = {k: system[k] for k in ("name", "id", "battleScribeVersion", "revision", "type") if k in system}
    (OUT / SYSTEM).write_text(json.dumps({"gameSystem": {**sys_header, "profileTypes": system.get("profileTypes", []),
                                                         "sharedRules": system_rules}}, indent=1, ensure_ascii=False),
                              encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps({"repository": "BSData/wh40k-11e", "note": "cut by scripts/bsdata_fixture.py",
                                                   "date": "2026-10-13"}, indent=1), encoding="utf-8")
    write_index(OUT)
    for f in sorted(OUT.glob("*.json")):
        print(f"{f.name}: {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
