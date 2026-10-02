"""Game score: primary and secondary VP per battle round, Battle Ready, CP, and the WTC result.

The sheet has a column per battle round, plus one for what is scored at the end of the battle.
The primary mission is scored option by option (PrimaryOption: one per scoring line of its card):
ticked when it can be scored once, counted when it is scored "for each ...". Without a card, a cell
holds VP as entered: a number, "-" (nothing scored) or "" (not played yet).
A secondary mission's cell is one of SECONDARY_CELLS: "" (nothing scored this round), "-" (the mission
wasn't active this round), the VP scored, or "x" (discarded). Scoring or discarding it closes it: it
isn't active in the rounds after.

Caps: 5 VP per secondary mission (whatever the rounds they are scored in), 15 VP per battle round for
the primary and for the secondaries, 45 VP each over the game; Battle Ready is worth 10, and is scored
unless unticked: 100 VP at most. VP above a cap can be entered, they just don't count (SecondaryRow.over
and the *_over methods tell where).
CP: gained and spent are counted per battle round; what remains carries over to the next round.
WTC: the VP difference converts to a 20-point split (0-5 VP apart: 10-10, every 5 VP more: one point
more, 51+: 20-0)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ROUNDS = 5
END = ROUNDS                    # the column after the battle rounds: end of the battle
COLUMNS = ROUNDS + 1
PRIMARY_MAX = 45
SECONDARY_MAX = 45
ROUND_MAX = 15                  # primary VP, and secondary VP, in one battle round
SECONDARY_MISSION_MAX = 5       # one secondary mission, over the game
BATTLE_READY = 10
SECONDARY_CELLS = ("", "-", "1", "2", "3", "4", "5", "x")

_ORDINALS = ("FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH")


def vp(cell: str) -> int:
    """The VP in a cell: its number, 0 for "-", "" or anything that isn't one."""
    try:
        return max(0, int(str(cell).strip()))
    except ValueError:
        return 0


def columns(header: str) -> tuple[int, ...]:
    """The columns a scoring block covers, from its header: "SECOND TO FOURTH BATTLE ROUND" -> (1, 2, 3),
    "ANY BATTLE ROUND" -> every round, "END OF THE BATTLE" -> (END,)."""
    h = header.upper()
    if "END OF THE BATTLE" in h:
        return (END,)
    named = [i for i, word in enumerate(_ORDINALS) if word in h]
    if not named:
        return tuple(range(ROUNDS))
    if "ONWARDS" in h:
        return tuple(range(named[0], ROUNDS))
    if " TO " in h:
        return tuple(range(named[0], named[-1] + 1))
    return tuple(named)


@dataclass(frozen=True)
class PrimaryOption:
    """One scoring line of a primary mission card."""
    text: str
    vp: int
    columns: tuple[int, ...]            # where it can be scored: battle rounds 0-4, END
    most: int = 1                       # times it can be scored in a column: 1 (a tick), 0 for no limit
    group: int = 0                      # options of a group are alternatives ("OR"): one at most per column
    block: int = 0                      # its scoring block on the card
    round: str = ""                     # the block's header: "SECOND BATTLE ROUND ONWARDS"
    when: str = ""                      # "End of your turn."
    additional: bool = False            # a "+" line: adds to the one above

    @property
    def tick(self) -> bool:
        return self.most == 1


def primary_options(mission: dict | None) -> list[PrimaryOption]:
    """The scoring options of a primary mission card (as parsed by crunch.data.missions)."""
    out: list[PrimaryOption] = []
    for b, block in enumerate((mission or {}).get("scoring", [])):
        cols = columns(block.get("round", ""))
        when = block.get("when", "")
        for cond in block.get("conditions", []):
            m = re.search(r"\d+", (cond.get("vp") or [{}])[0].get("vp", ""))
            if not m:
                continue
            text = cond.get("text", "")
            if text.lower().startswith("for each"):
                most = 0
            elif cols != (END,) and when.lower().startswith("end of a turn"):
                most = 2                                    # either player's turn: twice a battle round
            else:
                most = 1
            group = out[-1].group if cond.get("alternative") and out and out[-1].block == b else len(out)
            out.append(PrimaryOption(text, int(m.group()), cols, most, group, b, block.get("round", ""), when,
                                     bool(cond.get("additional"))))
    return out


@dataclass
class SecondaryRow:
    name: str = ""
    rounds: list[str] = field(default_factory=lambda: [""] * ROUNDS)

    @property
    def closed(self) -> int | None:
        """The battle round the mission was scored or discarded in, if it was."""
        return next((r for r, c in enumerate(self.rounds) if c == "x" or vp(c)), None)

    def set(self, r: int, cell: str) -> None:
        """The cell of a battle round. Scored or discarded: the rounds after read "-"; and blank again
        when that is undone. A closed mission's other cells are left as they are."""
        was = self.closed
        if was not in (None, r):
            return
        self.rounds[r] = cell
        if self.closed == r or was == r:
            self.rounds[r + 1:] = ["-" if self.closed == r else ""] * (ROUNDS - r - 1)

    def counted(self) -> list[int]:
        """The VP that count in each battle round: the mission's cap is used up round after round."""
        out, left = [], SECONDARY_MISSION_MAX
        for c in self.rounds:
            out.append(min(vp(c), left))
            left -= out[-1]
        return out

    @property
    def over(self) -> bool:
        """VP scored for this mission are lost to its cap."""
        return sum(vp(c) for c in self.rounds) > SECONDARY_MISSION_MAX


@dataclass
class PlayerScore:
    name: str = ""
    went_first: bool = False
    primary: list[str] = field(default_factory=lambda: [""] * COLUMNS)     # by hand, when there are no options
    secondaries: list[SecondaryRow] = field(default_factory=list)
    battle_ready: bool = True
    cp_gained: list[int] = field(default_factory=lambda: [0] * ROUNDS)
    cp_spent: list[int] = field(default_factory=lambda: [0] * ROUNDS)
    options: list[PrimaryOption] = field(default_factory=list)
    counts: list[list[int]] = field(default_factory=list)                  # per option: times scored per column

    def set_options(self, options: list[PrimaryOption]) -> None:
        """Score the primary mission with these options, nothing scored yet."""
        self.options = list(options)
        self.counts = [[0] * COLUMNS for _ in self.options]

    def score(self, i: int, col: int, n: int) -> None:
        """Option i is scored n times in a column (a tick: 0 or 1); its alternatives are then unscored."""
        opt = self.options[i]
        if col not in opt.columns:
            return
        n = max(0, n)
        self.counts[i][col] = min(n, opt.most) if opt.most else n
        if self.counts[i][col]:
            for j, other in enumerate(self.options):
                if j != i and other.group == opt.group:
                    self.counts[j][col] = 0

    # ------------------------------------------------------------ CP
    def cp_remaining(self, r: int) -> int:
        """CP left at the end of a battle round: all gained so far, less all spent."""
        return sum(self.cp_gained[:r + 1]) - sum(self.cp_spent[:r + 1])

    def cp_played(self, r: int) -> bool:
        """CP were gained or spent in this battle round or a later one."""
        return any(self.cp_gained[r:]) or any(self.cp_spent[r:])

    # ------------------------------------------------------------ primary
    def primary_raw(self, col: int) -> int:
        """Primary VP scored in a column, before the cap."""
        if self.options:
            return sum(o.vp * n[col] for o, n in zip(self.options, self.counts))
        return vp(self.primary[col]) if col < len(self.primary) else 0

    def primary_vp(self, col: int) -> int:
        raw = self.primary_raw(col)
        return raw if col == END else min(ROUND_MAX, raw)

    def primary_over(self, col: int) -> bool:
        """VP scored in this battle round are lost to the cap."""
        return col != END and self.primary_raw(col) > ROUND_MAX

    @property
    def primary_total(self) -> int:
        return min(PRIMARY_MAX, sum(self.primary_vp(c) for c in range(COLUMNS)))

    # ------------------------------------------------------------ secondary
    def unused_secondaries(self, names: list[str], row: SecondaryRow | None = None) -> list[str]:
        """The missions among `names` this player can still draw: a mission is on the sheet once.
        row: the row being chosen for, whose own mission stays in the list."""
        used = {r.name.strip().lower() for r in self.secondaries if r is not row}
        return [n for n in names if n.strip().lower() not in used]

    def secondary_raw(self, r: int) -> int:
        """Secondary VP scored in a battle round, each mission within its own cap, before the round's."""
        return sum(row.counted()[r] for row in self.secondaries)

    def secondary_vp(self, r: int) -> int:
        return min(ROUND_MAX, self.secondary_raw(r))

    def secondary_over(self, r: int) -> bool:
        """VP scored in this battle round are lost to the round's cap."""
        return self.secondary_raw(r) > ROUND_MAX

    @property
    def secondary_total(self) -> int:
        return min(SECONDARY_MAX, sum(self.secondary_vp(r) for r in range(ROUNDS)))

    @property
    def total(self) -> int:
        return self.primary_total + self.secondary_total + (BATTLE_READY if self.battle_ready else 0)


def wtc(a: int, b: int) -> tuple[int, int]:
    """WTC points (out of 20) for VP totals a and b."""
    diff = abs(a - b)
    win = 10 if diff <= 5 else min(20, 10 + (diff - 1) // 5)
    return (win, 20 - win) if a >= b else (20 - win, win)
