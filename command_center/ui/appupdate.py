"""The packaged app's own update, at every start-up (the logic is in command_center.release): when
GitHub has a newer release, the app offers to install it (one that was declined, not again for a day); on a yes, a small window downloads it,
then the app closes and comes back as the new version."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from command_center import release
from command_center.ui.updater import UpdateWindow


class AppUpdateWindow(UpdateWindow):
    """Downloads and unpacks a release (its zip's address is the target)."""

    headline = "Downloading the new version of the app"
    failed = "The update could not be downloaded: starting the version there is."

    def _work(self, url: str):
        self.new_dir = None
        try:
            self.new_dir = release.download(url, self._messages.put)
        except Exception as e:  # noqa: BLE001 - whatever went wrong, the app starts as it is
            self.error = str(e)

    def done_text(self) -> str:
        return "Installing: the app will start again in a moment."


def update_app() -> bool:
    """Offer the latest release when it is newer than the running app, and start its installation.
    True: the installation is under way and the app must exit now. From the source: nothing, False."""
    current = release.current_version()
    if not current or not release.can_install():
        return False
    try:
        found = release.latest_release()
    except Exception:  # noqa: BLE001 - offline, or GitHub out of reach: asked again at the next start
        return False
    if not found or not release.is_newer(found[0], current) or release.was_declined(found[0]):
        return False
    tag, url = found
    root = tk.Tk()
    root.withdraw()
    wanted = messagebox.askyesno("Command Center 40K", f"Version {tag} of the app is available (this is {current}).\n\n"
                                                       "Install it now? Your lists and saved work are kept.")
    root.destroy()
    if not wanted:
        release.mark_declined(tag)
        return False
    win = AppUpdateWindow(url)
    win.mainloop()
    if win.new_dir is None:
        return False
    try:
        release.install(win.new_dir)
    except Exception:  # noqa: BLE001 - the app starts as it is
        return False
    return True
