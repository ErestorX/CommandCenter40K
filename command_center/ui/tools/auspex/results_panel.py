"""Middle third of the Armies Auspex window: the phase and the simulation results."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import numpy as np

from command_center.config import ATTRIBUTION_SHORT as ATTRIBUTION
from command_center.core import SimResult
from command_center.ui.theme import C
from command_center.ui.widgets import make_tree, pct

if TYPE_CHECKING:
    from command_center.ui.tools.auspex.window import AuspexWindow


class ResultsPanel(ttk.Frame):
    def __init__(self, master, win: "AuspexWindow"):
        super().__init__(master, style="Panel.TFrame", padding=10)
        self.win = win
        fonts = win.app.fonts

        top = ttk.Frame(self, style="Flat.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="← Command Center", command=win.back).pack(side="left")
        ttk.Button(top, text="⇄ Swap sides", command=win.swap).pack(side="right")

        ph = ttk.Frame(self, style="Flat.TFrame")
        ph.pack(fill="x", pady=(10, 2))
        ttk.Label(ph, text="Phase", style="H2.TLabel").pack(side="left", padx=(0, 10))
        for text, val in (("Shooting", "shooting"), ("Fight", "fight")):
            ttk.Radiobutton(ph, text=text, value=val, variable=win.phase, style="Panel.TRadiobutton",
                            command=win.on_phase).pack(side="left", padx=4)

        self.title_lbl = ttk.Label(self, text="", style="H2.TLabel", wraplength=440, justify="center")
        self.title_lbl.pack(fill="x", pady=(8, 8))

        cards = ttk.Frame(self, style="Flat.TFrame")
        cards.pack(fill="x")
        self.cards = {}
        for i, (key, label) in enumerate((("dmg", "Expected damage"), ("slain", "Models slain"),
                                          ("wipe", "Unit destroyed"))):
            f = ttk.Frame(cards, style="Panel.TFrame", padding=(6, 4))
            f.grid(row=0, column=i, sticky="nsew", padx=2)
            cards.columnconfigure(i, weight=1, uniform="cards")
            ttk.Label(f, text=label, style="Muted.TLabel").pack()
            big = ttk.Label(f, text="–", style="Big.TLabel")
            big.pack()
            small = ttk.Label(f, text="", style="Muted.TLabel", justify="center")
            small.pack()
            self.cards[key] = (big, small)

        self.chart_title = ttk.Label(self, text="", style="Muted.TLabel")
        self.chart_title.pack(anchor="w", pady=(10, 0))
        self.canvas = tk.Canvas(self, height=190, bg=C["panel"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_chart())

        f, self.breakdown = make_tree(self, [("w", "Weapon"), ("n", "#"), ("a", "Att"), ("h", "Hits"),
                                             ("wd", "Wnds"), ("u", "Unsv"), ("d", "Dmg")],
                                      [-160, 32, 46, 46, 46, 46, 46], height=5)
        f.pack(fill="x", pady=(6, 4))

        self.status = ttk.Label(self, text="", style="Muted.TLabel")
        self.status.pack(anchor="w")
        ttk.Label(self, text=ATTRIBUTION, style="Muted.TLabel").pack(anchor="w")
        self.result: SimResult | None = None

    def busy(self, title: str):
        self.title_lbl.configure(text=title)
        self.status.configure(text="Computing…")

    def empty(self, title: str, message: str):
        self.result = None
        self.title_lbl.configure(text=title)
        for big, small in self.cards.values():
            big.configure(text="–")
            small.configure(text="")
        self.breakdown.delete(*self.breakdown.get_children())
        self.chart_title.configure(text="")
        self.canvas.delete("all")
        self.status.configure(text=message)

    def show(self, title: str, r: SimResult, seconds: float):
        self.result = r
        st = r.stats()
        self.title_lbl.configure(text=title)
        lo, hi = st["damage_pct"]["p5"], st["damage_pct"]["p95"]
        self.cards["dmg"][0].configure(text=f"{st['damage_mean']:.1f}")
        self.cards["dmg"][1].configure(text=f"± {st['damage_sd']:.1f}  ·  90%: {lo:.0f}–{hi:.0f}\n"
                                            f"of {r.total_wounds} wounds")
        slo, shi = st["slain_pct"]["p5"], st["slain_pct"]["p95"]
        self.cards["slain"][0].configure(text=f"{st['slain_mean']:.1f}")
        self.cards["slain"][1].configure(text=f"± {st['slain_sd']:.1f}  ·  90%: {slo:.0f}–{shi:.0f}\n"
                                              f"of {r.target.models} models")
        self.cards["wipe"][0].configure(text=pct(st["p_wipe"]))
        pc = st["p_character_slain"]
        self.cards["wipe"][1].configure(text=(f"character slain: {pct(pc)}" if pc is not None else "") +
                                        f"\nmean 95% CI {st['damage_ci95'][0]:.2f}–{st['damage_ci95'][1]:.2f}")
        self.breakdown.delete(*self.breakdown.get_children())
        for w in r.weapons:
            self.breakdown.insert("", "end", values=(w.name, w.count, f"{w.attacks:.1f}", f"{w.hits:.1f}",
                                                     f"{w.wounds:.1f}", f"{w.unsaved:.1f}", f"{w.damage:.1f}"))
        tags = ", ".join(r.mod_tags) or "none"
        self.status.configure(text=f"{r.trials:,} simulated attacks in {seconds:.2f}s  ·  modifiers: {tags}")
        self.draw_chart()

    def draw_chart(self):
        cv = self.canvas
        cv.delete("all")
        r = self.result
        if not r:
            return
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50 or H < 50:
            return
        st = r.stats()
        if r.target.models > 2:
            probs = list(st["slain_hist"])
            at_least = st["p_slain_at_least"]
            labels = [str(k) for k in range(len(probs))]
            self.chart_title.configure(text="Models slain: chance of exactly k (bar) and at least k (below)")
        else:
            cap = max(1, r.total_wounds)
            d = np.minimum(r.damage, cap)
            probs = list(np.bincount(d, minlength=cap + 1)[: cap + 1] / len(d))
            at_least = [float((d >= k).mean()) for k in range(cap + 1)]
            labels = [str(k) for k in range(cap + 1)]
            self.chart_title.configure(text=f"Damage dealt (of {cap} wounds): chance of exactly k and at least k")
        n = len(probs)
        pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 34
        cw = (W - pad_l - pad_r) / n
        top = max(probs) or 1
        base = H - pad_b
        mean = st["slain_mean"] if r.target.models > 2 else st["damage_mean"]
        label_every = max(1, int(np.ceil(n / ((W - 16) / 28))))
        for k, p in enumerate(probs):
            x0 = pad_l + k * cw + cw * 0.12
            x1 = pad_l + (k + 1) * cw - cw * 0.12
            h = (base - pad_t) * p / top
            cv.create_rectangle(x0, base - h, x1, base, fill=C["bar"] if p >= 0.005 else C["bar2"], width=0)
            if k % label_every == 0:
                cx = (x0 + x1) / 2
                cv.create_text(cx, base + 9, text=labels[k], fill=C["ink"], font=self.win.app.fonts["small"])
                if k:
                    cv.create_text(cx, base + 23, text=pct(at_least[k]), fill=C["muted"],
                                   font=self.win.app.fonts["small"])
        mx = pad_l + (mean + 0.5) * cw
        cv.create_line(mx, pad_t - 6, mx, base, fill=C["ink"], dash=(3, 3))
        cv.create_text(mx + 4, pad_t - 6, text=f"mean {mean:.1f}", anchor="nw", fill=C["ink"],
                       font=self.win.app.fonts["small"])
        cv.create_line(pad_l, base, W - pad_r, base, fill=C["line"])
