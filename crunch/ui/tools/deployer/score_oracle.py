"""Score Oracle: a floating window next to the Deployer holding the game's score sheet.

One per Deployer: opening it again brings it to the front; it closes with the Deployer.

The sheet puts the two players face to face: a header (players, the WTC result and the VP), then one
grid per player, side by side, with a cell per battle round: went first, the primary mission, the
secondary missions (rows added as they are drawn), Battle Ready, and CP remaining. Scores are kept
in crunch.deploy.scoring.PlayerScore objects (totals, caps, WTC)."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.deploy.scoring import (BATTLE_READY, PRIMARY_MAX, ROUNDS, SECONDARY_MAX, PlayerScore, SecondaryRow,
                                   wtc)
from crunch.ui.theme import C, font_family

if TYPE_CHECKING:
    from crunch.ui.tools.deployer.window import DeployerWindow

ROLES = ("attacker", "defender")
CELL_BG, CELL_DONE = "#ffffff", "#e9e6df"          # empty cell, cell with a value
WIN_INK, LOSE_INK = "#2f7d32", C["muted"]


class ScoreOracle(tk.Toplevel):
    def __init__(self, deployer: "DeployerWindow"):
        super().__init__(deployer)
        self.deployer = deployer
        self.title("Game Crunch — Score Oracle")
        self.configure(bg=C["bg"])
        self.geometry("900x820")
        self.minsize(760, 560)
        self.transient(deployer)                   # floats above the Deployer, both usable
        fam = font_family()
        self.fonts = {"score": (fam, 30, "bold"), "name": (fam, 13, "bold"), "result": (fam, 12, "bold"),
                      "cell": (fam, 10), "total": (fam, 10, "bold")}
        self.scores = {role: PlayerScore(name=role.title()) for role in ROLES}
        self.cells: dict[str, dict] = {role: {} for role in ROLES}
        self.primary_names = {role: "Primary mission" for role in ROLES}

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self._build_header(body).pack(fill="x")
        grids = ttk.Frame(body)
        grids.pack(fill="both", expand=True, pady=(8, 0))
        for c in range(2):
            grids.columnconfigure(c, weight=1, uniform="players")
        grids.rowconfigure(0, weight=1)
        self.grids = {}
        for c, role in enumerate(ROLES):                  # face to face: attacker left, defender right
            g = ttk.Frame(grids, style="Panel.TFrame", padding=10)
            g.grid(row=0, column=c, sticky="nsew", padx=(0, 5) if c == 0 else (5, 0))
            self.grids[role] = g
            self._build_player(role)
        self.footer = ttk.Label(body, text="", style="Muted.TLabel", wraplength=860, justify="left")
        self.footer.pack(anchor="w", pady=(6, 0))
        self.refresh()

    # ---------------------------------------------------------------- header
    def _build_header(self, parent) -> ttk.Frame:
        h = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 10))
        for c in (0, 2):
            h.columnconfigure(c, weight=1, uniform="sides")
        ttk.Label(h, text=date.today().strftime("%B %d, %Y"), style="Muted.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.name_vars, self.side_labels = {}, {}
        for col, role, anchor in ((0, "attacker", "w"), (2, "defender", "e")):
            f = ttk.Frame(h, style="Flat.TFrame")
            f.grid(row=1, column=col, sticky=anchor)
            v = tk.StringVar(value=self.scores[role].name)
            v.trace_add("write", lambda *a, r=role: self._on_name(r))
            e = tk.Entry(f, textvariable=v, font=self.fonts["name"], relief="flat", bg=C["panel"],
                         fg=C["att"] if role == "attacker" else C["def"], width=16,
                         justify="left" if anchor == "w" else "right", highlightthickness=0)
            e.pack(anchor=anchor)
            self.name_vars[role] = v
            lb = ttk.Label(f, text="", style="Panel.TLabel", justify="left" if anchor == "w" else "right")
            lb.pack(anchor=anchor)
            self.side_labels[role] = lb
        mid = ttk.Frame(h, style="Flat.TFrame")
        mid.grid(row=1, column=1, padx=20)
        self.score_lbl = tk.Label(mid, text="", font=self.fonts["score"], bg=C["panel"], fg=C["ink"])
        self.score_lbl.pack()
        self.result_lbl = tk.Label(mid, text="", font=self.fonts["result"], bg=C["panel"])
        self.result_lbl.pack()
        self.points_lbl = ttk.Label(mid, text="", style="Muted.TLabel")
        self.points_lbl.pack()
        return h

    # ---------------------------------------------------------------- one player's grid
    def _build_player(self, role: str):
        g = self.grids[role]
        for w in g.winfo_children():
            w.destroy()
        for i in range(g.grid_size()[1] + 1):                 # earlier builds' spacer rows: back to normal
            g.rowconfigure(i, weight=0)
        s = self.scores[role]
        g.columnconfigure(0, weight=1)
        ttk.Label(g, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").grid(
            row=0, column=0, sticky="w")
        for r in range(ROUNDS):                                 # round numbers
            ttk.Label(g, text=str(r + 1), style="Muted.TLabel").grid(row=0, column=1 + r)
        row = 1

        # went first: one tick, for one player
        ttk.Label(g, text="Went first", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 2))
        v = tk.BooleanVar(value=s.went_first)
        ttk.Checkbutton(g, variable=v, style="Panel.TCheckbutton",
                        command=lambda r=role, v=v: self._on_went_first(r, v.get())).grid(
            row=row, column=1, columnspan=ROUNDS, sticky="w", pady=(6, 2))
        self.cells[role]["went_first"] = v
        row += 1

        # primary mission
        self.cells[role]["primary_label"] = ttk.Label(g, text=self.primary_names[role], style="Panel.TLabel",
                                                      wraplength=200, justify="left")
        self.cells[role]["primary_label"].grid(row=row, column=0, sticky="w", pady=(8, 2))
        self._round_cells(g, row, s.primary, pady=(8, 2))
        self.cells[role]["primary_total"] = ttk.Label(g, text="", style="Panel.TLabel", font=self.fonts["total"])
        self.cells[role]["primary_total"].grid(row=row, column=1 + ROUNDS, padx=(6, 0), pady=(8, 2))
        row += 1

        # secondary missions: a row per mission drawn
        first_secondary = row
        names = [m["name"].title() for m in self.deployer.ctx.missions.secondary_missions]
        for i, sec in enumerate(s.secondaries):
            pady = (8, 1) if i == 0 else 1
            cell = ttk.Frame(g, style="Flat.TFrame")
            cell.grid(row=row, column=0, sticky="ew", pady=pady)
            nv = tk.StringVar(value=sec.name)
            nv.trace_add("write", lambda *a, sec=sec, nv=nv: setattr(sec, "name", nv.get()))
            ttk.Combobox(cell, textvariable=nv, values=names, width=20).pack(side="left", fill="x", expand=True)
            x = tk.Label(cell, text="✕", bg=C["panel"], fg=C["muted"], cursor="hand2", padx=4)
            x.pack(side="left")
            x.bind("<Button-1>", lambda e, r=role, i=i: self._remove_secondary(r, i))
            self._round_cells(g, row, sec.rounds, pady=pady)
            row += 1
        ttk.Button(g, text="+ Secondary", command=lambda r=role: self._add_secondary(r)).grid(
            row=row, column=0, sticky="w", pady=(4 if s.secondaries else 8, 2))
        self.cells[role]["secondary_total"] = ttk.Label(g, text="", style="Panel.TLabel", font=self.fonts["total"])
        self.cells[role]["secondary_total"].grid(row=first_secondary, column=1 + ROUNDS, rowspan=row - first_secondary + 1,
                                                 padx=(6, 0))
        row += 1

        # Battle Ready
        ttk.Label(g, text="Battle Ready", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 2))
        br = tk.BooleanVar(value=s.battle_ready)
        ttk.Checkbutton(g, variable=br, style="Panel.TCheckbutton",
                        command=lambda s=s, br=br: (setattr(s, "battle_ready", br.get()), self.update_totals())).grid(
            row=row, column=1, columnspan=ROUNDS, sticky="w", pady=(10, 2))
        self.cells[role]["battle_ready_total"] = ttk.Label(g, text="", style="Panel.TLabel", font=self.fonts["total"])
        self.cells[role]["battle_ready_total"].grid(row=row, column=1 + ROUNDS, padx=(6, 0), pady=(10, 2))
        row += 1

        # CP remaining
        ttk.Label(g, text="CP remaining", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 2))
        self._round_cells(g, row, s.cp, pady=(8, 2), counts=False)
        row += 1
        ttk.Frame(g, style="Flat.TFrame").grid(row=row, column=0)
        g.rowconfigure(row, weight=1)                          # space below, not between the rows
        self.update_totals()

    def _round_cells(self, g, row: int, values: list[str], pady, counts: bool = True):
        """A cell per battle round, editing `values` in place: a number, "-" or nothing."""
        for r in range(ROUNDS):
            v = tk.StringVar(value=values[r])
            e = tk.Entry(g, textvariable=v, width=3, justify="center", font=self.fonts["cell"], relief="flat",
                         highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["ink"],
                         bg=CELL_DONE if values[r] else CELL_BG)
            e.grid(row=row, column=1 + r, padx=1, pady=pady, ipady=2)
            v.trace_add("write", lambda *a, v=v, e=e, r=r: self._on_cell(values, r, v, e, counts))

    # ---------------------------------------------------------------- edits
    def _on_cell(self, values: list[str], r: int, v: tk.StringVar, e: tk.Entry, counts: bool):
        text = v.get().strip()
        ok = text in ("", "-") or text.isdigit()
        e.configure(bg=CELL_BG if not text else (CELL_DONE if ok else "#f6d4d4"))   # red: not a number
        values[r] = text if ok else ""
        if counts:
            self.update_totals()

    def _on_name(self, role: str):
        self.scores[role].name = self.name_vars[role].get()
        self.update_totals()

    def _on_went_first(self, role: str, on: bool):
        self.scores[role].went_first = on
        if on:                                                # only one player goes first
            other = "defender" if role == "attacker" else "attacker"
            self.scores[other].went_first = False
            self.cells[other]["went_first"].set(False)

    def _add_secondary(self, role: str):
        self.scores[role].secondaries.append(SecondaryRow())
        self._build_player(role)

    def _remove_secondary(self, role: str, i: int):
        del self.scores[role].secondaries[i]
        self._build_player(role)

    # ---------------------------------------------------------------- totals and the result
    def update_totals(self):
        for role in ROLES:
            s, c = self.scores[role], self.cells[role]
            if "primary_total" in c:
                c["primary_total"].configure(text=f"{s.primary_total}/{PRIMARY_MAX}")
                c["secondary_total"].configure(text=f"{s.secondary_total}/{SECONDARY_MAX}")
                c["battle_ready_total"].configure(text=f"{BATTLE_READY if s.battle_ready else 0}/{BATTLE_READY}")
        a, d = self.scores["attacker"], self.scores["defender"]
        wa, wd = wtc(a.total, d.total)
        self.score_lbl.configure(text=f"{wa} - {wd}")
        if a.total == d.total:
            self.result_lbl.configure(text="DRAW", fg=LOSE_INK)
        else:
            winner = a if a.total > d.total else d
            self.result_lbl.configure(text=f"{(winner.name or 'Winner').upper()} WINS", fg=WIN_INK)
        self.points_lbl.configure(text=f"WTC  ·  Points: {a.total} - {d.total}")

    def refresh(self):
        """Armies, dispositions and primary missions, as the Deployer shows them."""
        d = self.deployer
        armies = {"attacker": d.selection.attacker, "defender": d.selection.defender}
        fd = {role: d.side.disposition(role) for role in ROLES}
        book = d.ctx.missions
        primaries = {}
        for role, other in (("attacker", "defender"), ("defender", "attacker")):
            army = armies[role]
            mission = book.primary_mission(fd[role], fd[other]) if fd[role] and fd[other] else None
            primaries[role] = mission["name"].title() if mission else "Primary mission"
            self.primary_names[role] = primaries[role]
            self.side_labels[role].configure(
                text=f"{army.faction or army.path.stem}\n{fd[role] or 'No Force Disposition'}")
            if "primary_label" in self.cells[role]:
                self.cells[role]["primary_label"].configure(text=primaries[role])
        layouts = book.layouts_for(fd["attacker"], fd["defender"]) if all(fd.values()) else []
        self.footer.configure(text="Warhammer 40,000 11th edition  ·  "
                                   + (f"{fd['attacker']} vs {fd['defender']}  ·  " if all(fd.values()) else "")
                                   + f"{primaries['attacker']} / {primaries['defender']}"
                                   + (f"  ·  layouts {', '.join(l['id'] for l in layouts)}" if layouts else ""))
        self.update_totals()
