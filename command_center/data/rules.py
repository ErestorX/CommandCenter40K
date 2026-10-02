"""Rules text that the simulator doesn't need: army rules, detachments, stratagems,
enhancements and unit abilities. Tables are loaded lazily on first use."""
from __future__ import annotations

from collections import defaultdict

from command_center.data.wahapedia import Wahapedia, read_table
from command_center.util import norm


class RulesBook:
    """Lazily loads the rules tables that the simulator itself doesn't need."""

    def __init__(self, wd: Wahapedia):
        self.wd = wd
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

    # ---- army level --------------------------------------------------------
    def army_rules(self, faction_id: str | None) -> list[dict]:
        return [a for a in self.table("Abilities") if faction_id and a.get("faction_id") == faction_id]

    def detachments(self, faction_id: str | None, names: list[str]) -> list[dict]:
        rows = [d for d in self.table("Detachments") if d.get("faction_id") == faction_id]
        wanted = [norm(n) for n in names]
        return [d for d in rows if norm(d["name"]) in wanted]

    def detachment_content(self, det: dict) -> dict[str, list[dict]]:
        did, name = det.get("id", ""), norm(det.get("name", ""))
        match = lambda r: (did and r.get("detachment_id") == did) or norm(r.get("detachment", "")) == name
        return {
            "rules": [r for r in self.table("Detachment_abilities") if match(r)],
            "enhancements": [r for r in self.table("Enhancements") if match(r)],
            "stratagems": [r for r in self.table("Stratagems") if match(r)],
        }

    def core_stratagems(self) -> list[dict]:
        return [s for s in self.table("Stratagems")
                if not s.get("faction_id") and s.get("type", "").lower().startswith("core")]

    # ---- unit level --------------------------------------------------------
    def unit_abilities(self, datasheet_id: str) -> dict[str, list[tuple[str, str]]]:
        """{'Core': [(name, html)], 'Faction': [...], 'Datasheet': [...], 'Wargear': [...], ...}"""
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

    def invuln_description(self, datasheet_id: str) -> str:
        """Conditions on the invulnerable save, if the datasheet has any."""
        return next((m.get("inv_sv_descr") for m in self.wd._models.get(datasheet_id, []) if m.get("inv_sv_descr")), "")

    def datasheet_row(self, datasheet_id: str) -> dict:
        return self.wd.datasheets.get(datasheet_id, {})
