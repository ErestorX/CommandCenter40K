"""One side of the Engagement Optimizer: an army list with include toggles, the selected unit's details, and
its tests (packages of modifiers applied together)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.analysis.plan import (ATTACKER, DEFAULT, NONE, TestPackage, UnitPlan, all_loads, default_on,
                                          resolve_attached, test_count, weapon_key)
from command_center.analysis.variants import (ATTACKER_VARIANTS, DEFENDER_VARIANTS, PHASE_LABEL, PHASES, package_label,
                                              toggle)
from command_center.lists import ArmyList, ListUnit, target_for
from command_center.ui.theme import C
from command_center.ui.views.rules import show_army_rules, show_unit_abilities
from command_center.ui.widgets import EyeButton, make_tree

if TYPE_CHECKING:
    from command_center.ui.tools.optimizer.window import OptimizerWindow

ON, OFF = "✓", "·"


class UnitPlanPanel(ttk.Frame):
    def __init__(self, master, win: "OptimizerWindow", army: ArmyList, role: str):
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
        self.units_tree.tag_configure("off", foreground=C["dim"])
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
                self.plan(u).set_included(on, self.role)
                self._refresh_row(u)
        if self.unit:
            self._refresh_tests()
        self.win.plans_changed()

    def _on_units_click(self, e):
        row, col = self.units_tree.identify_row(e.y), self.units_tree.identify_column(e.x)
        if not row or col != "#1":
            return
        u = self.army.unit(int(row))
        if not u.datasheet:
            return
        p = self.plan(u)
        p.set_included(not p.included, self.role)
        self._refresh_row(u)
        if u is self.unit:
            self._refresh_tests()
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
            self.weapons_tree.tag_configure("off", foreground=C["dim"])
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
        self.catalogue = ATTACKER_VARIANTS if attacker else DEFENDER_VARIANTS
        self.draft: list[str] = []            # modifiers ticked for the next test (kept across units)
        ttk.Label(tab, text="Tick modifiers, then Add test: they are applied together, as one test. "
                            "Unticking the unit deletes its tests.",
                  style="Muted.TLabel", wraplength=380, justify="left").pack(anchor="w")
        f, self.mods_tree = make_tree(tab, [("on", "✓"), ("mod", "Modifier"), ("note", "")], [30, -190, 90],
                                      height=9)
        f.pack(fill="both", expand=True, pady=(4, 0))
        self.mods_tree.tag_configure("group", foreground=C["muted"])
        self.mods_tree.bind("<ButtonRelease-1>", self._toggle_mod)
        group = None
        for v in self.catalogue.values():
            if v.group != group:
                group = v.group
                self.mods_tree.insert("", "end", iid=f"g:{group}", tags=("group",), values=("", group.upper(), ""))
            note = "" if set(v.phases) == set(PHASES) else f"{PHASE_LABEL[v.phases[0]].lower()} only"
            self.mods_tree.insert("", "end", iid=f"v:{v.key}", values=(OFF, v.label, note))

        bar = ttk.Frame(tab, style="Flat.TFrame")
        bar.pack(fill="x", pady=(4, 2))
        self.phase_vars: dict[str, tk.BooleanVar] = {}
        if attacker:
            for ph in PHASES:
                v = tk.BooleanVar(value=True)
                ttk.Checkbutton(bar, text=PHASE_LABEL[ph], variable=v, style="Panel.TCheckbutton").pack(
                    side="left", padx=(0, 8))
                self.phase_vars[ph] = v
        ttk.Button(bar, text="Add test", style="Accent.TButton", command=self._add_test).pack(side="right")
        ttk.Button(bar, text="Clear", width=6, command=self._clear_draft).pack(side="right", padx=4)
        self.draft_label = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=380, justify="left")
        self.draft_label.pack(anchor="w")

        ttk.Label(tab, text="Tests for this unit (click ✕ to delete)", style="Muted.TLabel").pack(
            anchor="w", pady=(6, 0))
        cols = ([("ph", "Phase")] if attacker else []) + [("mods", "Modifiers"), ("x", "")]
        widths = ([70] if attacker else []) + [-240, 28]
        f, self.tests_tree = make_tree(tab, cols, widths, height=5)
        f.pack(fill="both", expand=True, pady=(2, 0))
        self.tests_tree.bind("<ButtonRelease-1>", self._on_tests_click)
        self._refresh_draft()

    def _toggle_mod(self, e):
        row = self.mods_tree.identify_row(e.y)
        if not row.startswith("v:"):
            return
        self.draft = toggle(self.draft, row[2:], self.catalogue)
        self._refresh_draft()

    def _clear_draft(self):
        self.draft = []
        self._refresh_draft()

    def _refresh_draft(self, message: str = ""):
        for k in self.catalogue:
            self.mods_tree.set(f"v:{k}", "on", ON if k in self.draft else OFF)
        self.draft_label.configure(text=message or f"Next test: {package_label(self.draft, self.catalogue)}")

    def _add_test(self):
        if not self.unit or not self.unit.datasheet:
            return
        phases = [ph for ph, v in self.phase_vars.items() if v.get()]
        if self.role == ATTACKER and not phases:
            self._refresh_draft("Tick Shooting and/or Fight first.")
            return
        p = self.plan(self.unit)
        if not p.included:
            p.set_included(True, self.role)
        if not p.add_test(TestPackage(list(self.draft), phases)):
            self._refresh_draft("This unit already has that test.")
            return
        self._tests_changed()

    def _phases_text(self, t: TestPackage) -> str:
        return "Both" if set(t.phases) == set(PHASES) else PHASE_LABEL[t.phases[0]]

    def _refresh_tests(self):
        t = self.tests_tree
        t.delete(*t.get_children())
        for i, pkg in enumerate(self.plan(self.unit).tests):
            label = package_label(pkg.mods, self.catalogue)
            values = ((self._phases_text(pkg),) if self.role == ATTACKER else ()) + (label, "✕")
            t.insert("", "end", iid=str(i), values=values)

    def _on_tests_click(self, e):
        row, col = self.tests_tree.identify_row(e.y), self.tests_tree.identify_column(e.x)
        if not row or not self.unit or col != f"#{len(self.tests_tree['columns'])}":
            return
        del self.plan(self.unit).tests[int(row)]
        self._tests_changed()

    def _tests_changed(self):
        self._refresh_tests()
        self._refresh_row(self.unit)
        self._refresh_draft()
        self.win.plans_changed()
