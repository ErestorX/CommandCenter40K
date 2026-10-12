"""Take the root README's screenshots (assets/screenshots/) from the real app.

    python scripts/readme_screenshots.py                        every screenshot, into assets/screenshots
    python scripts/readme_screenshots.py --out shots launcher   only some, into another folder

The app is opened on the demonstration lists (lists/DemOrks.txt attacking lists/TestMarines.txt) and on
a temporary copy of the work saved for them (assets/demo/user_data): your own user_data is neither read
nor written. Each window is pictured by Qt itself (what it holds, without its title bar): it need not be
in front, and the mouse and the keyboard can be used meanwhile (about half a minute; the Engagement
Optimizer's tests are really run).
"""
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))               # run from anywhere: the app's package is next to this folder


def main(out: Path, only: set[str]) -> None:
    from command_center import config
    data = Path(tempfile.mkdtemp(prefix="cc40k-shots-"))
    shutil.copytree(config.DEMO_USER_DATA_DIR, data / "user_data")
    config.USER_DATA_DIR = data / "user_data"                   # before anything reads or saves there

    from PySide6.QtCore import QEventLoop, QTimer

    from command_center.context import AppContext
    from command_center.deploy.scoring import SecondaryRow
    from command_center.ui.app import App, application
    from command_center.ui.launcher import AddListDialog
    from command_center.ui.registry import discover

    discover()
    qt = application()
    app = App(AppContext())
    app.show()
    orks, marines = config.LISTS_DIR / "DemOrks.txt", config.LISTS_DIR / "TestMarines.txt"

    def pump(seconds=0.5, until=None):
        """Let the app run: for that long, or until something is true (two minutes at most)."""
        for _ in range(int(seconds * 20) if until is None else 2400):
            loop = QEventLoop()                                 # Qt's own waiting: worker threads get to run
            QTimer.singleShot(50, loop.quit)
            loop.exec()
            if until is not None and until():
                return

    def shot(name, widget):
        if only and name not in only:
            return
        pump(0.4)
        picture = widget.grab()
        picture.save(str(out / f"{name}.png"))
        print(f"{name}.png  {picture.width()}x{picture.height()}")

    # ---------------------------------------------------------------- launcher, add a list
    for picker in (app.launcher.att, app.launcher.dfn):         # the demonstration lists only, whatever else is there
        picker.paths = [orks, marines]
        picker._fill()
    app.launcher.att.select(orks)
    app.launcher.dfn.select(marines)
    pump(0.8)
    shot("launcher", app)
    dlg = AddListDialog(app.launcher.dfn, app, "defender", lambda p: None)
    dlg.text.setPlainText(marines.read_text(encoding="utf-8"))
    dlg.name.setText("TestMarines v2")
    dlg.open()
    pump(0.8)
    shot("add-list", dlg)
    dlg.reject()
    sel = app.launcher.selection

    # ---------------------------------------------------------------- Armies Auspex
    win = app.open_tool("auspex", sel)
    tank = next(u for u in sel.attacker.units if u.label.startswith("Tankbustas"))
    inter = next(u for u in sel.defender.units if u.label.startswith("Intercessor"))
    for panel, unit in ((win.left, tank), (win.right, inter)):
        panel.units_tree.select(unit.uid)
        panel.on_unit()
    win.left._range_box.setEditText('12"')
    win.right.checks["cover"].setChecked(True)
    win.results.status.setText("")
    pump(until=lambda: "simulated" in win.results.status.text() and not win._timer.isActive())
    shot("armies-auspex", win)
    win.back()

    # ---------------------------------------------------------------- Engagement Optimizer and its results
    win = app.open_tool("optimizer", sel)
    deff = next(u for u in sel.attacker.units if u.label.startswith("Deffkoptas"))
    dread = next(u for u in sel.defender.units if u.label.startswith("Redemptor"))
    for panel, unit in ((win.left, deff), (win.right, dread)):
        panel.units_tree.select(unit.uid)
        panel._on_select()
    win.left.nb.setCurrentIndex(1)                              # its tests, with the Value column
    shot("engagement-optimizer", win)
    if not only or only & {"optimizer-army-plan", "optimizer-matrix"}:
        win.run()
        pump(until=lambda: bool(win.result_windows))
        res = win.result_windows[-1]
        for tab, name in ((0, "optimizer-army-plan"), (1, "optimizer-matrix")):
            res.nb.setCurrentIndex(tab)
            if tab == 1:
                res._cell_click(4, 1)                           # a pairing's tests, under the matrix
            shot(name, res)
        res.close()
    win.back()

    # ---------------------------------------------------------------- Field Holomap and the Score Oracle
    win = app.open_tool("holomap", sel)
    pump(0.6)
    for i, m in enumerate(win.maps):
        m.rng = random.Random(7 + i)                            # the same spots at every run
    for role, wanted in (("attacker", ("Meganobz", "Tankbustas", "Deffkoptas")), ("defender", ("",))):
        for key, row in win.side.rows[role].items():
            if row.name.startswith(wanted):
                win.side.toggle(role, key)
    key = next(f"attacker:{k}" for k, row in win.side.rows["attacker"].items() if row.name.startswith("Deffkoptas"))
    win.maps[0].pick(key)
    for name in ("move", "charge", "plan", "sight"):
        win.overlay_ticks[name].setChecked(True)
    shot("field-holomap", win)
    for tick in win.shown[1:]:
        tick.setChecked(False)
    shot("field-holomap-one-layout", win)
    for tick in win.shown[1:]:
        tick.setChecked(True)

    o = win.open_score_oracle()
    pump(0.6)
    o.cells["attacker"]["went_first"].setChecked(True)
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
    shot("score-oracle", o)
    win.back()

    # ---------------------------------------------------------------- Disposition Cogitator, an Estimate
    win = app.open_tool("cogitator", None)
    pump(0.6)
    shot("disposition-cogitator", win)
    win.open_estimate("Take and Hold", "Disruption")
    shot("estimate", win.estimate)
    win.back()
    app.close()
    qt.processEvents()
    shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":                  # the guard the Optimizer's worker processes need
    import argparse
    ap = argparse.ArgumentParser(description="Take the README's screenshots from the real app.")
    ap.add_argument("names", nargs="*", help="the screenshots to take, without .png (default: all)")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "screenshots", help="the folder they go in")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    main(args.out, set(args.names))
