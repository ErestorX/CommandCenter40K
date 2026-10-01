"""Score Oracle: a floating window next to the Deployer for the game's score sheet.

One per Deployer: opening it again brings it to the front; it closes with the Deployer. The score
sheet itself goes in `self.sheet` (to be designed)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.ui.theme import C

if TYPE_CHECKING:
    from crunch.ui.tools.deployer.window import DeployerWindow

ROLES = ("attacker", "defender")


class ScoreOracle(tk.Toplevel):
    def __init__(self, deployer: "DeployerWindow"):
        super().__init__(deployer)
        self.deployer = deployer
        self.title("Game Crunch — Score Oracle")
        self.configure(bg=C["bg"])
        self.geometry("620x720")
        self.minsize(420, 400)
        self.transient(deployer)                   # floats above the Deployer, both usable

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Score Oracle", style="H1.TLabel").pack(anchor="w")

        players = ttk.Frame(body, style="Panel.TFrame", padding=10)
        players.pack(fill="x", pady=(8, 8))
        for c in range(2):
            players.columnconfigure(c, weight=1, uniform="players")
        self.player_labels: dict[str, ttk.Label] = {}
        for c, role in enumerate(ROLES):
            col = ttk.Frame(players, style="Flat.TFrame")
            col.grid(row=0, column=c, sticky="nsew", padx=(0, 6) if c == 0 else (6, 0))
            ttk.Label(col, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").pack(
                anchor="w")
            self.player_labels[role] = ttk.Label(col, text="", style="Panel.TLabel", justify="left",
                                                 wraplength=270)
            self.player_labels[role].pack(anchor="w")

        # the score sheet, to be designed
        self.sheet = ttk.Frame(body, style="Panel.TFrame", padding=10)
        self.sheet.pack(fill="both", expand=True)
        ttk.Label(self.sheet, text="Score sheet", style="H2.TLabel").pack(anchor="w")
        ttk.Label(self.sheet, text="To be designed.", style="Muted.TLabel").pack(anchor="w")
        self.refresh()

    def refresh(self):
        """Armies, dispositions and primary missions, as chosen in the Deployer."""
        d = self.deployer
        armies = {"attacker": d.selection.attacker, "defender": d.selection.defender}
        fd = {role: d.side.disposition(role) for role in ROLES}
        book = d.ctx.missions
        for role, other in (("attacker", "defender"), ("defender", "attacker")):
            army = armies[role]
            mission = book.primary_mission(fd[role], fd[other]) if fd[role] and fd[other] else None
            lines = [f"{army.faction or army.path.stem}  ·  {army.points} pts",
                     fd[role] or "no Force Disposition chosen",
                     f"Primary: {mission['name'].title()}" if mission else "Primary: -"]
            self.player_labels[role].configure(text="\n".join(lines))
