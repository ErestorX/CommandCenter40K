"""A web spike: what the front end evaluated in docs/web_migration.md would look like, on the app's real
data and back end. Not part of the app, and not shipped with it. The same window as spikes/qt_spike.py.

    python spikes/web_spike/server.py              serve the page and open it in the browser
    python spikes/web_spike/server.py --window     in a window of its own (pip install pywebview)
    python spikes/web_spike/server.py --no-open    serve only (--port N: on that port)

The back end stays in Python, behind a small JSON interface made with the standard library alone:

    /                   the page (index.html, the palette of command_center.ui.theme written into it)
    /api/board          a real layout, four units placed in their zones
    /api/sight          what a unit sees from where it stands (command_center.deploy.sight)
    /api/matrix         a heatmap's values, each with its colour
    /api/stratagems     Wahapedia's HTML, as it is
    /api/run            a long task, its progress sent as it goes (server-sent events)
    /pyodide            the same line of sight computed in the browser, with no server (pyodide.html)
    /backend.zip        the back end's packages, for that page; /data.zip: Wahapedia's CSVs; /bench.py: BENCH

    python spikes/web_spike/server.py --bench      run BENCH here, to compare with what that page measures

/api/report takes what a page measured and prints it (the pages opened with ?auto=1 send it).
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))               # run from anywhere: the app's package is two folders up

from command_center import config
from command_center.context import AppContext
from command_center.deploy.placement import ellipse_polygon, random_spot
from command_center.deploy.sight import Obstacles, cast, fans

# the theme's colours and the chart's ramp, copied: importing them from command_center.ui would bring tkinter
C = {"bg": "#0b0b0d", "panel": "#15151a", "field": "#0e0e11", "raised": "#22222a", "hover": "#2e2e38",
     "ink": "#e9e7e2", "muted": "#908d87", "line": "#3b3b44", "accent": "#d5352c", "select": "#5a1d19",
     "att": "#e2554e"}
RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5",
        "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"]
UNITS = [("attacker", "Boyz", 9.0, 3.5, 18), ("attacker", "Battlewagon", 6.5, 4.0, 36),
         ("defender", "Intercessors", 5.0, 2.6, 24), ("defender", "Redemptor Dreadnought", 3.5, 3.5, 36)]


# What the Pyodide page runs in the browser, and --bench here: the data loaded, then one attack simulated.
BENCH = """
import json, sys, time
from command_center.core import Modifiers, Target, TargetGroup, WeaponLoad, simulate
from command_center.data.wahapedia import Wahapedia
t = time.perf_counter()
wd = Wahapedia(None)
att, dfn = wd.unit_by_name("Kabalite Warriors", None), wd.unit_by_name("Custodian Guard", None)
load_ms = (time.perf_counter() - t) * 1000
loads = [WeaponLoad(w, 10) for w in att.weapons if not w.melee]
target = Target(dfn.name, [TargetGroup(dfn.models[0], 5, dfn.is_character)], dfn.keywords)
times = []
for _ in range(5):
    t = time.perf_counter()
    simulate(loads, target, Modifiers(), 20_000, 1)
    times.append((time.perf_counter() - t) * 1000)
bench = json.dumps({"python": sys.version.split()[0], "data_load_ms": round(load_ms),
                    "simulate_20000_ms": round(sorted(times)[2], 1)})
"""


class Spike:
    """What the pages are served from: loaded once, as AppContext is for the app's windows."""

    def __init__(self):
        self.ctx = AppContext()
        self.layout = self.ctx.missions.layouts[0]
        self.obstacles = Obstacles.from_layout(self.layout)
        self.reports: list[dict] = []
        self.reported = threading.Event()

    def board(self) -> dict:
        rng, zones = random.Random(40), self.layout.get("deployment_zones", {})
        tokens = []
        for role, label, w, h, reach in UNITS:
            x, y = random_spot(zones.get(role, []), w, h, rng)
            tokens.append({"role": role, "label": label, "w": w, "h": h, "reach": reach, "x": x, "y": y, "angle": 0})
        return {"layout": self.layout, "tokens": tokens, "dispositions": self.ctx.missions.dispositions}

    def sight(self, q: dict) -> list:
        x, y, w, h, angle, reach = (float(q[k][0]) for k in ("x", "y", "w", "h", "angle", "reach"))
        rays = cast(ellipse_polygon(x, y, w, h, angle, n=72), reach, self.obstacles)
        return [[[round(px, 2), round(py, 2)] for px, py in fan] for fan in fans(rays)]

    def matrix(self) -> dict:
        rows = ["Boyz", "Battlewagon", "Meganobz", "Deff Dread", "Lootas", "Warbikers"]
        cols = ["Intercessors", "Terminators", "Redemptor", "Land Raider"]
        values = [[((i * 7 + j * 13) % 17) / 2 + 0.4 * i for j in range(len(cols))] for i in range(len(rows))]
        flat = [v for row in values for v in row]
        low, span = min(flat), max(flat) - min(flat)

        def cell(v):
            i = round((v - low) / span * (len(RAMP) - 1))
            return {"value": v, "fill": RAMP[i], "ink": "white" if i <= 6 else "#0b0b0b"}
        return {"rows": rows, "cols": cols, "cells": [[cell(v) for v in row] for row in values]}

    def stratagems(self) -> list:
        return [{k: s[k] for k in ("name", "cp_cost", "type", "legend", "description")}
                for s in self.ctx.rules.core_stratagems()[:8]]

    def backend_zip(self) -> bytes:
        """The back end as Pyodide unpacks it: every package but the front end."""
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted((ROOT / "command_center").rglob("*.py")):
                if "ui" not in path.relative_to(ROOT).parts:
                    z.write(path, path.relative_to(ROOT).as_posix())
        return out.getvalue()

    def data_zip(self) -> bytes:
        """Wahapedia's CSVs, where the back end looks for them."""
        out, raw = io.BytesIO(), Path(self.ctx.wd.data_dir)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(raw.glob("*.csv")):
                z.write(path, f"wahapedia_data/{config.EDITION}/raw/{path.name}")
        return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    spike: Spike
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):               # quiet: one line per request otherwise
        pass

    def send(self, body: bytes, kind: str):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, data):
        self.send(json.dumps(data).encode("utf-8"), "application/json")

    def do_GET(self):
        url, s = urlparse(self.path), self.spike
        if url.path in ("/", "/pyodide"):
            page = (HERE / ("index.html" if url.path == "/" else "pyodide.html")).read_text(encoding="utf-8")
            palette = "".join(f"--{k}: {v}; " for k, v in C.items())
            self.send(page.replace("/*PALETTE*/", palette).encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/font.ttf":
            self.send(next(config.FONTS_DIR.glob("*.ttf")).read_bytes(), "font/ttf")
        elif url.path == "/backend.zip":
            self.send(s.backend_zip(), "application/zip")
        elif url.path == "/data.zip":
            self.send(s.data_zip(), "application/zip")
        elif url.path == "/bench.py":
            self.send(BENCH.encode("utf-8"), "text/x-python")
        elif url.path == "/api/board":
            self.json(s.board())
        elif url.path == "/api/sight":
            self.json(s.sight(parse_qs(url.query)))
        elif url.path == "/api/matrix":
            self.json(s.matrix())
        elif url.path == "/api/stratagems":
            self.json(s.stratagems())
        elif url.path == "/api/run":
            self.run_task()
        else:
            self.send_error(404)

    def run_task(self):
        """Real work on this request's thread, its progress sent as it goes: no queue to poll."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        outline = ellipse_polygon(14, 14, 6.5, 4.0, 0, n=72)
        for n in range(1, 21):
            cast(outline, 36, self.spike.obstacles)
            self.wfile.write(f"data: {n * 5}\n\n".encode())
            self.wfile.flush()
        self.close_connection = True

    def do_POST(self):
        if urlparse(self.path).path != "/api/report":
            self.send_error(404)
            return
        report = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        print(json.dumps(report), flush=True)
        self.spike.reports.append(report)
        self.spike.reported.set()
        self.json({})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=0, help="the port to serve on (any free one by default)")
    parser.add_argument("--no-open", action="store_true", help="serve only: open nothing")
    parser.add_argument("--window", action="store_true", help="a window of its own, with pywebview")
    parser.add_argument("--until-report", action="store_true", help="stop once a page has sent its measures")
    parser.add_argument("--bench", action="store_true", help="run BENCH here and print what it measures")
    args = parser.parse_args()
    if args.bench:
        scope: dict = {}
        exec(BENCH, scope)
        print(scope["bench"])
        return
    Handler.spike = spike = Spike()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)     # this machine only
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(url, flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if args.window:
        import webview
        webview.create_window("Command Center 40K — web spike", url, maximized=True, background_color=C["bg"])
        webview.start()
        return
    if not args.no_open and not args.until_report:
        webbrowser.open(url)
    try:
        if args.until_report:
            spike.reported.wait(180)
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
