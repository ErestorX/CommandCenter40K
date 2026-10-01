"""The Deployer: mission and deployment support. For the two armies' Force Dispositions it shows the
three battlefield layouts of the pairing (right two thirds), the primary mission each player plays
and a compact view of both armies (left third). Ticking a unit puts its base (or the ellipse of the
whole unit) on each map, at a random spot of its side's deployment zone, to be dragged around."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.ui.registry import Selection, register_tool
from crunch.ui.tools.deployer.map_view import LayoutMap, legend
from crunch.ui.tools.deployer.side_panel import ROLES, SidePanel
from crunch.ui.toolwindow import ToolWindow

if TYPE_CHECKING:
    from crunch.ui.app import App


class DeployerWindow(ToolWindow):
    title_text = "Deployer"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="thirds")
        body.columnconfigure(1, weight=2, uniform="thirds")
        body.rowconfigure(0, weight=1)
        self.side = SidePanel(body, self)
        self.side.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        maps = ttk.Frame(body)
        maps.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        for i in range(2):
            maps.columnconfigure(i, weight=1, uniform="maps")
            maps.rowconfigure(i, weight=1, uniform="maps")
        self.maps = [LayoutMap(maps) for _ in range(3)]
        self.selected: tuple[LayoutMap, str] | None = None     # the unit token later functions act on
        for i, m in enumerate(self.maps):
            m.grid(row=i // 2, column=i % 2, sticky="nsew", padx=3, pady=3)
            m.on_select = self._on_select
        self._build_info(maps).grid(row=1, column=1, sticky="nsew", padx=3, pady=3)
        self.refresh()

    def _build_info(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        self.pairing = ttk.Label(f, text="", style="H2.TLabel", wraplength=420, justify="left")
        self.pairing.pack(anchor="w")
        self.info = ttk.Label(f, text="", style="Muted.TLabel", wraplength=420, justify="left")
        self.info.pack(anchor="w", pady=(2, 8))
        self.measure = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Show table-setup measurements", variable=self.measure, style="Panel.TCheckbutton",
                        command=self._toggle_measurements).pack(anchor="w", pady=(0, 8))
        legend(f).pack(anchor="w")
        ttk.Label(f, text="Layouts: Event Companion, via rapidingress.com", style="Muted.TLabel").pack(
            side="bottom", anchor="w")
        return f

    def _on_select(self, source: LayoutMap, key: str | None):
        """One selection for the whole window: selecting on one map clears the others."""
        self.selected = (source, key) if key else None
        for m in self.maps:
            if m is not source:
                m.set_selected(None)
        self.side.show_selected(key.split(":", 1) if key else None)

    def toggle_unit(self, role: str, row, on: bool):
        """Put a roster row on every map (each at its own random spot in the side's zone), or take it off."""
        key = f"{role}:{row.key}"
        for m in self.maps:
            if on:
                m.add_token(key, role, row.name, row.footprint)
            else:
                m.remove_token(key)

    def _toggle_measurements(self):
        for m in self.maps:
            m.show_measurements = self.measure.get()
            m.draw()

    def refresh(self):
        book = self.ctx.missions
        armies = {"attacker": self.selection.attacker, "defender": self.selection.defender}
        fd = {role: self.side.disposition(role) for role in ROLES}
        both = all(fd.values())
        name = {role: armies[role].faction or armies[role].path.stem for role in ROLES}
        if both and fd["attacker"] == fd["defender"]:     # mirror: both players play the same mission
            cards = [("both", f"{name['attacker']} & {name['defender']}",
                      book.primary_mission(fd["attacker"], fd["defender"]))]
        else:
            cards = [(role, name[role], book.primary_mission(fd[role], fd[other]) if both else None)
                     for role, other in (("attacker", "defender"), ("defender", "attacker"))]
        self.side.show_missions(cards)

        if not book.available:
            msg = "No mission data yet: run  python -m crunch fetch"
            layouts = []
        elif not both:
            msg = "Choose a Force Disposition for both armies."
            layouts = []
        else:
            layouts = book.layouts_for(fd["attacker"], fd["defender"])
            msg = "" if layouts else f"No layouts found for {fd['attacker']} vs {fd['defender']}."
        for i, m in enumerate(self.maps):
            m.set_layout(layouts[i] if i < len(layouts) else None, msg if i == 0 else "", self.measure.get())

        if both:
            pairing = (f"{fd['attacker']} (mirror)" if fd["attacker"] == fd["defender"]
                       else f"{fd['attacker']} vs {fd['defender']}")
            self.pairing.configure(text=pairing)
            self.info.configure(text=f"{len(layouts)} layouts for this pairing. Each map shows the deployment "
                                     "zones, the terrain and the objectives (numbered as printed).")
        else:
            self.pairing.configure(text="")
            self.info.configure(text="")


@register_tool("deployer", "Deployer", "Missions and deployment: the primary missions and the three battlefield "
               "layouts for the two armies' Force Dispositions.", order=30)
def open_deployer(app: "App", selection: Selection) -> DeployerWindow:
    return DeployerWindow(app, selection)
