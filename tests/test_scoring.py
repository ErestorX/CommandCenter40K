"""Score sheet: VP per round, primary scoring options, caps, Battle Ready, and the WTC result."""
import tempfile
import unittest
from pathlib import Path

from command_center.deploy.estimates import EstimateStore, difficulty, difficulty_groups, game_estimate, saved_scores
from command_center.deploy.scoring import END, PlayerScore, SecondaryRow, columns, primary_options, vp, wtc


def _cond(text, points, additional=False, alternative=False):
    return {"text": text, "vp": [{"vp": points, "notes": ["CUMULATIVE"] if additional else []}],
            "additional": additional, "alternative": alternative}


# a card in the shape command_center.data.missions parses them
MISSION = {"name": "TEST", "scoring": [
    {"round": "ANY BATTLE ROUND", "when": "End of your turn.", "conditions": [
        _cond("One or two objectives are consecrated.", "3VP"),
        _cond("Three or more objectives are consecrated.", "6VP", alternative=True)]},
    {"round": "SECOND BATTLE ROUND ONWARDS", "when": "End of your Command phase.", "conditions": [
        _cond("For each objective you control.", "3VP"),
        _cond("For each of those objectives that is within your opponent's territory.", "+3VP", additional=True)]},
    {"round": "ANY BATTLE ROUND", "when": "End of a turn.", "conditions": [
        _cond("One or more condemned enemy units left the battlefield this turn.", "5VP")]},
    {"round": "END OF THE BATTLE", "when": "", "conditions": [
        _cond("You control your opponent's home objective.", "8VP")]},
]}


class ScoringTest(unittest.TestCase):
    def test_cells(self):
        self.assertEqual([vp(c) for c in ("4", " 13 ", "-", "", "x", "-3")], [4, 13, 0, 0, 0, 0])

    def test_the_example_game(self):
        # the example sheet: 45 + 39 + 10 = 94 against 28 + 27 + 10 = 65, so 15 - 5
        a = PlayerScore("Erestor", True, ["4", "9", "13", "13", "9", ""],
                        [SecondaryRow("Display of Might", ["5", "", "", "", ""]),
                         SecondaryRow("A Tempting Target", ["5", "", "", "", ""]),
                         SecondaryRow("Burden of Trust", ["", "4", "", "", ""]),
                         SecondaryRow("Secure No Man's Land", ["", "5", "", "", ""]),
                         SecondaryRow("Bring It Down", ["", "", "5", "", ""]),
                         SecondaryRow("Beacon", ["", "", "5", "", ""]),
                         SecondaryRow("No Prisoners", ["", "", "", "2", ""]),
                         SecondaryRow("Centre Ground", ["", "", "", "3", ""]),
                         SecondaryRow("Overwhelming Force", ["", "", "", "", "-"]),
                         SecondaryRow("Outflank", ["", "", "", "", "5"])])
        b = PlayerScore("Balazs", False, ["4", "6", "-", "4", "14", ""],
                        [SecondaryRow("Assassination", ["5", "", "", "", ""]), SecondaryRow("Cleanse", ["2", "", "", "", ""]),
                         SecondaryRow("A Tempting Target", ["", "-", "5", "", ""]),
                         SecondaryRow("Bring It Down", ["", "", "-", "-", "5"]),
                         SecondaryRow("Overwhelming Force", ["", "", "", "-", "3"]),
                         SecondaryRow("Defend Stronghold", ["", "", "", "-", "5"]),
                         SecondaryRow("Burden of Trust", ["", "", "", "", "2"])])
        self.assertEqual((a.primary_total, a.secondary_total, a.total), (45, 39, 94))
        self.assertEqual((b.primary_total, b.secondary_total, b.total), (28, 27, 65))
        self.assertEqual(wtc(a.total, b.total), (15, 5))
        self.assertEqual(wtc(b.total, a.total), (5, 15))

    def test_caps_and_battle_ready(self):
        s = PlayerScore(primary=["15", "15", "15", "15", "15", ""],
                        secondaries=[SecondaryRow(str(i), ["5" if r == i // 3 else "" for r in range(5)])
                                     for i in range(9)])                  # three missions a round, 5 VP each
        self.assertEqual((s.primary_total, s.secondary_total, s.total), (45, 45, 100))   # Battle Ready: by default
        self.assertFalse(any(s.primary_over(c) or s.secondary_over(c) for c in range(5)))   # at a cap, nothing lost
        self.assertFalse(any(row.over for row in s.secondaries))
        s.battle_ready = False
        self.assertEqual(s.total, 90)

    def test_round_caps(self):
        # VP above a cap are kept on the sheet, flagged, and don't count
        s = PlayerScore(primary=["20", "9", "", "", "", "20"],
                        secondaries=[SecondaryRow("a", ["8", "", "", "", ""]), SecondaryRow("b", ["2", "2", "3", "", ""]),
                                     SecondaryRow("c", ["", "5", "", "", ""]), SecondaryRow("d", ["", "5", "", "", ""]),
                                     SecondaryRow("e", ["", "5", "", "", ""]), SecondaryRow("f", ["", "4", "", "", ""])])
        self.assertEqual([s.primary_vp(c) for c in (0, 1, END)], [15, 9, 20])      # the end of the battle: no round cap
        self.assertEqual([s.primary_over(c) for c in (0, 1, END)], [True, False, False])
        self.assertEqual(s.primary_total, 44)
        # a mission: 5 VP at most, over the rounds it is scored in
        self.assertEqual([row.over for row in s.secondaries], [True, True, False, False, False, False])
        self.assertEqual(s.secondaries[0].counted(), [5, 0, 0, 0, 0])
        self.assertEqual(s.secondaries[1].counted(), [2, 2, 1, 0, 0])
        # a round: 15 VP at most; a mission over its own cap doesn't flag the round
        self.assertEqual([s.secondary_vp(r) for r in range(3)], [7, 15, 1])        # round 2: 2 + 5 + 5 + 5 + 4
        self.assertEqual([s.secondary_over(r) for r in range(3)], [False, True, False])
        self.assertEqual(s.secondary_total, 23)

    def test_cp(self):
        s = PlayerScore()
        s.cp_gained[:3] = [1, 2, 1]
        s.cp_spent[:3] = [0, 2, 3]
        self.assertEqual([s.cp_remaining(r) for r in range(5)], [1, 1, -1, -1, -1])     # carried over the rounds
        self.assertEqual([s.cp_played(r) for r in range(5)], [True, True, True, False, False])

    def test_unused_secondaries(self):
        names = ["Beacon", "Cleanse", "Outflank"]
        s = PlayerScore(secondaries=[SecondaryRow("Beacon"), SecondaryRow(" cleanse "), SecondaryRow()])
        self.assertEqual(s.unused_secondaries(names), ["Outflank"])
        self.assertEqual(s.unused_secondaries(names, s.secondaries[0]), ["Beacon", "Outflank"])   # its own stays
        self.assertEqual(s.unused_secondaries(names, s.secondaries[2]), ["Outflank"])

    def test_secondary_cells(self):
        row = SecondaryRow("Beacon")
        row.set(0, "-")                                     # not active, nothing scored: still open
        row.set(1, "")
        self.assertEqual((row.rounds, row.closed), (["-", "", "", "", ""], None))
        row.set(2, "4")                                     # scored: not active afterwards
        self.assertEqual((row.rounds, row.closed), (["-", "", "4", "-", "-"], 2))
        row.set(0, "5")                                     # closed: its other cells are locked
        row.set(4, "x")
        self.assertEqual(row.rounds, ["-", "", "4", "-", "-"])
        row.set(2, "x")                                     # discarded instead: closed as well, no VP
        self.assertEqual((row.rounds, row.closed, sum(row.counted())), (["-", "", "x", "-", "-"], 2, 0))
        row.set(2, "")                                      # undone: the rounds after are open again
        self.assertEqual((row.rounds, row.closed), (["-", "", "", "", ""], None))
        row.set(4, "3")
        self.assertEqual((row.rounds, row.closed), (["-", "", "", "", "3"], 4))

    def test_block_columns(self):
        self.assertEqual(columns("ANY BATTLE ROUND"), (0, 1, 2, 3, 4))
        self.assertEqual(columns("FIRST AND SECOND BATTLE ROUND"), (0, 1))
        self.assertEqual(columns("SECOND TO FOURTH BATTLE ROUND"), (1, 2, 3))
        self.assertEqual(columns("FOURTH BATTLE ROUND ONWARDS"), (3, 4))
        self.assertEqual(columns("FIFTH BATTLE ROUND"), (4,))
        self.assertEqual(columns("END OF THE BATTLE"), (END,))

    def test_primary_options(self):
        opts = primary_options(MISSION)
        self.assertEqual([(o.vp, o.most, o.columns) for o in opts],
                         [(3, 1, (0, 1, 2, 3, 4)), (6, 1, (0, 1, 2, 3, 4)),            # ticks
                          (3, 0, (1, 2, 3, 4)), (3, 0, (1, 2, 3, 4)),                  # "for each": counted
                          (5, 2, (0, 1, 2, 3, 4)),                                     # "a turn": each player's
                          (8, 1, (END,))])
        self.assertEqual([o.group for o in opts], [0, 0, 2, 3, 4, 5])                  # the "or" line: same group
        self.assertTrue(opts[3].additional)
        self.assertEqual(primary_options(None), [])
        self.assertEqual(primary_options({"name": "x", "scoring": []}), [])

    def test_scoring_options(self):
        s = PlayerScore()
        s.set_options(primary_options(MISSION))
        s.score(0, 0, 1)
        self.assertEqual(s.primary_vp(0), 3)
        s.score(1, 0, 1)                                    # the alternative: instead of the first
        self.assertEqual((s.counts[0][0], s.primary_vp(0)), (0, 6))
        s.score(1, 0, 5)                                    # a tick: once
        self.assertEqual(s.primary_vp(0), 6)
        s.score(2, 0, 1)                                    # not scored in the first battle round
        self.assertEqual(s.primary_vp(0), 6)
        s.score(2, 1, 3)
        s.score(3, 1, 2)
        s.score(2, 2, -1)                                   # never below zero
        self.assertEqual((s.primary_raw(1), s.primary_vp(1), s.primary_over(1), s.primary_vp(2)), (15, 15, False, 0))
        s.score(4, 1, 3)                                    # twice a battle round at most
        self.assertEqual((s.primary_raw(1), s.primary_vp(1), s.primary_over(1)), (25, 15, True))
        s.score(5, END, 1)
        self.assertEqual(s.primary_total, 6 + 15 + 8)
        s.set_options([])                                   # another mission: nothing scored
        self.assertEqual(s.primary_total, 0)

    def test_wtc_bands(self):
        self.assertEqual([wtc(50 + d, 50)[0] for d in (0, 5, 6, 10, 11, 30, 50, 51, 60)],
                         [10, 10, 11, 11, 12, 15, 19, 20, 20])


class EstimateTest(unittest.TestCase):
    ORDER = ["Take and Hold", "Purge the Foe", "Disruption"]

    @staticmethod
    def players():
        scores = [PlayerScore("Player 1"), PlayerScore("Player 2")]
        for s in scores:
            s.set_options(primary_options(MISSION))
        return scores

    def test_saved_per_pairing_and_first_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "estimates.json"
            store = EstimateStore(path)
            p1_first, p2_first = self.players(), self.players()
            p1_first[0].score(0, 0, 1)
            p1_first[1].score(2, 1, 3)
            p2_first[1].score(5, END, 1)
            store.put("Take and Hold", "Disruption", 0, ["Test", "Test"], p1_first)
            store.put("Take and Hold", "Disruption", 1, ["Test", "Test"], p2_first)

            again = EstimateStore(path)                         # as saved: each version its own scoring
            a, b = self.players(), self.players()
            self.assertTrue(again.load("Take and Hold", "Disruption", 0, ["Test", "Test"], a))
            self.assertTrue(again.load("Take and Hold", "Disruption", 1, ["Test", "Test"], b))
            self.assertEqual([s.primary_total for s in a], [3, 9])
            self.assertEqual([s.primary_total for s in b], [0, 8])
            self.assertFalse(again.has("Disruption", "Take and Hold", 0))      # the pairing the other way round
            self.assertFalse(again.load("Take and Hold", "Purge the Foe", 0, ["Test", "Test"], a))
            self.assertEqual([s.primary_total for s in a], [3, 9])              # nothing loaded, nothing changed

    def test_mirror_pairing_has_one_estimate(self):
        # who goes first makes no difference: the player going first always has the same scoring
        with tempfile.TemporaryDirectory() as tmp:
            store = EstimateStore(Path(tmp) / "estimates.json")
            p1_first = self.players()
            p1_first[0].score(0, 0, 1)                          # the player going first: 3 VP
            p1_first[1].score(5, END, 1)                        # the player going second: 8 VP
            store.put("Disruption", "Disruption", 0, ["Test", "Test"], p1_first)
            self.assertTrue(store.has("Disruption", "Disruption", 1))
            p2_first = self.players()
            self.assertTrue(store.load("Disruption", "Disruption", 1, ["Test", "Test"], p2_first))
            self.assertEqual([s.primary_total for s in p2_first], [8, 3])       # Player 2 goes first: it has the 3
            p2_first[1].score(1, 1, 1)                          # edited there: the player going first, 9 VP
            store.put("Disruption", "Disruption", 1, ["Test", "Test"], p2_first)
            back = self.players()
            store.load("Disruption", "Disruption", 0, ["Test", "Test"], back)
            self.assertEqual([s.primary_total for s in back], [9, 8])
            self.assertEqual(len(store._data), 1)

    def test_load_replaces_and_checks_the_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EstimateStore(Path(tmp) / "estimates.json")
            saved = self.players()
            saved[0].score(1, 0, 1)
            store.put("a", "b", 0, ["Test", "Test"], saved)
            mine = self.players()
            mine[0].score(4, 0, 2)                              # scored before the import: replaced by it
            self.assertTrue(store.load("a", "b", 0, ["Test", "Test"], mine))
            self.assertEqual(mine[0].counts, saved[0].counts)
            self.assertFalse(store.load("a", "b", 0, ["Test", "Another mission"], mine))   # another card
            other = [PlayerScore(), PlayerScore()]              # no options: the saved counts don't fit
            self.assertFalse(store.load("a", "b", 0, ["Test", "Test"], other))

    def test_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "estimates.json"
            path.write_text("not json", encoding="utf-8")
            self.assertFalse(EstimateStore(path).has("a", "b", 0))

    def test_difficulty_groups(self):
        # fifths of the margins, by rank: 0 the hardest (lowest margins), 4 the easiest
        margins = {k: m for k, m in zip("abcdefghij", (-20, -12, -7, -3, 0, 0, 3, 7, 12, 20))}
        self.assertEqual(difficulty_groups(margins), dict(zip("abcdefghij", (0, 0, 1, 1, 2, 2, 3, 3, 4, 4))))
        self.assertEqual(difficulty_groups({"a": 7}), {"a": 2})                         # alone: the middle
        self.assertEqual(difficulty_groups({"a": 4, "b": 4, "c": 4}), {"a": 2, "b": 2, "c": 2})
        self.assertEqual(difficulty_groups({"a": 5, "b": -5}), {"a": 3, "b": 1})        # a pairing's two sides
        self.assertEqual(difficulty_groups({"a": 100, "b": 1, "c": 2, "d": 3, "e": 4}),  # by rank, not by size
                         {"b": 0, "c": 1, "d": 2, "e": 3, "a": 4})
        self.assertEqual(difficulty_groups({}), {})

    def test_difficulty_of_saved_estimates(self):
        class Book:                                             # two dispositions, the same card for every pairing
            dispositions = ["A", "B"]

            @staticmethod
            def primary_mission(own, opponent):
                return MISSION
        with tempfile.TemporaryDirectory() as tmp:
            store = EstimateStore(Path(tmp) / "estimates.json")
            self.assertEqual(difficulty(Book, store), {})
            names, scores, saved = saved_scores(Book, store, "A", "B", 0)
            self.assertEqual((names, saved, [s.primary_total for s in scores]), (["Test", "Test"], False, [0, 0]))
            scores[0].score(1, 0, 1)                            # A against B, A first: 6 - 0
            store.put("A", "B", 0, names, scores)
            # each player's point of view; nothing for the Estimate with B going first, nor the mirrors
            self.assertEqual(difficulty(Book, store), {("A", "B", True): 3, ("B", "A", False): 1})
            _, mirror, _ = saved_scores(Book, store, "A", "A", 0)
            mirror[1].score(5, END, 1)                          # A against A: 0 - 8 for the player going first
            store.put("A", "A", 0, names, mirror)
            self.assertEqual(difficulty(Book, store), {("A", "A", True): 0, ("B", "A", False): 1,
                                                       ("A", "B", True): 3, ("A", "A", False): 4})

    def test_the_estimate_of_a_game(self):
        # Player 1 has the disposition that comes first in the matrix
        self.assertEqual(game_estimate(self.ORDER, "Take and Hold", "Disruption", True),
                         ("Take and Hold", "Disruption", 0, True))
        self.assertEqual(game_estimate(self.ORDER, "Take and Hold", "Disruption", False),
                         ("Take and Hold", "Disruption", 1, True))
        self.assertEqual(game_estimate(self.ORDER, "Disruption", "Take and Hold", True),       # the attacker: Player 2
                         ("Take and Hold", "Disruption", 1, False))
        self.assertEqual(game_estimate(self.ORDER, "Disruption", "Take and Hold", False),
                         ("Take and Hold", "Disruption", 0, False))
        self.assertEqual(game_estimate(self.ORDER, "Disruption", "Disruption", False),         # mirror: the attacker is 1
                         ("Disruption", "Disruption", 1, True))


if __name__ == "__main__":
    unittest.main()
