"""Base class for tool windows."""
from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from command_center.ui.screen import fill_screen
from command_center.ui.theme import C, dark_title_bar

if TYPE_CHECKING:
    from command_center.ui.app import App
    from command_center.ui.registry import Selection


class ToolWindow(tk.Toplevel):
    """A themed top-level window that knows the app context and the selected armies (None for a tool
    registered with needs_armies=False, when no lists are chosen). It fills the screen, and stays so.

    Closing it (or calling back()) returns to the launcher when no other tool is open."""

    title_text = "Tool"

    def __init__(self, app: "App", selection: "Selection | None"):
        super().__init__(app)
        self.app = app
        self.ctx = app.ctx
        self.selection = selection
        self.title(f"Command Center 40K — {self.title_text}")
        self.configure(bg=C["bg"])
        fill_screen(self)
        dark_title_bar(self)
        self.protocol("WM_DELETE_WINDOW", self.back)

    def back(self):
        self.destroy()
        self.app.on_tool_closed(self)
