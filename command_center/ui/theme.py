"""Colours, fonts and ttk styles shared by every window."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

C = {
    "bg": "#f3f1ec", "panel": "#fbfaf8", "ink": "#1d1c1a", "muted": "#6e6a63", "line": "#d8d3c8",
    "att": "#a3262a", "def": "#1f5288", "bar": "#a3262a", "bar2": "#e2b8b9", "grid": "#e7e3da",
}
# Force Dispositions' colour code: ink (text), tint (a badge's background)
DISPOSITION_COLORS = {
    "take and hold": ("#2f7d32", "#d6ead7"),        # green
    "purge the foe": ("#a3262a", "#f1d3d3"),        # red
    "disruption": ("#1b3a8a", "#d2daf0"),           # deep blue
    "reconnaissance": ("#0f7a7a", "#cfe8e8"),       # teal
    "priority assets": ("#8a6d00", "#f5e6a8"),      # yellow
}
# how hard a matchup is, by the group of its Estimate (command_center.deploy.estimates.difficulty_groups)
DIFFICULTY_COLORS = ("#c0392b", "#e67e22", "#f1c40f", "#8bc34a", "#2e7d32")        # the hardest group first
NO_ESTIMATE = "white"


def disposition_colors(name: str) -> tuple[str, str]:
    """(ink, tint) of a Force Disposition; muted grey for one without a colour."""
    return DISPOSITION_COLORS.get(" ".join((name or "").lower().split()), (C["muted"], C["grid"]))


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
    # drop-downs of a sheet: white while they can be chosen from, greyed once locked
    style.map("Sheet.TCombobox", fieldbackground=[("disabled", C["grid"]), ("readonly", "white")],
              foreground=[("disabled", C["muted"])])
    # cells of a matrix: white boxes on the panel
    style.configure("Cell.TFrame", background="white", relief="solid", borderwidth=1, bordercolor=C["line"])
    style.configure("Cell.TLabel", background="white")
    style.configure("CellMuted.TLabel", background="white", foreground=C["muted"], font=root.fonts["small"])
    # badges: a value shown as a tinted tag, in its side's colours
    badge = dict(font=root.fonts["role"], padding=(10, 3), relief="flat", borderwidth=0)
    style.configure("AttBadge.TLabel", background="#f1d3d3", foreground=C["att"], **badge)
    style.configure("DefBadge.TLabel", background="#d3dff0", foreground=C["def"], **badge)
    style.configure("MutedBadge.TLabel", background=C["grid"], foreground=C["muted"], **badge)


def font_family() -> str:
    return tkfont.nametofont("TkDefaultFont").actual("family")
