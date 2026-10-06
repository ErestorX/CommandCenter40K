"""Application shell: updates the data if it is due (command_center.ui.updater), then creates the Tk
root, loads the shared context, shows the launcher and opens tools from the registry.

    python main.py            # or: python -m command_center
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from command_center.context import AppContext
from command_center.lists.library import install_demo
from command_center.release import use_bundled_certificates
from command_center.ui.appupdate import update_app
from command_center.ui.launcher import Launcher
from command_center.ui.registry import Selection, discover, get_tool
from command_center.ui.screen import fill_screen
from command_center.ui.theme import load_fonts, setup_style
from command_center.ui.updater import refresh_data


def dpi_aware() -> None:
    """Crisp text on high-DPI screens (Windows). To call before the first window."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - older Windows, or already set: keep the scaling there is
            pass
        try:        # an app of its own in the taskbar, with its windows' icon: not grouped under Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ErestorX.CommandCenter40K")
        except Exception:  # noqa: BLE001 - cosmetic only
            pass


class App(tk.Tk):
    def __init__(self, ctx: AppContext):
        dpi_aware()
        load_fonts()                       # before Tk starts: it lists the fonts once
        super().__init__()
        self.ctx = ctx
        self.title("Command Center 40K")
        setup_style(self)                  # also sets self.fonts
        fill_screen(self)
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
    """data_dir: a folder of Wahapedia CSVs to use as it is; without one, the app's own data, which is
    fetched again first when its last check is more than a day old."""
    discover()
    use_bundled_certificates()
    install_demo()
    if data_dir is None:
        dpi_aware()
        if update_app():                   # the packaged app is installing its new version: it comes back
            raise SystemExit(0)
        refresh_data()
    try:
        ctx = AppContext(data_dir)
    except FileNotFoundError as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Command Center 40K", f"{e}\n\nThe data could not be downloaded: check the connection and "
                                                   "start the app again, or run:  python -m command_center fetch")
        root.destroy()
        raise SystemExit(1)
    App(ctx).mainloop()
