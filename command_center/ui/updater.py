"""The data update the app runs before anything else: when the data was last checked more than a day
ago (or never fetched, or BSData's files aren't there yet), a small window fetches it again
(command_center.data.fetch.update, what `python -m command_center fetch` does: BSData's army data, then
Wahapedia's), showing what it is doing; then the app starts.

Out of reach: it says so and the app starts with the data already on disk."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QDialog, QProgressBar, QVBoxLayout

from command_center import config
from command_center.data import fetch
from command_center.ui.widgets import Panel, label, restyle

RETRIES, TIMEOUT = 1, 20          # at start-up: one attempt per request, not long (the command line is more patient)
DONE_MS, FAILED_MS = 700, 3000    # how long the last message stays up before the app starts
WIDTH, HEIGHT = 560, 225


def edition_dir() -> Path:
    """Where the app's data lives: next to the CSVs it reads, or where fetch writes by default."""
    raw = config.find_data_dir()
    return raw.parent if raw else config.DATA_ROOT / config.EDITION


class _Thread(QThread):
    def __init__(self, work):
        super().__init__()
        self.work = work

    def run(self):
        self.work()


class UpdateWindow(QDialog):
    """Runs the update on a thread; closes itself when it is over. To show with exec()."""

    headline = "Checking BSData and Wahapedia for new data (done once a day)"
    failed = "The data could not be checked: starting with the data on disk."
    message = Signal(str)                   # from the worker thread: delivered on the window's

    def __init__(self, target):
        super().__init__()
        self.setWindowTitle("Command Center 40K")
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)     # no close button
        self.setFixedSize(WIDTH, HEIGHT)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        body = Panel()
        outer.addWidget(body)
        col = QVBoxLayout(body)
        col.setContentsMargins(18, 18, 18, 18)
        col.addWidget(label("Command Center 40K", "h1"))
        col.addSpacing(2)
        col.addWidget(label(self.headline))
        col.addSpacing(6)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)                                 # going: no end known
        col.addWidget(self.bar)
        col.addSpacing(6)
        self.status = label("", "muted", wrap=True)
        col.addWidget(self.status)
        col.addStretch(1)

        self.changed: bool | None = None                        # the data changed; None: the update failed
        self.error = ""
        self.message.connect(self._show)
        self._thread = _Thread(lambda: self._work(target))
        self._thread.finished.connect(self._over)
        self._thread.start()

    def log(self, text: str) -> None:
        """What the update is doing, from its thread."""
        self.message.emit(text)

    def _work(self, target: Path):
        """The update itself (worker thread: no widget touched here, messages go through log)."""
        saved = fetch.RETRIES, fetch.TIMEOUT
        fetch.RETRIES, fetch.TIMEOUT = RETRIES, TIMEOUT
        fetch.set_log(self.log)
        try:
            self.changed = fetch.update(target)
        except Exception as e:  # noqa: BLE001 - whatever went wrong, the app starts with what it has
            self.error = str(e)
        finally:
            fetch.set_log(None)
            fetch.RETRIES, fetch.TIMEOUT = saved

    def _show(self, text: str):
        text = text.strip()
        if text and self._thread.isRunning():
            self.status.setText(text.splitlines()[0])

    def _over(self):
        self.bar.setRange(0, 100)
        self.bar.setValue(0 if self.error else 100)
        if self.error:
            restyle(self.status, role="warn")
            self.status.setText(f"{self.failed}\n{self.error}")
        else:
            self.status.setText(self.done_text())
        QTimer.singleShot(FAILED_MS if self.error else DONE_MS, self.accept)

    def done_text(self) -> str:
        return "New data downloaded." if self.changed else "The data is up to date."

    def reject(self):                       # Escape, or the system's close: not while files are being written
        pass


def refresh_data(target: Path | None = None, max_age_hours: float = fetch.MAX_AGE_HOURS) -> bool | None:
    """Fetch the data again if its last check is more than `max_age_hours` old, or BSData's files aren't
    there yet, in a window of its own. Returns whether the data changed; None when nothing was due, or
    when the update failed."""
    target = target or edition_dir()
    has_bsdata = (config.bsdata_dir(target.parent) / config.BSDATA_SYSTEM_FILE).exists()
    if not fetch.is_stale(target, max_age_hours) and has_bsdata:
        return None
    win = UpdateWindow(target)
    win.exec()
    return win.changed
