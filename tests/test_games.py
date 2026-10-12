"""Games saved per matchup: the file of a pair of lists, and a player's score sheet out and in."""
import json
import tempfile
import unittest
from pathlib import Path

from command_center.deploy.games import VERSION, GameStore, score_from_dict, score_to_dict
from command_center.deploy.scoring import PlayerScore, PrimaryOption, SecondaryRow


def options() -> list[PrimaryOption]:
    """Two options of a made-up mission: a tick in rounds 1 to 5, a count in rounds 2 to 5."""
    return [PrimaryOption("Hold one", 4, (0, 1, 2, 3, 4), 1, 0, 0, "any battle round", "end of your turn", False),
            PrimaryOption("For each objective", 3, (1, 2, 3, 4), 0, 1, 1, "second battle round onwards", "command phase", False)]


class GameStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = GameStore(Path(tempfile.mkdtemp()) / "games")

    def test_a_game_comes_back(self):
        self.assertEqual(self.store.load("lists/Orks.txt", "lists/Marines.txt"), {})
        game = {"shown": [True, False, True], "units": ["attacker:u1"], "boards": {"TH-TH-A": {"attacker:u1": {"x": 3.5}}}}
        self.store.save("lists/Orks.txt", "lists/Marines.txt", game)
        back = self.store.load("elsewhere/Orks.txt", "Marines.txt")              # the lists' names, wherever they are
        self.assertEqual({k: back[k] for k in game}, game)
        self.assertEqual((back["version"], back["attacker"], back["defender"]), (VERSION, "Orks.txt", "Marines.txt"))
        self.assertEqual(self.store.load("lists/Marines.txt", "lists/Orks.txt"), {})     # the other way round: another game
        self.assertEqual(self.store.path("a/Orks.txt", "Marines.txt").name, "Orks vs Marines.json")

    def test_a_name_no_file_can_have(self):
        path = self.store.path('What?: "this".txt', "a|b.txt")
        self.assertEqual(path.name, "What__ _this_ vs a_b.json")
        self.store.save('What?: "this".txt', "a|b.txt", {"units": []})
        self.assertEqual(self.store.load('What?: "this".txt', "a|b.txt")["units"], [])

    def test_a_file_that_is_no_game(self):
        path = self.store.path("Orks.txt", "Marines.txt")
        path.parent.mkdir(parents=True)
        for text in ("not json", "[1, 2]", ""):
            path.write_text(text, encoding="utf-8")
            self.assertEqual(self.store.load("Orks.txt", "Marines.txt"), {})


class ScoreSheetTest(unittest.TestCase):
    def sheet(self) -> PlayerScore:
        s = PlayerScore(name="Hugo", went_first=True, battle_ready=False)
        s.set_options(options())
        s.score(0, 0, 1)
        s.score(1, 2, 3)
        row = SecondaryRow("Assassination")
        row.set(1, "4")
        s.secondaries += [row, SecondaryRow("Behind Enemy Lines")]
        s.cp_gained[:], s.cp_spent[:] = [1, 1, 2, 0, 0], [0, 2, 1, 0, 0]
        return s

    def test_a_sheet_comes_back(self):
        saved = json.loads(json.dumps(score_to_dict(self.sheet(), "Take It")))       # as the file has it
        back = PlayerScore(name="Attacker")
        back.set_options(options())
        score_from_dict(back, saved, "Take It")
        self.assertEqual(back, self.sheet())
        self.assertEqual(back.total, self.sheet().total)

    def test_another_mission_keeps_what_does_not_depend_on_it(self):
        saved = score_to_dict(self.sheet(), "Take It")
        back = PlayerScore()
        back.set_options(options()[:1])                                      # another mission's options
        score_from_dict(back, saved, "Hold It")
        self.assertEqual(back.counts, [[0] * 6])                             # nothing scored on its primary
        self.assertEqual((back.name, back.went_first, back.battle_ready), ("Hugo", True, False))
        self.assertEqual([s.name for s in back.secondaries], ["Assassination", "Behind Enemy Lines"])
        self.assertEqual(back.cp_gained, [1, 1, 2, 0, 0])

    def test_what_is_not_a_sheet_changes_nothing(self):
        fresh = PlayerScore(name="Attacker")
        fresh.set_options(options())
        for bad in (None, [], "sheet", {"name": 3, "went_first": "yes", "cp_gained": [1, 2], "secondaries": "none",
                                        "mission": "Take It", "counts": [[1] * 6], "primary": ["1"]}):
            back = PlayerScore(name="Attacker")
            back.set_options(options())
            score_from_dict(back, bad, "Take It")
            self.assertEqual(back, fresh)
        back = PlayerScore()
        back.set_options(options())
        score_from_dict(back, {"mission": "Take It", "counts": [[9] * 6, [-2, 2, 0, 0, 0, 0]],
                               "secondaries": [{"name": "A", "rounds": ["9"] * 5}, {"rounds": []}, "x"]}, "Take It")
        self.assertEqual(back.counts[0], [1, 1, 1, 1, 1, 0])                 # a tick is one at most, in its own columns
        self.assertEqual(back.counts[1], [0, 2, 0, 0, 0, 0])
        self.assertEqual([(s.name, s.rounds) for s in back.secondaries], [("A", [""] * 5)])     # cells that are none: blank


if __name__ == "__main__":
    unittest.main()
