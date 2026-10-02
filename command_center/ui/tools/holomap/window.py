"""The Field Holomap: mission and deployment support. For the two armies' Force Dispositions it shows the
three battlefield layouts of the pairing (right two thirds), the primary mission each player plays
and a compact view of both armies (left third). Ticking a unit puts its base (or the ellipse of the
whole unit) on each map, at a random spot of its side's deployment zone, to be dragged around.

Each layout can be taken off the view (next to the legend). The layouts viewed and the info panel
(legend, options) are placed in the right two thirds so that the boards are as large as they can be
(command_center.deploy.arrange): the panel in a cell next to the boards, in a column on their right, or in a
strip under them."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.analysis.army_plans import pair_key
from command_center.deploy.arrange import Rect, arrange
from command_center.ui.registry import Selection, register_tool
from command_center.ui.tools.holomap.map_view import OVERLAYS, LayoutMap, legend
from command_center.ui.tools.holomap.score_oracle import ScoreOracle
from command_center.ui.tools.holomap.side_panel import ROLES, SidePanel
from command_center.ui.toolwindow import ToolWindow

if TYPE_CHECKING:
    from command_center.ui.app import App


class HolomapWindow(ToolWindow):
    title_text = "Field Holomap"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="thirds")
        body.columnconfigure(1, weight=2, uniform="thirds")
        body.rowconfigure(0, weight=1)
        self.side = SidePanel(body, self)
        self.side.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        maps = self.board_area = ttk.Frame(body)           # the boards and the info panel: placed by _arrange
        maps.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.maps = [LayoutMap(maps) for _ in range(3)]
        self.shown = [tk.BooleanVar(value=True) for _ in self.maps]     # the layouts being viewed
        self._arrange_job = None
        self.selected: tuple[LayoutMap, str] | None = None     # the unit token later functions act on
        self.placed: dict[str, object] = {}                     # token key -> roster row on the maps
        plans = self.ctx.army_plans                             # the Engagement Optimizer's army plan, kept live
        self.plan = plans.get(selection.attacker.path, selection.defender.path)
        self._unsubscribe = plans.subscribe(self._on_plan_saved)
        self.oracle: ScoreOracle | None = None                 # the floating score window, when open
        for m in self.maps:
            m.on_select = self._on_select
        self.info_cell = self._build_info(maps)
        maps.bind("<Configure>", lambda e: self._arrange())
        self.refresh()
        self._update_plan_links()

    def _build_info(self, parent) -> ttk.Frame:
        """The info panel, in two parts (_arrange stacks them or sets them side by side): the board
        (pairing, measurements, legend, the layouts viewed), and the selected unit's options."""
        cell = ttk.Frame(parent)

        top = self.info_top = ttk.Frame(cell, style="Panel.TFrame", padding=10)
        self.pairing = ttk.Label(top, text="", style="H2.TLabel", wraplength=270, justify="left")
        self.pairing.pack(anchor="w")
        self.info = ttk.Label(top, text="", style="Muted.TLabel", wraplength=270, justify="left")
        self.info.pack(anchor="w", pady=(2, 6))
        self.measure = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Show table-setup measurements", variable=self.measure,
                        style="Panel.TCheckbutton", command=self._toggle_measurements).pack(anchor="w", pady=(0, 6))
        keys = ttk.Frame(top, style="Flat.TFrame")              # the legend | the layouts viewed
        keys.pack(anchor="w")
        legend(keys).pack(side="left", anchor="n")
        view = ttk.Frame(keys, style="Flat.TFrame")
        view.pack(side="left", anchor="n", padx=(18, 0))
        ttk.Label(view, text="View", style="Muted.TLabel").pack(anchor="w")
        for letter, v in zip("ABC", self.shown):
            ttk.Checkbutton(view, text=f"Layout {letter}", variable=v, style="Panel.TCheckbutton",
                            command=self._toggle_layouts).pack(anchor="w")

        bottom = self.info_bottom = ttk.Frame(cell, style="Panel.TFrame", padding=10)
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
        self.plan_note = ttk.Label(bottom, text="No Engagement Optimizer army plan for these two lists yet: Targets "
                                               "need one.", style="Muted.TLabel")
        self._sub_options()
        return cell

    # ---------------------------------------------------------------- the boards viewed, and their place
    def _toggle_layouts(self):
        for m, v in zip(self.maps, self.shown):
            if not v.get() and m.selected:                      # no selection left on a board out of view
                m._select(None)
        self._arrange()

    def _arrange_later(self):
        """Arrange again once the info panel has its new size (its texts changed)."""
        if self._arrange_job is None:
            self._arrange_job = self.after_idle(self._arrange)

    def _arrange(self):
        """Place the boards viewed and the info panel in the space they share, the boards as large as
        that allows."""
        self._arrange_job = None
        area, top, bottom = self.board_area, self.info_top, self.info_bottom
        if area.winfo_width() < 10 or area.winfo_height() < 10:           # not laid out yet
            return
        gap, m0 = 6, self.maps[0]
        tw, th, bw, bh = top.winfo_reqwidth(), top.winfo_reqheight(), bottom.winfo_reqwidth(), bottom.winfo_reqheight()
        chrome = (26, m0.title.winfo_reqheight() + m0.sub.winfo_reqheight() + 30)     # a map's frame, title, margins
        shown = [m for m, v in zip(self.maps, self.shown) if v.get()]
        a = arrange(len(shown), area.winfo_width(), area.winfo_height(),
                    tall=(max(tw, bw) + gap, th + bh + 2 * gap), wide=(tw + bw + 2 * gap, max(th, bh) + gap),
                    chrome=chrome)

        def put(w, rect: Rect):
            x, y, width, height = rect
            w.place(x=x + 3, y=y + 3, width=max(1, width - 6), height=max(1, height - 6))
        for m in self.maps:
            if m not in shown:
                m.place_forget()
        for m, rect in zip(shown, a.boards):
            put(m, rect)
        put(self.info_cell, a.info)
        cell = self.info_cell                                   # its two parts: side by side, or stacked
        top.grid(row=0, column=0, sticky="nsew")
        if a.wide:
            bottom.grid(row=0, column=1, sticky="nsew", padx=(gap, 0), pady=0)
        else:
            bottom.grid(row=1, column=0, sticky="ew", padx=0, pady=(gap, 0))
        cell.rowconfigure(0, weight=1)
        cell.columnconfigure(0, weight=1)
        cell.columnconfigure(1, weight=1 if a.wide else 0)

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

    # ---------------------------------------------------------------- the Engagement Optimizer's army plan
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
        self._arrange_later()

    # ---------------------------------------------------------------- Score Oracle
    def open_score_oracle(self):
        """The floating score window: one per Field Holomap, brought to the front if already open."""
        if self.oracle is not None and self.oracle.winfo_exists():
            self.oracle.deiconify()
            self.oracle.lift()
            self.oracle.focus_set()
            return
        self.oracle = ScoreOracle(self)

    def back(self):
        self._unsubscribe()
        if self._arrange_job is not None:
            self.after_cancel(self._arrange_job)
        if self.oracle is not None and self.oracle.winfo_exists():
            self.oracle.destroy()
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
        if getattr(self, "oracle", None) is not None and self.oracle.winfo_exists():
            self.oracle.refresh()

        if not book.available:
            msg = "No mission data yet: run  python -m command_center fetch"
            layouts = []
        elif not both:
            msg = "Both lists need a Force Disposition (in their Configuration) to show the layouts."
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
        self._arrange_later()


@register_tool("holomap", "Field Holomap", "Missions and deployment: the primary missions and the three battlefield "
               "layouts for the two armies' Force Dispositions.", order=30)
def open_holomap(app: "App", selection: Selection) -> HolomapWindow:
    return HolomapWindow(app, selection)
