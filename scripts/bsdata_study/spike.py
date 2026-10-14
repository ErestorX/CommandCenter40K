"""BSData study, spike: link NewRecruit text lists to BSData (wh40k-11e, JSON) by exact names only, and
compare what is found with what the app gets from Wahapedia today.

    git clone --depth 1 https://github.com/BSData/wh40k-11e.git <somewhere>
    python scripts/bsdata_study/spike.py <somewhere> lists/*.txt

Per list and in total: units, model lines, gear items found by their exact (case-folded) name; their
stats, weapon stats and keywords, unit keywords and Leader lists compared with Wahapedia's. See
docs/bsdata-study.md. Throwaway code: the reader (BSData) is what a real one would start from."""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))

WEAPON_TYPES = {"Ranged Weapons", "Melee Weapons"}


def key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("’", "'").strip().lower())


# ----------------------------------------------------------------------------- the data
class BSData:
    def __init__(self, repo: Path):
        t = time.perf_counter()
        self.books: dict[str, dict] = {}          # catalogue id -> catalogue (and the game system)
        for f in sorted(repo.glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            book = doc.get("catalogue") or doc.get("gameSystem")
            self.books[book["id"]] = book
        self.system = next(b for b in self.books.values() if b.get("type") == "gameSystem")
        self.by_id: dict[str, dict] = {}
        for b in self.books.values():
            self._index(b)
        self.load_s = time.perf_counter() - t

    def _index(self, node):
        if isinstance(node, dict):
            if "id" in node and "targetId" not in node:
                self.by_id.setdefault(node["id"], node)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    self._index(v)
        elif isinstance(node, list):
            for x in node:
                self._index(x)

    def catalogue_for(self, title: str) -> dict | None:
        """The catalogue whose name starts the list's title, the longest one."""
        t = key(title)
        hits = [b for b in self.books.values() if b.get("type") == "catalogue" and t.startswith(key(b["name"]))]
        return max(hits, key=lambda b: len(b["name"])) if hits else None

    def reach(self, book: dict) -> list[dict]:
        """The catalogue, those it links (recursively), and the game system."""
        out, todo = [], [book]
        while todo:
            b = todo.pop(0)
            if b in out:
                continue
            out.append(b)
            todo += [self.books[l["targetId"]] for l in b.get("catalogueLinks", []) if l["targetId"] in self.books]
        return out + [self.system]

    # ---- following links
    def target(self, node: dict) -> dict:
        return self.by_id.get(node["targetId"], {}) if "targetId" in node else node

    def entries(self, node: dict):
        """Direct child entries of an entry or group, links followed (the link's name kept)."""
        for k in ("selectionEntries", "selectionEntryGroups", "entryLinks"):
            for e in node.get(k, []) or []:
                t = self.target(e)
                if t:
                    yield e.get("name") or t.get("name", ""), t

    def profiles(self, node: dict) -> list[dict]:
        out = list(node.get("profiles", []) or [])
        for link in node.get("infoLinks", []) or []:
            if link.get("type") == "profile":
                p = self.target(link)
                if p:
                    out.append(p)
        for g in node.get("infoGroups", []) or []:
            out += self.profiles(g)
        return out

    def rules(self, node: dict) -> list[dict]:
        out = list(node.get("rules", []) or [])
        out += [self.target(l) for l in node.get("infoLinks", []) or [] if l.get("type") == "rule" and self.target(l)]
        return out

    def descendants(self, node: dict, depth=0, seen=None):
        """(name, entry) below an entry, links followed, each entry once."""
        seen = seen if seen is not None else set()
        for name, e in self.entries(node):
            if id(e) in seen or depth > 8:
                continue
            seen.add(id(e))
            yield name, e
            yield from self.descendants(e, depth + 1, seen)

    # ---- units
    def unit_index(self, books: list[dict]) -> dict[str, dict]:
        """name -> unit/model entry selectable in these catalogues (first catalogue wins)."""
        found: dict[str, dict] = {}
        for b in books:
            for k in ("sharedSelectionEntries", "selectionEntries", "entryLinks"):
                for e in b.get(k, []) or []:
                    t = self.target(e)
                    if t.get("type") in ("unit", "model"):
                        found.setdefault(key(e.get("name") or t.get("name")), t)
        return found


def chars(p: dict) -> dict[str, str]:
    return {c["name"]: c.get("$text", "") for c in p.get("characteristics", [])}


# ----------------------------------------------------------------------------- linking a list
def models_of(bs: BSData, unit: dict) -> dict[str, dict]:
    """Model entries of a unit by name (the unit itself if it is a single model)."""
    out = {key(n): e for n, e in bs.descendants(unit) if e.get("type") == "model"}
    if unit.get("type") == "model":
        out.setdefault(key(unit["name"]), unit)
    return out


def stat_profile(bs: BSData, model: dict, unit: dict) -> dict | None:
    for node in (model, unit):
        for p in bs.profiles(node):
            if p.get("typeName") == "Unit":
                return p
    for _, e in bs.descendants(unit):                  # some keep the profile on a nested entry
        for p in bs.profiles(e):
            if p.get("typeName") == "Unit":
                return p
    return None


def gear_index(bs: BSData, *nodes: dict) -> dict[str, list[dict]]:
    """gear name -> profiles found at or below that entry (weapons, abilities)."""
    out: dict[str, list[dict]] = {}

    def own(e, depth=0):
        """Profiles of a selectable entry and of what it is made of (not the options of its groups)."""
        ps = bs.profiles(e)
        for _, d in bs.entries(e):
            if d.get("type") not in (None, "selectionEntryGroup") and depth < 4:
                ps += own(d, depth + 1)
        return ps

    for node in nodes:
        for name, e in bs.descendants(node):
            if e.get("type") in (None, "selectionEntryGroup"):
                continue
            ps = own(e)
            for n in {key(name), key(e.get("name", ""))}:
                out.setdefault(n, [])
                out[n] += [p for p in ps if p not in out[n]]
            for p in bs.profiles(e):                     # a profile is also known by its own name
                out.setdefault(key(p["name"]), [])
                if p not in out[key(p["name"])]:
                    out[key(p["name"])].append(p)
    return out


def enhancement_index(bs: BSData, books: list[dict]) -> dict[str, dict]:
    out = {}
    for b in books:
        for g in b.get("sharedSelectionEntryGroups", []) or []:
            if g.get("name") == "Enhancements":
                for n, e in bs.descendants(g):
                    for p in bs.profiles(e):
                        out.setdefault(key(n), p)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    repo, lists = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    from command_center.context import AppContext
    from command_center.core.dice import Dice
    from command_center.core.keywords import parse_weapon_keywords
    from command_center.lists import parse_list
    from command_center.lists.linking import match_weapon

    bs = BSData(repo)
    print(f"BSData: {len(bs.books)} files, {len(bs.by_id)} ids, read in {bs.load_s:.1f}s")
    wd = AppContext().wd
    total = Counter()
    for path in lists:
        army = parse_list(path, wd)
        book = bs.catalogue_for(army.title)
        print(f"\n#### {path.name}: catalogue {book and book['name']!r}")
        if not book:
            continue
        books = bs.reach(book)
        units = bs.unit_index(books)
        enh = enhancement_index(bs, books)
        c = Counter()
        for u in army.units:
            entry = units.get(key(u.name))
            c["units"] += 1
            if not entry:
                print(f"  !! unit not found: {u.name}")
                continue
            c["units found"] += 1
            models = models_of(bs, entry)
            for m in u.models or []:
                c["model lines"] += 1
                me = models.get(key(m.name))
                if not me:
                    print(f"  !! {u.name}: model '{m.name}' not found (has {sorted(models)})")
                    continue
                c["model lines found"] += 1
                sp = stat_profile(bs, me, entry)
                if not sp:
                    print(f"  !! {u.name}: no stat profile for {m.name}")
                    continue
                st = chars(sp)
                c["stat profiles"] += 1
                if not st.get("Base"):
                    c["no base size"] += 1
                    print(f"  .. {u.name}: '{m.name}' has no base size")
                if u.datasheet:                                   # vs Wahapedia
                    w = u.datasheet.profile(m.name)
                    ours = (st.get("M"), st.get("T"), st.get("Sv"), st.get("W"), (st.get("InSv") or "-").rstrip("+"), st.get("Base") or "")
                    theirs = (w.M, str(w.T), f"{w.Sv}+", str(w.W), str(w.inv or "-"), w.base)
                    if [x.replace('"', "") for x in ours[:5]] != [str(x).replace('"', "") for x in theirs[:5]]:
                        c["stat differences"] += 1
                        print(f"  <> {u.name} / {m.name}: BSData {ours[:5]}  Wahapedia {theirs[:5]}")
                    if ours[5] and theirs[5] and ours[5] != theirs[5]:
                        print(f"  <> {u.name} / {m.name}: base BSData {ours[5]} Wahapedia {theirs[5]}")
                gear = gear_index(bs, me, entry)
                for g, _ in m.gear:
                    c["gear"] += 1
                    ps = gear.get(key(g))
                    if ps is None:
                        if key(g) in enh:
                            c["gear: enhancement"] += 1
                        else:
                            c["gear not found"] += 1
                            print(f"  !! {u.name} / {m.name}: gear '{g}' not found")
                        continue
                    weapons = [p for p in ps if p.get("typeName") in WEAPON_TYPES]
                    if not weapons:
                        c["gear: ability/other"] += 1
                        continue
                    c["gear: weapon"] += 1
                    for p in weapons:
                        ch = chars(p)
                        try:
                            Dice.parse(ch.get("A")), Dice.parse(ch.get("D"))
                            parse_weapon_keywords(ch.get("Keywords", ""))
                        except ValueError as e:
                            c["weapon parse errors"] += 1
                            print(f"  !! {p['name']}: {e}")
                        if u.datasheet:
                            wp = match_weapon(g, u.datasheet)
                            if not wp:
                                c["weapons BSData only"] += 1
                                continue
                            skill = (ch.get("BS") or ch.get("WS") or "").rstrip("+")
                            mine = (ch.get("A"), "N/A" if skill in ("N/A", "-", "") else skill, ch.get("S"),
                                    (ch.get("AP") or "0").lstrip("-"), ch.get("D"))
                            tags = sorted(parse_weapon_keywords(ch.get("Keywords", "")).tags())
                            c["weapon profiles compared"] += 1
                            stats = [(x, (str(x.A), str(x.skill or "N/A"), str(x.S), str(x.AP), str(x.D))) for x in wp]
                            same = [x for x, t in stats if [v.upper() for v in mine] == [v.upper() for v in t]]
                            if not same:
                                c["weapon stat differences"] += 1
                                print(f"  <> {p['name']}: BSData {mine}  Wahapedia {[(x.name, t) for x, t in stats]}")
                            elif not any(sorted(x.keywords.tags()) == tags for x in same):
                                c["weapon keyword differences"] += 1
                                print(f"  <> {p['name']} keywords: BSData {tags}  Wahapedia {sorted(same[0].keywords.tags())}")
            # keywords, abilities, leader, support, modifiers
            kws = {key(l["name"]) for l in entry.get("categoryLinks", [])}
            if u.datasheet:
                wk = {key(k) for k in u.datasheet.keywords}
                plain = {k.removeprefix("faction: ") for k in kws}
                if wk - plain or plain - wk:
                    c["keyword differences"] += 1
                    print(f"  <> {u.name} keywords: BSData only {sorted(plain - wk)}  Wahapedia only {sorted(wk - plain)}")
            abil = [p["name"] for p in bs.profiles(entry) if p.get("typeName") == "Abilities"]
            core = [r.get("name") for r in bs.rules(entry)]
            c["abilities"] += len(abil)
            c["rules linked"] += len(core)
            leader = next((chars(p).get("Description", "") for p in bs.profiles(entry) if p["name"] == "Leader"), "")
            if leader:
                c["leaders"] += 1
                named = {key(re.sub(r"[*^■\-]", "", n)).strip() for n in re.split(r"\n|,", leader.split(":", 1)[-1]) if n.strip()}
                named = {n.removesuffix(".") for n in named if n and len(n) < 60}
                if u.datasheet:
                    theirs = {key(wd.datasheets[i]["name"]) for i in wd.leads.get(u.datasheet.id, ()) if i in wd.datasheets}
                    if named != theirs:
                        c["leader differences"] += 1
                        print(f"  <> {u.name} leads: BSData only {sorted(named - theirs)}  Wahapedia only {sorted(theirs - named)}")
            if any("support" == k for k in kws) or any(r.get("name", "").lower() == "support" for r in bs.rules(entry)):
                c["support"] += 1
            mods = [m for _, e in [(None, entry)] + list(bs.descendants(entry)) for p in bs.profiles(e)
                    for m in p.get("modifiers", []) or []] + \
                   [m for _, e in [(None, entry)] + list(bs.descendants(entry)) for m in e.get("modifiers", []) or []
                    if len(m.get("field", "")) > 12]
            c["characteristic modifiers"] += len(mods)
            for g, _ in u.unit_gear:                     # gear on the unit line: enhancements, wargear, Warlord
                c["unit-line items"] += 1
                if key(g) in enh:
                    c["unit-line: enhancement"] += 1
                elif key(g) in gear_index(bs, entry):
                    c["unit-line: entry"] += 1
                elif key(g) != "warlord":
                    c["unit-line not found"] += 1
                    print(f"  !! {u.name}: '{g}' not found")
        print("  " + ", ".join(f"{k}: {v}" for k, v in c.items()))
        total += c
    print("\nTOTAL " + ", ".join(f"{k}: {v}" for k, v in total.items()))



if __name__ == "__main__":
    main()
