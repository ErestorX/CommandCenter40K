"""Read access to the mission data written by `crunch fetch` (missions/json/): Force Dispositions,
primary missions and battlefield layouts. Files are loaded lazily; missing files read as empty."""
from __future__ import annotations

import json
from pathlib import Path

from crunch.util import norm


def _key(name: str) -> str:
    """Compare names across sources: "DESTROYER'S WRATH" == "Destroyer’s Wrath"."""
    return norm((name or "").replace("’", "'"))


class MissionBook:
    def __init__(self, json_dir: str | Path):
        self.json_dir = Path(json_dir)
        self._cache: dict[str, object] = {}

    def _load(self, name: str, empty):
        if name not in self._cache:
            try:
                self._cache[name] = json.loads((self.json_dir / f"{name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache[name] = empty
        return self._cache[name]

    @property
    def available(self) -> bool:
        return bool(self.layouts) and bool(self.primary_missions)

    @property
    def layouts(self) -> list[dict]:
        return self._load("layouts", {}).get("layouts", [])

    @property
    def primary_missions(self) -> list[dict]:
        return self._load("primary_missions", [])

    @property
    def secondary_missions(self) -> list[dict]:
        return self._load("secondary_missions", [])

    @property
    def dispositions(self) -> list[str]:
        """Force Disposition names, in the source's order."""
        names = self._load("layouts", {}).get("force_dispositions", {})
        if names:
            return list(names.values())
        return [d["name"] for d in self._load("force_dispositions", [])]

    def disposition(self, name: str) -> str | None:
        """The canonical Force Disposition name for `name` (any case), or None."""
        return next((d for d in self.dispositions if _key(d) == _key(name)), None)

    def layouts_for(self, a: str, b: str) -> list[dict]:
        """The layouts (A, B, C) of a pairing of Force Dispositions, in either order."""
        want = sorted([_key(a), _key(b)])
        found = [l for l in self.layouts if sorted(_key(d) for d in l["force_dispositions"]) == want]
        return sorted(found, key=lambda l: l.get("variant", ""))

    def primary_mission(self, own: str, opponent: str) -> dict | None:
        """The primary mission card a player with disposition `own` plays against `opponent`."""
        for p in self.primary_missions:
            if _key(p.get("force_disposition", "")) == _key(own) and \
                    _key(p.get("opponent_force_disposition", "")) == _key(opponent):
                return p
        # fall back to the layouts' mission names
        for l in self.layouts_for(own, opponent):
            for m in l.get("missions", []):
                if _key(m["force_disposition"]) == _key(own):
                    return next((p for p in self.primary_missions if _key(p["name"]) == _key(m["mission"])),
                                {"name": m["mission"], "scoring": [], "intro": [], "actions": [], "legend": ""})
        return None
