"""A battlefield layout drawn on a canvas: deployment zones, terrain, objectives, measurements.
Scales to the space it gets, keeping the board's 60" x 44" proportions."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from crunch.ui.theme import C, font_family

BOARD_W, BOARD_H = 60.0, 44.0
ZONE_FILL = {"attacker": "#f1d3d3", "defender": "#d3dff0"}
ZONE_INK = {"attacker": C["att"], "defender": C["def"]}
BOARD_FILL = "#f7f5ef"
AREA_FILL, AREA_LINE = "#ddd6c8", "#9b9384"
FEATURE_FILL = {"DENSE": "#5f584d", "LIGHT": "#a8a092"}
OBJ_FILL = {"central": "#1d1c1a", "expansion": "#3c7d45"}
MEASURE = "#6e6a63"


def objective_fill(o: dict) -> str:
    if o.get("type") == "home":
        return ZONE_INK.get(o.get("owner") or "", "#1d1c1a")
    return OBJ_FILL.get(o.get("type", ""), "#1d1c1a")


class LayoutMap(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, style="Panel.TFrame", padding=6)
        self.title = ttk.Label(self, text="", style="H2.TLabel")
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, text="", style="Muted.TLabel")
        self.sub.pack(anchor="w")
        self.cv = tk.Canvas(self, bg=C["panel"], highlightthickness=0)
        self.cv.pack(fill="both", expand=True, pady=(4, 0))
        self.layout: dict | None = None
        self.message = ""
        self.show_measurements = False
        self.cv.bind("<Configure>", lambda e: self.draw())

    def set_layout(self, layout: dict | None, message: str = "", show_measurements: bool | None = None):
        self.layout, self.message = layout, message
        if show_measurements is not None:
            self.show_measurements = show_measurements
        if layout:
            self.title.configure(text=f"Layout {layout.get('variant', '')}")
            self.sub.configure(text=f"{layout['id']}  ·  attacker deploys {layout.get('attacker_edge', '?')}, "
                                    f"defender {layout.get('defender_edge', '?')}")
        else:
            self.title.configure(text="")
            self.sub.configure(text="")
        self.draw()

    # ---------------------------------------------------------------- drawing
    def draw(self):
        cv = self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        fam = font_family()
        if not self.layout:
            if self.message:
                cv.create_text(W / 2, H / 2, text=self.message, fill=C["muted"], font=(fam, 10), width=W - 20)
            return
        pad = 4
        k = min((W - 2 * pad) / BOARD_W, (H - 2 * pad) / BOARD_H)
        if k <= 0:
            return
        ox = (W - BOARD_W * k) / 2
        oy = (H - BOARD_H * k) / 2

        def xy(p):                                     # board inches (y up) -> canvas pixels
            return ox + p[0] * k, oy + (BOARD_H - p[1]) * k

        def flat(points):
            return [c for p in points for c in xy(p)]

        cv.create_rectangle(ox, oy, ox + BOARD_W * k, oy + BOARD_H * k, fill=BOARD_FILL, outline="")
        lay = self.layout
        for side in ("attacker", "defender"):
            for poly in lay.get("deployment_zones", {}).get(side, []):
                if len(poly) >= 3:
                    cv.create_polygon(flat(poly), fill=ZONE_FILL[side], outline="")
        areas = lay.get("terrain", [])
        for area in areas:                              # every footprint first, so none hides a feature
            for fp in area.get("footprints", []):
                if len(fp.get("points", [])) >= 3:
                    cv.create_polygon(flat(fp["points"]), fill=AREA_FILL, outline=AREA_LINE)
        for area in areas:
            for f in area.get("features", []):
                if len(f.get("points", [])) >= 3:
                    cv.create_polygon(flat(f["points"]), fill=FEATURE_FILL.get(f.get("category"), "#8a857a"),
                                      outline="")
        if self.show_measurements:
            m = lay.get("measurements", {})
            for x1, y1, x2, y2 in m.get("lines", []):
                cv.create_line(*xy((x1, y1)), *xy((x2, y2)), fill=MEASURE, dash=(3, 2))
            size = max(7, min(9, int(k * 1.1)))
            for lb in m.get("labels", []):
                x, y = xy((lb["x"], lb["y"]))
                t = cv.create_text(x, y, text=lb["text"], fill=C["ink"], font=(fam, size))
                bb = cv.bbox(t)
                r = cv.create_rectangle(bb[0] - 1, bb[1], bb[2] + 1, bb[3], fill=BOARD_FILL, outline="")
                cv.tag_raise(t, r)
        r = max(6.0, 0.9 * k)
        for o in lay.get("objectives", []):
            x, y = xy(o["position"])
            cv.create_oval(x - r, y - r, x + r, y + r, fill=objective_fill(o), outline="white", width=2)
            cv.create_text(x, y, text=str(o["number"]), fill="white", font=(fam, max(7, int(r * 0.9)), "bold"))
        cv.create_rectangle(ox, oy, ox + BOARD_W * k, oy + BOARD_H * k, outline=C["ink"])
        self._edge_labels(ox, oy, k, fam)

    def _edge_labels(self, ox, oy, k, fam):
        """ATTACKER / DEFENDER written inside the board along each side's deployment edge."""
        w, h = BOARD_W * k, BOARD_H * k
        spots = {"left": (ox + 10, oy + h / 2, 90), "right": (ox + w - 10, oy + h / 2, 270),
                 "bottom": (ox + w / 2, oy + h - 9, 0), "top": (ox + w / 2, oy + 9, 0)}
        for side in ("attacker", "defender"):
            edge = self.layout.get(f"{side}_edge", "")
            if edge in spots:
                x, y, angle = spots[edge]
                self.cv.create_text(x, y, text=side.upper(), angle=angle, fill=ZONE_INK[side],
                                    font=(fam, 8, "bold"))


def legend(master) -> ttk.Frame:
    """Key to the map colours."""
    f = ttk.Frame(master, style="Flat.TFrame")
    fam = font_family()
    rows = [("zone", ZONE_FILL["attacker"], "Attacker deployment zone"),
            ("zone", ZONE_FILL["defender"], "Defender deployment zone"),
            ("area", AREA_FILL, "Terrain area"),
            ("area", FEATURE_FILL["DENSE"], "Dense terrain feature"),
            ("area", FEATURE_FILL["LIGHT"], "Light terrain feature"),
            ("obj", ZONE_INK["attacker"], "Attacker home objective"),
            ("obj", ZONE_INK["defender"], "Defender home objective"),
            ("obj", OBJ_FILL["expansion"], "Expansion objective"),
            ("obj", OBJ_FILL["central"], "Central objective")]
    for kind, color, text in rows:
        row = ttk.Frame(f, style="Flat.TFrame")
        row.pack(anchor="w", pady=1)
        sw = tk.Canvas(row, width=18, height=14, bg=C["panel"], highlightthickness=0)
        if kind == "obj":
            sw.create_oval(3, 1, 15, 13, fill=color, outline="white")
        else:
            sw.create_rectangle(1, 2, 17, 12, fill=color, outline=AREA_LINE if kind == "area" else "")
        sw.pack(side="left")
        ttk.Label(row, text=text, style="Panel.TLabel", font=(fam, 9)).pack(side="left", padx=(4, 0))
    return f
