"""Score sheet: VP per round, caps, Battle Ready, and the WTC result."""
import unittest

from crunch.deploy.scoring import PlayerScore, SecondaryRow, vp, wtc


class ScoringTest(unittest.TestCase):
    def test_cells(self):
        self.assertEqual([vp(c) for c in ("4", " 13 ", "-", "", "x", "-3")], [4, 13, 0, 0, 0, 0])

    def test_the_example_game(self):
        # the example sheet: 45 + 39 + 10 = 94 against 28 + 27 + 10 = 65, so 15 - 5
        a = PlayerScore("Erestor", True, ["4", "9", "13", "13", "9"],
                        [SecondaryRow("Display of Might", ["5", "", "", "", ""]),
                         SecondaryRow("A Tempting Target", ["5", "", "", "", ""]),
                         SecondaryRow("Burden of Trust", ["", "4", "", "", ""]),
                         SecondaryRow("Secure No Man's Land", ["", "5", "", "", ""]),
                         SecondaryRow("Bring It Down", ["", "", "5", "", ""]),
                         SecondaryRow("Beacon", ["", "", "5", "", ""]),
                         SecondaryRow("No Prisoners", ["", "", "", "2", ""]),
                         SecondaryRow("Centre Ground", ["", "", "", "3", ""]),
                         SecondaryRow("Overwhelming Force", ["", "", "", "", "-"]),
                         SecondaryRow("Outflank", ["", "", "", "", "5"])], True)
        b = PlayerScore("Balazs", False, ["4", "6", "-", "4", "14"],
                        [SecondaryRow("x", ["5", "2", "5", "", ""]), SecondaryRow("y", ["", "", "", "5", "10"])], True)
        self.assertEqual((a.primary_total, a.secondary_total, a.total), (45, 39, 94))
        self.assertEqual((b.primary_total, b.secondary_total, b.total), (28, 27, 65))
        self.assertEqual(wtc(a.total, b.total), (15, 5))
        self.assertEqual(wtc(b.total, a.total), (5, 15))

    def test_caps_and_battle_ready(self):
        s = PlayerScore(primary=["15", "15", "15", "15", "15"],
                        secondaries=[SecondaryRow("a", ["20", "20", "20", "", ""])])
        self.assertEqual((s.primary_total, s.secondary_total, s.total), (45, 45, 90))
        s.battle_ready = True
        self.assertEqual(s.total, 100)

    def test_wtc_bands(self):
        self.assertEqual([wtc(50 + d, 50)[0] for d in (0, 5, 6, 10, 11, 30, 50, 51, 60)],
                         [10, 10, 11, 11, 12, 15, 19, 20, 20])


if __name__ == "__main__":
    unittest.main()
