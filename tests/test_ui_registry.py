import unittest

try:
    import tkinter  # noqa: F401
    HAVE_TK = True
except ImportError:          # some Linux Pythons ship without tkinter
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "tkinter not available")
class RegistryTest(unittest.TestCase):
    def test_tools_are_discovered(self):
        from command_center.ui.registry import discover
        keys = [t.key for t in discover()]
        self.assertIn("auspex", keys)
        self.assertIn("optimizer", keys)

    def test_tools_without_armies(self):
        from command_center.ui.registry import discover
        tools = {t.key: t for t in discover()}
        self.assertFalse(tools["cogitator"].needs_armies)         # opens with no list chosen
        self.assertTrue(all(tools[k].needs_armies for k in ("auspex", "optimizer", "holomap")))


if __name__ == "__main__":
    unittest.main()
