"""The Disposition Cogitator: every Force Disposition pitted against every other. In the left two
fifths, a matrix with a row and a column per disposition; each cell names the primary mission its
row's disposition plays against its column's, and the one played in return, each in its disposition's
colour (command_center.ui.theme.disposition_colors), as are the headings. Clicking a cell shows the
pairing's Estimate in the right three fifths (command_center.ui.tools.cogitator.estimate): the two
primary missions to score, and the pairing's layouts; the cell is outlined. A pairing has one
Estimate: the two cells that are each other's mirror across the diagonal show the same one, with the
upper cell's row disposition as Player 1. The Estimate shown at first is Battlefield Dominance's.

In a cell's bottom right corner, "1st o / 2nd o": how hard the matchup is for the row's disposition
(Player 1, in the upper triangle) when it goes first, and when it goes second. A circle's colour
comes from the saved Estimate's margin (the row's primary VP less the column's), in five groups
relative to every other margin on the matrix, from red (the hardest) to green (the easiest); it stays
empty without a saved Estimate. The colours follow the Estimates as they are edited.

It needs no army list: the launcher opens it whatever is selected."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from string import capwords
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.deploy.estimates import difficulty
from command_center.ui.registry import Selection, register_tool
from command_center.ui.theme import C, DIFFICULTY_COLORS, NO_ESTIMATE, display_family, disposition_colors, font_family
from command_center.ui.tools.cogitator.estimate import EstimatePanel
from command_center.ui.toolwindow import ToolWindow

if TYPE_CHECKING:
    from command_center.ui.app import App


FIRST_SHOWN = "Battlefield Dominance"      # the primary mission whose Estimate is shown at first
MATRIX, ESTIMATE = 2, 3                    # how the window's width is shared: two fifths, three fifths
HEADINGS = 118                             # width of the matrix's column of row headings


def _hyphenated(word: str, font: tkfont.Font, room: int) -> str:
    """`word`, cut in two with a hyphen if it is wider than `room`: where a heading would otherwise be
    wrapped in the middle of it, wherever the line ends."""
    if font.measure(word) <= room:
        return word
    cut = next((n for n in range(len(word) - 2, 2, -1) if font.measure(word[:n] + "-") <= room), len(word) // 2)
    cut = min(cut, len(word) * 2 // 3)                        # not just its last letters on the second line
    return f"{word[:cut]}-\n{word[cut:]}"


class CogitatorWindow(ToolWindow):
    title_text = "Disposition Cogitator"

    def __init__(self, app: "App", selection: Selection | None):
        super().__init__(app, selection)
        self.estimate: EstimatePanel | None = None              # the Estimate shown on the right
        self.pair: tuple[str, str] | None = None                # its pairing
        self.cells: dict[tuple[int, int], ttk.Frame] = {}
        # the difficulty circles: (row, column, the row's disposition goes first) -> canvas, circle
        self.dots: dict[tuple[int, int, bool], tuple[tk.Canvas, int]] = {}
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Button(top, text="← Command Center", command=self.back).pack(side="left")
        ttk.Label(top, text="Disposition Cogitator", style="H1.TLabel").pack(side="left", padx=(12, 0))
        split = ttk.Frame(body)
        split.pack(fill="both", expand=True, pady=(8, 0))
        split.rowconfigure(0, weight=1)
        split.columnconfigure(0, weight=MATRIX, uniform="fifths")
        split.columnconfigure(1, weight=ESTIMATE, uniform="fifths")
        left = ttk.Frame(split)                                 # the matrix, in the middle of its two fifths
        left.grid(row=0, column=0, sticky="nsew")
        self.right = ttk.Frame(split)
        self.right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.update_idletasks()                                 # the window fills the screen: its real width
        self.matrix = self._build_matrix(left, (self.winfo_width() - 24) * MATRIX // (MATRIX + ESTIMATE))
        self.matrix.place(relx=0.5, rely=0.5, anchor="center")
        self.show_difficulty()
        if self.ctx.missions.dispositions:
            self.open_estimate(*self._first_pairing())

    def _first_pairing(self) -> tuple[str, str]:
        """The pairing played with FIRST_SHOWN (the first one of the matrix if no mission has that name)."""
        book = self.ctx.missions
        names = book.dispositions
        pairs = [(own, opponent) for r, own in enumerate(names) for opponent in names[r:]]
        played = lambda a, b: (book.primary_mission(a, b) or {}).get("name", "").lower() == FIRST_SHOWN.lower()
        return next((p for p in pairs if played(*p) or played(*p[::-1])), pairs[0])

    def _build_matrix(self, parent, width: int) -> ttk.Frame:
        """width: what the matrix may take; its cells are as wide as that allows, 170 at most."""
        book = self.ctx.missions
        names = book.dispositions
        f = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        if not names:
            ttk.Label(f, text="No mission data yet: run  python -m command_center fetch", style="Muted.TLabel").pack()
            return f
        fam = font_family()
        cell_w = max(96, min(170, (width - 28 - HEADINGS - 6) // len(names) - 6))
        ttk.Label(f, text="Click a matchup for its Estimate", style="Muted.TLabel", wraplength=HEADINGS - 8,
                  justify="left").grid(row=0, column=0, sticky="sw", padx=(0, 6), pady=6)
        f.columnconfigure(0, minsize=HEADINGS)
        heading = tkfont.Font(family=display_family(), size=10, weight="bold")
        room = min(cell_w, HEADINGS) - 16
        for i, name in enumerate(names):
            ink, tint = disposition_colors(name)
            badge = dict(text=" ".join(_hyphenated(word, heading, room) for word in name.upper().split()),
                         bg=tint, fg=ink, font=heading, padx=6, pady=3)
            tk.Label(f, anchor="center", wraplength=cell_w - 14, **badge).grid(row=0, column=1 + i, sticky="nsew",
                                                                               padx=3, pady=(0, 6))
            tk.Label(f, anchor="e", justify="right", wraplength=HEADINGS - 14, **badge).grid(
                row=1 + i, column=0, sticky="nsew", padx=(0, 6), pady=3)
            f.columnconfigure(1 + i, uniform="pairings", minsize=cell_w)
            f.rowconfigure(1 + i, uniform="pairings", minsize=84)
        for r, own in enumerate(names):
            for c, opponent in enumerate(names):
                mine, theirs = book.primary_mission(own, opponent), book.primary_mission(opponent, own)
                cell = ttk.Frame(f, style="Cell.TFrame", padding=(8, 6), cursor="hand2")
                cell.grid(row=1 + r, column=1 + c, sticky="nsew", padx=3, pady=3)
                self.cells[r, c] = cell
                ttk.Label(cell, text=capwords(mine["name"]) if mine else "?", style="Cell.TLabel",
                          font=(fam, 10, "bold"), foreground=disposition_colors(own)[0], wraplength=cell_w - 20,
                          justify="left").pack(anchor="w")
                if own == opponent:
                    ttk.Label(cell, text="mirror", style="CellMuted.TLabel").pack(anchor="w")
                else:
                    ttk.Label(cell, text=f"vs {capwords(theirs['name'])}" if theirs else "", style="CellMuted.TLabel",
                              foreground=disposition_colors(opponent)[0], wraplength=cell_w - 20,
                              justify="left").pack(anchor="w")
                self._difficulty_dots(cell, r, c, fam).pack(side="bottom", anchor="e")
                pair = (own, opponent) if r <= c else (opponent, own)       # as its upper-triangle cell
                for w in (cell, *cell.winfo_children()):
                    w.bind("<Button-1>", lambda e, pair=pair: self.open_estimate(*pair))
        ttk.Label(f, text="1st / 2nd: the row's disposition going first / second, from its Estimates",
                  style="Muted.TLabel").grid(row=1 + len(names), column=0, columnspan=1 + len(names), sticky="e",
                                             pady=(8, 0))
        key = ttk.Frame(f, style="Flat.TFrame")                 # what the circles' colours mean
        key.grid(row=2 + len(names), column=0, columnspan=1 + len(names), sticky="e", pady=(2, 0))
        ttk.Label(key, text="hardest", style="Muted.TLabel").pack(side="left")
        scale = tk.Canvas(key, width=16 * len(DIFFICULTY_COLORS) + 4, height=14, bg=C["panel"], highlightthickness=0)
        for i, color in enumerate(DIFFICULTY_COLORS):
            scale.create_oval(4 + 16 * i, 2, 14 + 16 * i, 12, fill=color, outline=C["muted"])
        scale.pack(side="left", padx=4)
        ttk.Label(key, text="easiest", style="Muted.TLabel").pack(side="left")
        none = tk.Canvas(key, width=16, height=14, bg=C["panel"], highlightthickness=0)
        none.create_oval(4, 2, 14, 12, fill=NO_ESTIMATE, outline=C["muted"])
        none.pack(side="left", padx=(12, 2))
        ttk.Label(key, text="no Estimate yet", style="Muted.TLabel").pack(side="left")
        return f

    def _difficulty_dots(self, cell, r: int, c: int, fam: str) -> tk.Canvas:
        """"1st o / 2nd o" for a cell: a circle per turn order of the row's disposition."""
        cv = tk.Canvas(cell, width=96, height=16, bg=C["field"], highlightthickness=0)
        x = 0
        for text, goes_first in (("1st", True), ("/  2nd", False)):
            t = cv.create_text(x, 8, text=text, anchor="w", fill=C["muted"], font=(fam, 9))
            x = cv.bbox(t)[2] + 5
            self.dots[r, c, goes_first] = (cv, cv.create_oval(x, 3, x + 10, 13, fill=NO_ESTIMATE, outline=C["muted"]))
            x += 16
        cv.configure(width=x - 5)
        return cv

    def show_difficulty(self):
        """Colour the circles from the saved Estimates: each one's margin for the row's disposition, in
        five groups relative to all the others."""
        names = self.ctx.missions.dispositions
        groups = difficulty(self.ctx.missions, self.ctx.estimates)
        for (r, c, goes_first), (cv, dot) in self.dots.items():
            group = groups.get((names[r], names[c], goes_first))
            cv.itemconfigure(dot, fill=NO_ESTIMATE if group is None else DIFFICULTY_COLORS[group])

    def open_estimate(self, first: str, second: str):
        """Show the Estimate of a pairing (Player 1's disposition, Player 2's) on the right, in place of the
        one that was there, and outline its cells: the pairing's and its mirror across the diagonal."""
        if self.pair == (first, second):
            return
        if self.estimate is not None:
            self.estimate.destroy()
        self.pair = (first, second)
        self.estimate = EstimatePanel(self.right, self, first, second)
        self.estimate.pack(fill="both", expand=True)
        names = self.ctx.missions.dispositions
        shown = {(names.index(first), names.index(second)), (names.index(second), names.index(first))}
        for at, cell in self.cells.items():
            cell.configure(style="CellOn.TFrame" if at in shown else "Cell.TFrame")


@register_tool("cogitator", "Disposition Cogitator", "Every Force Disposition against every other: the primary "
               "missions of each pairing, and its Estimate: the primaries to score, the layouts.", order=5, needs_armies=False)
def open_cogitator(app: "App", selection: Selection | None) -> CogitatorWindow:
    return CogitatorWindow(app, selection)
