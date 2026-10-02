"""Canvas charts for tkinter: a heatmap and a horizontal bar chart with whiskers, both with hover
tooltips and click callbacks. Colours follow one rule each: magnitude = one blue ramp, identity =
fixed categorical slots, text = ink colours (never the series colour)."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Callable

from command_center.ui.theme import C, font_family

INK = C["ink"]
INK_2 = C["muted"]
INK_3 = C["dim"]
GRID = C["grid"]
SURFACE = C["panel"]
# sequential blue ramp, light -> dark (steps 100 ... 700)
RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5",
        "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"]       # low (dark) to high (light)
# categorical slots, fixed order (slot 1 blue, slot 2 orange, ...)
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
MISSING = C["field"]


def ramp_color(t: float) -> tuple[str, str]:
    """Fill for a 0..1 magnitude and a readable text ink for it."""
    t = min(1.0, max(0.0, t))
    i = round(t * (len(RAMP) - 1))
    return RAMP[i], ("white" if i <= 6 else "#0b0b0b")


class _Tip:
    """Tooltip drawn on the canvas itself, kept inside the visible area."""

    def __init__(self, canvas: tk.Canvas):
        self.cv = canvas
        self.items: list[int] = []

    def show(self, x: float, y: float, lines: list[str]):
        self.hide()
        if not lines:
            return
        fam = font_family()
        cx, cy = self.cv.canvasx(x), self.cv.canvasy(y)
        t = self.cv.create_text(cx + 14, cy + 14, text="\n".join(lines), anchor="nw", fill="white",
                                font=(fam, 9), justify="left")
        x0, y0, x1, y1 = self.cv.bbox(t)
        vw = self.cv.winfo_width()
        dx = min(0, self.cv.canvasx(vw) - 6 - (x1 + 6))          # keep inside on the right
        vis_bottom = self.cv.canvasy(self.cv.winfo_height())
        dy = min(0, vis_bottom - 6 - (y1 + 6))
        if dy < 0:
            dy = min(dy, (cy - 14) - (y1 + 6) - (cy + 14 - y0))  # flip above the cursor
        self.cv.move(t, dx, dy)
        x0, y0, x1, y1 = self.cv.bbox(t)
        r = self.cv.create_rectangle(x0 - 6, y0 - 4, x1 + 6, y1 + 4, fill=C["raised"], outline=C["line"])
        self.cv.tag_raise(t, r)
        self.items = [r, t]

    def hide(self):
        for i in self.items:
            self.cv.delete(i)
        self.items = []


# =============================================================================
# heatmap
# =============================================================================
class Heatmap(ttk.Frame):
    """rows x cols grid of values on the blue ramp. Scrolls when it doesn't fit."""

    def __init__(self, master, on_click: Callable[[int, int], None] | None = None,
                 on_right_click: Callable[[int, int], None] | None = None):
        super().__init__(master, style="Flat.TFrame")
        self.cv = tk.Canvas(self, bg=SURFACE, highlightthickness=0)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.cv.xview)
        self.cv.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.cv.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tip = _Tip(self.cv)
        self.on_click, self.on_right_click = on_click, on_right_click
        self.rows: list[str] = []
        self.cols: list[str] = []
        self.values: list[list[float | None]] = []
        self.tips: list[list[list[str]]] = []
        self.fmt: Callable[[float], str] = lambda v: f"{v:.1f}"
        self.selected: tuple[int, int] | None = None
        self._geom = None
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.cv.bind("<Button-1>", lambda e: self._click(e, self.on_click))
        self.cv.bind("<Button-3>", lambda e: self._click(e, self.on_right_click))
        self.cv.bind("<Button-2>", lambda e: self._click(e, self.on_right_click))     # macOS right button

    def set_data(self, rows, cols, values, tips, fmt=None, caption: str = ""):
        self.rows, self.cols, self.values, self.tips = rows, cols, values, tips
        if fmt:
            self.fmt = fmt
        self.caption = caption
        if self.selected and (self.selected[0] >= len(rows) or self.selected[1] >= len(cols)):
            self.selected = None
        self.draw()

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.tip.items = []
        fam = font_family()
        if not self.rows or not self.cols:
            cv.create_text(20, 20, text="Nothing to show: all tests are filtered out or hidden.",
                           anchor="nw", fill=INK_2, font=(fam, 10))
            cv.configure(scrollregion=(0, 0, 10, 10))
            return
        W = max(cv.winfo_width(), 300)
        row_w = min(260, max(140, int(W * 0.24)))
        head_h = 64
        cw = max(64, min(130, (W - row_w - 20) // max(1, len(self.cols))))
        ch = 30
        self._geom = (row_w, head_h, cw, ch)
        vals = [v for r in self.values for v in r if v is not None]
        vmin, vmax = (min(vals), max(vals)) if vals else (0.0, 1.0)
        span = (vmax - vmin) or 1.0
        for j, c in enumerate(self.cols):
            x = row_w + j * cw + cw / 2
            cv.create_text(x, head_h - 6, text=c, anchor="s", width=cw - 6, justify="center",
                           fill=INK, font=(fam, 9))
        for i, r in enumerate(self.rows):
            y = head_h + i * ch
            cv.create_text(row_w - 8, y + ch / 2, text=r, anchor="e", width=row_w - 12, fill=INK, font=(fam, 9))
            for j in range(len(self.cols)):
                v = self.values[i][j]
                x = row_w + j * cw
                if v is None:
                    fill, ink, txt = MISSING, INK_3, "–"
                else:
                    fill, ink = ramp_color((v - vmin) / span)
                    txt = self.fmt(v)
                cv.create_rectangle(x + 1, y + 1, x + cw - 1, y + ch - 1, fill=fill, outline="")
                cv.create_text(x + cw / 2, y + ch / 2, text=txt, fill=ink, font=(fam, 9, "bold"))
        if self.selected:
            i, j = self.selected
            x, y = row_w + j * cw, head_h + i * ch
            cv.create_rectangle(x, y, x + cw, y + ch, outline=INK, width=2)
        # legend: the ramp with its end values
        ly = head_h + len(self.rows) * ch + 18
        lw = min(260, len(self.cols) * cw)
        seg = lw / len(RAMP)
        for k, col in enumerate(RAMP):
            cv.create_rectangle(row_w + k * seg, ly, row_w + (k + 1) * seg, ly + 10, fill=col, outline="")
        cv.create_text(row_w, ly + 14, text=self.fmt(vmin), anchor="nw", fill=INK_2, font=(fam, 8))
        cv.create_text(row_w + lw, ly + 14, text=self.fmt(vmax), anchor="ne", fill=INK_2, font=(fam, 8))
        if getattr(self, "caption", ""):
            cv.create_text(row_w + lw + 12, ly + 5, text=self.caption, anchor="w", fill=INK_2, font=(fam, 8))
        cv.configure(scrollregion=(0, 0, row_w + len(self.cols) * cw + 20, ly + 40))

    def _cell(self, e):
        if not self._geom:
            return None
        row_w, head_h, cw, ch = self._geom
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        j, i = int((x - row_w) // cw), int((y - head_h) // ch)
        if x < row_w or y < head_h or not (0 <= i < len(self.rows)) or not (0 <= j < len(self.cols)):
            return None
        return i, j

    def _motion(self, e):
        c = self._cell(e)
        if not c:
            self.tip.hide()
            return
        self.tip.show(e.x, e.y, self.tips[c[0]][c[1]])

    def _click(self, e, cb):
        c = self._cell(e)
        if c and cb:
            if cb is self.on_click:
                self.selected = c
            cb(*c)
            self.draw()


# =============================================================================
# horizontal bars with whiskers
# =============================================================================
@dataclass
class BarItem:
    key: object
    label: str
    value: float
    lo: float | None = None           # whisker (e.g. 5th percentile)
    hi: float | None = None           # whisker (e.g. 95th percentile)
    color: str = SLOTS[0]
    sublabel: str = ""
    tip: list[str] = field(default_factory=list)
    segments: list[tuple[float, str]] = field(default_factory=list)   # stacked (share, colour); shares sum to 1


class BarChart(ttk.Frame):
    """Sorted horizontal bars. Click a bar -> on_click(key). Scrolls vertically."""

    ROW = 30

    def __init__(self, master, on_click: Callable[[object], None] | None = None):
        super().__init__(master, style="Flat.TFrame")
        self.cv = tk.Canvas(self, bg=SURFACE, highlightthickness=0)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=ys.set)
        self.cv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tip = _Tip(self.cv)
        self.on_click = on_click
        self.items: list[BarItem] = []
        self.fmt: Callable[[float], str] = lambda v: f"{v:.1f}"
        self.legend: list[tuple[str, str]] = []
        self.empty_text = "Nothing to show."
        self._rows: list[tuple[float, float, BarItem]] = []
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda e: (self.tip.hide(), self._hover(None)))
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1),
                                                                     "units"))
        self.cv.bind("<Button-4>", lambda e: self.cv.yview_scroll(-3, "units"))
        self.cv.bind("<Button-5>", lambda e: self.cv.yview_scroll(3, "units"))
        self._hovered = None

    def set_data(self, items: list[BarItem], fmt=None, legend=None, empty_text: str = ""):
        self.items = items
        if fmt:
            self.fmt = fmt
        self.legend = legend or []
        if empty_text:
            self.empty_text = empty_text
        self.cv.yview_moveto(0)
        self.draw()

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.tip.items = []
        fam = font_family()
        self._rows = []
        if not self.items:
            cv.create_text(20, 20, text=self.empty_text, anchor="nw", fill=INK_2, font=(fam, 10))
            cv.configure(scrollregion=(0, 0, 10, 10))
            return
        W = max(cv.winfo_width(), 300)
        label_w = min(330, max(160, int(W * 0.38)))
        value_w = 56
        x0, x1 = label_w + 8, W - value_w - 8
        top = 26 if self.legend else 8
        vmax = max(max(it.value, it.hi if it.hi is not None else it.value) for it in self.items) or 1.0
        scale = (x1 - x0) / vmax
        # legend (identity is never colour alone: every bar also has its label)
        lx = x0
        for name, color in self.legend:
            cv.create_rectangle(lx, 8, lx + 10, 18, fill=color, outline="")
            t = cv.create_text(lx + 14, 13, text=name, anchor="w", fill=INK_2, font=(fam, 9))
            lx = cv.bbox(t)[2] + 16
        # recessive vertical grid
        for k in range(1, 5):
            gx = x0 + (x1 - x0) * k / 4
            cv.create_line(gx, top, gx, top + len(self.items) * self.ROW, fill=GRID)
        for n, it in enumerate(self.items):
            y = top + n * self.ROW
            if self._hovered is not None and self._hovered is it.key:
                cv.create_rectangle(0, y, W, y + self.ROW, fill=GRID, outline="")
            cv.create_text(label_w, y + (10 if it.sublabel else self.ROW / 2), text=it.label, anchor="e",
                           width=label_w - 8, fill=INK, font=(fam, 9))
            if it.sublabel:
                cv.create_text(label_w, y + 22, text=it.sublabel, anchor="e", width=label_w - 8,
                               fill=INK_2, font=(fam, 8))
            bx = x0 + max(1.0, it.value * scale)
            if it.segments:
                sx = x0
                for share, color in it.segments:
                    ex = sx + (bx - x0) * share
                    cv.create_rectangle(sx, y + 8, ex, y + self.ROW - 8, fill=color, outline="")
                    sx = ex
            else:
                cv.create_rectangle(x0, y + 8, bx, y + self.ROW - 8, fill=it.color, outline="")
            if it.lo is not None and it.hi is not None and it.hi > it.lo:
                lo, hi = x0 + it.lo * scale, x0 + it.hi * scale
                cy = y + self.ROW / 2
                cv.create_line(lo, cy, hi, cy, fill=INK_2, width=1)
                cv.create_line(lo, cy - 4, lo, cy + 4, fill=INK_2)
                cv.create_line(hi, cy - 4, hi, cy + 4, fill=INK_2)
            cv.create_text(W - 8, y + self.ROW / 2, text=self.fmt(it.value), anchor="e", fill=INK,
                           font=(fam, 9, "bold"))
            self._rows.append((y, y + self.ROW, it))
        cv.create_line(x0, top, x0, top + len(self.items) * self.ROW, fill=INK_3)
        cv.configure(scrollregion=(0, 0, W, top + len(self.items) * self.ROW + 10))

    def _item_at(self, e) -> BarItem | None:
        y = self.cv.canvasy(e.y)
        for y0, y1, it in self._rows:
            if y0 <= y < y1:
                return it
        return None

    def _hover(self, key):
        if key is not self._hovered:
            self._hovered = key
            self.draw()

    def _motion(self, e):
        it = self._item_at(e)
        self._hover(it.key if it else None)
        if it:
            self.tip.show(e.x, e.y, it.tip)
        else:
            self.tip.hide()

    def _click(self, e):
        it = self._item_at(e)
        if it and self.on_click:
            self.tip.hide()
            self.on_click(it.key)
