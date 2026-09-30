"""
Download Wahapedia's CSV export and build a structured data tree.

    python -m crunch fetch                  # -> <project>/wahapedia_data/wh40k11ed/
    python -m crunch fetch --force          # re-download even if unchanged
    python -m crunch fetch --from-dir DIR   # build from CSVs saved by hand
    python -m crunch fetch --rebuild-json   # only rebuild json/ from raw/

Output: <root>/<edition>/{raw/, archive/<update>/, json/, manifest.json, README.txt}

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

from crunch import config

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

USER_AGENT = "Mozilla/5.0 (crunch fetch; personal mathhammer tool)"
ATTRIBUTION = config.ATTRIBUTION


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


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


def fetch(url: str, retries: int = 3) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
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
            sys.exit(f"Last_update.csv not found at {base_url} - is the edition name right?")
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
        sys.exit(f"Missing required tables: {', '.join(sorted(missing))}")

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
manifest.json Row counts and SHA-256 per table, to detect changes.

Please keep the attribution line with any copy or use of this data.
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m crunch fetch", description="Download Wahapedia's export into a structured tree.")
    ap.add_argument("--out", default=str(config.DATA_ROOT), help="root output folder (default: <project>/wahapedia_data)")
    ap.add_argument("--edition", default=DEFAULT_EDITION, help="Wahapedia edition path (default: wh40k11ed)")
    ap.add_argument("--force", action="store_true", help="download and rebuild even if unchanged")
    ap.add_argument("--from-dir", type=Path, help="build from CSVs already on disk instead of downloading")
    ap.add_argument("--rebuild-json", action="store_true", help="only rebuild json/ from the existing raw/")
    a = ap.parse_args(argv)

    edition_dir = Path(a.out) / a.edition
    edition_dir.mkdir(parents=True, exist_ok=True)
    base_url = BASE_URL.format(edition=a.edition)

    if a.rebuild_json:
        raw = edition_dir / "raw"
        blobs = {p.stem: p.read_bytes() for p in raw.glob("*.csv")}
        if not blobs:
            sys.exit(f"No CSVs in {raw}")
    else:
        try:
            blobs = download(edition_dir, base_url, a.force, a.from_dir)
        except RuntimeError as e:
            sys.exit(f"{e}\nIf Wahapedia blocks scripted downloads, save the CSVs from "
                     f"{base_url}  (links on its 'Data Export' page) into a folder and rerun with --from-dir.")
        if blobs is None:
            return

    log("Building JSON tree...")
    counts = build(edition_dir, blobs)
    stamp = last_update_stamp(blobs["Last_update"]) if "Last_update" in blobs else ""
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(edition_dir / "manifest.json", {
        "attribution": ATTRIBUTION,
        "source": base_url,
        "edition": a.edition,
        "last_update": stamp,
        "fetched_at": fetched,
        "tables": {t: {"rows": counts.get(t, 0), "sha256": hashlib.sha256(blobs[t]).hexdigest()}
                   for t in sorted(blobs)},
        "missing_tables": [t for t in TABLES if t not in blobs],
    })
    (edition_dir / "README.txt").write_text(
        README.format(attribution=ATTRIBUTION, url=base_url, stamp=stamp or "unknown", fetched=fetched),
        encoding="utf-8")

    n_f = len(json.loads((edition_dir / "json" / "index.json").read_text(encoding="utf-8"))["factions"])
    log(f"Done: {n_f} factions, {counts.get('Datasheets', 0)} datasheets, "
        f"{counts.get('Stratagems', 0)} stratagems -> {edition_dir.resolve()}")
    log(ATTRIBUTION)


if __name__ == "__main__":
    main()