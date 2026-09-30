"""Dice expressions from datasheets: "3", "D6", "2D3", "D6+1", "d6+3"."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_DICE_RE = re.compile(r"^\s*(\d*)\s*[dD]\s*(\d+)\s*(?:\+\s*(\d+))?\s*$")


@dataclass(frozen=True)
class Dice:
    n: int = 0          # number of dice
    sides: int = 0      # die size
    flat: int = 0       # flat bonus

    @classmethod
    def parse(cls, text) -> "Dice":
        s = str(text if text is not None else "").strip()
        if s in ("", "-", "N/A", "n/a"):
            return cls()
        if s.isdigit():
            return cls(0, 0, int(s))
        m = _DICE_RE.match(s)
        if not m:
            raise ValueError(f"Unparseable dice expression: {text!r}")
        return cls(int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0))

    def __bool__(self) -> bool:
        return bool(self.n or self.flat)

    @property
    def mean(self) -> float:
        return self.n * (self.sides + 1) / 2 + self.flat

    def roll(self, rng: np.random.Generator, size) -> np.ndarray:
        out = np.full(size, self.flat, dtype=np.int64)
        for _ in range(self.n):
            out += rng.integers(1, self.sides + 1, size=size)
        return out

    def __str__(self) -> str:
        if not self.n:
            return str(self.flat)
        base = f"{'' if self.n == 1 else self.n}D{self.sides}"
        return base + (f"+{self.flat}" if self.flat else "")
