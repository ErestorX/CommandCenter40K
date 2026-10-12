"""The Field Holomap: mission and deployment support. For the two armies' Force Dispositions it shows the
three battlefield layouts of the pairing (right two thirds), the primary mission each player plays
and a compact view of both armies (left third). Ticking a unit puts its base (or the ellipse of the
whole unit) on each map, at a random spot of its side's deployment zone, to be dragged around.

Each layout can be taken off the view (next to the legend). The layouts viewed and the info panel
(legend, options) are placed in the right two thirds so that the boards are as large as they can be
(command_center.deploy.arrange): the panel in a cell next to the boards, in a column on their right, or in a
strip under them."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from command_center.analysis.army_plans import pair_key
from command_center.deploy.arrange import Rect, arrange
from command_center.ui.registry import Selection, register_tool
from command_center.ui.tools.holomap.map_view import DRAWN, OVERLAYS, Legend, UnitMap
from command_center.ui.tools.holomap.score_oracle import ScoreOracle
from command_center.ui.tools.holomap.side_panel import ROLES, SidePanel
from command_center.ui.toolwindow import ToolWindow
from command_center.ui.widgets import Panel, Tick, label

if TYPE_CHECKING:
    from command_center.ui.app import App

GAP = 6                         # between the boards, the info panel and its two parts


class BoardArea(QWidget):
    """Where the boards and the info panel go: it has no layout of its own, the window places them."""

    def __init__(self, win: "HolomapWindow"):
        super().__init__()
        self.win = win

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.win.arrange()


class HolomapWindow(ToolWindow):
    title_text = "Field Holomap"

    def __init__(self, app: "App", selection: Selection):
        super().__init__(app, selection)
        self._built = False
        body = QHBoxLayout(self)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        self.side = SidePanel(self)
        self.board_area = BoardArea(self)                       # the boards and the info panel: placed by arrange
        for part, share in ((self.side, 1), (self.board_area, 2)):
            part.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # a third, two thirds
            body.addWidget(part, share)
        self.maps = [UnitMap() for _ in range(3)]
        for m in self.maps:
            m.setParent(self.board_area)
            m.on_select = self._on_select
        self.selected: tuple[UnitMap, str] | None = None        # the unit token later functions act on
        self.placed: dict[str, object] = {}                     # token key -> roster row on the maps
        plans = self.ctx.army_plans                             # the Engagement Optimizer's army plan, kept live
        self.plan = plans.get(selection.attacker.path, selection.defender.path)
        self._unsubscribe = plans.subscribe(self._on_plan_saved)
        self.oracle: ScoreOracle | None = None                  # the floating score window, when open
        self._arrange_timer = QTimer(self)
        self._arrange_timer.setSingleShot(True)
        self._arrange_timer.timeout.connect(self.arrange)
        self.info_cell = self._build_info()
        self._built = True
        self.refresh()
        self._update_plan_links()

    def _build_info(self) -> QWidget:
        """The info panel, in two parts (arrange stacks them or sets them side by side): the board
        (pairing, measurements, legend, the layouts viewed), and the selected unit's options."""
        cell = QWidget(self.board_area)
        self.info_grid = QGridLayout(cell)
        self.info_grid.setContentsMargins(0, 0, 0, 0)
        self.info_grid.setSpacing(GAP)

        top = self.info_top = Panel()
        col = QVBoxLayout(top)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)
        self.pairing = label("", "h2", wrap=True)
        self.pairing.setFixedWidth(330)
        col.addWidget(self.pairing)
        col.addSpacing(2)
        self.info = label("", "muted", wrap=True)
        self.info.setFixedWidth(330)
        col.addWidget(self.info)
        col.addSpacing(6)
        self.measure = Tick("Show table-setup measurements")
        self.measure.toggled.connect(lambda _on: self._toggle_measurements())
        col.addWidget(self.measure)
        col.addSpacing(6)
        keys = QHBoxLayout()                                    # the legend | the layouts viewed
        keys.setSpacing(18)
        keys.addWidget(Legend())
        view = QVBoxLayout()
        view.setSpacing(2)
        view.addWidget(label("View", "muted"))
        self.shown: list[Tick] = []                             # the layouts being viewed
        for letter in "ABC":
            tick = Tick(f"Layout {letter}")
            tick.setChecked(True)
            tick.toggled.connect(lambda _on: self._toggle_layouts())
            view.addWidget(tick)
            self.shown.append(tick)
        view.addStretch(1)
        keys.addLayout(view)
        keys.addStretch(1)
        col.addLayout(keys)
        col.addStretch(1)

        bottom = self.info_bottom = Panel()
        col = QVBoxLayout(bottom)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(4)
        col.addWidget(label("Selected unit", "muted"))
        self.overlay_ticks: dict[str, Tick] = {}

        def option_row(lead: str, options: list[tuple[str, str]]):
            row = QHBoxLayout()
            row.setSpacing(12)
            if lead:
                row.addWidget(label(lead))
            for name, text in options:
                tick = self.overlay_ticks[name] = Tick(text)
                tick.toggled.connect(lambda _on: self._toggle_overlays())
                row.addWidget(tick)
            row.addStretch(1)
            col.addLayout(row)

        option_row("Show", [("move", "Movement"), ("advance", "Advance"), ("charge", "Charge")])
        option_row("", [("objectives", "Distances to the objectives")])
        option_row("Show", [("plan", "Targets"), ("plan2", "2nd"), ("planall", "all")])
        option_row("Show", [("sight", "Line of Sight"), ("hidden", "Hidden"), ("ground", "Go to Ground")])
        self.plan_note = label("No Engagement Optimizer army plan for these two lists yet: Targets need one.", "muted",
                               wrap=True)
        col.addWidget(self.plan_note)
        col.addStretch(1)
        self._sub_options()
        return cell

    # ---------------------------------------------------------------- the boards viewed, and their place
    def _toggle_layouts(self):
        for m, tick in zip(self.maps, self.shown):
            if not tick.isChecked() and m.selected:             # no selection left on a board out of view
                m._select(None)
        self.arrange()

    def _arrange_later(self):
        """Arrange again once the info panel has its new size (its texts changed)."""
        self._arrange_timer.start(0)

    def arrange(self):
        """Place the boards viewed and the info panel in the space they share, the boards as large as
        that allows."""
        if not self._built:
            return
        area, top, bottom = self.board_area, self.info_top, self.info_bottom
        if area.width() < 10 or area.height() < 10:             # not laid out yet
            return
        m0 = self.maps[0]
        (tw, th), (bw, bh) = ((s.width(), s.height()) for s in (top.sizeHint(), bottom.sizeHint()))
        # what a map takes around its board: frame and margins, title, line under it
        chrome = (16, m0.title.sizeHint().height() + m0.sub.sizeHint().height() + 20)
        shown = [m for m, tick in zip(self.maps, self.shown) if tick.isChecked()]
        a = arrange(len(shown), area.width(), area.height(),
                    tall=(max(tw, bw) + GAP, th + bh + 2 * GAP), wide=(tw + bw + 2 * GAP, max(th, bh) + GAP),
                    chrome=chrome, drawn=DRAWN)               # a map draws its reserves under its board

        def put(w: QWidget, rect: Rect):
            x, y, width, height = rect
            w.setGeometry(x + 3, y + 3, max(1, width - 6), max(1, height - 6))
            w.show()
        for m in self.maps:
            if m not in shown:
                m.hide()
        for m, rect in zip(shown, a.boards):
            put(m, rect)
        grid = self.info_grid                                   # its two parts: side by side, or stacked
        grid.removeWidget(top)
        grid.removeWidget(bottom)
        grid.addWidget(top, 0, 0)
        grid.addWidget(bottom, *((0, 1) if a.wide else (1, 0)))
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1 if a.wide else 0)
        put(self.info_cell, a.info)

    def _sub_options(self):
        """Hidden refines line of sight, Go to Ground refines Hidden, 2nd and all refine Targets: each
        only available while the option it refines is on."""
        on = {name: tick.isChecked() for name, tick in self.overlay_ticks.items()}
        for name, usable in (("hidden", on["sight"]), ("ground", on["sight"] and on["hidden"]),
                             ("plan2", on["plan"]), ("planall", on["plan"])):
            self.overlay_ticks[name].setEnabled(usable)

    def _on_select(self, source: UnitMap, key: str | None):
        """One selection for the whole window: selecting on one map clears the others."""
        self.selected = (source, key) if key else None
        for m in self.maps:
            if m is not source:
                m.set_selected(None)
        self.side.show_selected(key.split(":", 1) if key else None)

    def toggle_unit(self, role: str, row, on: bool):
        """Put a roster row on every map (each at its own random spot in the side's zone), or take it off."""
        key = f"{role}:{row.key}"
        for m in self.maps:
            if on:
                m.add_token(key, role, row.name, row.footprint, row.move, row.ranges, row.bases, row.characters)
            else:
                m.remove_token(key)
        if on:
            self.placed[key] = row
        else:
            self.placed.pop(key, None)
        self._update_plan_links()

    # ---------------------------------------------------------------- the Engagement Optimizer's army plan
    def _on_plan_saved(self, plan):
        if plan.key == pair_key(self.selection.attacker.path, self.selection.defender.path):
            self.plan = plan
            self._update_plan_links()

    def _update_plan_links(self):
        """Attacker -> target pairs of the army plan, between units placed on the maps."""
        links = []
        if self.plan:
            defenders = {k: {u.label or u.name for u in row.units}
                         for k, row in self.placed.items() if k.startswith("defender:")}
            for key, row in self.placed.items():
                if not key.startswith("attacker:"):
                    continue
                entry = self.plan.entry_for(row.units[0].label or row.units[0].name)
                for rank, target in (("primary", entry and entry.primary), ("secondary", entry and entry.secondary)):
                    if target:
                        hit = next((k for k, labels in defenders.items() if target.units[0] in labels), None)
                        if hit:
                            links.append((key, hit, rank))
        for m in self.maps:
            m.set_plan_links(links)
        self.plan_note.setVisible(not self.plan)                # the note only takes room when needed
        self._arrange_later()

    # ---------------------------------------------------------------- Score Oracle
    def open_score_oracle(self) -> ScoreOracle:
        """The floating score window: one per Field Holomap, brought to the front if already open."""
        if self.oracle is None:
            self.oracle = ScoreOracle(self)
            self.oracle.destroyed.connect(self._oracle_closed)
        self.oracle.show()
        self.oracle.raise_()
        self.oracle.activateWindow()
        return self.oracle

    def _oracle_closed(self):
        self.oracle = None

    def closeEvent(self, event):
        self._unsubscribe()
        self._arrange_timer.stop()
        super().closeEvent(event)                               # the Score Oracle is this window's: it closes with it

    def _toggle_overlays(self):
        self._sub_options()
        flags = {name: tick.isChecked() and tick.isEnabled() for name, tick in self.overlay_ticks.items()}
        for m in self.maps:
            m.set_overlays(**flags)

    def _toggle_measurements(self):
        for m in self.maps:
            m.show_measurements = self.measure.isChecked()
            m.draw()

    def refresh(self):
        book = self.ctx.missions
        fd = {role: self.side.disposition(role) for role in ROLES}
        both = all(fd.values())
        for role, other in (("attacker", "defender"), ("defender", "attacker")):
            self.side.show_mission(role, book.primary_mission(fd[role], fd[other]) if both else None)
        if self.oracle is not None:
            self.oracle.refresh()

        if not book.available:
            msg = "No mission data yet: run  python -m command_center fetch"
            layouts = []
        elif not both:
            msg = "Both lists need a Force Disposition (in their Configuration) to show the layouts."
            layouts = []
        else:
            layouts = book.layouts_for(fd["attacker"], fd["defender"])
            msg = "" if layouts else f"No layouts found for {fd['attacker']} vs {fd['defender']}."
        for i, m in enumerate(self.maps):
            m.set_layout(layouts[i] if i < len(layouts) else None, msg if i == 0 else "", self.measure.isChecked())

        if both:
            pairing = (f"{fd['attacker']} (mirror)" if fd["attacker"] == fd["defender"]
                       else f"{fd['attacker']} vs {fd['defender']}")
            self.pairing.setText(pairing)
            self.info.setText(f"{len(layouts)} layouts for this pairing  ·  Event Companion, via rapidingress.com")
        else:
            self.pairing.setText("")
            self.info.setText("")
        self._arrange_later()


@register_tool("holomap", "Field Holomap", "Missions and deployment: the primary missions and the three battlefield "
               "layouts for the two armies' Force Dispositions.", order=30)
def open_holomap(app: "App", selection: Selection) -> HolomapWindow:
    return HolomapWindow(app, selection)
