"""One side of the Armies Auspex window: an army, its selected unit, attached characters, and
role-specific options (weapons + attacker modifiers, or allocation order + defender modifiers)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QVBoxLayout

from command_center.core import Dice, DiceMod, Modifiers, WeaponLoad
from command_center.lists import ArmyList, ListUnit, target_for, weapon_loads
from command_center.ui.theme import C
from command_center.ui.views.rules import show_army_rules, show_unit_abilities
from command_center.ui.widgets import Combo, EyeButton, Panel, Table, Tick, button, label, restyle

if TYPE_CHECKING:
    from command_center.ui.tools.auspex.window import AuspexWindow

NONE = "None"                   # no character attached
NO_CHARACTER = "—"              # no character for Precision attacks to go to


class ArmyPanel(Panel):
    """One third of the Armies Auspex window: an army, a unit, its attached characters, and role-specific options."""

    def __init__(self, win: "AuspexWindow", army: ArmyList, role: str, state: dict | None = None):
        super().__init__()
        self.win, self.army, self.role = win, army, role
        self.wd = win.ctx.wd
        self.unit: ListUnit | None = None
        self.options: dict[str, list[ListUnit]] = {"leader": [], "support": []}
        self.checked: dict[tuple[str, str], bool] = {}
        self._loads: list[WeaponLoad] = []
        self._pending = state or {}
        self.order_keys: list[str] = []
        self._key_labels: dict[str, str] = {}
        self._prec_keys: dict[str, str] = {}
        attacker = role == "attacker"

        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)
        col.addWidget(label("ATTACKER" if attacker else "DEFENDER", "att" if attacker else "def"))
        col.addWidget(label(army.faction, "h2"))
        head = QHBoxLayout()
        sub = f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else "")
        head.addWidget(label(sub, "muted", wrap=True), 1)
        head.addWidget(EyeButton(lambda: show_army_rules(self.win, self.win.ctx.rules, self.army),
                                 "Army rules, detachment and stratagems"), 0, Qt.AlignTop)
        col.addLayout(head)
        col.addSpacing(6)

        self.units_tree = Table([("unit", "Unit"), ("n", "Models"), ("pts", "Pts")], [-200, 60, 50],
                                rows=4 if attacker else 5)       # room for the weapons
        for u in army.units:
            mark = "☆ " if u.is_support else "★ " if u.is_character else ""
            name = mark + u.label + ("" if u.datasheet else "  (no datasheet)")
            self.units_tree.add_row((name, u.model_count, u.points), key=u.uid)
        self.units_tree.itemSelectionChanged.connect(self.on_unit)
        col.addWidget(self.units_tree, 2)
        col.addSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.attach_boxes: dict[str, Combo] = {}
        for r, (kind, text) in enumerate((("leader", "Leader"), ("support", "Support"))):
            grid.addWidget(label(text), r, 0)
            box = self.attach_boxes[kind] = Combo()
            box.addItem(NONE)
            box.activated.connect(lambda _i: self._on_attached())       # chosen by the user, not set from here
            grid.addWidget(box, r, 1)
        col.addLayout(grid)
        col.addSpacing(6)

        mh = QHBoxLayout()
        mh.setSpacing(4)
        mh.addWidget(label("Models", "muted"))
        mh.addWidget(EyeButton(self._show_abilities, "Abilities of every model in the unit"))
        mh.addStretch(1)
        col.addLayout(mh)
        col.addSpacing(2)
        self.models_tree = Table([("m", "Model"), ("n", "#"), ("mv", "M"), ("t", "T"), ("sv", "Sv"), ("inv", "Inv"),
                                  ("w", "W")], [-150, 34, 40, 34, 40, 40, 34], rows=3, fixed=True, selectable=False)
        col.addWidget(self.models_tree)
        col.addSpacing(6)

        if attacker:
            col.addWidget(label("Weapons (click to include / exclude; profiles of one weapon are exclusive)", "muted"))
            self.weapons_tree = Table([("on", "✓"), ("n", "#"), ("w", "Weapon"), ("a", "A"), ("sk", "Skill"), ("s", "S"),
                                       ("ap", "AP"), ("d", "D"), ("kw", "Abilities")],
                                      [24, 28, -130, 38, 38, 30, 32, 44, -110], rows=4)
            self.weapons_tree.itemClicked.connect(lambda item, _col: self._toggle_weapon(item))
            col.addWidget(self.weapons_tree, 3)
        else:
            col.addWidget(self._build_allocation(), 3)
        col.addSpacing(4)
        self.note = label("", "muted", wrap=True)
        col.addWidget(self.note)
        col.addSpacing(4)
        col.addWidget(self._build_mods(attacker))               # at the bottom: the tables above give way, not this

        first = self._pending.get("uid")
        if first is None and army.units:
            linked = [u for u in army.units
                      if army.default_attached(u, self.wd) or army.default_attached(u, self.wd, True)]
            first = (linked or [u for u in army.units if u.datasheet] or army.units)[0].uid
        if first is not None:
            self.units_tree.select(first)                       # shown; the window calls on_unit() once it is built

    # ---------------- allocation (defender only) ----------------
    def _build_allocation(self) -> QGroupBox:
        box = QGroupBox("Wound allocation order (drag to reorder)")
        col = QVBoxLayout(box)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(4)
        self.alloc_tree = Table([("i", "#"), ("m", "Model"), ("sv", "Save"), ("w", "W")], [30, -170, 70, 36], rows=3)
        self.alloc_tree.allow_reorder()
        self.alloc_tree.reordered.connect(self._reordered)
        col.addWidget(self.alloc_tree, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(label("Precision attacks go to"))
        self.prec_box = Combo()
        self.prec_box.setMinimumContentsLength(18)
        self.prec_box.activated.connect(lambda _i: self.win.schedule())
        row.addWidget(self.prec_box)
        row.addStretch(1)
        row.addWidget(button("Reset order", self._reset_order))
        col.addLayout(row)
        return box

    def _reset_order(self):
        self._fill_allocation(target_for(self.unit, self.attached), reset=True)
        self.win.schedule()

    def _fill_allocation(self, target, reset=True):
        keys, labels, seen = [], {}, {}
        for gi in target.default_order():
            k = seen.get(gi, 0)
            seen[gi] = k + 1
            key = f"{gi}:{k}"
            g = target.groups[gi]
            name = (g.label or g.profile.name) + (f" {k + 1}" if g.count > 1 else "")
            labels[key] = ("★ " if g.character else "") + name
            keys.append(key)
        if reset or sorted(self.order_keys) != sorted(keys):
            self.order_keys = keys
        self._key_labels = labels
        self._alloc_target = target
        self._show_allocation()
        chars = [k for k in self.order_keys if target.groups[int(k.split(':')[0])].character]
        names = [labels[k] for k in chars]
        self._prec_keys = dict(zip(names, chars))
        chosen = self.prec_box.currentText()
        self.prec_box.clear()
        self.prec_box.addItems(names or [NO_CHARACTER])
        self.prec_box.setEnabled(bool(names))
        if chosen in names:
            self.prec_box.setCurrentText(chosen)

    def _show_allocation(self):
        """The allocation table, in the order of order_keys."""
        target, t = self._alloc_target, self.alloc_tree
        t.clear_rows()
        for i, key in enumerate(self.order_keys):
            g = target.groups[int(key.split(":")[0])]
            p = g.profile
            t.add_row((i + 1, self._key_labels[key], f"{p.Sv}+" + (f" / {p.inv}++" if p.inv else ""), p.W), key=key,
                      color=C["def"] if g.character else None)

    def _reordered(self):
        """A row was dragged to another place: the order is the table's, numbered again."""
        self.order_keys = self.alloc_tree.keys()
        self._show_allocation()
        self.win.schedule()

    def apply_order(self, target) -> None:
        """Copy the defender's allocation order and precision choice onto a Target."""
        if self.role != "defender" or not self.order_keys:
            return
        target.model_order = [int(k.split(":")[0]) for k in self.order_keys]
        key = self._prec_keys.get(self.prec_box.currentText())
        target.precision_pos = self.order_keys.index(key) if key in self.order_keys else None

    # ---------------- modifiers ----------------
    REROLLS = {"none": "none", "1s": "ones", "1s & 2s": "ones_twos", "failed": "fails"}
    IF_WEAKER = {"never": "none", "always": "always", "S < T": "lt", "S <= T": "le"}      # +1 to wound
    IF_STRONGER = {"never": "none", "always": "always", "S > T": "gt", "S >= T": "ge"}   # -1 to be wounded
    FNP_AGAINST = {"all": "all", "psychic": "psychic", "mortal": "mortal", "psychic/mortal": "psychic_mortal"}
    SKILL = {"-1": -1, "none": 0, "+1": 1}
    RANGE_ANY = "∞"
    RANGES = [RANGE_ANY, '<2"', '6"', '9"', '12"', '18"', '24"', '36"', '48"']
    HIDDEN_DISTANCE = 15        # inches, unless another distance is typed

    def _build_mods(self, attacker: bool) -> QGroupBox:
        box = QGroupBox("Attacker modifiers" if attacker else "Defender modifiers")
        grid = QGridLayout(box)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(4, 1)                             # what is left of the width: after the columns
        self.vars: dict[str, Callable[[], object]] = {}        # a modifier's value, as its widget has it
        self.checks: dict[str, Tick] = {}
        self.fields: dict[str, tuple[QLineEdit, str]] = {}

        def combo(r, c, text, key, values, default, tip="") -> Combo:
            grid.addWidget(label(text), r, c)
            cb = Combo()
            cb.addItems(values)
            cb.setCurrentText(default)
            cb.activated.connect(lambda _i: self.win.schedule())
            if tip:
                cb.setToolTip(tip)
            grid.addWidget(cb, r, c + 1, Qt.AlignLeft)
            self.vars[key] = cb.currentText
            return cb

        def check(text, key, tip="") -> Tick:
            cb = self.checks[key] = Tick(text)
            cb.toggled.connect(lambda _on: self.win.schedule())
            if tip:
                cb.setToolTip(tip)
            self.vars[key] = cb.isChecked
            return cb

        def line(r) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(4)
            grid.addLayout(row, r, 0, 1, 5)
            return row

        def checks(r, specs, title=""):
            """A row of tick boxes: (label, key, tooltip)."""
            row = line(r)
            if title:
                row.addWidget(label(title))
                row.addSpacing(2)
            made = []
            for text, key, tip in specs:
                made.append(check(text, key, tip))
                row.addWidget(made[-1])
                row.addSpacing(4)
            row.addStretch(1)
            return made

        def entry(row, key, kind, tip, default=""):
            e = QLineEdit(default)
            e.setFixedWidth(44)
            e.setAlignment(Qt.AlignCenter)
            e.setToolTip(tip)
            e.textChanged.connect(lambda _text, key=key: self._on_field(key))
            row.addWidget(e)
            self.fields[key] = (e, kind)

        def fields(r, specs):
            """A row of small free-text fields: (label, key, 'dice'|'amount'|'int'|'inches', tooltip)."""
            row = line(r)
            for text, key, kind, tip in specs:
                row.addWidget(label(text))
                entry(row, key, kind, tip)
                row.addSpacing(6)
            row.addStretch(1)

        if attacker:
            combo(0, 0, "Hit roll", "hit_mod", ["-1", "0", "+1"], "0")
            combo(0, 2, "+1 to wound", "wound_plus", list(self.IF_WEAKER), "never")
            combo(1, 0, "Skill", "skill_mod", list(self.SKILL), "none",
                  tip="Modifier to the BS / WS: +1 improves it (4+ becomes 3+), -1 worsens it")
            rng = combo(1, 2, "Effective range", "effective_range", self.RANGES, self.RANGE_ANY,
                        tip="Distance to the target, in inches (any number can be typed).\n"
                            "∞: every weapon shoots and no distance rule comes into play.\n"
                            '<2": only [CLOSE-QUARTERS] weapons shoot.\n'
                            "Otherwise weapons out of range don't shoot, Rapid Fire and Melta apply within half "
                            'range, Conversion beyond 12", and a Hidden target is seen from close enough only.')
            rng.setEditable(True)
            rng.setInsertPolicy(Combo.NoInsert)
            rng.setMinimumContentsLength(4)
            rng.editTextChanged.connect(lambda _text: self._on_range())
            self._range_box = rng
            combo(2, 0, "Re-roll hits", "reroll_hits", list(self.REROLLS), "none")
            combo(2, 2, "Re-roll wounds", "reroll_wounds", list(self.REROLLS), "none")
            combo(3, 0, "Crit hits on", "crit_hit_on", ["6+", "5+", "4+", "3+", "2+"], "6+")
            combo(3, 2, "Crit wounds on", "crit_wound_on", ["6+", "5+", "4+", "3+", "2+"], "6+")
            checks(4, [("Lethal Hits", "add_lethal_hits", ""),
                       ("Devastating Wounds", "add_devastating_wounds", ""),
                       ("Precision", "add_precision", "")])
            checks(5, [("cover", "ignores_cover", "Ranged attacks ignore the Benefit of Cover, and a Hidden target is visible to them"),
                       ("Skill mods", "ignores_skill_maluses",
                        "Whatever worsens the BS / WS is ignored (cover, -1 Skill); bonuses still apply"),
                       ("hit mods", "ignores_hit_maluses",
                        "Negative modifiers to the hit roll are ignored; bonuses still apply"),
                       ("wound mods", "ignores_wound_maluses",
                        "Negative modifiers to the wound roll are ignored; bonuses still apply")], title="Ignores")
            _, not_visible, self._spotted = checks(6, [
                ("Plunging Fire", "plunging_fire", "Improves the BS of ranged attacks by 1"),
                ("Target not visible", "not_visible", "Only [INDIRECT FIRE] weapons shoot, and only unmodified 6s hit"),
                ("Spotted", "spotted", "A target that is not visible but spotted is hit on a fixed 4+")])
            not_visible.toggled.connect(self._on_not_visible)
            self._spotted.setEnabled(False)
            fields(7, [("Sustained Hits", "add_sustained_hits", "amount",
                        "Grants [SUSTAINED HITS X]: 1, 2, D3. A weapon that already has it keeps the bigger one"),
                       ("Blast / Cleave", "add_blast", "int",
                        "Grants [BLAST X] / [CLEAVE X]: +X attacks for each full 5 models in the target. "
                        "A weapon that already has it keeps the bigger one"),
                       ("Rapid Fire", "add_rapid_fire", "amount",
                        "Grants [RAPID FIRE X] to ranged weapons: 1, 2, D3. It applies within half the weapon's "
                        "range, so it needs an effective range")])
            fields(8, [("Attacks", "extra_attacks", "dice", "Added to each model's Attacks: +1, -1, D3, +D3"),
                       ("S", "extra_strength", "int", "Added to the weapons' Strength: +1, -1"),
                       ("AP", "extra_ap", "int", "+1 improves AP (AP-1 becomes AP-2), -1 worsens it"),
                       ("Damage", "extra_damage", "dice", "Added to each attack's Damage: +1, -1, D3")])
        else:
            grid.addWidget(check("Cover (-1 BS)", "cover"), 0, 0, 1, 2)
            combo(0, 2, "Additional invuln", "extra_invuln", ["none", "6+", "5+", "4+", "3+"], "none",
                  tip="An invulnerable save on top of the models' own: each model uses the better of the two")
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(check("Hidden beyond", "hidden",
                                "Not visible to attackers further away than this distance: only [INDIRECT FIRE] weapons "
                                "shoot.\nIt needs the attacker's effective range, and attacks that ignore cover see through it"))
            entry(row, "hidden_beyond", "inches", "Distance in inches (15 if left empty)", str(self.HIDDEN_DISTANCE))
            row.addWidget(label('"'))
            row.addStretch(1)
            grid.addLayout(row, 1, 0, 1, 2)
            combo(1, 2, "Skill", "enemy_skill_mod", list(self.SKILL), "none",
                  tip="Modifier to the attackers' BS / WS: -1 worsens it (3+ becomes 4+)")
            grid.addWidget(check("-1 to be hit", "minus_hit"), 2, 0, 1, 2)
            combo(2, 2, "-1 to be wounded", "minus_wound", list(self.IF_STRONGER), "never")
            grid.addWidget(check("-1 Damage", "damage_reduction"), 3, 0, 1, 2)
            grid.addWidget(check("Halve Damage", "halve_damage"), 3, 2, 1, 2)
            combo(4, 0, "Feel No Pain", "feel_no_pain", ["none", "6+", "5+", "4+", "3+"], "none")
            combo(4, 2, "FNP against", "fnp_against", list(self.FNP_AGAINST), "all")
            fields(5, [("Toughness", "toughness_mod", "int", "Added to the unit's Toughness: +1, -1"),
                       ("Save", "save_char_mod", "int", "+1 improves the Save characteristic (3+ becomes 2+)"),
                       ("AP", "ap_mod", "int", "Change to incoming AP: -1 worsens it (AP-2 becomes AP-1)")])
        return box

    def _on_not_visible(self, on: bool):
        if not on:                              # "Spotted" only means something for a non-visible target
            self._spotted.setChecked(False)
        self._spotted.setEnabled(on)
        self.win.schedule()

    def _on_range(self):
        try:
            self._parse_range(self._range_box.currentText())
            ink = C["ink"]
        except ValueError:
            ink = C["warn"]                     # not a distance: ignored in the simulation
        self._range_box.lineEdit().setStyleSheet(f"color: {ink};")
        self.win.schedule()

    @classmethod
    def _parse_range(cls, text: str) -> float | None:
        """'∞' or nothing: None (no distance rule); '<2"': just under 2; '18"' or '18': 18.0. Else ValueError."""
        t = text.strip().rstrip('"').strip().replace(",", ".")
        if t in ("", cls.RANGE_ANY):
            return None
        d = float(t[1:]) - 0.5 if t.startswith("<") else float(t)
        if d < 0:
            raise ValueError(text)
        return d

    @staticmethod
    def _parse_field(text: str, kind: str):
        """Parsed value, or raises ValueError. Empty means no modifier."""
        t = text.strip()
        if kind == "dice":
            return DiceMod.parse(t)
        if kind == "amount":
            return Dice.parse(t)
        if t in ("", "+", "-"):
            return 0
        if kind == "inches":
            return float(t.rstrip('"').replace(",", "."))
        return int(t.replace(" ", ""))

    def _on_field(self, key: str):
        entry, kind = self.fields[key]
        try:
            self._parse_field(entry.text(), kind)
            restyle(entry, state="")
        except ValueError:
            restyle(entry, state="bad")          # invalid: shown in red, ignored in the simulation
        self.win.schedule()

    def field_value(self, key: str):
        entry, kind = self.fields[key]
        try:
            return self._parse_field(entry.text(), kind)
        except ValueError:
            return {"dice": DiceMod(), "amount": Dice()}.get(kind, 0)

    def apply_mods(self, m: Modifiers) -> None:
        v = {k: get() for k, get in self.vars.items()}
        num = lambda s: int(str(s).rstrip("+")) if s not in ("none", "") else None
        if self.role == "attacker":
            m.hit_mod += int(v["hit_mod"])
            m.skill_mod += self.SKILL[v["skill_mod"]]
            try:
                m.effective_range = self._parse_range(v["effective_range"])
            except ValueError:
                pass                             # not a distance: no distance rule
            m.plunging_fire, m.ignores_cover = v["plunging_fire"], v["ignores_cover"]
            m.ignores_skill_maluses, m.ignores_hit_maluses = v["ignores_skill_maluses"], v["ignores_hit_maluses"]
            m.ignores_wound_maluses = v["ignores_wound_maluses"]
            m.not_visible, m.spotted = v["not_visible"], v["spotted"]
            m.add_blast = max(0, self.field_value("add_blast"))
            m.add_rapid_fire = self.field_value("add_rapid_fire")
            m.reroll_hits = self.REROLLS[v["reroll_hits"]]
            m.reroll_wounds = self.REROLLS[v["reroll_wounds"]]
            wound_plus = self.IF_WEAKER[v["wound_plus"]]
            if wound_plus == "always":
                m.wound_mod += 1
            else:
                m.wound_plus_if_weaker = wound_plus
            m.crit_hit_on = num(v["crit_hit_on"])
            m.crit_wound_on = num(v["crit_wound_on"])
            m.add_sustained_hits = self.field_value("add_sustained_hits")
            m.add_lethal_hits, m.add_devastating_wounds = v["add_lethal_hits"], v["add_devastating_wounds"]
            m.add_precision = v["add_precision"]
            m.extra_attacks = self.field_value("extra_attacks")
            m.extra_strength += self.field_value("extra_strength")
            m.extra_ap += self.field_value("extra_ap")
            m.extra_damage = self.field_value("extra_damage")
        else:
            m.cover = v["cover"]
            m.feel_no_pain = num(v["feel_no_pain"])
            m.fnp_against = self.FNP_AGAINST[v["fnp_against"]]
            m.to_be_hit_mod -= int(v["minus_hit"])
            m.damage_reduction = int(v["damage_reduction"])
            m.halve_damage = v["halve_damage"]
            m.extra_invuln = num(v["extra_invuln"])
            if v["hidden"]:
                m.hidden_beyond = self.field_value("hidden_beyond") or self.HIDDEN_DISTANCE
            m.enemy_skill_mod += self.SKILL[v["enemy_skill_mod"]]
            minus_wound = self.IF_STRONGER[v["minus_wound"]]
            if minus_wound == "always":
                m.to_be_wounded_mod -= 1
            else:
                m.wound_minus_if_stronger = minus_wound
            m.toughness_mod += self.field_value("toughness_mod")
            m.save_char_mod += self.field_value("save_char_mod")
            m.ap_mod += self.field_value("ap_mod")

    # ---------------- selection ----------------
    def _attached(self, kind: str) -> ListUnit | None:
        name = self.attach_boxes[kind].currentText()
        return next((u for u in self.options[kind] if u.label == name), None)

    @property
    def attached(self) -> list[ListUnit]:
        """Leader first, then Support character (either may be absent)."""
        return [u for u in (self._attached("leader"), self._attached("support")) if u]

    def state(self) -> dict:
        return {"uid": self.unit.uid if self.unit else None,
                "leader": self.attach_boxes["leader"].currentText(), "support": self.attach_boxes["support"].currentText()}

    def on_unit(self):
        """The unit selected in the table becomes this side's unit, with the characters that lead it by default."""
        uid = self.units_tree.selected_key()
        if uid is None:
            return
        if self.unit is not None and self.unit.uid == uid:
            return          # selected again: keep the current attachments
        self.unit = self.army.unit(uid)
        pending, self._pending = self._pending, {}
        for kind in ("leader", "support"):
            opts = self.army.attach_options(self.unit, self.wd, support=kind == "support")
            self.options[kind] = opts
            names = [NONE] + [u.label for u in opts]
            box = self.attach_boxes[kind]
            box.clear()
            box.addItems(names)
            box.setEnabled(bool(opts))
            default = self.army.default_attached(self.unit, self.wd, support=kind == "support")
            want = pending.get(kind)
            box.setCurrentText(want if want in names else (default.label if default else NONE))
        self._on_attached()

    def _on_attached(self):
        u = self.unit
        if not u:
            return
        attached = self.attached
        target = target_for(u, attached)
        self.models_tree.clear_rows()
        self.models_tree.set_rows(min(5, max(3, len(target.groups))))   # show every model line
        for g in target.groups:
            p = g.profile
            self.models_tree.add_row((("★ " if g.character else "") + (g.label or p.name), g.count, p.M, p.T, f"{p.Sv}+",
                                      f"{p.inv}++" if p.inv else "–", p.W))
        notes = []
        if not u.datasheet:
            notes.append(f"No Wahapedia datasheet found for “{u.name}”.")
        gear, unknown = list(u.unmatched_gear), list(u.unknown_gear)
        for a in attached:
            gear += a.unmatched_gear
            unknown += a.unknown_gear
        known = [g for g in dict.fromkeys(gear) if g not in unknown]
        if known:
            notes.append("Not simulated (abilities / wargear): " + ", ".join(known))
        if unknown:
            notes.append("⚠ Not found on the datasheet: " + ", ".join(dict.fromkeys(unknown)))
        self.note.setText("\n".join(notes))
        self.note.setVisible(bool(notes))
        if self.role == "attacker":
            self._loads = weapon_loads(u)
            for a in attached:
                self._loads += weapon_loads(a)
            self._default_checks()
            self.refresh_weapons()
        else:
            self._fill_allocation(target, reset=True)
        self.win.schedule()

    def _show_abilities(self):
        if self.unit:
            show_unit_abilities(self.win, self.win.ctx.rules, [self.unit] + self.attached)

    # ---------------- weapons (attacker only) ----------------
    def _default_checks(self):
        """Select every weapon, but only the first profile of multi-profile weapons."""
        self.checked = {}
        seen = set()
        for ld in self._loads:
            key = (ld.source, ld.weapon.name)
            group = (ld.source, ld.weapon.base_name, ld.weapon.melee)
            self.checked[key] = group not in seen
            seen.add(group)

    def phase_loads(self) -> list[WeaponLoad]:
        melee = self.win.phase == "fight"
        return [ld for ld in self._loads if ld.weapon.melee == melee]

    def selected_loads(self) -> list[WeaponLoad]:
        return [ld for ld in self.phase_loads() if self.checked.get((ld.source, ld.weapon.name))]

    def refresh_weapons(self):
        if self.role != "attacker":
            return
        t = self.weapons_tree
        t.clear_rows()
        for i, ld in enumerate(self.phase_loads()):
            w = ld.weapon
            on = self.checked.get((ld.source, w.name), False)
            name = w.name + (f"  [{ld.source}]" if self.unit and ld.source != self.unit.label else "")
            t.add_row(("✓" if on else "", ld.count, name, str(w.A), f"{w.skill}+" if w.skill else "N/A", w.S,
                       f"-{w.AP}" if w.AP else "0", str(w.D), ", ".join(w.keywords.tags())), key=i,
                      color=None if on else C["dim"])
        if not t.keys():
            t.add_row(("", "", "No weapons for this phase", "", "", "", "", "", ""))

    def toggle_weapon(self, row: int):
        """Include or exclude the weapon on a row of the table."""
        loads = self.phase_loads()
        if not 0 <= row < len(loads):
            return
        ld = loads[row]
        key = (ld.source, ld.weapon.name)
        on = not self.checked.get(key, False)
        self.checked[key] = on
        if on:   # profiles of the same weapon are alternatives: switch the others off
            for other in self._loads:
                if (other is not ld and other.source == ld.source and other.weapon.melee == ld.weapon.melee
                        and other.weapon.base_name == ld.weapon.base_name):
                    self.checked[(other.source, other.weapon.name)] = False
        self.refresh_weapons()
        self.weapons_tree.select(row)
        self.win.schedule()

    def _toggle_weapon(self, item):
        row = item.data(0, Qt.UserRole)
        if row is not None:
            self.toggle_weapon(row)
