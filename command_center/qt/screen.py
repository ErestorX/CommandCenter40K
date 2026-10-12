"""How the app's windows take the screen: the main ones fill it and stay so, the floating ones opened
from them are as tall as it."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QStyle, QWidget


class _StayMaximised(QObject):
    def eventFilter(self, win, event):
        if event.type() == QEvent.WindowStateChange and not win.windowState() & (
                Qt.WindowMaximized | Qt.WindowMinimized | Qt.WindowFullScreen):
            QTimer.singleShot(0, win.showMaximized)             # once Qt is done with this change
        return False


def fill_screen(win: QWidget) -> None:
    """Have a main window open maximised and keep it so: it can be minimised, but goes back to the full
    screen as soon as it is restored."""
    win.setWindowState(win.windowState() | Qt.WindowMaximized)
    win._stay_maximised = _StayMaximised(win)
    win.installEventFilter(win._stay_maximised)


def available(win: QWidget | None = None):
    """The part of the screen windows may take (without the taskbar): that of `win`'s screen."""
    screen = (win.screen() if win is not None else None) or QGuiApplication.primaryScreen()
    return screen.availableGeometry()


class _FullHeight(QObject):
    def __init__(self, win: QWidget, parent: QWidget | None):
        super().__init__(win)
        self.parent_window, self.done = parent, False

    def eventFilter(self, win, event):
        if event.type() == QEvent.Show and not self.done:
            self.done = True
            QTimer.singleShot(0, lambda: self.place(win))       # its frame is known once it is on screen
        return False

    def place(self, win: QWidget):
        area, frame = available(self.parent_window), win.frameGeometry()
        bar = frame.height() - win.height()
        if bar > 0:
            win.setFixedHeight(area.height() - bar)
        win.move(area.x() + (area.width() - win.frameGeometry().width()) // 2, area.y())


def screen_height(win: QWidget, width: int, parent: QWidget | None = None) -> None:
    """Make a floating window as tall as the screen allows (down to the taskbar, as its maximised parent),
    `width` wide at most, centred; only its width can then be changed. Its title bar's height is a guess
    until the window is shown and can be measured."""
    area = available(parent)
    bar = win.style().pixelMetric(QStyle.PM_TitleBarHeight)
    width = min(width, area.width())
    win.resize(width, area.height() - bar)
    win.setFixedHeight(area.height() - bar)
    win.move(area.x() + (area.width() - width) // 2, area.y())
    win._full_height = _FullHeight(win, parent)
    win.installEventFilter(win._full_height)
