"""One side of the matchup window: an army, its selected unit, attached characters, and
role-specific options (weapons + attacker modifiers, or allocation order + defender modifiers)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.core import Dice, DiceMod, Modifiers, WeaponLoad
from crunch.lists import ArmyList, ListUnit, target_for, weapon_loads
from crunch.ui.theme import C
from crunch.ui.views.rules import show_army_rules, show_unit_abilities
from crunch.ui.widgets import EyeButton, Tooltip, make_tree

if TYPE_CHECKING:
    from crunch.ui.tools.matchup.window import MatchupWindow


class ArmyPanel(ttk.Frame):
    """One third of the matchup window: an army, a unit, its attached characters, and role-specific options."""

    def __init__(self, master, win: "MatchupWindow", army: ArmyList, role: str, state: dict | None = None):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win, self.army, self.role = win, army, role
        self.wd = win.ctx.wd
        self.unit: ListUnit | None = None
        self.options: dict[str, list[ListUnit]] = {"leader": [], "support": []}
        self.checked: dict[tuple[str, str], bool] = {}
        self._loads: list[WeaponLoad] = []
        self._pending = state or {}
        self.order_keys: list[str] = []
        self._key_labels: dict[str, str] = {}
        self._drag: str | None = None
        self._dragged = False
        attacker = role == "attacker"

        ttk.Label(self, text="ATTACKER" if attacker else "DEFENDER",
                  style="Att.TLabel" if attacker else "Def.TLabel").pack(anchor="w")
        ttk.Label(self, text=army.faction, style="H2.TLabel").pack(anchor="w")
        head = ttk.Frame(self, style="Flat.TFrame")
        head.pack(fill="x", pady=(0, 6))
        EyeButton(head, lambda: show_army_rules(self.win, self.win.ctx.rules, self.army),
                  "Army rules, detachment and stratagems").pack(side="right", anchor="n", padx=(6, 0))
        sub = f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else "")
        ttk.Label(head, text=sub, style="Muted.TLabel", wraplength=400).pack(side="left", anchor="w")

        f, self.units_tree = make_tree(self, [("unit", "Unit"), ("n", "Models"), ("pts", "Pts")],
                                       [-200, 60, 50], height=6)
        f.pack(fill="both", expand=True)
        for u in army.units:
            mark = "☆ " if u.is_support else "★ " if u.is_character else ""
            name = mark + u.label + ("" if u.datasheet else "  (no datasheet)")
            self.units_tree.insert("", "end", iid=str(u.uid), values=(name, u.model_count, u.points))
        self.units_tree.bind("<<TreeviewSelect>>", lambda e: self._on_unit())

        grid = ttk.Frame(self, style="Flat.TFrame")
        grid.pack(fill="x", pady=(8, 2))
        grid.columnconfigure(1, weight=1)
        self.attach_vars, self.attach_boxes = {}, {}
        for r, (kind, label) in enumerate((("leader", "Leader"), ("support", "Support"))):
            ttk.Label(grid, text=label, style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=1)
            v = tk.StringVar(value="None")
            cb = ttk.Combobox(grid, textvariable=v, state="readonly", width=28)
            cb.grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e: self._on_attached())
            self.attach_vars[kind], self.attach_boxes[kind] = v, cb

        mh = ttk.Frame(self, style="Flat.TFrame")
        mh.pack(fill="x", pady=(6, 0))
        ttk.Label(mh, text="Models", style="Muted.TLabel").pack(side="left")
        EyeButton(mh, self._show_abilities, "Abilities of every model in the unit").pack(side="left", padx=4)
        f, self.models_tree = make_tree(self, [("m", "Model"), ("n", "#"), ("mv", "M"), ("t", "T"), ("sv", "Sv"),
                                               ("inv", "Inv"), ("w", "W")],
                                        [-150, 34, 40, 34, 40, 40, 34], height=3)
        f.pack(fill="x", pady=(2, 6))

        if attacker:
            ttk.Label(self, text="Weapons (click to include / exclude; profiles of one weapon are exclusive)",
                      style="Muted.TLabel").pack(anchor="w")
            f, self.weapons_tree = make_tree(
                self, [("on", "✓"), ("n", "#"), ("w", "Weapon"), ("a", "A"), ("sk", "Skill"), ("s", "S"),
                       ("ap", "AP"), ("d", "D"), ("kw", "Abilities")],
                [24, 28, -130, 38, 38, 30, 32, 44, -110], height=7)
            f.pack(fill="both", expand=True)
            self.weapons_tree.bind("<ButtonRelease-1>", self._toggle_weapon)
            self.weapons_tree.tag_configure("off", foreground="#a9a49a")
        else:
            self._build_allocation()
        self.note = ttk.Label(self, text="", style="Muted.TLabel", wraplength=420, justify="left")
        self.note.pack(anchor="w", pady=(4, 0))
        self._build_mods(attacker)

        first = self._pending.get("uid")
        if first is None and army.units:
            linked = [u for u in army.units
                      if army.default_attached(u, self.wd) or army.default_attached(u, self.wd, True)]
            first = (linked or [u for u in army.units if u.datasheet] or army.units)[0].uid
        if first is not None:
            self.units_tree.selection_set(str(first))
            self.units_tree.see(str(first))

    # ---------------- allocation (defender only) ----------------
    def _build_allocation(self):
        box = ttk.LabelFrame(self, text="Wound allocation order (drag to reorder)", style="Panel.TLabelframe",
                             padding=6)
        box.pack(fill="both", expand=True, pady=(0, 2))
        f, self.alloc_tree = make_tree(box, [("i", "#"), ("m", "Model"), ("sv", "Save"), ("w", "W")],
                                       [30, -170, 70, 36], height=4)
        f.pack(fill="both", expand=True)
        self.alloc_tree.tag_configure("char", foreground=C["def"])
        self.alloc_tree.bind("<ButtonPress-1>", self._drag_start)
        self.alloc_tree.bind("<B1-Motion>", self._drag_move)
        self.alloc_tree.bind("<ButtonRelease-1>", self._drag_end)
        row = ttk.Frame(box, style="Flat.TFrame")
        row.pack(side="bottom", fill="x", pady=(4, 0), before=f)     # the table shrinks, not this row
        ttk.Button(row, text="Reset order", command=self._reset_order).pack(side="right")  # packed first: keeps its width
        ttk.Label(row, text="Precision attacks go to", style="Panel.TLabel").pack(side="left")
        self.prec_var = tk.StringVar(value="—")
        self.prec_box = ttk.Combobox(row, textvariable=self.prec_var, state="readonly", width=18)
        self.prec_box.pack(side="left", padx=6)
        self.prec_box.bind("<<ComboboxSelected>>", lambda e: self.win.schedule())

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
        t = self.alloc_tree
        t.delete(*t.get_children())
        for i, key in enumerate(self.order_keys):
            g = target.groups[int(key.split(":")[0])]
            p = g.profile
            t.insert("", "end", iid=key, tags=("char",) if g.character else (),
                     values=(i + 1, labels[key], f"{p.Sv}+" + (f" / {p.inv}++" if p.inv else ""), p.W))
        chars = [k for k in self.order_keys if target.groups[int(k.split(':')[0])].character]
        names = [labels[k] for k in chars]
        self._prec_keys = dict(zip(names, chars))
        if names:
            self.prec_box.configure(values=names, state="readonly")
            if self.prec_var.get() not in names:
                self.prec_var.set(names[0])
        else:
            self.prec_box.configure(values=["—"], state="disabled")
            self.prec_var.set("—")

    def _drag_start(self, e):
        self._drag = self.alloc_tree.identify_row(e.y) or None
        self._dragged = False

    def _drag_move(self, e):
        if not self._drag:
            return
        over = self.alloc_tree.identify_row(e.y)
        if over and over != self._drag:
            self.alloc_tree.move(self._drag, "", self.alloc_tree.index(over))
            self._dragged = True

    def _drag_end(self, _e):
        if self._drag and self._dragged:
            self.order_keys = list(self.alloc_tree.get_children())
            for i, key in enumerate(self.order_keys):
                self.alloc_tree.set(key, "i", i + 1)
            self.win.schedule()
        self._drag = None

    def apply_order(self, target) -> None:
        """Copy the defender's allocation order and precision choice onto a Target."""
        if self.role != "defender" or not self.order_keys:
            return
        target.model_order = [int(k.split(":")[0]) for k in self.order_keys]
        key = getattr(self, "_prec_keys", {}).get(self.prec_var.get())
        target.precision_pos = self.order_keys.index(key) if key in self.order_keys else None

    # ---------------- modifiers ----------------
    REROLLS = {"none": "none", "1s": "ones", "1s & 2s": "ones_twos", "failed": "fails"}
    IF_WEAKER = {"never": "none", "always": "always", "S < T": "lt", "S <= T": "le"}      # +1 to wound
    IF_STRONGER = {"never": "none", "always": "always", "S > T": "gt", "S >= T": "ge"}   # -1 to be wounded
    FNP_AGAINST = {"all": "all", "psychic": "psychic", "mortal": "mortal", "psychic/mortal": "psychic_mortal"}

    def _build_mods(self, attacker: bool):
        box = ttk.LabelFrame(self, text="Attacker modifiers" if attacker else "Defender modifiers",
                             style="Panel.TLabelframe", padding=6)
        # pinned to the bottom and packed first, so tables above shrink instead of hiding the modifiers
        box.pack(side="bottom", fill="x", pady=(4, 0), before=self.winfo_children()[0])
        self.note.pack_configure(side="bottom", before=box)
        self.vars: dict[str, tk.Variable] = {}
        self.fields: dict[str, tuple[tk.StringVar, str, tk.Entry]] = {}

        def combo(r, c, label, key, values, default, width=7):
            ttk.Label(box, text=label, style="Panel.TLabel").grid(row=r, column=c, sticky="w", padx=(0, 4), pady=2)
            v = tk.StringVar(value=default)
            cb = ttk.Combobox(box, textvariable=v, values=values, state="readonly", width=width)
            cb.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=2)
            cb.bind("<<ComboboxSelected>>", lambda e: self.win.schedule())
            self.vars[key] = v

        def check(r, c, label, key):
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(box, text=label, variable=v, style="Panel.TCheckbutton",
                            command=self.win.schedule).grid(row=r, column=c, columnspan=2, sticky="w", pady=2)
            self.vars[key] = v

        def fields(r, specs):
            """A row of small free-text fields: (label, key, 'dice'|'amount'|'int', tooltip)."""
            row = ttk.Frame(box, style="Flat.TFrame")
            row.grid(row=r, column=0, columnspan=4, sticky="w", pady=(4, 2))
            for label, key, kind, tip in specs:
                ttk.Label(row, text=label, style="Panel.TLabel").pack(side="left", padx=(0, 4))
                v = tk.StringVar(value="")
                e = tk.Entry(row, textvariable=v, width=5, relief="solid", borderwidth=1, highlightthickness=0,
                             bg="white", justify="center")
                e.pack(side="left", padx=(0, 10))
                Tooltip(e, tip)
                v.trace_add("write", lambda *_a, k=key: self._on_field(k))
                self.fields[key] = (v, kind, e)

        if attacker:
            combo(0, 0, "Hit roll", "hit_mod", ["-1", "0", "+1"], "0")
            combo(0, 2, "+1 to wound", "wound_plus", list(self.IF_WEAKER), "never")
            combo(1, 0, "Re-roll hits", "reroll_hits", list(self.REROLLS), "none")
            combo(1, 2, "Re-roll wounds", "reroll_wounds", list(self.REROLLS), "none")
            combo(2, 0, "Crit hits on", "crit_hit_on", ["6+", "5+", "4+", "3+", "2+"], "6+")
            combo(2, 2, "Crit wounds on", "crit_wound_on", ["6+", "5+", "4+", "3+", "2+"], "6+")
            check(3, 0, "Lethal Hits", "add_lethal_hits")
            check(3, 2, "Devastating Wounds", "add_devastating_wounds")
            check(4, 0, "Precision", "add_precision")
            fields(5, [("Sustained Hits", "add_sustained_hits", "amount",
                        "Grants [SUSTAINED HITS X]: 1, 2, D3. A weapon that already has it keeps the bigger one")])
            fields(6, [("Attacks", "extra_attacks", "dice", "Added to each model's Attacks: +1, -1, D3, +D3"),
                       ("S", "extra_strength", "int", "Added to the weapons' Strength: +1, -1"),
                       ("AP", "extra_ap", "int", "+1 improves AP (AP-1 becomes AP-2), -1 worsens it"),
                       ("Damage", "extra_damage", "dice", "Added to each attack's Damage: +1, -1, D3")])
        else:
            check(0, 0, "Cover (-1 BS)", "cover")
            combo(0, 2, "Invuln (override)", "invuln_override", ["none", "6+", "5+", "4+", "3+"], "none")
            check(1, 0, "-1 to be hit", "minus_hit")
            combo(1, 2, "-1 to be wounded", "minus_wound", list(self.IF_STRONGER), "never")
            check(2, 0, "-1 Damage", "damage_reduction")
            check(2, 2, "Halve Damage", "halve_damage")
            combo(3, 0, "Feel No Pain", "feel_no_pain", ["none", "6+", "5+", "4+", "3+"], "none")
            combo(3, 2, "FNP against", "fnp_against", list(self.FNP_AGAINST), "all", width=13)
            fields(4, [("Toughness", "toughness_mod", "int", "Added to the unit's Toughness: +1, -1"),
                       ("Save", "save_char_mod", "int", "+1 improves the Save characteristic (3+ becomes 2+)"),
                       ("AP", "ap_mod", "int", "Change to incoming AP: -1 worsens it (AP-2 becomes AP-1)")])

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
        return int(t.replace(" ", ""))

    def _on_field(self, key: str):
        v, kind, entry = self.fields[key]
        try:
            self._parse_field(v.get(), kind)
            entry.configure(bg="white")
        except ValueError:
            entry.configure(bg="#f6d4d4")     # invalid: shown in red, ignored in the simulation
        self.win.schedule()

    def field_value(self, key: str):
        v, kind, _ = self.fields[key]
        try:
            return self._parse_field(v.get(), kind)
        except ValueError:
            return {"dice": DiceMod(), "amount": Dice()}.get(kind, 0)

    def apply_mods(self, m: Modifiers) -> None:
        v = {k: var.get() for k, var in self.vars.items()}
        num = lambda s: int(str(s).rstrip("+")) if s not in ("none", "") else None
        if self.role == "attacker":
            m.hit_mod += int(v["hit_mod"])
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
            m.hit_mod -= int(v["minus_hit"])
            m.damage_reduction = int(v["damage_reduction"])
            m.halve_damage = v["halve_damage"]
            m.invuln_override = num(v["invuln_override"])
            minus_wound = self.IF_STRONGER[v["minus_wound"]]
            if minus_wound == "always":
                m.wound_mod -= 1
            else:
                m.wound_minus_if_stronger = minus_wound
            m.toughness_mod += self.field_value("toughness_mod")
            m.save_char_mod += self.field_value("save_char_mod")
            m.ap_mod += self.field_value("ap_mod")

    # ---------------- selection ----------------
    def _attached(self, kind: str) -> ListUnit | None:
        name = self.attach_vars[kind].get()
        return next((u for u in self.options[kind] if u.label == name), None)

    @property
    def attached(self) -> list[ListUnit]:
        """Leader first, then Support character (either may be absent)."""
        return [u for u in (self._attached("leader"), self._attached("support")) if u]

    def state(self) -> dict:
        return {"uid": self.unit.uid if self.unit else None,
                "leader": self.attach_vars["leader"].get(), "support": self.attach_vars["support"].get()}

    def _on_unit(self):
        sel = self.units_tree.selection()
        if not sel:
            return
        if self.unit is not None and self.unit.uid == int(sel[0]):
            return          # re-fired select event: keep the current attachments
        self.unit = self.army.unit(int(sel[0]))
        pending, self._pending = self._pending, {}
        for kind in ("leader", "support"):
            opts = self.army.attach_options(self.unit, self.wd, support=kind == "support")
            self.options[kind] = opts
            names = ["None"] + [u.label for u in opts]
            self.attach_boxes[kind].configure(values=names, state="readonly" if opts else "disabled")
            default = self.army.default_attached(self.unit, self.wd, support=kind == "support")
            want = pending.get(kind)
            self.attach_vars[kind].set(want if want in names else (default.label if default else "None"))
        self._on_attached()

    def _on_attached(self):
        u = self.unit
        if not u:
            return
        attached = self.attached
        target = target_for(u, attached)
        self.models_tree.delete(*self.models_tree.get_children())
        self.models_tree.configure(height=min(5, max(3, len(target.groups))))   # show every model line
        for g in target.groups:
            p = g.profile
            self.models_tree.insert("", "end", values=(("★ " if g.character else "") + (g.label or p.name), g.count,
                                                       p.M, p.T, f"{p.Sv}+", f"{p.inv}++" if p.inv else "–", p.W))
        notes = []
        if not u.datasheet:
            notes.append(f"No Wahapedia datasheet found for “{u.name}”.")
        gear = list(u.unmatched_gear)
        for a in attached:
            gear += a.unmatched_gear
        if gear:
            notes.append("Not simulated (abilities / wargear): " + ", ".join(dict.fromkeys(gear)))
        self.note.configure(text="\n".join(notes))
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
        melee = self.win.phase.get() == "fight"
        return [ld for ld in self._loads if ld.weapon.melee == melee]

    def selected_loads(self) -> list[WeaponLoad]:
        return [ld for ld in self.phase_loads() if self.checked.get((ld.source, ld.weapon.name))]

    def refresh_weapons(self):
        if self.role != "attacker":
            return
        t = self.weapons_tree
        t.delete(*t.get_children())
        for i, ld in enumerate(self.phase_loads()):
            w = ld.weapon
            on = self.checked.get((ld.source, w.name), False)
            name = w.name + (f"  [{ld.source}]" if self.unit and ld.source != self.unit.label else "")
            t.insert("", "end", iid=f"{i}", tags=() if on else ("off",),
                     values=("✓" if on else "", ld.count, name, str(w.A), f"{w.skill}+" if w.skill else "N/A",
                             w.S, f"-{w.AP}" if w.AP else "0", str(w.D), ", ".join(w.keywords.tags())))
        if not t.get_children():
            t.insert("", "end", values=("", "", "No weapons for this phase", "", "", "", "", "", ""))

    def _toggle_weapon(self, event):
        row = self.weapons_tree.identify_row(event.y)
        loads = self.phase_loads()
        if not row or not row.isdigit() or int(row) >= len(loads):
            return
        ld = loads[int(row)]
        key = (ld.source, ld.weapon.name)
        on = not self.checked.get(key, False)
        self.checked[key] = on
        if on:   # profiles of the same weapon are alternatives: switch the others off
            for other in self._loads:
                if (other is not ld and other.source == ld.source and other.weapon.melee == ld.weapon.melee
                        and other.weapon.base_name == ld.weapon.base_name):
                    self.checked[(other.source, other.weapon.name)] = False
        self.refresh_weapons()
        self.weapons_tree.selection_set(row)
        self.win.schedule()
