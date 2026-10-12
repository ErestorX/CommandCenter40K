"""Colours, fonts and styles shared by every window.

A dark theme: black backgrounds, charcoal panels with a thin steel border, inset black fields, bevelled
buttons with their text in the display font, white text and a red accent. The colours are those of
command_center.ui.palette; here they become the application's palette and its style sheet.

A widget takes a style by its `role` property (command_center.ui.widgets sets it): QLabel[role="h1"],
QFrame[role="panel"], QPushButton[role="accent"]...

Fonts: Caliban Angelus (assets/fonts, loaded for this process only) is the display font: titles,
headings, buttons, badges and tabs. Its digits and small sizes are hard to read, so numbers and body
text stay in the system's font (font_family()). BODY_IN_DISPLAY_FONT puts everything in it."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from command_center import config
from command_center.ui.palette import (BODY_IN_DISPLAY_FONT, C, DIFFICULTY_COLORS, DISPLAY_FAMILY,  # noqa: F401
                                       DISPOSITION_COLORS, NO_ESTIMATE, disposition_colors)

BODY_SIZE = 10                  # points
_display: str | None = None     # the display family once known to be there (else the system's)
_body = ""

STYLE = """
QToolTip {{ background: {raised}; color: {ink}; border: 1px solid {line}; padding: 2px 6px; }}

QFrame[role="panel"] {{ background: {panel}; border: 1px solid {line}; }}
QFrame[role="cell"] {{ background: {field}; border: 1px solid {line}; }}
QFrame[role="cell"][on="true"] {{ border-color: {accent}; }}
QFrame[role="rule"] {{ background: {line}; border: none; }}

QLabel[role="h1"] {{ font-family: "{display}"; font-size: 17pt; font-weight: bold; }}
QLabel[role="h2"] {{ font-family: "{display}"; font-size: 12pt; font-weight: bold; }}
QLabel[role="big"] {{ font-size: 22pt; font-weight: bold; }}
QLabel[role="muted"] {{ color: {muted}; font-size: 9pt; }}
QLabel[role="warn"] {{ color: {warn}; font-size: 9pt; }}
QLabel[role="small"] {{ font-size: 9pt; }}
QLabel[role="total"] {{ font-weight: bold; }}
QLabel[role="att"] {{ color: {att}; font-family: "{display}"; font-weight: bold; }}
QLabel[role="def"] {{ color: {def}; font-family: "{display}"; font-weight: bold; }}
QLabel[role="att-badge"], QLabel[role="def-badge"], QLabel[role="muted-badge"] {{
    font-family: "{display}"; font-weight: bold; padding: 3px 10px; }}
QLabel[role="att-badge"] {{ background: #4a1715; color: #ff8f88; }}
QLabel[role="def-badge"] {{ background: #16304f; color: #9cc6f5; }}
QLabel[role="muted-badge"] {{ background: {grid}; color: {muted}; }}

QPushButton {{ font-family: "{display}"; font-weight: bold; color: {ink}; background: {raised}; padding: 5px 12px;
    border: 1px solid {line}; border-top-color: #4a4a55; border-left-color: #4a4a55; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {field}; border-color: {line}; border-top-color: #08080a; border-left-color: #08080a; }}
QPushButton:disabled {{ color: {dim}; background: {panel}; }}
QPushButton[role="accent"] {{ color: {accent}; font-size: 11pt; padding: 6px 12px; }}
QPushButton[role="accent"]:hover {{ color: #ff5a4f; }}
QPushButton[role="accent"]:disabled {{ color: {dim}; }}
QPushButton[role="step"] {{ font-family: "{body}"; padding: 0px 5px; border: none; }}
QPushButton[role="switch"] {{ color: {muted}; font-size: 11pt; padding: 7px 18px; min-width: 70px; }}
QPushButton[role="switch"]:hover {{ color: {ink}; }}
QPushButton[role="switch"]:checked {{ color: {accent}; background: {field}; border-color: {line};
    border-top-color: #08080a; border-left-color: #08080a; }}

QTreeWidget {{ background: {field}; color: {ink}; border: 1px solid {line}; outline: none; }}
QTreeWidget::item {{ padding: 2px 3px; }}
QTreeWidget::item:selected {{ background: {select}; color: white; }}
QHeaderView::section {{ background: {raised}; color: {ink}; font-size: 9pt; padding: 3px 4px; border: none;
    border-right: 1px solid {line}; border-bottom: 1px solid {line}; }}
QTreeWidget[role="filters"] {{ background: {field}; }}
QTabWidget::pane {{ border: 1px solid {line}; background: {panel}; top: -1px; }}
QTabBar::tab {{ font-family: "{display}"; font-weight: bold; color: {muted}; background: {bg}; padding: 5px 14px;
    border: 1px solid {line}; margin-right: 2px; }}
QTabBar::tab:hover {{ color: {ink}; background: {raised}; }}
QTabBar::tab:selected {{ color: {ink}; background: {panel}; border-bottom-color: {panel}; }}
QSplitter::handle {{ background: {bg}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QSpinBox {{ background: {field}; color: {ink}; border: 1px solid {line}; padding: 2px 4px; }}
QSlider::groove:horizontal {{ height: 6px; background: {field}; border: 1px solid {line}; }}
QSlider::handle:horizontal {{ width: 12px; margin: -6px 0; background: {raised}; border: 1px solid {line};
    border-top-color: #4a4a55; border-left-color: #4a4a55; }}
QSlider::handle:horizontal:hover {{ background: {hover}; }}
QMenu {{ background: {raised}; color: {ink}; border: 1px solid {line}; padding: 3px; }}
QMenu::item {{ padding: 4px 18px; }}
QMenu::item:selected {{ background: {select}; color: white; }}
QGroupBox {{ border: 1px solid {line}; margin-top: 9px; padding-top: 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0px 3px; color: {muted}; }}
QComboBox {{ background: {field}; color: {ink}; border: 1px solid {line}; padding: 2px 6px; }}
QComboBox:disabled {{ background: {grid}; color: {dim}; }}
QComboBox::drop-down {{ background: {raised}; border-left: 1px solid {line}; width: 16px; }}
QComboBox::drop-down:hover {{ background: {hover}; }}
QComboBox QAbstractItemView {{ background: {field}; color: {ink}; border: 1px solid {line};
    selection-background-color: {select}; selection-color: white; outline: none; }}

QListWidget, QPlainTextEdit, QLineEdit {{ background: {field}; color: {ink}; border: 1px solid {line};
    selection-background-color: {select}; selection-color: white; }}
QListWidget {{ border: none; outline: none; }}
QListWidget::item:selected {{ background: {select}; color: white; }}
QLineEdit {{ padding: 3px 4px; }}
QLineEdit[state="done"] {{ background: {raised}; }}
QLineEdit[state="bad"] {{ background: {bad}; }}

QProgressBar {{ background: {field}; border: 1px solid {line}; max-height: 12px; }}
QProgressBar::chunk {{ background: {accent}; }}
QScrollArea {{ border: none; }}
"""


def load_fonts() -> list[str]:
    """Make the fonts of assets/fonts usable by this process, and return their families. Qt does it on
    every system: nothing is installed."""
    return [family for path in sorted(config.FONTS_DIR.glob("*.ttf"))
            for family in QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(path)))]


def app_identity() -> None:
    """An app of its own in the Windows taskbar, with its windows' icon: not grouped under Python's.
    To call before the first window."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ErestorX.CommandCenter40K")
        except Exception:  # noqa: BLE001 - cosmetic only
            pass


def setup_style(app: QApplication) -> None:
    """The app's look, on every window opened from now on: colours, fonts, icon, dark title bars."""
    global _display, _body
    app.setStyle("Fusion")                      # the same widgets on every system, drawn from the palette
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)        # the title bars too
    _display = DISPLAY_FAMILY if DISPLAY_FAMILY in load_fonts() else None
    font = app.font()
    if _display and BODY_IN_DISPLAY_FONT:
        font.setFamily(_display)
    font.setPointSize(BODY_SIZE)
    app.setFont(font)
    _body = font.family()
    icon = config.ICON_DIR / ("icon.ico" if sys.platform == "win32" else "icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    p = QPalette()
    for role, color in ((QPalette.Window, C["bg"]), (QPalette.WindowText, C["ink"]), (QPalette.Base, C["field"]),
                        (QPalette.AlternateBase, C["panel"]), (QPalette.Text, C["ink"]), (QPalette.Button, C["raised"]),
                        (QPalette.ButtonText, C["ink"]), (QPalette.Highlight, C["select"]),
                        (QPalette.HighlightedText, "white"), (QPalette.ToolTipBase, C["raised"]),
                        (QPalette.ToolTipText, C["ink"]), (QPalette.PlaceholderText, C["muted"]),
                        (QPalette.Light, "#4a4a55"), (QPalette.Midlight, C["hover"]), (QPalette.Mid, C["line"]),
                        (QPalette.Dark, "#08080a"), (QPalette.Shadow, "#000000"), (QPalette.Link, C["def"])):
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(C["dim"]))
    app.setPalette(p)
    app.setStyleSheet(STYLE.format(display=display_family(), body=_body, **C))


def font_family() -> str:
    """The family of body text and numbers."""
    return _body or QApplication.font().family()


def display_family() -> str:
    """The family of titles, headings and buttons: the display font, or the system's without it."""
    return _display or font_family()
