"""Game score: primary and secondary VP per battle round, Battle Ready, CP, and the WTC result.

A cell holds VP as entered: a number, "-" (nothing scored / discarded) or "" (not played yet).
Primary and secondary VP are each capped at 45; Battle Ready is worth 10: 100 VP at most.
WTC: the VP difference converts to a 20-point split (0-5 VP apart: 10-10, every 5 VP more: one point
more, 51+: 20-0)."""
from __future__ import annotations

from dataclasses import dataclass, field

ROUNDS = 5
PRIMARY_MAX = 45
SECONDARY_MAX = 45
BATTLE_READY = 10


def vp(cell: str) -> int:
    """The VP in a cell: its number, 0 for "-", "" or anything that isn't one."""
    try:
        return max(0, int(str(cell).strip()))
    except ValueError:
        return 0


@dataclass
class SecondaryRow:
    name: str = ""
    rounds: list[str] = field(default_factory=lambda: [""] * ROUNDS)


@dataclass
class PlayerScore:
    name: str = ""
    went_first: bool = False
    primary: list[str] = field(default_factory=lambda: [""] * ROUNDS)
    secondaries: list[SecondaryRow] = field(default_factory=list)
    battle_ready: bool = False
    cp: list[str] = field(default_factory=lambda: [""] * ROUNDS)

    @property
    def primary_total(self) -> int:
        return min(PRIMARY_MAX, sum(vp(c) for c in self.primary))

    @property
    def secondary_total(self) -> int:
        return min(SECONDARY_MAX, sum(vp(c) for row in self.secondaries for c in row.rounds))

    @property
    def total(self) -> int:
        return self.primary_total + self.secondary_total + (BATTLE_READY if self.battle_ready else 0)


def wtc(a: int, b: int) -> tuple[int, int]:
    """WTC points (out of 20) for VP totals a and b."""
    diff = abs(a - b)
    win = 10 if diff <= 5 else min(20, 10 + (diff - 1) // 5)
    return (win, 20 - win) if a >= b else (20 - win, win)
