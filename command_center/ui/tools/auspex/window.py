"""The Armies Auspex tool: pick one unit (plus Leader/Support) per side and see the simulated results."""
from __future__ import annotations

import gc
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.core import Modifiers, simulate
from command_center.lists import target_for
from command_center.ui.registry import Selection, register_tool
from command_center.ui.tools.auspex.army_panel import ArmyPanel
from command_center.ui.tools.auspex.results_panel import ResultsPanel
from command_center.ui.toolwindow import ToolWindow

if TYPE_CHECKING:
    from command_center.ui.app import App


class AuspexWindow(ToolWindow):
    """Attacker army | results | defender army, split in thirds."""

    title_text = "Armies Auspex"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        self.phase = tk.StringVar(value="shooting")
        self._job = None
        self._gen = 0
        self.armies = [selection.attacker, selection.defender]
        self.states: list[dict | None] = [None, None]
        self.body = None
        self.build()

    def build(self):
        if self.body:
            self.body.destroy()
            self.body = self.left = self.right = self.results = None
            gc.collect()    # free the old panels' Tk variables here, not later on the simulation thread
        self._ready = False
        self.body = ttk.Frame(self, padding=8)
        self.body.pack(fill="both", expand=True)
        for c in range(3):
            self.body.columnconfigure(c, weight=1, uniform="thirds")
        self.body.rowconfigure(0, weight=1)
        self.results = ResultsPanel(self.body, self)
        self.left = ArmyPanel(self.body, self, self.armies[0], "attacker", self.states[0])
        self.right = ArmyPanel(self.body, self, self.armies[1], "defender", self.states[1])
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.results.grid(row=0, column=1, sticky="nsew", padx=4)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self._ready = True
        self.update_idletasks()
        self.left._on_unit()
        self.right._on_unit()

    def swap(self):
        self.states = [self.right.state(), self.left.state()]
        self.armies.reverse()
        self.build()

    def on_phase(self):
        self.left.refresh_weapons()
        self.schedule()

    def schedule(self):
        if not getattr(self, "_ready", False):
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(150, self.run)

    def run(self):
        self._job = None
        att, dfn = self.left, self.right
        if not att.unit or not dfn.unit:
            return
        a_name = " + ".join([att.unit.label] + [a.label for a in att.attached])
        target = target_for(dfn.unit, dfn.attached)
        dfn.apply_order(target)
        title = f"{a_name}  →  {target.name}"
        if not dfn.unit.datasheet:
            self.results.empty(title, "The defending unit has no datasheet.")
            return
        loads = att.selected_loads()
        if not loads:
            self.results.empty(title, f"No {'melee' if self.phase.get() == 'fight' else 'ranged'} weapons selected.")
            return
        mods = Modifiers()
        att.apply_mods(mods)
        dfn.apply_mods(mods)
        self._gen += 1
        gen = self._gen
        self.results.busy(title)

        box: list = []

        def work():   # background thread: no tkinter calls in here
            t0 = time.perf_counter()
            try:
                box.append((simulate(loads, target, mods, trials=self.ctx.settings.trials), None,
                            time.perf_counter() - t0))
            except Exception as e:  # noqa: BLE001
                box.append((None, e, 0.0))
        gc.collect()        # tkinter objects must never be finalised on the worker thread
        threading.Thread(target=work, daemon=True).start()
        self._poll(gen, title, box)

    def _poll(self, gen, title, box):
        if not self.winfo_exists() or gen != self._gen:
            return
        if not box:
            self.after(25, self._poll, gen, title, box)
            return
        res, err, dt = box[0]
        if err:
            self.results.empty(title, f"Error: {err}")
        else:
            self.results.show(title, res, dt)


@register_tool("auspex", "Armies Auspex", "One unit (with Leader/Support) against another: expected damage, "
               "models slain and the full distribution.", order=10)
def open_auspex(app: "App", selection: Selection) -> AuspexWindow:
    return AuspexWindow(app, selection)
