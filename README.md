# Game Crunch

Warhammer 40,000 (11th edition) toolkit: load two army lists, pick units, and get
mathhammer statistics (expected damage, models slain, full distributions) from a
Monte Carlo engine driven by Wahapedia's data export.

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are © Games Workshop.

## Quick start

```bash
pip install -r requirements.txt        # numpy (tkinter ships with Python on Windows)
python -m crunch fetch                  # download Wahapedia data, mission deck and layouts into wahapedia_data/
python main.py                          # launch the app   (or double-click run_app.bat)
```

Army lists are NewRecruit **text** exports placed in `lists/`.

Command line:

```bash
python -m crunch show  --unit "Knight Castellan"
python -m crunch fight --attacker "Kabalite Warriors" --attacker-models 10 \
                       --defender "Custodian Guard" --defender-models 5 --mod cover
python -m crunch fetch --force          # refresh the data
python -m crunch fetch --no-missions    # CSVs only
```

Tests (standard library `unittest`, no extra packages):

```bash
python -m unittest discover -s tests -t .
```

## Layout

```
main.py                   start the app
run_app.bat               start the app with .venv, errors -> run_log.txt
crunch/
  config.py               paths (project, data, lists), edition, attribution
  context.py              AppContext: loaded data + settings shared by every window
  cli.py, __main__.py     python -m crunch  ui | fetch | show | fight
  util.py                 text helpers (norm, strip_html, to_int, clean_glyphs)
  core/                   rules engine - pure Python/numpy, no files, no UI
    dice.py               "D6+1" etc.
    keywords.py           weapon abilities, incl. qualified ones ("Lethal Hits: non-Vehicle")
    models.py             Weapon, ModelProfile, Unit, WeaponLoad, Target(Group)
    modifiers.py          everything that can change an attack sequence
    engine.py             simulate() and allocation (11th-edition save ordering)
  data/
    fetch.py              download Wahapedia CSVs, build json/ tree, check missions and layouts
    missions.py           Wahapedia mission deck page -> missions/json/: Force Dispositions,
                          primary and secondary missions
    layouts.py            Rapid Ingress layout data -> missions/json/layouts.json: the 45
                          layouts (deployment zones, objectives, terrain) per disposition pairing
    wahapedia.py          CSVs -> Unit objects
    rules.py              army rules, detachments, stratagems, abilities (lazy)
    missionbook.py        primary missions and layouts from missions/json (lazy), per disposition pairing
  lists/
    registry.py           pluggable list formats
    newrecruit.py         NewRecruit text export
    model.py              ArmyList / ListUnit (format-independent)
    linking.py            list -> datasheets, weapon loads, targets
  deploy/                 Deployer back end (no UI)
    bases.py              base sizes (inches; estimated when the data has none), unit footprints
    roster.py             an army as it stands on the table: unit + attached characters, footprint
    placement.py          random spot in a deployment zone, keeping footprints on the board
    movement.py           move / advance / charge rings
    objectives.py         objectives as terrain: touching areas joined, distance to a unit
    sight.py              line of sight by ray casting (dense terrain, ruin edges, board edges)
  analysis/               Optimizer back end (no UI)
    variants.py           catalogue of attacker / defender modifiers, test packages
    plan.py               per-unit test plans, saved to user_data/test_plans.json
    sweep.py              build every test, run them in parallel worker processes
    results.py            filtering, hiding and aggregation (best / average / worst, phase totals)
    assign.py             army plan: a 1st and 2nd target for every attacker
    army_plans.py         saved army plans, one per pair of lists, shared with other windows
  ui/
    app.py                Tk root, launcher, opens tools
    registry.py           @register_tool + auto-discovery
    toolwindow.py         base class for tool windows
    launcher.py           choose attacker/defender lists, then a tool
    theme.py, widgets.py  colours, styles, shared widgets
    charts.py             canvas heatmap and bar chart with tooltips
    richtext.py           Wahapedia HTML -> text window, stratagem cards
    views/rules.py        army-rules and unit-abilities windows (reusable)
    tools/
      finder/             the Finder: one unit against another (army panels | results)
      optimizer/          the Optimizer (test plans | run | results window)
      deployer/           the Deployer: missions + army summaries | the pairing's three layouts
tests/                    unit tests + small fixtures
lists/                    your army lists
user_data/                saved test plans (git-ignored)
wahapedia_data/           downloaded data (git-ignored)
```

Dependencies only point downwards: `ui → lists → data → core`. Nothing in `core`
imports from `data`, `lists` or `ui`, so the engine can be reused (CLI, tests,
a future web front end) without tkinter.

## Optimizer

Tick attacking and defending units, then build each unit's tests (Tests tab): tick
some modifiers and press **Add test**. All ticked modifiers are applied **together**,
as one test; add as many tests as you like. An attacker test also says which phases
it runs in (Shooting, Fight or both); a modifier that means nothing in a phase (cover
in the Fight phase) is dropped there. Ticking a unit gives it a "No modifiers" test;
unticking it deletes all its tests.

Every attacker test (in each of its phases) is run against every defender test: an
attacker with {No modifiers: both phases} and {+1 to hit, Re-roll failed wounds: Shooting}
against a defender with {No modifiers} and {Cover, Feel No Pain 6+} makes 3 x 2 = 6 tests.
Plans are saved per list file, side and unit.

Results open in their own window. The **Phase** selector shows the Shooting phase,
the Fight phase, or their **total**: for each pairing, each phase's value (from its
own best / average / worst attacker test) is added up, capped at the whole defending
unit; the chance to destroy the unit becomes "destroyed in either phase". Phases are
simulated separately, so a total doesn't account for Shooting casualties before the Fight.

- **Army plan** - gives every attacker a 1st target (its priority) and a 2nd target
  (worth half) so that every defender is targeted at least once, guided by a mix of
  share of the unit's wounds and points removed per 100 pts (slider). Attackers sent
  at the same unit share it: damage beyond its wounds counts for nothing. The plan is
  saved automatically, one per pair of lists (attacker list, defender list), and kept
  up to date as settings, filters or hidden tests change (user_data/army_plans.json);
  reopening the results restores it. Other windows read it through `ctx.army_plans`:
  `get(attacker_list, defender_list)`, then `targets_of(unit)` / `attackers_of(unit)`
  (any unit of a group finds it), and `subscribe(callback)` to hear about changes.
- **Matrix** - attackers x defenders heatmap; click a cell for every test behind it,
  right-click to hide the pairing.
- **Best attackers into... / Best targets for...** - ranked bars; click a bar to hide
  that scenario and let the unit's next best one take its place.
- **All tests** - sortable table; tick / untick rows to hide them.
- Filters on the left (attackers, defenders, phase, scenarios), metric
  (damage, models slain, % wounds, wipe chance, points removed, points per 100 pts),
  best / average / worst over attacker scenarios and defender tests, CSV export.

## Deployer

Uses each list's `Force Disposition:` line (changeable in the window) to show the
primary mission each player plays, a compact view of both armies (Leaders and Support
characters merged into their unit), and the three battlefield layouts of the pairing:
deployment zones, terrain, objectives and, optionally, the table-setup measurements.
Needs the mission data from `python -m crunch fetch`.

Tick a unit (✓) to put it on every map, each at its own random spot in its side's
deployment zone; drag it anywhere on its board, it stops at the edges. A single model
is its base (Wahapedia's base size); a unit is one ellipse holding every base with 1"
between neighbours (Leaders and Support characters included). Models without an
official base size (vehicles: "Use model") get an oval estimated from their Wounds,
drawn dashed. Units are half see-through so terrain shows underneath, and new ones are
placed clear of those already on the board when there is room. Hover a unit for its
models and size; click to select it (one selection for the window, highlighted in the
roster), double click to turn it 30° clockwise, right click to release the selection.

Options for the selected unit (under the legend), following it as it moves:
movement range (M, the slowest model's), advance (M + 3.5", the average D6), charge
(7", the average 2D6; M + 7" with movement ticked too; M + D6 + 2D6 = M + 10.5" with
advance ticked too) - each a line
at that distance from the unit's footprint edge - and the distance to each objective,
as a dash-dot line from the footprint edge to the nearest point of the objective. An
objective is the whole terrain its marker stands on; terrain areas touching along an
edge (at least 1" of outline in contact, not just a corner) count as one piece.

Targets (option): arrows from attackers to their targets in the Optimizer's army plan for
these two lists, edge to edge, redrawn as units move and as soon as the Optimizer re-plans.
By default the selected unit's 1st target (for a selected defender: the attackers aiming at
it); "2nd" adds the 2nd targets (dashed), "all" shows them for every attacker on the maps.

Line of sight (option): what the unit sees up to its longest ranged weapon, shaded very
lightly, with a circle (and its distance) per weapon range, all from the base edge. Rays
leave from points around the base; a dense terrain feature stops a ray, and a ray can
cross one terrain edge (see into a ruin, not through it), two when it starts inside one.
A piece of terrain counts as one whole, as for objectives: the footprints of an area, and
areas touching along an edge, have no inner borders (seams up to 0.3" wide included).
Light features don't block; the board edges do; elevation is ignored. Its sub-option
Hidden: nothing inside a terrain area can be seen from more than 15" - a ray entering a
terrain area stops 15" from its source (or at the area's edge if it gets there beyond 15");
and Hidden's own sub-option Go to Ground brings that down to 12".

## Adding a new window (tool)

1. Create `crunch/ui/tools/<name>.py` (or a package `crunch/ui/tools/<name>/`).
2. Subclass `ToolWindow` and register a factory:

```python
from crunch.ui.registry import Selection, register_tool
from crunch.ui.toolwindow import ToolWindow


class GamePlanWindow(ToolWindow):
    title_text = "Game plan"

    def __init__(self, app, selection: Selection):
        super().__init__(app, selection)
        # self.ctx.wd       -> datasheets / units
        # self.ctx.rules    -> rules text
        # self.selection.attacker / .defender -> the two ArmyList objects


@register_tool("gameplan", "Game plan", "Deployment and objectives for both lists", order=20)
def open_gameplan(app, selection):
    return GamePlanWindow(app, selection)
```

That's all: the launcher discovers it and shows a **Game plan →** button next to
**Finder →**. Reuse `crunch.ui.widgets`, `crunch.ui.theme` and `crunch.ui.views`
for a consistent look.

## Adding a list format

Write `crunch/lists/<format>.py` with `detect(text) -> bool` and
`parse(text, path, wd) -> ArmyList`, call `register_parser(...)`, and import the
module in `crunch/lists/__init__.py`. Datasheet linking, weapon loads and targets
then work unchanged.

## Engine rules (11th edition)

- Benefit of Cover worsens the BS of ranged attacks by 1 (not vs Ignores Cover / Torrent / melee).
- A unit uses the Toughness of the majority of its non-Character models.
- The defender sets the allocation order; Precision attacks go to one chosen Character first.
- Save rolls for a weapon's attacks are resolved from the lowest result to the highest.
- Normal damage is resolved before mortal wounds (Devastating Wounds); mortals spill over.
