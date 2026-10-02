"""The Disposition Cogitator: every Force Disposition pitted against every other. At the centre, a
matrix with a row and a column per disposition; each cell names the primary mission its row's
disposition plays against its column's, and the one played in return, each in its disposition's
colour (command_center.ui.theme.disposition_colors), as are the headings. Clicking a cell opens the
pairing's Estimate, a floating window (command_center.ui.tools.cogitator.estimate): the two primary missions
to score, and the pairing's layouts. A pairing has one Estimate: the two cells that are each other's
mirror across the diagonal open the same one, with the upper cell's row disposition as Player 1.

In a cell's bottom right corner, "1st o / 2nd o": how hard the matchup is for the row's disposition
(Player 1, in the upper triangle) when it goes first, and when it goes second. A circle's colour
comes from the saved Estimate's margin (the row's primary VP less the column's), in five groups
relative to every other margin on the matrix, from red (the hardest) to green (the easiest); it stays
empty without a saved Estimate. The colours follow the Estimates as they are edited.

It needs no army list: the launcher opens it whatever is selected."""
from __future__ import annotations

import tkinter as tk
from string import capwords
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.deploy.estimates import difficulty
from command_center.ui.registry import Selection, register_tool
from command_center.ui.theme import DIFFICULTY_COLORS, NO_ESTIMATE, C, disposition_colors, font_family
from command_center.ui.tools.cogitator.estimate import EstimateWindow
from command_center.ui.toolwindow import ToolWindow

if TYPE_CHECKING:
    from command_center.ui.app import App


class CogitatorWindow(ToolWindow):
    title_text = "Disposition Cogitator"
    default_geometry = "1280x760"
    min_size = (1000, 600)

    def __init__(self, app: "App", selection: Selection | None):
        super().__init__(app, selection)
        self.estimates: dict[tuple[str, str], EstimateWindow] = {}     # the floating windows, per pairing
        # the difficulty circles: (row, column, the row's disposition goes first) -> canvas, circle
        self.dots: dict[tuple[int, int, bool], tuple[tk.Canvas, int]] = {}
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Button(top, text="← Command Center", command=self.back).pack(side="left")
        ttk.Label(top, text="Disposition Cogitator", style="H1.TLabel").pack(side="left", padx=(12, 0))
        centre = ttk.Frame(body)                                # the matrix, in the middle of what is left
        centre.pack(fill="both", expand=True)
        self.matrix = self._build_matrix(centre)
        self.matrix.place(relx=0.5, rely=0.5, anchor="center")
        self.show_difficulty()

    def _build_matrix(self, parent) -> ttk.Frame:
        book = self.ctx.missions
        names = book.dispositions
        f = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        if not names:
            ttk.Label(f, text="No mission data yet: run  python -m command_center fetch", style="Muted.TLabel").pack()
            return f
        fam = font_family()
        ttk.Label(f, text="Click a matchup for its Estimate", style="Muted.TLabel").grid(row=0, column=0,
                                                                                        sticky="sw", padx=6, pady=6)
        for i, name in enumerate(names):
            ink, tint = disposition_colors(name)
            badge = dict(text=name.upper(), bg=tint, fg=ink, font=(fam, 9, "bold"), padx=10, pady=3)
            tk.Label(f, anchor="center", **badge).grid(row=0, column=1 + i, sticky="ew", padx=3, pady=(0, 6))
            tk.Label(f, anchor="e", **badge).grid(row=1 + i, column=0, sticky="ew", padx=(0, 6), pady=3)
            f.columnconfigure(1 + i, uniform="pairings", minsize=170)
            f.rowconfigure(1 + i, uniform="pairings", minsize=84)
        for r, own in enumerate(names):
            for c, opponent in enumerate(names):
                mine, theirs = book.primary_mission(own, opponent), book.primary_mission(opponent, own)
                cell = ttk.Frame(f, style="Cell.TFrame", padding=(8, 6), cursor="hand2")
                cell.grid(row=1 + r, column=1 + c, sticky="nsew", padx=3, pady=3)
                ttk.Label(cell, text=capwords(mine["name"]) if mine else "?", style="Cell.TLabel",
                          font=(fam, 10, "bold"), foreground=disposition_colors(own)[0], wraplength=150,
                          justify="left").pack(anchor="w")
                if own == opponent:
                    ttk.Label(cell, text="mirror", style="CellMuted.TLabel").pack(anchor="w")
                else:
                    ttk.Label(cell, text=f"vs {capwords(theirs['name'])}" if theirs else "", style="CellMuted.TLabel",
                              foreground=disposition_colors(opponent)[0], wraplength=150,
                              justify="left").pack(anchor="w")
                self._difficulty_dots(cell, r, c, fam).pack(side="bottom", anchor="e")
                pair = (own, opponent) if r <= c else (opponent, own)       # as its upper-triangle cell
                for w in (cell, *cell.winfo_children()):
                    w.bind("<Button-1>", lambda e, pair=pair: self.open_estimate(*pair))
        key = ttk.Frame(f, style="Flat.TFrame")                 # what the circles' colours mean
        key.grid(row=1 + len(names), column=0, columnspan=1 + len(names), sticky="e", pady=(8, 0))
        ttk.Label(key, text="1st / 2nd: the row's disposition going first / second, from its Estimates   hardest",
                  style="Muted.TLabel").pack(side="left")
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
        cv = tk.Canvas(cell, width=96, height=16, bg="white", highlightthickness=0)
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
        """The Estimate of a pairing (Player 1's disposition, Player 2's): one each, brought to the front
        if already open."""
        win = self.estimates.get((first, second))
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_set()
            return
        self.estimates[first, second] = EstimateWindow(self, first, second)


@register_tool("cogitator", "Disposition Cogitator", "Every Force Disposition against every other: the primary "
               "missions of each pairing, and its Estimate: the primaries to score, the layouts.", order=5, needs_armies=False)
def open_cogitator(app: "App", selection: Selection | None) -> CogitatorWindow:
    return CogitatorWindow(app, selection)
