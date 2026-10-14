"""BSData study, survey: every faction of BSData (wh40k-11e) against the app's Wahapedia data.

    python scripts/bsdata_study/survey.py <wh40k-11e clone>

- units: found in both by name (BSData's " [Legends]" suffix aside), per faction; only in one of them
- stat profiles (M T Sv W invulnerable) and base sizes, notation aside ("4+*", "60mm Flying", "Hull")
- base sizes missing in BSData, per file
- Leader abilities (free text) read as unit names: how many name a unit
- modifiers on profiles: how many only test what the list selects (so an NR text list can evaluate them)
See docs/bsdata-study.md."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike import BSData, chars  # noqa: E402

from command_center.context import AppContext  # noqa: E402
from command_center.util import norm  # noqa: E402


def plain(name: str) -> str:
    return norm(re.sub(r"\s*\[legends\]", "", name, flags=re.I))


def invuln(text: str) -> str:
    return re.split(r"[*/ ]", text or "-")[0].rstrip("+") or "-"


def base(text: str) -> str:
    b = re.sub(r"\s+|base|flying", "", (text or "").lower())
    return "usemodel" if b in ("hull", "usemodel") else b


def units_and_stats(bs: BSData, wd) -> None:
    c = Counter()
    only_bs, diffs = Counter(), []
    names = defaultdict(list)
    for did, r in wd.datasheets.items():
        if r.get("virtual", "").lower() != "true":
            names[norm(r["name"])].append(did)
    seen, done = set(), set()
    for book in bs.books.values():
        if book.get("type") != "catalogue" or book.get("library"):
            continue
        parts = [x.strip() for x in book["name"].split(" - ")]
        fid = next((f for f in (wd.faction_id(x) for x in reversed(parts)) if f), None)
        for name, e in bs.unit_index([book] + [b for b in bs.reach(book) if b.get("library")]).items():
            if "[crucible]" in name or (id(e), fid) in done:
                continue
            done.add((id(e), fid))
            c["units"] += 1
            hits = [h for h in names.get(plain(e["name"]), []) if wd.datasheets[h].get("faction_id") == fid]
            if not hits:
                only_bs[book["name"]] += 1
                continue
            c["units in both"] += 1
            seen.update(hits)
            ds = wd.unit(hits[0])
            theirs_w = {norm(w.name) for w in ds.weapons} | {norm(w.base_name) for w in ds.weapons}
            for p in {id(p): p for _, d in bs.descendants(e) for p in bs.profiles(d)
                      if p.get("typeName") in ("Ranged Weapons", "Melee Weapons")}.values():
                c["weapon profiles"] += 1
                c["weapon names spelled the same"] += norm(re.sub(r"^➤\s*", "", p["name"])) in theirs_w
            profiles = {id(p): p for _, d in [(None, e)] + list(bs.descendants(e)) for p in bs.profiles(d)
                        if p.get("typeName") == "Unit"}
            for p in profiles.values():
                st = chars(p)
                w = next((m for m in ds.models if norm(m.name) == norm(p["name"])), ds.models[0] if len(ds.models) == 1 else None)
                if not w:
                    c["profiles named differently"] += 1
                    continue
                c["profiles compared"] += 1
                mine = [st.get("M", "").replace('"', ""), st.get("T"), st.get("Sv", "").rstrip("+"), st.get("W"), invuln(st.get("InSv"))]
                theirs = [w.M.replace('"', ""), str(w.T), str(w.Sv), str(w.W), str(w.inv or "-")]
                if mine != theirs:
                    c["profiles differing"] += 1
                    diffs.append(f"{book['name']} / {p['name']}: BSData {mine}  Wahapedia {theirs}")
                b1, b2 = base(st.get("Base")), base(w.base)
                if not b1:
                    c["bases missing in BSData"] += 1
                elif b2 and b1 != b2:
                    c["bases differing"] += 1
                    diffs.append(f"{book['name']} / {p['name']}: base BSData {st.get('Base')}  Wahapedia {w.base}")
    only_wh = [wd.datasheets[d]["name"] for ids in names.values() for d in ids if d not in seen]
    print("UNITS AND STATS:", dict(c))
    print(f"  Wahapedia datasheets not in BSData: {len(only_wh)} {only_wh[:10]}")
    print(f"  BSData units not in Wahapedia (allies reached through imports included): {sum(only_bs.values())}")
    print("  differences:")
    for d in diffs:
        print("   ", d)


def missing_bases(bs: BSData) -> None:
    empty, total = Counter(), Counter()
    for book in bs.books.values():
        def walk(n):
            if isinstance(n, dict):
                if n.get("typeName") == "Unit":
                    total[book["name"]] += 1
                    if not next((x.get("$text") for x in n.get("characteristics", []) if x["name"] == "Base"), ""):
                        empty[book["name"]] += 1
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for x in n:
                    walk(x)
        walk(book)
    print("\nBASE SIZES MISSING (stat profiles without one, per file):")
    for name in sorted(empty, key=lambda n: -empty[n]):
        print(f"  {empty[name]:4} / {total[name]:4}  {name}")


def leaders(bs: BSData) -> None:
    c = Counter()
    for book in bs.books.values():
        if book.get("type") != "catalogue" or book.get("library"):
            continue
        units = {plain(n) for n in bs.unit_index(bs.reach(book))}
        for e in bs.unit_index([book]).values():
            text = next((chars(p).get("Description", "") for p in bs.profiles(e) if p["name"] == "Leader"), "")
            if not text:
                continue
            c["Leader abilities"] += 1
            body = re.split(r"\n\s*\n", text.split(":", 1)[-1].strip())[0]
            for part in re.split(r"\n|,", body):
                n = re.sub(r"\s+", " ", re.sub(r"[*^■•\-–\[\]]", " ", part)).strip(" . ")
                if n and len(n) < 60:
                    c["names"] += 1
                    c["names that are units"] += norm(n) in units or norm(n).rstrip("s") in units or norm(n) + "s" in units
    print("\nLEADERS:", dict(c))


def modifiers(bs: BSData) -> None:
    verdict = Counter()

    def conditions(m):
        out = list(m.get("conditions", []) or []) + list(m.get("repeats", []) or [])
        for g in m.get("conditionGroups", []) or []:
            out += conditions(g)
        return out

    def walk(n):
        if isinstance(n, dict):
            if "typeName" in n:
                groups = n.get("modifierGroups", []) or []
                for m in (n.get("modifiers", []) or []) + [x for g in groups for x in g.get("modifiers", []) or []]:
                    cs = conditions(m) + [c for g in groups for c in conditions(g)]
                    selections = all(c.get("field") == "selections" for c in cs)
                    verdict["unconditional" if not cs else "on selections only" if selections else "on more"] += 1
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    for book in bs.books.values():
        walk(book)
    print("\nMODIFIERS ON PROFILES:", dict(verdict))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    bs = BSData(Path(sys.argv[1]))
    wd = AppContext().wd
    print(f"BSData: {len(bs.books)} files read in {bs.load_s:.1f}s; Wahapedia: {wd.last_update}")
    units_and_stats(bs, wd)
    missing_bases(bs)
    leaders(bs)
    modifiers(bs)
    print("\n" + json.dumps({"bsdata files": len(bs.books)}))


if __name__ == "__main__":
    main()
