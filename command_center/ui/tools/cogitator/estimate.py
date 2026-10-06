"""The Estimate: the Disposition Cogitator's panel for one pairing of Force Dispositions, Player 1's
against Player 2's, to the right of its matrix.

Top half, the two players face to face with the primary mission each plays in the pairing, as on the
Score Oracle's sheet: a row per scoring option, to tick or count per battle round, and the VP it adds
up to; under them, the actions of the mission's card, in full. Bottom half, the pairing's three battlefield layouts, with the deployment zones and the line
between the two territories; Player 1 has the layouts' attacker side, Player 2 the defender's.

A pairing has two Estimates: one with Player 1 going first, one with Player 2. The header switches
between them (Player 1 first to begin with). In a mirror pairing they are the same Estimate with the
two players swapped: what is scored for the player going first shows on whoever goes first. Each is
saved at every change (ctx.estimates, command_center.deploy.estimates) and shown again the next time;
the Score Oracle can import the one matching its game."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.deploy.estimates import PLAYERS, saved_scores
from command_center.deploy.scoring import COLUMNS, PlayerScore
from command_center.ui.tools.holomap.map_view import LayoutMap
from command_center.ui.views.scoresheet import FaceToFace, PrimaryRows, column_headers, sheet_fonts

if TYPE_CHECKING:
    from command_center.ui.tools.cogitator.window import CogitatorWindow

SIDES = (("Att.TLabel", "AttBadge.TLabel"), ("Def.TLabel", "DefBadge.TLabel"))     # Player 1, Player 2


class EstimatePanel(ttk.Frame):
    def __init__(self, master, cogitator: "CogitatorWindow", first: str, second: str):
        """first, second: Player 1's and Player 2's Force Dispositions."""
        super().__init__(master)
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
        # the actions of each player's primary mission, as on its card
        self.actions = [(book.primary_mission(*p) or {}).get("actions", []) for p in pairing]

        body = self
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
            row = self._show_actions(g, rows.next_row, i)
            ttk.Frame(g, style="Flat.TFrame").grid(row=row, column=0)
            g.rowconfigure(row, weight=1)                       # space below, not between the rows
            rows.refresh()
            self.faces.wrap(i)

    def _show_actions(self, g, row: int, i: int) -> int:
        """The actions of a player's mission, from `row` down: each one's name and type, then its card's lines
        (starts, units, use limit, completes, effect...). Returns the first free row under them."""
        def line(text: str, style: str, pady, **kw):
            nonlocal row
            lb = ttk.Label(g, text=text, style=style, wraplength=400, justify="left", **kw)
            lb.grid(row=row, column=0, columnspan=2 + COLUMNS, sticky="w", pady=pady)
            self.faces.wide[i].append(lb)
            row += 1
        for a in self.actions[i]:
            line(f"{a.get('name', '').title()}  ·  {a.get('type', '').capitalize()}", "Panel.TLabel", (12, 2),
                 font=self.fonts["total"])
            for key, text in a.items():
                if key not in ("name", "type"):
                    line(f"{key.replace('_', ' ').capitalize()}: {text}", "Muted.TLabel", (0, 2))
        return row

    def _changed(self, i: int):
        """A player's scoring changed: its totals, the Estimate saved, and the matrix's difficulty colours."""
        self.primaries[i].refresh()
        goes_first = self.goes_first.get()
        self.store.put(*self.pair, goes_first, self.names, self.scores[goes_first])
        self.cogitator.show_difficulty()
