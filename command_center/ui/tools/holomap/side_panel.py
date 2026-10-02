"""Left third of the Field Holomap: one column per player (attacker left, defender right) with its Force
Disposition and its primary mission, then a compact view of both army lists, whose units can be
ticked to put them on the maps."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from command_center.deploy.roster import RosterRow, roster
from command_center.lists import ArmyList
from command_center.ui.theme import C, font_family
from command_center.ui.widgets import make_tree

if TYPE_CHECKING:
    from command_center.ui.tools.holomap.window import HolomapWindow

ROLES = ("attacker", "defender")
COLUMNS = ("attacker", "defender")       # left to right, as everywhere else in the app
ON = "✓"


class SidePanel(ttk.Frame):
    def __init__(self, master, win: "HolomapWindow"):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win = win
        armies = (win.selection.attacker, win.selection.defender)
        top = ttk.Frame(self, style="Flat.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="← Command Center", command=win.back).pack(side="left")
        ttk.Button(top, text="Score Oracle", command=win.open_score_oracle).pack(side="right")
        ttk.Label(self, text="Field Holomap", style="H2.TLabel").pack(anchor="w", pady=(10, 0))

        # ---- one column per player: disposition + primary mission | army 1 | army 2 ----------------
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, pady=(6, 0))
        cols = ttk.Frame(pw, style="Flat.TFrame")
        for c in range(2):
            cols.columnconfigure(c, weight=1, uniform="players")
        cols.rowconfigure(0, weight=1)
        self.dispositions: dict[str, str] = {}            # role -> Force Disposition, as the lists set it
        self.texts: dict[str, tk.Text] = {}
        by_role = dict(zip(ROLES, armies))
        for c, role in enumerate(COLUMNS):
            self._player_column(cols, role, by_role[role]).grid(row=0, column=c, sticky="nsew",
                                                                padx=(0, 4) if c == 0 else (4, 0))
        pw.add(cols, weight=3)
        self.trees: dict[str, ttk.Treeview] = {}
        self.rows: dict[str, dict[str, RosterRow]] = {}
        for role, army in zip(ROLES, armies):
            pw.add(self._army_view(pw, role, army), weight=2)

    # ---------------------------------------------------------------- dispositions
    def disposition(self, role: str) -> str:
        return self.dispositions[role]

    def _player_column(self, parent, role: str, army: ArmyList) -> ttk.Frame:
        """Title with the army's Force Disposition opposite (as its list sets it), then the army's name,
        then its primary mission."""
        book = self.win.ctx.missions
        f = ttk.Frame(parent, style="Flat.TFrame")
        head = ttk.Frame(f, style="Flat.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").pack(
            side="left")
        fd = book.disposition(army.force_disposition) or ""
        self.dispositions[role] = fd
        badge = ("AttBadge.TLabel" if role == "attacker" else "DefBadge.TLabel") if fd else "MutedBadge.TLabel"
        ttk.Label(head, text=fd.upper() if fd else "NO FORCE DISPOSITION", style=badge).pack(side="right")
        name = army.faction or army.path.stem
        note = "" if fd else "  ·  its list sets none (Configuration: \"Force Disposition: ...\")"
        ttk.Label(f, text=name + note, style="Muted.TLabel", wraplength=230, justify="left").pack(anchor="w", pady=(2, 0))
        self.texts[role] = self._make_text(f)
        return f

    # ---------------------------------------------------------------- missions
    def _make_text(self, parent) -> tk.Text:
        fr = ttk.Frame(parent, style="Flat.TFrame")
        fr.pack(fill="both", expand=True, pady=(2, 6))
        t = tk.Text(fr, wrap="word", relief="flat", bg="white", padx=8, pady=6, width=10, height=10, cursor="arrow")
        sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        fam = font_family()
        t.tag_configure("name", font=(fam, 12, "bold"), spacing1=2, spacing3=2)
        t.tag_configure("legend", foreground=C["muted"], font=(fam, 9, "italic"), spacing3=4)
        t.tag_configure("round", font=(fam, 9, "bold"), spacing1=6)
        t.tag_configure("when", foreground=C["muted"], font=(fam, 9))
        t.tag_configure("body", font=(fam, 10), lmargin1=8, lmargin2=20, spacing1=1)
        t.tag_configure("vp", font=(fam, 10, "bold"))
        t.tag_configure("note", foreground=C["muted"], font=(fam, 8))
        t.tag_configure("rule", font=(fam, 9), lmargin1=8, lmargin2=8, spacing1=2)
        t.configure(state="disabled")
        return t

    def show_mission(self, role: str, card: dict | None):
        """A player's primary mission card (None: not known yet) in that player's column."""
        t = self.texts[role]
        t.configure(state="normal")
        t.delete("1.0", "end")
        if card:
            self._write_card(t, card)
        else:
            t.insert("end", "Both lists need a Force Disposition to know this mission.\n", "legend")
        t.configure(state="disabled")
        t.yview_moveto(0)

    @staticmethod
    def _write_card(t: tk.Text, card: dict):
        t.insert("end", card["name"].title() + "\n", "name")
        if card.get("legend"):
            t.insert("end", card["legend"] + "\n", "legend")
        for line in card.get("intro", []):
            t.insert("end", line + "\n", "rule")
        for a in card.get("actions", []):
            t.insert("end", f"{a.get('name', '').title()} ({a.get('type', '').lower()})\n", "round")
            for k, v in a.items():
                if k not in ("name", "type"):
                    t.insert("end", f"{k.replace('_', ' ').capitalize()}: {v}\n", "rule")
        for block in card.get("scoring", []):
            t.insert("end", block.get("round", "").capitalize() + "  ", "round")
            t.insert("end", block.get("when", "") + "\n", "when")
            for c in block.get("conditions", []):
                prefix = "or " if c.get("alternative") else "+ " if c.get("additional") else "• "
                t.insert("end", prefix + c.get("text", "") + "  ", "body")
                for v in c.get("vp", []):
                    t.insert("end", v["vp"], "vp")
                    if v.get("notes"):
                        t.insert("end", " " + " ".join(v["notes"]).lower(), "note")
                    t.insert("end", "  ", "body")
                t.insert("end", "\n", "body")

    # ---------------------------------------------------------------- armies
    def _army_view(self, parent, role: str, army: ArmyList) -> ttk.Frame:
        f = ttk.Frame(parent, style="Flat.TFrame")
        rows = roster(army, self.win.ctx.wd)
        self.rows[role] = {r.key: r for r in rows}
        head = ttk.Frame(f, style="Flat.TFrame")
        head.pack(fill="x", pady=(6, 0))
        ttk.Label(head, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").pack(
            side="left")
        ttk.Label(head, text=f"  {army.faction}  ·  {army.points} pts", style="Panel.TLabel").pack(side="left")
        dets = ", ".join(army.detachment_names)
        ttk.Label(f, text=f"{dets}  ·  {len(rows)} units on the table, {sum(r.models for r in rows)} models"
                          "  ·  click ✓ to put a unit on the maps",
                  style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w")
        tf, tree = make_tree(f, [("on", "✓"), ("unit", "Unit"), ("m", "Models"), ("pts", "Pts")],
                             [28, -240, 56, 50], height=5)
        tf.pack(fill="both", expand=True, pady=(2, 0))
        for r in rows:
            tree.insert("", "end", iid=r.key, values=("", r.name, r.models, r.points))
        tree.bind("<ButtonRelease-1>", lambda e, role=role: self._on_click(role, e))
        self.trees[role] = tree
        return f

    def show_selected(self, role_key: list[str] | None):
        """Highlight the roster row of the selected unit (None: no highlight)."""
        for role, tree in self.trees.items():
            if role_key and role_key[0] == role and tree.exists(role_key[1]):
                tree.selection_set(role_key[1])
                tree.see(role_key[1])
            else:
                tree.selection_remove(*tree.selection())

    def _on_click(self, role: str, e):
        tree = self.trees[role]
        key, col = tree.identify_row(e.y), tree.identify_column(e.x)
        if not key or col != "#1":
            return
        on = tree.set(key, "on") != ON
        tree.set(key, "on", ON if on else "")
        self.win.toggle_unit(role, self.rows[role][key], on)
