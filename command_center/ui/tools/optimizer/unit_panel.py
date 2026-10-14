"""One side of the Engagement Optimizer: an army list with include toggles, the selected unit's details, and
its tests (packages of modifiers applied together)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from command_center.analysis.plan import (ATTACKER, DEFAULT, NONE, TestPackage, UnitPlan, all_loads, default_on,
                                          resolve_attached, test_count, weapon_key)
from command_center.analysis.variants import (ATTACKER_VARIANTS, DEFENDER_VARIANTS, PHASE_LABEL, PHASES, package_label,
                                              split, toggle, with_value)
from command_center.lists import ArmyList, ListUnit, target_for
from command_center.ui.theme import C
from command_center.ui.views.rules import show_army_rules, show_unit_abilities
from command_center.ui.widgets import Combo, EyeButton, Panel, Table, Tick, button, label

if TYPE_CHECKING:
    from command_center.ui.tools.optimizer.window import OptimizerWindow

ON, OFF = "✓", "·"
VALUE = 2                       # the column of the modifiers table that holds a modifier's value


class ValueEditor(Combo):
    """The drop-down put over a modifier's value cell: pick a value or type one. Return or a pick takes
    it, Escape leaves the value as it was, and so does clicking elsewhere after typing nothing new."""

    def __init__(self, panel: "UnitPlanPanel", key: str):
        super().__init__()
        self.panel, self.key = panel, key

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.panel.close_editor(keep=False)
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() != Qt.PopupFocusReason:              # not its own list opening
            self.panel.close_editor()


class UnitPlanPanel(Panel):
    def __init__(self, win: "OptimizerWindow", army: ArmyList, role: str):
        super().__init__()
        self.win, self.army, self.role = win, army, role
        self.wd = win.ctx.armies
        self.store = win.store
        self.unit: ListUnit | None = None
        attacker = role == ATTACKER

        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)
        col.addWidget(label("ATTACKERS" if attacker else "DEFENDERS", "att" if attacker else "def"))
        col.addWidget(label(army.faction, "h2"))
        head = QHBoxLayout()
        sub = f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else "")
        head.addWidget(label(sub, "muted", wrap=True), 1)
        head.addWidget(EyeButton(lambda: show_army_rules(self.win, self.win.ctx.rules, self.army),
                                 "Army rules, detachment and stratagems"), 0, Qt.AlignTop)
        col.addLayout(head)
        col.addSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.addWidget(label("Tick the units to test (click ✓)", "muted"), 1)
        bar.addWidget(button("All", lambda: self._include_all(True)))
        bar.addWidget(button("None", lambda: self._include_all(False)))
        col.addLayout(bar)
        col.addSpacing(2)

        self.units_tree = Table([("on", "✓"), ("unit", "Unit"), ("pts", "Pts"), ("tests", "Tests")], [30, -200, 46, 46],
                                rows=5)
        for u in army.units:
            self.units_tree.add_row(("", "", "", ""), key=u.uid)
            self._refresh_row(u)
        self.units_tree.itemClicked.connect(self._on_units_click)
        self.units_tree.itemSelectionChanged.connect(self._on_select)
        col.addWidget(self.units_tree, 2)
        col.addSpacing(6)

        self.nb = QTabWidget()
        col.addWidget(self.nb, 5)
        self._build_unit_tab(attacker)
        self._build_tests_tab(attacker)

        first = next((u for u in army.units if u.datasheet), None)
        if first:
            self.units_tree.select(first.uid)
            self._on_select()

    # ------------------------------------------------------------------ units list
    def plan(self, u: ListUnit) -> UnitPlan:
        return self.store.get(self.army, self.role, u)

    def _refresh_row(self, u: ListUnit):
        p = self.plan(u)
        name = ("★ " if u.is_character else "") + u.label + ("" if u.datasheet else "  (no datasheet)")
        self.units_tree.set_row(u.uid, (ON if p.included else "", name, u.points, test_count(self.role, p)),
                                None if p.included else C["dim"])

    def _include_all(self, on: bool):
        for u in self.army.units:
            if u.datasheet:
                self.plan(u).set_included(on, self.role)
                self._refresh_row(u)
        if self.unit:
            self._refresh_tests()
        self.win.plans_changed()

    def _on_units_click(self, item, column: int):
        if column == 0:
            self.toggle_unit(item.data(0, Qt.UserRole))

    def toggle_unit(self, uid: int):
        """Include a unit in the tests, or take it out (with its tests)."""
        u = self.army.unit(uid)
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
        uid = self.units_tree.selected_key()
        if uid is None:
            return
        self.close_editor()
        self.unit = self.army.unit(uid)
        self._load_unit()

    # ------------------------------------------------------------------ unit tab
    def _build_unit_tab(self, attacker: bool):
        tab = QWidget()
        self.nb.addTab(tab, "Unit")
        col = QVBoxLayout(tab)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.attach_boxes: dict[str, Combo] = {}
        for r, kind in enumerate(("leader", "support")):
            grid.addWidget(label(kind.title()), r, 0)
            cb = self.attach_boxes[kind] = Combo()
            cb.activated.connect(lambda _i, kind=kind: self._on_attach(kind))
            grid.addWidget(cb, r, 1)
        col.addLayout(grid)
        col.addSpacing(6)
        mh = QHBoxLayout()
        mh.setSpacing(4)
        mh.addWidget(label("Models", "muted"))
        mh.addWidget(EyeButton(self._show_abilities, "Abilities of every model in the unit"))
        mh.addStretch(1)
        col.addLayout(mh)
        col.addSpacing(2)
        self.models_tree = Table([("m", "Model"), ("n", "#"), ("t", "T"), ("sv", "Sv"), ("inv", "Inv"), ("w", "W")],
                                 [-150, 30, 30, 36, 40, 30], rows=3, fixed=True, selectable=False)
        col.addWidget(self.models_tree)
        col.addSpacing(4)
        if attacker:
            col.addWidget(label("Weapons (click to include / exclude)", "muted"))
            self.weapons_tree = Table([("on", "✓"), ("ph", "Phase"), ("n", "#"), ("w", "Weapon"), ("a", "A"), ("sk", "Sk"),
                                       ("s", "S"), ("ap", "AP"), ("d", "D"), ("kw", "Abilities")],
                                      [24, 52, 26, -120, 38, 32, 28, 30, 44, -90], rows=4)
            self.weapons_tree.itemClicked.connect(lambda item, _col: self.toggle_weapon(item.data(0, Qt.UserRole)))
            col.addWidget(self.weapons_tree, 1)
        else:
            col.addStretch(1)

    def _attached(self) -> list[ListUnit]:
        return resolve_attached(self.army, self.unit, self.plan(self.unit), self.wd) if self.unit else []

    def _load_unit(self):
        u, p = self.unit, self.plan(self.unit)
        for kind in ("leader", "support"):
            opts = self.army.attach_options(u, self.wd, support=kind == "support")
            default = self.army.default_attached(u, self.wd, support=kind == "support")
            default_label = f"{DEFAULT[:-1]}: {default.label})" if default else f"{DEFAULT[:-1]}: none)"
            box = self.attach_boxes[kind]
            box.clear()
            box.addItems([default_label, NONE] + [o.label for o in opts])
            box.setEnabled(bool(opts))
            choice = getattr(p, kind)
            box.setCurrentText(default_label if choice == DEFAULT else choice)
        self._refresh_details()
        self._refresh_tests()

    def _on_attach(self, kind: str):
        v = self.attach_boxes[kind].currentText()
        setattr(self.plan(self.unit), kind, DEFAULT if v.startswith(DEFAULT[:-1]) else v)
        self._refresh_details()
        self.win.plans_changed()

    def _refresh_details(self):
        u = self.unit
        attached = self._attached()
        t = target_for(u, attached)
        self.models_tree.clear_rows()
        self.models_tree.set_rows(min(5, max(3, len(t.groups))))
        for g in t.groups:
            pr = g.profile
            self.models_tree.add_row((("★ " if g.character else "") + g.label, g.count, pr.T, f"{pr.Sv}+",
                                      f"{pr.inv}++" if pr.inv else "–", pr.W))
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
        t.clear_rows()
        loads, on = self._weapon_rows()
        for i, ld in enumerate(loads):
            w, k = ld.weapon, weapon_key(ld)
            name = w.name + (f"  [{ld.source}]" if ld.source != self.unit.label else "")
            t.add_row((ON if on[k] else "", "Fight" if w.melee else "Shoot", ld.count, name, str(w.A),
                       f"{w.skill}+" if w.skill else "N/A", w.S, f"-{w.AP}" if w.AP else "0", str(w.D),
                       ", ".join(w.keywords.tags())), key=i, color=None if on[k] else C["dim"])

    def toggle_weapon(self, row: int):
        """Include or exclude the weapon on a row of the table."""
        if row is None or not self.unit:
            return
        loads, on = self._weapon_rows()
        ld = loads[row]
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
        tab = QWidget()
        self.nb.addTab(tab, "Tests")
        col = QVBoxLayout(tab)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(0)
        self.catalogue = ATTACKER_VARIANTS if attacker else DEFENDER_VARIANTS
        self.draft: list[str] = []            # modifiers ticked for the next test (kept across units)
        # the value each modifier that takes one would be ticked with (kept across units)
        self.values: dict[str, str] = {k: v.param.default for k, v in self.catalogue.items() if v.param}
        self._editor: ValueEditor | None = None
        col.addWidget(label("Tick modifiers, then Add test: they are applied together, as one test. "
                            "Click a value to pick or type another. Unticking the unit deletes its tests.", "muted", wrap=True))
        col.addSpacing(4)
        self.mods_tree = Table([("on", "✓"), ("mod", "Modifier"), ("value", "Value ▾"), ("note", "")], [30, -150, 70, 86],
                               rows=5, selectable=False)
        self.mods_tree.itemClicked.connect(self._on_mods_click)
        group = None
        for v in self.catalogue.values():
            if v.group != group:
                group = v.group
                self.mods_tree.add_row(("", group.upper(), "", ""), key=f"g:{group}", color=C["muted"])
            note = "" if set(v.phases) == set(PHASES) else f"{PHASE_LABEL[v.phases[0]].lower()} only"
            self.mods_tree.add_row((OFF, v.name, self.values.get(v.key, ""), note), key=f"v:{v.key}")
        col.addWidget(self.mods_tree, 3)
        col.addSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.phase_ticks: dict[str, Tick] = {}
        if attacker:
            for ph in PHASES:
                tick = self.phase_ticks[ph] = Tick(PHASE_LABEL[ph])
                tick.setChecked(True)
                bar.addWidget(tick)
        bar.addStretch(1)
        bar.addWidget(button("Clear", self._clear_draft))
        bar.addWidget(button("Add test", self.add_test, "accent"))
        col.addLayout(bar)
        col.addSpacing(2)
        self.draft_label = label("", "muted", wrap=True)
        col.addWidget(self.draft_label)
        col.addSpacing(6)

        col.addWidget(label("Tests for this unit (click ✕ to delete)", "muted"))
        col.addSpacing(2)
        cols = ([("ph", "Phase")] if attacker else []) + [("mods", "Modifiers"), ("x", "")]
        widths = ([70] if attacker else []) + [-240, 28]
        self.tests_tree = Table(cols, widths, rows=3, selectable=False)
        self.tests_tree.itemClicked.connect(self._on_tests_click)
        col.addWidget(self.tests_tree, 2)
        self._refresh_draft()

    def _on_mods_click(self, item, column: int):
        row = item.data(0, Qt.UserRole)
        self.close_editor()
        if not row.startswith("v:"):
            return
        v = self.catalogue[row[2:]]
        if v.param and column == VALUE:
            self.edit_value(v.key)
        else:
            self.toggle_mod(v.key)

    def toggle_mod(self, key: str):
        """Tick a modifier for the next test, or untick it."""
        v = self.catalogue[key]
        self.draft = toggle(self.draft, v.mod(self.values.get(v.key, "")), self.catalogue)
        self._refresh_draft()

    def edit_value(self, key: str) -> ValueEditor:
        """A drop-down over the modifier's value cell: pick a value or type one."""
        param = self.catalogue[key].param
        cb = self._editor = ValueEditor(self, key)
        cb.addItems(param.choices)
        typed = param.kind != "choice"
        cb.setEditable(typed)
        cb.setCurrentText(self.values[key])
        cb.activated.connect(lambda _i: self.close_editor())
        self.mods_tree.setItemWidget(self.mods_tree.row(f"v:{key}"), VALUE, cb)
        cb.setFocus()
        if typed:
            cb.lineEdit().returnPressed.connect(self.close_editor)
            cb.lineEdit().selectAll()
        else:
            cb.showPopup()
        return cb

    def close_editor(self, keep: bool = True):
        """Take the edited value (one the modifier can't read is dropped), and tick its modifier."""
        cb, self._editor = self._editor, None
        if cb is None:
            return
        key, text = cb.key, cb.currentText()
        self.mods_tree.removeItemWidget(self.mods_tree.row(f"v:{key}"), VALUE)
        cb.deleteLater()
        if keep:
            self.set_value(key, text)

    def set_value(self, key: str, text: str) -> bool:
        """Give a modifier its value and tick it for the next test. False for a value it can't take."""
        try:
            mod = self.catalogue[key].mod(text)
        except ValueError:
            return False
        self.values[key] = split(mod)[1]
        self.mods_tree.set_cell(f"v:{key}", VALUE, self.values[key])
        ticked = {split(m)[0] for m in self.draft}
        self.draft = with_value(self.draft, mod) if key in ticked else toggle(self.draft, mod, self.catalogue)
        self._refresh_draft()
        return True

    def _clear_draft(self):
        self.close_editor(keep=False)
        self.draft = []
        self._refresh_draft()

    def _refresh_draft(self, message: str = ""):
        ticked = {split(m)[0] for m in self.draft}
        for k in self.catalogue:
            self.mods_tree.set_cell(f"v:{k}", 0, ON if k in ticked else OFF)
        self.draft_label.setText(message or f"Next test: {package_label(self.draft, self.catalogue)}")

    def add_test(self):
        """The ticked modifiers become a test of the selected unit (which is then included)."""
        self.close_editor()
        if not self.unit or not self.unit.datasheet:
            return
        phases = [ph for ph, tick in self.phase_ticks.items() if tick.isChecked()]
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
        t.clear_rows()
        for i, pkg in enumerate(self.plan(self.unit).tests):
            text = package_label(pkg.mods, self.catalogue)
            t.add_row(((self._phases_text(pkg),) if self.role == ATTACKER else ()) + (text, "✕"), key=i)

    def _on_tests_click(self, item, column: int):
        if column == self.tests_tree.columnCount() - 1:
            self.delete_test(item.data(0, Qt.UserRole))

    def delete_test(self, row: int):
        if self.unit:
            del self.plan(self.unit).tests[row]
            self._tests_changed()

    def _tests_changed(self):
        self._refresh_tests()
        self._refresh_row(self.unit)
        self._refresh_draft()
        self.win.plans_changed()
