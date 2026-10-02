"""Saved Estimates: what each player expects to score on the primary mission in a pairing of Force
Dispositions, saved to user_data/estimates.json at every change.

An Estimate belongs to a pairing (Player 1's disposition, Player 2's) and to who goes first: each
pairing has two, one per player going first. It holds, for each player, the primary mission and how
many times each of its scoring options is scored in each column of the sheet (PlayerScore.counts).
A mirror pairing (the same disposition on both sides) has one only: who goes first makes no
difference there, so its "Player 2 first" Estimate is its "Player 1 first" one with the two players
swapped (the player going first always has the same scoring).

The Score Oracle imports the one matching its game: game_estimate() tells which, and which of its
two players is the game's attacker.

An Estimate's margin (a player's primary VP less the opponent's) says how hard the matchup is for
that player; difficulty_groups() sorts margins into five groups, relative to each other, and
difficulty() gives the group of every saved Estimate, from each of its two players' point of view."""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from pathlib import Path
from string import capwords

from crunch import config
from crunch.deploy.scoring import COLUMNS, PlayerScore, primary_options

DIFFICULTY_GROUPS = 5
PLAYERS = ("Player 1", "Player 2")


def difficulty_groups(margins: dict) -> dict:
    """The difficulty group of each margin, from 0 (the hardest: the lowest margins) to 4 (the easiest),
    relative to the others: fifths of the margins, by rank; equal margins share a group (one margin
    alone, or all equal: the middle group)."""
    ranked = sorted(margins.values())
    out = {}
    for key, m in margins.items():
        below = bisect_left(ranked, m)
        rank = below + (bisect_right(ranked, m) - below) / 2            # the middle of its ties
        out[key] = min(DIFFICULTY_GROUPS - 1, int(rank / len(ranked) * DIFFICULTY_GROUPS))
    return out


def estimate_key(first: str, second: str, goes_first: int) -> str:
    """first, second: Player 1's and Player 2's dispositions; goes_first: 0 (Player 1) or 1 (Player 2)."""
    return f"{first}|{second}|P{goes_first + 1} first"


def game_estimate(order: list[str], attacker: str, defender: str, attacker_first: bool) -> tuple[str, str, int, bool]:
    """The Estimate of a game: (Player 1's disposition, Player 2's, who goes first, the attacker is
    Player 1). Player 1 has the disposition that comes first in `order` (the Cogitator's matrix: its
    upper triangle); in a mirror pairing, the attacker is Player 1."""
    def rank(name: str) -> int:
        return order.index(name) if name in order else len(order)
    attacker_is_p1 = rank(attacker) <= rank(defender)
    first, second = (attacker, defender) if attacker_is_p1 else (defender, attacker)
    return first, second, 0 if attacker_first == attacker_is_p1 else 1, attacker_is_p1


def saved_scores(book, store: "EstimateStore", first: str, second: str,
                 goes_first: int) -> tuple[list[str], list[PlayerScore], bool]:
    """An Estimate as saved: the two players' primary missions (from `book`, a MissionBook), their scores
    (Player 1's, Player 2's), and whether there was one saved (if not: nothing scored)."""
    missions = [book.primary_mission(fd, other) for fd, other in ((first, second), (second, first))]
    names = [capwords(m["name"]) if m else "Primary mission" for m in missions]
    scores = [PlayerScore(name=p, went_first=i == goes_first) for i, p in enumerate(PLAYERS)]
    for score, mission in zip(scores, missions):
        score.set_options(primary_options(mission))
    return names, scores, store.load(first, second, goes_first, names, scores)


def difficulty(book, store: "EstimateStore") -> dict[tuple[str, str, bool], int]:
    """How hard each matchup with a saved Estimate is: (a disposition, its opponent's, it goes first) ->
    its difficulty group (see difficulty_groups), from that disposition's point of view. Every Estimate
    counts twice, once for each of its players, with opposite margins."""
    names = book.dispositions
    margins: dict[tuple[str, str, bool], int] = {}
    for r, first in enumerate(names):
        for second in names[r:]:                                # each pairing: Player 1, Player 2
            for goes_first in (0, 1):
                _, scores, saved = saved_scores(book, store, first, second, goes_first)
                if not saved:
                    continue
                margin = scores[0].primary_total - scores[1].primary_total
                margins[first, second, goes_first == 0] = margin
                if first != second:                             # Player 2's point of view
                    margins[second, first, goes_first == 1] = -margin
    return difficulty_groups(margins)


class EstimateStore:
    """Estimates keyed by pairing and by who goes first, saved as JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.USER_DATA_DIR / "estimates.json"
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        self._data: dict[str, list[dict]] = raw if isinstance(raw, dict) else {}

    @staticmethod
    def _slot(first: str, second: str, goes_first: int) -> tuple[str, bool]:
        """Where an Estimate is kept: its key, and whether its two players are kept swapped (a mirror
        pairing's "Player 2 first" Estimate is the "Player 1 first" one, swapped)."""
        swapped = first == second and goes_first == 1
        return estimate_key(first, second, 0 if swapped else goes_first), swapped

    def has(self, first: str, second: str, goes_first: int) -> bool:
        return self._slot(first, second, goes_first)[0] in self._data

    def put(self, first: str, second: str, goes_first: int, missions: list[str], scores: list[PlayerScore]) -> None:
        """Save the two players' primary scoring (Player 1's, then Player 2's) to disk."""
        key, swapped = self._slot(first, second, goes_first)
        if swapped:
            missions, scores = missions[::-1], scores[::-1]
        self._data[key] = [
            {"mission": mission, "counts": [list(row) for row in score.counts]}
            for mission, score in zip(missions, scores)]
        self.save()

    def load(self, first: str, second: str, goes_first: int, missions: list[str], scores: list[PlayerScore]) -> bool:
        """Put the saved Estimate on the two players' scores (already set up with their missions'
        options), in place of what they hold. False, and nothing changed, when there is none saved, or
        when it was saved for other mission cards."""
        key, swapped = self._slot(first, second, goes_first)
        if swapped:
            missions, scores = missions[::-1], scores[::-1]
        saved = self._data.get(key)
        if not isinstance(saved, list) or len(saved) != len(scores):
            return False
        for entry, mission, score in zip(saved, missions, scores):
            counts = entry.get("counts") if isinstance(entry, dict) else None
            if entry.get("mission") != mission or not isinstance(counts, list) or len(counts) != len(score.options) \
                    or any(not isinstance(row, list) or len(row) != COLUMNS for row in counts):
                return False
        for entry, score in zip(saved, scores):
            score.set_options(score.options)                    # nothing scored, then what was saved
            for i, row in enumerate(entry["counts"]):
                for col, n in enumerate(row):
                    if isinstance(n, int) and n > 0:
                        score.score(i, col, n)
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        tmp.replace(self.path)
