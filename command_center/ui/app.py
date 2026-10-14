"""Application shell: starts Qt, updates the app and the data if they are due (command_center.ui.appupdate,
command_center.ui.updater), loads the shared context, shows the launcher and opens tools from the registry.

    python main.py            # or: python -m command_center
"""
from __future__ import annotations

import gc
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget

from command_center.context import AppContext
from command_center.lists.library import install_demo
from command_center.ui.appupdate import update_app
from command_center.ui.launcher import Launcher
from command_center.ui.registry import Selection, discover, get_tool
from command_center.ui.screen import fill_screen, put_away, show_again
from command_center.ui.theme import app_identity, setup_style
from command_center.ui.updater import refresh_data
from command_center.release import use_bundled_certificates


def application() -> QApplication:
    """The process's Qt application, with the app's look: made at the first call. Python's garbage
    collector then runs on the main thread only (collect_on_main_thread)."""
    app = QApplication.instance()
    if app is None:
        app_identity()
        app = QApplication(sys.argv[:1])
        app.setApplicationName("Command Center 40K")
        setup_style(app)
        collect_on_main_thread(app)
    return app


GC_INTERVAL_MS = 250
_gc_timer: QTimer | None = None


def collect_on_main_thread(app: QApplication) -> None:
    """Python collects garbage in whichever thread happens to be allocating when a collection is due:
    a simulation's worker thread (command_center.ui.worker) too. Freeing a Qt object there (a window
    closed a moment before, its timers) destroys it outside the thread it belongs to, which Qt
    reports ("QBasicTimer::stop: Failed...") and can crash on. So automatic collection is off, and a
    timer on the main thread does what it would: a generation is collected once its count is past its
    threshold."""
    global _gc_timer
    gc.disable()
    _gc_timer = QTimer(app)
    _gc_timer.timeout.connect(_collect_garbage)
    _gc_timer.start(GC_INTERVAL_MS)


def _collect_garbage() -> None:
    counts, thresholds = gc.get_count(), gc.get_threshold()
    for generation in (2, 1, 0):
        if generation < len(counts) and 0 < thresholds[generation] < counts[generation]:
            gc.collect(generation)
            return


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
