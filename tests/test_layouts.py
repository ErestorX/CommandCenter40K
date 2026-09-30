"""Battlefield layouts from Rapid Ingress: parsing, geometry, and the update check."""
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from crunch.data.layouts import (LAYOUT_FILES, MEASUREMENTS_FILE, TERRAIN_FILE, board_edge, centroid, js_const,
                                 parse_layouts, rebuild_layouts, update_layouts)

FIX = Path(__file__).parent / "fixtures" / "rapidingress"
FILES = {n: (FIX / n).read_bytes() for n in LAYOUT_FILES}
BASE = "https://rapidingress.com/"


def inside(pt, poly):
    x, y = pt
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


class ParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = parse_layouts(FILES[TERRAIN_FILE].decode(), FILES[MEASUREMENTS_FILE].decode())
        cls.by_id = {l["id"]: l for l in cls.data["layouts"]}

    def test_dispositions_and_missions(self):
        self.assertEqual(self.data["force_dispositions"],
                         {"TH": "Take and Hold", "PF": "Purge the Foe", "DI": "Disruption", "RE": "Reconnaissance",
                          "PA": "Priority Assets"})
        l = self.by_id["PF-TH-B"]
        self.assertEqual((l["variant"], l["force_dispositions"]), ("B", ["Purge the Foe", "Take and Hold"]))
        self.assertEqual({m["force_disposition"]: m["mission"] for m in l["missions"]},
                         {"Take and Hold": "Immovable Object", "Purge the Foe": "Unstoppable Force"})
        self.assertEqual(self.by_id["TH-TH-A"]["missions"],
                         [{"force_disposition": "Take and Hold", "code": "TH", "mission": "Battlefield Dominance"}])

    def test_deployment_zones_on_opposite_edges(self):
        opposite = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
        for l in self.data["layouts"]:
            with self.subTest(l["id"]):
                self.assertEqual(set(l["deployment_zones"]), {"attacker", "defender"})
                self.assertEqual(opposite[l["attacker_edge"]], l["defender_edge"])
        self.assertEqual((self.by_id["TH-TH-A"]["attacker_edge"], self.by_id["TH-TH-A"]["defender_edge"]),
                         ("left", "right"))

    def test_home_objectives_are_in_their_owners_zone(self):
        for l in self.data["layouts"]:
            homes = [o for o in l["objectives"] if o["type"] == "home"]
            self.assertEqual(sorted(o["owner"] for o in homes), ["attacker", "defender"])
            for o in homes:
                with self.subTest(l["id"], objective=o["number"]):
                    self.assertTrue(any(inside(o["position"], z) for z in l["deployment_zones"][o["owner"]]))

    def test_objectives_sit_on_terrain_areas(self):
        l = self.by_id["TH-TH-A"]
        self.assertEqual([o["number"] for o in l["objectives"]], [1, 2, 3, 4, 5])
        areas = {a["area"]: a for a in l["terrain"]}
        for o in l["objectives"]:
            self.assertEqual(areas[o["area"]]["objective"], o["number"])

    def test_terrain_areas_and_features(self):
        a = self.by_id["TH-TH-A"]["terrain"][0]
        fp = a["footprints"][0]
        self.assertEqual((a["area"], fp["piece_type"], fp["obscuring"]), ("TH-TH-A-T01", "large_rect_7x11.5", True))
        self.assertTrue(fp["points"] and fp["los_points"])
        self.assertTrue(a["features"])
        self.assertEqual(set(a["features"][0]), {"category", "elevation", "codes", "points"})

    def test_every_footprint_piece_is_kept(self):
        # T03 of TH-TH-A is made of two footprint pieces (the one carrying objective 2, and another)
        t03 = next(a for a in self.by_id["TH-TH-A"]["terrain"] if a["area"] == "TH-TH-A-T03")
        self.assertEqual(len(t03["footprints"]), 2)
        self.assertEqual(t03["objective"], 2)
        for src in js_const(FILES[TERRAIN_FILE].decode(), "ELEVEN_E_LAYOUTS"):
            want = Counter(p["areaId"] for p in src["terrain"] if not p.get("feature"))
            got = Counter({a["area"]: len(a["footprints"]) for a in self.by_id[src["id"]]["terrain"]})
            self.assertEqual(+got, want, src["id"])

    def test_measurements(self):
        m = self.by_id["TH-TH-A"]["measurements"]
        self.assertTrue(m["lines"] and len(m["lines"][0]) == 4)
        self.assertEqual(m["labels"][0]["text"], '25"')

    def test_geometry_helpers(self):
        self.assertEqual(centroid([[0, 0], [4, 0], [4, 2], [0, 2]]), [2.0, 1.0])
        self.assertEqual(board_edge([[[0, 0], [12, 0], [12, 44], [0, 44]]]), "left")
        self.assertEqual(board_edge([[[0, 32], [60, 32], [60, 44], [0, 44]]]), "top")


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch("crunch.data.layouts.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def site(self, files=FILES):
        requests = []

        def get(url):
            requests.append(url)
            return files.get(url[len(BASE):])
        return get, requests

    def run_update(self, fetch, old=None, **kw):
        return update_layouts(self.tmp, BASE, fetch, old=old, log=lambda m: None, **kw)

    def test_first_run_stores_raw_and_json(self):
        fetch, requests = self.site()
        entry = self.run_update(fetch)
        self.assertEqual(entry["count"], 2)
        self.assertEqual(sorted(requests), sorted(BASE + n for n in LAYOUT_FILES))
        m = self.tmp / "missions"
        self.assertEqual((m / "raw" / "layouts" / TERRAIN_FILE).read_bytes(), FILES[TERRAIN_FILE])
        data = json.loads((m / "json" / "layouts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["layouts"]), 2)

    def test_unchanged_then_changed(self):
        entry = self.run_update(self.site()[0])
        self.assertIsNone(self.run_update(self.site()[0], old=entry))
        changed = dict(FILES, **{TERRAIN_FILE: FILES[TERRAIN_FILE].replace(b"Immovable Object", b"Immovable Wall")})
        new = self.run_update(self.site(changed)[0], old=entry)
        self.assertNotEqual(new["content_sha256"], entry["content_sha256"])
        archived = list((self.tmp / "missions" / "archive").glob(f"*/layouts/{TERRAIN_FILE}"))
        self.assertEqual([p.read_bytes() for p in archived], [FILES[TERRAIN_FILE]])

    def test_files_saved_by_hand_need_no_download(self):
        fetch, requests = self.site()
        self.assertEqual(self.run_update(fetch, files=dict(FILES))["count"], 2)
        self.assertEqual(requests, [])

    def test_missing_file_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.run_update(self.site({})[0])

    def test_rebuild_offline(self):
        self.run_update(self.site()[0])
        (self.tmp / "missions" / "json" / "layouts.json").unlink()
        self.assertEqual(rebuild_layouts(self.tmp), 2)


if __name__ == "__main__":
    unittest.main()
