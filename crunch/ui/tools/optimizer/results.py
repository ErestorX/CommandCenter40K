"""Results explorer for the Optimizer: matrix, rankings and a table, with filters and hideable
data points. Every view reads the same ResultSet, so hiding or filtering applies everywhere."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from crunch.analysis.results import ATT_MODES, DEF_MODES, DIMS, METRICS, Agg, ResultSet
from crunch.analysis.sweep import TestRecord, to_csv
from crunch.ui.charts import INK_3, SLOTS, BarChart, BarItem, Heatmap
from crunch.ui.theme import C
from crunch.ui.widgets import make_tree

if TYPE_CHECKING:
    from crunch.ui.registry import Selection

PHASE_COLOR = {"Shooting": SLOTS[0], "Fight": SLOTS[1]}
LEGEND = [("Shooting", SLOTS[0]), ("Fight", SLOTS[1])]
MIXED = INK_3


def _inv(d: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in d.items()}


class ResultsWindow(tk.Toplevel):
    def __init__(self, master, records: list[TestRecord], selection: "Selection"):
        super().__init__(master)
        self.title(f"Game Crunch — Optimizer results ({len(records):,} tests)")
        self.configure(bg=C["bg"])
        self.geometry("1500x900")
        self.minsize(1100, 700)
        self.rs = ResultSet(records)
        self.selection = selection
        self.pair_selected: tuple[str, str] | None = None

        # ---- top bar -------------------------------------------------------------------------
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.metric = tk.StringVar(value=METRICS["dmg_mean"].label)
        self.att_mode = tk.StringVar(value=ATT_MODES["best"])
        self.def_mode = tk.StringVar(value=DEF_MODES["mean"])
        for label, var, values, w in (("Metric", self.metric, [m.label for m in METRICS.values()], 26),
                                      ("Attacker scenarios", self.att_mode, list(ATT_MODES.values()), 26),
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
        self.filters.tag_configure("off", foreground="#a9a49a")
        self.filters.tag_configure("dim", font=("TkDefaultFont", 9, "bold"))
        self.filters.bind("<ButtonRelease-1>", self._toggle_filter)
        body.add(side, weight=1)

        self.nb = ttk.Notebook(body)
        body.add(self.nb, weight=5)
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
        atts, defs, cells = self.rs.matrix(self.metric_key, self.am, self.dm)
        values = [[c.value if c else None for c in row] for row in cells]
        tips = [[self._cell_tip(a, d, c, m) for d, c in zip(defs, row)] for a, row in zip(atts, cells)]
        self._matrix_cache = (atts, defs, cells)
        self.matrix_title.configure(text=f"{m.label} — {self.att_mode.get().lower()}, "
                                         f"{self.def_mode.get().lower()}")
        self.heat.set_data(atts, defs, values, tips, fmt=m.fmt, caption=m.label)
        self._refresh_detail()

    @staticmethod
    def _scenario_text(r: TestRecord) -> str:
        return f"{r.phase} · {r.att_test} (vs {r.def_test})"

    def _cell_tip(self, a, d, agg: Agg | None, m) -> list[str]:
        if not agg:
            return [f"{a}  →  {d}", "no visible tests"]
        lines = [f"{a}  →  {d}", f"{m.label}: {m.fmt(agg.value)}"]
        if agg.record:
            r = agg.record
            lines.append(f"from: {r.phase} · {r.att_test}" + (f" (vs {r.def_test})" if agg.exact else
                                                                " (averaged over defender tests)"))
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
        recs = [r for r in self.rs.visible() if r.attacker == a and r.defender == d]
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
        expand = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Every scenario (not just each unit's best)", variable=expand,
                        style="Panel.TCheckbutton", command=self.refresh).pack(side="left", padx=12)
        hint = ttk.Label(tab, text="Click a bar to hide it: the unit's next scenario takes its place. "
                                   "Whiskers: 90% of games (best/worst modes).", style="Muted.TLabel")
        hint.pack(anchor="w", pady=(4, 2))
        chart = BarChart(tab, on_click=lambda key, m=mode: self._rank_hide(m, key))
        chart.pack(fill="both", expand=True)
        setattr(self, f"rank_{mode}", (var, cb, expand, chart))

    def _refresh_rank(self, mode: str):
        var, cb, expand, chart = getattr(self, f"rank_{mode}")
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
            if expand.get():
                for ph, test, agg in self.rs.scenarios(a, d, m.key, self.dm, recs):
                    items.append(self._agg_bar(agg, m, o, f"{ph} · {test}", ("records", tuple(agg.records))))
            else:
                agg = self.rs.pair(a, d, m.key, self.am, self.dm, recs)
                if agg.record:
                    rep = agg.record
                    prefix = {"best": "best: ", "worst": "worst: "}.get(self.am, "")
                    bi = self._agg_bar(agg, m, o, f"{prefix}{rep.phase} · {rep.att_test}",
                                       ("best", a, d, rep.phase, rep.att_test))
                else:
                    bi = BarItem(("pair", a, d), o, agg.value, color=MIXED, sublabel="average of scenarios",
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
        elif key[0] == "best":                  # hide that scenario of the pair (all defender tests)
            _, a, d, ph, test = key
            self.hide([r for r in vis if r.attacker == a and r.defender == d and r.phase == ph and r.att_test == test])
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
        self.table.tag_configure("hidden", foreground="#b3aea4")
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
            self._refresh_matrix()
        elif tab == 1:
            self._refresh_rank("into")
        elif tab == 2:
            self._refresh_rank("from")
        else:
            self._refresh_table()
