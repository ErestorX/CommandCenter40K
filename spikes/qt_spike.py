"""A Qt spike: what the migration evaluated in docs/qt_migration.md would look like, on the app's real
data and back end. Not part of the app, and not shipped with it.

    pip install PySide6-Essentials
    python spikes/qt_spike.py                    the window
    python spikes/qt_spike.py --shot spike.png   save a picture of the window and exit (it need not be in
                                                 front, nor on a screen: QT_QPA_PLATFORM=offscreen, with
                                                 QT_QPA_FONTDIR set to the system's fonts)

What it tries, each where Tk needed a workaround or a hand-made part:
  - the theme: the app's palette (command_center.ui.theme.C) as one style sheet, Caliban Angelus loaded
    from assets/fonts by Qt itself, a dark title bar asked of Qt
  - a real layout as a scene in board inches: the view scales it, nothing is drawn again on a resize
  - units as items with real transparency, dragged by Qt (stopped at the board's edges), turned by a
    double click; the selected one's line of sight (command_center.deploy.sight) drawn again as it moves
  - a heatmap painted by hand with tooltips, as command_center.ui.charts
  - Wahapedia's HTML handed as it is to a text browser
  - a worker thread that reports through signals
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))               # run from anywhere: the app's package is next to this folder

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton, QSplitter, QTabWidget,
                               QTextBrowser, QToolTip, QVBoxLayout, QWidget)

from command_center import config
from command_center.context import AppContext
from command_center.deploy.placement import clamp, ellipse_polygon, extent, random_spot
from command_center.deploy.sight import Obstacles, cast, fans
from command_center.ui.charts import ramp_color
from command_center.ui.theme import C, DISPLAY_FAMILY
from command_center.ui.tools.holomap.map_view import (AREA_FILL, AREA_LINE, BOARD_FILL, BOARD_H, BOARD_INK, BOARD_W,
                                                      FEATURE_FILL, SELECTED, SIGHT_FILL, TOKEN, ZONE_FILL,
                                                      objective_fill)

STYLE = """
* {{ color: {ink}; font-size: 10pt; }}
QMainWindow, QWidget {{ background: {bg}; }}
QFrame#panel {{ background: {panel}; border: 1px solid {line}; }}
QFrame#panel QLabel, QFrame#panel QCheckBox {{ background: {panel}; }}
QLabel#h1 {{ font-family: "{display}"; font-size: 17pt; font-weight: bold; }}
QLabel#muted {{ color: {muted}; font-size: 9pt; }}
QPushButton {{ font-family: "{display}"; font-weight: bold; background: {raised}; padding: 5px 12px;
               border: 1px solid {line}; border-top-color: #4a4a55; border-left-color: #4a4a55; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed, QPushButton:checked {{ background: {field}; color: {accent};
               border-top-color: #08080a; border-left-color: #08080a; }}
QPushButton[accent="true"] {{ color: {accent}; font-size: 11pt; }}
QComboBox, QTextBrowser {{ background: {field}; border: 1px solid {line}; padding: 3px 6px;
               selection-background-color: {select}; }}
QComboBox QAbstractItemView {{ background: {field}; selection-background-color: {select}; }}
QProgressBar {{ background: {field}; border: 1px solid {line}; max-height: 10px; }}
QProgressBar::chunk {{ background: {accent}; }}
QTabWidget::pane {{ border: 1px solid {line}; }}
QTabBar::tab {{ font-family: "{display}"; font-weight: bold; color: {muted}; background: {bg};
               padding: 5px 14px; border: 1px solid {line}; }}
QTabBar::tab:selected {{ color: {ink}; background: {panel}; }}
QSplitter::handle {{ background: {bg}; }}
QToolTip {{ background: {raised}; color: {ink}; border: 1px solid {line}; }}
"""


def color(hex_code: str, opacity: float = 1.0) -> QColor:
    c = QColor(hex_code)
    c.setAlphaF(opacity)
    return c


def polygon(points) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


# =============================================================================
# the board
# =============================================================================
class Token(QGraphicsPolygonItem):
    """A unit: its footprint's ellipse, half see-through, dragged by Qt and kept on the board."""

    def __init__(self, board: "Board", role: str, label: str, w: float, h: float, x: float, y: float, reach: float):
        super().__init__(polygon(ellipse_polygon(0, 0, w, h)))
        self.board, self.role, self.label, self.w, self.h, self.reach = board, role, label, w, h, reach
        fill, line = TOKEN[role]
        self.setBrush(color(fill, 0.5))                 # what Tk does with stipples, or with an image on macOS
        self.setPen(QPen(QColor(line), 0))              # 0: one pixel wide whatever the zoom
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f'{label}  ·  {w:.1f}" x {h:.1f}"')
        self.setZValue(10)
        self.setPos(x, y)
        name = QGraphicsSimpleTextItem(label, self)
        name.setFlag(QGraphicsItem.ItemIgnoresTransformations)      # text in pixels, not in inches
        name.setBrush(QColor(line))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        name.setFont(font)
        name.setPos(-w / 2, -h / 2 - 0.3)

    def outline(self, n: int = 72):
        return ellipse_polygon(self.x(), self.y(), self.w, self.h, self.rotation(), n=n)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(*clamp(value.x(), value.y(), *extent(self.w, self.h, self.rotation())))
        if change == QGraphicsItem.ItemPositionHasChanged and self.isSelected():
            self.board.show_sight(self)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setPen(QPen(QColor(SELECTED if value else TOKEN[self.role][1]), 0.25 if value else 0))
            self.board.show_sight(self if value else None)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.setRotation((self.rotation() + 30) % 360)
        self.board.show_sight(self)


class Board(QGraphicsView):
    """A layout drawn once, in inches, y up: the view does the scaling."""

    def __init__(self, layout: dict):
        self.board_scene = QGraphicsScene(0, 0, BOARD_W, BOARD_H)     # kept: a view does not own its scene
        super().__init__(self.board_scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor(C["panel"]))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.scale(1, -1)
        self.obstacles = Obstacles.from_layout(layout)
        self.sight_ms: list[float] = []
        scene, none = self.board_scene, QPen(Qt.NoPen)
        scene.addRect(0, 0, BOARD_W, BOARD_H, none, QColor(BOARD_FILL))
        for side in ("attacker", "defender"):
            for zone in layout.get("deployment_zones", {}).get(side, []):
                scene.addPolygon(polygon(zone), none, QColor(ZONE_FILL[side]))
        for area in layout.get("terrain", []):
            for fp in area.get("footprints", []):
                scene.addPolygon(polygon(fp["points"]), QPen(QColor(AREA_LINE), 0), QColor(AREA_FILL))
        for area in layout.get("terrain", []):
            for f in area.get("features", []):
                scene.addPolygon(polygon(f["points"]), none, QColor(FEATURE_FILL.get(f.get("category"), "#8a857a")))
        for o in layout.get("objectives", []):
            x, y = o["position"]
            scene.addEllipse(x - 0.9, y - 0.9, 1.8, 1.8, QPen(QColor("white"), 0.15), QColor(objective_fill(o)))
        scene.addRect(0, 0, BOARD_W, BOARD_H, QPen(QColor(BOARD_INK), 0))
        self.sight = QGraphicsPathItem()
        self.sight.setPen(none)
        self.sight.setBrush(color(SIGHT_FILL, 0.3))
        self.sight.setZValue(5)                         # over the terrain, under the units
        scene.addItem(self.sight)

    def add_token(self, role: str, label: str, w: float, h: float, reach: float, zones, rng) -> Token:
        token = Token(self, role, label, w, h, *random_spot(zones, w, h, rng), reach)
        self.scene().addItem(token)
        return token

    def show_sight(self, token: Token | None):
        """What `token` sees: the union of its fans as one path, so no darker where they overlap."""
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        if token:
            t0 = time.perf_counter()
            for fan in fans(cast(token.outline(), token.reach, self.obstacles)):
                path.addPolygon(polygon(fan))
                path.closeSubpath()
            self.sight_ms.append((time.perf_counter() - t0) * 1000)
        self.sight.setPath(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(QRectF(0, 0, BOARD_W, BOARD_H), Qt.KeepAspectRatio)


# =============================================================================
# a heatmap, painted by hand
# =============================================================================
class Heatmap(QWidget):
    ROW_W, HEAD_H, CELL_H = 170, 30, 30

    def __init__(self, rows: list[str], cols: list[str], values: list[list[float]]):
        super().__init__()
        self.rows, self.cols, self.values = rows, cols, values
        self.setMouseTracking(True)
        self.setMinimumHeight(self.HEAD_H + len(rows) * self.CELL_H + 10)

    def _cell_w(self) -> float:
        return max(60.0, (self.width() - self.ROW_W - 10) / len(self.cols))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["panel"]))
        cw = self._cell_w()
        flat = [v for row in self.values for v in row]
        low, span = min(flat), (max(flat) - min(flat)) or 1.0
        for j, name in enumerate(self.cols):
            p.drawText(QRectF(self.ROW_W + j * cw, 0, cw, self.HEAD_H), Qt.AlignCenter, name)
        for i, name in enumerate(self.rows):
            y = self.HEAD_H + i * self.CELL_H
            p.setPen(QColor(C["ink"]))
            p.drawText(QRectF(0, y, self.ROW_W - 8, self.CELL_H), Qt.AlignRight | Qt.AlignVCenter, name)
            for j, v in enumerate(self.values[i]):
                fill, ink = ramp_color((v - low) / span)
                cell = QRectF(self.ROW_W + j * cw + 1, y + 1, cw - 2, self.CELL_H - 2)
                p.fillRect(cell, QColor(fill))
                p.setPen(QColor(ink))
                p.drawText(cell, Qt.AlignCenter, f"{v:.1f}")

    def mouseMoveEvent(self, event):
        pos = event.position()
        i, j = int((pos.y() - self.HEAD_H) // self.CELL_H), int((pos.x() - self.ROW_W) // self._cell_w())
        if 0 <= i < len(self.rows) and 0 <= j < len(self.cols) and pos.x() >= self.ROW_W:
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{self.rows[i]} into {self.cols[j]}\n{self.values[i][j]:.2f} wounds on average", self)
        else:
            QToolTip.hideText()


# =============================================================================
# a worker thread: signals, where Tk needs a queue polled every 100 ms
# =============================================================================
class Worker(QThread):
    progress = Signal(int)

    def __init__(self, obstacles: Obstacles, outline, reach: float):
        super().__init__()
        self.obstacles, self.outline, self.reach = obstacles, outline, reach

    def run(self):
        for n in range(1, 21):
            cast(self.outline, self.reach, self.obstacles)      # real work, off the window's thread
            self.progress.emit(n * 5)


# =============================================================================
# the window
# =============================================================================
class Window(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setWindowTitle("Command Center 40K — Qt spike")
        layout = ctx.missions.layouts[0]
        self.board = Board(layout)
        import random
        rng = random.Random(40)
        zones = layout.get("deployment_zones", {})
        units = [("attacker", "Boyz", 9.0, 3.5, 18), ("attacker", "Battlewagon", 6.5, 4.0, 36),
                 ("defender", "Intercessors", 5.0, 2.6, 24), ("defender", "Redemptor Dreadnought", 3.5, 3.5, 36)]
        self.tokens = [self.board.add_token(role, name, w, h, reach, zones.get(role, []), rng)
                       for role, name, w, h, reach in units]

        side = QWidget()
        col = QVBoxLayout(side)
        title = QLabel("Engagement Optimizer")
        title.setObjectName("h1")
        col.addWidget(title)
        note = QLabel(f"Layout {layout['id']}  ·  drag a unit, double click to turn it, click it for its line of sight")
        note.setObjectName("muted")
        note.setWordWrap(True)
        col.addWidget(note)

        bar = QHBoxLayout()
        switch = QButtonGroup(self)
        for n, text in enumerate(("Shooting", "Fight")):        # the Auspex's switch: two buttons, one pressed in
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(n == 0)
            switch.addButton(b)
            bar.addWidget(b)
        combo = QComboBox()
        combo.addItems(ctx.missions.dispositions)
        bar.addWidget(combo, 1)
        bar.addWidget(QCheckBox("Cover"))
        run = QPushButton("Run tests")
        run.setProperty("accent", True)
        bar.addWidget(run)
        col.addLayout(bar)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        col.addWidget(self.progress)
        run.clicked.connect(self.run_tests)

        tabs = QTabWidget()
        rows = ["Boyz", "Battlewagon", "Meganobz", "Deff Dread", "Lootas", "Warbikers"]
        cols = ["Intercessors", "Terminators", "Redemptor", "Land Raider"]
        values = [[((i * 7 + j * 13) % 17) / 2 + 0.4 * i for j in range(len(cols))] for i in range(len(rows))]
        tabs.addTab(Heatmap(rows, cols, values), "Matrix")
        rules = QTextBrowser()
        rules.document().setDefaultStyleSheet(f".kwb {{ font-weight: bold; font-size: 9pt; }} h3 {{ color: {C['att']}; }}"
                                              f" .meta {{ color: {C['muted']}; }}")
        rules.setHtml("".join(f"<h3>{s['name']} <span class='meta'>{s['cp_cost']}CP · {s['type']}</span></h3>"
                              f"<p><i>{s['legend']}</i></p><p>{s['description']}</p>"
                              for s in ctx.rules.core_stratagems()[:8]))     # Wahapedia's HTML, as it is
        tabs.addTab(rules, "Stratagems")
        col.addWidget(tabs, 1)

        split = QSplitter()
        split.addWidget(self.board)
        split.addWidget(side)
        split.setSizes([3000, 2000])                    # shares of the width: three fifths to the board
        self.setCentralWidget(split)
        self.tokens[1].setSelected(True)                # the Battlewagon's line of sight, from the start

    def run_tests(self):
        token = self.tokens[1]
        self.worker = Worker(self.board.obstacles, token.outline(), token.reach)
        self.worker.progress.connect(self.progress.setValue)    # delivered on the window's thread
        self.worker.start()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shot", metavar="PNG", help="save a picture of the window there, and exit")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)        # the title bars too (Windows, macOS)
    families = [f for ttf in sorted(config.FONTS_DIR.glob("*.ttf"))
                for f in QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(ttf)))]
    display = DISPLAY_FAMILY if DISPLAY_FAMILY in families else app.font().family()
    app.setStyleSheet(STYLE.format(display=display, **C))
    win = Window(AppContext())
    if not args.shot:
        win.showMaximized()
        raise SystemExit(app.exec())
    win.resize(1600, 900)
    win.show()
    win.run_tests()

    def shoot():
        for dx in range(40):                            # a drag, as the mouse would do it: 40 moves, 40 sights
            win.tokens[1].moveBy(0.25, 0)
        win.worker.wait()
        app.processEvents()
        win.grab().save(args.shot)
        ms = sorted(win.board.sight_ms)
        print(f"display font: {display}   line of sight drawn {len(ms)} times, median {ms[len(ms) // 2]:.1f} ms")
        app.quit()
    QTimer.singleShot(300, shoot)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
