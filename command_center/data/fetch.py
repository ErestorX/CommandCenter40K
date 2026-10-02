"""
Download Wahapedia's CSV export and mission deck, the battlefield layouts, and build a data tree.

    python -m command_center fetch                  # -> <project>/wahapedia_data/wh40k11ed/
    python -m command_center fetch --force          # re-download even if unchanged
    python -m command_center fetch --from-dir DIR   # build from files saved by hand: the CSVs, and optionally
                                            # mission_deck.html, terrain-data-11e.js, measurements-11e.js
    python -m command_center fetch --rebuild-json   # only rebuild json/ (and missions/json/) from what's saved
    python -m command_center fetch --no-missions    # CSVs only

The app runs the same update by itself when it starts, if the last check is more than a day old
(update(), is_stale(): see command_center.ui.app).

Output: <root>/<edition>/{raw/, archive/<update>/, json/, missions/, manifest.json, README.txt}
The CSVs, the mission deck (command_center.data.missions) and the layouts (command_center.data.layouts) are checked
for updates separately.

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are (c) Games Workshop.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from command_center import config
from command_center.data import layouts, missions

BASE_URL = config.WAHAPEDIA_BASE_URL
DEFAULT_EDITION = config.EDITION

# Tables in Wahapedia's 40k export spec. Missing ones are skipped, not fatal.
TABLES = [
    "Last_update",
    "Factions",
    "Source",
    "Detachments",
    "Datasheets",
    "Datasheets_abilities",
    "Datasheets_keywords",
    "Datasheets_models",
    "Datasheets_options",
    "Datasheets_wargear",
    "Datasheets_unit_composition",
    "Datasheets_models_cost",
    "Datasheets_stratagems",
    "Datasheets_enhancements",
    "Datasheets_detachment_abilities",
    "Datasheets_leader",
    "Stratagems",
    "Abilities",
    "Enhancements",
    "Detachment_abilities",
]
REQUIRED = {"Datasheets", "Factions"}

USER_AGENT = "Mozilla/5.0 (command_center fetch; personal mathhammer tool)"
ATTRIBUTION = config.ATTRIBUTION


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------
RETRIES, TIMEOUT = 3, 60          # per request: attempts, seconds
MAX_AGE_HOURS = 24                # the data is checked again once the last check is older than this
_sink = None                      # where log() writes instead of the console (see set_log)


def log(msg: str) -> None:
    if _sink:
        _sink(msg)
    else:
        print(msg, flush=True)


def set_log(sink) -> None:
    """Send the progress messages to sink(message) (None: back to the console)."""
    global _sink
    _sink = sink


def slug(text: str, max_len: int = 60) -> str:
    """Filesystem-safe name (Windows-safe too)."""
    s = html.unescape(text or "").lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return (s or "unnamed")[:max_len]


def strip_html(text: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def parse_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = []
    for r in csv.DictReader(io.StringIO(text), delimiter="|"):
        # Wahapedia lines end with a trailing '|' -> empty-named column; drop it
        row = {k.strip(): (v or "").strip() for k, v in r.items() if k and k.strip()}
        for k in list(row):
            if k in ("description", "legend", "abilities") and "<" in row[k]:
                row[f"{k}_text"] = strip_html(row[k])
        rows.append(row)
    return rows


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url: str, retries: int | None = None) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    retries = retries or RETRIES
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = str(getattr(e, "reason", e))
        if attempt < retries:
            time.sleep(2 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {err}")


# -----------------------------------------------------------------------------
# step 1: get the raw CSVs
# -----------------------------------------------------------------------------
def download(edition_dir: Path, base_url: str, force: bool, from_dir: Path | None) -> dict[str, bytes] | None:
    raw_dir = edition_dir / "raw"
    manifest_path = edition_dir / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    blobs: dict[str, bytes] = {}
    if from_dir:
        for t in TABLES:
            p = from_dir / f"{t}.csv"
            if p.exists():
                blobs[t] = p.read_bytes()
        log(f"Read {len(blobs)} CSVs from {from_dir}")
    else:
        stamp_blob = fetch(base_url + "Last_update.csv")
        if stamp_blob is None:
            raise RuntimeError(f"Last_update.csv not found at {base_url} - is the edition name right?")
        stamp = last_update_stamp(stamp_blob)
        if not force and stamp and stamp == old_manifest.get("last_update") and raw_dir.exists():
            log(f"Already up to date (Wahapedia last update {stamp}). Use --force to rebuild.")
            return None
        log(f"Wahapedia last update: {stamp or 'unknown'}")
        blobs["Last_update"] = stamp_blob
        for t in TABLES[1:]:
            log(f"  GET {t}.csv")
            b = fetch(base_url + f"{t}.csv")
            if b is None:
                log(f"    (not published, skipped)")
                continue
            blobs[t] = b
            time.sleep(0.5)  # be polite to a free, donation-funded site

    missing = REQUIRED - set(blobs)
    if missing:
        raise RuntimeError(f"Missing required tables: {', '.join(sorted(missing))}")

    # archive the previous raw set before overwriting
    if raw_dir.exists() and any(raw_dir.iterdir()):
        prev = old_manifest.get("last_update") or "unknown"
        arch = edition_dir / "archive" / slug(prev.replace(":", "-"), 40)
        if not arch.exists():
            shutil.copytree(raw_dir, arch)
            log(f"Archived previous CSVs to {arch}")
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for t, b in blobs.items():
        (raw_dir / f"{t}.csv").write_bytes(b)
    return blobs


def last_update_stamp(blob: bytes) -> str:
    rows = parse_csv(blob)
    if rows:
        return next(iter(rows[0].values()), "")
    return blob.decode("utf-8-sig", errors="replace").strip().splitlines()[-1].strip("|")


# -----------------------------------------------------------------------------
# step 2: build the JSON tree
# -----------------------------------------------------------------------------
def build(edition_dir: Path, blobs: dict[str, bytes]) -> dict:
    T = {name: parse_csv(b) for name, b in blobs.items()}
    get = lambda name: T.get(name, [])
    json_dir = edition_dir / "json"
    if json_dir.exists():
        shutil.rmtree(json_dir)

    # ---- lookups ----------------------------------------------------------
    abilities_by_id = {a["id"]: a for a in get("Abilities") if a.get("id")}
    strat_by_id = {s["id"]: s for s in get("Stratagems") if s.get("id")}
    enh_by_id = {e["id"]: e for e in get("Enhancements") if e.get("id")}

    # every "Datasheets_<x>" table with a datasheet_id column becomes a child list
    children: dict[str, dict[str, list]] = {}
    for name, rows in T.items():
        if name.startswith("Datasheets_") and rows and "datasheet_id" in rows[0]:
            key = name[len("Datasheets_"):].lower()
            grouped = defaultdict(list)
            for r in rows:
                grouped[r["datasheet_id"]].append({k: v for k, v in r.items() if k != "datasheet_id"})
            children[key] = grouped

    leads, led_by = defaultdict(list), defaultdict(list)
    for r in get("Datasheets_leader"):
        if r.get("leader_id") and r.get("attached_id"):
            leads[r["leader_id"]].append(r["attached_id"])
            led_by[r["attached_id"]].append(r["leader_id"])

    ds_by_id = {d["id"]: d for d in get("Datasheets") if d.get("id")}
    factions = {f["id"]: f for f in get("Factions") if f.get("id")}

    # ---- group everything by faction --------------------------------------
    by_faction = lambda rows: _group(rows, "faction_id")
    f_datasheets = by_faction(get("Datasheets"))
    f_strats = by_faction(get("Stratagems"))
    f_enh = by_faction(get("Enhancements"))
    f_det_abil = by_faction(get("Detachment_abilities"))
    f_detachments = by_faction(get("Detachments"))
    f_abilities = by_faction(get("Abilities"))

    # core / shared abilities (no faction)
    write_json(json_dir / "core" / "abilities.json", f_abilities.get("", []))

    index = {"attribution": ATTRIBUTION, "factions": []}
    for fid in sorted(set(factions) | set(f_datasheets)):
        frow = factions.get(fid, {"id": fid, "name": fid})
        fdir = json_dir / "factions" / f"{slug(fid, 12)}_{slug(frow.get('name', fid))}"

        # detachments: explicit table if present, otherwise inferred from the rows
        dets: dict[str, dict] = {}
        for d in f_detachments.get(fid, []):
            dets[d.get("id") or d.get("name")] = {**d, "abilities": [], "enhancements": [], "stratagems": []}
        for kind, rows in (("abilities", f_det_abil.get(fid, [])),
                           ("enhancements", f_enh.get(fid, [])),
                           ("stratagems", f_strats.get(fid, []))):
            for r in rows:
                key = r.get("detachment_id") or r.get("detachment")
                if not key:
                    continue
                dets.setdefault(key, {"id": r.get("detachment_id", ""), "name": r.get("detachment", key),
                                      "abilities": [], "enhancements": [], "stratagems": []})
                dets[key][kind].append(r)
        det_files = []
        used = set()
        for key, det in dets.items():
            name = slug(det.get("name") or key)
            if name in used:
                name = f"{name}_{slug(key, 12)}"
            used.add(name)
            write_json(fdir / "detachments" / f"{name}.json", det)
            det_files.append({"id": det.get("id"), "name": det.get("name"),
                              "file": f"detachments/{name}.json"})

        write_json(fdir / "faction.json", {
            **frow,
            "army_rules": f_abilities.get(fid, []),
            "detachments": det_files,
            "attribution": ATTRIBUTION,
        })
        write_json(fdir / "stratagems.json", f_strats.get(fid, []))
        write_json(fdir / "enhancements.json", f_enh.get(fid, []))

        # datasheets
        ds_entries = []
        used = set()
        for ds in f_datasheets.get(fid, []):
            did = ds["id"]
            name = slug(ds.get("name", did))
            if name in used:
                name = f"{name}_{slug(did, 12)}"
            used.add(name)
            out = dict(ds)
            for key, grouped in children.items():
                out[key] = grouped.get(did, [])
            # resolve shared abilities referenced by id
            for a in out.get("abilities", []):
                ref = abilities_by_id.get(a.get("ability_id", ""))
                if ref:
                    for k in ("name", "legend", "description", "description_text"):
                        if not a.get(k) and ref.get(k):
                            a[k] = ref[k]
            out["leads"] = [{"id": i, "name": ds_by_id.get(i, {}).get("name", "")} for i in leads.get(did, [])]
            out["led_by"] = [{"id": i, "name": ds_by_id.get(i, {}).get("name", "")} for i in led_by.get(did, [])]
            out["stratagem_names"] = [strat_by_id[s["stratagem_id"]]["name"]
                                      for s in out.get("stratagems", [])
                                      if s.get("stratagem_id") in strat_by_id]
            out["enhancement_names"] = [enh_by_id[e["enhancement_id"]]["name"]
                                        for e in out.get("enhancements", [])
                                        if e.get("enhancement_id") in enh_by_id]
            write_json(fdir / "datasheets" / f"{name}.json", out)
            ds_entries.append({"id": did, "name": ds.get("name"), "role": ds.get("role", ""),
                               "file": f"datasheets/{name}.json"})

        index["factions"].append({
            "id": fid, "name": frow.get("name", fid),
            "dir": fdir.relative_to(json_dir).as_posix(),
            "datasheets": sorted(ds_entries, key=lambda e: e["name"] or ""),
            "detachments": det_files,
            "stratagem_count": len(f_strats.get(fid, [])),
        })
    write_json(json_dir / "index.json", index)
    return {name: len(rows) for name, rows in T.items()}


def _group(rows: list[dict], key: str) -> dict[str, list]:
    g = defaultdict(list)
    for r in rows:
        g[r.get(key, "")].append(r)
    return g


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------
README = """\
{attribution}

Source: {url}
Wahapedia last update: {stamp}
Fetched: {fetched}

raw/          Wahapedia's CSV export, unchanged ('|'-delimited, UTF-8, HTML in text fields).
              Use this folder as mathhammer.py's --data.
archive/      Earlier raw exports, one folder per Wahapedia update.
json/         The same data regrouped per faction / detachment / datasheet.
missions/     json/force_dispositions, primary_missions, secondary_missions.json from the mission
              deck page ({missions_url}), and json/layouts.json: the battlefield layouts
              (deployment zones, objectives, terrain) from {layouts_url}.
              raw/ holds the sources as downloaded, archive/ their earlier versions.
manifest.json Row counts and SHA-256 per table, and content hashes of the missions and layouts.

Please keep the attribution line with any copy or use of this data.
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m command_center fetch", description="Download Wahapedia's export into a structured tree.")
    ap.add_argument("--out", default=str(config.DATA_ROOT), help="root output folder (default: <project>/wahapedia_data)")
    ap.add_argument("--edition", default=DEFAULT_EDITION, help="Wahapedia edition path (default: wh40k11ed)")
    ap.add_argument("--force", action="store_true", help="download and rebuild even if unchanged")
    ap.add_argument("--from-dir", type=Path, help="build from CSVs already on disk instead of downloading")
    ap.add_argument("--rebuild-json", action="store_true", help="only rebuild json/ from the existing raw/")
    ap.add_argument("--no-missions", action="store_true", help="skip the mission deck page")
    a = ap.parse_args(argv)

    edition_dir = Path(a.out) / a.edition
    edition_dir.mkdir(parents=True, exist_ok=True)
    base_url = BASE_URL.format(edition=a.edition)
    missions_url = config.MISSION_DECK_URL.format(edition=a.edition)

    if a.rebuild_json:
        raw = edition_dir / "raw"
        blobs = {p.stem: p.read_bytes() for p in raw.glob("*.csv")}
        if not blobs:
            sys.exit(f"No CSVs in {raw}")
        if not a.no_missions:
            counts = missions.rebuild_missions(edition_dir)
            log(f"Rebuilt missions/json: {counts}" if counts else "No saved mission deck page to rebuild.")
            n = layouts.rebuild_layouts(edition_dir)
            log(f"Rebuilt missions/json/layouts.json: {n} layouts" if n else "No saved layout data to rebuild.")
        build_csv_tree(edition_dir, base_url, missions_url, a.edition, blobs)
    else:
        try:
            update(edition_dir, a.edition, a.force, a.from_dir, not a.no_missions)
        except RuntimeError as e:
            sys.exit(f"{e}\nIf Wahapedia blocks scripted downloads, save the CSVs from "
                     f"{base_url}  (links on its 'Data Export' page) into a folder and rerun with --from-dir.")


def update(edition_dir: Path, edition: str = DEFAULT_EDITION, force: bool = False, from_dir: Path | None = None,
           with_missions: bool = True) -> bool:
    """Bring the data tree up to date: download what changed (or read it from `from_dir`) and rebuild.
    Returns whether the CSV data changed. RuntimeError when Wahapedia can't be reached or a required
    table is missing: nothing is then changed, and the missions are not checked either.
    A check against the site is noted in the manifest (checked_at): see is_stale()."""
    edition_dir.mkdir(parents=True, exist_ok=True)
    base_url = BASE_URL.format(edition=edition)
    missions_url = config.MISSION_DECK_URL.format(edition=edition)
    blobs = download(edition_dir, base_url, force, from_dir)
    if with_missions:
        update_missions_step(edition_dir, missions_url, force, from_dir)
    if blobs is not None:
        build_csv_tree(edition_dir, base_url, missions_url, edition, blobs)
    if not from_dir:
        mark_checked(edition_dir)
    return blobs is not None


def mark_checked(edition_dir: Path, when: datetime | None = None) -> None:
    """Note in the manifest that the data was checked against the site (now, unless `when`)."""
    manifest_path = edition_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["checked_at"] = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    write_json(manifest_path, manifest)


def last_checked(edition_dir: Path) -> datetime | None:
    """When the data was last checked against the site (or, failing that, last built); None if never."""
    try:
        manifest = json.loads((edition_dir / "manifest.json").read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(manifest.get("checked_at") or manifest["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def is_stale(edition_dir: Path, max_age_hours: float = MAX_AGE_HOURS, now: datetime | None = None) -> bool:
    """The data is due for a check: never checked, or more than `max_age_hours` ago."""
    checked = last_checked(edition_dir)
    if checked is None:
        return True
    return ((now or datetime.now(timezone.utc)) - checked).total_seconds() > max_age_hours * 3600


def update_missions_step(edition_dir: Path, url: str, force: bool, from_dir: Path | None) -> None:
    """Check the mission deck and the layouts for changes; a failure here never stops the CSV update."""
    manifest_path = edition_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    saved = from_dir / missions.PAGE_FILE if from_dir else None
    page = saved.read_bytes() if saved and saved.exists() else None
    log("Checking the mission deck...")
    try:
        entry = missions.update_missions(edition_dir, url, fetch, force, manifest.get("missions"), page, log)
        if entry:
            manifest["missions"] = entry
    except RuntimeError as e:
        log(f"  Mission deck skipped: {e}\n  (save the page as {missions.PAGE_FILE} and rerun with --from-dir)")

    saved = {n: from_dir / n for n in layouts.LAYOUT_FILES} if from_dir else {}
    files = {n: p.read_bytes() for n, p in saved.items() if p.exists()}
    log("Checking the battlefield layouts...")
    try:
        entry = layouts.update_layouts(edition_dir, config.LAYOUTS_BASE_URL, fetch, force, manifest.get("layouts"),
                                       files, log)
        if entry:
            manifest["layouts"] = entry
    except (RuntimeError, ValueError) as e:
        log(f"  Layouts skipped: {e}\n  (save {', '.join(layouts.LAYOUT_FILES)} from "
            f"{config.LAYOUTS_BASE_URL} and rerun with --from-dir)")
    write_json(manifest_path, manifest)


def build_csv_tree(edition_dir: Path, base_url: str, missions_url: str, edition: str,
                   blobs: dict[str, bytes]) -> None:
    manifest_path = edition_dir / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    log("Building JSON tree...")
    counts = build(edition_dir, blobs)
    stamp = last_update_stamp(blobs["Last_update"]) if "Last_update" in blobs else ""
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(manifest_path, {
        "attribution": ATTRIBUTION,
        "source": base_url,
        "edition": edition,
        "last_update": stamp,
        "fetched_at": fetched,
        **({"checked_at": old_manifest["checked_at"]} if "checked_at" in old_manifest else {}),
        "tables": {t: {"rows": counts.get(t, 0), "sha256": hashlib.sha256(blobs[t]).hexdigest()}
                   for t in sorted(blobs)},
        "missing_tables": [t for t in TABLES if t not in blobs],
        **{k: old_manifest[k] for k in ("missions", "layouts") if k in old_manifest},
    })
    (edition_dir / "README.txt").write_text(
        README.format(attribution=ATTRIBUTION, url=base_url, stamp=stamp or "unknown", fetched=fetched,
                      missions_url=missions_url, layouts_url=config.LAYOUTS_BASE_URL),
        encoding="utf-8")

    n_f = len(json.loads((edition_dir / "json" / "index.json").read_text(encoding="utf-8"))["factions"])
    log(f"Done: {n_f} factions, {counts.get('Datasheets', 0)} datasheets, "
        f"{counts.get('Stratagems', 0)} stratagems -> {edition_dir.resolve()}")
    log(ATTRIBUTION)


if __name__ == "__main__":
    main()