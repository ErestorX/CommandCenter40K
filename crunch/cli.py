"""
Command line:

    python -m crunch                    # graphical app (same as: python main.py)
    python -m crunch fetch [--force]    # download / refresh Wahapedia data
    python -m crunch show --unit "Knight Castellan"
    python -m crunch fight --attacker "Kabalite Warriors" --attacker-models 10 \\
        --defender "Custodian Guard" --defender-models 5 --mod cover

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are (c) Games Workshop.
"""
from __future__ import annotations

import argparse
import sys

from crunch.core import Modifiers, Target, TargetGroup, WeaponLoad, simulate
from crunch.data.wahapedia import Wahapedia


def cmd_show(a):
    wd = Wahapedia(a.data)
    u = wd.unit_by_name(a.unit, a.faction)
    print(f"{u.name}  ({wd.factions.get(u.faction_id, u.faction_id)})")
    for p in u.models:
        print(f"  {p.name}: M{p.M} T{p.T} Sv{p.Sv}+" + (f" {p.inv}++" if p.inv else "") + f" W{p.W}")
    print(f"  keywords: {', '.join(sorted(u.keywords)) or '-'}")
    for w in u.weapons:
        print("  - " + w.summary())


def cmd_fight(a):
    wd = Wahapedia(a.data)
    att = wd.unit_by_name(a.attacker, a.attacker_faction)
    dfn = wd.unit_by_name(a.defender, a.defender_faction)
    mods = Modifiers.from_pairs(a.mod or [])
    weapons = att.weapons
    if a.weapon:
        weapons = [w for w in weapons if a.weapon.lower() in w.name.lower()]
    weapons = [w for w in weapons if (w.melee if a.melee else not w.melee)]
    if not weapons:
        sys.exit("No matching weapons")
    target = Target(dfn.name, [TargetGroup(dfn.models[0], a.defender_models, dfn.is_character)], dfn.keywords)
    print(f"{att.name} x{a.attacker_models} ({'melee' if a.melee else 'ranged'})")
    if a.each:
        for w in weapons:
            r = simulate([WeaponLoad(w, a.attacker_models)], target, mods, a.trials, a.seed)
            print(r.report(), "\n")
    else:
        r = simulate([WeaponLoad(w, a.attacker_models) for w in weapons], target, mods, a.trials, a.seed)
        print(r.report())
    print("Powered by Wahapedia")


def cmd_ui(a):
    from crunch.ui.app import main as ui_main
    ui_main(a.data)


def cmd_fetch(rest: list[str]):
    from crunch.data import fetch
    fetch.main(rest)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "fetch":            # fetch owns its own argument parser
        cmd_fetch(argv[1:])
        return
    ap = argparse.ArgumentParser(prog="python -m crunch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    u = sub.add_parser("ui", help="graphical app (default)")
    u.add_argument("--data", help="folder with the raw Wahapedia CSVs")
    u.set_defaults(fn=cmd_ui)
    sub.add_parser("fetch", help="download / refresh Wahapedia data (see: python -m crunch fetch -h)")

    s = sub.add_parser("show", help="show a unit's stats and weapons")
    s.add_argument("--data")
    s.add_argument("--unit", required=True)
    s.add_argument("--faction")
    s.set_defaults(fn=cmd_show)

    f = sub.add_parser("fight", help="attacker vs defender (all weapons of the chosen type fire together)")
    f.add_argument("--data")
    f.add_argument("--attacker", required=True)
    f.add_argument("--attacker-faction")
    f.add_argument("--attacker-models", type=int, default=1)
    f.add_argument("--defender", required=True)
    f.add_argument("--defender-faction")
    f.add_argument("--defender-models", type=int, default=1)
    f.add_argument("--weapon", help="substring of the weapon name")
    f.add_argument("--melee", action="store_true", help="use melee weapons (default: ranged)")
    f.add_argument("--each", action="store_true", help="one result per weapon instead of combined")
    f.add_argument("--mod", action="append", help="modifier key=value, repeatable (see crunch.core.modifiers)")
    f.add_argument("--trials", type=int, default=20_000)
    f.add_argument("--seed", type=int, default=1)
    f.set_defaults(fn=cmd_fight)

    a = ap.parse_args(argv)
    if not a.cmd:
        a = ap.parse_args(["ui"])
    try:
        a.fn(a)
    except (KeyError, FileNotFoundError) as e:
        sys.exit(str(e))
