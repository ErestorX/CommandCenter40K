"""BSData's files read into the engine's objects, lists linked to them first and completed by Wahapedia,
the rules text taken from them, and their download. On tests/fixtures/bsdata (cut from the real files
by scripts/bsdata_fixture.py)."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from command_center import config
from command_center.data import fetch as fetch_mod
from command_center.data.armies import Armies, wahapedia_id
from command_center.data.bsdata import BSData, attached_names, key, to_html
from command_center.data.rules import RulesBook
from command_center.lists import parse_list, target_for, weapon_loads
from tests.helpers import FIXTURE_BSDATA, FIXTURE_LIST, FIXTURES, fixture_armies, fixture_bs, fixture_wd

SM = "Imperium - Space Marines - Test Company"


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.bs = fixture_bs()

    def test_catalogue_from_the_title(self):
        sm = next(e["id"] for e in self.bs.index if e["type"] == "catalogue")
        self.assertEqual(self.bs.catalogue_for("Imperium - Adeptus Astartes - Space Marines - My list"), sm)   # its name starts it
        self.assertEqual(self.bs.catalogue_for(SM), sm)                       # the last part of its name is in it
        self.assertIsNone(self.bs.catalogue_for("Xenos - Orks - Waaagh"))
        self.assertEqual(self.bs.reach(sm)[-1], self.bs.system_id)            # and the game system after it

    def test_units_by_their_exact_names(self):
        self.assertEqual(self.bs.find("Intercessor Squad", SM)["name"], "Intercessor Squad")
        self.assertEqual(self.bs.find("intercessor squad [Legends]", SM)["name"], "Intercessor Squad")
        self.assertIsNone(self.bs.find("Intercessor", SM))                    # a model's name isn't a unit's
        self.assertIsNotNone(self.bs.find("Captain", "Imperium - Ultramarines - x"))    # catalogue unknown: all of them

    def test_a_unit_as_the_engine_sees_it(self):
        squad = self.bs.unit(self.bs.find("Intercessor Squad", SM))
        self.assertEqual(squad.source, "bsdata")
        self.assertEqual([m.name for m in squad.models], ["Intercessor Sergeant", "Intercessor", "Intercessor w/ Grenade Launcher"])
        self.assertEqual(squad.profile("Intercessor w/ Grenade Launcher").name, "Intercessor w/ Grenade Launcher")
        m = squad.models[1]
        self.assertEqual((m.M, m.T, m.Sv, m.inv, m.W, m.base), ('6"', 5, 3, None, 2, ""))     # no base: left blank
        self.assertEqual([w.name for w in squad.gear["boltrifle"]], ["Bolt Rifle - Focused Fire", "Bolt Rifle - Saturation"])
        self.assertEqual(squad.gear["terminatorhonoursupgrade"], [])           # wargear, not a weapon
        flamer = squad.gear["handflamer"][0]
        self.assertEqual((flamer.type, flamer.range, flamer.skill, flamer.keywords.tags()),
                         ("Ranged", '9"', None, ["Torrent", "Close Quarters"]))
        self.assertIn("infantry", squad.keywords)
        self.assertIn("adeptus astartes", squad.keywords)                     # "Faction: Adeptus Astartes"
        self.assertIs(self.bs.unit(self.bs.find("Intercessor Squad", SM)), squad)     # built once

    def test_characters(self):
        captain = self.bs.unit(self.bs.find("Captain", SM))
        apothecary = self.bs.unit(self.bs.find("Apothecary", SM))
        self.assertTrue(captain.is_character and not captain.is_support)
        self.assertTrue(apothecary.is_support)
        self.assertIn("intercessorsquad", self.bs.attaches(captain.id))
        self.assertIn("intercessorsquad", self.bs.attaches(apothecary.id))
        self.assertIsNone(self.bs.attaches(self.bs.find("Intercessor Squad", SM)["id"]))
        self.assertEqual(self.bs.faction_keywords(captain.id), {"adeptusastartes"})
        for item in ("warlord", "artificerarmour", "relicshield", "finesthour"):       # enhancement, wargear, ability
            self.assertIn(item, captain.other_gear)

    def test_rules_text(self):
        captain = self.bs.find("Captain", SM)["id"]
        self.bs.unit(self.bs.find("Captain", SM))
        ab = self.bs.abilities(captain)
        self.assertIn("Leader", [n for n, _ in ab["Core"]])                    # a rule of the game system
        self.assertIn("Combat Doctrines", [n for n, _ in ab["Faction"]])
        self.assertIn("Finest Hour", [n for n, _ in ab["Datasheet"]])
        self.assertIn("Relic Shield", [n for n, _ in ab["Wargear"]])
        sm = self.bs.catalogue_for(SM)
        enh = self.bs.enhancements(sm)
        self.assertEqual((enh["artificerarmour"]["cost"], enh["artificerarmour"]["detachment"]), (15, "Gladius Task Force"))
        det = self.bs.detachment("Gladius Task Force", SM)
        self.assertEqual([r["name"] for r in det["rules"]], ["Codex Discipline"])
        self.assertEqual(len(det["enhancements"]), 4)
        self.assertIn("Take and Hold", det["tags"])
        self.assertIsNone(self.bs.detachment("Waaagh Tribe", SM))

    def test_text_helpers(self):
        self.assertEqual(attached_names("This model can be attached to the following units:\n- **^^Intercessor Squad^^**\n"
                                        "- **^^Hellblaster Squad^^**\n\nAnother paragraph"),
                         {"intercessorsquad", "hellblastersquad"})
        self.assertEqual(attached_names("This model can be attached to the following unit:\n■ Wyches"), {"wyches"})
        self.assertEqual(attached_names("can be attached to: GUARDIAN DEFENDERS, STORM GUARDIANS and WARLOCK CONCLAVE."),
                         {"guardiandefenders", "stormguardians", "warlockconclave"})
        self.assertEqual(to_html("**Bold** for ^^Infantry^^ units\n<b>"), "<b>Bold</b> for <b>Infantry</b> units<br>&lt;b&gt;")
        self.assertEqual(key("Assault Squad [Legends]"), key("assault squad"))

    def test_the_modes_of_a_weapon(self):
        from command_center.core.dice import Dice
        from command_center.core.keywords import WeaponKeywords
        from command_center.core.models import Weapon
        from command_center.data.bsdata import name_modes

        def weapons(*names):
            return [Weapon(n, "Ranged", '18"', Dice(0, 0, 1), 3, 10, 4, Dice(0, 0, 1), WeaponKeywords()) for n in names]
        melta = weapons("Melta Rifle", "Melta Rifle HUNTER:Monster/Vehicle")
        name_modes("Melta rifle", melta)
        self.assertEqual([w.name for w in melta], ["Melta rifle", "Melta rifle - HUNTER:Monster/Vehicle"])
        self.assertEqual({w.base_name for w in melta}, {"Melta rifle"})                 # one fires at a time
        for item, names, expected in (
                ("Multi-melta", ("Multi-melta", "Multi-melta (HUNTER:Monster/Vehicle)"), ["Multi-melta", "Multi-melta - HUNTER:Monster/Vehicle"]),
                ("Plasma pistol", ("Plasma pistol - standard", "Plasma pistol- supercharge"), ["Plasma pistol - standard", "Plasma pistol - supercharge"]),
                ("Infernus heavy bolter", ("Infernus heavy bolter (Bolt)", "Infernus heavy bolter (Infernus)"),
                 ["Infernus heavy bolter - Bolt", "Infernus heavy bolter - Infernus"]),
                ("Kroot bolt thrower and Kroot rifle", ("Kroot bolt thrower", "Kroot rifle (Ranged)"), ["Kroot bolt thrower", "Kroot rifle (Ranged)"]),
                ("Melee Weapons", ("Lady's Blade", "Razor fan"), ["Lady's Blade", "Razor fan"])):     # two weapons, not modes
            ws = weapons(*names)
            name_modes(item, ws)
            self.assertEqual([w.name for w in ws], expected)

    def test_missing_or_broken_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                BSData(tmp)
            folder = Path(tmp) / "b"
            folder.mkdir()
            for f in FIXTURE_BSDATA.glob("*.json"):
                if f.name != "index.json":
                    (folder / f.name).write_bytes(f.read_bytes())
            (folder / "Broken.json").write_text("{not json", encoding="utf-8")
            bs = BSData(folder)                                                 # no index: written; a broken file: skipped
            self.assertTrue((folder / "index.json").exists())
            self.assertEqual(len(bs.index), 2)
            self.assertIsNotNone(bs.find("Captain", SM))


class LinkingTest(unittest.TestCase):
    """Lists linked to BSData first, completed by Wahapedia."""

    def setUp(self):
        self.armies = fixture_armies()
        self.army = parse_list(FIXTURE_LIST, self.armies)
        self.captain, self.apothecary, self.squad, self.squad2 = self.army.units

    def test_units_come_from_bsdata_with_wahapedia_behind(self):
        for u in self.army.units:
            self.assertEqual(u.datasheet.source, "bsdata")
            self.assertEqual(u.datasheet.fallback.source, "wahapedia")
            self.assertEqual(u.datasheet.faction_id, "SM")
        self.assertEqual(wahapedia_id(self.squad.datasheet), "001")

    def test_blanks_filled_from_wahapedia(self):
        bases = {m.name: m.base for m in self.squad.datasheet.models}
        self.assertEqual(bases, {"Intercessor Sergeant": "32mm", "Intercessor": "32mm", "Intercessor w/ Grenade Launcher": "32mm"})
        loads = {ld.weapon.name: ld.count for ld in weapon_loads(self.captain)}
        self.assertEqual(loads, {"Master-crafted bolter": 1,                     # BSData's
                                 "Power weapon – strike": 1, "Power weapon – sweep": 1})     # not on BSData's Captain: Wahapedia's
        self.assertEqual(self.captain.unmatched_gear, ["Warlord"])
        self.assertEqual(self.captain.unknown_gear, [])

    def test_weapons_and_models_by_their_names(self):
        loads = {ld.weapon.name: ld.count for ld in weapon_loads(self.squad)}
        self.assertEqual(loads, {"Bolt Rifle - Focused Fire": 5, "Bolt Rifle - Saturation": 5, "Close combat weapon": 5})
        t = target_for(self.squad)
        self.assertEqual([(g.label, g.count) for g in t.groups], [("Intercessor", 4), ("Intercessor Sergeant", 1)])
        self.assertEqual(t.groups[0].profile.name, "Intercessor")

    def test_who_joins_whom(self):
        self.assertIs(self.army.default_attached(self.squad, self.armies), self.captain)
        self.assertIs(self.army.default_attached(self.squad, self.armies, support=True), self.apothecary)
        self.assertEqual(self.army.attach_options(self.squad2, self.armies), [self.captain])
        self.assertTrue(self.armies.can_lead(self.captain.datasheet.id, self.squad.datasheet.id))
        self.assertFalse(self.armies.can_lead(self.captain.datasheet.id, self.apothecary.datasheet.id))

    def test_led_by_references_without_a_known_catalogue(self):
        army = parse_list(FIXTURES / "lists" / "LedBy.txt", self.armies)       # "Ultramarines": not in the fixture
        cap1, cap2, apo, sq1, sq2 = army.units
        self.assertEqual(cap1.datasheet.source, "bsdata")
        self.assertIs(army.default_attached(sq2, self.armies), cap1)
        self.assertIs(army.default_attached(sq1, self.armies, support=True), apo)
        self.assertEqual(sq2.unknown_gear, ["Auspex"])                         # neither BSData's nor Wahapedia's

    def test_an_enhancement_that_is_a_weapon(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "bs"
            folder.mkdir()
            for f in FIXTURE_BSDATA.glob("*.json"):
                (folder / f.name).write_bytes(f.read_bytes())
            sm = folder / "Imperium - Space Marines.json"
            doc = json.loads(sm.read_text(encoding="utf-8"))
            enhancements = next(g for g in doc["catalogue"]["sharedSelectionEntryGroups"] if g["name"] == "Enhancements")
            sword = {"name": "Melee Weapons", "typeName": "Melee Weapons", "characteristics": [
                {"name": n, "$text": v} for n, v in (("Range", "Melee"), ("A", "6"), ("WS", "2+"), ("S", "7"),
                                                     ("AP", "-3"), ("D", "3"), ("Keywords", ""))]}
            enhancements["selectionEntryGroups"][0]["selectionEntries"].append(
                {"name": "Imperium's Sword", "id": "test-sword", "type": "upgrade",
                 "profiles": [{**sword, "name": "Imperium's Sword", "id": "test-sword-p"}]})
            sm.write_text(json.dumps(doc), encoding="utf-8")
            armies = Armies(fixture_wd(), BSData(folder))
            text = FIXTURE_LIST.read_text(encoding="utf-8").replace("Power weapon, Warlord", "Power weapon, Warlord, Imperium's Sword")
            path = Path(tmp) / "list.txt"
            path.write_text(text, encoding="utf-8")
            army = parse_list(path, armies)
        captain, squad = army.units[0], army.units[2]
        sword = next(ld for ld in weapon_loads(captain) if ld.weapon.name == "Imperium's Sword")
        self.assertEqual((sword.count, sword.weapon.type, sword.weapon.S, sword.weapon.AP), (1, "Melee", 7, 3))
        self.assertIn("Master-crafted bolter", {ld.weapon.name for ld in weapon_loads(captain)})    # and the rest of its gear
        self.assertEqual((captain.unmatched_gear, captain.unknown_gear), (["Warlord"], []))
        self.assertNotIn("Imperium's Sword", {ld.weapon.name for ld in weapon_loads(squad)})       # only for its bearer

    def test_not_in_bsdata_is_wahapedia(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = FIXTURE_LIST.read_text(encoding="utf-8").replace("Apothecary", "Ork Boyz")
            path = Path(tmp) / "list.txt"
            path.write_text(text, encoding="utf-8")
            army = parse_list(path, self.armies)
        boyz = next(u for u in army.units if u.name == "Ork Boyz")
        self.assertEqual((boyz.datasheet.source, boyz.datasheet.id), ("wahapedia", "002"))

    def test_without_bsdata_as_before(self):
        alone = Armies(fixture_wd())
        army = parse_list(FIXTURE_LIST, alone)
        self.assertEqual({u.datasheet.source for u in army.units}, {"wahapedia"})
        self.assertIs(army.default_attached(army.units[2], alone), army.units[0])
        self.assertEqual({ld.weapon.name for ld in weapon_loads(army.units[2])}, {"Bolt rifle", "Close combat weapon"})


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.armies = fixture_armies()
        self.book = RulesBook(fixture_wd(), self.armies.bs)
        self.army = parse_list(FIXTURE_LIST, self.armies)

    def test_abilities_and_enhancements_from_bsdata(self):
        captain = self.army.units[0]
        ab = self.book.abilities_of(captain.datasheet)
        self.assertIn("Finest Hour", [n for n, _ in ab["Datasheet"]])
        self.assertEqual(self.book.datasheet_row(captain.datasheet)["name"], "Captain")      # Wahapedia's row, by the fallback
        captain.unit_gear.append(("Artificer Armour", 1))
        enh = self.book.enhancements_of(captain)
        self.assertEqual([(e["name"], e["cost"]) for e in enh], [("Artificer Armour", 15)])

    def test_detachment_from_bsdata_stratagems_from_wahapedia(self):
        dets = self.book.detachments("SM", self.army.detachment_names, self.army)
        self.assertEqual([d["name"] for d in dets], ["Gladius Task Force"])
        content = self.book.detachment_content(dets[0])
        self.assertEqual([r["name"] for r in content["rules"]], ["Codex Discipline"])
        self.assertEqual(len(content["enhancements"]), 4)
        self.assertEqual(content["stratagems"], [])                            # the fixture's Wahapedia has none
        self.assertEqual(self.book.detachments("SM", ["Nowhere"], self.army), [])

    def test_wahapedia_units_keep_wahapedia_rules(self):
        alone = parse_list(FIXTURE_LIST, Armies(fixture_wd()))
        self.assertEqual(self.book.abilities_of(alone.units[0].datasheet), {})     # the fixture has no abilities table


class DownloadTest(unittest.TestCase):
    """update_bsdata against a fake GitHub: the last commit, then that commit's zip."""

    @staticmethod
    def zip_of(files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        return buf.getvalue()

    def github(self, sha: str, files: dict[str, bytes]):
        calls = []

        def get(url):
            calls.append(url)
            if "api.github.com" in url:
                return json.dumps({"sha": sha, "commit": {"committer": {"date": "2026-10-13T22:53:39Z"}}}).encode()
            return self.zip_of(files) if sha in url else None
        return get, calls

    def files(self) -> dict[str, bytes]:
        out = {f"wh40k-11e-x/{f.name}": f.read_bytes() for f in FIXTURE_BSDATA.glob("*.json")
               if f.name not in ("index.json", "manifest.json")}
        out["wh40k-11e-x/README.md"] = b"readme"
        out["wh40k-11e-x/sub/Hidden.json"] = b"{}"                              # not at the top: left out
        return out

    def test_download_then_up_to_date_then_new(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetch_mod, "log"):
            folder = Path(tmp) / "bsdata" / "wh40k-11e"
            get, calls = self.github("abc123", self.files())
            self.assertTrue(fetch_mod.update_bsdata(folder, get=get))
            self.assertEqual(sorted(p.name for p in folder.iterdir()),
                             ["Imperium - Space Marines.json", "Warhammer 40,000.json", "index.json", "manifest.json"])
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((manifest["sha"], manifest["date"][:10]), ("abc123", "2026-10-13"))
            self.assertEqual(BSData(folder).revision, "2026-10-13")
            self.assertFalse(fetch_mod.update_bsdata(folder, get=get))          # same commit: nothing downloaded
            self.assertEqual(sum("codeload" in c for c in calls), 1)
            get, _ = self.github("def456", self.files())
            self.assertTrue(fetch_mod.update_bsdata(folder, get=get))           # a new commit
            self.assertFalse(folder.with_name(folder.name + ".old").exists())

    def test_files_held_open_are_replaced_one_by_one(self):
        """Windows can't rename a folder while a file in it is open (an antivirus scanning it)."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetch_mod, "log"):
            folder = Path(tmp) / "wh40k-11e"
            get, _ = self.github("abc123", self.files())
            fetch_mod.update_bsdata(folder, get=get)
            (folder / "Gone.json").write_text("{}", encoding="utf-8")         # no longer in the repository
            real_rename = Path.rename

            def held(self, target):
                if self.name == folder.name:
                    raise PermissionError("in use")
                return real_rename(self, target)
            get, _ = self.github("def456", self.files())
            with mock.patch.object(Path, "rename", held), mock.patch.object(fetch_mod, "SWAP_WAIT", 0):
                self.assertTrue(fetch_mod.update_bsdata(folder, get=get))
            self.assertEqual(json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["sha"], "def456")
            self.assertFalse((folder / "Gone.json").exists())
            self.assertFalse(folder.with_name(folder.name + ".new").exists())
            self.assertIsNotNone(BSData(folder).find("Captain", SM))

    def test_a_bad_archive_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetch_mod, "log"):
            folder = Path(tmp) / "wh40k-11e"
            get, _ = self.github("abc123", self.files())
            fetch_mod.update_bsdata(folder, get=get)
            get, _ = self.github("bad", {"wh40k-11e-x/Other.json": b"{}"})
            with self.assertRaises(RuntimeError):
                fetch_mod.update_bsdata(folder, get=get)
            self.assertEqual(json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["sha"], "abc123")
            with self.assertRaises(RuntimeError):
                fetch_mod.update_bsdata(folder, get=lambda url: None)          # GitHub out of reach

    def test_the_update_goes_on_without_bsdata(self):
        def site(url):
            if "github" in url:
                raise RuntimeError("no network")
            path = FIXTURES / "wahapedia" / url.rsplit("/", 1)[-1]
            return path.read_bytes() if url.endswith(".csv") and path.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            ed = Path(tmp) / "wh40k11ed"
            messages = []
            fetch_mod.set_log(messages.append)
            try:
                with mock.patch.object(fetch_mod, "fetch", site), mock.patch.object(fetch_mod.time, "sleep"):
                    self.assertTrue(fetch_mod.update(ed, with_missions=False))
            finally:
                fetch_mod.set_log(None)
            self.assertTrue((ed / "raw" / "Datasheets.csv").exists())
            self.assertTrue(any("BSData skipped" in m for m in messages))
            self.assertFalse(config.bsdata_dir(Path(tmp)).exists())


if __name__ == "__main__":
    unittest.main()
