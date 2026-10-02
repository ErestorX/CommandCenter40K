"""Parts of a score sheet shared by the windows that show one (the Score Oracle, the Disposition
Cogitator's Estimates): two players' grids face to face in a scrolling area, and the rows of a primary
mission in such a grid.

A grid has the texts in column 0, a column per battle round and one for the end of the battle
(columns 1 to COLUMNS), then a column for totals."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from command_center.deploy.scoring import COLUMNS, END, PRIMARY_MAX, PlayerScore
from command_center.ui.theme import C, font_family

CELL_BG, CELL_DONE = "#ffffff", "#e9e6df"          # empty cell, cell with a value
CELL_BAD = "#f6d4d4"                               # not a number
OVER_INK = "#b26a00"                               # VP lost to a cap


def sheet_fonts() -> dict[str, tuple]:
    fam = font_family()
    return {"cell": (fam, 10), "total": (fam, 10, "bold"), "small": (fam, 9)}


class FaceToFace(ttk.Frame):
    """Two grids side by side, one per player, scrolling together when they are taller than the room
    they get. Texts registered in `wide` (spanning a grid) and `beside` (left of the round columns)
    are wrapped to the width they have."""

    def __init__(self, master):
        super().__init__(master)
        bar = ttk.Scrollbar(self, orient="vertical")
        bar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.configure(command=self.canvas.yview)
        sheet = self.sheet = ttk.Frame(self.canvas)
        self.sheet_id = self.canvas.create_window(0, 0, window=sheet, anchor="nw")
        self.canvas.bind("<Configure>", self._resized)
        sheet.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=(0, 0, e.width, e.height)))
        self.winfo_toplevel().bind("<MouseWheel>", self.wheel)
        sheet.rowconfigure(0, weight=1)
        self.grids: list[ttk.Frame] = []
        self.wide: list[list] = [[], []]
        self.beside: list[list] = [[], []]
        for c in range(2):
            sheet.columnconfigure(c, weight=1, uniform="players")
            g = ttk.Frame(sheet, style="Panel.TFrame", padding=10)
            g.grid(row=0, column=c, sticky="nsew", padx=(0, 5) if c == 0 else (5, 0))
            g.columnconfigure(0, weight=1)
            self.grids.append(g)

    def clear(self, i: int) -> ttk.Frame:
        """Empty a player's grid, to build it again."""
        g = self.grids[i]
        for w in g.winfo_children():
            w.destroy()
        for row in range(g.grid_size()[1] + 1):               # earlier builds' spacer rows: back to normal
            g.rowconfigure(row, weight=0)
        self.wide[i], self.beside[i] = [], []
        return g

    def wheel(self, e):
        """The wheel scrolls the sheet, wherever the pointer is: never the value of a drop-down under it."""
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _resized(self, e):
        """The sheet is as wide as the scrolling area, and at least as tall; its texts wrap to that width."""
        self.canvas.itemconfigure(self.sheet_id, width=e.width)
        self.sheet.rowconfigure(0, minsize=e.height)
        for i in range(2):
            self.wrap(i)

    def wrap(self, i: int):
        """Texts wrap at the width their grid leaves them. That width comes from the scrolling area's,
        not from the grid's own: the grid's depends on its texts, and the two would chase each other."""
        full = (self.canvas.winfo_width() - 10) // 2 - 26     # half the sheet, less the gap, border and padding
        if full < 100:                                        # not laid out yet
            return
        beside = full - self.grids[i].grid_bbox(1, 0, 1 + COLUMNS, 0)[2] - 10     # left of the round columns
        for lb in self.wide[i]:
            lb.configure(wraplength=full)
        for lb in self.beside[i]:
            lb.configure(wraplength=max(120, beside))


def column_headers(g, row: int = 0):
    """The round numbers, then the end of the battle, above their columns."""
    for col in range(COLUMNS):
        ttk.Label(g, text="End" if col == END else str(col + 1), style="Muted.TLabel").grid(row=row, column=1 + col)


def summary_row(g, row: int, title: str, n: int, fonts: dict) -> tuple[ttk.Label, list[tk.Label], ttk.Label]:
    """A section's heading: its name, a label per column for the VP counted there, one for its total."""
    lb = ttk.Label(g, text=title, style="Panel.TLabel", font=fonts["total"], wraplength=220, justify="left")
    lb.grid(row=row, column=0, sticky="w", pady=(10, 2))
    rounds = []
    for col in range(n):
        t = tk.Label(g, text="", font=fonts["total"], bg=C["panel"], fg=C["ink"], width=3)
        t.grid(row=row, column=1 + col, pady=(10, 2))
        rounds.append(t)
    total = ttk.Label(g, text="", style="Panel.TLabel", font=fonts["total"])
    total.grid(row=row, column=1 + COLUMNS, padx=(6, 0), pady=(10, 2))
    return lb, rounds, total


def show_vp(lb: tk.Label, points: int, over: bool):
    """The VP counted in a column; with a "!" when more were scored than the round's cap."""
    lb.configure(text=f"{points}!" if over else str(points) if points else "", fg=OVER_INK if over else C["ink"])


class PrimaryRows:
    """A player's primary mission in a grid, from `row` down: its heading (the VP counted per column, the
    total), then a row per scoring option of its card, under its block's heading: a tick box where the
    option is scored once, a - n + counter where it is scored "for each ...". Without options (the
    mission isn't known), a row of VP cells to fill by hand.

    next_row: the first free row under it. wide, beside: its texts, for FaceToFace to wrap.
    on_change: called after each edit; refresh() then shows the totals."""

    def __init__(self, g, row: int, score: PlayerScore, title: str, fonts: dict, on_change: Callable[[], None]):
        self.score, self.fonts, self.on_change = score, fonts, on_change
        self.wide: list = []
        self.counts: dict[tuple[int, int], tk.IntVar] = {}
        lb, self.rounds, self.total = summary_row(g, row, title, COLUMNS, fonts)
        self.beside: list = [lb]
        row += 1
        if not score.options:
            ttk.Label(g, text="VP scored", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=1)
            self._round_cells(g, row, score.primary)
            self.next_row = row + 1
            return
        block = None
        for i, opt in enumerate(score.options):
            if opt.block != block:                              # "Second battle round onwards · End of your turn."
                block = opt.block
                head = ttk.Label(g, text="  ·  ".join(t for t in (opt.round.capitalize(), opt.when) if t),
                                 style="Muted.TLabel", wraplength=400, justify="left")
                head.grid(row=row, column=0, columnspan=2 + COLUMNS, sticky="w", pady=(5, 0))
                self.wide.append(head)
                row += 1
            text = f"{'or ' if opt.group != i else ''}{'+' if opt.additional else ''}{opt.vp}VP  {opt.text}"
            lb = tk.Label(g, text=text, font=fonts["small"], bg=C["panel"], fg=C["ink"], wraplength=220,
                          justify="left", anchor="w")
            lb.grid(row=row, column=0, sticky="w", padx=(8, 0), pady=1)
            self.beside.append(lb)
            for col in opt.columns:
                v = self.counts[i, col] = tk.IntVar(value=score.counts[i][col])
                if opt.tick:
                    w = ttk.Checkbutton(g, variable=v, style="Panel.TCheckbutton",
                                        command=lambda i=i, col=col, v=v: self._score(i, col, v.get()))
                else:
                    w = self._counter(g, i, col, v)
                w.grid(row=row, column=1 + col, padx=1 if opt.tick else 4, pady=1)
            row += 1
        self.next_row = row

    def refresh(self):
        s = self.score
        for col, lb in enumerate(self.rounds):
            show_vp(lb, s.primary_vp(col), s.primary_over(col))
        self.total.configure(text=f"{s.primary_total}/{PRIMARY_MAX}")

    def _score(self, i: int, col: int, n: int):
        """An option is scored n times in a column; ticks and counters then show the sheet's state
        (scoring an option unticks its alternatives)."""
        self.score.score(i, col, n)
        for (j, c), v in self.counts.items():
            if c == col:
                v.set(self.score.counts[j][c])
        self.on_change()

    def _counter(self, g, i: int, col: int, v: tk.IntVar) -> tk.Frame:
        """- n +: how many times an option is scored in a column."""
        f = tk.Frame(g, bg=C["panel"])
        for text, step in (("−", -1), ("", 0), ("+", 1)):
            if not step:
                tk.Label(f, textvariable=v, width=2, font=self.fonts["cell"], bg=C["panel"], fg=C["ink"]).pack(
                    side="left")
                continue
            b = tk.Label(f, text=text, font=self.fonts["total"], bg=CELL_DONE, fg=C["ink"], cursor="hand2", padx=3)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, step=step: self._score(i, col, v.get() + step))
        return f

    def _round_cells(self, g, row: int, values: list[str]):
        """A cell per column of `values`, editing them in place: a number, "-" or nothing."""
        for r in range(len(values)):
            v = tk.StringVar(value=values[r])
            e = tk.Entry(g, textvariable=v, width=3, justify="center", font=self.fonts["cell"], relief="flat",
                         highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["ink"],
                         bg=self._cell_bg(values[r]))
            e.grid(row=row, column=1 + r, padx=1, pady=1, ipady=2)
            v.trace_add("write", lambda *a, v=v, e=e, r=r: self._on_cell(values, r, v, e))

    @staticmethod
    def _cell_bg(text: str) -> str:
        if not text:
            return CELL_BG
        return CELL_DONE if text == "-" or text.isdigit() else CELL_BAD

    def _on_cell(self, values: list[str], r: int, v: tk.StringVar, e: tk.Entry):
        text = v.get().strip()
        bg = self._cell_bg(text)
        e.configure(bg=bg)
        values[r] = "" if bg == CELL_BAD else text
        self.on_change()
