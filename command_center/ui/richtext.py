"""Read-only rich text for the UI: Wahapedia HTML rendered into a tkinter Text window,
plus card grids (used for stratagems). Reusable by any tool that needs to show rules text."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from html.parser import HTMLParser
from tkinter import ttk

import re

from command_center.util import clean_glyphs
from command_center.ui.theme import C, dark_title_bar

# =============================================================================
# HTML -> tagged text
# =============================================================================
class _Render(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "ul", "ol", "table", "tbody"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[tuple[str, tuple[str, ...]]] = []
        self.stack: list[tuple[str, str | None]] = []
        self.depth = 0
        self.first_cell = True

    def _last(self) -> str:
        for text, _ in reversed(self.out):
            if text:
                return text[-1]
        return "\n"

    def _nl(self, soft=True):
        if not soft or self._last() != "\n":
            self.out.append(("\n", ()))

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "br":
            self._nl(soft=False)
            return
        if tag == "img":
            return
        if tag in ("p", "div", "tr", "table"):
            self._nl()
        if tag in ("ul", "ol"):
            self.depth += 1
            self._nl()
        if tag == "li":
            self._nl()
            self.out.append(("   " * self.depth + "• ", ("bullet",)))
        if tag == "tr":
            self.first_cell = True
        if tag in ("td", "th"):
            if not self.first_cell:
                self.out.append(("   |   ", ("muted",)))
            self.first_cell = False
        style = None
        if tag in ("b", "strong", "th"):
            style = "bold"
        elif tag in ("i", "em"):
            style = "italic"
        elif tag == "u":
            style = "underline"
        elif "kwb" in cls:
            style = "kw"
        elif "hi_custom" in cls or "impact18" in cls or "abName" == cls:
            style = "h3"
        elif "ShowFluff" in cls or "legend" in cls:
            style = "italic"
        self.stack.append((tag, style))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ("ul", "ol"):
            self.depth = max(0, self.depth - 1)
        if tag in self.BLOCK or tag in ("h1", "h2", "h3"):
            self._nl()

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data)
        if not text.strip() and self._last() == "\n":
            return
        if self._last() == "\n":
            text = text.lstrip()
        tags = tuple(s for _, s in self.stack if s) + (("indent",) if self.depth else ())
        self.out.append((text, tags))


clean = clean_glyphs


def render_html(html_text: str) -> list[tuple[str, tuple[str, ...]]]:
    r = _Render()
    r.feed(clean(html_text))
    r.close()
    # collapse runs of blank lines
    out, blank = [], 0
    for text, tags in r.out:
        if text == "\n":
            blank += 1
            if blank > 2:
                continue
        else:
            blank = 0
        out.append((text, tags))
    while out and out[-1][0] == "\n":
        out.pop()
    return out


# =============================================================================
# window
# =============================================================================
CARD = {"head": "#4a1715", "sub": "#1f4a73", "border": C["line"], "body": C["field"], "legend": C["grid"]}


def _style_text(t: tk.Text, fam: str) -> None:
    t.tag_configure("h1", font=(fam, 16, "bold"), spacing1=6, spacing3=6)
    t.tag_configure("h2", font=(fam, 13, "bold"), foreground=C["att"], spacing1=14, spacing3=4)
    t.tag_configure("h3", font=(fam, 11, "bold"), spacing1=8, spacing3=2)
    t.tag_configure("meta", font=(fam, 9), foreground=C["muted"], spacing3=4)
    t.tag_configure("bold", font=(fam, 10, "bold"))
    t.tag_configure("italic", font=(fam, 10, "italic"), foreground="#c4c1bb")
    t.tag_configure("underline", underline=True)
    t.tag_configure("kw", font=(fam, 9, "bold"))
    t.tag_configure("muted", foreground=C["muted"])
    t.tag_configure("bullet", foreground=C["att"])
    t.tag_configure("indent", lmargin1=18, lmargin2=34)
    t.tag_configure("rule", foreground=C["line"])
    t.tag_configure("found", background="#7a6410", foreground="white")


def _display_lines(t: tk.Text) -> int:
    n = t.count("1.0", "end", "displaylines")
    if isinstance(n, tuple):
        n = n[0]
    return max(1, int(n or 1))


class RichTextWindow(tk.Toplevel):
    """Scrollable, read-only rich text with headings, rendered HTML and card grids.

    Build content with h1/h2/h3/meta/html/cards, then call done()."""

    def __init__(self, master, title: str, width=760, height=820):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.configure(bg=C["panel"])
        dark_title_bar(self)
        bar = ttk.Frame(self, padding=(10, 8, 10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Find").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=28)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.find())
        ttk.Button(bar, text="Next", command=self.find).pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        fam = tkfont.nametofont("TkDefaultFont").actual("family")
        self.text = tk.Text(body, wrap="word", padx=18, pady=12, borderwidth=0, highlightthickness=0,
                            bg=C["panel"], fg=C["ink"], font=(fam, 10), spacing1=1, spacing3=2,
                            cursor="arrow")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.fam = fam
        _style_text(self.text, fam)
        self._last_find = "1.0"
        self._card_grids: list[tuple[tk.Frame, list[tk.Text]]] = []
        self._card_labels: dict[tk.Frame, list[tuple[tk.Label, int]]] = {}
        self._cards_job = None
        self.text.bind("<Configure>", lambda e: self._schedule_cards())

    # ---- writing helpers ----
    def h1(self, s):
        self.text.insert("end", s + "\n", ("h1",))

    def h2(self, s):
        self.text.insert("end", s + "\n", ("h2",))

    def h3(self, s, meta: str = ""):
        self.text.insert("end", s, ("h3",))
        if meta:
            self.text.insert("end", "   " + meta, ("meta",))
        self.text.insert("end", "\n")

    def meta(self, s):
        self.text.insert("end", s + "\n", ("meta",))

    def html(self, html_text: str):
        for text, tags in render_html(html_text):
            self.text.insert("end", text, tags)
        self.text.insert("end", "\n")

    def gap(self):
        self.text.insert("end", "\n")

    def cards(self, stratagems: list[dict], per_row: int = 3):
        """Stratagems as cards, `per_row` per line; cards in a row share its height."""
        if not stratagems:
            return
        grid = tk.Frame(self.text, bg=C["panel"])
        texts = []
        self._card_labels[grid] = []
        for c in range(per_row):
            grid.columnconfigure(c, weight=1, uniform="card")
        for i, st in enumerate(stratagems):
            card, body = self._card(grid, st)
            card.grid(row=i // per_row, column=i % per_row, sticky="nsew", padx=5, pady=5)
            texts.append(body)
        self.text.window_create("end", window=grid)
        self.text.insert("end", "\n")
        self._card_grids.append((grid, texts))
        self._schedule_cards()

    def _card(self, parent, st: dict):
        fam = self.fam
        card = tk.Frame(parent, bg=CARD["body"], highlightthickness=1, highlightbackground=CARD["border"])
        head = tk.Frame(card, bg=CARD["head"])
        head.pack(fill="x")
        tk.Label(head, text=f"{st.get('cp_cost', '?')}CP", bg=CARD["head"], fg="white",
                 font=(fam, 12, "bold"), padx=8, pady=4).pack(side="right", anchor="n")
        name = tk.Label(head, text=clean(st.get("name", "")).upper(), bg=CARD["head"], fg="white", anchor="w",
                        justify="left", font=(fam, 11, "bold"), padx=8, pady=4)
        name.pack(side="left", fill="x", expand=True)
        self._card_labels[parent].append((name, 80))
        if st.get("type"):
            sub = tk.Label(card, text=clean(st["type"]).upper(), bg=CARD["sub"], fg="white", anchor="w", justify="left",
                           font=(fam, 8, "bold"), padx=8, pady=3)
            sub.pack(fill="x")
            self._card_labels[parent].append((sub, 24))
        body = tk.Text(card, wrap="word", width=1, height=4, padx=8, pady=6, borderwidth=0, highlightthickness=0,
                       bg=CARD["body"], fg=C["ink"], font=(fam, 10), spacing1=1, spacing3=2, cursor="arrow")
        _style_text(body, fam)
        body.tag_configure("legend", font=(fam, 9, "italic"), foreground="#c4c1bb", background=CARD["legend"],
                           spacing3=6)
        if st.get("legend"):
            body.insert("end", clean(st["legend"]).strip() + "\n", ("legend",))
        for text, tags in render_html(st.get("description", "")):
            body.insert("end", text, tags)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True)
        foot = "  ·  ".join(x for x in (st.get("turn"), st.get("phase")) if x)
        if foot:
            tk.Label(card, text=foot, bg=CARD["body"], fg=C["muted"], font=(fam, 8), anchor="w",
                     padx=8, pady=3).pack(fill="x", side="bottom")
        for w in (card, head, name, body):
            self._forward_wheel(w)
        return card, body

    def _forward_wheel(self, w):
        """Scrolling over a card scrolls the whole window, not the card."""
        w.bind("<MouseWheel>", lambda e: (self.text.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1),
                                                                  "units"), "break")[1])
        w.bind("<Button-4>", lambda e: (self.text.yview_scroll(-3, "units"), "break")[1])
        w.bind("<Button-5>", lambda e: (self.text.yview_scroll(3, "units"), "break")[1])

    def _schedule_cards(self):
        if self._cards_job:
            self.after_cancel(self._cards_job)
        self._cards_job = self.after(60, self._layout_cards)

    def _layout_cards(self):
        """Fit card grids to the window width, then size each card body to its text."""
        self._cards_job = None
        if not self._card_grids or not self.winfo_exists():
            return
        width = self.text.winfo_width() - 2 * int(self.text.cget("padx")) - 8
        if width < 200:
            return
        for grid, texts in self._card_grids:
            cols = int(grid.grid_size()[0]) or 1
            col_w = (width - 10 * cols) // cols
            for c in range(cols):
                grid.columnconfigure(c, minsize=col_w)
            for label, reserve in self._card_labels.get(grid, []):
                label.configure(wraplength=max(60, col_w - reserve))
        self.update_idletasks()
        for _, texts in self._card_grids:
            for t in texts:
                t.configure(height=_display_lines(t))

    def done(self):
        self.text.configure(state="disabled")

    def find(self):
        q = self.q.get().strip()
        t = self.text
        t.tag_remove("found", "1.0", "end")
        if not q:
            return
        pos = t.search(q, self._last_find, nocase=True, stopindex="end") or t.search(q, "1.0", nocase=True,
                                                                                      stopindex="end")
        if pos:
            end = f"{pos}+{len(q)}c"
            t.tag_add("found", pos, end)
            t.see(pos)
            self._last_find = end
        # highlight matches inside stratagem cards too
        for _, texts in self._card_grids:
            for ct in texts:
                ct.tag_remove("found", "1.0", "end")
                start = "1.0"
                while True:
                    hit = ct.search(q, start, nocase=True, stopindex="end")
                    if not hit:
                        break
                    start = f"{hit}+{len(q)}c"
                    ct.tag_add("found", hit, start)


RulesWindow = RichTextWindow   # backwards-compatible name
