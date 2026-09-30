import unittest

try:
    import tkinter  # noqa: F401
    HAVE_TK = True
except ImportError:          # some Linux Pythons ship without tkinter
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "tkinter not available")
class RegistryTest(unittest.TestCase):
    def test_tools_are_discovered(self):
        from crunch.ui.registry import discover
        keys = [t.key for t in discover()]
        self.assertIn("matchup", keys)


if __name__ == "__main__":
    unittest.main()
