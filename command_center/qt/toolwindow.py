"""Base class for tool windows."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from command_center.qt.screen import fill_screen

if TYPE_CHECKING:
    from command_center.qt.app import App
    from command_center.qt.registry import Selection


class ToolWindow(QWidget):
    """A top-level window that knows the app context and the selected armies (None for a tool
    registered with needs_armies=False, when no lists are chosen). It fills the screen, and stays so.

    Closing it (or calling back()) returns to the launcher when no other tool is open."""

    title_text = "Tool"

    def __init__(self, app: "App", selection: "Selection | None"):
        super().__init__()                      # no parent: a window of the launcher's would hide with it
        self.app = app
        self.ctx = app.ctx
        self.selection = selection
        self.setWindowTitle(f"Command Center 40K — {self.title_text}")
        self.setAttribute(Qt.WA_DeleteOnClose)
        fill_screen(self)

    def back(self):
        self.close()

    def closeEvent(self, event):
        self.app.on_tool_closed(self)
        super().closeEvent(event)
