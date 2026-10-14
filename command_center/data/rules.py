"""Rules text that the simulator doesn't need: army rules, detachments, stratagems, enhancements and
unit abilities.

BSData first (command_center.data.bsdata), Wahapedia after: a unit's abilities and enhancements, and a
detachment's rule and enhancements, come from BSData when the unit or the detachment is there; the
army rules and the stratagems always come from Wahapedia (BSData has no stratagems, and only some of
the army rules), and so does whatever BSData lacks. Wahapedia's tables are loaded on first use."""
from __future__ import annotations

from collections import defaultdict

from command_center.core.models import Unit
from command_center.data.armies import wahapedia_id
from command_center.data.bsdata import BSData, key
from command_center.data.wahapedia import Wahapedia, read_table
from command_center.util import norm


# Army rules of one Chapter, which the data files with the Space Marines' (norm()-ed names):
# the Faction keywords of the armies they are for.
CHAPTER_RULES = {
    "theravenwing": {"darkangels"}, "thedeathwing": {"darkangels"},
    "sonsofruss": {"spacewolves"},
    "heirsofsigismund": {"blacktemplars"},
}


class RulesBook:
    """Lazily loads the rules tables that the simulator itself doesn't need."""

    def __init__(self, wd: Wahapedia, bs: BSData | None = None):
        self.wd = wd
        self.bs = bs
        self._t: dict[str, list[dict]] = {}

    def table(self, name: str) -> list[dict]:
        if name not in self._t:
            self._t[name] = read_table(self.wd.data_dir, name)
        return self._t[name]

    @property
    def abilities_by_id(self) -> dict[str, dict]:
        if "_ab" not in self._t:
            self._t["_ab"] = {a["id"]: a for a in self.table("Abilities")}
        return self._t["_ab"]

    def _bsdata(self, unit: Unit | None) -> bool:
        return bool(self.bs and unit and unit.source == "bsdata")

    # ---- army level --------------------------------------------------------
    def army_rules(self, faction_id: str | None, army=None) -> list[dict]:
        """The faction's army rules (Wahapedia's). For an army (a parsed list), only those that concern
        it: a rule that datasheets carry ("Kill Team", "Curse of the Wulfen") if one of its units does,
        a Chapter's rule only for that Chapter's army."""
        rules = [a for a in self.table("Abilities") if faction_id and a.get("faction_id") == faction_id]
        if army is None:
            return rules
        carried: dict[str, set[str]] = defaultdict(set)          # ability id -> datasheets with it
        for r in self.table("Datasheets_abilities"):
            carried[r.get("ability_id", "")].add(r.get("datasheet_id", ""))
        mine = {wahapedia_id(u.datasheet) for u in army.units if u.datasheet} - {None}
        keywords = self.faction_keywords(army)
        return [a for a in rules
                if (not carried.get(a["id"]) or carried[a["id"]] & mine)
                and (norm(a["name"]) not in CHAPTER_RULES or CHAPTER_RULES[norm(a["name"])] & keywords)]

    def faction_keywords(self, army) -> set[str]:
        """norm()-ed Faction keywords of an army: its units' ("bloodangels", "adeptusastartes") and
        those its title names ("Imperium - Adeptus Astartes - Blood Angels - ...")."""
        faction = {norm(k["keyword"]) for rows in self.wd._keywords.values() for k in rows
                   if k.get("is_faction_keyword", "").lower() == "true"}
        found = {norm(p) for p in army.title.split(" - ")} & faction
        for u in army.units:
            ds = u.datasheet
            if self._bsdata(ds):
                found |= self.bs.faction_keywords(ds.id)
            if wahapedia_id(ds):
                found |= {norm(k["keyword"]) for k in self.wd._keywords.get(wahapedia_id(ds), [])
                          if k.get("is_faction_keyword", "").lower() == "true"}
        return found

    def enhancements_of(self, unit) -> list[dict]:
        """The enhancements a list gives a unit (ListUnit): {"name", "description" (HTML), "cost"}. BSData's
        when it has them, Wahapedia's for the others."""
        ds = unit.datasheet
        if not ds:
            return []
        given = [n for n, _ in unit.unit_gear] + [n for m in unit.models for n, _ in m.gear]
        found, out = set(), []
        if self._bsdata(ds):
            known = self.bs.enhancements(self.bs._owner.get(ds.id))
            for n in given:
                e = known.get(key(n))
                if e and e["name"] not in found:
                    found.add(e["name"])
                    out.append(e)
        faction = ds.faction_id or (ds.fallback.faction_id if ds.fallback else "")
        for e in self.table("Enhancements"):
            if (e.get("faction_id") == faction and norm(e.get("name", "")) in {norm(n) for n in given}
                    and norm(e.get("name", "")) not in {norm(f) for f in found}):
                out.append(e)
        return out

    def detachments(self, faction_id: str | None, names: list[str], army=None) -> list[dict]:
        """The detachments of a list, in its order: Wahapedia's row (type, Detachment Points, Force
        Disposition), with BSData's (under "bsdata") when the list's catalogue has it."""
        rows = {norm(d["name"]): d for d in self.table("Detachments") if d.get("faction_id") == faction_id}
        out = []
        for name in names:
            row = dict(rows.get(norm(name), {}))
            found = self.bs.detachment(name, army.title) if self.bs and army is not None else None
            if found:
                row.setdefault("name", found["name"])
                row["bsdata"] = found
            if row:
                out.append(row)
        return out

    def detachment_content(self, det: dict) -> dict[str, list[dict]]:
        """Its rules and enhancements (BSData's when it has the detachment), and its stratagems (Wahapedia's)."""
        did, name = det.get("id", ""), norm(det.get("name", ""))
        match = lambda r: (did and r.get("detachment_id") == did) or norm(r.get("detachment", "")) == name
        found = det.get("bsdata")
        return {
            "rules": (found["rules"] if found and found["rules"]
                      else [r for r in self.table("Detachment_abilities") if match(r)]),
            "enhancements": (found["enhancements"] if found and found["enhancements"]
                             else [r for r in self.table("Enhancements") if match(r)]),
            "stratagems": [r for r in self.table("Stratagems") if match(r)],
        }

    def core_stratagems(self) -> list[dict]:
        return [s for s in self.table("Stratagems")
                if not s.get("faction_id") and s.get("type", "").lower().startswith("core")]

    # ---- unit level --------------------------------------------------------
    def abilities_of(self, unit: Unit) -> dict[str, list[tuple[str, str]]]:
        """{'Core': [(name, html)], 'Faction': [...], 'Datasheet': [...], 'Wargear': [...], ...}: BSData's
        for a BSData unit (Wahapedia's when BSData has none), Wahapedia's otherwise."""
        if self._bsdata(unit):
            found = self.bs.abilities(unit.id)
            if any(found.values()) or not unit.fallback:
                return found
        wid = wahapedia_id(unit)
        return self.unit_abilities(wid) if wid else {}

    def unit_abilities(self, datasheet_id: str) -> dict[str, list[tuple[str, str]]]:
        """A Wahapedia datasheet's abilities, as abilities_of gives them."""
        if "_dsa" not in self._t:
            g = defaultdict(list)
            for r in self.table("Datasheets_abilities"):
                g[r.get("datasheet_id", "")].append(r)
            self._t["_dsa"] = g
        out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in sorted(self._t["_dsa"].get(datasheet_id, []), key=lambda r: int(r.get("line") or 0)):
            ref = self.abilities_by_id.get(r.get("ability_id", ""), {})
            name = r.get("name") or ref.get("name", "")
            if r.get("parameter"):
                name = f"{name} {r['parameter']}"
            kind = r.get("type") or "Other"
            if kind not in ("Core", "Faction", "Datasheet", "Wargear"):
                kind = "Other"
            desc = r.get("description") or ("" if kind in ("Core", "Faction") else ref.get("description", ""))
            out[kind].append((name, desc))
        return out

    def invuln_description(self, unit: Unit) -> str:
        """Conditions on the invulnerable save, if Wahapedia's datasheet has any."""
        wid = wahapedia_id(unit)
        return next((m.get("inv_sv_descr") for m in self.wd._models.get(wid or "", []) if m.get("inv_sv_descr")), "")

    def datasheet_row(self, unit: Unit) -> dict:
        """Wahapedia's datasheet row (leader text, damaged profile...): the unit's, or its fallback's."""
        return self.wd.datasheets.get(wahapedia_id(unit) or "", {})
