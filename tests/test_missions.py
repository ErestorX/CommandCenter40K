"""Mission deck scraping: parsing the page, storing it, and the update check in `crunch fetch`."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crunch.data import fetch as fetch_mod
from crunch.data.missions import PAGE_FILE, parse_deck, rebuild_missions, update_missions

FIX = Path(__file__).parent / "fixtures" / "wahapedia"
PAGE = (FIX / "mission_deck.html").read_bytes()
URL = "https://wahapedia.ru/wh40k11ed/the-rules/mission-deck-2026-27/"


class FakeSite:
    """Serves the fixture page and fake map images; counts requests."""

    def __init__(self, page=PAGE):
        self.page, self.requests = page, []

    def __call__(self, url):
        self.requests.append(url)
        if url == URL:
            return self.page
        if url.endswith(".png"):
            return b"PNG:" + url.rsplit("/", 1)[-1].encode()
        return None


class ParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deck = parse_deck(PAGE.decode("utf-8"), URL)

    def test_counts(self):
        self.assertEqual({k: len(v) for k, v in self.deck.items()},
                         {"force_dispositions": 5, "primary_missions": 3, "secondary_missions": 2, "deployments": 2})

    def test_force_disposition_matchups(self):
        purge = next(d for d in self.deck["force_dispositions"] if d["key"] == "PurgeTheFoe")
        self.assertEqual(purge["name"], "Purge the Foe")
        self.assertEqual([(m["opponent"], m["mission"]) for m in purge["matchups"]][:2],
                         [("Take and Hold", "UNSTOPPABLE FORCE"), ("Purge the Foe", "MEATGRINDER")])
        self.assertEqual(len(purge["matchups"]), 5)

    def test_primary_mission_matches_its_dispositions(self):
        by_name = {p["name"]: p for p in self.deck["primary_missions"]}
        for fd in self.deck["force_dispositions"]:
            for m in fd["matchups"]:
                p = by_name.get(m["mission"])
                if p:
                    self.assertEqual((p["force_disposition"], p["opponent_force_disposition"]),
                                     (fd["name"], m["opponent"]))

    def test_primary_scoring(self):
        p = next(p for p in self.deck["primary_missions"] if p["name"] == "BATTLEFIELD DOMINANCE")
        self.assertEqual([b["round"] for b in p["scoring"]], ["FIRST AND SECOND BATTLE ROUND",
                                                             "SECOND BATTLE ROUND ONWARDS"])
        first = p["scoring"][0]
        self.assertEqual(first["when"], "End of your turn.")
        self.assertEqual(first["conditions"][0]["text"], "You control more objectives than your opponent.")
        self.assertEqual(first["conditions"][0]["vp"], [{"vp": "2VP", "notes": []}])
        extra = p["scoring"][1]["conditions"][1]
        self.assertTrue(extra["additional"])
        self.assertEqual(extra["vp"], [{"vp": "+2VP", "notes": ["CUMULATIVE"]}])
        self.assertIn("You control more objectives than your opponent. 2VP", p["text"])

    def test_or_lines_and_intro_rules(self):
        p = next(p for p in self.deck["primary_missions"] if p["name"] == "CONSECRATE")
        conds = p["scoring"][0]["conditions"]
        self.assertEqual([c["alternative"] for c in conds], [False, True])
        self.assertTrue(conds[1]["text"].startswith("Three or more objectives"))
        self.assertTrue(p["intro"] and p["intro"][0].startswith("Each time a friendly unit destroys a unit"))

    def test_actions(self):
        s = next(s for s in self.deck["secondary_missions"] if s["name"] == "PLUNDER")
        a = s["actions"][0]
        self.assertEqual((a["name"], a["type"], a["starts"], a["completes"]),
                         ("PLUNDER", "OBJECTIVE ACTION", "Your Shooting phase.", "Immediately."))
        self.assertTrue(s["intro"][0].startswith("WHEN DRAWN:"))

    def test_fixed_secondary_scores_both_ways(self):
        s = next(s for s in self.deck["secondary_missions"] if s["name"] == "A GRIEVOUS BLOW")
        self.assertTrue(s["fixed"])
        self.assertEqual(s["scoring"][0]["conditions"][0]["vp"],
                         [{"vp": "4VP", "notes": ["FIXED"]}, {"vp": "5VP", "notes": ["TACTICAL", "(UP TO 5VP)"]}])
        self.assertFalse(next(x for x in self.deck["secondary_missions"] if x["name"] == "PLUNDER")["fixed"])

    def test_deployments(self):
        d = self.deck["deployments"][0]
        self.assertEqual(d, {"name": "TIPPING POINT", "image": "maps/CA7_TippingPoint.png",
                             "image_url": "https://wahapedia.ru/wh40k11ed/img/maps/cards/CA7_TippingPoint.png"})


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch("crunch.data.missions.time.sleep")      # the polite pause between downloads
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_update(self, site, old=None, force=False):
        return update_missions(self.tmp, URL, site, force, old, log=lambda m: None)

    def test_first_run_stores_everything(self):
        site = FakeSite()
        entry = self.run_update(site)
        m = self.tmp / "missions"
        self.assertEqual(entry["counts"]["primary_missions"], 3)
        self.assertEqual((m / "raw" / PAGE_FILE).read_bytes(), PAGE)
        for name in ("force_dispositions", "primary_missions", "secondary_missions", "deployments"):
            self.assertTrue((m / "json" / f"{name}.json").exists(), name)
        self.assertEqual((m / "maps" / "CA7_TippingPoint.png").read_bytes(), b"PNG:CA7_TippingPoint.png")

    def test_unchanged_page_is_not_rewritten(self):
        entry = self.run_update(FakeSite())
        site = FakeSite(PAGE.replace(b"<body>", b"<body><div class='ad'>new ad, new token</div>"))
        self.assertIsNone(self.run_update(site, old=entry))              # only the page chrome changed
        self.assertEqual(site.requests, [URL])                            # maps not downloaded again
        self.assertFalse((self.tmp / "missions" / "archive").exists())

    def test_changed_page_is_archived_and_rebuilt(self):
        entry = self.run_update(FakeSite())
        changed = PAGE.replace(b"BATTLEFIELD DOMINANCE", b"BATTLEFIELD SUPREMACY")
        site = FakeSite(changed)
        new = self.run_update(site, old=entry)
        self.assertNotEqual(new["content_sha256"], entry["content_sha256"])
        archived = list((self.tmp / "missions" / "archive").glob(f"*/{PAGE_FILE}"))
        self.assertEqual([p.read_bytes() for p in archived], [PAGE])
        prim = json.loads((self.tmp / "missions" / "json" / "primary_missions.json").read_text(encoding="utf-8"))
        self.assertIn("BATTLEFIELD SUPREMACY", [p["name"] for p in prim])
        self.assertEqual(sum(u.endswith(".png") for u in site.requests), 2)    # maps refreshed

    def test_missing_map_is_fetched_again(self):
        entry = self.run_update(FakeSite())
        (self.tmp / "missions" / "maps" / "CA7_DawnOfWar.png").unlink()
        site = FakeSite()
        self.assertIsNone(self.run_update(site, old=entry))
        self.assertEqual([u.rsplit("/", 1)[-1] for u in site.requests if u.endswith(".png")], ["CA7_DawnOfWar.png"])

    def test_a_page_without_cards_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.run_update(FakeSite(b"<html><body>maintenance</body></html>"))

    def test_rebuild_offline(self):
        self.run_update(FakeSite())
        shutil.rmtree(self.tmp / "missions" / "json")
        self.assertEqual(rebuild_missions(self.tmp, URL)["deployments"], 2)
        self.assertTrue((self.tmp / "missions" / "json" / "deployments.json").exists())


class FetchCommandTest(unittest.TestCase):
    """`python -m crunch fetch --from-dir` with CSVs and the saved page, no network."""

    def test_csvs_and_missions_share_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            with mock.patch.object(fetch_mod, "fetch", FakeSite()), mock.patch.object(fetch_mod, "log"), \
                    mock.patch("crunch.data.missions.time.sleep"):
                fetch_mod.main(["--out", str(out), "--from-dir", str(FIX)])
                ed = out / "wh40k11ed"
                manifest = json.loads((ed / "manifest.json").read_text(encoding="utf-8"))
                self.assertIn("Datasheets", manifest["tables"])
                self.assertEqual(manifest["missions"]["counts"]["secondary_missions"], 2)
                self.assertTrue((ed / "missions" / "maps" / "CA7_DawnOfWar.png").exists())
                # a CSV-only rebuild keeps the missions entry
                fetch_mod.main(["--out", str(out), "--from-dir", str(FIX), "--no-missions"])
                manifest = json.loads((ed / "manifest.json").read_text(encoding="utf-8"))
                self.assertIn("missions", manifest)


if __name__ == "__main__":
    unittest.main()
