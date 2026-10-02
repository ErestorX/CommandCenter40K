"""Colours, fonts and ttk styles shared by every window."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

C = {
    "bg": "#f3f1ec", "panel": "#fbfaf8", "ink": "#1d1c1a", "muted": "#6e6a63", "line": "#d8d3c8",
    "att": "#a3262a", "def": "#1f5288", "bar": "#a3262a", "bar2": "#e2b8b9", "grid": "#e7e3da",
}


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
    # badges: a value shown as a tinted tag, in its side's colours
    badge = dict(font=root.fonts["role"], padding=(10, 3), relief="flat", borderwidth=0)
    style.configure("AttBadge.TLabel", background="#f1d3d3", foreground=C["att"], **badge)
    style.configure("DefBadge.TLabel", background="#d3dff0", foreground=C["def"], **badge)
    style.configure("MutedBadge.TLabel", background=C["grid"], foreground=C["muted"], **badge)


def font_family() -> str:
    return tkfont.nametofont("TkDefaultFont").actual("family")
