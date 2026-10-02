"""The Estimate: the Disposition Cogitator's floating window for one pairing of Force Dispositions,
Player 1's against Player 2's.

Top half, the two players face to face with the primary mission each plays in the pairing, as on the
Score Oracle's sheet: a row per scoring option, to tick or count per battle round, and the VP it adds
up to. Bottom half, the pairing's three battlefield layouts, with the deployment zones and the line
between the two territories; Player 1 has the layouts' attacker side, Player 2 the defender's.

A pairing has two Estimates: one with Player 1 going first, one with Player 2. The header switches
between them (Player 1 first to begin with). In a mirror pairing they are the same Estimate with the
two players swapped: what is scored for the player going first shows on whoever goes first. Each is saved at every change (ctx.estimates,
crunch.deploy.estimates) and shown again the next time; the Score Oracle can import the one matching
its game."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.deploy.estimates import PLAYERS, saved_scores
from crunch.deploy.scoring import PlayerScore
from crunch.ui.theme import C
from crunch.ui.tools.deployer.map_view import LayoutMap
from crunch.ui.views.scoresheet import FaceToFace, PrimaryRows, column_headers, sheet_fonts

if TYPE_CHECKING:
    from crunch.ui.tools.cogitator.window import CogitatorWindow

SIDES = (("Att.TLabel", "AttBadge.TLabel"), ("Def.TLabel", "DefBadge.TLabel"))     # Player 1, Player 2


class EstimateWindow(tk.Toplevel):
    def __init__(self, cogitator: "CogitatorWindow", first: str, second: str):
        """first, second: Player 1's and Player 2's Force Dispositions."""
        super().__init__(cogitator)
        self.title(f"Game Crunch — Estimate: {first} vs {second}")
        self.configure(bg=C["bg"])
        self.geometry("1280x900")
        self.minsize(1000, 640)
        self.transient(cogitator)                  # floats above the Cogitator, both usable
        book = cogitator.ctx.missions
        self.cogitator = cogitator
        self.store = cogitator.ctx.estimates
        self.pair = (first, second)
        self.fonts = sheet_fonts()
        pairing = ((first, second), (second, first))

        # one Estimate per player going first: each its own two scores, as saved
        self.scores: list[list[PlayerScore]] = []
        for goes_first in range(2):
            self.names, scores, _ = saved_scores(book, self.store, first, second, goes_first)
            self.scores.append(scores)
        if first == second:                                     # mirror: one Estimate, its players swapped
            self.scores[1] = self.scores[0][::-1]
        self.goes_first = tk.IntVar(value=0)                    # the Estimate shown: the player going first

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        for row in (1, 2):                                      # the primaries above, the maps below: half each
            body.rowconfigure(row, weight=1, uniform="halves")
        self.turn_labels: list[ttk.Label] = []
        self._build_header(body, pairing).grid(row=0, column=0, sticky="ew")
        self.faces = FaceToFace(body)
        self.faces.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.primaries: list[PrimaryRows | None] = [None, None]

        maps = ttk.Frame(body)
        maps.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        maps.rowconfigure(0, weight=1)
        layouts = book.layouts_for(first, second)
        self.maps: list[LayoutMap] = []
        for c in range(3):
            maps.columnconfigure(c, weight=1, uniform="maps")
            m = LayoutMap(maps)
            m.show_territory = True
            m.role_names = dict(zip(("attacker", "defender"), PLAYERS))
            m.grid(row=0, column=c, sticky="nsew", padx=(0 if c == 0 else 3, 0 if c == 2 else 3))
            m.set_layout(layouts[c] if c < len(layouts) else None,
                         "" if layouts or c else f"No layouts found for {first} vs {second}.")
            self.maps.append(m)
        self._show_estimate()

    def _build_header(self, parent, pairing) -> ttk.Frame:
        """Each player: its name, Force Disposition and primary mission, and whether it goes first. Between
        them, who goes first: the Estimate shown."""
        head = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 8))
        for c in (0, 2):
            head.columnconfigure(c, weight=1, uniform="sides")
        for c, i, anchor in ((0, 0, "w"), (2, 1, "e")):
            f = ttk.Frame(head, style="Flat.TFrame")
            f.grid(row=0, column=c, sticky=anchor)
            top = ttk.Frame(f, style="Flat.TFrame")
            top.pack(anchor=anchor)
            parts = [ttk.Label(top, text=PLAYERS[i].upper(), style=SIDES[i][0]),
                     ttk.Label(top, text=pairing[i][0].upper(), style=SIDES[i][1]),
                     ttk.Label(top, text="", style="Muted.TLabel")]
            self.turn_labels.append(parts[2])
            for w in (parts if anchor == "w" else reversed(parts)):      # mirrored on the right
                w.pack(side="left", padx=(0, 8) if anchor == "w" else (8, 0))
            ttk.Label(f, text=self.names[i], style="H2.TLabel").pack(anchor=anchor, pady=(4, 0))
        mid = ttk.Frame(head, style="Flat.TFrame")
        mid.grid(row=0, column=1, padx=20)
        pick = ttk.Frame(mid, style="Flat.TFrame")
        pick.pack()
        ttk.Label(pick, text="Goes first", style="Panel.TLabel").pack(side="left", padx=(0, 6))
        for i, player in enumerate(PLAYERS):
            ttk.Radiobutton(pick, text=player, value=i, variable=self.goes_first, style="Panel.TRadiobutton",
                            command=self._show_estimate).pack(side="left", padx=(0, 6))
        ttk.Label(mid, text="Mirror: one Estimate, the same whoever goes first, saved as you go"
                  if pairing[0][0] == pairing[0][1] else "One Estimate per player going first, each saved as you go",
                  style="Muted.TLabel").pack(
            pady=(4, 0))
        return head

    def _show_estimate(self):
        """The Estimate of the player going first: who goes first next to the names, and its two primaries."""
        goes_first = self.goes_first.get()
        for i, lb in enumerate(self.turn_labels):
            lb.configure(text="goes first" if i == goes_first else "goes second")
        for i, score in enumerate(self.scores[goes_first]):
            g = self.faces.clear(i)
            ttk.Label(g, text=PLAYERS[i].upper(), style=SIDES[i][0]).grid(row=0, column=0, sticky="w")
            column_headers(g)
            rows = self.primaries[i] = PrimaryRows(g, 1, score, self.names[i], self.fonts,
                                                   on_change=lambda i=i: self._changed(i))
            self.faces.wide[i] += rows.wide
            self.faces.beside[i] += rows.beside
            ttk.Frame(g, style="Flat.TFrame").grid(row=rows.next_row, column=0)
            g.rowconfigure(rows.next_row, weight=1)             # space below, not between the rows
            rows.refresh()
            self.faces.wrap(i)

    def _changed(self, i: int):
        """A player's scoring changed: its totals, the Estimate saved, and the matrix's difficulty colours."""
        self.primaries[i].refresh()
        goes_first = self.goes_first.get()
        self.store.put(*self.pair, goes_first, self.names, self.scores[goes_first])
        self.cogitator.show_difficulty()
