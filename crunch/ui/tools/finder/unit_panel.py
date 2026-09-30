"""One side of the Unit finder: an army list with include toggles, the selected unit's details, and
its test plan (which scenarios are tried)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.analysis.plan import (ATTACKER, DEFAULT, NONE, UnitPlan, all_loads, default_on, resolve_attached,
                                  test_count, weapon_key)
from crunch.analysis.variants import ATTACKER_VARIANTS, DEFENDER_VARIANTS, MELEE, PHASES, RANGED
from crunch.lists import ArmyList, ListUnit, target_for
from crunch.ui.theme import C
from crunch.ui.views.rules import show_army_rules, show_unit_abilities
from crunch.ui.widgets import EyeButton, make_tree

if TYPE_CHECKING:
    from crunch.ui.tools.finder.window import FinderWindow

ON, OFF, NA = "✓", "·", ""


class UnitPlanPanel(ttk.Frame):
    def __init__(self, master, win: "FinderWindow", army: ArmyList, role: str):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win, self.army, self.role = win, army, role
        self.wd = win.ctx.wd
        self.store = win.store
        self.unit: ListUnit | None = None
        attacker = role == ATTACKER

        ttk.Label(self, text="ATTACKERS" if attacker else "DEFENDERS",
                  style="Att.TLabel" if attacker else "Def.TLabel").pack(anchor="w")
        ttk.Label(self, text=army.faction, style="H2.TLabel").pack(anchor="w")
        head = ttk.Frame(self, style="Flat.TFrame")
        head.pack(fill="x", pady=(0, 4))
        EyeButton(head, lambda: show_army_rules(self.win, self.win.ctx.rules, self.army),
                  "Army rules, detachment and stratagems").pack(side="right", anchor="n", padx=(6, 0))
        sub = f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else "")
        ttk.Label(head, text=sub, style="Muted.TLabel", wraplength=380).pack(side="left", anchor="w")

        bar = ttk.Frame(self, style="Flat.TFrame")
        bar.pack(fill="x", pady=(0, 2))
        ttk.Label(bar, text="Tick the units to test (click ✓)", style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="None", width=6, command=lambda: self._include_all(False)).pack(side="right")
        ttk.Button(bar, text="All", width=6, command=lambda: self._include_all(True)).pack(side="right", padx=4)

        f, self.units_tree = make_tree(self, [("on", "✓"), ("unit", "Unit"), ("pts", "Pts"), ("tests", "Tests")],
                                       [30, -200, 46, 46], height=7)
        f.pack(fill="both", expand=True)
        self.units_tree.tag_configure("off", foreground="#9a958b")
        for u in army.units:
            self.units_tree.insert("", "end", iid=str(u.uid))
            self._refresh_row(u)
        self.units_tree.bind("<ButtonRelease-1>", self._on_units_click)
        self.units_tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, pady=(6, 0))
        self._build_unit_tab(attacker)
        self._build_tests_tab(attacker)

        first = next((u for u in army.units if u.datasheet), None)
        if first:
            self.units_tree.selection_set(str(first.uid))

    # ------------------------------------------------------------------ units list
    def plan(self, u: ListUnit) -> UnitPlan:
        return self.store.get(self.army, self.role, u)

    def _refresh_row(self, u: ListUnit):
        p = self.plan(u)
        name = ("★ " if u.is_character else "") + u.label + ("" if u.datasheet else "  (no datasheet)")
        self.units_tree.item(str(u.uid), values=(ON if p.included else "", name, u.points, test_count(self.role, p)),
                             tags=() if p.included else ("off",))

    def _include_all(self, on: bool):
        for u in self.army.units:
            if u.datasheet:
                self.plan(u).included = on
                self._refresh_row(u)
        self.win.plans_changed()

    def _on_units_click(self, e):
        row, col = self.units_tree.identify_row(e.y), self.units_tree.identify_column(e.x)
        if not row or col != "#1":
            return
        u = self.army.unit(int(row))
        if not u.datasheet:
            return
        p = self.plan(u)
        p.included = not p.included
        self._refresh_row(u)
        self.win.plans_changed()

    def selected_units(self) -> list[ListUnit]:
        return [u for u in self.army.units if u.datasheet and self.plan(u).included]

    def _on_select(self):
        sel = self.units_tree.selection()
        if not sel:
            return
        self.unit = self.army.unit(int(sel[0]))
        self._load_unit()

    # ------------------------------------------------------------------ unit tab
    def _build_unit_tab(self, attacker: bool):
        tab = ttk.Frame(self.nb, style="Flat.TFrame", padding=6)
        self.nb.add(tab, text="Unit")
        grid = ttk.Frame(tab, style="Flat.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.attach_vars, self.attach_boxes = {}, {}
        for r, kind in enumerate(("leader", "support")):
            ttk.Label(grid, text=kind.title(), style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=1)
            v = tk.StringVar(value=DEFAULT)
            cb = ttk.Combobox(grid, textvariable=v, state="readonly", width=26)
            cb.grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e, k=kind: self._on_attach(k))
            self.attach_vars[kind], self.attach_boxes[kind] = v, cb
        mh = ttk.Frame(tab, style="Flat.TFrame")
        mh.pack(fill="x", pady=(6, 0))
        ttk.Label(mh, text="Models", style="Muted.TLabel").pack(side="left")
        EyeButton(mh, self._show_abilities, "Abilities of every model in the unit").pack(side="left", padx=4)
        f, self.models_tree = make_tree(tab, [("m", "Model"), ("n", "#"), ("t", "T"), ("sv", "Sv"), ("inv", "Inv"),
                                              ("w", "W")], [-150, 30, 30, 36, 40, 30], height=3)
        f.pack(fill="x", pady=(2, 4))
        if attacker:
            ttk.Label(tab, text="Weapons (click to include / exclude)", style="Muted.TLabel").pack(anchor="w")
            f, self.weapons_tree = make_tree(
                tab, [("on", "✓"), ("ph", "Phase"), ("n", "#"), ("w", "Weapon"), ("a", "A"), ("sk", "Sk"),
                      ("s", "S"), ("ap", "AP"), ("d", "D"), ("kw", "Abilities")],
                [24, 52, 26, -120, 38, 32, 28, 30, 44, -90], height=6)
            f.pack(fill="both", expand=True)
            self.weapons_tree.tag_configure("off", foreground="#a9a49a")
            self.weapons_tree.bind("<ButtonRelease-1>", self._toggle_weapon)

    def _attached(self) -> list[ListUnit]:
        return resolve_attached(self.army, self.unit, self.plan(self.unit), self.wd) if self.unit else []

    def _load_unit(self):
        u, p = self.unit, self.plan(self.unit)
        for kind in ("leader", "support"):
            opts = self.army.attach_options(u, self.wd, support=kind == "support")
            default = self.army.default_attached(u, self.wd, support=kind == "support")
            default_label = f"{DEFAULT[:-1]}: {default.label})" if default else f"{DEFAULT[:-1]}: none)"
            values = [default_label, NONE] + [o.label for o in opts]
            self.attach_boxes[kind].configure(values=values, state="readonly" if opts else "disabled")
            choice = getattr(p, kind)
            self.attach_vars[kind].set(default_label if choice == DEFAULT else choice)
        self._refresh_details()
        self._refresh_tests()

    def _on_attach(self, kind: str):
        v = self.attach_vars[kind].get()
        setattr(self.plan(self.unit), kind, DEFAULT if v.startswith(DEFAULT[:-1]) else v)
        self._refresh_details()
        self.win.plans_changed()

    def _refresh_details(self):
        u = self.unit
        attached = self._attached()
        t = target_for(u, attached)
        self.models_tree.delete(*self.models_tree.get_children())
        self.models_tree.configure(height=min(5, max(3, len(t.groups))))
        for g in t.groups:
            pr = g.profile
            self.models_tree.insert("", "end", values=(("★ " if g.character else "") + g.label, g.count, pr.T,
                                                       f"{pr.Sv}+", f"{pr.inv}++" if pr.inv else "–", pr.W))
        if self.role == ATTACKER:
            self._refresh_weapons()

    # ------------------------------------------------------------------ weapons (attacker)
    def _weapon_rows(self):
        loads = all_loads(self.unit, self._attached())
        on = default_on(loads)
        on.update({k: v for k, v in self.plan(self.unit).weapons.items() if k in on})
        loads.sort(key=lambda ld: ld.weapon.melee)            # shooting first
        return loads, on

    def _refresh_weapons(self):
        t = self.weapons_tree
        t.delete(*t.get_children())
        loads, on = self._weapon_rows()
        for i, ld in enumerate(loads):
            w, k = ld.weapon, weapon_key(ld)
            name = w.name + (f"  [{ld.source}]" if ld.source != self.unit.label else "")
            t.insert("", "end", iid=str(i), tags=() if on[k] else ("off",),
                     values=(ON if on[k] else "", "Fight" if w.melee else "Shoot", ld.count, name, str(w.A),
                             f"{w.skill}+" if w.skill else "N/A", w.S, f"-{w.AP}" if w.AP else "0", str(w.D),
                             ", ".join(w.keywords.tags())))

    def _toggle_weapon(self, e):
        row = self.weapons_tree.identify_row(e.y)
        if not row or not self.unit:
            return
        loads, on = self._weapon_rows()
        ld = loads[int(row)]
        k = weapon_key(ld)
        p = self.plan(self.unit)
        p.weapons[k] = not on[k]
        if p.weapons[k]:        # alternative profiles of one weapon are exclusive
            for o in loads:
                if (o is not ld and o.source == ld.source and o.weapon.melee == ld.weapon.melee
                        and o.weapon.base_name == ld.weapon.base_name):
                    p.weapons[weapon_key(o)] = False
        self._refresh_weapons()
        self.win.plans_changed()

    def _show_abilities(self):
        if self.unit:
            show_unit_abilities(self.win, self.win.ctx.rules, [self.unit] + self._attached())

    # ------------------------------------------------------------------ tests tab
    def _build_tests_tab(self, attacker: bool):
        tab = ttk.Frame(self.nb, style="Flat.TFrame", padding=6)
        self.nb.add(tab, text="Tests")
        hint = ("Each ticked scenario is one extra test, on its own (never combined). Top row: test this phase?"
                if attacker else "Each ticked scenario is one extra test for this unit, on its own.")
        ttk.Label(tab, text=hint, style="Muted.TLabel", wraplength=380, justify="left").pack(anchor="w")
        cols = [("t", "Scenario"), (RANGED, "Shooting"), (MELEE, "Fight")] if attacker else \
            [("t", "Scenario"), ("any", "Test"), ("note", "")]
        widths = [-190, 70, 70] if attacker else [-190, 50, 90]
        f, self.tests_tree = make_tree(tab, cols, widths, height=12)
        f.pack(fill="both", expand=True, pady=(4, 0))
        self.tests_tree.tag_configure("group", foreground=C["muted"])
        self.tests_tree.tag_configure("phase", background="#efe9dd")
        self.tests_tree.bind("<ButtonRelease-1>", self._toggle_test)
        self._test_rows: dict[str, str] = {}      # tree iid -> variant key (or "phase")

    def _refresh_tests(self):
        t = self.tests_tree
        t.delete(*t.get_children())
        p = self.plan(self.unit)
        if self.role == ATTACKER:
            t.insert("", "end", iid="phase", tags=("phase",),
                     values=("Test this phase", *(ON if p.phases.get(ph) else OFF for ph in PHASES)))
            catalogue = ATTACKER_VARIANTS
        else:
            catalogue = DEFENDER_VARIANTS
        group = None
        for v in catalogue.values():
            if v.group != group:
                group = v.group
                if group != "Baseline":
                    t.insert("", "end", iid=f"g:{group}", tags=("group",), values=(group.upper(), "", ""))
            if self.role == ATTACKER:
                cells = []
                for ph in PHASES:
                    if ph not in v.phases:
                        cells.append(NA)
                    elif not p.phases.get(ph):
                        cells.append("–")
                    else:
                        cells.append(ON if v.key in p.variant_keys(ph) else OFF)
                t.insert("", "end", iid=f"v:{v.key}", values=(v.label, *cells))
            else:
                note = "shooting only" if v.phases == (RANGED,) else ""
                t.insert("", "end", iid=f"v:{v.key}",
                         values=(v.label, ON if v.key in p.variant_keys("any") else OFF, note))

    def _toggle_test(self, e):
        row, col = self.tests_tree.identify_row(e.y), self.tests_tree.identify_column(e.x)
        if not row or not self.unit or row.startswith("g:"):
            return
        p = self.plan(self.unit)
        if self.role == ATTACKER:
            phase = {"#2": RANGED, "#3": MELEE}.get(col)
            if not phase:
                return
            if row == "phase":
                p.phases[phase] = not p.phases.get(phase)
            else:
                key = row[2:]
                if phase in ATTACKER_VARIANTS[key].phases and p.phases.get(phase):
                    p.toggle_variant(phase, key)
        else:
            if col not in ("#1", "#2"):
                return
            if row.startswith("v:"):
                p.toggle_variant("any", row[2:])
        self._refresh_tests()
        self._refresh_row(self.unit)
        self.win.plans_changed()
