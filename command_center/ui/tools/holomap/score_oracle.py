"""Score Oracle: a floating window next to the Field Holomap holding the game's score sheet.

One per Field Holomap: opening it again brings it to the front; it closes with the Field Holomap.

The sheet puts the two players face to face: a header (players, the WTC result and the VP), then one
grid per player, side by side, with a column per battle round and one for the end of the battle: went
first, Battle Ready, the primary mission, the secondary missions (a row per mission, drawn at random
among those the player hasn't had yet, scored from a drop-down per round), and the CP (gained, used,
remaining). The primary mission has a row per scoring option of its card (command_center.ui.views.scoresheet).
VP above a cap can still be entered: a "!" then shows on the round's total (15 VP a round) or at the
end of the secondary mission's row (5 VP a mission). Scores are kept in
command_center.deploy.scoring.PlayerScore objects (totals, caps, WTC).

"Import Estimate" fills the two primary missions from the Disposition Cogitator's saved Estimate of
the game's pairing, the one with the player ticked "Went first" going first (command_center.deploy.estimates).
The circle next to it has that Estimate's difficulty colour, as on the Cogitator's matrix, from the
attacker's point of view; it is white when there is no such Estimate, or nobody is ticked yet."""
from __future__ import annotations

import random
import tkinter as tk
from datetime import date
from string import capwords
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.deploy.estimates import difficulty, game_estimate
from command_center.deploy.scoring import (BATTLE_READY, COLUMNS, PRIMARY_MAX, ROUND_MAX, ROUNDS, SECONDARY_CELLS,
                                           SECONDARY_MAX, SECONDARY_MISSION_MAX, PlayerScore, SecondaryRow,
                                           primary_options, wtc)
from command_center.ui.theme import DIFFICULTY_COLORS, NO_ESTIMATE, C, font_family
from command_center.ui.views.scoresheet import (CELL_DONE, OVER_INK, FaceToFace, PrimaryRows, column_headers,
                                                sheet_fonts, show_vp, summary_row)

if TYPE_CHECKING:
    from command_center.ui.tools.holomap.window import HolomapWindow

ROLES = ("attacker", "defender")
WIN_INK, LOSE_INK = "#2f7d32", C["muted"]


class ScoreOracle(tk.Toplevel):
    def __init__(self, holomap: "HolomapWindow"):
        super().__init__(holomap)
        self.holomap = holomap
        self.title("Command Center 40K — Score Oracle")
        self.configure(bg=C["bg"])
        self.geometry("1240x860")
        self.minsize(1000, 560)
        self.transient(holomap)                   # floats above the Field Holomap, both usable
        fam = font_family()
        self.fonts = {"score": (fam, 30, "bold"), "name": (fam, 13, "bold"), "result": (fam, 12, "bold"),
                      **sheet_fonts()}
        self.scores = {role: PlayerScore(name=role.title()) for role in ROLES}
        self.cells: dict[str, dict] = {role: {} for role in ROLES}
        self.primary_names = {role: "Primary mission" for role in ROLES}

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self._build_header(body).pack(fill="x")
        self.footer = ttk.Label(body, text="", style="Muted.TLabel", wraplength=1200, justify="left")
        self.footer.pack(side="bottom", anchor="w", pady=(6, 0))
        self.faces = FaceToFace(body)                     # face to face: attacker left, defender right
        self.faces.pack(fill="both", expand=True, pady=(8, 0))
        for role in ROLES:
            self._build_player(role)
        self.refresh()

    # ---------------------------------------------------------------- header
    def _build_header(self, parent) -> ttk.Frame:
        h = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 10))
        for c in (0, 2):
            h.columnconfigure(c, weight=1, uniform="sides")
        ttk.Label(h, text=date.today().strftime("%B %d, %Y"), style="Muted.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        imp = ttk.Frame(h, style="Flat.TFrame")                # the Cogitator's Estimate of this game, on demand
        imp.grid(row=0, column=1, columnspan=2, sticky="e")
        self.import_note = ttk.Label(imp, text="", style="Muted.TLabel")
        self.import_note.pack(side="left", padx=(0, 8))
        ttk.Button(imp, text="Import Estimate", command=self.import_estimate).pack(side="left")
        self.estimate_dot = tk.Canvas(imp, width=16, height=16, bg=C["panel"], highlightthickness=0)
        self.estimate_dot.create_oval(2, 2, 14, 14, fill=NO_ESTIMATE, outline=C["muted"], tags="dot")
        self.estimate_dot.pack(side="left", padx=(6, 0))
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
        side = ROLES.index(role)
        g = self.faces.clear(side)
        s = self.scores[role]
        ttk.Label(g, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").grid(
            row=0, column=0, sticky="w")
        column_headers(g)
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
        primary = self.cells[role]["primary"] = PrimaryRows(g, row, s, self.primary_names[role], self.fonts,
                                                            self.update_totals)
        self.faces.wide[side] += primary.wide
        self.faces.beside[side] += primary.beside
        row = primary.next_row

        # secondary missions: the VP counted per round, then a row per mission drawn ("!": over its cap)
        lb, self.cells[role]["secondary_rounds"], self.cells[role]["secondary_total"] = summary_row(
            g, row, "Secondary missions", ROUNDS, self.fonts)
        self.faces.beside[side].append(lb)
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
            cb.bind("<MouseWheel>", self.faces.wheel)
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
        self.faces.wrap(side)

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
            cb.bind("<MouseWheel>", self.faces.wheel)
            boxes.append(cb)
        show()

    # ---------------------------------------------------------------- edits
    def _on_name(self, role: str):
        self.scores[role].name = self.name_vars[role].get()
        self.update_totals()

    def _on_went_first(self, role: str, on: bool):
        self.scores[role].went_first = on
        if on:                                                # only one player goes first
            other = "defender" if role == "attacker" else "attacker"
            self.scores[other].went_first = False
            self.cells[other]["went_first"].set(False)
        self.show_estimate()

    def show_estimate(self):
        """The circle by "Import Estimate": the difficulty colour of the Estimate that would be imported,
        for the attacker; white without one (none saved, or nobody ticked "Went first")."""
        d = self.holomap
        fd = {role: d.side.disposition(role) for role in ROLES}
        first = next((role for role in ROLES if self.scores[role].went_first), None)
        group = None
        if first and all(fd.values()):
            groups = difficulty(d.ctx.missions, d.ctx.estimates)
            group = groups.get((fd["attacker"], fd["defender"], first == "attacker"))
        self.estimate_dot.itemconfigure("dot", fill=NO_ESTIMATE if group is None else DIFFICULTY_COLORS[group])

    def import_estimate(self):
        """Fill the two primary missions from the Cogitator's saved Estimate of this game: its pairing of
        Force Dispositions, with the player ticked "Went first" going first. What was scored on the
        primaries is replaced; the note next to the button says what was done, or what is missing."""
        d = self.holomap
        fd = {role: d.side.disposition(role) for role in ROLES}
        first = next((role for role in ROLES if self.scores[role].went_first), None)
        if not all(fd.values()):
            return self.import_note.configure(text="Both lists need a Force Disposition")
        if first is None:
            return self.import_note.configure(text="Tick who went first, then import")
        p1, p2, goes_first, attacker_is_p1 = game_estimate(d.ctx.missions.dispositions, fd["attacker"],
                                                          fd["defender"], first == "attacker")
        roles = ROLES if attacker_is_p1 else ROLES[::-1]        # the roles of Player 1 and Player 2
        label = f"{p1} vs {p2}, Player {goes_first + 1} ({roles[goes_first]}) first"
        if not d.ctx.estimates.load(p1, p2, goes_first, [self.primary_names[r] for r in roles],
                                    [self.scores[r] for r in roles]):
            return self.import_note.configure(text=f"No Estimate saved for {label}")
        for role in ROLES:
            self._build_player(role)
        self.import_note.configure(text=f"Imported: {label}")

    def _secondary_names(self) -> list[str]:
        return [capwords(m["name"]) for m in self.holomap.ctx.missions.secondary_missions]

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
            if "cp_remaining" in c:                             # its grid is built
                c["primary"].refresh()
                for r, lb in enumerate(c["secondary_rounds"]):
                    show_vp(lb, s.secondary_vp(r), s.secondary_over(r))
                for sec, mark in c["secondary_marks"]:
                    mark.configure(text="!" if sec.over else "")
                for r, lb in enumerate(c["cp_remaining"]):      # up to the last round played
                    left = s.cp_remaining(r)
                    lb.configure(text=left if s.cp_played(r) else "", fg=C["att"] if left < 0 else C["ink"])
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
        """Armies, dispositions and primary missions, as the Field Holomap shows them."""
        d = self.holomap
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
        self.show_estimate()
