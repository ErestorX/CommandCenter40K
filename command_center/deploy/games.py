"""A game under way, saved per matchup: what the Field Holomap and its Score Oracle hold for a pair of
army lists, so that it is there again when the pair is opened again.

One file per matchup, in user_data/games/: "<attacker's list> vs <defender's list>.json" (the lists the
other way round are another matchup). It holds the score sheet, the layouts viewed, the units put on
the maps and, per layout, where each unit stands and how (see command_center.ui.tools.holomap). What is
only a way of looking at the board (line of sight, planned targets...) is not kept.

No UI here: the windows hand over plain dictionaries. Reading is forgiving: a file that is missing, or
that is not what was written, is no game; a score saved for another mission keeps what does not depend
on the mission."""
from __future__ import annotations

import json
from pathlib import Path

from command_center import config
from command_center.deploy.scoring import COLUMNS, ROUNDS, SECONDARY_CELLS, PlayerScore, SecondaryRow

VERSION = 1
FORBIDDEN = '\\/:*?"<>|'          # not allowed in a file name


class GameStore:
    """The games saved, a file each."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else config.USER_DATA_DIR / "games"

    def path(self, attacker_list: str | Path, defender_list: str | Path) -> Path:
        name = f"{Path(attacker_list).stem} vs {Path(defender_list).stem}"
        return self.folder / ("".join("_" if c in FORBIDDEN else c for c in name) + ".json")

    def load(self, attacker_list: str | Path, defender_list: str | Path) -> dict:
        """The game saved for a matchup; {} when there is none (or none that can be read)."""
        try:
            game = json.loads(self.path(attacker_list, defender_list).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return game if isinstance(game, dict) else {}

    def save(self, attacker_list: str | Path, defender_list: str | Path, game: dict) -> None:
        path = self.path(attacker_list, defender_list)
        path.parent.mkdir(parents=True, exist_ok=True)
        game = {"version": VERSION, "attacker": Path(attacker_list).name, "defender": Path(defender_list).name, **game}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(game, indent=1), encoding="utf-8")
        tmp.replace(path)


def score_to_dict(score: PlayerScore, mission: str) -> dict:
    """A player's sheet as it can be saved; `mission`: the primary mission its options are those of."""
    return {"name": score.name, "went_first": score.went_first, "battle_ready": score.battle_ready,
            "mission": mission, "counts": [list(row) for row in score.counts], "primary": list(score.primary),
            "secondaries": [{"name": s.name, "rounds": list(s.rounds)} for s in score.secondaries],
            "cp_gained": list(score.cp_gained), "cp_spent": list(score.cp_spent)}


def _numbers(value, length: int) -> list[int] | None:
    ok = isinstance(value, list) and len(value) == length and all(isinstance(n, int) and not isinstance(n, bool) for n in value)
    return [max(0, n) for n in value] if ok else None


def score_from_dict(score: PlayerScore, data, mission: str) -> None:
    """Put a saved sheet on a player's score, whose options are already those of `mission`. What was
    scored on the primary mission is only taken if it was saved for that mission; whatever in the saved
    sheet is not what was written is left as the score has it."""
    if not isinstance(data, dict):
        return
    if isinstance(data.get("name"), str):
        score.name = data["name"]
    for flag in ("went_first", "battle_ready"):
        if isinstance(data.get(flag), bool):
            setattr(score, flag, data[flag])
    for cp in ("cp_gained", "cp_spent"):
        numbers = _numbers(data.get(cp), ROUNDS)
        if numbers is not None:
            setattr(score, cp, numbers)
    rows = data.get("secondaries")
    if isinstance(rows, list):
        score.secondaries = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("name"), str):
                rounds = row.get("rounds")
                ok = isinstance(rounds, list) and len(rounds) == ROUNDS and all(c in SECONDARY_CELLS for c in rounds)
                score.secondaries.append(SecondaryRow(row["name"], list(rounds) if ok else [""] * ROUNDS))
    if data.get("mission") != mission:
        return
    primary = data.get("primary")
    if isinstance(primary, list) and len(primary) == COLUMNS and all(isinstance(c, str) for c in primary):
        score.primary = list(primary)
    counts = data.get("counts")
    if isinstance(counts, list) and len(counts) == len(score.options) and all(_numbers(row, COLUMNS) is not None for row in counts):
        score.set_options(score.options)                    # nothing scored, then what was saved
        for i, row in enumerate(counts):
            for col, n in enumerate(row):
                if n > 0:
                    score.score(i, col, n)
