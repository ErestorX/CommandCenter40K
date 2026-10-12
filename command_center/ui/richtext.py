"""Read-only rich text for the UI: a window showing headings, Wahapedia's HTML and card grids (used for
stratagems). Reusable by any tool that needs to show rules text.

The window holds one document. Wahapedia's HTML goes into it nearly as it is: Qt lays out its lists and
tables. What is taken out first (prepare) is what was meant for Wahapedia's own pages: images, links,
and the colours and sizes written on its tags, which were chosen for a light page."""
from __future__ import annotations

import re
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QTextBrowser, QTextEdit, QVBoxLayout, QWidget

from command_center.ui.screen import screen_height
from command_center.ui.theme import C
from command_center.ui.widgets import button, label
from command_center.util import clean_glyphs

CARD = {"head": "#4a1715", "sub": "#1f4a73", "border": C["line"], "body": C["field"], "legend": C["grid"]}
FOUND = ("#7a6410", "white")                # a match of the search: its background, its ink
SOFT = "#c4c1bb"                            # italics: a little under the text's ink

STYLE = f"""
body {{ color: {C['ink']}; font-size: 10pt; }}
h1 {{ font-size: 16pt; font-weight: bold; margin-top: 6px; margin-bottom: 6px; }}
h2 {{ font-size: 13pt; font-weight: bold; color: {C['att']}; margin-top: 16px; margin-bottom: 4px; }}
h3, h4 {{ font-size: 11pt; font-weight: bold; margin-top: 10px; margin-bottom: 2px; }}
p {{ margin-top: 2px; margin-bottom: 4px; }}
ul, ol {{ margin-top: 2px; margin-bottom: 2px; }}
i {{ color: {SOFT}; }}
td {{ padding: 2px 4px; }}
.meta {{ font-size: 9pt; font-weight: normal; color: {C['muted']}; }}
.kwb, .kwbu, .kwbo, .kwbOne {{ font-size: 9pt; font-weight: bold; }}
.impact18, .hi_custom, .abName {{ font-size: 11pt; font-weight: bold; }}
.ShowFluff, .legend2, .abLegend {{ font-style: italic; color: {SOFT}; }}
.card-name {{ font-size: 11pt; font-weight: bold; color: white; }}
.card-cp {{ font-size: 12pt; font-weight: bold; color: white; }}
.card-type {{ font-size: 8pt; font-weight: bold; color: white; }}
.card-legend {{ font-size: 9pt; font-style: italic; color: {SOFT}; }}
.card-foot {{ font-size: 8pt; color: {C['muted']}; }}
"""

_IMAGE = re.compile(r"<img\b[^>]*>", re.I)
_LINK = re.compile(r"</?a\b[^>]*>", re.I)
_STYLED = re.compile(r"""\s(?:style|width|height|max-width|bgcolor|bordercolor|cellpadding|cellspacing)\s*=\s*"""
                     r"""(?:"[^"]*"+|'[^']*'+|[^\s>]+)""", re.I)
_BREAK = r"(?:<br\s*/?>\s*)"
_BLOCK = r"(?:ul|ol|table)\b"                # what has margins of its own


def _table(tag: re.Match) -> str:
    """A table's opening tag: its lines in the theme's colour. One that Wahapedia only wraps another in
    (border="0") stays without lines."""
    lined = not re.search(r"""\bborder\s*=\s*["']?0""", tag.group(0), re.I)
    return (f'<table border="{int(lined)}" cellspacing="0" cellpadding="4" '
            f'style="border-collapse: collapse; border-color: {C["line"]};">')


def prepare(html_text: str) -> str:
    """Wahapedia's HTML, ready for the window's document: no images, no links, no colours or sizes of
    its own (the document's are used), tables with thin lines, no empty lines around lists and tables
    (they have their own margins) and never more than one between two paragraphs."""
    text = _LINK.sub("", _IMAGE.sub("", clean_glyphs(html_text or "")))
    text = re.sub(r"<table\b[^>]*>", _table, text, flags=re.I)
    text = re.sub(r"<(?!table\b)[a-zA-Z][^>]*>", lambda tag: _STYLED.sub("", tag.group(0)), text)
    text = re.sub(rf"{_BREAK}+(?=<{_BLOCK}|<div\b[^>]*>\s*<table\b)", "", text, flags=re.I)
    text = re.sub(rf"(</{_BLOCK}[^>]*>(?:\s*</div>)?)\s*{_BREAK}+", r"\1", text, flags=re.I)
    return re.sub(rf"{_BREAK}{{3,}}", "<br><br>", text, flags=re.I)


class RichTextWindow(QWidget):
    """Scrollable, read-only rich text with headings, rendered HTML and card grids.

    Build content with h1/h2/h3/meta/line/html/cards, then call done(): the window is shown. As tall as
    the screen."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 760):
        super().__init__(parent, Qt.Window)             # a window of its own, kept above the one it was opened from
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose)
        screen_height(self, width, parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 8, 10, 6)
        bar.setSpacing(6)
        bar.addWidget(label("Find"))
        self.q = QLineEdit()
        self.q.setFixedWidth(240)
        self.q.returnPressed.connect(self.find)
        bar.addWidget(self.q)
        bar.addWidget(button("Next", self.find))
        bar.addStretch(1)
        bar.addWidget(button("Close", self.close))
        col.addLayout(bar)
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.setStyleSheet(f"QTextBrowser {{ background: {C['panel']}; border: none; }}")
        self.text.document().setDefaultStyleSheet(STYLE)
        self.text.document().setDocumentMargin(16)
        col.addWidget(self.text, 1)
        self.parts: list[str] = []

    # ---- writing helpers ----
    def h1(self, s):
        self.parts.append(f"<h1>{escape(s)}</h1>")

    def h2(self, s):
        self.parts.append(f"<h2>{escape(s)}</h2>")

    def h3(self, s, meta: str = ""):
        tail = f' &nbsp; <span class="meta">{escape(meta)}</span>' if meta else ""
        self.parts.append(f"<h3>{escape(s)}{tail}</h3>")

    def meta(self, s):
        self.parts.append(f'<p class="meta">{escape(s)}</p>')

    def line(self, name: str, text: str, keywords: bool = False):
        """A line of plain text after its name in bold: "Core: Deep Strike, Scouts"."""
        value = f'<span class="kwb">{escape(text)}</span>' if keywords else escape(text)
        self.parts.append(f"<p><b>{escape(name)}</b> {value}</p>")

    def html(self, html_text: str):
        self.parts.append(f"<div>{prepare(html_text)}</div>")

    def gap(self):
        self.parts.append("<p>&nbsp;</p>")

    def cards(self, stratagems: list[dict], per_row: int = 3):
        """Stratagems as cards, `per_row` per line; cards in a row share its height."""
        if not stratagems:
            return
        share = 100 // per_row
        rows = []
        for start in range(0, len(stratagems), per_row):
            cells = [f'<td width="{share}%" bgcolor="{CARD["body"]}" style="border: 1px solid {CARD["border"]}; padding: 0;">'
                     f"{self._card(st)}</td>" for st in stratagems[start:start + per_row]]
            cells += [f'<td width="{share}%"></td>'] * (per_row - len(cells))
            rows.append(f"<tr>{''.join(cells)}</tr>")
        self.parts.append(f'<table width="100%" cellspacing="10" cellpadding="0">{"".join(rows)}</table>')

    @staticmethod
    def _card(st: dict) -> str:
        def row(content: str, color: str = "", span: int = 2) -> str:
            back = f' bgcolor="{color}"' if color else ""
            return f'<tr><td colspan="{span}"{back}>{content}</td></tr>'
        name = escape(clean_glyphs(st.get("name", "")).upper())
        rows = [f'<tr><td bgcolor="{CARD["head"]}"><span class="card-name">{name}</span></td>'
                f'<td bgcolor="{CARD["head"]}" align="right"><span class="card-cp">{escape(str(st.get("cp_cost", "?")))}CP'
                "</span></td></tr>"]
        if st.get("type"):
            rows.append(row(f'<span class="card-type">{escape(clean_glyphs(st["type"]).upper())}</span>', CARD["sub"]))
        if st.get("legend"):
            rows.append(row(f'<span class="card-legend">{escape(clean_glyphs(st["legend"]).strip())}</span>', CARD["legend"]))
        rows.append(row(prepare(st.get("description", ""))))
        foot = "  ·  ".join(x for x in (st.get("turn"), st.get("phase")) if x)
        if foot:
            rows.append(row(f'<span class="card-foot">{escape(clean_glyphs(foot))}</span>'))
        return f'<table width="100%" cellspacing="0" cellpadding="6">{"".join(rows)}</table>'

    def done(self):
        """The content is complete: lay it out and show the window."""
        self.text.setHtml("".join(self.parts))
        self.show()

    def find(self):
        """Mark every match of the search, cards included, and go to the next one (the first again after the last)."""
        q = self.q.text().strip()
        doc, marks = self.text.document(), []
        cursor = doc.find(q) if q else QTextCursor()
        while not cursor.isNull():
            mark = QTextEdit.ExtraSelection()
            mark.cursor = cursor
            look = QTextCharFormat()
            look.setBackground(QColor(FOUND[0]))
            look.setForeground(QColor(FOUND[1]))
            mark.format = look
            marks.append(mark)
            cursor = doc.find(q, cursor)
        self.text.setExtraSelections(marks)
        if marks and not self.text.find(q):
            self.text.moveCursor(QTextCursor.Start)
            self.text.find(q)


RulesWindow = RichTextWindow   # backwards-compatible name
