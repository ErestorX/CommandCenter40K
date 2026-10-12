"""The Armies Auspex tool: pick one unit (plus Leader/Support) per side and see the simulated results."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from command_center.core import Modifiers, simulate
from command_center.lists import target_for
from command_center.qt.registry import Selection, register_tool
from command_center.qt.tools.auspex.army_panel import ArmyPanel
from command_center.qt.tools.auspex.results_panel import ResultsPanel
from command_center.qt.toolwindow import ToolWindow
from command_center.qt.worker import Task

if TYPE_CHECKING:
    from command_center.qt.app import App

DELAY = 150         # ms after the last change before the simulation runs: one run for a burst of changes


class AuspexWindow(ToolWindow):
    """Attacker army | results | defender army, split in thirds."""

    title_text = "Armies Auspex"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        self.phase = "shooting"
        self._gen = 0                       # the latest simulation asked for: older ones' results are dropped
        self._ready = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.run)
        self.armies = [selection.attacker, selection.defender]
        self.states: list[dict | None] = [None, None]
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.body: QWidget | None = None
        self.build()

    def build(self):
        if self.body is not None:
            self.box.removeWidget(self.body)
            self.body.deleteLater()
        self._ready = False
        self.body = QWidget()
        row = QHBoxLayout(self.body)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)
        self.results = ResultsPanel(self)
        self.left = ArmyPanel(self, self.armies[0], "attacker", self.states[0])
        self.right = ArmyPanel(self, self.armies[1], "defender", self.states[1])
        for panel in (self.left, self.results, self.right):
            panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # thirds, whatever they hold
            row.addWidget(panel, 1)
        self.box.addWidget(self.body)
        self._ready = True
        self.left.on_unit()
        self.right.on_unit()

    def swap(self):
        self.states = [self.right.state(), self.left.state()]
        self.armies.reverse()
        self.build()

    def set_phase(self, phase: str):
        self.phase = phase
        self.results.phase_buttons[phase].setChecked(True)
        self.left.refresh_weapons()
        self.schedule()

    def schedule(self):
        """Something the simulation depends on changed: run it again, shortly. A simulation still under
        way is for what was there before: its result will be dropped."""
        if self._ready:
            self._gen += 1
            self._timer.start(DELAY)

    def run(self):
        self._timer.stop()
        att, dfn = self.left, self.right
        if not att.unit or not dfn.unit:
            return
        a_name = " + ".join([att.unit.label] + [a.label for a in att.attached])
        target = target_for(dfn.unit, dfn.attached)
        dfn.apply_order(target)
        title = f"{a_name}  →  {target.name}"
        self._gen += 1
        gen, trials = self._gen, self.ctx.settings.trials
        if not dfn.unit.datasheet:
            self.results.empty(title, "The defending unit has no datasheet.")
            return
        loads = att.selected_loads()
        if not loads:
            self.results.empty(title, f"No {'melee' if self.phase == 'fight' else 'ranged'} weapons selected.")
            return
        mods = Modifiers()
        att.apply_mods(mods)
        dfn.apply_mods(mods)
        self.results.busy(title)

        def work():   # another thread: nothing of the window is touched in here
            t0 = time.perf_counter()
            try:
                return gen, title, simulate(loads, target, mods, trials=trials), None, time.perf_counter() - t0
            except Exception as e:  # noqa: BLE001 - shown in the results panel
                return gen, title, None, e, 0.0
        task = Task(work)
        task.done.connect(self._simulated)
        task.begin()

    def _simulated(self, outcome, error):
        gen, title, result, failed, seconds = outcome
        if gen != self._gen:                # asked for again since: this one is out of date
            return
        if failed:
            self.results.empty(title, f"Error: {failed}")
        else:
            self.results.show_result(title, result, seconds)


@register_tool("auspex", "Armies Auspex", "One unit (with Leader/Support) against another: expected damage, "
               "models slain and the full distribution.", order=10)
def open_auspex(app: "App", selection: Selection) -> AuspexWindow:
    return AuspexWindow(app, selection)
