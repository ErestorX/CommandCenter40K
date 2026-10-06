import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from command_center import release


class VersionTest(unittest.TestCase):
    def test_version_key(self):
        self.assertEqual(release.version_key("v1.2.3"), (1, 2, 3))
        self.assertEqual(release.version_key("1.10"), (1, 10))
        self.assertIsNone(release.version_key("main"))             # a build from a branch has no version
        self.assertIsNone(release.version_key(""))

    def test_is_newer(self):
        self.assertTrue(release.is_newer("v1.10.0", "v1.9.3"))      # numbers, not text
        self.assertFalse(release.is_newer("v1.0.0", "v1.0.0"))
        self.assertFalse(release.is_newer("v1.0.0", "v1.1.0"))
        self.assertFalse(release.is_newer("v2.0.0", "main"))        # nothing offered to a build without a version

    def test_no_version_from_the_source(self):
        self.assertEqual(release.current_version(), "")


class CheckedTest(unittest.TestCase):
    def test_due_once_a_day(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "user_data" / "app_update.json"
            now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
            self.assertTrue(release.is_due(now=now, path=path))     # never checked
            release.mark_checked(now, path)
            self.assertFalse(release.is_due(now=now + timedelta(hours=23), path=path))
            self.assertTrue(release.is_due(now=now + timedelta(hours=25), path=path))
            path.write_text("not json", encoding="utf-8")
            self.assertTrue(release.is_due(now=now, path=path))


class SwapScriptTest(unittest.TestCase):
    def test_replaces_the_app_only(self):
        new, app, tmp = Path("T") / "new" / "App", Path("C") / "My App", Path("T")
        script = release.swap_script(new, app, "App.exe", 4242, tmp)
        self.assertIn('"PID eq 4242"', script)                      # waits for the app to close
        self.assertIn(f'robocopy "{new / "_internal"}" "{app / "_internal"}" /MIR', script)
        self.assertIn(f'copy /y "{new / "App.exe"}" "{app / "App.exe"}"', script)
        self.assertIn(f'start "" "{app / "App.exe"}"', script)
        for kept in ("lists", "user_data", "wahapedia_data"):
            self.assertNotIn(kept, script)

    def test_macos_replaces_the_app_and_puts_it_back_on_failure(self):
        new = PurePosixPath("/tmp/cc40k-update-x/new/My App.app")
        app = PurePosixPath("/Applications/My App.app")
        script = release.swap_script_macos(new, app, 4242, PurePosixPath("/tmp/cc40k-update-x"))
        self.assertIn("while kill -0 4242", script)                 # waits for the app to close
        self.assertIn("if mv '/Applications/My App.app' '/Applications/My App.app.old'; then", script)
        self.assertIn("if mv '/tmp/cc40k-update-x/new/My App.app' '/Applications/My App.app'; then", script)
        self.assertIn("else mv '/Applications/My App.app.old' '/Applications/My App.app'; fi", script)
        self.assertIn("open '/Applications/My App.app'", script)
        self.assertNotIn("Application Support", script)             # where the user's folders are


class BundledListsTest(unittest.TestCase):
    def test_copied_once(self):
        from command_center.lists.library import install_folder
        with tempfile.TemporaryDirectory() as d:
            source, lists = Path(d) / "app" / "lists", Path(d) / "user" / "lists"
            self.assertFalse(install_folder(source, lists))             # an app without lists inside
            source.mkdir(parents=True)
            (source / "Example.txt").write_text("a list", encoding="utf-8")
            self.assertTrue(install_folder(source, lists))
            self.assertEqual((lists / "Example.txt").read_text(encoding="utf-8"), "a list")
            (lists / "Example.txt").unlink()                            # the user removes it: it stays removed
            self.assertFalse(install_folder(source, lists))
            self.assertEqual(list(lists.iterdir()), [])

    def test_the_demonstration_work_is_for_lists_the_app_comes_with(self):
        import json

        from command_center import config
        lists = {p.name for p in config.LISTS_DIR.glob("*.txt")}
        if not config.DEMO_USER_DATA_DIR.is_dir() or not lists:
            self.skipTest("no demonstration data here")
        plans = json.loads((config.DEMO_USER_DATA_DIR / "army_plans.json").read_text(encoding="utf-8"))
        tests = json.loads((config.DEMO_USER_DATA_DIR / "test_plans.json").read_text(encoding="utf-8"))
        named = {name for key in plans for name in key.split("|")} | {key.split("|")[0] for key in tests}
        self.assertTrue(named)
        self.assertLessEqual(named, lists)


if __name__ == "__main__":
    unittest.main()
