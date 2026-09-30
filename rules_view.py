"""
rules_view.py - read-only rules text for the UI: army rules, detachments, stratagems,
enhancements and unit abilities, rendered from Wahapedia's HTML into a tkinter Text window.

Powered by Wahapedia (https://wahapedia.ru). Rules text is (c) Games Workshop.
"""
from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from collections import defaultdict
from html.parser import HTMLParser
from tkinter import ttk

from mathhammer import Wahapedia, norm, read_table

# =============================================================================
# data
# =============================================================================
class RulesBook:
    """Lazily loads the rules tables that the simulator itself doesn't need."""

    def __init__(self, wd: Wahapedia):
        self.wd = wd
        self._t: dict[str, list[dict]] = {}

    def table(self, name: str) -> list[dict]:
        if name not in self._t:
            self._t[name] = read_table(self.wd.data_dir, name)
        return self._t[name]

    @property
    def abilities_by_id(self) -> dict[str, dict]:
        if "_ab" not in self._t:
            self._t["_ab"] = {a["id"]: a for a in self.table("Abilities")}
        return self._t["_ab"]

    # ---- army level --------------------------------------------------------
    def army_rules(self, faction_id: str | None) -> list[dict]:
        return [a for a in self.table("Abilities") if faction_id and a.get("faction_id") == faction_id]

    def detachments(self, faction_id: str | None, names: list[str]) -> list[dict]:
        rows = [d for d in self.table("Detachments") if d.get("faction_id") == faction_id]
        wanted = [norm(n) for n in names]
        return [d for d in rows if norm(d["name"]) in wanted]

    def detachment_content(self, det: dict) -> dict[str, list[dict]]:
        did, name = det.get("id", ""), norm(det.get("name", ""))
        match = lambda r: (did and r.get("detachment_id") == did) or norm(r.get("detachment", "")) == name
        return {
            "rules": [r for r in self.table("Detachment_abilities") if match(r)],
            "enhancements": [r for r in self.table("Enhancements") if match(r)],
            "stratagems": [r for r in self.table("Stratagems") if match(r)],
        }

    def core_stratagems(self) -> list[dict]:
        return [s for s in self.table("Stratagems")
                if not s.get("faction_id") and s.get("type", "").lower().startswith("core")]

    # ---- unit level --------------------------------------------------------
    def unit_abilities(self, datasheet_id: str) -> dict[str, list[tuple[str, str]]]:
        """{'Core': [(name, html)], 'Faction': [...], 'Datasheet': [...], 'Wargear': [...], ...}"""
        if "_dsa" not in self._t:
            g = defaultdict(list)
            for r in self.table("Datasheets_abilities"):
                g[r.get("datasheet_id", "")].append(r)
            self._t["_dsa"] = g
        out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in sorted(self._t["_dsa"].get(datasheet_id, []), key=lambda r: int(r.get("line") or 0)):
            ref = self.abilities_by_id.get(r.get("ability_id", ""), {})
            name = r.get("name") or ref.get("name", "")
            if r.get("parameter"):
                name = f"{name} {r['parameter']}"
            kind = r.get("type") or "Other"
            if kind not in ("Core", "Faction", "Datasheet", "Wargear"):
                kind = "Other"
            desc = r.get("description") or ("" if kind in ("Core", "Faction") else ref.get("description", ""))
            out[kind].append((name, desc))
        return out

    def datasheet_row(self, datasheet_id: str) -> dict:
        return self.wd.datasheets.get(datasheet_id, {})


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


def clean(s: str) -> str:
    """Characters some Windows/Tk fonts can't draw -> plain equivalents."""
    return (s or "").replace("\u2011", "-").replace("\u00ad", "").replace("\u2009", " ").replace("\u202f", " ")


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
CARD = {"head": "#1d1c1a", "sub": "#1f4a73", "border": "#b9b3a6", "body": "#ffffff", "legend": "#f4f1ea"}


def _style_text(t: tk.Text, fam: str) -> None:
    t.tag_configure("h1", font=(fam, 16, "bold"), spacing1=6, spacing3=6)
    t.tag_configure("h2", font=(fam, 13, "bold"), foreground="#a3262a", spacing1=14, spacing3=4)
    t.tag_configure("h3", font=(fam, 11, "bold"), spacing1=8, spacing3=2)
    t.tag_configure("meta", font=(fam, 9), foreground="#6e6a63", spacing3=4)
    t.tag_configure("bold", font=(fam, 10, "bold"))
    t.tag_configure("italic", font=(fam, 10, "italic"), foreground="#4a4741")
    t.tag_configure("underline", underline=True)
    t.tag_configure("kw", font=(fam, 9, "bold"))
    t.tag_configure("muted", foreground="#8a857c")
    t.tag_configure("bullet", foreground="#a3262a")
    t.tag_configure("indent", lmargin1=18, lmargin2=34)
    t.tag_configure("rule", foreground="#d8d3c8")
    t.tag_configure("found", background="#f2dd9b")


def _display_lines(t: tk.Text) -> int:
    n = t.count("1.0", "end", "displaylines")
    if isinstance(n, tuple):
        n = n[0]
    return max(1, int(n or 1))


class RulesWindow(tk.Toplevel):
    """Scrollable, read-only rich text."""

    def __init__(self, master, title: str, width=760, height=820):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.configure(bg="#fbfaf8")
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
                            bg="#fbfaf8", fg="#1d1c1a", font=(fam, 10), spacing1=1, spacing3=2,
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
        grid = tk.Frame(self.text, bg="#fbfaf8")
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
                       bg=CARD["body"], fg="#1d1c1a", font=(fam, 10), spacing1=1, spacing3=2, cursor="arrow")
        _style_text(body, fam)
        body.tag_configure("legend", font=(fam, 9, "italic"), foreground="#4a4741", background=CARD["legend"],
                           spacing3=6)
        if st.get("legend"):
            body.insert("end", clean(st["legend"]).strip() + "\n", ("legend",))
        for text, tags in render_html(st.get("description", "")):
            body.insert("end", text, tags)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True)
        foot = "  ·  ".join(x for x in (st.get("turn"), st.get("phase")) if x)
        if foot:
            tk.Label(card, text=foot, bg=CARD["body"], fg="#6e6a63", font=(fam, 8), anchor="w",
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


# =============================================================================
# content builders
# =============================================================================
def _strat_meta(s: dict) -> str:
    bits = [f"{s.get('cp_cost', '?')} CP", s.get("type", "")]
    if s.get("turn"):
        bits.append(s["turn"])
    if s.get("phase"):
        bits.append(s["phase"])
    return "  ·  ".join(b for b in bits if b)


def show_army_rules(master, book: RulesBook, army) -> RulesWindow:
    w = RulesWindow(master, f"{army.faction} — army & detachment rules", width=1120, height=860)
    w.h1(army.faction)
    w.meta(f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else ""))

    rules = book.army_rules(army.faction_id)
    w.h2("Army rules")
    if not rules:
        w.meta("No army rule found for this faction.")
    for r in rules:
        w.h3(r["name"])
        w.html(r.get("description", ""))

    dets = book.detachments(army.faction_id, army.detachment_names)
    if not dets:
        w.h2("Detachment")
        w.meta(f"Could not match “{army.detachment or 'no detachment'}” to a Wahapedia detachment.")
    taken = {norm(n) for u in army.units for n, _ in u.unit_gear}
    for m_u in army.units:
        for m in m_u.models:
            taken |= {norm(n) for n, _ in m.gear}
    for d in dets:
        c = book.detachment_content(d)
        w.h2(f"Detachment: {d['name']}")
        extra = [x for x in (d.get("type"), f"{d['dp']} DP" if d.get("dp") else "", d.get("force_disposition")) if x]
        if extra:
            w.meta("  ·  ".join(extra))
        for r in c["rules"]:
            w.h3(r["name"])
            w.html(r.get("description", ""))
        if c["enhancements"]:
            w.h3("Enhancements")
            for e in c["enhancements"]:
                mine = "  ← in this list" if norm(e["name"]) in taken else ""
                w.h3(f"• {e['name']}", f"{e.get('cost', '?')} pts{mine}")
                w.html(e.get("description", ""))
        if c["stratagems"]:
            w.h3("Stratagems")
            w.cards(c["stratagems"])

    core = book.core_stratagems()
    if core:
        w.h2("Core stratagems")
        w.cards(core)
    w.gap()
    w.meta("Powered by Wahapedia · rules © Games Workshop")
    w.done()
    return w


def show_unit_abilities(master, book: RulesBook, units: list) -> RulesWindow:
    """units: ListUnit objects (bodyguard first, then attached characters)."""
    names = " + ".join(u.label for u in units)
    w = RulesWindow(master, f"{names} — abilities", width=700)
    w.h1(names)
    for u in units:
        ds = u.datasheet
        if not ds:
            continue
        row = book.datasheet_row(ds.id)
        w.h2(u.label + ("  (Support)" if u.is_support else "  (Leader)" if u is not units[0] and u.is_character else ""))
        for p in ds.models:
            inv = f"  {p.inv}++" if p.inv else ""
            w.meta(f"{p.name}:  M {p.M}   T {p.T}   Sv {p.Sv}+{inv}   W {p.W}")
        inv_descr = next((m.get("inv_sv_descr") for m in book.wd._models.get(ds.id, []) if m.get("inv_sv_descr")), "")
        if inv_descr:
            w.html(inv_descr)
        ab = book.unit_abilities(ds.id)
        for kind in ("Core", "Faction"):
            if ab.get(kind):
                w.text.insert("end", f"{kind}: ", ("bold",))
                w.text.insert("end", ", ".join(n for n, _ in ab[kind]) + "\n")
        for kind, title in (("Datasheet", "Abilities"), ("Wargear", "Wargear abilities"), ("Other", "Other")):
            for name, desc in ab.get(kind, []):
                w.h3(name, title if kind != "Datasheet" else "")
                if desc:
                    w.html(desc)
        if row.get("leader_head") or row.get("leader_footer"):
            w.h3("Attachment")
            w.html(row.get("leader_head", "") + "<br>" + row.get("leader_footer", ""))
        if row.get("damaged_w"):
            w.h3(f"Damaged: {row['damaged_w']} wounds remaining")
            w.html(row.get("damaged_description", ""))
        w.text.insert("end", "Keywords: ", ("bold",))
        w.text.insert("end", ", ".join(sorted(k.upper() for k in ds.keywords)) + "\n", ("kw",))
    w.gap()
    w.meta("Powered by Wahapedia · rules © Games Workshop")
    w.done()
    return w
