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
  lists/
    registry.py           pluggable list formats
    newrecruit.py         NewRecruit text export
    model.py              ArmyList / ListUnit (format-independent)
    linking.py            list -> datasheets, weapon loads, targets
  analysis/               Optimizer back end (no UI)
    variants.py           catalogue of attacker / defender modifiers, test packages
    plan.py               per-unit test plans, saved to user_data/test_plans.json
    sweep.py              build every test, run them in parallel worker processes
    results.py            filtering, hiding and aggregation (best / average / worst, phase totals)
    assign.py             army plan: a 1st and 2nd target for every attacker
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
  at the same unit share it: damage beyond its wounds counts for nothing.
- **Matrix** - attackers x defenders heatmap; click a cell for every test behind it,
  right-click to hide the pairing.
- **Best attackers into... / Best targets for...** - ranked bars; click a bar to hide
  that scenario and let the unit's next best one take its place.
- **All tests** - sortable table; tick / untick rows to hide them.
- Filters on the left (attackers, defenders, phase, scenarios), metric
  (damage, models slain, % wounds, wipe chance, points removed, points per 100 pts),
  best / average / worst over attacker scenarios and defender tests, CSV export.

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
