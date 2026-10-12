"""Application shell: starts Qt, updates the app and the data if they are due (command_center.qt.appupdate,
command_center.qt.updater), loads the shared context, shows the launcher and opens tools from the registry.

    python -m command_center qt
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget

from command_center.context import AppContext
from command_center.lists.library import install_demo
from command_center.qt.appupdate import update_app
from command_center.qt.launcher import Launcher
from command_center.qt.registry import Selection, discover, get_tool
from command_center.qt.screen import fill_screen, put_away, show_again
from command_center.qt.theme import app_identity, setup_style
from command_center.qt.updater import refresh_data
from command_center.release import use_bundled_certificates


def application() -> QApplication:
    """The process's Qt application, with the app's look: made at the first call."""
    app = QApplication.instance()
    if app is None:
        app_identity()
        app = QApplication(sys.argv[:1])
        app.setApplicationName("Command Center 40K")
        setup_style(app)
    return app


class App(QWidget):
    """The launcher's window, and what the tools opened from it share: the context, the list of them."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Command Center 40K")
        fill_screen(self)
        self.open_windows: list[QWidget] = []
        self.launcher = Launcher(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.launcher)

    def open_tool(self, key: str, selection: Selection | None) -> QWidget:
        win = get_tool(key).open(self, selection)
        self.open_windows.append(win)
        win.show()
        put_away(self)
        return win

    def on_tool_closed(self, win: QWidget) -> None:
        if win in self.open_windows:
            self.open_windows.remove(win)
        if not self.open_windows:
            show_again(self)


def main(data_dir: str | None = None) -> None:
    """data_dir: a folder of Wahapedia CSVs to use as it is; without one, the app's own data, which is
    fetched again first when its last check is more than a day old."""
    discover()
    use_bundled_certificates()
    install_demo()
    qt = application()
    if data_dir is None:
        if update_app():                   # the packaged app is installing its new version: it comes back
            raise SystemExit(0)
        refresh_data()
    try:
        ctx = AppContext(data_dir)
    except FileNotFoundError as e:
        QMessageBox.critical(None, "Command Center 40K", f"{e}\n\nThe data could not be downloaded: check the "
                             "connection and start the app again, or run:  python -m command_center fetch")
        raise SystemExit(1)
    win = App(ctx)
    win.show()
    raise SystemExit(qt.exec())
