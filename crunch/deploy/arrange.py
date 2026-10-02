"""Where the Deployer puts the boards being viewed and its info panel (legend, options) in the space
they share, so that the boards are drawn as large as possible.

The info panel has two shapes: `tall` (its parts stacked) and `wide` (its parts side by side). It goes
in a cell of the boards' grid, in a column on the right, or in a strip under the boards; the boards
take a grid in what is left. Every such arrangement is tried: the one with the largest boards wins.
Stacked, the panel can do with a little less height than it asks for (SQUEEZE: the end of its legend
goes), rather than the boards giving up much more to make room for it."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from crunch.deploy.placement import BOARD_H, BOARD_W

Rect = tuple[int, int, int, int]            # x, y, width, height
Size = tuple[int, int]
SQUEEZE = 0.85                              # the share of its height the stacked info panel can do with


@dataclass(frozen=True)
class Arrangement:
    boards: list[Rect]                      # a cell per board viewed, in order
    info: Rect
    wide: bool                              # the info panel in its wide shape
    scale: float                            # pixels per inch the boards are drawn at


def _grid(n: int, x: int, y: int, w: int, h: int, cols: int) -> list[Rect]:
    """n cells in a grid of `cols` columns filling a rectangle, row after row."""
    rows = ceil(n / cols)
    cw, ch = w // cols, h // rows
    return [(x + (i % cols) * cw, y + (i // cols) * ch, cw, ch) for i in range(n)]


def arrange(n: int, width: int, height: int, tall: Size, wide: Size, chrome: Size = (0, 0)) -> Arrangement:
    """n boards and the info panel in a width x height space.
    tall, wide: the size the info panel asks for in each shape.
    chrome: what a board's cell needs around the board itself (frame, title)."""
    if n <= 0:
        return Arrangement([], (0, 0, width, height), False, 0.0)

    def scale(cell: Rect) -> float:
        return min((cell[2] - chrome[0]) / BOARD_W, (cell[3] - chrome[1]) / BOARD_H)

    found: list[Arrangement] = []
    least = tall[1] * SQUEEZE
    for cols in range(1, n + 2):                # the info panel in a cell of the grid: what is left of the last row
        cells = _grid(n + 1, 0, 0, width, height, cols)
        x, y, w, h = cells[n]
        if w >= tall[0] and h >= least:
            found.append(Arrangement(cells[:n], (x, y, width - x, h), False, scale(cells[0])))
    for cols in range(1, n + 1):
        w, h = width - tall[0], height - wide[1]
        if w > 0 and least <= height:           # in a column on the right
            cells = _grid(n, 0, 0, w, height, cols)
            found.append(Arrangement(cells, (w, 0, tall[0], height), False, scale(cells[0])))
        if h > 0 and wide[0] <= width:          # in a strip under the boards
            cells = _grid(n, 0, 0, width, h, cols)
            found.append(Arrangement(cells, (0, h, width, wide[1]), True, scale(cells[0])))
    if not found:                               # no room for the info panel as it asks: it keeps its width
        w = max(width // 2, width - tall[0])
        cells = _grid(n, 0, 0, w, height, 1)
        found.append(Arrangement(cells, (w, 0, width - w, height), False, scale(cells[0])))
    return max(found, key=lambda a: a.scale)
