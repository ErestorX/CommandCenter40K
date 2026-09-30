"""Optimizer: pit every selected attacking unit against every selected defending unit, over each
unit's own list of test scenarios, then explore the results."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.analysis.plan import (ATTACKER, DEFENDER, PlanStore, active_loads, defender_target, display_name,
                                  resolve_attached, unit_points)
from crunch.analysis.sweep import AttackerSpec, DefenderSpec, build_cases, default_workers, run_sweep
from crunch.analysis.variants import PHASES
from crunch.ui.registry import Selection, register_tool
from crunch.ui.tools.optimizer.unit_panel import UnitPlanPanel
from crunch.ui.toolwindow import ToolWindow
from crunch.ui.widgets import make_tree

if TYPE_CHECKING:
    from crunch.ui.app import App

TRIALS = {"2,000 (fast)": 2_000, "5,000": 5_000, "10,000": 10_000, "20,000 (precise)": 20_000}


class OptimizerWindow(ToolWindow):
    title_text = "Optimizer"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        self.store = PlanStore()
        self._save_job = None
        self._running = False
        self._cancel = False
        self.results = None
        self.result_windows: list[tk.Toplevel] = []

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        for c in range(3):
            body.columnconfigure(c, weight=1, uniform="thirds")
        body.rowconfigure(0, weight=1)
        self.left = UnitPlanPanel(body, self, selection.attacker, ATTACKER)
        self.right = UnitPlanPanel(body, self, selection.defender, DEFENDER)
        self.mid = self._build_middle(body)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.mid.grid(row=0, column=1, sticky="nsew", padx=4)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self.protocol("WM_DELETE_WINDOW", self.back)
        self.plans_changed(save=False)

    # ------------------------------------------------------------------ middle column
    def _build_middle(self, parent):
        f = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        top = ttk.Frame(f, style="Flat.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="← Lists", command=self.back).pack(side="left")
        ttk.Label(f, text="Optimizer", style="H2.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(f, text="Every ticked attacker is tested against every ticked defender, for each phase and "
                          "each scenario ticked on both sides (scenarios are tried one at a time, never "
                          "combined).", style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w")

        self.summary = ttk.Label(f, text="", style="Panel.TLabel", justify="left", wraplength=420)
        self.summary.pack(anchor="w", pady=(10, 4))
        fr, self.plan_tree = make_tree(f, [("side", "Side"), ("unit", "Unit"), ("tests", "Scenarios")],
                                       [70, -220, 70], height=10)
        fr.pack(fill="both", expand=True)

        opts = ttk.Frame(f, style="Flat.TFrame")
        opts.pack(fill="x", pady=(8, 4))
        ttk.Label(opts, text="Trials per test", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.trials_var = tk.StringVar(value="5,000")
        ttk.Combobox(opts, textvariable=self.trials_var, values=list(TRIALS), state="readonly",
                     width=16).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(opts, text="CPU workers", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.workers_var = tk.IntVar(value=default_workers())
        ttk.Spinbox(opts, from_=1, to=32, textvariable=self.workers_var, width=6).grid(
            row=1, column=1, sticky="w", padx=6, pady=(4, 0))

        runbar = ttk.Frame(f, style="Flat.TFrame")
        runbar.pack(fill="x", pady=(6, 2))
        self.run_btn = ttk.Button(runbar, text="Run tests", style="Accent.TButton", command=self.run)
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(runbar, text="Cancel", command=self.cancel)
        self.cancel_btn.pack(side="left", padx=6)
        self.cancel_btn.state(["disabled"])
        self.results_btn = ttk.Button(runbar, text="Results  →", style="Accent.TButton", command=self.open_results)
        self.results_btn.pack(side="right")
        self.results_btn.state(["disabled"])
        self.progress = ttk.Progressbar(f, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 2))
        self.status = ttk.Label(f, text="", style="Muted.TLabel")
        self.status.pack(anchor="w")
        return f

    # ------------------------------------------------------------------ plans
    def plans_changed(self, save: bool = True):
        if save:
            if self._save_job:
                self.after_cancel(self._save_job)
            self._save_job = self.after(400, self.store.save)
        atts, defs = self.build_specs()
        n = len(build_cases(atts, defs))
        self.summary.configure(text=f"{len(atts)} attacker(s) × {len(defs)} defender(s)  →  {n:,} tests")
        t = self.plan_tree
        t.delete(*t.get_children())
        for a in atts:
            t.insert("", "end", values=("Attacker", a.name, sum(len(v) for v in a.variants.values())))
        for d in defs:
            t.insert("", "end", values=("Defender", d.name, len(d.variants)))
        if not self._running:
            self.run_btn.state(["!disabled"] if n else ["disabled"])
        self._n_cases = n

    def build_specs(self) -> tuple[list[AttackerSpec], list[DefenderSpec]]:
        wd = self.ctx.wd
        atts: list[AttackerSpec] = []
        for u in self.left.selected_units():
            p = self.left.plan(u)
            attached = resolve_attached(self.left.army, u, p, wd)
            phases = [ph for ph in PHASES if p.phases.get(ph)]
            atts.append(AttackerSpec(display_name(u, attached), unit_points(u, attached),
                                     {ph: active_loads(u, attached, p, ph) for ph in phases},
                                     {ph: list(p.variant_keys(ph)) for ph in phases}))
        defs: list[DefenderSpec] = []
        for u in self.right.selected_units():
            p = self.right.plan(u)
            attached = resolve_attached(self.right.army, u, p, wd)
            defs.append(DefenderSpec(display_name(u, attached), unit_points(u, attached),
                                     defender_target(u, attached), list(p.variant_keys("any"))))
        return atts, defs

    # ------------------------------------------------------------------ running
    def run(self):
        if self._running:
            return
        atts, defs = self.build_specs()
        cases = build_cases(atts, defs)
        if not cases:
            return
        trials = TRIALS.get(self.trials_var.get(), 5_000)
        try:
            workers = max(1, int(self.workers_var.get()))
        except (tk.TclError, ValueError):
            workers = default_workers()
        self._running, self._cancel = True, False
        self.run_btn.state(["disabled"])
        self.cancel_btn.state(["!disabled"])
        self.progress.configure(maximum=len(cases), value=0)
        self.status.configure(text=f"Running {len(cases):,} tests on {workers} worker(s)…")
        box: dict = {"done": 0, "total": len(cases), "result": None, "error": None}
        t0 = time.perf_counter()

        def progress(done, total):          # worker thread: only store numbers here
            box["done"] = done

        def work():
            try:
                box["result"] = run_sweep(cases, trials, workers, progress, lambda: self._cancel)
            except Exception as e:  # noqa: BLE001
                box["error"] = e
            box["finished"] = True

        threading.Thread(target=work, daemon=True).start()
        self._poll(box, t0, trials)

    def _poll(self, box, t0, trials):
        if not self.winfo_exists():
            return
        done, total = box["done"], box["total"]
        self.progress.configure(value=done)
        el = time.perf_counter() - t0
        if not box.get("finished"):
            eta = f" · about {el / done * (total - done):.0f}s left" if done else ""
            self.status.configure(text=f"{done:,} / {total:,} tests · {el:.0f}s{eta}")
            self.after(100, self._poll, box, t0, trials)
            return
        self._running = False
        self.cancel_btn.state(["disabled"])
        self.run_btn.state(["!disabled"])
        if box["error"]:
            self.status.configure(text=f"Error: {box['error']}")
            return
        records = box["result"] or []
        self.results = records
        errors = sum(bool(r.error) for r in records)
        what = "Cancelled after" if self._cancel else "Finished"
        self.status.configure(text=f"{what} {len(records):,} tests in {el:.1f}s ({trials:,} trials each)"
                                   + (f" · {errors} failed" if errors else ""))
        if records:
            self.results_btn.state(["!disabled"])
            self.open_results()

    def cancel(self):
        self._cancel = True
        self.status.configure(text="Cancelling…")

    def open_results(self):
        if not self.results:
            return
        from crunch.ui.tools.optimizer.results import ResultsWindow
        w = ResultsWindow(self, self.results, self.selection)
        self.result_windows.append(w)

    def back(self):
        self._cancel = True
        if self._save_job:
            self.after_cancel(self._save_job)
        self.store.save()
        super().back()


@register_tool("optimizer", "Optimizer", "Test many attackers against many defenders over lists of scenarios, "
               "then rank and compare the results.", order=20)
def open_optimizer(app: "App", selection: Selection) -> OptimizerWindow:
    return OptimizerWindow(app, selection)
