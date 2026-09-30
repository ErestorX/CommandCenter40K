"""Wahapedia CSV export -> Unit objects. Loads the tables once and builds units on demand."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path

from crunch import config
from crunch.core.dice import Dice
from crunch.core.keywords import parse_weapon_keywords
from crunch.core.models import ModelProfile, Unit, Weapon
from crunch.util import norm, strip_html, to_int as _int


def read_table(data_dir: Path, name: str) -> list[dict]:
    path = Path(data_dir) / f"{name}.csv"
    if not path.exists():
        return []
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter="|")
    return [{k: (v or "").strip() for k, v in r.items() if k} for r in rows]


# List builders name some factions differently from Wahapedia (chapters, super-faction names).
# Keys are norm()-ed names, values Wahapedia faction ids.
FACTION_ALIASES = {
    **{k: "SM" for k in ("adeptusastartes", "spacemarine", "bloodangels", "darkangels", "spacewolves",
                         "blacktemplars", "deathwatch", "ultramarines", "imperialfists", "ironhands",
                         "ravenguard", "salamanders", "whitescars")},
    "hereticastartes": "CSM", "chaosspacemarines": "CSM",
    "asuryani": "AE", "craftworlds": "AE", "harlequins": "AE", "ynnari": "AE",
    "tauempire": "TAU", "tau": "TAU",
    "leaguesofvotann": "LoV", "votann": "LoV",
    "imperialagents": "AoI", "agentsoftheimperium": "AoI",
    "sistersofbattle": "AS", "adeptasororitas": "AS",
    "genestealercults": "GC", "genestealercult": "GC",
}


class Wahapedia:
    """Loads the raw CSVs once and builds Unit objects on demand."""

    def __init__(self, data_dir: str | Path | None = None):
        d = Path(data_dir) if data_dir else config.find_data_dir()
        if not d or not (d / "Datasheets.csv").exists():
            raise FileNotFoundError("No Wahapedia data found. Run `python -m crunch fetch` first.")
        self.data_dir = d
        self.datasheets = {r["id"]: r for r in read_table(d, "Datasheets")}
        self.factions = {r["id"]: r["name"] for r in read_table(d, "Factions")}
        self._models = self._by_ds(read_table(d, "Datasheets_models"))
        self._wargear = self._by_ds(read_table(d, "Datasheets_wargear"))
        self._keywords = self._by_ds(read_table(d, "Datasheets_keywords"))
        self.leads: dict[str, set[str]] = defaultdict(set)   # leader id -> bodyguard ids
        for r in read_table(d, "Datasheets_leader"):
            self.leads[r.get("leader_id", "")].add(r.get("attached_id", ""))
        lu = read_table(d, "Last_update")
        self.last_update = next(iter(lu[0].values()), "") if lu else ""
        self._cache: dict[str, Unit] = {}

    @staticmethod
    def _by_ds(rows):
        g = defaultdict(list)
        for r in rows:
            g[r.get("datasheet_id", "")].append(r)
        return g

    def faction_id(self, name: str) -> str | None:
        n = norm(name)
        for fid, fname in self.factions.items():
            if norm(fname) == n or norm(fid) == n:
                return fid
        alias = FACTION_ALIASES.get(n)
        return alias if alias in self.factions else None

    def find(self, name: str, faction_id: str | None = None) -> str | None:
        """Datasheet id by name, preferring the given faction."""
        n = norm(name)
        hits = [i for i, r in self.datasheets.items() if norm(r["name"]) == n]
        if not hits:
            hits = [i for i, r in self.datasheets.items() if norm(r["name"]) in (n.rstrip("s"), n + "s")]
        if not hits:
            return None
        same = [i for i in hits if self.datasheets[i].get("faction_id") == faction_id]
        return (same or hits)[0]

    def unit(self, did: str) -> Unit:
        if did in self._cache:
            return self._cache[did]
        ds = self.datasheets[did]
        models = [
            ModelProfile(
                name=m.get("name") or ds["name"], M=m.get("M", ""),
                T=_int(m.get("T"), 4), Sv=_int(m.get("Sv"), 7),
                inv=_int(m.get("inv_sv")) if _int(m.get("inv_sv")) else None,
                W=_int(m.get("W"), 1),
            )
            for m in self._models.get(did, [])
        ] or [ModelProfile(ds["name"], "", 4, 7, None, 1)]
        weapons = []
        for w in self._wargear.get(did, []):
            skill = w.get("BS_WS", "")
            if not w.get("name") or w.get("A", "") in ("", "-") or (skill == "-" and "torrent" not in w.get("description", "").lower()):
                continue
            try:
                weapons.append(Weapon(
                    name=strip_html(w["name"]), type=w.get("type") or "Ranged", range=w.get("range") or "",
                    A=Dice.parse(w.get("A")),
                    skill=None if skill.upper() in ("N/A", "", "-") else _int(skill),
                    S=_int(w.get("S"), 4), AP=abs(_int(w.get("AP"), 0)), D=Dice.parse(w.get("D")),
                    keywords=parse_weapon_keywords(w.get("description", "")),
                ))
            except ValueError:
                continue
        kws = {k["keyword"].lower() for k in self._keywords.get(did, []) if k.get("keyword")}
        u = Unit(did, ds["name"], ds.get("faction_id", ""), models, weapons, kws,
                 ds.get("is_support", "").lower() == "true")
        self._cache[did] = u
        return u

    def unit_by_name(self, name: str, faction: str | None = None) -> Unit:
        did = self.find(name, self.faction_id(faction) if faction else None)
        if not did:
            raise KeyError(f"No datasheet matching {name!r}")
        return self.unit(did)

    def can_lead(self, leader_id: str, bodyguard_id: str) -> bool:
        return bodyguard_id in self.leads.get(leader_id, ())
