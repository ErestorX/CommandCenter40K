"""Middle third of the Armies Auspex window: the phase and the simulation results."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from command_center.config import ATTRIBUTION_SHORT as ATTRIBUTION
from command_center.core import SimResult
from command_center.qt.theme import C, font_family
from command_center.qt.widgets import Panel, Table, button, label, pct

if TYPE_CHECKING:
    from command_center.qt.tools.auspex.window import AuspexWindow

PHASES = (("Shooting", "shooting"), ("Fight", "fight"))


class Histogram(QWidget):
    """The chances of each outcome of a result: a bar per number of models slain (or of wounds dealt,
    against one or two models), the chance of at least as many under it, the mean marked."""

    def __init__(self):
        super().__init__()
        self.result: SimResult | None = None
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_result(self, r: SimResult | None) -> str:
        """Show a result (None: nothing), and return the chart's title for it."""
        self.result = r
        self.update()
        if not r:
            return ""
        if r.target.models > 2:
            return "Models slain: chance of exactly k (bar) and at least k (below)"
        return f"Damage dealt (of {max(1, r.total_wounds)} wounds): chance of exactly k and at least k"

    def paintEvent(self, event):
        r, W, H = self.result, self.width(), self.height()
        if not r or W < 50 or H < 50:
            return
        p = QPainter(self)
        st = r.stats()
        if r.target.models > 2:
            probs = list(st["slain_hist"])
            at_least = st["p_slain_at_least"]
        else:
            cap = max(1, r.total_wounds)
            d = np.minimum(r.damage, cap)
            probs = list(np.bincount(d, minlength=cap + 1)[: cap + 1] / len(d))
            at_least = [float((d >= k).mean()) for k in range(cap + 1)]
        n = len(probs)
        pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 34
        cw = (W - pad_l - pad_r) / n
        top = max(probs) or 1
        base = H - pad_b
        mean = st["slain_mean"] if r.target.models > 2 else st["damage_mean"]
        label_every = max(1, int(np.ceil(n / ((W - 16) / 28))))
        p.setFont(QFont(font_family(), 9))
        for k, prob in enumerate(probs):
            x0 = pad_l + k * cw + cw * 0.12
            x1 = pad_l + (k + 1) * cw - cw * 0.12
            h = (base - pad_t) * prob / top
            p.fillRect(QRectF(x0, base - h, x1 - x0, h), QColor(C["bar"] if prob >= 0.005 else C["bar2"]))
            if k % label_every == 0:
                cx = (x0 + x1) / 2
                p.setPen(QColor(C["ink"]))
                p.drawText(QRectF(cx - 30, base + 2, 60, 14), Qt.AlignCenter, str(k))
                if k:
                    p.setPen(QColor(C["muted"]))
                    p.drawText(QRectF(cx - 30, base + 16, 60, 14), Qt.AlignCenter, pct(at_least[k]))
        mx = pad_l + (mean + 0.5) * cw
        p.setPen(QPen(QColor(C["ink"]), 1, Qt.DashLine))
        p.drawLine(QPointF(mx, pad_t - 6), QPointF(mx, base))
        p.setPen(QColor(C["ink"]))
        p.drawText(QRectF(mx + 4, pad_t - 10, 120, 14), Qt.AlignLeft | Qt.AlignVCenter, f"mean {mean:.1f}")
        p.setPen(QColor(C["line"]))
        p.drawLine(QPointF(pad_l, base), QPointF(W - pad_r, base))


class ResultsPanel(Panel):
    def __init__(self, win: "AuspexWindow"):
        super().__init__()
        self.win = win
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(0)

        top = QHBoxLayout()
        top.addWidget(button("← Command Center", win.back))
        top.addStretch(1)
        top.addWidget(button("⇄ Swap sides", win.swap))
        col.addLayout(top)
        col.addSpacing(10)

        ph = QHBoxLayout()
        ph.setSpacing(0)
        ph.addWidget(label("Phase", "h2"))
        ph.addSpacing(10)
        group = QButtonGroup(self)                          # a switch: two buttons, the chosen one pressed in
        self.phase_buttons = {}
        for text, phase in PHASES:
            b = self.phase_buttons[phase] = button(text, lambda phase=phase: win.set_phase(phase), "switch")
            b.setCheckable(True)
            b.setChecked(phase == win.phase)
            group.addButton(b)
            ph.addWidget(b)
        ph.addStretch(1)
        col.addLayout(ph)
        col.addSpacing(8)

        self.title_lbl = label("", "h2", wrap=True, align=Qt.AlignCenter)
        col.addWidget(self.title_lbl)
        col.addSpacing(8)

        cards = QHBoxLayout()
        cards.setSpacing(4)
        self.cards = {}
        for key, text in (("dmg", "Expected damage"), ("slain", "Models slain"), ("wipe", "Unit destroyed")):
            card = Panel()
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # a third each
            inner = QVBoxLayout(card)
            inner.setContentsMargins(6, 4, 6, 4)
            inner.setSpacing(0)
            inner.addWidget(label(text, "muted", align=Qt.AlignCenter))
            big = label("–", "big", align=Qt.AlignCenter)
            small = label("\n", "muted", align=Qt.AlignCenter)
            inner.addWidget(big)
            inner.addWidget(small)
            cards.addWidget(card, 1)
            self.cards[key] = (big, small)
        col.addLayout(cards)
        col.addSpacing(10)

        self.chart_title = label("", "muted")
        col.addWidget(self.chart_title)
        self.chart = Histogram()
        col.addWidget(self.chart, 1)
        col.addSpacing(6)
        self.breakdown = Table([("w", "Weapon"), ("n", "#"), ("a", "Att"), ("h", "Hits"), ("wd", "Wnds"), ("u", "Unsv"),
                                ("d", "Dmg")], [-160, 32, 46, 46, 46, 46, 46], rows=5, fixed=True, selectable=False)
        col.addWidget(self.breakdown)
        col.addSpacing(4)
        self.status = label("", "muted", wrap=True)
        col.addWidget(self.status)
        col.addWidget(label(ATTRIBUTION, "muted"))
        self.result: SimResult | None = None

    def busy(self, title: str):
        self.title_lbl.setText(title)
        self.status.setText("Computing…")

    def empty(self, title: str, message: str):
        self.result = None
        self.title_lbl.setText(title)
        for big, small in self.cards.values():
            big.setText("–")
            small.setText("\n")
        self.breakdown.clear_rows()
        self.chart_title.setText(self.chart.set_result(None))
        self.status.setText(message)

    def show_result(self, title: str, r: SimResult, seconds: float):
        self.result = r
        st = r.stats()
        self.title_lbl.setText(title)
        lo, hi = st["damage_pct"]["p5"], st["damage_pct"]["p95"]
        self.cards["dmg"][0].setText(f"{st['damage_mean']:.1f}")
        self.cards["dmg"][1].setText(f"± {st['damage_sd']:.1f}  ·  90%: {lo:.0f}–{hi:.0f}\nof {r.total_wounds} wounds")
        slo, shi = st["slain_pct"]["p5"], st["slain_pct"]["p95"]
        self.cards["slain"][0].setText(f"{st['slain_mean']:.1f}")
        self.cards["slain"][1].setText(f"± {st['slain_sd']:.1f}  ·  90%: {slo:.0f}–{shi:.0f}\nof {r.target.models} models")
        self.cards["wipe"][0].setText(pct(st["p_wipe"]))
        pc = st["p_character_slain"]
        self.cards["wipe"][1].setText((f"character slain: {pct(pc)}" if pc is not None else "") +
                                      f"\nmean 95% CI {st['damage_ci95'][0]:.2f}–{st['damage_ci95'][1]:.2f}")
        self.breakdown.clear_rows()
        for w in r.weapons:
            self.breakdown.add_row((w.name, w.count, f"{w.attacks:.1f}", f"{w.hits:.1f}", f"{w.wounds:.1f}",
                                    f"{w.unsaved:.1f}", f"{w.damage:.1f}"))
        tags = ", ".join(r.mod_tags) or "none"
        self.status.setText(f"{r.trials:,} simulated attacks in {seconds:.2f}s  ·  modifiers: {tags}")
        self.chart_title.setText(self.chart.set_result(r))
