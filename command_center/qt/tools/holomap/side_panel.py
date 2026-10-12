"""Left third of the Field Holomap: one column per player (attacker left, defender right) with its Force
Disposition and its primary mission, then a compact view of both army lists, whose units can be
ticked to put them on the maps."""
from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from command_center.deploy.roster import RosterRow, roster
from command_center.lists import ArmyList
from command_center.qt.theme import C
from command_center.qt.widgets import Panel, Table, button, label

if TYPE_CHECKING:
    from command_center.qt.tools.holomap.window import HolomapWindow

ROLES = ("attacker", "defender")
COLUMNS = ("attacker", "defender")       # left to right, as everywhere else in the app
ON = "✓"

CARD_STYLE = f"""
.name {{ font-size: 12pt; font-weight: bold; }}
.legend {{ color: {C['muted']}; font-size: 9pt; font-style: italic; }}
.round {{ font-size: 9pt; font-weight: bold; }}
.when {{ color: {C['muted']}; font-size: 9pt; font-weight: normal; }}
.note {{ color: {C['muted']}; font-size: 8pt; }}
.rule {{ font-size: 9pt; }}
p {{ margin-top: 2px; margin-bottom: 2px; }}
"""


def card_html(card: dict) -> str:
    """A primary mission card: its name, what it says, its actions, and its scoring, block by block."""
    e = escape
    out = [f'<p class="name">{e(card["name"].title())}</p>']
    if card.get("legend"):
        out.append(f'<p class="legend">{e(card["legend"])}</p>')
    out += [f'<p class="rule">{e(line)}</p>' for line in card.get("intro", [])]
    for a in card.get("actions", []):
        out.append(f'<p class="round" style="margin-top: 8px;">{e(a.get("name", "").title())} ({e(a.get("type", "").lower())})</p>')
        out += [f'<p class="rule">{e(k.replace("_", " ").capitalize())}: {e(str(v))}</p>'
                for k, v in a.items() if k not in ("name", "type")]
    for block in card.get("scoring", []):
        out.append(f'<p class="round" style="margin-top: 8px;">{e(block.get("round", "").capitalize())} &nbsp;'
                   f'<span class="when">{e(block.get("when", ""))}</span></p>')
        for c in block.get("conditions", []):
            prefix = "or " if c.get("alternative") else "+ " if c.get("additional") else "• "
            scored = " &nbsp;".join(f'<b>{e(v["vp"])}</b>' + (f' <span class="note">{e(" ".join(v["notes"]).lower())}</span>'
                                                               if v.get("notes") else "") for v in c.get("vp", []))
            out.append(f'<p style="margin-left: 8px;">{e(prefix + c.get("text", ""))} &nbsp;{scored}</p>')
    return "".join(out)


class SidePanel(Panel):
    def __init__(self, win: "HolomapWindow"):
        super().__init__()
        self.win = win
        armies = (win.selection.attacker, win.selection.defender)
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)
        top = QHBoxLayout()
        top.addWidget(button("← Command Center", win.back))
        top.addStretch(1)
        top.addWidget(button("Score Oracle", win.open_score_oracle))
        col.addLayout(top)
        col.addSpacing(10)
        col.addWidget(label("Field Holomap", "h2"))
        col.addSpacing(6)

        # ---- one column per player: disposition + primary mission | army 1 | army 2 ----------------
        pw = QSplitter(Qt.Vertical)
        col.addWidget(pw, 1)
        cols = QWidget()
        row = QHBoxLayout(cols)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.dispositions: dict[str, str] = {}            # role -> Force Disposition, as the lists set it
        self.texts: dict[str, QTextBrowser] = {}
        by_role = dict(zip(ROLES, armies))
        for role in COLUMNS:
            row.addWidget(self._player_column(role, by_role[role]), 1)
        pw.addWidget(cols)
        self.trees: dict[str, Table] = {}
        self.rows: dict[str, dict[str, RosterRow]] = {}
        for role, army in zip(ROLES, armies):
            pw.addWidget(self._army_view(role, army))
        pw.setSizes([3000, 2000, 2000])                     # shares of the height

    # ---------------------------------------------------------------- dispositions
    def disposition(self, role: str) -> str:
        return self.dispositions[role]

    def _player_column(self, role: str, army: ArmyList) -> QWidget:
        """Title with the army's Force Disposition opposite (as its list sets it), then the army's name,
        then its primary mission."""
        book = self.win.ctx.missions
        f = QWidget()
        f.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)        # half each
        col = QVBoxLayout(f)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(label(role.upper(), "att" if role == "attacker" else "def"))
        head.addStretch(1)
        fd = book.disposition(army.force_disposition) or ""
        self.dispositions[role] = fd
        badge = ("att-badge" if role == "attacker" else "def-badge") if fd else "muted-badge"
        head.addWidget(label(fd.upper() if fd else "NO FORCE DISPOSITION", badge))
        col.addLayout(head)
        name = army.faction or army.path.stem
        note = "" if fd else "  ·  its list sets none (Configuration: \"Force Disposition: ...\")"
        col.addWidget(label(name + note, "muted", wrap=True))
        text = self.texts[role] = QTextBrowser()
        text.setOpenLinks(False)
        text.document().setDefaultStyleSheet(CARD_STYLE)
        text.document().setDocumentMargin(8)
        text.setStyleSheet(f"QTextBrowser {{ background: {C['field']}; border: none; }}")
        col.addWidget(text, 1)
        return f

    # ---------------------------------------------------------------- missions
    def show_mission(self, role: str, card: dict | None):
        """A player's primary mission card (None: not known yet) in that player's column."""
        self.texts[role].setHtml(card_html(card) if card else
                                 '<p class="legend">Both lists need a Force Disposition to know this mission.</p>')

    # ---------------------------------------------------------------- armies
    def _army_view(self, role: str, army: ArmyList) -> QWidget:
        f = QWidget()
        col = QVBoxLayout(f)
        col.setContentsMargins(0, 6, 0, 0)
        col.setSpacing(0)
        rows = roster(army, self.win.ctx.wd)
        self.rows[role] = {r.key: r for r in rows}
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(role.upper(), "att" if role == "attacker" else "def"))
        head.addWidget(label(f"{army.faction}  ·  {army.points} pts"), 1)
        col.addLayout(head)
        dets = ", ".join(army.detachment_names)
        col.addWidget(label(f"{dets}  ·  {len(rows)} units on the table, {sum(r.models for r in rows)} models"
                            "  ·  click ✓ to put a unit on the maps", "muted", wrap=True))
        col.addSpacing(2)
        tree = self.trees[role] = Table([("on", "✓"), ("unit", "Unit"), ("m", "Models"), ("pts", "Pts")],
                                        [28, -240, 56, 50], rows=3)
        for r in rows:
            tree.add_row(("", r.name, r.models, r.points), key=r.key)
        tree.itemClicked.connect(lambda item, column, role=role: self._on_click(role, item, column))
        col.addWidget(tree, 1)
        return f

    def show_selected(self, role_key: list[str] | None):
        """Highlight the roster row of the selected unit (None: no highlight)."""
        for role, tree in self.trees.items():
            tree.select(role_key[1] if role_key and role_key[0] == role else None)

    def _on_click(self, role: str, item, column: int):
        if column == 0:
            self.toggle(role, item.data(0, Qt.UserRole))

    def toggle(self, role: str, key: str):
        """Put a unit of the roster on the maps, or take it off."""
        tree = self.trees[role]
        on = tree.row(key).text(0) != ON
        tree.set_cell(key, 0, ON if on else "")
        self.win.toggle_unit(role, self.rows[role][key], on)
