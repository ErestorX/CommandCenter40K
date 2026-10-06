"""Colours, fonts and ttk styles shared by every window.

A dark theme: black backgrounds, charcoal panels with a thin steel border, inset black fields, bevelled
buttons with their text in the display font, white text and a red accent.

Fonts: Caliban Angelus (assets/fonts, loaded for this process only) is the display font: titles,
headings, buttons, badges and tabs. Its digits and small sizes are hard to read, so numbers and body
text stay in the system's font (font_family()). BODY_IN_DISPLAY_FONT puts everything in it."""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from command_center import config

C = {
    "bg": "#0b0b0d",            # windows
    "panel": "#15151a",         # panels on a window
    "field": "#0e0e11",         # what holds content or is typed in: lists, tables, text, entries, cells
    "raised": "#22222a",        # buttons, table headings, a cell with a value
    "hover": "#2e2e38",
    "ink": "#e9e7e2", "muted": "#908d87", "dim": "#5c5a56",        # text; secondary; switched off
    "line": "#3b3b44", "grid": "#25252c",                           # borders; faint rules and tints
    "accent": "#d5352c",        # the red of the accent buttons
    "select": "#5a1d19",        # a selected row
    "att": "#e2554e", "def": "#6aa5ea",
    "bar": "#d5352c", "bar2": "#5e2623",
    "good": "#6fcf73", "warn": "#f0a030", "bad": "#5a1f1f",        # a win; VP lost, overkill; an invalid entry
}

DISPLAY_FAMILY = "Caliban Angelus"
BODY_IN_DISPLAY_FONT = False    # True: every text in the display font, numbers included
_display: str | None = None     # the display family once known to be there (else the system's)
_fonts_loaded = False

# Force Dispositions' colour code: ink (text), tint (a badge's background)
DISPOSITION_COLORS = {
    "take and hold": ("#6fcf73", "#17361a"),        # green
    "purge the foe": ("#f0625c", "#471715"),        # red
    "disruption": ("#8aa2f7", "#18214f"),           # deep blue
    "reconnaissance": ("#4fd1c5", "#0f3a38"),       # teal
    "priority assets": ("#f2cc4d", "#43360b"),      # yellow
}

# how hard a matchup is, by the group of its Estimate (command_center.deploy.estimates.difficulty_groups)
DIFFICULTY_COLORS = ("#c0392b", "#e67e22", "#f1c40f", "#8bc34a", "#2e7d32")        # the hardest group first
NO_ESTIMATE = C["field"]         # an empty circle: on the dark theme, an unfilled one


def disposition_colors(name: str) -> tuple[str, str]:
    """(ink, tint) of a Force Disposition; muted grey for one without a colour."""
    return DISPOSITION_COLORS.get(" ".join((name or "").lower().split()), (C["muted"], C["grid"]))


def load_fonts() -> None:
    """Make the fonts of assets/fonts usable by this process (Windows and macOS; elsewhere they must be
    installed). To call before the Tk root is created; once is enough, more calls do nothing."""
    global _fonts_loaded
    if sys.platform not in ("win32", "darwin") or _fonts_loaded:
        return
    _fonts_loaded = True
    try:
        import ctypes
        paths = sorted(config.FONTS_DIR.glob("*.ttf"))
        if sys.platform == "win32":
            for path in paths:
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)  # FR_PRIVATE: not installed, ours only
            return
        from ctypes.util import find_library
        cf, ct = ctypes.CDLL(find_library("CoreFoundation")), ctypes.CDLL(find_library("CoreText"))
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                                               ctypes.c_bool]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        for path in paths:
            raw = str(path).encode("utf-8")
            url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
            if url:
                ct.CTFontManagerRegisterFontsForURL(url, 1, None)           # kCTFontManagerScopeProcess: ours only
                cf.CFRelease(url)
    except Exception:  # noqa: BLE001 - no font: the system's is used
        pass


def set_icon(root: tk.Tk) -> None:
    """The app's icon on this root's window and on every window opened from it (and so in the taskbar)."""
    try:
        if sys.platform == "win32":
            root.iconbitmap(default=str(config.ICON_DIR / "icon.ico"))      # every size, sharp in the title bar
        else:
            root._icon = tk.PhotoImage(master=root, file=str(config.ICON_DIR / "icon.png"))
            root.iconphoto(True, root._icon)
    except Exception:  # noqa: BLE001 - cosmetic only: Tk's own icon
        pass


def dark_title_bar(win: tk.Misc) -> None:
    """Ask Windows for a dark title bar on a top-level window (ignored where it can't be done).
    To call once the window is set up: making it transient gives it a new frame, a plain one."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attribute in (20, 19):                  # DWMWA_USE_IMMERSIVE_DARK_MODE, and its older number
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def setup_style(root: tk.Tk) -> None:
    global _display
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(size=10)
    _display = DISPLAY_FAMILY if DISPLAY_FAMILY in tkfont.families(root) else None
    if _display and BODY_IN_DISPLAY_FONT:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
            tkfont.nametofont(name).configure(family=_display)
    fam, dis = base.actual("family"), display_family()
    root.fonts = {
        "h1": tkfont.Font(family=dis, size=17, weight="bold"),
        "h2": tkfont.Font(family=dis, size=12, weight="bold"),
        "big": tkfont.Font(family=fam, size=22, weight="bold"),
        "small": tkfont.Font(family=fam, size=9),
        "role": tkfont.Font(family=dis, size=10, weight="bold"),
        "button": tkfont.Font(family=dis, size=10, weight="bold"),
        "accent": tkfont.Font(family=dis, size=11, weight="bold"),
    }
    root.configure(bg=C["bg"])
    set_icon(root)
    dark_title_bar(root)
    # plain Tk widgets that are given no colours of their own
    for pattern, value in (("*Entry.background", C["field"]), ("*Entry.foreground", C["ink"]),
                           ("*Entry.insertBackground", C["ink"]), ("*Entry.disabledBackground", C["grid"]),
                           ("*Text.background", C["field"]), ("*Text.foreground", C["ink"]),
                           ("*Text.insertBackground", C["ink"]), ("*Text.selectBackground", C["select"]),
                           ("*Text.selectForeground", "white"), ("*Entry.selectBackground", C["select"]),
                           ("*Entry.selectForeground", "white"),
                           ("*Listbox.background", C["field"]), ("*Listbox.foreground", C["ink"]),
                           ("*Listbox.selectBackground", C["select"]), ("*Listbox.selectForeground", "white"),
                           ("*Canvas.background", C["panel"]), ("*Label.background", C["panel"]),
                           ("*Label.foreground", C["ink"]),
                           # the list a drop-down opens
                           ("*TCombobox*Listbox.background", C["field"]), ("*TCombobox*Listbox.foreground", C["ink"]),
                           ("*TCombobox*Listbox.selectBackground", C["select"]),
                           ("*TCombobox*Listbox.selectForeground", "white")):
        root.option_add(pattern, value)

    bevel = dict(bordercolor=C["line"], lightcolor="#4a4a55", darkcolor="#08080a")       # a raised edge
    flat = dict(bordercolor=C["line"], lightcolor=C["field"], darkcolor=C["field"])      # an inset field
    style.configure(".", background=C["bg"], foreground=C["ink"], fieldbackground=C["field"], bordercolor=C["line"],
                    lightcolor=C["panel"], darkcolor=C["panel"], troughcolor=C["field"], insertcolor=C["ink"],
                    selectbackground=C["select"], selectforeground="white", focuscolor=C["line"])
    # a disabled widget keeps the background of what it sits on (the theme's own would be light grey)
    style.map(".", foreground=[("disabled", C["dim"])], background=[])
    style.configure("MutedBg.TLabel", background=C["bg"], foreground=C["muted"], font=root.fonts["small"])
    style.configure("TFrame", background=C["bg"])
    style.configure("Panel.TFrame", background=C["panel"], relief="solid", borderwidth=1, bordercolor=C["line"])
    style.configure("Flat.TFrame", background=C["panel"], relief="flat", borderwidth=0)
    style.configure("TLabel", background=C["bg"], foreground=C["ink"])
    style.configure("Panel.TLabel", background=C["panel"])
    style.configure("Muted.TLabel", background=C["panel"], foreground=C["muted"], font=root.fonts["small"])
    style.configure("H1.TLabel", font=root.fonts["h1"])
    style.configure("H2.TLabel", background=C["panel"], font=root.fonts["h2"])
    style.configure("Big.TLabel", background=C["panel"], font=root.fonts["big"])
    style.configure("Att.TLabel", background=C["panel"], foreground=C["att"], font=root.fonts["role"])
    style.configure("Def.TLabel", background=C["panel"], foreground=C["def"], font=root.fonts["role"])

    # buttons: bevelled, their text in the display font; the accent ones in red
    style.configure("TButton", background=C["raised"], foreground=C["ink"], font=root.fonts["button"], padding=(12, 5),
                    relief="raised", **bevel)
    style.map("TButton", background=[("disabled", C["panel"]), ("pressed", C["field"]), ("active", C["hover"])],
              foreground=[("disabled", C["dim"])], lightcolor=[("pressed", "#08080a")], darkcolor=[("pressed", "#4a4a55")])
    style.configure("Accent.TButton", font=root.fonts["accent"], foreground=C["accent"], padding=(12, 6))
    style.map("Accent.TButton", foreground=[("disabled", C["dim"]), ("active", "#ff5a4f")])

    # tick boxes and radio buttons: an inset box, a light mark
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=C["bg"], foreground=C["ink"], indicatorbackground=C["field"],
                        indicatorforeground=C["ink"], upperbordercolor=C["line"], lowerbordercolor=C["line"],
                        focuscolor=C["bg"])
        style.map(name, background=[("active", C["bg"])], foreground=[("disabled", C["dim"])],
                  indicatorbackground=[("disabled", C["grid"]), ("pressed", C["hover"]), ("active", C["raised"])],
                  indicatorforeground=[("disabled", C["dim"])])
        style.configure(f"Panel.{name}", background=C["panel"], focuscolor=C["panel"])
        style.map(f"Panel.{name}", background=[("active", C["panel"])])

    # fields
    style.configure("TEntry", foreground=C["ink"], fieldbackground=C["field"], insertcolor=C["ink"], **flat)
    style.configure("TSpinbox", foreground=C["ink"], fieldbackground=C["field"], background=C["raised"],
                    arrowcolor=C["ink"], insertcolor=C["ink"], **flat)
    style.configure("TCombobox", foreground=C["ink"], fieldbackground=C["field"], background=C["raised"],
                    arrowcolor=C["ink"], **flat)
    style.map("TCombobox", fieldbackground=[("disabled", C["grid"]), ("readonly", C["field"])],
              foreground=[("disabled", C["dim"])], background=[("active", C["hover"])],
              selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["ink"])],
              arrowcolor=[("disabled", C["dim"])])
    # drop-downs of a sheet: black while they can be chosen from, greyed once locked
    style.map("Sheet.TCombobox", fieldbackground=[("disabled", C["grid"]), ("readonly", C["field"])],
              foreground=[("disabled", C["muted"])])

    # tables
    style.configure("Treeview", rowheight=22, background=C["field"], fieldbackground=C["field"], foreground=C["ink"],
                    **flat)
    style.configure("Treeview.Heading", font=root.fonts["small"], background=C["raised"], foreground=C["ink"],
                    relief="flat", **bevel)
    style.map("Treeview.Heading", background=[("active", C["hover"])])
    style.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", "white")])

    style.configure("TScrollbar", background=C["raised"], troughcolor=C["field"], arrowcolor=C["muted"], **bevel)
    style.map("TScrollbar", background=[("disabled", C["panel"]), ("active", C["hover"])],
              arrowcolor=[("disabled", C["grid"])])
    style.configure("TNotebook", background=C["bg"], bordercolor=C["line"], lightcolor=C["panel"],
                    darkcolor=C["panel"], tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=C["bg"], foreground=C["muted"], font=root.fonts["button"],
                    padding=(14, 5), bordercolor=C["line"], lightcolor=C["bg"], darkcolor=C["bg"])
    style.map("TNotebook.Tab", background=[("selected", C["panel"]), ("active", C["raised"])],
              foreground=[("selected", C["ink"]), ("active", C["ink"])],
              lightcolor=[("selected", C["panel"])], darkcolor=[("selected", C["panel"])])
    style.configure("TPanedwindow", background=C["bg"])
    style.configure("Sash", background=C["bg"], bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"])
    style.configure("TSeparator", background=C["line"])
    style.configure("TLabelframe", background=C["bg"], bordercolor=C["line"], lightcolor=C["bg"], darkcolor=C["bg"])
    style.configure("TLabelframe.Label", background=C["bg"], foreground=C["muted"])
    style.configure("Panel.TLabelframe", background=C["panel"], lightcolor=C["panel"], darkcolor=C["panel"])
    style.configure("Panel.TLabelframe.Label", background=C["panel"], foreground=C["muted"])
    style.configure("TProgressbar", background=C["accent"], troughcolor=C["field"], bordercolor=C["line"],
                    lightcolor=C["accent"], darkcolor=C["accent"])
    style.configure("TScale", background=C["raised"], troughcolor=C["field"], **bevel)
    style.map("TScale", background=[("active", C["hover"])])

    # cells of a matrix: black boxes on the panel
    style.configure("Cell.TFrame", background=C["field"], relief="solid", borderwidth=1, bordercolor=C["line"])
    style.configure("Cell.TLabel", background=C["field"])
    style.configure("CellMuted.TLabel", background=C["field"], foreground=C["muted"], font=root.fonts["small"])
    # badges: a value shown as a tinted tag, in its side's colours
    badge = dict(font=root.fonts["role"], padding=(10, 3), relief="flat", borderwidth=0)
    style.configure("AttBadge.TLabel", background="#4a1715", foreground="#ff8f88", **badge)
    style.configure("DefBadge.TLabel", background="#16304f", foreground="#9cc6f5", **badge)
    style.configure("MutedBadge.TLabel", background=C["grid"], foreground=C["muted"], **badge)


def font_family() -> str:
    """The family of body text and numbers."""
    return tkfont.nametofont("TkDefaultFont").actual("family")


def display_family() -> str:
    """The family of titles, headings and buttons: the display font, or the system's without it."""
    return _display or font_family()
