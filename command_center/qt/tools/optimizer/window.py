"""Engagement Optimizer: pit every selected attacking unit against every selected defending unit, over each
unit's own list of tests (packages of modifiers), then explore the results."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QProgressBar, QSizePolicy, QSpinBox, QVBoxLayout

from command_center.analysis.plan import (ATTACKER, DEFENDER, PlanStore, active_loads, defender_target, display_name,
                                          resolve_attached, unit_points)
from command_center.analysis.sweep import AttackerSpec, DefenderSpec, build_cases, default_workers, run_sweep
from command_center.analysis.variants import PHASES
from command_center.qt.registry import Selection, register_tool
from command_center.qt.tools.optimizer.unit_panel import UnitPlanPanel
from command_center.qt.toolwindow import ToolWindow
from command_center.qt.widgets import Combo, Panel, Table, button, label
from command_center.qt.worker import Task

if TYPE_CHECKING:
    from command_center.qt.app import App

TRIALS = {"2,000 (fast)": 2_000, "5,000": 5_000, "10,000": 10_000, "20,000 (precise)": 20_000}
SAVE_DELAY = 400            # ms after the last change before the plans are saved


class OptimizerWindow(ToolWindow):
    title_text = "Engagement Optimizer"

    def __init__(self, app: "App", selection: Selection, store: PlanStore | None = None):
        """store: where the units' tests are kept (the user's saved ones unless another is given)."""
        super().__init__(app, selection)
        self.store = store or PlanStore()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.store.save)
        self._running = False
        self._cancel = False
        self._n_cases = 0
        self.results = None
        self.result_windows: list = []

        body = QHBoxLayout(self)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        self.left = UnitPlanPanel(self, selection.attacker, ATTACKER)
        self.right = UnitPlanPanel(self, selection.defender, DEFENDER)
        self.mid = self._build_middle()
        for panel in (self.left, self.mid, self.right):
            panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # thirds, whatever they hold
            body.addWidget(panel, 1)
        self.plans_changed(save=False)

    # ------------------------------------------------------------------ middle column
    def _build_middle(self) -> Panel:
        f = Panel()
        col = QVBoxLayout(f)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)
        top = QHBoxLayout()
        top.addWidget(button("← Command Center", self.back))
        top.addStretch(1)
        col.addLayout(top)
        col.addSpacing(10)
        col.addWidget(label("Engagement Optimizer", "h2"))
        col.addWidget(label("Every ticked attacker is tested against every ticked defender: each attacker test "
                            "(in each of its phases) against each defender test. A test applies all of its "
                            "modifiers together.", "muted", wrap=True))
        col.addSpacing(10)
        self.summary = label("", wrap=True)
        col.addWidget(self.summary)
        col.addSpacing(4)
        self.plan_tree = Table([("side", "Side"), ("unit", "Unit"), ("tests", "Tests")], [70, -220, 70], rows=10,
                               selectable=False)
        col.addWidget(self.plan_tree, 1)
        col.addSpacing(8)

        opts = QGridLayout()
        opts.setHorizontalSpacing(6)
        opts.setVerticalSpacing(4)
        opts.setColumnStretch(2, 1)
        opts.addWidget(label("Trials per test"), 0, 0)
        self.trials_box = Combo()
        self.trials_box.addItems(list(TRIALS))
        self.trials_box.setCurrentText("5,000")
        opts.addWidget(self.trials_box, 0, 1)
        opts.addWidget(label("CPU workers"), 1, 0)
        self.workers_box = QSpinBox()
        self.workers_box.setRange(1, 32)
        self.workers_box.setValue(default_workers())
        opts.addWidget(self.workers_box, 1, 1)
        col.addLayout(opts)
        col.addSpacing(8)

        runbar = QHBoxLayout()
        runbar.setSpacing(6)
        self.run_btn = button("Cogitate", self.run, "accent")
        self.cancel_btn = button("Cancel", self.cancel)
        self.cancel_btn.setEnabled(False)
        self.results_btn = button("Results  →", self.open_results, "accent")
        self.results_btn.setEnabled(False)
        runbar.addWidget(self.run_btn)
        runbar.addWidget(self.cancel_btn)
        runbar.addStretch(1)
        runbar.addWidget(self.results_btn)
        col.addLayout(runbar)
        col.addSpacing(6)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        col.addWidget(self.progress)
        col.addSpacing(2)
        self.status = label("", "muted", wrap=True)
        col.addWidget(self.status)
        return f

    # ------------------------------------------------------------------ plans
    def plans_changed(self, save: bool = True):
        if save:
            self._save_timer.start(SAVE_DELAY)
        atts, defs = self.build_specs()
        n = len(build_cases(atts, defs))
        self.summary.setText(f"{len(atts)} attacker(s) × {len(defs)} defender(s)  →  {n:,} tests")
        t = self.plan_tree
        t.clear_rows()
        for a in atts:
            t.add_row(("Attacker", a.name, sum(len(v) for v in a.tests.values())))
        for d in defs:
            t.add_row(("Defender", d.name, len(d.tests)))
        if not self._running:
            self.run_btn.setEnabled(bool(n))
        self._n_cases = n

    def build_specs(self) -> tuple[list[AttackerSpec], list[DefenderSpec]]:
        wd = self.ctx.wd
        atts: list[AttackerSpec] = []
        for u in self.left.selected_units():
            p = self.left.plan(u)
            attached = resolve_attached(self.left.army, u, p, wd)
            tests = {ph: [tuple(t.mods) for t in p.tests if ph in t.phases] for ph in PHASES}
            tests = {ph: pkgs for ph, pkgs in tests.items() if pkgs}
            atts.append(AttackerSpec(display_name(u, attached), unit_points(u, attached),
                                     {ph: active_loads(u, attached, p, ph) for ph in tests}, tests))
        defs: list[DefenderSpec] = []
        for u in self.right.selected_units():
            p = self.right.plan(u)
            attached = resolve_attached(self.right.army, u, p, wd)
            defs.append(DefenderSpec(display_name(u, attached), unit_points(u, attached),
                                     defender_target(u, attached), [tuple(t.mods) for t in p.tests]))
        return atts, defs

    # ------------------------------------------------------------------ running
    def run(self):
        if self._running:
            return
        atts, defs = self.build_specs()
        cases = build_cases(atts, defs)
        if not cases:
            return
        self._trials = trials = TRIALS.get(self.trials_box.currentText(), 5_000)
        workers = max(1, self.workers_box.value())
        self._running, self._cancel = True, False
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._total = len(cases)
        self.progress.setRange(0, self._total)
        self.progress.setValue(0)
        self.status.setText(f"Running {self._total:,} tests on {workers} worker(s)…")
        self._t0 = time.perf_counter()
        task = Task(lambda: None)

        def work():         # another thread: the window only hears of it through the task's signals
            return run_sweep(cases, trials, workers, lambda done, total: task.step.emit(done), lambda: self._cancel)
        task.work = work
        task.step.connect(self._progressed)
        task.done.connect(self._finished)
        task.begin()

    def _progressed(self, done: int):
        if not self._running:
            return
        self.progress.setValue(done)
        el = time.perf_counter() - self._t0
        eta = f" · about {el / done * (self._total - done):.0f}s left" if done else ""
        self.status.setText(f"{done:,} / {self._total:,} tests · {el:.0f}s{eta}")

    def _finished(self, records, error):
        el = time.perf_counter() - self._t0
        self._running = False
        self.cancel_btn.setEnabled(False)
        self.run_btn.setEnabled(bool(self._n_cases))
        if error:
            self.status.setText(f"Error: {error}")
            return
        records = records or []
        self.progress.setValue(len(records))
        self.results = records
        errors = sum(bool(r.error) for r in records)
        what = "Cancelled after" if self._cancel else "Finished"
        self.status.setText(f"{what} {len(records):,} tests in {el:.1f}s ({self._trials:,} trials each)"
                            + (f" · {errors} failed" if errors else ""))
        if records:
            self.results_btn.setEnabled(True)
            self.open_results()

    def cancel(self):
        self._cancel = True
        self.status.setText("Cancelling…")

    def open_results(self):
        if not self.results:
            return None
        from command_center.qt.tools.optimizer.results import ResultsWindow
        w = ResultsWindow(self, self.results, self.selection)
        self.result_windows.append(w)
        w.show()
        return w

    def closeEvent(self, event):
        self._cancel = True                 # a run under way stops at its next test
        self._save_timer.stop()
        self.store.save()
        super().closeEvent(event)


@register_tool("optimizer", "Engagement Optimizer", "Test many attackers against many defenders, each with its own packages of modifiers, "
               "then rank and compare the results.", order=20)
def open_optimizer(app: "App", selection: Selection) -> OptimizerWindow:
    return OptimizerWindow(app, selection)
