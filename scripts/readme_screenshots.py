"""Take the root README's screenshots (assets/screenshots/) from the real app. Windows only.

    python scripts/readme_screenshots.py                        every screenshot, into assets/screenshots
    python scripts/readme_screenshots.py --out shots launcher   only some, into another folder

The app is opened on the demonstration lists (lists/DemOrks.txt attacking lists/TestMarines.txt) and on
a temporary copy of the work saved for them (assets/demo/user_data): your own user_data is neither read
nor written. Each window is brought to the front and copied from the screen, so leave the mouse and the
keyboard alone while it runs (about a minute; the Engagement Optimizer's 160 tests are really run).
"""
import ctypes
import ctypes.wintypes as wt
import random
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))               # run from anywhere: the app's package is next to this folder

user32, gdi32, dwm = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.dwmapi
for f, res, args in ((user32.GetDC, wt.HDC, [wt.HWND]), (gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC]),
                     (gdi32.CreateCompatibleBitmap, wt.HBITMAP, [wt.HDC, ctypes.c_int, ctypes.c_int]),
                     (gdi32.SelectObject, wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ]),
                     (gdi32.BitBlt, wt.BOOL, [wt.HDC] + [ctypes.c_int] * 4 + [wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]),
                     (gdi32.GetDIBits, ctypes.c_int, [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                                                      ctypes.c_void_p, wt.UINT]),
                     (gdi32.DeleteObject, wt.BOOL, [wt.HGDIOBJ]), (gdi32.DeleteDC, wt.BOOL, [wt.HDC]),
                     (user32.ReleaseDC, ctypes.c_int, [wt.HWND, wt.HDC]), (user32.GetParent, wt.HWND, [wt.HWND])):
    f.restype, f.argtypes = res, args


def grab(left: int, top: int, width: int, height: int, path: Path) -> None:
    """Copy a rectangle of the screen to a PNG file."""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, width, height)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, width, height, screen, left, top, 0x00CC0020)      # SRCCOPY
    header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)     # top-down, 32 bits
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem, bmp, 0, height, pixels, header, 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)
    raw = pixels.raw
    rgb = bytearray()
    for y in range(height):                                     # a PNG row: no filter, then R, G, B
        line = raw[y * width * 4:(y + 1) * width * 4]           # the screen's are B, G, R and a spare byte
        px = bytearray(width * 3)
        px[0::3], px[1::3], px[2::3] = line[2::4], line[1::4], line[0::4]
        rgb += b"\x00" + px

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(rgb), 9)) + chunk(b"IEND", b""))


def main(out: Path, only: set[str]) -> None:
    from command_center import config
    data = Path(tempfile.mkdtemp(prefix="cc40k-shots-"))
    shutil.copytree(config.DEMO_USER_DATA_DIR, data / "user_data")
    config.USER_DATA_DIR = data / "user_data"                   # before anything reads or saves there

    from command_center.context import AppContext
    from command_center.deploy.scoring import SecondaryRow
    from command_center.ui.app import App
    from command_center.ui.launcher import AddListDialog
    from command_center.ui.registry import discover

    discover()
    app = App(AppContext())
    orks, marines = config.LISTS_DIR / "DemOrks.txt", config.LISTS_DIR / "TestMarines.txt"
    work = wt.RECT()
    user32.SystemParametersInfoW(48, 0, ctypes.byref(work), 0)

    def pump(seconds=1.0, win=None):
        end = time.time() + seconds
        while time.time() < end:
            (win or app).update()
            time.sleep(0.02)

    def frame(win):
        """What is seen of a window on the screen: its frame without the invisible borders, on the work area."""
        r = wt.RECT()
        dwm.DwmGetWindowAttribute(user32.GetParent(win.winfo_id()), 9, ctypes.byref(r), ctypes.sizeof(r))
        left, top = max(r.left, 0), max(r.top, 0)
        return left, top, min(r.right, work.right) - left, min(r.bottom, work.bottom) - top

    def shot(name, win, rect=None):
        if only and name not in only:
            return
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
        pump(1.2, win)
        box = rect or frame(win)
        grab(*box, out / f"{name}.png")
        win.attributes("-topmost", False)
        print(f"{name}.png  {box[2]}x{box[3]}")

    # ---------------------------------------------------------------- launcher, add a list
    app.launcher.att.select(orks)
    app.launcher.dfn.select(marines)
    pump(1.5)
    shot("launcher", app)
    dlg = AddListDialog(app.launcher.dfn, app, "defender", lambda p: None)
    dlg.text.insert("1.0", marines.read_text(encoding="utf-8"))
    dlg.name.set("TestMarines v2")
    pump(1.0, dlg)
    shot("add-list", dlg)
    dlg.destroy()
    sel = app.launcher.selection

    # ---------------------------------------------------------------- Armies Auspex
    win = app.open_tool("auspex", sel)
    pump(2.0, win)
    tank = next(u for u in sel.attacker.units if u.label.startswith("Tankbustas"))
    inter = next(u for u in sel.defender.units if u.label.startswith("Intercessor"))
    win.left.units_tree.selection_set(str(tank.uid))
    win.right.units_tree.selection_set(str(inter.uid))
    pump(1.0, win)
    win.left.vars["effective_range"].set('12"')
    win.right.vars["cover"].set(True)
    win.schedule()
    pump(3.0, win)
    shot("armies-auspex", win)
    win.back()

    # ---------------------------------------------------------------- Engagement Optimizer and its results
    win = app.open_tool("optimizer", sel)
    pump(2.0, win)
    deff = next(u for u in sel.attacker.units if u.label.startswith("Deffkoptas"))
    dread = next(u for u in sel.defender.units if u.label.startswith("Redemptor"))
    win.left.units_tree.selection_set(str(deff.uid))
    win.right.units_tree.selection_set(str(dread.uid))
    win.left.nb.select(1)                                       # its tests, with the Value column
    pump(1.5, win)
    shot("engagement-optimizer", win)
    if not only or only & {"optimizer-army-plan", "optimizer-matrix"}:
        win.run()
        end = time.time() + 300
        while not win.result_windows and time.time() < end:
            pump(0.5, win)
        res = win.result_windows[-1]
        for tab, name in ((0, "optimizer-army-plan"), (1, "optimizer-matrix")):
            res.nb.select(tab)
            pump(2.0, res)
            shot(name, res)
        res.destroy()
    win.back()

    # ---------------------------------------------------------------- Field Holomap and the Score Oracle
    win = app.open_tool("holomap", sel)
    pump(2.5, win)
    for i, m in enumerate(win.maps):
        m.rng = random.Random(7 + i)                            # the same spots at every run
    for role, wanted in (("attacker", ("Meganobz", "Tankbustas", "Deffkoptas")), ("defender", ("",))):
        for key, row in win.side.rows[role].items():
            if row.name.startswith(wanted):
                win.side.trees[role].set(key, "on", "✓")
                win.toggle_unit(role, row, True)
    pump(1.0, win)
    key = next(f"attacker:{k}" for k, row in win.side.rows["attacker"].items() if row.name.startswith("Deffkoptas"))
    win.maps[0]._select(key)
    for name in ("move", "charge", "plan", "sight"):
        win.overlay_vars[name].set(True)
    win._toggle_overlays()
    pump(2.0, win)
    shot("field-holomap", win)
    for v in win.shown[1:]:
        v.set(False)
    win._toggle_layouts()
    pump(2.0, win)
    shot("field-holomap-one-layout", win)
    for v in win.shown[1:]:
        v.set(True)
    win._toggle_layouts()

    win.open_score_oracle()
    o = win.oracle
    pump(1.5, o)
    o.cells["attacker"]["went_first"].set(True)
    o._on_went_first("attacker", True)
    o.import_estimate()
    games = {"attacker": ([("Defend Stronghold", {0: "5"}), ("Forward Position", {1: "3"}), ("No Prisoners", {1: "x"})],
                          [1, 2, 1, 0, 0], [0, 2, 1, 0, 0]),
             "defender": ([("Assassination", {0: "4"}), ("A Grievous Blow", {1: "5"})],
                          [1, 1, 2, 0, 0], [1, 0, 2, 0, 0])}
    for role, (secondaries, gained, spent) in games.items():
        s = o.scores[role]
        for name, cells in secondaries:
            row = SecondaryRow(name)
            for r, cell in cells.items():
                row.set(r, cell)
            s.secondaries.append(row)
        s.cp_gained[:], s.cp_spent[:] = gained, spent
        o._build_player(role)
    o.update_totals()
    pump(1.5, o)
    shot("score-oracle", o)
    win.back()

    # ---------------------------------------------------------------- Disposition Cogitator, an Estimate
    win = app.open_tool("cogitator", None)
    pump(2.5, win)
    shot("disposition-cogitator", win)
    win.open_estimate("Take and Hold", "Disruption")
    pump(2.0, win)
    e = win.estimate
    shot("estimate", win, (e.winfo_rootx() - 6, e.winfo_rooty() - 6, e.winfo_width() + 12, e.winfo_height() + 12))
    win.back()
    app.destroy()
    shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":                  # the guard the Optimizer's worker processes need
    import argparse
    ap = argparse.ArgumentParser(description="Take the README's screenshots from the real app (Windows).")
    ap.add_argument("names", nargs="*", help="the screenshots to take, without .png (default: all)")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "screenshots", help="the folder they go in")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    main(args.out, set(args.names))
