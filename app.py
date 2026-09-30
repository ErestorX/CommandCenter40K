#!/usr/bin/env python3
"""
app.py - lightweight mathhammer UI (tkinter, ships with Python).

    python app.py

Window 1: pick an attacker list and a defender list (NewRecruit text exports in ./lists).
Window 2: left third = attacker army, right third = defender army, middle = results.
Pick one unit (and its attached character) on each side; results update automatically.

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are (c) Games Workshop.
"""
from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from army_list import ArmyList, ListUnit, parse_list, target_for, weapon_loads
from mathhammer import Modifiers, SimResult, Wahapedia, WeaponLoad, simulate
from rules_view import RulesBook, show_army_rules, show_unit_abilities

HERE = Path(__file__).resolve().parent
LISTS_DIR = HERE / "lists"
ATTRIBUTION = "Powered by Wahapedia · rules and stats © Games Workshop"

C = {
    "bg": "#f3f1ec", "panel": "#fbfaf8", "ink": "#1d1c1a", "muted": "#6e6a63", "line": "#d8d3c8",
    "att": "#a3262a", "def": "#1f5288", "bar": "#a3262a", "bar2": "#e2b8b9", "grid": "#e7e3da",
}


# =============================================================================
# shared helpers
# =============================================================================
def setup_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(size=10)
    fam = base.actual("family")
    root.fonts = {
        "h1": tkfont.Font(family=fam, size=15, weight="bold"),
        "h2": tkfont.Font(family=fam, size=11, weight="bold"),
        "big": tkfont.Font(family=fam, size=22, weight="bold"),
        "small": tkfont.Font(family=fam, size=9),
        "role": tkfont.Font(family=fam, size=9, weight="bold"),
    }
    root.configure(bg=C["bg"])
    style.configure(".", background=C["bg"], foreground=C["ink"])
    style.configure("TFrame", background=C["bg"])
    style.configure("Panel.TFrame", background=C["panel"], relief="solid", borderwidth=1)
    style.configure("Flat.TFrame", background=C["panel"], relief="flat", borderwidth=0)
    style.configure("TLabel", background=C["bg"], foreground=C["ink"])
    style.configure("Panel.TLabel", background=C["panel"])
    style.configure("Muted.TLabel", background=C["panel"], foreground=C["muted"], font=root.fonts["small"])
    style.configure("H1.TLabel", font=root.fonts["h1"])
    style.configure("H2.TLabel", background=C["panel"], font=root.fonts["h2"])
    style.configure("Big.TLabel", background=C["panel"], font=root.fonts["big"])
    style.configure("Att.TLabel", background=C["panel"], foreground=C["att"], font=root.fonts["role"])
    style.configure("Def.TLabel", background=C["panel"], foreground=C["def"], font=root.fonts["role"])
    style.configure("Panel.TCheckbutton", background=C["panel"])
    style.configure("Panel.TRadiobutton", background=C["panel"])
    style.configure("Panel.TLabelframe", background=C["panel"])
    style.configure("Panel.TLabelframe.Label", background=C["panel"], foreground=C["muted"])
    style.configure("Treeview", rowheight=22, background="white", fieldbackground="white")
    style.configure("Treeview.Heading", font=root.fonts["small"])
    style.map("Treeview", background=[("selected", "#e9dcc3")], foreground=[("selected", C["ink"])])
    style.configure("Accent.TButton", font=root.fonts["h2"])


def make_tree(parent, columns, widths, height=6, anchor_first="w"):
    frame = ttk.Frame(parent, style="Flat.TFrame")
    tree = ttk.Treeview(frame, columns=[c for c, _ in columns], show="headings", height=height,
                        selectmode="browse")
    for i, ((col, title), w) in enumerate(zip(columns, widths)):
        tree.heading(col, text=title)
        stretch = w < 0
        tree.column(col, width=abs(w), minwidth=abs(w) if stretch else 20, stretch=stretch,
                    anchor=anchor_first if i == 0 or stretch else "center")
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, tree


def pct(x: float) -> str:
    return f"{x:.0%}" if x < 0.995 or x == 1 else ">99%"


# =============================================================================
# window 1 - pick the two lists
# =============================================================================
class ListPicker(ttk.Frame):
    def __init__(self, master, app: "App", role: str):
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.app, self.role = app, role
        self.paths: list[Path] = []
        self.army: ArmyList | None = None

        ttk.Label(self, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").pack(anchor="w")
        ttk.Label(self, text="Army list", style="H2.TLabel").pack(anchor="w", pady=(0, 6))
        box = ttk.Frame(self, style="Flat.TFrame")
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, height=10, activestyle="none", exportselection=False,
                                  highlightthickness=0, borderwidth=0, selectbackground="#e9dcc3",
                                  selectforeground=C["ink"])
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())

        btns = ttk.Frame(self, style="Flat.TFrame")
        btns.pack(fill="x", pady=(6, 8))
        ttk.Button(btns, text="Browse…", command=self.browse).pack(side="left")
        ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="left", padx=6)

        self.preview = ttk.Label(self, text="No list selected", style="Muted.TLabel", justify="left",
                                 wraplength=360)
        self.preview.pack(anchor="w", fill="x")
        self.refresh()

    def refresh(self):
        keep = self.selected_path
        found = sorted(LISTS_DIR.glob("*.txt")) if LISTS_DIR.exists() else []
        self.paths = found + [p for p in self.paths if p not in found]
        self.listbox.delete(0, "end")
        for p in self.paths:
            self.listbox.insert("end", p.stem)
        if keep in self.paths:
            self.select(keep)

    @property
    def selected_path(self) -> Path | None:
        sel = self.listbox.curselection()
        return self.paths[sel[0]] if sel else None

    def select(self, path: Path | None):
        self.listbox.selection_clear(0, "end")
        if path is None:
            self.army = None
            self._show_preview()
            return
        if path not in self.paths:
            self.paths.append(path)
            self.listbox.insert("end", path.stem)
        i = self.paths.index(path)
        self.listbox.selection_set(i)
        self.listbox.see(i)
        self._on_select()

    def browse(self):
        f = filedialog.askopenfilename(title=f"Choose the {self.role} list",
                                       initialdir=LISTS_DIR if LISTS_DIR.exists() else HERE,
                                       filetypes=[("NewRecruit text export", "*.txt"), ("All files", "*.*")])
        if f:
            self.select(Path(f))

    def _on_select(self):
        p = self.selected_path
        self.army = None
        if p:
            try:
                self.army = parse_list(p, self.app.wd)
            except Exception as e:  # noqa: BLE001 - show any parse problem to the user
                self.preview.configure(text=f"Could not read {p.name}:\n{e}")
                self.master.update_buttons()
                return
        self._show_preview()
        self.master.update_buttons()

    def _show_preview(self):
        a = self.army
        if not a:
            self.preview.configure(text="No list selected")
            return
        lines = [f"{a.faction}  ·  {a.points} pts  ·  {len(a.units)} units"]
        if a.detachment:
            lines.append(f"Detachment: {a.detachment}")
        if not a.faction_id:
            lines.append("⚠ Faction not recognised, units matched across all factions")
        if a.unmatched_units:
            lines.append("⚠ No datasheet for: " + ", ".join(a.unmatched_units))
        self.preview.configure(text="\n".join(lines))


class Launcher(ttk.Frame):
    def __init__(self, app: "App"):
        super().__init__(app, padding=18)
        self.app = app
        ttk.Label(self, text="Mathhammer — choose the armies", style="H1.TLabel").grid(row=0, column=0, columnspan=3,
                                                                                    sticky="w")
        ttk.Label(self, text=f"Wahapedia data: last update {app.wd.last_update or 'unknown'}   ·   lists folder: "
                             f"{LISTS_DIR}", foreground=C["muted"]).grid(row=1, column=0, columnspan=3, sticky="w",
                                                                        pady=(2, 12))
        self.att = ListPicker(self, app, "attacker")
        self.dfn = ListPicker(self, app, "defender")
        self.att.grid(row=2, column=0, sticky="nsew")
        mid = ttk.Frame(self, padding=10)
        mid.grid(row=2, column=1)
        ttk.Button(mid, text="⇄", width=3, command=self.swap).pack()
        self.dfn.grid(row=2, column=2, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(2, weight=1)

        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Label(bottom, text=ATTRIBUTION, foreground=C["muted"]).pack(side="left")
        self.go = ttk.Button(bottom, text="Open matchup  →", style="Accent.TButton", command=self.open_matchup)
        self.go.pack(side="right")
        paths = self.att.paths
        if len(paths) >= 2:
            self.att.select(paths[0])
            self.dfn.select(paths[1])
        self.update_buttons()

    def update_buttons(self):
        ok = bool(getattr(self, "att", None) and getattr(self, "dfn", None) and self.att.army and self.dfn.army)
        if hasattr(self, "go"):
            self.go.state(["!disabled"] if ok else ["disabled"])

    def swap(self):
        a, d = self.att.selected_path, self.dfn.selected_path
        self.att.select(d)
        self.dfn.select(a)

    def open_matchup(self):
        if self.att.army and self.dfn.army:
            self.app.open_matchup(self.att.army, self.dfn.army)


# =============================================================================
# window 2 - the matchup
# =============================================================================
class EyeButton(tk.Canvas):
    """Small drawn 'eye' icon button (no emoji fonts needed)."""

    def __init__(self, master, command, tooltip: str = "", bg: str | None = None):
        super().__init__(master, width=24, height=16, highlightthickness=0, bd=0, cursor="hand2",
                         bg=bg or C["panel"])
        self.command = command
        self._draw(C["muted"])
        self.bind("<Enter>", lambda e: self._draw(C["att"]))
        self.bind("<Leave>", lambda e: self._draw(C["muted"]))
        self.bind("<Button-1>", lambda e: self.command())
        if tooltip:
            Tooltip(self, tooltip)

    def _draw(self, color):
        self.delete("all")
        self.create_polygon(2, 8, 7, 3, 12, 2, 17, 3, 22, 8, 17, 13, 12, 14, 7, 13, smooth=True,
                            outline=color, fill="", width=1.6)
        self.create_oval(8.5, 4.5, 15.5, 11.5, outline=color, width=1.6)
        self.create_oval(10.5, 6.5, 13.5, 9.5, fill=color, outline=color)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 18
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#1d1c1a", fg="white", padx=6, pady=2).pack()

    def hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ArmyPanel(ttk.Frame):
    """One third of the matchup window: an army, a unit, its attached characters, and role-specific options."""

    def __init__(self, master, win: "MatchupWindow", army: ArmyList, role: str, state: dict | None = None):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win, self.army, self.role = win, army, role
        self.wd = win.app.wd
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
        EyeButton(head, lambda: show_army_rules(self.win, self.win.app.rules, self.army),
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
        self.note.pack(anchor="w", pady=(4, 4))
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
                                       [30, -170, 70, 36], height=5)
        f.pack(fill="both", expand=True)
        self.alloc_tree.tag_configure("char", foreground=C["def"])
        self.alloc_tree.bind("<ButtonPress-1>", self._drag_start)
        self.alloc_tree.bind("<B1-Motion>", self._drag_move)
        self.alloc_tree.bind("<ButtonRelease-1>", self._drag_end)
        row = ttk.Frame(box, style="Flat.TFrame")
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Precision attacks go to", style="Panel.TLabel").pack(side="left")
        self.prec_var = tk.StringVar(value="—")
        self.prec_box = ttk.Combobox(row, textvariable=self.prec_var, state="readonly", width=22)
        self.prec_box.pack(side="left", padx=6)
        self.prec_box.bind("<<ComboboxSelected>>", lambda e: self.win.schedule())
        ttk.Button(row, text="Reset order", command=self._reset_order).pack(side="right")

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
    def _build_mods(self, attacker: bool):
        box = ttk.LabelFrame(self, text="Attacker modifiers" if attacker else "Defender modifiers",
                             style="Panel.TLabelframe", padding=6)
        box.pack(fill="x", pady=(4, 0))
        self.vars: dict[str, tk.Variable] = {}

        def combo(r, c, label, key, values, default):
            ttk.Label(box, text=label, style="Panel.TLabel").grid(row=r, column=c, sticky="w", padx=(0, 4), pady=2)
            v = tk.StringVar(value=default)
            cb = ttk.Combobox(box, textvariable=v, values=values, state="readonly", width=7)
            cb.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=2)
            cb.bind("<<ComboboxSelected>>", lambda e: self.win.schedule())
            self.vars[key] = v

        def check(r, c, label, key):
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(box, text=label, variable=v, style="Panel.TCheckbutton",
                            command=self.win.schedule).grid(row=r, column=c, columnspan=2, sticky="w", pady=2)
            self.vars[key] = v

        if attacker:
            combo(0, 0, "Hit roll", "hit_mod", ["-1", "0", "+1"], "0")
            combo(0, 2, "Wound roll", "wound_mod", ["-1", "0", "+1"], "0")
            combo(1, 0, "Re-roll hits", "reroll_hits", ["none", "ones", "fails"], "none")
            combo(1, 2, "Re-roll wounds", "reroll_wounds", ["none", "ones", "fails"], "none")
            combo(2, 0, "Crit hits on", "crit_hit_on", ["6+", "5+", "4+"], "6+")
            combo(2, 2, "Sustained", "add_sustained_hits", ["0", "1", "2"], "0")
            check(3, 0, "Lethal Hits", "add_lethal_hits")
            check(3, 2, "Dev. Wounds", "add_devastating_wounds")
            check(4, 0, "+1 AP", "extra_ap")
            check(4, 2, "+1 Damage", "extra_damage")
            check(5, 0, "+1 Attack", "extra_attacks")
            check(5, 2, "Twin-linked", "add_twin_linked")
        else:
            check(0, 0, "Cover (-1 BS)", "cover")
            combo(0, 2, "Feel No Pain", "feel_no_pain", ["none", "6+", "5+", "4+"], "none")
            check(1, 0, "-1 to be hit", "minus_hit")
            check(1, 2, "-1 to be wounded", "minus_wound")
            check(2, 0, "-1 Damage", "damage_reduction")
            check(2, 2, "Halve Damage", "halve_damage")
            combo(3, 0, "Invuln (override)", "invuln_override", ["none", "6+", "5+", "4+", "3+"], "none")

    def apply_mods(self, m: Modifiers) -> None:
        v = {k: var.get() for k, var in self.vars.items()}
        num = lambda s: int(str(s).rstrip("+")) if s not in ("none", "") else None
        if self.role == "attacker":
            m.hit_mod += int(v["hit_mod"])
            m.wound_mod += int(v["wound_mod"])
            m.reroll_hits, m.reroll_wounds = v["reroll_hits"], v["reroll_wounds"]
            m.crit_hit_on = num(v["crit_hit_on"])
            m.add_sustained_hits = int(v["add_sustained_hits"])
            m.add_lethal_hits, m.add_devastating_wounds = v["add_lethal_hits"], v["add_devastating_wounds"]
            m.add_twin_linked = v["add_twin_linked"]
            m.extra_ap, m.extra_damage, m.extra_attacks = int(v["extra_ap"]), int(v["extra_damage"]), int(v["extra_attacks"])
        else:
            m.cover = v["cover"]
            m.feel_no_pain = num(v["feel_no_pain"])
            m.hit_mod -= int(v["minus_hit"])
            m.wound_mod -= int(v["minus_wound"])
            m.damage_reduction = int(v["damage_reduction"])
            m.halve_damage = v["halve_damage"]
            m.invuln_override = num(v["invuln_override"])

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
            show_unit_abilities(self.win, self.win.app.rules, [self.unit] + self.attached)

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


class ResultsPanel(ttk.Frame):
    def __init__(self, master, win: "MatchupWindow"):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win = win
        fonts = win.app.fonts

        top = ttk.Frame(self, style="Flat.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="← Lists", command=win.back).pack(side="left")
        ttk.Button(top, text="⇄ Swap sides", command=win.swap).pack(side="right")

        ph = ttk.Frame(self, style="Flat.TFrame")
        ph.pack(fill="x", pady=(10, 2))
        ttk.Label(ph, text="Phase", style="H2.TLabel").pack(side="left", padx=(0, 10))
        for text, val in (("Shooting", "shooting"), ("Fight", "fight")):
            ttk.Radiobutton(ph, text=text, value=val, variable=win.phase, style="Panel.TRadiobutton",
                            command=win.on_phase).pack(side="left", padx=4)

        sit = ttk.LabelFrame(self, text="Situation", style="Panel.TLabelframe", padding=6)
        sit.pack(fill="x", pady=(6, 8))
        self.sit_vars = {}
        opts = [("stationary", "Remained stationary (Heavy)"), ("half_range", "Within half range (Melta, Rapid Fire)"),
                ("charged", "Charged this turn (Lance)"), ("beyond_12", "Target beyond 12\" (Conversion)"),
                ("not_visible", "Target not visible (Indirect Fire)")]
        for i, (key, label) in enumerate(opts):
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(sit, text=label, variable=v, style="Panel.TCheckbutton",
                            command=win.schedule).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12), pady=1)
            self.sit_vars[key] = v

        self.title_lbl = ttk.Label(self, text="", style="H2.TLabel", wraplength=440, justify="center")
        self.title_lbl.pack(fill="x", pady=(2, 8))

        cards = ttk.Frame(self, style="Flat.TFrame")
        cards.pack(fill="x")
        self.cards = {}
        for i, (key, label) in enumerate((("dmg", "Expected damage"), ("slain", "Models slain"),
                                          ("wipe", "Unit destroyed"))):
            f = ttk.Frame(cards, style="Panel.TFrame", padding=(6, 4))
            f.grid(row=0, column=i, sticky="nsew", padx=2)
            cards.columnconfigure(i, weight=1, uniform="cards")
            ttk.Label(f, text=label, style="Muted.TLabel").pack()
            big = ttk.Label(f, text="–", style="Big.TLabel")
            big.pack()
            small = ttk.Label(f, text="", style="Muted.TLabel", justify="center")
            small.pack()
            self.cards[key] = (big, small)

        self.chart_title = ttk.Label(self, text="", style="Muted.TLabel")
        self.chart_title.pack(anchor="w", pady=(10, 0))
        self.canvas = tk.Canvas(self, height=190, bg=C["panel"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_chart())

        f, self.breakdown = make_tree(self, [("w", "Weapon"), ("n", "#"), ("a", "Att"), ("h", "Hits"),
                                             ("wd", "Wnds"), ("u", "Unsv"), ("d", "Dmg")],
                                      [-160, 32, 46, 46, 46, 46, 46], height=5)
        f.pack(fill="x", pady=(6, 4))

        self.status = ttk.Label(self, text="", style="Muted.TLabel")
        self.status.pack(anchor="w")
        ttk.Label(self, text=ATTRIBUTION, style="Muted.TLabel").pack(anchor="w")
        self.result: SimResult | None = None

    def apply_mods(self, m: Modifiers):
        for k, v in self.sit_vars.items():
            setattr(m, k, bool(v.get()))

    def busy(self, title: str):
        self.title_lbl.configure(text=title)
        self.status.configure(text="Computing…")

    def empty(self, title: str, message: str):
        self.result = None
        self.title_lbl.configure(text=title)
        for big, small in self.cards.values():
            big.configure(text="–")
            small.configure(text="")
        self.breakdown.delete(*self.breakdown.get_children())
        self.chart_title.configure(text="")
        self.canvas.delete("all")
        self.status.configure(text=message)

    def show(self, title: str, r: SimResult, seconds: float):
        self.result = r
        st = r.stats()
        self.title_lbl.configure(text=title)
        lo, hi = st["damage_pct"]["p5"], st["damage_pct"]["p95"]
        self.cards["dmg"][0].configure(text=f"{st['damage_mean']:.1f}")
        self.cards["dmg"][1].configure(text=f"± {st['damage_sd']:.1f}  ·  90%: {lo:.0f}–{hi:.0f}\n"
                                            f"of {r.total_wounds} wounds")
        slo, shi = st["slain_pct"]["p5"], st["slain_pct"]["p95"]
        self.cards["slain"][0].configure(text=f"{st['slain_mean']:.1f}")
        self.cards["slain"][1].configure(text=f"± {st['slain_sd']:.1f}  ·  90%: {slo:.0f}–{shi:.0f}\n"
                                              f"of {r.target.models} models")
        self.cards["wipe"][0].configure(text=pct(st["p_wipe"]))
        pc = st["p_character_slain"]
        self.cards["wipe"][1].configure(text=(f"character slain: {pct(pc)}" if pc is not None else "") +
                                        f"\nmean 95% CI {st['damage_ci95'][0]:.2f}–{st['damage_ci95'][1]:.2f}")
        self.breakdown.delete(*self.breakdown.get_children())
        for w in r.weapons:
            self.breakdown.insert("", "end", values=(w.name, w.count, f"{w.attacks:.1f}", f"{w.hits:.1f}",
                                                     f"{w.wounds:.1f}", f"{w.unsaved:.1f}", f"{w.damage:.1f}"))
        tags = ", ".join(r.mod_tags) or "none"
        self.status.configure(text=f"{r.trials:,} simulated attacks in {seconds:.2f}s  ·  modifiers: {tags}")
        self.draw_chart()

    def draw_chart(self):
        cv = self.canvas
        cv.delete("all")
        r = self.result
        if not r:
            return
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50 or H < 50:
            return
        st = r.stats()
        if r.target.models > 2:
            probs = list(st["slain_hist"])
            at_least = st["p_slain_at_least"]
            labels = [str(k) for k in range(len(probs))]
            self.chart_title.configure(text="Models slain: chance of exactly k (bar) and at least k (below)")
        else:
            cap = max(1, r.total_wounds)
            d = np.minimum(r.damage, cap)
            probs = list(np.bincount(d, minlength=cap + 1)[: cap + 1] / len(d))
            at_least = [float((d >= k).mean()) for k in range(cap + 1)]
            labels = [str(k) for k in range(cap + 1)]
            self.chart_title.configure(text=f"Damage dealt (of {cap} wounds): chance of exactly k and at least k")
        n = len(probs)
        pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 34
        cw = (W - pad_l - pad_r) / n
        top = max(probs) or 1
        base = H - pad_b
        mean = st["slain_mean"] if r.target.models > 2 else st["damage_mean"]
        label_every = max(1, int(np.ceil(n / ((W - 16) / 28))))
        for k, p in enumerate(probs):
            x0 = pad_l + k * cw + cw * 0.12
            x1 = pad_l + (k + 1) * cw - cw * 0.12
            h = (base - pad_t) * p / top
            cv.create_rectangle(x0, base - h, x1, base, fill=C["bar"] if p >= 0.005 else C["bar2"], width=0)
            if k % label_every == 0:
                cx = (x0 + x1) / 2
                cv.create_text(cx, base + 9, text=labels[k], fill=C["ink"], font=self.win.app.fonts["small"])
                if k:
                    cv.create_text(cx, base + 23, text=pct(at_least[k]), fill=C["muted"],
                                   font=self.win.app.fonts["small"])
        mx = pad_l + (mean + 0.5) * cw
        cv.create_line(mx, pad_t - 6, mx, base, fill=C["ink"], dash=(3, 3))
        cv.create_text(mx + 4, pad_t - 6, text=f"mean {mean:.1f}", anchor="nw", fill=C["ink"],
                       font=self.win.app.fonts["small"])
        cv.create_line(pad_l, base, W - pad_r, base, fill=C["line"])


class MatchupWindow(tk.Toplevel):
    def __init__(self, app: "App", attacker: ArmyList, defender: ArmyList):
        super().__init__(app)
        self.app = app
        self.title("Mathhammer — matchup")
        self.configure(bg=C["bg"])
        self.geometry("1500x900")
        self.minsize(1200, 760)
        self.protocol("WM_DELETE_WINDOW", self.back)
        self.phase = tk.StringVar(value="shooting")
        self._job = None
        self._gen = 0
        self.armies = [attacker, defender]
        self.states: list[dict | None] = [None, None]
        self.body = None
        self.build()

    def build(self):
        if self.body:
            self.body.destroy()
        self._ready = False
        self.body = ttk.Frame(self, padding=8)
        self.body.pack(fill="both", expand=True)
        for c in range(3):
            self.body.columnconfigure(c, weight=1, uniform="thirds")
        self.body.rowconfigure(0, weight=1)
        self.results = ResultsPanel(self.body, self)
        self.left = ArmyPanel(self.body, self, self.armies[0], "attacker", self.states[0])
        self.right = ArmyPanel(self.body, self, self.armies[1], "defender", self.states[1])
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.results.grid(row=0, column=1, sticky="nsew", padx=4)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self._ready = True
        self.update_idletasks()
        self.left._on_unit()
        self.right._on_unit()

    def swap(self):
        self.states = [self.right.state(), self.left.state()]
        self.armies.reverse()
        self.build()

    def back(self):
        self.destroy()
        self.app.deiconify()

    def on_phase(self):
        self.left.refresh_weapons()
        self.schedule()

    def schedule(self):
        if not getattr(self, "_ready", False):
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(150, self.run)

    def run(self):
        self._job = None
        att, dfn = self.left, self.right
        if not att.unit or not dfn.unit:
            return
        a_name = " + ".join([att.unit.label] + [a.label for a in att.attached])
        target = target_for(dfn.unit, dfn.attached)
        dfn.apply_order(target)
        title = f"{a_name}  →  {target.name}"
        if not dfn.unit.datasheet:
            self.results.empty(title, "The defending unit has no datasheet.")
            return
        loads = att.selected_loads()
        if not loads:
            self.results.empty(title, f"No {'melee' if self.phase.get() == 'fight' else 'ranged'} weapons selected.")
            return
        mods = Modifiers()
        att.apply_mods(mods)
        dfn.apply_mods(mods)
        self.results.apply_mods(mods)
        self._gen += 1
        gen = self._gen
        self.results.busy(title)

        box: list = []

        def work():   # background thread: no tkinter calls in here
            t0 = time.perf_counter()
            try:
                box.append((simulate(loads, target, mods, trials=self.app.trials), None,
                            time.perf_counter() - t0))
            except Exception as e:  # noqa: BLE001
                box.append((None, e, 0.0))
        threading.Thread(target=work, daemon=True).start()
        self._poll(gen, title, box)

    def _poll(self, gen, title, box):
        if not self.winfo_exists() or gen != self._gen:
            return
        if not box:
            self.after(25, self._poll, gen, title, box)
            return
        res, err, dt = box[0]
        if err:
            self.results.empty(title, f"Error: {err}")
        else:
            self.results.show(title, res, dt)


# =============================================================================
# app
# =============================================================================
class App(tk.Tk):
    trials = 20_000

    def __init__(self):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:  # noqa: BLE001 - older Windows: keep default scaling
                pass
        super().__init__()
        self.title("Mathhammer")
        setup_style(self)
        try:
            self.wd = Wahapedia()
            self.rules = RulesBook(self.wd)
        except FileNotFoundError as e:
            self.withdraw()
            messagebox.showerror("Mathhammer", f"{e}\n\nExpected a data folder next to app.py.")
            self.destroy()
            raise SystemExit(1)
        self.geometry("980x560")
        self.minsize(820, 480)
        self.launcher = None
        self.launcher = Launcher(self)
        self.launcher.pack(fill="both", expand=True)

    def open_matchup(self, attacker: ArmyList, defender: ArmyList):
        self.withdraw()
        MatchupWindow(self, attacker, defender)


if __name__ == "__main__":
    App().mainloop()
