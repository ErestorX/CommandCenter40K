"""First window: choose the attacker and defender army lists, then a tool. Tools that need no army
list have their buttons apart, on the left of the others.

A list can be added from here: "Add..." takes the text copied from NewRecruit (the dialog says how to
export it), saves it in the lists folder under a new name, and selects it."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from command_center.config import ATTRIBUTION_SHORT as ATTRIBUTION, LISTS_DIR, PROJECT_ROOT
from command_center.lists import ArmyList, parse_list
from command_center.lists.library import name_problem, save_list, text_problem
from command_center.ui.registry import Selection, Tool, tools
from command_center.ui.screen import screen_height
from command_center.ui.widgets import Panel, button, label, rule

if TYPE_CHECKING:
    from command_center.ui.app import App


class ListPicker(Panel):
    def __init__(self, launcher: "Launcher", app: "App", role: str):
        super().__init__()
        self.launcher, self.app, self.role = launcher, app, role
        self.paths: list[Path] = []
        self.army: ArmyList | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(0)
        col.addWidget(label(role.upper(), "att" if role == "attacker" else "def"))
        col.addWidget(label("Army list", "h2"))
        col.addSpacing(6)
        self.listbox = QListWidget()
        self.listbox.itemSelectionChanged.connect(self._on_select)
        col.addWidget(self.listbox, 1)
        col.addSpacing(6)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        for text, command in (("Browse...", self.browse), ("Refresh", self.refresh), ("Add...", self.add)):
            btns.addWidget(button(text, command))
        btns.addStretch(1)
        col.addLayout(btns)
        col.addSpacing(8)
        self.preview = label("No list selected", "muted", wrap=True)
        col.addWidget(self.preview)
        self.refresh()

    def _fill(self):
        """The list as `paths` has it, nothing selected; no one is told."""
        self.listbox.blockSignals(True)
        self.listbox.clear()
        self.listbox.addItems([p.stem for p in self.paths])
        self.listbox.blockSignals(False)

    def refresh(self):
        keep = self.selected_path
        found = sorted(LISTS_DIR.glob("*.txt")) if LISTS_DIR.exists() else []
        self.paths = found + [p for p in self.paths if p not in found]
        self._fill()
        if keep in self.paths:
            self.select(keep)

    @property
    def selected_path(self) -> Path | None:
        row = self.listbox.currentRow() if self.listbox.selectedItems() else -1
        return self.paths[row] if 0 <= row < len(self.paths) else None

    def select(self, path: Path | None):
        if path is not None and path not in self.paths:
            self.paths.append(path)
            self._fill()
        self.listbox.blockSignals(True)
        self.listbox.clearSelection()
        if path is not None:
            self.listbox.setCurrentRow(self.paths.index(path))
        self.listbox.blockSignals(False)
        self._on_select()

    def browse(self):
        f, _ = QFileDialog.getOpenFileName(self, f"Choose the {self.role} list",
                                           str(LISTS_DIR if LISTS_DIR.exists() else PROJECT_ROOT),
                                           "NewRecruit text export (*.txt);;All files (*)")
        if f:
            self.select(Path(f))

    def add(self):
        """Paste a list's text, name it: it is saved with the others and selected here."""
        AddListDialog(self, self.app, self.role, self._added).open()

    def _added(self, path: Path):
        for picker in (self.launcher.att, self.launcher.dfn):   # both sides list it; this one selects it
            picker.refresh()
        self.select(path)

    def _on_select(self):
        p = self.selected_path
        self.army = None
        if p:
            try:
                self.army = parse_list(p, self.app.ctx.wd)
            except Exception as e:  # noqa: BLE001 - show any parse problem to the user
                self.preview.setText(f"Could not read {p.name}:\n{e}")
                self.launcher.update_buttons()
                return
        self._show_preview()
        self.launcher.update_buttons()

    def _show_preview(self):
        a = self.army
        if not a:
            self.preview.setText("No list selected")
            return
        lines = [f"{a.faction}  ·  {a.points} pts  ·  {len(a.units)} units"]
        if a.detachment:
            lines.append(f"Detachment: {a.detachment}")
        if not a.faction_id:
            lines.append("⚠ Faction not recognised, units matched across all factions")
        if a.unmatched_units:
            lines.append("⚠ No datasheet for: " + ", ".join(a.unmatched_units))
        self.preview.setText("\n".join(lines))


HOW_TO_EXPORT = (
    "In the NewRecruit app, when the list is finished:",
    "1.  Click Export, then Text export",
    "2.  Export Format: NR",
    "3.  Tick all the Content options",
    "4.  Copy to clipboard, then paste it below",
)


class AddListDialog(QDialog):
    """Paste an army list's text and give it a new name: it is saved next to the other lists.
    on_saved(path) is called once it is. To show with open(): the launcher waits for it."""

    def __init__(self, parent: QWidget, app: "App", role: str, on_saved):
        super().__init__(parent)
        self.app, self.on_saved = app, on_saved
        self.setWindowTitle("Command Center 40K — add an army list")
        self.setMinimumWidth(560)
        screen_height(self, 720, app)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        body = Panel()
        outer.addWidget(body)
        col = QVBoxLayout(body)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(0)
        col.addWidget(label(f"Add an army list ({role})", "h2"))
        col.addSpacing(8)

        how = Panel("cell")                                     # how to get the right text
        lines = QVBoxLayout(how)
        lines.setContentsMargins(12, 8, 12, 8)
        lines.setSpacing(2)
        for i, line in enumerate(HOW_TO_EXPORT):
            lines.addWidget(label(line, None if i else "muted"))
        col.addWidget(how)
        col.addSpacing(10)

        self.text = QPlainTextEdit()
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))      # a list's text, as it was typed
        col.addWidget(self.text, 1)
        col.addSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Name of the list (a new one)"))
        self.name = QLineEdit()
        self.name.setFixedWidth(300)
        self.name.returnPressed.connect(self.save)
        row.addWidget(self.name)
        row.addWidget(label(f"saved in {LISTS_DIR}", "muted"), 1)
        col.addLayout(row)
        col.addSpacing(6)
        self.problem = label("", "warn", wrap=True)
        col.addWidget(self.problem)
        col.addSpacing(8)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(self._plain(button("Paste", self.paste)))
        btns.addStretch(1)
        btns.addWidget(self._plain(button("Cancel", self.reject)))
        btns.addWidget(self._plain(button("Save", self.save, "accent")))
        col.addLayout(btns)
        self.text.setFocus()

    @staticmethod
    def _plain(b: QPushButton) -> QPushButton:
        """Return in the name's field saves; nowhere else does it press a button."""
        b.setAutoDefault(False)
        return b

    def paste(self):
        """Replace the text with the clipboard's."""
        clip = QGuiApplication.clipboard().text()
        if not clip:                                            # nothing on the clipboard, or not text
            self.problem.setText("There is no text on the clipboard.")
            return
        self.text.setPlainText(clip)
        self.problem.setText("")

    def save(self):
        text, name = self.text.toPlainText(), self.name.text()
        problem = text_problem(text, self.app.ctx.wd) or name_problem(name, LISTS_DIR)
        if problem:
            self.problem.setText(problem)
            return
        try:
            path = save_list(text, name, LISTS_DIR)
        except (OSError, ValueError) as e:
            self.problem.setText(f"The list could not be saved: {e}")
            return
        self.accept()
        self.on_saved(path)


class Launcher(QWidget):
    """Pick the attacker and defender lists, then open any registered tool."""

    def __init__(self, app: "App"):
        super().__init__()
        self.app = app
        self.tool_buttons: list[QPushButton] = []          # those that need both lists chosen
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 18, 18, 18)
        grid.setSpacing(0)
        grid.addWidget(label("Command Center 40K — choose the armies", "h1"), 0, 0, 1, 3)
        sub = label(f"Wahapedia data: last update {app.ctx.wd.last_update or 'unknown'}   ·   "
                    f"lists folder: {LISTS_DIR}", "muted")
        sub.setContentsMargins(0, 2, 0, 12)
        grid.addWidget(sub, 1, 0, 1, 3)
        self.att = ListPicker(self, app, "attacker")
        self.dfn = ListPicker(self, app, "defender")
        grid.addWidget(self.att, 2, 0)
        swap = button("⇄", self.swap)
        swap.setFixedWidth(52)
        mid = QVBoxLayout()
        mid.setContentsMargins(10, 10, 10, 10)
        mid.addWidget(swap)
        grid.addLayout(mid, 2, 1)
        grid.addWidget(self.dfn, 2, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(2, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 14, 0, 0)
        bottom.setSpacing(8)
        bottom.addStretch(1)
        apart = [t for t in tools() if not t.needs_armies]
        needing = [t for t in tools() if t.needs_armies]
        for tool in apart:                      # on their own, left of a rule
            bottom.addWidget(self._tool_button(tool))
        if apart and needing:
            bottom.addSpacing(12)
            bottom.addWidget(rule())
            bottom.addSpacing(4)
        for tool in needing:
            b = self._tool_button(tool)
            bottom.addWidget(b)
            self.tool_buttons.append(b)
        grid.addLayout(bottom, 3, 0, 1, 3)
        # on its own line: next to the buttons it would be cut short on a narrow window
        credit = label(ATTRIBUTION, "muted")
        credit.setContentsMargins(0, 8, 0, 0)
        grid.addWidget(credit, 4, 0, 1, 3)
        paths = self.att.paths
        if len(paths) >= 2:
            self.att.select(paths[0])
            self.dfn.select(paths[1])
        self.update_buttons()

    def _tool_button(self, tool: Tool) -> QPushButton:
        return button(f"{tool.title}  →", lambda: self.open_tool(tool), "accent", tool.description)

    @property
    def selection(self) -> Selection | None:
        if self.att.army and self.dfn.army:
            return Selection(self.att.army, self.dfn.army)
        return None

    def update_buttons(self):
        ok = bool(getattr(self, "att", None) and getattr(self, "dfn", None) and self.att.army and self.dfn.army)
        for b in self.tool_buttons:
            b.setEnabled(ok)

    def swap(self):
        a, d = self.att.selected_path, self.dfn.selected_path
        self.att.select(d)
        self.dfn.select(a)

    def open_tool(self, tool: Tool):
        sel = self.selection
        if sel or not tool.needs_armies:
            self.app.open_tool(tool.key, sel)
