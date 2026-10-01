"""Left third of the Deployer: each army's Force Disposition, the two primary missions, and a
compact view of both army lists, whose units can be ticked to put them on the maps."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from crunch.deploy.roster import RosterRow, roster
from crunch.lists import ArmyList
from crunch.ui.theme import C, font_family
from crunch.ui.widgets import make_tree

if TYPE_CHECKING:
    from crunch.ui.tools.deployer.window import DeployerWindow

ROLES = ("attacker", "defender")
ON = "✓"


class SidePanel(ttk.Frame):
    def __init__(self, master, win: "DeployerWindow"):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win = win
        armies = (win.selection.attacker, win.selection.defender)
        top = ttk.Frame(self, style="Flat.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="← Lists", command=win.back).pack(side="left")
        ttk.Label(self, text="Deployer", style="H2.TLabel").pack(anchor="w", pady=(10, 0))

        # ---- Force Dispositions ---------------------------------------------------------------
        box = ttk.LabelFrame(self, text="Force Dispositions", style="Panel.TLabelframe", padding=6)
        box.pack(fill="x", pady=(6, 6))
        box.columnconfigure(1, weight=1)
        self.fd_vars: dict[str, tk.StringVar] = {}
        options = win.ctx.missions.dispositions
        for r, (role, army) in enumerate(zip(ROLES, armies)):
            ttk.Label(box, text=role.upper(), style="Att.TLabel" if role == "attacker" else "Def.TLabel").grid(
                row=r, column=0, sticky="w", padx=(0, 6))
            ttk.Label(box, text=army.faction or army.path.stem, style="Panel.TLabel").grid(row=r, column=1, sticky="w")
            v = tk.StringVar(value=win.ctx.missions.disposition(army.force_disposition) or "")
            cb = ttk.Combobox(box, textvariable=v, values=options, state="readonly", width=18)
            cb.grid(row=r, column=2, sticky="e", pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e: self.win.refresh())
            self.fd_vars[role] = v
        self.fd_note = ttk.Label(box, text="", style="Muted.TLabel", wraplength=380, justify="left")
        self.fd_note.grid(row=2, column=0, columnspan=3, sticky="w")
        missing = [a.faction or a.path.stem for a in armies if not win.ctx.missions.disposition(a.force_disposition)]
        if missing:
            self.fd_note.configure(text=f"No Force Disposition in the list of {', '.join(missing)}: choose one.")

        # ---- missions | army 1 | army 2 ----------------------------------------------------------
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True)
        mf = ttk.Frame(pw, style="Flat.TFrame")
        ttk.Label(mf, text="Primary missions", style="Muted.TLabel").pack(anchor="w")
        self.text = self._make_text(mf)
        pw.add(mf, weight=3)
        self.trees: dict[str, ttk.Treeview] = {}
        self.rows: dict[str, dict[str, RosterRow]] = {}
        for role, army in zip(ROLES, armies):
            pw.add(self._army_view(pw, role, army), weight=2)

    # ---------------------------------------------------------------- dispositions
    def disposition(self, role: str) -> str:
        return self.fd_vars[role].get()

    # ---------------------------------------------------------------- missions
    def _make_text(self, parent) -> tk.Text:
        fr = ttk.Frame(parent, style="Flat.TFrame")
        fr.pack(fill="both", expand=True, pady=(2, 6))
        t = tk.Text(fr, wrap="word", relief="flat", bg="white", padx=10, pady=8, height=10, cursor="arrow")
        sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        fam = font_family()
        t.tag_configure("who_attacker", foreground=C["att"], font=(fam, 9, "bold"))
        t.tag_configure("who_defender", foreground=C["def"], font=(fam, 9, "bold"))
        t.tag_configure("who_both", foreground=C["ink"], font=(fam, 9, "bold"))
        t.tag_configure("name", font=(fam, 12, "bold"), spacing1=2, spacing3=2)
        t.tag_configure("legend", foreground=C["muted"], font=(fam, 9, "italic"), spacing3=4)
        t.tag_configure("round", font=(fam, 9, "bold"), spacing1=6)
        t.tag_configure("when", foreground=C["muted"], font=(fam, 9))
        t.tag_configure("body", font=(fam, 10), lmargin1=8, lmargin2=20, spacing1=1)
        t.tag_configure("vp", font=(fam, 10, "bold"))
        t.tag_configure("note", foreground=C["muted"], font=(fam, 8))
        t.tag_configure("rule", font=(fam, 9), lmargin1=8, lmargin2=8, spacing1=2)
        t.tag_configure("sep", font=(fam, 4))
        t.configure(state="disabled")
        return t

    def show_missions(self, cards: list[tuple[str, str, dict | None]]):
        """cards: (role, army name, primary mission card or None); role "both" for a mirror pairing."""
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for n, (role, army, card) in enumerate(cards):
            if n:
                t.insert("end", "\n", "sep")
            disp = self.disposition("attacker" if role == "both" else role)
            who = "BOTH PLAYERS" if role == "both" else role.upper()
            t.insert("end", f"{who}  ·  {army}" + (f"  ·  {disp}" if disp else "") + "\n", f"who_{role}")
            if not card:
                t.insert("end", "Choose both Force Dispositions to see this mission.\n", "legend")
                continue
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
        t.configure(state="disabled")
        t.yview_moveto(0)

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
