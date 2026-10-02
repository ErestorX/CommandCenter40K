"""Battlefield layouts: deployment zones, objectives and terrain for every Force Disposition pairing.

Wahapedia's deployment cards are not the ones this edition plays: each pairing of Force Dispositions
(15, mirrors included) has three layouts A / B / C from the Event Companion, each with its own
deployment zones, objectives on terrain areas and terrain. Rapid Ingress publishes them as data
(config.LAYOUTS_BASE_URL + LAYOUT_FILES); this module normalises them into

    <edition>/missions/json/layouts.json
    <edition>/missions/raw/layouts/*.js          the source files as downloaded
    <edition>/missions/archive/<date>/layouts/   earlier versions

Board: 60" wide x 44" tall, origin at the bottom-left corner, y up (the source's frame).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

TERRAIN_FILE = "terrain-data-11e.js"
MEASUREMENTS_FILE = "measurements-11e.js"
LAYOUT_FILES = (TERRAIN_FILE, MEASUREMENTS_FILE)
BOARD = {"width": 60, "height": 44, "units": "inch", "origin": "bottom-left, y up"}


def js_const(text: str, name: str):
    """The JSON literal assigned to `const NAME = ...` in a generated JS file."""
    m = re.search(rf"const {re.escape(name)}\s*=\s*", text)
    if not m:
        raise ValueError(f"{name} not found")
    return json.JSONDecoder().raw_decode(text[m.end():])[0]


def _pts(points: list[dict]) -> list[list[float]]:
    return [[p["x"], p["y"]] for p in points]


def centroid(points: list[list[float]]) -> list[float]:
    """Area centroid of a polygon (falls back to the mean of its points if degenerate)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        n = len(points) or 1
        return [round(sum(p[0] for p in points) / n, 2), round(sum(p[1] for p in points) / n, 2)]
    return [round(cx / (3 * a), 2), round(cy / (3 * a), 2)]


def board_edge(zones: list[list[list[float]]], tol: float = 0.5) -> str:
    """The board edge a deployment zone runs along most: left / right / bottom / top.
    (The source's own edge labels use the Event Companion's portrait orientation, not this frame.)"""
    W, H = BOARD["width"], BOARD["height"]
    contact = {"left": 0.0, "right": 0.0, "bottom": 0.0, "top": 0.0}
    for poly in zones:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            for edge, on in (("left", lambda x, y: x <= tol), ("right", lambda x, y: x >= W - tol),
                             ("bottom", lambda x, y: y <= tol), ("top", lambda x, y: y >= H - tol)):
                if on(x0, y0) and on(x1, y1):
                    contact[edge] += abs(x1 - x0) + abs(y1 - y0)
    return max(contact, key=contact.get) if any(contact.values()) else ""


def disposition_names(matchups: dict) -> dict[str, str]:
    """{"TH": "Take and Hold", ...} read from the labels ("Purge the Foe vs Take and Hold")."""
    names: dict[str, str] = {}
    for m in matchups.values():
        a, b = m["pair"]
        label = m.get("dispositionLabel", "")
        if " vs " in label:
            names.setdefault(a, label.split(" vs ")[0].strip())
            names.setdefault(b, label.split(" vs ")[1].strip())
        else:
            names.setdefault(a, re.sub(r"\s*\(mirror\)\s*$", "", label).strip())
    return names


def parse_layouts(terrain_js: str, measurements_js: str) -> dict:
    layouts_src = js_const(terrain_js, "ELEVEN_E_LAYOUTS")
    names = disposition_names(js_const(terrain_js, "ELEVEN_E_MATCHUPS"))
    measurements = js_const(measurements_js, "ELEVEN_E_MEASUREMENTS") if measurements_js else {}

    layouts = []
    for src in layouts_src:
        zones = {}
        for z in src.get("deploymentZones", []):
            side = "attacker" if "-dz-atk" in z["id"] else "defender" if "-dz-def" in z["id"] else z["id"]
            zones.setdefault(side, []).append(_pts(z["points"]))

        areas: dict[str, dict] = {}
        for p in src.get("terrain", []):
            area = areas.setdefault(p["areaId"], {"area": p["areaId"], "footprints": [], "features": []})
            if p.get("feature"):
                area["features"].append({"category": p.get("category", ""), "elevation": p.get("elevation"),
                                         "codes": p.get("codes", []), "points": _pts(p["points"]),
                                         "los_points": _pts(p.get("losPoints", []))})
            else:                                   # a footprint: an area can be made of several pieces
                area["footprints"].append({"piece_type": p.get("pieceType", ""),
                                           "obscuring": p.get("obscuring", False),
                                           "points": _pts(p["points"]),
                                           "los_points": _pts(p.get("losPoints", []))})
                if p.get("objective"):
                    area["objective"] = p["objective"]["number"]

        objectives = []
        for p in src.get("terrain", []):
            o = p.get("objective")
            if o and not p.get("feature"):
                objectives.append({"number": o["number"], "type": o.get("type", ""), "owner": o.get("owner"),
                                   "area": p["areaId"],
                                   "position": centroid(_pts(p.get("losPoints") or p["points"]))})
        objectives.sort(key=lambda o: o["number"])

        meas = measurements.get(src["id"], {})
        layouts.append({
            "id": src["id"],
            "variant": src.get("variant", ""),
            "force_dispositions": [names.get(c, c) for c in src["matchup"]],
            "force_disposition_codes": list(src["matchup"]),
            "missions": [{"force_disposition": names.get(c, c), "code": c, "mission": m}
                         for c, m in src.get("missions", {}).items()],
            "attacker_edge": board_edge(zones.get("attacker", [])),
            "defender_edge": board_edge(zones.get("defender", [])),
            "deployment_zones": zones,
            "objectives": objectives,
            "terrain": list(areas.values()),
            "measurements": {"lines": meas.get("dimLines", []), "labels": meas.get("dimLabels", [])},
        })
    return {"board": BOARD, "force_dispositions": names, "layouts": layouts}


def content_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def update_layouts(edition_dir: Path, base_url: str, fetch: Callable[[str], bytes | None], force: bool = False,
                   old: dict | None = None, files: dict[str, bytes] | None = None,
                   log: Callable[[str], None] = print) -> dict | None:
    """Fetch (or use `files`), parse and store the layouts if they changed.
    Returns the new manifest entry, or None when unchanged."""
    missions_dir = edition_dir / "missions"
    raw_dir = missions_dir / "raw" / "layouts"
    blobs = dict(files or {})
    for name in LAYOUT_FILES:
        if name not in blobs:
            log(f"  GET {base_url}{name}")
            b = fetch(base_url + name)
            if b is None:
                raise RuntimeError(f"layout data not found: {base_url}{name}")
            blobs[name] = b
            time.sleep(0.5)
    data = parse_layouts(blobs[TERRAIN_FILE].decode("utf-8"), blobs[MEASUREMENTS_FILE].decode("utf-8"))
    if not data["layouts"]:
        raise RuntimeError("no layouts found - has the source changed format?")
    digest = content_hash(data)
    old = old or {}
    out = missions_dir / "json" / "layouts.json"
    if not force and digest == old.get("content_sha256") and out.exists():
        log("Layouts already up to date.")
        return None

    source_changed = any((raw_dir / n).exists() and (raw_dir / n).read_bytes() != b for n, b in blobs.items())
    if source_changed:                   # archive earlier source files (not when only the parsing changed)
        arch = missions_dir / "archive" / (old.get("fetched_at") or "unknown")[:10] / "layouts"
        if not arch.exists():
            shutil.copytree(raw_dir, arch)
            log(f"Archived previous layout data to {arch}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, b in blobs.items():
        (raw_dir / name).write_bytes(b)
    _write(out, data)
    log(f"Layouts: {len(data['layouts'])} layouts for {len({tuple(sorted(l['force_disposition_codes'])) for l in data['layouts']})} "
        f"Force Disposition pairings")
    return {"source": base_url, "files": list(LAYOUT_FILES), "content_sha256": digest,
            "count": len(data["layouts"]), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def rebuild_layouts(edition_dir: Path) -> int | None:
    """Re-parse the saved source files, offline. None if none were saved."""
    raw_dir = edition_dir / "missions" / "raw" / "layouts"
    if not (raw_dir / TERRAIN_FILE).exists():
        return None
    meas = raw_dir / MEASUREMENTS_FILE
    data = parse_layouts((raw_dir / TERRAIN_FILE).read_text(encoding="utf-8"),
                         meas.read_text(encoding="utf-8") if meas.exists() else "")
    _write(edition_dir / "missions" / "json" / "layouts.json", data)
    return len(data["layouts"])
