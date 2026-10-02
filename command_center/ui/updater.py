"""The data update the app runs before anything else: when the Wahapedia data was last checked more
than a day ago (or never fetched), a small window fetches it again (command_center.data.fetch.update,
what `python -m command_center fetch` does), showing what it is doing; then the app starts.

Wahapedia out of reach: it says so and the app starts with the data already on disk."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from command_center import config
from command_center.data import fetch
from command_center.ui.theme import C, dark_title_bar, load_fonts, setup_style

RETRIES, TIMEOUT = 1, 20          # at start-up: one attempt per request, not long (the command line is more patient)
DONE_MS, FAILED_MS = 700, 3000    # how long the last message stays up before the app starts


def edition_dir() -> Path:
    """Where the app's data lives: next to the CSVs it reads, or where fetch writes by default."""
    raw = config.find_data_dir()
    return raw.parent if raw else config.DATA_ROOT / config.EDITION


class UpdateWindow(tk.Tk):
    """Runs the update on a thread; closes itself when it is over."""

    def __init__(self, target: Path):
        load_fonts()
        super().__init__()
        self.title("Command Center 40K")
        setup_style(self)
        self.resizable(False, False)
        w, h = 560, 225
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{(self.winfo_screenheight() - h) // 2}")
        self.protocol("WM_DELETE_WINDOW", lambda: None)        # not while files are being written
        dark_title_bar(self)                                    # again: a fixed-size window gets a new frame
        body = ttk.Frame(self, style="Panel.TFrame", padding=18)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Label(body, text="Command Center 40K", style="H1.TLabel", background=C["panel"]).pack(anchor="w")
        ttk.Label(body, text="Checking Wahapedia for new data (done once a day)", style="Panel.TLabel").pack(
            anchor="w", pady=(6, 10))
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.status = ttk.Label(body, text="", style="Muted.TLabel", wraplength=w - 60, justify="left")
        self.status.pack(anchor="w", pady=(10, 0))

        self.changed: bool | None = None                        # the data changed; None: the update failed
        self.error = ""
        self._messages: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._work, args=(target,), daemon=True)
        self._thread.start()
        self.after(100, self._poll)

    def _work(self, target: Path):
        """The update itself (worker thread: no Tk here, messages go through the queue)."""
        saved = fetch.RETRIES, fetch.TIMEOUT
        fetch.RETRIES, fetch.TIMEOUT = RETRIES, TIMEOUT
        fetch.set_log(self._messages.put)
        try:
            self.changed = fetch.update(target)
        except Exception as e:  # noqa: BLE001 - whatever went wrong, the app starts with what it has
            self.error = str(e)
        finally:
            fetch.set_log(None)
            fetch.RETRIES, fetch.TIMEOUT = saved

    def _poll(self):
        last = ""
        while not self._messages.empty():
            last = self._messages.get_nowait().strip() or last
        if last:
            self.status.configure(text=last.splitlines()[0])
        if self._thread.is_alive():
            self.after(100, self._poll)
            return
        self.bar.stop()
        if self.error:
            self.bar.configure(mode="determinate", value=0)
            self.status.configure(text=f"Wahapedia could not be checked: starting with the data on disk.\n{self.error}",
                                  foreground=C["warn"])
        else:
            self.bar.configure(mode="determinate", value=100)
            self.status.configure(text="New data downloaded." if self.changed else "The data is up to date.")
        self.after(FAILED_MS if self.error else DONE_MS, self.destroy)


def refresh_data(target: Path | None = None, max_age_hours: float = fetch.MAX_AGE_HOURS) -> bool | None:
    """Fetch the data again if its last check is more than `max_age_hours` old, in a window of its own.
    Returns whether the data changed; None when nothing was due, or when the update failed."""
    target = target or edition_dir()
    if not fetch.is_stale(target, max_age_hours):
        return None
    win = UpdateWindow(target)
    win.mainloop()
    return win.changed
