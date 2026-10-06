"""Results explorer for the Engagement Optimizer: army plan, matrix, rankings and a table, with filters and hideable
data points. Every view reads the same ResultSet, so hiding or filtering applies everywhere.
The matrix and rankings show one phase, or the total of both (Shooting + Fight)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from command_center.analysis.army_plans import PlanEntry, PlanTarget, SavedPlan, units_of
from command_center.analysis.assign import plan_army
from command_center.analysis.results import ATT_MODES, DEF_MODES, DIMS, METRICS, PHASE_VIEWS, TOTAL, Agg, ResultSet
from command_center.analysis.sweep import TestRecord, to_csv
from command_center.ui.charts import INK_3, SLOTS, BarChart, BarItem, Heatmap, StemChart
from command_center.ui.screen import screen_height
from command_center.ui.theme import C, dark_title_bar
from command_center.ui.widgets import make_tree

if TYPE_CHECKING:
    from command_center.ui.registry import Selection

PHASE_COLOR = {"Shooting": SLOTS[0], "Fight": SLOTS[1]}
LEGEND = [("Shooting", SLOTS[0]), ("Fight", SLOTS[1])]
MIXED = INK_3


def _inv(d: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in d.items()}


class ResultsWindow(tk.Toplevel):
    def __init__(self, master, records: list[TestRecord], selection: "Selection"):
        super().__init__(master)
        self.title(f"Command Center 40K — Engagement Optimizer results ({len(records):,} tests)")
        self.configure(bg=C["bg"])
        self.minsize(1100, 1)
        screen_height(self, 1500)
        dark_title_bar(self)
        self.rs = ResultSet(records)
        self.selection = selection
        self.plans = master.ctx.army_plans          # the army plan is saved there for other windows
        saved = self.plans.get(selection.attacker.path, selection.defender.path)
        self._saved = saved.settings if saved else {}   # reopening shows (and keeps) the saved plan
        self.pair_selected: tuple[str, str] | None = None

        # ---- top bar -------------------------------------------------------------------------
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.phase_view = tk.StringVar(value=PHASE_VIEWS.get(self._saved.get("phase"), PHASE_VIEWS[TOTAL]))
        self.metric = tk.StringVar(value=METRICS["dmg_mean"].label)
        self.att_mode = tk.StringVar(value=ATT_MODES.get(self._saved.get("attacker_tests"), ATT_MODES["best"]))
        self.def_mode = tk.StringVar(value=DEF_MODES.get(self._saved.get("defender_tests"), DEF_MODES["mean"]))
        for label, var, values, w in (("Phase", self.phase_view, list(PHASE_VIEWS.values()), 22),
                                      ("Metric", self.metric, [m.label for m in METRICS.values()], 26),
                                      ("Attacker tests", self.att_mode, list(ATT_MODES.values()), 24),
                                      ("Defender tests", self.def_mode, list(DEF_MODES.values()), 24)):
            ttk.Label(top, text=label).pack(side="left", padx=(0, 4))
            cb = ttk.Combobox(top, textvariable=var, values=values, state="readonly", width=w)
            cb.pack(side="left", padx=(0, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(top, text="Export CSV…", command=self.export).pack(side="right")
        self.unhide_btn = ttk.Button(top, text="Show hidden", command=self.unhide)
        self.unhide_btn.pack(side="right", padx=6)
        self.count_lbl = ttk.Label(top, text="", foreground=C["muted"])
        self.count_lbl.pack(side="right", padx=10)

        # ---- body: filters | views ---------------------------------------------------------------
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        side = ttk.Frame(body, style="Panel.TFrame", padding=8)
        ttk.Label(side, text="Filters", style="H2.TLabel").pack(anchor="w")
        ttk.Label(side, text="Click to include / exclude", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        fr = ttk.Frame(side, style="Flat.TFrame")
        fr.pack(fill="both", expand=True)
        self.filters = ttk.Treeview(fr, show="tree", selectmode="none")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.filters.yview)
        self.filters.configure(yscrollcommand=sb.set)
        self.filters.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.filters.tag_configure("off", foreground=C["dim"])
        self.filters.tag_configure("dim", font=("TkDefaultFont", 9, "bold"))
        self.filters.bind("<ButtonRelease-1>", self._toggle_filter)
        body.add(side, weight=1)

        self.nb = ttk.Notebook(body)
        body.add(self.nb, weight=5)
        self._build_plan_tab()
        self._build_matrix_tab()
        self._build_rank_tab("into")
        self._build_rank_tab("from")
        self._build_table_tab()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh())

        self._fill_filters()
        self.refresh()

    # ------------------------------------------------------------------ settings
    @property
    def metric_key(self) -> str:
        return next(k for k, m in METRICS.items() if m.label == self.metric.get())

    @property
    def phase(self) -> str:
        return _inv(PHASE_VIEWS)[self.phase_view.get()]

    @property
    def am(self) -> str:
        return _inv(ATT_MODES)[self.att_mode.get()]

    @property
    def dm(self) -> str:
        return _inv(DEF_MODES)[self.def_mode.get()]

    # ------------------------------------------------------------------ filters
    def _fill_filters(self):
        t = self.filters
        t.delete(*t.get_children())
        for dim, title in DIMS.items():
            t.insert("", "end", iid=f"d|{dim}", text=title, open=True, tags=("dim",))
            for v in self.rs.values(dim):
                t.insert(f"d|{dim}", "end", iid=f"v|{dim}|{v}", text=v)
        self._paint_filters()

    def _paint_filters(self):
        t = self.filters
        for dim, title in DIMS.items():
            vals = self.rs.values(dim)
            ex = self.rs.excluded[dim]
            mark = "☑" if not ex else ("☐" if len(ex) >= len(vals) else "◐")
            t.item(f"d|{dim}", text=f"{mark}  {title}")
            for v in vals:
                on = v not in ex
                t.item(f"v|{dim}|{v}", text=f"{'☑' if on else '☐'}  {v}", tags=() if on else ("off",))

    def _toggle_filter(self, e):
        iid = self.filters.identify_row(e.y)
        if not iid or self.filters.identify_element(e.x, e.y) == "Treeitem.indicator":
            return
        parts = iid.split("|", 2)
        if parts[0] == "d":
            dim = parts[1]
            ex = self.rs.excluded[dim]
            if ex:
                ex.clear()
            else:
                ex.update(self.rs.values(dim))
        else:
            dim, v = parts[1], parts[2]
            ex = self.rs.excluded[dim]
            ex.symmetric_difference_update({v})
        self._paint_filters()
        self.refresh()

    # ------------------------------------------------------------------ hiding
    def hide(self, records: list[TestRecord]):
        self.rs.hidden.update(r.id for r in records)
        self.refresh()

    def unhide(self):
        self.rs.hidden.clear()
        self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="optimizer_results.csv")
        if path:
            to_csv(self.rs.visible(), path)

    # ------------------------------------------------------------------ army plan tab
    def _build_plan_tab(self):
        tab = ttk.Frame(self.nb, style="Panel.TFrame", padding=8)
        self.nb.add(tab, text="Army plan")
        self.plan_title = ttk.Label(tab, text="", style="H2.TLabel")
        self.plan_title.pack(anchor="w")
        ttk.Label(tab, text="Each attacker gets a 1st target (its priority) and a 2nd target (worth half), so that "
                            "every defender is targeted at least once. Attackers sent at the same unit share it: "
                            "what goes beyond its wounds counts for nothing. Uses the Phase, attacker tests and "
                            "defender tests chosen above, and skips hidden or filtered-out tests.",
                  style="Muted.TLabel", wraplength=1050, justify="left").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(tab, style="Flat.TFrame")
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Guide by:  points removed per 100 pts", style="Panel.TLabel").pack(side="left")
        self._weight_shown = self._weight_step(100 * self._saved.get("weight", 0.5))
        self.plan_weight = tk.DoubleVar(value=self._weight_shown)
        ttk.Scale(bar, from_=0, to=100, orient="horizontal", length=260, variable=self.plan_weight,
                  command=self._on_weight).pack(side="left", padx=8)
        ttk.Label(bar, text="share of the unit's wounds", style="Panel.TLabel").pack(side="left")
        self.weight_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.weight_lbl.pack(side="left", padx=12)
        self.plan_summary = ttk.Label(tab, text="", style="Panel.TLabel")
        self.plan_summary.pack(anchor="w", pady=(0, 4))

        pw = ttk.PanedWindow(tab, orient="vertical")
        pw.pack(fill="both", expand=True)
        top = ttk.Frame(pw, style="Flat.TFrame")
        ttk.Label(top, text="By attacker", style="Muted.TLabel").pack(anchor="w")
        f, self.plan_atts = make_tree(top, [("att", "Attacker"), ("t1", "1st target"), ("w1", "Wounds"),
                                            ("p1", "Pts/100"), ("t2", "2nd target"), ("w2", "Wounds"),
                                            ("p2", "Pts/100")], [-230, -230, 64, 64, -230, 64, 64], height=8)
        f.pack(fill="both", expand=True)
        pw.add(top, weight=1)
        bottom = ttk.Frame(pw, style="Flat.TFrame")
        ttk.Label(bottom, text="By defender (wounds: expected share of the unit's wounds removed by the "
                               "attackers sent at it)", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        f, self.plan_defs = make_tree(bottom, [("def", "Defender"), ("pts", "Pts"), ("by1", "1st target of"),
                                               ("w1", "Wounds"), ("by2", "2nd target of"), ("w2", "Wounds")],
                                      [-230, 50, -260, 64, -260, 64], height=8)
        f.pack(fill="both", expand=True)
        self.plan_defs.tag_configure("uncovered", foreground=C["muted"])
        self.plan_defs.tag_configure("overkill", foreground=C["warn"])
        pw.add(bottom, weight=1)
        self._plan_job = None

    WEIGHT_STEP = 10        # the "Guide by" slider moves by this many percent

    @classmethod
    def _weight_step(cls, value) -> int:
        """The slider's position, on its nearest step."""
        return cls.WEIGHT_STEP * round(float(value) / cls.WEIGHT_STEP)

    def _on_weight(self, value):
        """The slider was moved: it goes to the nearest step, and the plan is made again if that is another one."""
        step, was = self._weight_step(value), self._weight_shown
        self.plan_weight.set(step)
        self._weight_shown = step
        if step != was:
            self._schedule_plan()

    def _schedule_plan(self):
        self.weight_lbl.configure(text=self._weight_text())
        if self._plan_job:
            self.after_cancel(self._plan_job)
        self._plan_job = self.after(250, self._refresh_plan)

    def _weight_text(self) -> str:
        w = round(self.plan_weight.get())
        return f"{w}% wounds · {100 - w}% points"

    def _refresh_plan(self):
        self._plan_job = None
        self.weight_lbl.configure(text=self._weight_text())
        vis = self.rs.visible()
        atts = list(dict.fromkeys(r.attacker for r in vis))
        defs = list(dict.fromkeys(r.defender for r in vis))
        def_pts = {r.defender: r.def_points for r in vis}
        frac, ppp = {}, {}
        for (a, d), recs in self.rs.by_pair(vis).items():
            f = self.rs.pair(a, d, "frac_wounds", self.am, self.dm, recs, self.phase)
            p = self.rs.pair(a, d, "pts_per_100", self.am, self.dm, recs, self.phase)
            if f and p:
                frac[a, d], ppp[a, d] = f.value, p.value
        plan = plan_army(atts, defs, frac, ppp, self.plan_weight.get() / 100)
        self._save_plan(plan, frac, ppp)
        self.plan_title.configure(text=f"Army plan: {self.phase_view.get()}, {self.att_mode.get().lower()}, "
                                       f"{self.def_mode.get().lower()}")
        n_def = len(defs)
        if not atts or not defs:
            summary = "Nothing to plan: all tests are filtered out or hidden."
        elif plan.uncovered:
            summary = (f"{len(plan.uncovered)} of {n_def} defenders left out: {len(atts)} attackers x 2 targets "
                       f"can't reach them all ({', '.join(plan.uncovered)}).")
        else:
            summary = f"All {n_def} defenders are targeted by the {len(atts)} attackers."
        self.plan_summary.configure(text=summary)

        pct = lambda v: f"{v:.0%}"
        t = self.plan_atts
        t.delete(*t.get_children())
        first: dict[str, list[str]] = {d: [] for d in defs}
        second: dict[str, list[str]] = {d: [] for d in defs}
        for s in plan.assignments:
            row = [s.attacker]
            for d, into in ((s.primary, first), (s.secondary, second)):
                if d is None:
                    row += ["–", "", ""]
                else:
                    row += [d, pct(frac[s.attacker, d]), f"{ppp[s.attacker, d]:.1f}"]
                    into[d].append(s.attacker)
            t.insert("", "end", values=row)
        t = self.plan_defs
        t.delete(*t.get_children())
        for d in sorted(defs, key=lambda d: -def_pts[d]):
            w1 = sum(frac[a, d] for a in first[d])
            w2 = sum(frac[a, d] for a in second[d])
            tag = "uncovered" if not first[d] and not second[d] else ("overkill" if w1 > 1 else "")
            t.insert("", "end", tags=(tag,) if tag else (), values=(
                d, def_pts[d], ", ".join(first[d]) or "–", pct(w1) if first[d] else "",
                ", ".join(second[d]) or "–", pct(w2) if second[d] else ""))

    def _save_plan(self, plan, frac: dict, ppp: dict):
        """Keep the plan of this pair of lists up to date in the shared store (and on disk)."""
        def target(a, d):
            return PlanTarget(d, units_of(d), round(frac[a, d], 4), round(ppp[a, d], 2)) if d else None
        entries = [PlanEntry(s.attacker, units_of(s.attacker), target(s.attacker, s.primary),
                             target(s.attacker, s.secondary)) for s in plan.assignments]
        self.plans.put(SavedPlan(
            self.selection.attacker.path.name, self.selection.defender.path.name, entries, list(plan.uncovered),
            {"phase": self.phase, "attacker_tests": self.am, "defender_tests": self.dm,
             "weight": round(self.plan_weight.get() / 100, 3)}))

    # ------------------------------------------------------------------ matrix tab
    def _build_matrix_tab(self):
        tab = ttk.Frame(self.nb, style="Panel.TFrame", padding=8)
        self.nb.add(tab, text="Matrix")
        self.matrix_title = ttk.Label(tab, text="", style="H2.TLabel")
        self.matrix_title.pack(anchor="w")
        ttk.Label(tab, text="Rows: attackers · columns: defenders. Hover for details, click a cell to list every "
                            "test behind it, right-click a cell to hide that pairing.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        pw = ttk.PanedWindow(tab, orient="vertical")
        pw.pack(fill="both", expand=True)
        self.heat = Heatmap(pw, on_click=self._cell_click, on_right_click=self._cell_hide)
        pw.add(self.heat, weight=3)
        detail = ttk.Frame(pw, style="Flat.TFrame")
        self.detail_title = ttk.Label(detail, text="Click a cell to see its tests.", style="Muted.TLabel")
        self.detail_title.pack(anchor="w", pady=(6, 2))
        self.detail = BarChart(detail, on_click=lambda key: self.hide([key]))
        self.detail.pack(fill="both", expand=True)
        pw.add(detail, weight=2)
        self._matrix_cache = None

    def _refresh_matrix(self):
        m = METRICS[self.metric_key]
        atts, defs, cells = self.rs.matrix(self.metric_key, self.am, self.dm, self.phase)
        values = [[c.value if c else None for c in row] for row in cells]
        tips = [[self._cell_tip(a, d, c, m) for d, c in zip(defs, row)] for a, row in zip(atts, cells)]
        self._matrix_cache = (atts, defs, cells)
        self.matrix_title.configure(text=f"{self.phase_view.get()}: {m.label} — {self.att_mode.get().lower()}, "
                                         f"{self.def_mode.get().lower()}")
        self.heat.set_data(atts, defs, values, tips, fmt=m.fmt, caption=m.label)
        self._refresh_detail()

    @staticmethod
    def _scenario_text(r: TestRecord) -> str:
        return f"{r.phase} · {r.att_test} (vs {r.def_test})"

    @staticmethod
    def _source(agg: Agg) -> str:
        """Which test a phase value comes from."""
        if not agg.record:
            return "average of attacker tests"
        r = agg.record
        return r.att_test + (f" (vs {r.def_test})" if agg.exact else " (over defender tests)")

    def _cell_tip(self, a, d, agg: Agg | None, m) -> list[str]:
        if not agg:
            return [f"{a}  →  {d}", "no visible tests"]
        lines = [f"{a}  →  {d}", f"{m.label}: {m.fmt(agg.value)}" + (" (Shooting + Fight)" if agg.parts else "")]
        for ph, p in agg.parts.items():
            lines.append(f"  {ph}: {m.fmt(p.value)} · {self._source(p)}")
        if not agg.parts:
            lines.append(f"{agg.record.phase if agg.record else self.phase}: {self._source(agg)}")
        lines.append(f"{len(agg.records)} test(s) · click for details")
        return lines

    def _cell_click(self, i, j):
        atts, defs, _ = self._matrix_cache
        self.pair_selected = (atts[i], defs[j])
        self._refresh_detail()

    def _cell_hide(self, i, j):
        atts, defs, cells = self._matrix_cache
        if cells[i][j]:
            self.hide(cells[i][j].records)

    def _refresh_detail(self):
        if not self.pair_selected:
            self.detail.set_data([], empty_text="Click a cell to list its tests.")
            return
        a, d = self.pair_selected
        m = METRICS[self.metric_key]
        recs = [r for r in self.rs.visible() if r.attacker == a and r.defender == d
                and self.phase in (TOTAL, r.phase)]
        recs.sort(key=lambda r: -getattr(r, m.key))
        self.detail_title.configure(text=f"{a}  →  {d}: every visible test (click a bar to hide it)")
        self.detail.set_data([self._bar(r, m, f"{r.phase} · {r.att_test}", f"vs {r.def_test}") for r in recs],
                             fmt=m.fmt, legend=LEGEND, empty_text="All tests of this pairing are hidden.")

    def _bar(self, r: TestRecord, m, label: str, sub: str, key=None, value=None) -> BarItem:
        v = getattr(r, m.key) if value is None else value
        lo = getattr(r, m.lo) if m.lo and value is None else None
        hi = getattr(r, m.hi) if m.hi and value is None else None
        tip = [f"{r.attacker}  →  {r.defender}", f"{r.phase} · {r.att_test} · defender: {r.def_test}",
               f"{m.label}: {m.fmt(v)}" + (f"  (90% of games: {m.fmt(lo)}–{m.fmt(hi)})" if lo is not None else ""),
               f"damage {r.dmg_mean:.1f} · slain {r.slain_mean:.1f}/{r.models} · destroyed {r.p_wipe:.0%}",
               f"points removed {r.pts_removed:.0f} of {r.def_points} ({r.pts_per_100:.1f} per 100 pts)",
               "click to hide"]
        return BarItem(key if key is not None else r, label, v, lo, hi, PHASE_COLOR.get(r.phase, MIXED), sub, tip)

    def _agg_bar(self, agg: Agg, m, label: str, sub: str, key) -> BarItem:
        """Bar for an aggregated value; the spread is only shown when the value is one exact test."""
        bi = self._bar(agg.record, m, label, sub, key=key)
        if not agg.exact:
            bi.value, bi.lo, bi.hi = agg.value, None, None
            bi.tip[1] = f"{agg.record.phase} · {agg.record.att_test} · over {len(agg.records)} defender test(s)"
            bi.tip[2] = f"{m.label}: {m.fmt(agg.value)} (average)"
            bi.tip[3:5] = [f"tests: " + ", ".join(sorted({r.def_test for r in agg.records}))]
        return bi

    def _total_bar(self, agg: Agg, m, label: str, a: str, d: str) -> BarItem:
        """Bar for a pair's Shooting + Fight total, stacked by phase."""
        whole = sum(p.value for p in agg.parts.values()) or 1.0
        prefix = {"best": "best: ", "worst": "worst: "}.get(self.am, "")
        sub = prefix + " + ".join(f"{ph} {m.fmt(p.value)}" for ph, p in agg.parts.items())
        capped = m.cap is not None and agg.value < whole - 1e-9
        tip = [f"{a}  →  {d}", f"{m.label}: {m.fmt(agg.value)} (Shooting + Fight"
                               + (", capped at the whole unit)" if capped else ")")]
        tip += [f"{ph}: {m.fmt(p.value)} · {self._source(p)}" for ph, p in agg.parts.items()]
        if all(p.record for p in agg.parts.values()):
            key = ("tests", a, d, tuple((ph, p.record.att_test) for ph, p in agg.parts.items()))
            tip.append("click to hide these tests: the next best take their place")
        else:
            key = ("pair", a, d)
            tip.append("click to hide this pairing")
        return BarItem(key, label, agg.value, color=MIXED, sublabel=sub, tip=tip,
                       segments=[(p.value / whole, PHASE_COLOR[ph]) for ph, p in agg.parts.items()])

    # ------------------------------------------------------------------ ranking tabs
    def _build_rank_tab(self, mode: str):
        tab = ttk.Frame(self.nb, style="Panel.TFrame", padding=8)
        self.nb.add(tab, text="Best attackers into…" if mode == "into" else "Best targets for…")
        bar = ttk.Frame(tab, style="Flat.TFrame")
        bar.pack(fill="x")
        ttk.Label(bar, text="Defender" if mode == "into" else "Attacker", style="Panel.TLabel").pack(side="left")
        var = tk.StringVar()
        cb = ttk.Combobox(bar, textvariable=var, state="readonly", width=44)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        # the tests shown for each unit: its best, its worst, their average (the "Attacker tests" choice of
        # the top bar, which this sets and follows), or every one of them
        ttk.Label(bar, text="Tests", style="Panel.TLabel").pack(side="left", padx=(18, 0))
        shown = tk.StringVar(value=self._tests_shown())
        pick = ttk.Combobox(bar, textvariable=shown, values=list(self.TESTS_SHOWN), state="readonly", width=12)
        pick.pack(side="left", padx=6)
        pick.bind("<<ComboboxSelected>>", lambda e, shown=shown: self._on_tests_shown(shown.get()))
        hint = ttk.Label(tab, text="Best first, from the left. Click a stem to hide it: the unit's next best test "
                                   "takes its place. Totals are stacked Shooting + Fight. Whiskers: 90% of games "
                                   "(one test only).",
                         style="Muted.TLabel")
        hint.pack(anchor="w", pady=(4, 2))
        chart = StemChart(tab, on_click=lambda key, m=mode: self._rank_hide(m, key))
        chart.pack(fill="both", expand=True)
        setattr(self, f"rank_{mode}", (var, cb, shown, chart))

    TESTS_SHOWN = {"Best": "best", "Worst": "worst", "All": None, "Average": "mean"}     # None: every test

    def _tests_shown(self) -> str:
        """The "Attacker tests" choice of the top bar, as the ranking tabs name it."""
        return _inv(self.TESTS_SHOWN)[self.am]

    def _on_tests_shown(self, choice: str):
        """A ranking tab's choice of tests. Best, Worst and Average are the top bar's "Attacker tests": set
        there, for every view; All only spreads this tab's units into their tests."""
        mode = self.TESTS_SHOWN[choice]
        if mode:
            self.att_mode.set(ATT_MODES[mode])
        self.refresh()

    def _refresh_rank(self, mode: str):
        var, cb, shown, chart = getattr(self, f"rank_{mode}")
        every = self.TESTS_SHOWN.get(shown.get(), "best") is None
        if not every:
            shown.set(self._tests_shown())      # follows the top bar
        m = METRICS[self.metric_key]
        vis = self.rs.visible()
        pivots = list(dict.fromkeys((r.defender if mode == "into" else r.attacker) for r in vis))
        cb.configure(values=pivots)
        if var.get() not in pivots:
            var.set(pivots[0] if pivots else "")
        pivot = var.get()
        groups = self.rs.by_pair(vis)
        items: list[BarItem] = []
        others = list(dict.fromkeys((r.attacker if mode == "into" else r.defender) for r in vis))
        for o in others:
            a, d = (o, pivot) if mode == "into" else (pivot, o)
            recs = groups.get((a, d))
            if not recs:
                continue
            if every:
                for ph, test, agg in self.rs.scenarios(a, d, m.key, self.dm, recs, self.phase):
                    items.append(self._agg_bar(agg, m, o, f"{ph} · {test}", ("records", tuple(agg.records))))
            else:
                agg = self.rs.pair(a, d, m.key, self.am, self.dm, recs, self.phase)
                if not agg:
                    continue
                if agg.parts:
                    bi = self._total_bar(agg, m, o, a, d)
                elif agg.record:
                    rep = agg.record
                    prefix = {"best": "best: ", "worst": "worst: "}.get(self.am, "")
                    bi = self._agg_bar(agg, m, o, f"{prefix}{rep.phase} · {rep.att_test}",
                                       ("best", a, d, rep.phase, rep.att_test))
                else:
                    bi = BarItem(("pair", a, d), o, agg.value, color=MIXED, sublabel="average of tests",
                                 tip=[f"{a}  →  {d}", f"{m.label}: {m.fmt(agg.value)} (average)", "click to hide"])
                items.append(bi)
        items.sort(key=lambda it: -it.value)
        chart.set_data(items, fmt=m.fmt, legend=LEGEND + ([("average", MIXED)] if self.am == "mean" else []),
                       empty_text="Nothing to show: all tests are filtered out or hidden.")

    def _rank_hide(self, mode: str, key):
        vis = self.rs.visible()
        if isinstance(key, TestRecord):
            self.hide([key])
        elif key[0] == "records":
            self.hide(list(key[1]))
        elif key[0] == "best":                  # hide that test of the pair (all defender tests)
            _, a, d, ph, test = key
            self.hide([r for r in vis if r.attacker == a and r.defender == d and r.phase == ph and r.att_test == test])
        elif key[0] == "tests":                 # a total: hide the test behind each phase
            _, a, d, tests = key
            self.hide([r for r in vis if r.attacker == a and r.defender == d and (r.phase, r.att_test) in tests])
        elif key[0] == "pair":
            _, a, d = key
            self.hide([r for r in vis if r.attacker == a and r.defender == d])

    # ------------------------------------------------------------------ table tab
    COLS = [("on", "✓", 26), ("attacker", "Attacker", -170), ("defender", "Defender", -150), ("phase", "Phase", 64),
            ("att_test", "Attacker test", -130), ("def_test", "Defender test", -110), ("dmg_mean", "Dmg", 50),
            ("slain_mean", "Slain", 50), ("frac_wounds", "Wounds %", 64), ("p_wipe", "Destroyed", 70),
            ("pts_removed", "Pts", 50), ("pts_per_100", "Pts/100", 60)]

    def _build_table_tab(self):
        tab = ttk.Frame(self.nb, style="Panel.TFrame", padding=8)
        self.nb.add(tab, text="All tests")
        ttk.Label(tab, text="Every test that passes the filters. Click ✓ to hide / show a row, click a header to sort.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        f, self.table = make_tree(tab, [(k, t) for k, t, _ in self.COLS], [w for _, _, w in self.COLS], height=20)
        f.pack(fill="both", expand=True)
        self.table.tag_configure("hidden", foreground=C["dim"])
        for k, t, _ in self.COLS:
            if k != "on":
                self.table.heading(k, text=t, command=lambda k=k: self._sort(k))
        self.table.bind("<ButtonRelease-1>", self._table_click)
        self._sort_key, self._sort_desc = "dmg_mean", True

    def _sort(self, key):
        self._sort_desc = not self._sort_desc if key == self._sort_key else key not in (
            "attacker", "defender", "phase", "att_test", "def_test")
        self._sort_key = key
        self._refresh_table()

    def _refresh_table(self):
        t = self.table
        t.delete(*t.get_children())
        rows = [r for r in self.rs.records if self.rs.passes_filters(r)]
        rows.sort(key=lambda r: getattr(r, self._sort_key), reverse=self._sort_desc)
        for r in rows:
            hidden = r.id in self.rs.hidden
            t.insert("", "end", iid=str(r.id), tags=("hidden",) if hidden else (),
                     values=("" if hidden else "✓", r.attacker, r.defender, r.phase, r.att_test, r.def_test,
                             f"{r.dmg_mean:.1f}", f"{r.slain_mean:.1f}", f"{r.frac_wounds:.0%}", f"{r.p_wipe:.0%}",
                             f"{r.pts_removed:.0f}", f"{r.pts_per_100:.1f}"))

    def _table_click(self, e):
        row, col = self.table.identify_row(e.y), self.table.identify_column(e.x)
        if row and col == "#1" and self.table.identify_region(e.x, e.y) == "cell":
            self.rs.hidden.symmetric_difference_update({int(row)})
            self.refresh()

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        vis = self.rs.visible()
        n_hidden = len(self.rs.hidden)
        self.count_lbl.configure(text=f"{len(vis):,} of {len(self.rs.records):,} tests shown"
                                      + (f" · {n_hidden:,} hidden" if n_hidden else ""))
        self.unhide_btn.state(["!disabled"] if n_hidden else ["disabled"])
        tab = self.nb.index("current") if self.nb.tabs() else 0
        if tab == 0:
            self._refresh_plan()
        else:
            self._schedule_plan()           # keep the saved army plan up to date, whatever is on show
        if tab == 1:
            self._refresh_matrix()
        elif tab == 2:
            self._refresh_rank("into")
        elif tab == 3:
            self._refresh_rank("from")
        elif tab == 4:
            self._refresh_table()
