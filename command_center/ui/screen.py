"""How the app's windows take the screen: the main ones fill it and stay so, the floating ones opened
from them are as tall as it."""
from __future__ import annotations

import sys
import tkinter as tk

TITLE_BAR = 32      # a guess at the height of a window's title bar, until the window is there to be measured


def _zoom(win: tk.Misc) -> None:
    try:
        if sys.platform.startswith("linux"):
            win.attributes("-zoomed", True)
        else:
            win.state("zoomed")
    except tk.TclError:             # a window manager that can't: the screen's size, at least
        win.geometry(f"{win.winfo_screenwidth()}x{win.winfo_screenheight()}+0+0")


def fill_screen(win: tk.Misc) -> None:
    """Maximise a main window and keep it so: it can be minimised, but goes back to the full screen as soon
    as it is restored or resized. (Not `resizable(False, False)`, nor a title bar without its maximise button:
    Windows maximises such a window over the taskbar.)"""
    _zoom(win)

    def keep(e):
        if e.widget is win and win.state() == "normal":
            _zoom(win)
    win.bind("<Configure>", keep, add="+")


def screen_height(win: tk.Toplevel, width: int) -> None:
    """Make a floating window as tall as the screen allows (down to the taskbar, as its maximised parent),
    `width` wide at most, centred; only its width can then be changed."""
    parent = win.master.winfo_toplevel()
    parent.update_idletasks()
    screen_w = win.winfo_screenwidth()
    width = min(width, screen_w)
    x = (screen_w - width) // 2
    if parent.winfo_viewable():
        top = max(0, parent.winfo_y())                              # a maximised window starts off the screen
        bottom = parent.winfo_rooty() + parent.winfo_height()
    else:
        top, bottom = 0, win.winfo_screenheight() - 2 * TITLE_BAR
    win.geometry(f"{width}x{bottom - top - TITLE_BAR}+{x}+{top}")
    win.resizable(True, False)

    def measured(e):
        """Once it is on screen its frame can be measured: the height to the pixel, and what is centred is the
        window, not its frame."""
        if e.widget is not win:
            return
        win.unbind("<Map>", bound)
        win.update_idletasks()
        bar, side = win.winfo_rooty() - win.winfo_y(), win.winfo_rootx() - win.winfo_x()
        if bar > 0:
            win.geometry(f"{win.winfo_width()}x{bottom - top - bar}+{x - max(0, side)}+{top}")
    bound = win.bind("<Map>", measured, add="+")
