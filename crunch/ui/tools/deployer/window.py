"""The Deployer: mission and deployment support. For the two armies' Force Dispositions it shows the
three battlefield layouts of the pairing (right two thirds), the primary mission each player plays
and a compact view of both armies (left third). Ticking a unit puts its base (or the ellipse of the
whole unit) on each map, at a random spot of its side's deployment zone, to be dragged around."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.analysis.army_plans import pair_key
from crunch.ui.registry import Selection, register_tool
from crunch.ui.tools.deployer.map_view import OVERLAYS, LayoutMap, legend
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
        self.placed: dict[str, object] = {}                     # token key -> roster row on the maps
        plans = self.ctx.army_plans                             # the Optimizer's army plan, kept live
        self.plan = plans.get(selection.attacker.path, selection.defender.path)
        self._unsubscribe = plans.subscribe(self._on_plan_saved)
        for i, m in enumerate(self.maps):
            m.grid(row=i // 2, column=i % 2, sticky="nsew", padx=3, pady=3)
            m.on_select = self._on_select
        self._build_info(maps).grid(row=1, column=1, sticky="nsew", padx=3, pady=3)
        self.refresh()
        self._update_plan_links()

    def _build_info(self, parent) -> ttk.Frame:
        """Bottom-right cell: the board (pairing, measurements, legend) above, the selected unit's
        options below."""
        cell = ttk.Frame(parent)
        cell.columnconfigure(0, weight=1)
        cell.rowconfigure(0, weight=1)

        top = ttk.Frame(cell, style="Panel.TFrame", padding=10)
        top.grid(row=0, column=0, sticky="nsew")
        self.pairing = ttk.Label(top, text="", style="H2.TLabel", wraplength=420, justify="left")
        self.pairing.pack(anchor="w")
        self.info = ttk.Label(top, text="", style="Muted.TLabel", wraplength=420, justify="left")
        self.info.pack(anchor="w", pady=(2, 6))
        self.measure = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Show table-setup measurements", variable=self.measure,
                        style="Panel.TCheckbutton", command=self._toggle_measurements).pack(anchor="w", pady=(0, 6))
        legend(top).pack(anchor="w")

        bottom = ttk.Frame(cell, style="Panel.TFrame", padding=10)
        bottom.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(bottom, text="Selected unit", style="Muted.TLabel").pack(anchor="w")
        self.overlay_vars = {name: tk.BooleanVar(value=False) for name in OVERLAYS}
        self.overlay_widgets: dict[str, list] = {}

        def option_row(lead: str, options: list[tuple[str, str]]):
            row = ttk.Frame(bottom, style="Flat.TFrame")
            row.pack(anchor="w", pady=(2, 0))
            if lead:
                ttk.Label(row, text=lead, style="Panel.TLabel").pack(side="left", padx=(0, 8))
            for name, text in options:                     # "Movement ☐": the label, then its box
                lb = ttk.Label(row, text=text, style="Panel.TLabel")
                lb.pack(side="left")
                cb = ttk.Checkbutton(row, variable=self.overlay_vars[name], style="Panel.TCheckbutton",
                                     command=self._toggle_overlays)
                cb.pack(side="left", padx=(2, 12))
                self.overlay_widgets[name] = [lb, cb]

        option_row("Show", [("move", "Movement"), ("advance", "Advance"), ("charge", "Charge")])
        option_row("", [("objectives", "Distances to the objectives")])
        option_row("Show", [("plan", "Targets"), ("plan2", "2nd"), ("planall", "all")])
        option_row("Show", [("sight", "Line of Sight"), ("hidden", "Hidden"), ("ground", "Go to Ground")])
        self.plan_note = ttk.Label(bottom, text="No Optimizer army plan for these two lists yet: Targets "
                                               "need one.", style="Muted.TLabel")
        self._sub_options()
        return cell

    def _sub_options(self):
        """Hidden refines line of sight, Go to Ground refines Hidden, 2nd and all refine Targets: each
        only available while the option it refines is on."""
        sight, plan = self.overlay_vars["sight"].get(), self.overlay_vars["plan"].get()
        for name, on in (("hidden", sight), ("ground", sight and self.overlay_vars["hidden"].get()),
                         ("plan2", plan), ("planall", plan)):
            for w in self.overlay_widgets[name]:
                w.state(["!disabled"] if on else ["disabled"])

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
                m.add_token(key, role, row.name, row.footprint, row.move, row.ranges)
            else:
                m.remove_token(key)
        if on:
            self.placed[key] = row
        else:
            self.placed.pop(key, None)
        self._update_plan_links()

    # ---------------------------------------------------------------- the Optimizer's army plan
    def _on_plan_saved(self, plan):
        if plan.key == pair_key(self.selection.attacker.path, self.selection.defender.path):
            self.plan = plan
            self._update_plan_links()

    def _update_plan_links(self):
        """Attacker -> target pairs of the army plan, between units placed on the maps."""
        links = []
        if self.plan:
            defenders = {k: {u.label or u.name for u in row.units}
                         for k, row in self.placed.items() if k.startswith("defender:")}
            for key, row in self.placed.items():
                if not key.startswith("attacker:"):
                    continue
                entry = self.plan.entry_for(row.units[0].label or row.units[0].name)
                for rank, target in (("primary", entry and entry.primary), ("secondary", entry and entry.secondary)):
                    if target:
                        hit = next((k for k, labels in defenders.items() if target.units[0] in labels), None)
                        if hit:
                            links.append((key, hit, rank))
        for m in self.maps:
            m.set_plan_links(links)
        if self.plan:                                           # the note only takes room when needed
            self.plan_note.pack_forget()
        else:
            self.plan_note.pack(anchor="w", pady=(4, 0))

    def back(self):
        self._unsubscribe()
        super().back()

    def _toggle_overlays(self):
        self._sub_options()
        flags = {name: v.get() for name, v in self.overlay_vars.items()}
        for m in self.maps:
            m.set_overlays(**flags)

    def _toggle_measurements(self):
        for m in self.maps:
            m.show_measurements = self.measure.get()
            m.draw()

    def refresh(self):
        book = self.ctx.missions
        fd = {role: self.side.disposition(role) for role in ROLES}
        both = all(fd.values())
        for role, other in (("attacker", "defender"), ("defender", "attacker")):
            self.side.show_mission(role, book.primary_mission(fd[role], fd[other]) if both else None)

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
            self.info.configure(text=f"{len(layouts)} layouts for this pairing  ·  Event Companion, via "
                                     "rapidingress.com")
        else:
            self.pairing.configure(text="")
            self.info.configure(text="")


@register_tool("deployer", "Deployer", "Missions and deployment: the primary missions and the three battlefield "
               "layouts for the two armies' Force Dispositions.", order=30)
def open_deployer(app: "App", selection: Selection) -> DeployerWindow:
    return DeployerWindow(app, selection)
