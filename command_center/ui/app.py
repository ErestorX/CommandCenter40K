"""Application shell: creates the Tk root, loads the shared context, shows the launcher and
opens tools from the registry.

    python main.py            # or: python -m command_center
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from command_center.context import AppContext
from command_center.ui.launcher import Launcher
from command_center.ui.registry import Selection, discover, get_tool
from command_center.ui.theme import setup_style


class App(tk.Tk):
    def __init__(self, ctx: AppContext):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp text on high-DPI screens
            except Exception:  # noqa: BLE001 - older Windows: keep default scaling
                pass
        super().__init__()
        self.ctx = ctx
        self.title("Command Center 40K")
        setup_style(self)                  # also sets self.fonts
        self.geometry("980x560")
        self.minsize(820, 480)
        self.open_windows: list[tk.Toplevel] = []
        self.launcher = Launcher(self)
        self.launcher.pack(fill="both", expand=True)

    def open_tool(self, key: str, selection: Selection | None) -> tk.Toplevel:
        win = get_tool(key).open(self, selection)
        self.open_windows.append(win)
        self.withdraw()
        return win

    def on_tool_closed(self, win: tk.Toplevel) -> None:
        if win in self.open_windows:
            self.open_windows.remove(win)
        if not self.open_windows:
            self.deiconify()


def main(data_dir: str | None = None) -> None:
    discover()
    try:
        ctx = AppContext(data_dir)
    except FileNotFoundError as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Command Center 40K", f"{e}\n\nRun:  python -m command_center fetch")
        root.destroy()
        raise SystemExit(1)
    App(ctx).mainloop()
