"""Mission deck scraping: parsing the page, storing it, and the update check in `command_center fetch`."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from command_center import config
from command_center.data import fetch as fetch_mod
from command_center.data.missions import PAGE_FILE, parse_deck, rebuild_missions, update_missions

FIX = Path(__file__).parent / "fixtures" / "wahapedia"
LAYOUT_FIX = Path(__file__).parent / "fixtures" / "rapidingress"
PAGE = (FIX / "mission_deck.html").read_bytes()
URL = "https://wahapedia.ru/wh40k11ed/the-rules/mission-deck-2026-27/"


class FakeSite:
    """Serves the fixture page and layout files; records requests."""

    def __init__(self, page=PAGE):
        self.page, self.requests = page, []

    def __call__(self, url):
        self.requests.append(url)
        if url == URL:
            return self.page
        name = url.rsplit("/", 1)[-1]
        if url.startswith(config.LAYOUTS_BASE_URL) and (LAYOUT_FIX / name).exists():
            return (LAYOUT_FIX / name).read_bytes()
        return None


class ParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deck = parse_deck(PAGE.decode("utf-8"))

    def test_counts_and_outdated_deployment_cards_ignored(self):
        # the page's deployment cards sit between the primary and secondary decks: none may leak in
        self.assertEqual({k: len(v) for k, v in self.deck.items()},
                         {"force_dispositions": 5, "primary_missions": 3, "secondary_missions": 2})
        names = [c["name"] for k in ("primary_missions", "secondary_missions") for c in self.deck[k]]
        self.assertNotIn("TIPPING POINT", names)

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


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_update(self, site, old=None, force=False):
        return update_missions(self.tmp, URL, site, force, old, log=lambda m: None)

    def test_first_run_stores_everything(self):
        entry = self.run_update(FakeSite())
        m = self.tmp / "missions"
        self.assertEqual(entry["counts"], {"force_dispositions": 5, "primary_missions": 3, "secondary_missions": 2})
        self.assertEqual((m / "raw" / PAGE_FILE).read_bytes(), PAGE)
        for name in ("force_dispositions", "primary_missions", "secondary_missions"):
            self.assertTrue((m / "json" / f"{name}.json").exists(), name)

    def test_unchanged_page_is_not_rewritten(self):
        entry = self.run_update(FakeSite())
        site = FakeSite(PAGE.replace(b"<body>", b"<body><div class='ad'>new ad, new token</div>"))
        self.assertIsNone(self.run_update(site, old=entry))              # only the page chrome changed
        self.assertEqual(site.requests, [URL])
        self.assertFalse((self.tmp / "missions" / "archive").exists())

    def test_changed_page_is_archived_and_rebuilt(self):
        entry = self.run_update(FakeSite())
        new = self.run_update(FakeSite(PAGE.replace(b"BATTLEFIELD DOMINANCE", b"BATTLEFIELD SUPREMACY")), old=entry)
        self.assertNotEqual(new["content_sha256"], entry["content_sha256"])
        archived = list((self.tmp / "missions" / "archive").glob(f"*/{PAGE_FILE}"))
        self.assertEqual([p.read_bytes() for p in archived], [PAGE])
        prim = json.loads((self.tmp / "missions" / "json" / "primary_missions.json").read_text(encoding="utf-8"))
        self.assertIn("BATTLEFIELD SUPREMACY", [p["name"] for p in prim])

    def test_outdated_deployment_files_are_removed_and_layouts_kept(self):
        m = self.tmp / "missions"
        (m / "maps").mkdir(parents=True)
        (m / "maps" / "CA7_DawnOfWar.png").write_bytes(b"old")
        (m / "json").mkdir()
        (m / "json" / "deployments.json").write_text("[]", encoding="utf-8")
        (m / "json" / "layouts.json").write_text("{}", encoding="utf-8")
        self.run_update(FakeSite())
        self.assertFalse((m / "maps").exists())
        self.assertFalse((m / "json" / "deployments.json").exists())
        self.assertTrue((m / "json" / "layouts.json").exists())

    def test_a_page_without_cards_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.run_update(FakeSite(b"<html><body>maintenance</body></html>"))

    def test_rebuild_offline(self):
        self.run_update(FakeSite())
        shutil.rmtree(self.tmp / "missions" / "json")
        self.assertEqual(rebuild_missions(self.tmp)["secondary_missions"], 2)
        self.assertTrue((self.tmp / "missions" / "json" / "secondary_missions.json").exists())


class FetchCommandTest(unittest.TestCase):
    """`python -m command_center fetch --from-dir` with CSVs and the saved page, the layouts from a fake site."""

    def test_csvs_missions_and_layouts_share_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            with mock.patch.object(fetch_mod, "fetch", FakeSite()), mock.patch.object(fetch_mod, "log"), \
                    mock.patch("command_center.data.layouts.time.sleep"):
                fetch_mod.main(["--out", str(out), "--from-dir", str(FIX)])
                ed = out / "wh40k11ed"
                manifest = json.loads((ed / "manifest.json").read_text(encoding="utf-8"))
                self.assertIn("Datasheets", manifest["tables"])
                self.assertEqual(manifest["missions"]["counts"]["secondary_missions"], 2)
                self.assertEqual(manifest["layouts"]["count"], 2)
                self.assertTrue((ed / "missions" / "json" / "layouts.json").exists())
                # a CSV-only rebuild keeps both entries
                fetch_mod.main(["--out", str(out), "--from-dir", str(FIX), "--no-missions"])
                manifest = json.loads((ed / "manifest.json").read_text(encoding="utf-8"))
                self.assertIn("missions", manifest)
                self.assertIn("layouts", manifest)


if __name__ == "__main__":
    unittest.main()
