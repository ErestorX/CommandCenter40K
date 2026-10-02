"""Small reusable widgets and formatting helpers."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from command_center.ui.theme import C


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
