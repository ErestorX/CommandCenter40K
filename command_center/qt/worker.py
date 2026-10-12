"""Work done off the window's thread, so that the window keeps answering while it goes."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal

_running: set["Task"] = set()           # tasks under way: kept until they end, whatever became of their window


class Task(QThread):
    """Runs `work()` on a thread of its own. `done` is then emitted with what it returned and None, or
    with None and the exception it raised; `step`, by the work itself if it reports as it goes.

    A signal reaches a window's method on the window's thread, and not at all once the window is gone:
    connect a method of the window, not a function made on the spot."""

    done = Signal(object, object)
    step = Signal(object)

    def __init__(self, work: Callable[[], object]):
        super().__init__()
        self.work = work
        self.finished.connect(self._ended)

    def run(self):
        try:
            result = self.work()
        except Exception as e:  # noqa: BLE001 - whatever went wrong is the caller's to show
            self.done.emit(None, e)
        else:
            self.done.emit(result, None)

    def begin(self) -> "Task":
        _running.add(self)
        self.start()
        return self

    def _ended(self):
        _running.discard(self)
