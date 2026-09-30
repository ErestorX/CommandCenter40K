"""Base class for tool windows."""
from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from crunch.ui.theme import C

if TYPE_CHECKING:
    from crunch.ui.app import App
    from crunch.ui.registry import Selection


class ToolWindow(tk.Toplevel):
    """A themed top-level window that knows the app context and the selected armies.

    Closing it (or calling back()) returns to the launcher when no other tool is open."""

    title_text = "Tool"
    default_geometry = "1500x900"
    min_size = (1200, 760)

    def __init__(self, app: "App", selection: "Selection"):
        super().__init__(app)
        self.app = app
        self.ctx = app.ctx
        self.selection = selection
        self.title(f"Game Crunch — {self.title_text}")
        self.configure(bg=C["bg"])
        self.geometry(self.default_geometry)
        self.minsize(*self.min_size)
        self.protocol("WM_DELETE_WINDOW", self.back)

    def back(self):
        self.destroy()
        self.app.on_tool_closed(self)
