"""First window: choose the attacker and defender army lists, then a tool. Tools that need no army
list have their buttons apart, on the left of the others.

A list can be added from here: "Add..." takes the text copied from NewRecruit (the dialog says how to
export it), saves it in the lists folder under a new name, and selects it."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from command_center.config import ATTRIBUTION_SHORT as ATTRIBUTION, LISTS_DIR, PROJECT_ROOT
from command_center.lists import ArmyList, parse_list
from command_center.lists.library import name_problem, save_list, text_problem
from command_center.ui.registry import Selection, Tool, tools
from command_center.ui.screen import screen_height
from command_center.ui.theme import C, dark_title_bar
from command_center.ui.widgets import Tooltip

if TYPE_CHECKING:
    from command_center.ui.app import App


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
                                  highlightthickness=0, borderwidth=0, selectbackground=C["select"],
                                  selectforeground="white")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())

        btns = ttk.Frame(self, style="Flat.TFrame")
        btns.pack(fill="x", pady=(6, 8))
        ttk.Button(btns, text="Browse...", command=self.browse).pack(side="left")
        ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(btns, text="Add...", command=self.add).pack(side="left")

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
                                       initialdir=LISTS_DIR if LISTS_DIR.exists() else PROJECT_ROOT,
                                       filetypes=[("NewRecruit text export", "*.txt"), ("All files", "*.*")])
        if f:
            self.select(Path(f))

    def add(self):
        """Paste a list's text, name it: it is saved with the others and selected here."""
        AddListDialog(self, self.app, self.role, self._added)

    def _added(self, path: Path):
        for picker in (self.master.att, self.master.dfn):       # both sides list it; this one selects it
            picker.refresh()
        self.select(path)

    def _on_select(self):
        p = self.selected_path
        self.army = None
        if p:
            try:
                self.army = parse_list(p, self.app.ctx.wd)
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


HOW_TO_EXPORT = (
    "In the NewRecruit app, when the list is finished:",
    "1.  Click Export, then Text export",
    "2.  Export Format: NR",
    "3.  Tick all the Content options",
    "4.  Copy to clipboard, then paste it below",
)


class AddListDialog(tk.Toplevel):
    """Paste an army list's text and give it a new name: it is saved next to the other lists.
    on_saved(path) is called once it is."""

    def __init__(self, master, app: "App", role: str, on_saved):
        super().__init__(master)
        self.app, self.on_saved = app, on_saved
        self.title("Command Center 40K — add an army list")
        self.configure(bg=C["bg"])
        self.minsize(560, 1)
        self.transient(app)
        screen_height(self, 720)
        dark_title_bar(self)
        body = ttk.Frame(self, style="Panel.TFrame", padding=14)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Label(body, text=f"Add an army list ({role})", style="H2.TLabel").pack(anchor="w")

        how = ttk.Frame(body, style="Cell.TFrame", padding=(12, 8))       # how to get the right text
        how.pack(fill="x", pady=(8, 10))
        for i, line in enumerate(HOW_TO_EXPORT):
            ttk.Label(how, text=line, style="Cell.TLabel" if i else "CellMuted.TLabel").pack(anchor="w", pady=(0, 2))

        bottom = ttk.Frame(body, style="Flat.TFrame")           # packed first: it keeps its room when the window shrinks
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        row = ttk.Frame(bottom, style="Flat.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Name of the list (a new one)", style="Panel.TLabel").pack(side="left")
        self.name = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.name, width=36)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda e: self.save())
        ttk.Label(row, text=f"saved in {LISTS_DIR}", style="Muted.TLabel").pack(side="left")
        self.problem = ttk.Label(bottom, text="", style="Muted.TLabel", foreground=C["warn"], wraplength=660,
                                 justify="left")
        self.problem.pack(anchor="w", pady=(6, 0))
        btns = ttk.Frame(bottom, style="Flat.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="Paste", command=self.paste).pack(side="left")

        box = ttk.Frame(body, style="Flat.TFrame")
        box.pack(fill="both", expand=True)
        self.text = tk.Text(box, wrap="none", relief="flat", padx=8, pady=6, undo=True, height=10)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.text.focus_set()
        self.grab_set()                                         # the launcher waits for this window

    def paste(self):
        """Replace the text with the clipboard's."""
        try:
            clip = self.clipboard_get()
        except tk.TclError:                                     # nothing on the clipboard, or not text
            self.problem.configure(text="There is no text on the clipboard.")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", clip)
        self.problem.configure(text="")

    def save(self):
        text, name = self.text.get("1.0", "end"), self.name.get()
        problem = text_problem(text, self.app.ctx.wd) or name_problem(name, LISTS_DIR)
        if problem:
            self.problem.configure(text=problem)
            return
        try:
            path = save_list(text, name, LISTS_DIR)
        except (OSError, ValueError) as e:
            self.problem.configure(text=f"The list could not be saved: {e}")
            return
        self.destroy()
        self.on_saved(path)


class Launcher(ttk.Frame):
    """Pick the attacker and defender lists, then open any registered tool."""

    def __init__(self, app: "App"):
        super().__init__(app, padding=18)
        self.app = app
        ttk.Label(self, text="Command Center 40K — choose the armies", style="H1.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(self, text=f"Wahapedia data: last update {app.ctx.wd.last_update or 'unknown'}   ·   "
                             f"lists folder: {LISTS_DIR}", foreground=C["muted"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
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
        self.tool_buttons: list[ttk.Button] = []          # those that need both lists chosen
        for tool in reversed(tools()):          # packed from the right: first tool ends up right-most
            if not tool.needs_armies:
                continue
            b = self._tool_button(bottom, tool)
            b.pack(side="right", padx=(8, 0))
            self.tool_buttons.append(b)
        apart = [t for t in tools() if not t.needs_armies]
        if apart:                               # on their own, left of a rule
            ttk.Separator(bottom, orient="vertical").pack(side="right", fill="y", padx=(20, 12))
            for tool in reversed(apart):
                self._tool_button(bottom, tool).pack(side="right", padx=(8, 0))
        # on its own line: next to the buttons it would be cut short on a narrow window
        ttk.Label(self, text=ATTRIBUTION, foreground=C["muted"]).grid(row=4, column=0, columnspan=3, sticky="w",
                                                                      pady=(8, 0))
        paths = self.att.paths
        if len(paths) >= 2:
            self.att.select(paths[0])
            self.dfn.select(paths[1])
        self.update_buttons()

    def _tool_button(self, parent, tool: Tool) -> ttk.Button:
        b = ttk.Button(parent, text=f"{tool.title}  →", style="Accent.TButton",
                       command=lambda: self.open_tool(tool))
        if tool.description:
            Tooltip(b, tool.description)
        return b

    @property
    def selection(self) -> Selection | None:
        if self.att.army and self.dfn.army:
            return Selection(self.att.army, self.dfn.army)
        return None

    def update_buttons(self):
        ok = bool(getattr(self, "att", None) and getattr(self, "dfn", None) and self.att.army and self.dfn.army)
        for b in getattr(self, "tool_buttons", []):
            b.state(["!disabled"] if ok else ["disabled"])

    def swap(self):
        a, d = self.att.selected_path, self.dfn.selected_path
        self.att.select(d)
        self.dfn.select(a)

    def open_tool(self, tool: Tool):
        sel = self.selection
        if sel or not tool.needs_armies:
            self.app.open_tool(tool.key, sel)
