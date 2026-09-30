# Game Crunch

Warhammer 40,000 (11th edition) toolkit: load two army lists, pick units, and get
mathhammer statistics (expected damage, models slain, full distributions) from a
Monte Carlo engine driven by Wahapedia's data export.

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are © Games Workshop.

## Quick start

```bash
pip install -r requirements.txt        # numpy (tkinter ships with Python on Windows)
python -m crunch fetch                  # download Wahapedia data into wahapedia_data/
python main.py                          # launch the app   (or double-click run_app.bat)
```

Army lists are NewRecruit **text** exports placed in `lists/`.

Command line:

```bash
python -m crunch show  --unit "Knight Castellan"
python -m crunch fight --attacker "Kabalite Warriors" --attacker-models 10 \
                       --defender "Custodian Guard" --defender-models 5 --mod cover
python -m crunch fetch --force          # refresh the data
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
    fetch.py              download Wahapedia CSVs, build json/ tree
    wahapedia.py          CSVs -> Unit objects
    rules.py              army rules, detachments, stratagems, abilities (lazy)
  lists/
    registry.py           pluggable list formats
    newrecruit.py         NewRecruit text export
    model.py              ArmyList / ListUnit (format-independent)
    linking.py            list -> datasheets, weapon loads, targets
  ui/
    app.py                Tk root, launcher, opens tools
    registry.py           @register_tool + auto-discovery
    toolwindow.py         base class for tool windows
    launcher.py           choose attacker/defender lists, then a tool
    theme.py, widgets.py  colours, styles, shared widgets
    richtext.py           Wahapedia HTML -> text window, stratagem cards
    views/rules.py        army-rules and unit-abilities windows (reusable)
    tools/
      matchup/            the matchup tool (army panels | results)
tests/                    unit tests + small fixtures
lists/                    your army lists
wahapedia_data/           downloaded data (git-ignored)
```

Dependencies only point downwards: `ui → lists → data → core`. Nothing in `core`
imports from `data`, `lists` or `ui`, so the engine can be reused (CLI, tests,
a future web front end) without tkinter.

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
**Matchup →**. Reuse `crunch.ui.widgets`, `crunch.ui.theme` and `crunch.ui.views`
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
