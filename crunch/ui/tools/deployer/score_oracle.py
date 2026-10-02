"""Score Oracle: a floating window next to the Deployer holding the game's score sheet.

One per Deployer: opening it again brings it to the front; it closes with the Deployer.

The sheet puts the two players face to face: a header (players, the WTC result and the VP), then one
grid per player, side by side, with a column per battle round and one for the end of the battle: went
first, Battle Ready, the primary mission, the secondary missions (a row per mission, drawn at random
among those the player hasn't had yet, scored from a drop-down per round), and the CP (gained, used, remaining). The primary mission has a row per scoring option of its card: a tick box where it is
scored once, a - n + counter where it is scored "for each ...". VP above a cap can still be entered:
a "!" then shows on the round's total (15 VP a round) or at the end of the secondary mission's row
(5 VP a mission). Scores are kept in crunch.deploy.scoring.PlayerScore objects (totals, caps, WTC)."""
from __future__ import annotations

import random
import tkinter as tk
from datetime import date
from string import capwords
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.deploy.scoring import (BATTLE_READY, COLUMNS, END, PRIMARY_MAX, ROUND_MAX, ROUNDS, SECONDARY_CELLS,
                                   SECONDARY_MAX, SECONDARY_MISSION_MAX, PlayerScore, SecondaryRow, primary_options,
                                   wtc)
from crunch.ui.theme import C, font_family

if TYPE_CHECKING:
    from crunch.ui.tools.deployer.window import DeployerWindow

ROLES = ("attacker", "defender")
CELL_BG, CELL_DONE = "#ffffff", "#e9e6df"          # empty cell, cell with a value
CELL_BAD = "#f6d4d4"                               # not a number
OVER_INK = "#b26a00"                               # VP lost to a cap
WIN_INK, LOSE_INK = "#2f7d32", C["muted"]


class ScoreOracle(tk.Toplevel):
    def __init__(self, deployer: "DeployerWindow"):
        super().__init__(deployer)
        self.deployer = deployer
        self.title("Game Crunch — Score Oracle")
        self.configure(bg=C["bg"])
        self.geometry("1240x860")
        self.minsize(1000, 560)
        self.transient(deployer)                   # floats above the Deployer, both usable
        fam = font_family()
        self.fonts = {"score": (fam, 30, "bold"), "name": (fam, 13, "bold"), "result": (fam, 12, "bold"),
                      "cell": (fam, 10), "total": (fam, 10, "bold"), "small": (fam, 9)}
        self.scores = {role: PlayerScore(name=role.title()) for role in ROLES}
        self.cells: dict[str, dict] = {role: {} for role in ROLES}
        self.primary_names = {role: "Primary mission" for role in ROLES}

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self._build_header(body).pack(fill="x")
        self.footer = ttk.Label(body, text="", style="Muted.TLabel", wraplength=1200, justify="left")
        self.footer.pack(side="bottom", anchor="w", pady=(6, 0))
        # the two grids scroll together when they are taller than the window
        area = ttk.Frame(body)
        area.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Scrollbar(area, orient="vertical")
        bar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(area, bg=C["bg"], highlightthickness=0, yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.configure(command=self.canvas.yview)
        grids = self.sheet = ttk.Frame(self.canvas)
        self.sheet_id = self.canvas.create_window(0, 0, window=grids, anchor="nw")
        self.canvas.bind("<Configure>", self._resized)
        grids.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=(0, 0, e.width, e.height)))
        self.bind("<MouseWheel>", self._wheel)
        for c in range(2):
            grids.columnconfigure(c, weight=1, uniform="players")
        grids.rowconfigure(0, weight=1)
        self.grids = {}
        for c, role in enumerate(ROLES):                  # face to face: attacker left, defender right
            g = ttk.Frame(grids, style="Panel.TFrame", padding=10)
            g.grid(row=0, column=c, sticky="nsew", padx=(0, 5) if c == 0 else (5, 0))
            self.grids[role] = g
            self._build_player(role)
        self.refresh()

    def _wheel(self, e):
        """The wheel scrolls the sheet, wherever the pointer is: never the value of a drop-down under it."""
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _resized(self, e):
        """The sheet is as wide as the scrolling area, and at least as tall; its texts wrap to that width."""
        self.canvas.itemconfigure(self.sheet_id, width=e.width)
        self.sheet.rowconfigure(0, minsize=e.height)
        for role in ROLES:
            self._wrap(role)

    def _wrap(self, role: str):
        """Texts wrap at the width their grid leaves them. That width comes from the scrolling area's,
        not from the grid's own: the grid's depends on its texts, and the two would chase each other."""
        g, c = self.grids[role], self.cells[role]
        full = (self.canvas.winfo_width() - 10) // 2 - 26     # half the sheet, less the gap, border and padding
        if full < 100:                                        # not laid out yet
            return
        beside = full - g.grid_bbox(1, 0, 1 + COLUMNS, 0)[2] - 10     # left of the round columns
        for lb in c.get("wide", []):
            lb.configure(wraplength=full)
        for lb in c.get("beside", []):
            lb.configure(wraplength=max(120, beside))

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
        for col in range(COLUMNS):                              # round numbers, then the end of the battle
            ttk.Label(g, text="End" if col == END else str(col + 1), style="Muted.TLabel").grid(row=0, column=1 + col)
        self.cells[role].update(wide=[], beside=[])
        row = 1

        # went first: one tick, for one player
        ttk.Label(g, text="Went first", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 2))
        v = tk.BooleanVar(value=s.went_first)
        ttk.Checkbutton(g, variable=v, style="Panel.TCheckbutton",
                        command=lambda r=role, v=v: self._on_went_first(r, v.get())).grid(
            row=row, column=1, columnspan=ROUNDS, sticky="w", pady=(6, 2))
        self.cells[role]["went_first"] = v
        row += 1

        # Battle Ready
        ttk.Label(g, text="Battle Ready", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=2)
        br = tk.BooleanVar(value=s.battle_ready)
        ttk.Checkbutton(g, variable=br, style="Panel.TCheckbutton",
                        command=lambda s=s, br=br: (setattr(s, "battle_ready", br.get()), self.update_totals())).grid(
            row=row, column=1, columnspan=ROUNDS, sticky="w", pady=2)
        self.cells[role]["battle_ready_total"] = ttk.Label(g, text="", style="Panel.TLabel", font=self.fonts["total"])
        self.cells[role]["battle_ready_total"].grid(row=row, column=1 + COLUMNS, padx=(6, 0), pady=2)
        row += 1

        # primary mission: the VP counted per column, then a row per scoring option
        self._summary_row(g, row, role, "primary", self.primary_names[role], COLUMNS)
        row = self._primary_rows(g, row + 1, role)

        # secondary missions: the VP counted per round, then a row per mission drawn ("!": over its cap)
        self._summary_row(g, row, role, "secondary", "Secondary missions", ROUNDS)
        row += 1
        self.cells[role]["secondary_marks"] = []
        names = self._secondary_names()
        for i, sec in enumerate(s.secondaries):
            cell = ttk.Frame(g, style="Flat.TFrame")
            cell.grid(row=row, column=0, sticky="ew", pady=1)
            nv = tk.StringVar(value=sec.name)
            nv.trace_add("write", lambda *a, sec=sec, nv=nv: setattr(sec, "name", nv.get()))
            cb = ttk.Combobox(cell, textvariable=nv, width=20, state="readonly" if names else "normal",
                              style="Sheet.TCombobox")
            # the missions on the player's other rows are left out of the list
            cb.configure(postcommand=lambda cb=cb, sec=sec: cb.configure(values=s.unused_secondaries(names, sec)))
            cb.bind("<MouseWheel>", self._wheel)
            cb.pack(side="left", fill="x", expand=True)
            x = tk.Label(cell, text="✕", bg=C["panel"], fg=C["muted"], cursor="hand2", padx=4)
            x.pack(side="left")
            x.bind("<Button-1>", lambda e, r=role, i=i: self._remove_secondary(r, i))
            self._secondary_cells(g, row, sec)
            mark = tk.Label(g, text="", font=self.fonts["total"], bg=C["panel"], fg=OVER_INK)
            mark.grid(row=row, column=1 + COLUMNS, padx=(6, 0))
            self.cells[role]["secondary_marks"].append((sec, mark))
            row += 1
        ttk.Button(g, text="+ Secondary", command=lambda r=role: self._add_secondary(r)).grid(
            row=row, column=0, sticky="w", pady=(4, 2))
        row += 1

        # CP: gained and used, counted per round, and what remains
        for title, values in (("CP gained", s.cp_gained), ("CP used", s.cp_spent)):
            pady = (10, 1) if values is s.cp_gained else 1
            ttk.Label(g, text=title, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=pady)
            for r in range(ROUNDS):
                self._cp_counter(g, values, r).grid(row=row, column=1 + r, padx=4, pady=pady)
            row += 1
        ttk.Label(g, text="Remaining CP", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(1, 2))
        self.cells[role]["cp_remaining"] = []
        for r in range(ROUNDS):
            t = tk.Label(g, text="", font=self.fonts["total"], bg=C["panel"], fg=C["ink"], width=3)
            t.grid(row=row, column=1 + r, pady=(1, 2))
            self.cells[role]["cp_remaining"].append(t)
        row += 1
        ttk.Frame(g, style="Flat.TFrame").grid(row=row, column=0)
        g.rowconfigure(row, weight=1)                          # space below, not between the rows
        self.update_totals()
        self._wrap(role)

    def _summary_row(self, g, row: int, role: str, key: str, title: str, n: int):
        """A section's heading: its name, the VP counted in each column ("!": more were scored than the
        round's cap), its total."""
        lb = ttk.Label(g, text=title, style="Panel.TLabel", font=self.fonts["total"], wraplength=220, justify="left")
        lb.grid(row=row, column=0, sticky="w", pady=(10, 2))
        self.cells[role]["beside"].append(lb)
        self.cells[role][f"{key}_rounds"] = []
        for col in range(n):
            t = tk.Label(g, text="", font=self.fonts["total"], bg=C["panel"], fg=C["ink"], width=3)
            t.grid(row=row, column=1 + col, pady=(10, 2))
            self.cells[role][f"{key}_rounds"].append(t)
        self.cells[role][f"{key}_total"] = ttk.Label(g, text="", style="Panel.TLabel", font=self.fonts["total"])
        self.cells[role][f"{key}_total"].grid(row=row, column=1 + COLUMNS, padx=(6, 0), pady=(10, 2))

    def _primary_rows(self, g, row: int, role: str) -> int:
        """A row per scoring option of the primary mission, under its block's heading; a row of VP cells
        when the mission isn't known. Returns the next free row."""
        s, c = self.scores[role], self.cells[role]
        c["counts"] = {}
        if not s.options:
            ttk.Label(g, text="VP scored", style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=1)
            self._round_cells(g, row, s.primary, pady=1)
            return row + 1
        block = None
        for i, opt in enumerate(s.options):
            if opt.block != block:                              # "Second battle round onwards · End of your turn."
                block = opt.block
                head = ttk.Label(g, text="  ·  ".join(t for t in (opt.round.capitalize(), opt.when) if t),
                                 style="Muted.TLabel", wraplength=400, justify="left")
                head.grid(row=row, column=0, columnspan=2 + COLUMNS, sticky="w", pady=(5, 0))
                c["wide"].append(head)
                row += 1
            text = f"{'or ' if opt.group != i else ''}{'+' if opt.additional else ''}{opt.vp}VP  {opt.text}"
            lb = tk.Label(g, text=text, font=self.fonts["small"], bg=C["panel"], fg=C["ink"], wraplength=220,
                          justify="left", anchor="w")
            lb.grid(row=row, column=0, sticky="w", padx=(8, 0), pady=1)
            c["beside"].append(lb)
            for col in opt.columns:
                v = c["counts"][i, col] = tk.IntVar(value=s.counts[i][col])
                if opt.tick:
                    w = ttk.Checkbutton(g, variable=v, style="Panel.TCheckbutton",
                                        command=lambda i=i, col=col, v=v: self._score(role, i, col, v.get()))
                else:
                    w = self._counter(g, role, i, col, v)
                w.grid(row=row, column=1 + col, padx=1 if opt.tick else 4, pady=1)
            row += 1
        return row

    def _counter(self, g, role: str, i: int, col: int, v: tk.IntVar) -> tk.Frame:
        """- n +: how many times an option is scored in a column."""
        f = tk.Frame(g, bg=C["panel"])
        for text, step in (("−", -1), ("", 0), ("+", 1)):
            if not step:
                tk.Label(f, textvariable=v, width=2, font=self.fonts["cell"], bg=C["panel"], fg=C["ink"]).pack(
                    side="left")
                continue
            b = tk.Label(f, text=text, font=self.fonts["total"], bg=CELL_DONE, fg=C["ink"], cursor="hand2", padx=3)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, step=step: self._score(role, i, col, v.get() + step))
        return f

    def _cp_counter(self, g, values: list[int], r: int) -> tk.Frame:
        """- n +: CP gained (or used) in a round."""
        f = tk.Frame(g, bg=C["panel"])

        def step(by: int):
            values[r] = max(0, values[r] + by)
            n.configure(text=values[r])
            self.update_totals()
        for text, by in (("−", -1), ("+", 1)):
            b = tk.Label(f, text=text, font=self.fonts["total"], bg=CELL_DONE, fg=C["ink"], cursor="hand2", padx=3)
            b.pack(side="left" if by < 0 else "right")
            b.bind("<Button-1>", lambda e, by=by: step(by))
        n = tk.Label(f, text=values[r], width=2, font=self.fonts["cell"], bg=C["panel"], fg=C["ink"])
        n.pack(side="left")
        return f

    def _secondary_cells(self, g, row: int, sec: SecondaryRow):
        """A drop-down per battle round: nothing, "-" (not active), the VP scored, or "x" (discarded).
        Once the mission is scored or discarded, the row's other cells are locked."""
        boxes: list[ttk.Combobox] = []

        def show():
            for r, cb in enumerate(boxes):
                cb.set(sec.rounds[r])
                cb.configure(state="readonly" if sec.closed in (None, r) else "disabled")

        def pick(r: int):
            sec.set(r, boxes[r].get().strip())
            boxes[r].selection_clear()
            show()
            self.update_totals()
        for r in range(ROUNDS):
            cb = ttk.Combobox(g, values=SECONDARY_CELLS, width=2, justify="center", state="readonly",
                              style="Sheet.TCombobox")
            cb.grid(row=row, column=1 + r, padx=1, pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e, r=r: pick(r))
            cb.bind("<MouseWheel>", self._wheel)
            boxes.append(cb)
        show()

    def _round_cells(self, g, row: int, values: list[str], pady):
        """A cell per column of `values`, editing them in place: a number, "-" or nothing."""
        for r in range(len(values)):
            v = tk.StringVar(value=values[r])
            e = tk.Entry(g, textvariable=v, width=3, justify="center", font=self.fonts["cell"], relief="flat",
                         highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["ink"],
                         bg=self._cell_bg(values[r]))
            e.grid(row=row, column=1 + r, padx=1, pady=pady, ipady=2)
            v.trace_add("write", lambda *a, v=v, e=e, r=r: self._on_cell(values, r, v, e))

    @staticmethod
    def _cell_bg(text: str) -> str:
        if not text:
            return CELL_BG
        return CELL_DONE if text == "-" or text.isdigit() else CELL_BAD

    # ---------------------------------------------------------------- edits
    def _on_cell(self, values: list[str], r: int, v: tk.StringVar, e: tk.Entry):
        text = v.get().strip()
        bg = self._cell_bg(text)
        e.configure(bg=bg)
        values[r] = "" if bg == CELL_BAD else text
        self.update_totals()

    def _score(self, role: str, i: int, col: int, n: int):
        """A primary option is scored n times in a column; ticks and counters then show the sheet's state
        (scoring an option unticks its alternatives)."""
        s = self.scores[role]
        s.score(i, col, n)
        for (j, c), v in self.cells[role]["counts"].items():
            if c == col:
                v.set(s.counts[j][c])
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

    def _secondary_names(self) -> list[str]:
        return [capwords(m["name"]) for m in self.deployer.ctx.missions.secondary_missions]

    def _add_secondary(self, role: str):
        """A new row, with a mission drawn at random among those the player hasn't had yet."""
        s = self.scores[role]
        left = s.unused_secondaries(self._secondary_names())
        s.secondaries.append(SecondaryRow(random.choice(left) if left else ""))
        self._build_player(role)

    def _remove_secondary(self, role: str, i: int):
        del self.scores[role].secondaries[i]
        self._build_player(role)

    # ---------------------------------------------------------------- totals and the result
    def update_totals(self):
        for role in ROLES:
            s, c = self.scores[role], self.cells[role]
            if "primary_total" in c:
                for col, lb in enumerate(c["primary_rounds"]):
                    self._show_vp(lb, s.primary_vp(col), s.primary_over(col))
                for r, lb in enumerate(c["secondary_rounds"]):
                    self._show_vp(lb, s.secondary_vp(r), s.secondary_over(r))
                for sec, mark in c["secondary_marks"]:
                    mark.configure(text="!" if sec.over else "")
                for r, lb in enumerate(c["cp_remaining"]):      # up to the last round played
                    left = s.cp_remaining(r)
                    lb.configure(text=left if s.cp_played(r) else "", fg=C["att"] if left < 0 else C["ink"])
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

    @staticmethod
    def _show_vp(lb: tk.Label, points: int, over: bool):
        """The VP counted in a column; with a "!" when more were scored than the round's cap."""
        lb.configure(text=f"{points}!" if over else str(points) if points else "", fg=OVER_INK if over else C["ink"])

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
            primaries[role] = capwords(mission["name"]) if mission else "Primary mission"
            if primaries[role] != self.primary_names[role]:       # another mission: its own scoring options
                self.primary_names[role] = primaries[role]
                self.scores[role].set_options(primary_options(mission))
                self._build_player(role)
            self.side_labels[role].configure(
                text=f"{army.faction or army.path.stem}\n{fd[role] or 'No Force Disposition'}")
        layouts = book.layouts_for(fd["attacker"], fd["defender"]) if all(fd.values()) else []
        self.footer.configure(text="Warhammer 40,000 11th edition  ·  "
                                   + (f"{fd['attacker']} vs {fd['defender']}  ·  " if all(fd.values()) else "")
                                   + f"{primaries['attacker']} / {primaries['defender']}"
                                   + (f"  ·  layouts {', '.join(l['id'] for l in layouts)}" if layouts else "")
                                   + f"\n!  VP above a cap don't count: {ROUND_MAX} per battle round (primary,"
                                     f" secondary), {SECONDARY_MISSION_MAX} per secondary mission, {PRIMARY_MAX}"
                                     " over the game.")
        self.update_totals()
