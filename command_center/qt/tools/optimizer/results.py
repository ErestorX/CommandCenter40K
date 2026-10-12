"""Results explorer for the Engagement Optimizer: army plan, matrix, rankings and a table, with filters and hideable
data points. Every view reads the same ResultSet, so hiding or filtering applies everywhere.
The matrix and rankings show one phase, or the total of both (Shooting + Fight)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QSlider, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from command_center.analysis.army_plans import PlanEntry, PlanTarget, SavedPlan, units_of
from command_center.analysis.assign import plan_army
from command_center.analysis.results import ATT_MODES, DEF_MODES, DIMS, METRICS, PHASE_VIEWS, TOTAL, Agg, ResultSet
from command_center.analysis.sweep import TestRecord, to_csv
from command_center.qt.charts import INK_3, SLOTS, BarChart, BarItem, Heatmap, StemChart
from command_center.qt.screen import screen_height
from command_center.qt.theme import C
from command_center.qt.widgets import Combo, Panel, Table, button, label

if TYPE_CHECKING:
    from command_center.qt.registry import Selection
    from command_center.qt.tools.optimizer.window import OptimizerWindow

PHASE_COLOR = {"Shooting": SLOTS[0], "Fight": SLOTS[1]}
LEGEND = [("Shooting", SLOTS[0]), ("Fight", SLOTS[1])]
MIXED = INK_3
PLAN_DELAY = 250            # ms after the last change before the army plan is made again
PLAN, MATRIX, INTO, FROM, TABLE = range(5)        # the tabs, in their order
FILTERS_WIDTH = 290         # the filters' panel, to begin with: its edge can be dragged


def _inv(d: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in d.items()}


def _tab(margin: int = 8) -> tuple[QWidget, QVBoxLayout]:
    tab = QWidget()
    col = QVBoxLayout(tab)
    col.setContentsMargins(margin, margin, margin, margin)
    col.setSpacing(0)
    return tab, col


class ResultsWindow(QWidget):
    def __init__(self, parent: "OptimizerWindow", records: list[TestRecord], selection: "Selection"):
        super().__init__(parent, Qt.Window)             # a window of its own, above the Optimizer's
        self.setWindowTitle(f"Command Center 40K — Engagement Optimizer results ({len(records):,} tests)")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(1100)
        screen_height(self, 1500, parent)
        self.rs = ResultSet(records)
        self.selection = selection
        self.plans = parent.ctx.army_plans          # the army plan is saved there for other windows
        saved = self.plans.get(selection.attacker.path, selection.defender.path)
        self._saved = saved.settings if saved else {}   # reopening shows (and keeps) the saved plan
        self.pair_selected: tuple[str, str] | None = None
        self._ready = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        # ---- top bar -------------------------------------------------------------------------
        top = QHBoxLayout()
        top.setSpacing(4)

        def choice(text: str, values: list[str], chosen: str) -> Combo:
            top.addWidget(label(text))
            cb = Combo()
            cb.addItems(values)
            cb.setCurrentText(chosen)
            cb.activated.connect(lambda _i: self.refresh())
            top.addWidget(cb)
            top.addSpacing(10)
            return cb
        self.phase_view = choice("Phase", list(PHASE_VIEWS.values()),
                                 PHASE_VIEWS.get(self._saved.get("phase"), PHASE_VIEWS[TOTAL]))
        self.metric_box = choice("Metric", [m.label for m in METRICS.values()], METRICS["dmg_mean"].label)
        self.att_mode = choice("Attacker tests", list(ATT_MODES.values()),
                               ATT_MODES.get(self._saved.get("attacker_tests"), ATT_MODES["best"]))
        self.def_mode = choice("Defender tests", list(DEF_MODES.values()),
                               DEF_MODES.get(self._saved.get("defender_tests"), DEF_MODES["mean"]))
        top.addStretch(1)
        self.count_lbl = label("", "muted")
        top.addWidget(self.count_lbl)
        top.addSpacing(10)
        self.unhide_btn = button("Show hidden", self.unhide)
        top.addWidget(self.unhide_btn)
        top.addWidget(button("Export CSV…", self.export))
        outer.addLayout(top)

        # ---- body: filters | views ---------------------------------------------------------------
        body = QSplitter(Qt.Horizontal)
        outer.addWidget(body, 1)
        side = Panel()
        col = QVBoxLayout(side)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(0)
        col.addWidget(label("Filters", "h2"))
        col.addWidget(label("Click to include / exclude", "muted"))
        col.addSpacing(4)
        self.filters = QTreeWidget()
        self.filters.setHeaderHidden(True)
        self.filters.setSelectionMode(QTreeWidget.NoSelection)
        self.filters.setFocusPolicy(Qt.NoFocus)
        self.filters.itemClicked.connect(lambda item, _col: self.toggle_filter(*item.data(0, Qt.UserRole)))
        col.addWidget(self.filters, 1)
        body.addWidget(side)

        self.nb = QTabWidget()
        body.addWidget(self.nb)
        body.setStretchFactor(1, 1)                     # the views take what a wider window adds
        body.setSizes([FILTERS_WIDTH, 10 * FILTERS_WIDTH])
        self._build_plan_tab()
        self._build_matrix_tab()
        self._build_rank_tab("into")
        self._build_rank_tab("from")
        self._build_table_tab()
        self.nb.currentChanged.connect(lambda _i: self.refresh())

        self._fill_filters()
        self._ready = True
        self.refresh()

    # ------------------------------------------------------------------ settings
    @property
    def metric_key(self) -> str:
        return next(k for k, m in METRICS.items() if m.label == self.metric_box.currentText())

    @property
    def phase(self) -> str:
        return _inv(PHASE_VIEWS)[self.phase_view.currentText()]

    @property
    def am(self) -> str:
        return _inv(ATT_MODES)[self.att_mode.currentText()]

    @property
    def dm(self) -> str:
        return _inv(DEF_MODES)[self.def_mode.currentText()]

    # ------------------------------------------------------------------ filters
    def _fill_filters(self):
        t = self.filters
        t.clear()
        self._filter_items: dict[tuple, QTreeWidgetItem] = {}
        bold = QFont(t.font())
        bold.setBold(True)
        for dim, title in DIMS.items():
            head = self._filter_items[dim, None] = QTreeWidgetItem([title])
            head.setData(0, Qt.UserRole, (dim, None))
            head.setFont(0, bold)
            t.addTopLevelItem(head)
            for v in self.rs.values(dim):
                item = self._filter_items[dim, v] = QTreeWidgetItem([v])
                item.setToolTip(0, v)                   # in full: a test's name is often wider than the panel
                item.setData(0, Qt.UserRole, (dim, v))
                head.addChild(item)
            head.setExpanded(True)
        self._paint_filters()

    def _paint_filters(self):
        for dim, title in DIMS.items():
            vals = self.rs.values(dim)
            ex = self.rs.excluded[dim]
            mark = "☑" if not ex else ("☐" if len(ex) >= len(vals) else "◐")
            self._filter_items[dim, None].setText(0, f"{mark}  {title}")
            for v in vals:
                on = v not in ex
                item = self._filter_items[dim, v]
                item.setText(0, f"{'☑' if on else '☐'}  {v}")
                item.setForeground(0, QColor(C["ink"] if on else C["dim"]))

    def toggle_filter(self, dim: str, value: str | None):
        """Include or exclude a value of a filter; with no value, every value of the filter at once."""
        ex = self.rs.excluded[dim]
        if value is not None:
            ex.symmetric_difference_update({value})
        elif ex:
            ex.clear()
        else:
            ex.update(self.rs.values(dim))
        self._paint_filters()
        self.refresh()

    # ------------------------------------------------------------------ hiding
    def hide_records(self, records: list[TestRecord]):
        self.rs.hidden.update(r.id for r in records)
        self.refresh()

    def unhide(self):
        self.rs.hidden.clear()
        self.refresh()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export the tests shown", "optimizer_results.csv", "CSV (*.csv)")
        if path:
            to_csv(self.rs.visible(), path)

    # ------------------------------------------------------------------ army plan tab
    WEIGHT_STEP = 10        # the "Guide by" slider moves by this many percent

    def _build_plan_tab(self):
        tab, col = _tab()
        self.nb.addTab(tab, "Army plan")
        self.plan_title = label("", "h2")
        col.addWidget(self.plan_title)
        col.addWidget(label("Each attacker gets a 1st target (its priority) and a 2nd target (worth half), so that "
                            "every defender is targeted at least once. Attackers sent at the same unit share it: "
                            "what goes beyond its wounds counts for nothing. Uses the Phase, attacker tests and "
                            "defender tests chosen above, and skips hidden or filtered-out tests.", "muted", wrap=True))
        col.addSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(label("Guide by:  points removed per 100 pts"))
        self.plan_slider = QSlider(Qt.Horizontal)              # one notch per step: it can only stand on a step
        self.plan_slider.setRange(0, 100 // self.WEIGHT_STEP)
        self.plan_slider.setPageStep(1)
        self.plan_slider.setFixedWidth(260)
        self.plan_slider.setValue(round(100 * self._saved.get("weight", 0.5) / self.WEIGHT_STEP))
        self.plan_slider.valueChanged.connect(lambda _v: self._schedule_plan())
        bar.addWidget(self.plan_slider)
        bar.addWidget(label("share of the unit's wounds"))
        self.weight_lbl = label("", "muted")
        bar.addWidget(self.weight_lbl)
        bar.addStretch(1)
        col.addLayout(bar)
        col.addSpacing(4)
        self.plan_summary = label("")
        col.addWidget(self.plan_summary)
        col.addSpacing(4)

        pw = QSplitter(Qt.Vertical)
        col.addWidget(pw, 1)
        top, tcol = _tab(0)
        tcol.addWidget(label("By attacker", "muted"))
        self.plan_atts = Table([("att", "Attacker"), ("t1", "1st target"), ("w1", "Wounds"), ("p1", "Pts/100"),
                                ("t2", "2nd target"), ("w2", "Wounds"), ("p2", "Pts/100")],
                               [-230, -230, 64, 64, -230, 64, 64], rows=6, selectable=False)
        tcol.addWidget(self.plan_atts, 1)
        pw.addWidget(top)
        bottom, bcol = _tab(0)
        bcol.addWidget(label("By defender (wounds: expected share of the unit's wounds removed by the attackers sent at it)",
                             "muted"))
        self.plan_defs = Table([("def", "Defender"), ("pts", "Pts"), ("by1", "1st target of"), ("w1", "Wounds"),
                                ("by2", "2nd target of"), ("w2", "Wounds")], [-230, 50, -260, 64, -260, 64], rows=6,
                               selectable=False)
        bcol.addWidget(self.plan_defs, 1)
        pw.addWidget(bottom)
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.timeout.connect(self._refresh_plan)

    @property
    def weight(self) -> int:
        """The "Guide by" slider's position: the percentage given to the share of the unit's wounds."""
        return self.plan_slider.value() * self.WEIGHT_STEP

    def _schedule_plan(self):
        self.weight_lbl.setText(self._weight_text())
        self._plan_timer.start(PLAN_DELAY)

    def _weight_text(self) -> str:
        return f"{self.weight}% wounds · {100 - self.weight}% points"

    def _refresh_plan(self):
        self._plan_timer.stop()
        self.weight_lbl.setText(self._weight_text())
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
        plan = plan_army(atts, defs, frac, ppp, self.weight / 100)
        self._save_plan(plan, frac, ppp)
        self.plan_title.setText(f"Army plan: {self.phase_view.currentText()}, {self.att_mode.currentText().lower()}, "
                                f"{self.def_mode.currentText().lower()}")
        n_def = len(defs)
        if not atts or not defs:
            summary = "Nothing to plan: all tests are filtered out or hidden."
        elif plan.uncovered:
            summary = (f"{len(plan.uncovered)} of {n_def} defenders left out: {len(atts)} attackers x 2 targets "
                       f"can't reach them all ({', '.join(plan.uncovered)}).")
        else:
            summary = f"All {n_def} defenders are targeted by the {len(atts)} attackers."
        self.plan_summary.setText(summary)

        pct = lambda v: f"{v:.0%}"
        t = self.plan_atts
        t.clear_rows()
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
            t.add_row(row)
        t = self.plan_defs
        t.clear_rows()
        for d in sorted(defs, key=lambda d: -def_pts[d]):
            w1 = sum(frac[a, d] for a in first[d])
            w2 = sum(frac[a, d] for a in second[d])
            # no attacker sent at it: muted; more than its wounds from its 1st attackers: a warning
            color = C["muted"] if not first[d] and not second[d] else (C["warn"] if w1 > 1 else None)
            t.add_row((d, def_pts[d], ", ".join(first[d]) or "–", pct(w1) if first[d] else "",
                       ", ".join(second[d]) or "–", pct(w2) if second[d] else ""), color=color)

    def _save_plan(self, plan, frac: dict, ppp: dict):
        """Keep the plan of this pair of lists up to date in the shared store (and on disk)."""
        def target(a, d):
            return PlanTarget(d, units_of(d), round(frac[a, d], 4), round(ppp[a, d], 2)) if d else None
        entries = [PlanEntry(s.attacker, units_of(s.attacker), target(s.attacker, s.primary),
                             target(s.attacker, s.secondary)) for s in plan.assignments]
        self.plans.put(SavedPlan(
            self.selection.attacker.path.name, self.selection.defender.path.name, entries, list(plan.uncovered),
            {"phase": self.phase, "attacker_tests": self.am, "defender_tests": self.dm,
             "weight": round(self.weight / 100, 3)}))

    # ------------------------------------------------------------------ matrix tab
    def _build_matrix_tab(self):
        tab, col = _tab()
        self.nb.addTab(tab, "Matrix")
        self.matrix_title = label("", "h2")
        col.addWidget(self.matrix_title)
        col.addWidget(label("Rows: attackers · columns: defenders. Hover for details, click a cell to list every "
                            "test behind it, right-click a cell to hide that pairing.", "muted"))
        col.addSpacing(4)
        pw = QSplitter(Qt.Vertical)
        col.addWidget(pw, 1)
        self.heat = Heatmap(on_click=self._cell_click, on_right_click=self._cell_hide)
        pw.addWidget(self.heat)
        detail, dcol = _tab(0)
        self.detail_title = label("Click a cell to see its tests.", "muted")
        dcol.addWidget(self.detail_title)
        dcol.addSpacing(2)
        self.detail = BarChart(on_click=lambda key: self.hide_records([key]))
        dcol.addWidget(self.detail, 1)
        pw.addWidget(detail)
        pw.setSizes([3000, 2000])                       # shares of the height: three fifths to the matrix
        self._matrix_cache = None

    def _refresh_matrix(self):
        m = METRICS[self.metric_key]
        atts, defs, cells = self.rs.matrix(self.metric_key, self.am, self.dm, self.phase)
        values = [[c.value if c else None for c in row] for row in cells]
        tips = [[self._cell_tip(a, d, c, m) for d, c in zip(defs, row)] for a, row in zip(atts, cells)]
        self._matrix_cache = (atts, defs, cells)
        self.matrix_title.setText(f"{self.phase_view.currentText()}: {m.label} — {self.att_mode.currentText().lower()}, "
                                  f"{self.def_mode.currentText().lower()}")
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
            self.hide_records(cells[i][j].records)

    def _refresh_detail(self):
        if not self.pair_selected:
            self.detail.set_data([], empty_text="Click a cell to list its tests.")
            return
        a, d = self.pair_selected
        m = METRICS[self.metric_key]
        recs = [r for r in self.rs.visible() if r.attacker == a and r.defender == d
                and self.phase in (TOTAL, r.phase)]
        recs.sort(key=lambda r: -getattr(r, m.key))
        self.detail_title.setText(f"{a}  →  {d}: every visible test (click a bar to hide it)")
        self.detail.set_data([self._bar(r, m, f"{r.phase} · {r.att_test}", f"vs {r.def_test}") for r in recs],
                             fmt=m.fmt, legend=LEGEND, empty_text="All tests of this pairing are hidden.")

    def _bar(self, r: TestRecord, m, text: str, sub: str, key=None, value=None) -> BarItem:
        v = getattr(r, m.key) if value is None else value
        lo = getattr(r, m.lo) if m.lo and value is None else None
        hi = getattr(r, m.hi) if m.hi and value is None else None
        tip = [f"{r.attacker}  →  {r.defender}", f"{r.phase} · {r.att_test} · defender: {r.def_test}",
               f"{m.label}: {m.fmt(v)}" + (f"  (90% of games: {m.fmt(lo)}–{m.fmt(hi)})" if lo is not None else ""),
               f"damage {r.dmg_mean:.1f} · slain {r.slain_mean:.1f}/{r.models} · destroyed {r.p_wipe:.0%}",
               f"points removed {r.pts_removed:.0f} of {r.def_points} ({r.pts_per_100:.1f} per 100 pts)",
               "click to hide"]
        return BarItem(key if key is not None else r, text, v, lo, hi, PHASE_COLOR.get(r.phase, MIXED), sub, tip)

    def _agg_bar(self, agg: Agg, m, text: str, sub: str, key) -> BarItem:
        """Bar for an aggregated value; the spread is only shown when the value is one exact test."""
        bi = self._bar(agg.record, m, text, sub, key=key)
        if not agg.exact:
            bi.value, bi.lo, bi.hi = agg.value, None, None
            bi.tip[1] = f"{agg.record.phase} · {agg.record.att_test} · over {len(agg.records)} defender test(s)"
            bi.tip[2] = f"{m.label}: {m.fmt(agg.value)} (average)"
            bi.tip[3:5] = ["tests: " + ", ".join(sorted({r.def_test for r in agg.records}))]
        return bi

    def _total_bar(self, agg: Agg, m, text: str, a: str, d: str) -> BarItem:
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
        return BarItem(key, text, agg.value, color=MIXED, sublabel=sub, tip=tip,
                       segments=[(p.value / whole, PHASE_COLOR[ph]) for ph, p in agg.parts.items()])

    # ------------------------------------------------------------------ ranking tabs
    TESTS_SHOWN = {"Best": "best", "Worst": "worst", "All": None, "Average": "mean"}     # None: every test

    def _build_rank_tab(self, mode: str):
        tab, col = _tab()
        self.nb.addTab(tab, "Best attackers into…" if mode == "into" else "Best targets for…")
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(label("Defender" if mode == "into" else "Attacker"))
        pivot = Combo()
        pivot.setMinimumContentsLength(40)
        pivot.activated.connect(lambda _i: self.refresh())
        bar.addWidget(pivot)
        # the tests shown for each unit: its best, its worst, their average (the "Attacker tests" choice of
        # the top bar, which this sets and follows), or every one of them
        bar.addSpacing(12)
        bar.addWidget(label("Tests"))
        shown = Combo()
        shown.addItems(list(self.TESTS_SHOWN))
        shown.setCurrentText(self._tests_shown())
        shown.activated.connect(lambda _i, shown=shown: self.show_tests(shown.currentText()))
        bar.addWidget(shown)
        bar.addStretch(1)
        col.addLayout(bar)
        col.addSpacing(4)
        col.addWidget(label("Best first, from the left. Click a stem to hide it: the unit's next best test "
                            "takes its place. Totals are stacked Shooting + Fight. Whiskers: 90% of games "
                            "(one test only).", "muted"))
        col.addSpacing(2)
        chart = StemChart(on_click=lambda key, m=mode: self._rank_hide(m, key))
        col.addWidget(chart, 1)
        setattr(self, f"rank_{mode}", (pivot, shown, chart))

    def _tests_shown(self) -> str:
        """The "Attacker tests" choice of the top bar, as the ranking tabs name it."""
        return _inv(self.TESTS_SHOWN)[self.am]

    def show_tests(self, choice: str):
        """A ranking tab's choice of tests. Best, Worst and Average are the top bar's "Attacker tests": set
        there, for every view; All only spreads this tab's units into their tests."""
        mode = self.TESTS_SHOWN[choice]
        if mode:
            self.att_mode.setCurrentText(ATT_MODES[mode])
        self.refresh()

    def _refresh_rank(self, mode: str):
        pivot_box, shown, chart = getattr(self, f"rank_{mode}")
        every = self.TESTS_SHOWN.get(shown.currentText(), "best") is None
        if not every:
            shown.setCurrentText(self._tests_shown())      # follows the top bar
        m = METRICS[self.metric_key]
        vis = self.rs.visible()
        pivots = list(dict.fromkeys((r.defender if mode == "into" else r.attacker) for r in vis))
        pivot = pivot_box.currentText()
        pivot_box.clear()
        pivot_box.addItems(pivots)
        if pivot not in pivots:
            pivot = pivots[0] if pivots else ""
        pivot_box.setCurrentText(pivot)
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
            self.hide_records([key])
        elif key[0] == "records":
            self.hide_records(list(key[1]))
        elif key[0] == "best":                  # hide that test of the pair (all defender tests)
            _, a, d, ph, test = key
            self.hide_records([r for r in vis if r.attacker == a and r.defender == d and r.phase == ph
                               and r.att_test == test])
        elif key[0] == "tests":                 # a total: hide the test behind each phase
            _, a, d, tests = key
            self.hide_records([r for r in vis if r.attacker == a and r.defender == d and (r.phase, r.att_test) in tests])
        elif key[0] == "pair":
            _, a, d = key
            self.hide_records([r for r in vis if r.attacker == a and r.defender == d])

    # ------------------------------------------------------------------ table tab
    COLS = [("on", "✓", 26), ("attacker", "Attacker", -170), ("defender", "Defender", -150), ("phase", "Phase", 64),
            ("att_test", "Attacker test", -130), ("def_test", "Defender test", -110), ("dmg_mean", "Dmg", 50),
            ("slain_mean", "Slain", 50), ("frac_wounds", "Wounds %", 64), ("p_wipe", "Destroyed", 70),
            ("pts_removed", "Pts", 50), ("pts_per_100", "Pts/100", 60)]

    def _build_table_tab(self):
        tab, col = _tab()
        self.nb.addTab(tab, "All tests")
        col.addWidget(label("Every test that passes the filters. Click ✓ to hide / show a row, click a header to sort.",
                            "muted"))
        col.addSpacing(4)
        self.table = Table([(k, t) for k, t, _ in self.COLS], [w for _, _, w in self.COLS], rows=12, selectable=False)
        self.table.sort_by_heading(lambda column: self.sort(self.COLS[column][0]))
        self.table.itemClicked.connect(self._table_click)
        col.addWidget(self.table, 1)
        self._sort_key, self._sort_desc = "dmg_mean", True

    def sort(self, key: str):
        """Sort the table by a column: a second time, the other way round."""
        if key == "on":
            return
        self._sort_desc = not self._sort_desc if key == self._sort_key else key not in (
            "attacker", "defender", "phase", "att_test", "def_test")
        self._sort_key = key
        self._refresh_table()

    def _refresh_table(self):
        t = self.table
        t.clear_rows()
        rows = [r for r in self.rs.records if self.rs.passes_filters(r)]
        rows.sort(key=lambda r: getattr(r, self._sort_key), reverse=self._sort_desc)
        for r in rows:
            hidden = r.id in self.rs.hidden
            t.add_row(("" if hidden else "✓", r.attacker, r.defender, r.phase, r.att_test, r.def_test,
                       f"{r.dmg_mean:.1f}", f"{r.slain_mean:.1f}", f"{r.frac_wounds:.0%}", f"{r.p_wipe:.0%}",
                       f"{r.pts_removed:.0f}", f"{r.pts_per_100:.1f}"), key=r.id, color=C["dim"] if hidden else None)

    def _table_click(self, item, column: int):
        if column == 0:
            self.toggle_hidden(item.data(0, Qt.UserRole))

    def toggle_hidden(self, record_id: int):
        self.rs.hidden.symmetric_difference_update({record_id})
        self.refresh()

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        if not self._ready:
            return
        vis = self.rs.visible()
        n_hidden = len(self.rs.hidden)
        self.count_lbl.setText(f"{len(vis):,} of {len(self.rs.records):,} tests shown"
                               + (f" · {n_hidden:,} hidden" if n_hidden else ""))
        self.unhide_btn.setEnabled(bool(n_hidden))
        tab = self.nb.currentIndex()
        if tab == PLAN:
            self._refresh_plan()
        else:
            self._schedule_plan()           # keep the saved army plan up to date, whatever is on show
        if tab == MATRIX:
            self._refresh_matrix()
        elif tab == INTO:
            self._refresh_rank("into")
        elif tab == FROM:
            self._refresh_rank("from")
        elif tab == TABLE:
            self._refresh_table()
