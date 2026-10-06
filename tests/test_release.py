import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
