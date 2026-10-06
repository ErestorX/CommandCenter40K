# Command Center 40K - technical notes

How the app is built and how its tools work in detail. For what the app does and how to use
it, see the [README at the root](../README.md). Paths below are from the root of the project.

## Running, data, tests

```bash
pip install -r requirements.txt        # numpy (tkinter ships with Python on Windows)
python main.py                          # the app (run_app.bat: the same with .venv, errors -> run_log.txt)
python -m command_center                # the same
python -m command_center ui --data DIR  # with a folder of Wahapedia CSVs used as it is (no update check)
```

Data: `command_center.data.fetch.update()` downloads Wahapedia's CSV export, the mission deck
page and Rapid Ingress's layouts into `wahapedia_data/<edition>/` (raw/, json/, missions/,
manifest.json), only what changed. The app runs it at start-up (`command_center/ui/updater.py`)
when the manifest's `checked_at` is more than 24 hours old or there is no data, with one attempt
and 20 seconds per request; a failure leaves everything as it is and the app starts with the
data on disk. From the command line (three attempts, 60 seconds):

```bash
python -m command_center fetch                  # what the app does at start-up
python -m command_center fetch --force          # download and rebuild even if unchanged
python -m command_center fetch --no-missions    # CSVs only
python -m command_center fetch --from-dir DIR   # from files saved by hand
python -m command_center fetch --rebuild-json   # rebuild json/ from what is saved
```

The engine from the command line:

```bash
python -m command_center show  --unit "Knight Castellan"
python -m command_center fight --attacker "Kabalite Warriors" --attacker-models 10                        --defender "Custodian Guard" --defender-models 5 --mod cover
```

Tests (standard library `unittest`, no extra packages; run_tests.bat writes test_log.txt):

```bash
python -m unittest discover -s tests -t .
```

Packaged app: `.github/workflows/release.yml` builds it with PyInstaller (Python, tkinter and
numpy included) on Windows and on macOS (Apple Silicon), a zip each. Push a tag `vX.Y.Z` and
both zips are attached to a GitHub Release of that name; run the workflow by hand to get them
as artifacts of the run instead. Each build is started before it is zipped, and nothing is
released unless both come up. Where things are in the packaged app (`command_center/config.py`):

- Windows: a folder with the .exe. `config.PROJECT_ROOT` is that folder: lists (zipped with
  it), data and saved work are written there. `config.BUNDLE_ROOT` (fonts) is its `_internal`.
- macOS: a .app, which nothing is written in. `config.PROJECT_ROOT` is
  `~/Library/Application Support/Command Center 40K`; the lists ship inside the .app and are
  copied there at the first start (`lists.library.install_bundled_lists`). The .app is not
  signed with a Developer ID nor notarized: Gatekeeper has to be told to open it.

The packaged app updates itself (`command_center/release.py`, `command_center/ui/appupdate.py`):
it carries the tag it was built from (`version.txt` in the bundle) and, once a day at start-up
(`user_data/app_update.json`), asks GitHub for the latest release. When that one is newer it
offers to install it: its platform's zip is downloaded and unpacked in a temporary folder, the
app closes, and a script replaces the .exe and its `_internal` folder (Windows) or the .app
(macOS), nothing else, then starts the app again. Nothing is offered where the app can't be
replaced: a macOS app still running from its download folder (macOS runs it from a read-only
copy until it is moved). From the source there is no version and nothing is checked.

Saved state, all in `user_data/` (git-ignored): `test_plans.json` (the Engagement Optimizer's
tests, per list file, side and unit), `army_plans.json` (its army plans, per pair of lists),
`estimates.json` (the Disposition Cogitator's Estimates, per pairing and first player).

Look: `command_center/ui/theme.py` holds the dark palette (`C`), the ttk styles and the fonts.
Caliban Angelus (`assets/fonts/`, loaded for the process, no install) is the display font for
titles, headings, buttons, tabs and badges; numbers and body text stay in the system font
(`BODY_IN_DISPLAY_FONT` puts everything in it). The battlefield boards keep a light palette of
their own (`command_center/ui/tools/holomap/map_view.py`). The screenshots of the root README are in
`assets/screenshots/`.

## Layout

```
main.py                   start the app
run_app.bat               start the app with .venv, errors -> run_log.txt
command_center/
  config.py               paths (project, data, lists), edition, attribution
  release.py              the packaged app's own updates: latest release, download, install script
  context.py              AppContext: loaded data + settings shared by every window
  cli.py, __main__.py     python -m command_center  ui | fetch | show | fight
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
    library.py            the lists folder: a pasted list checked and saved under a new name
    newrecruit.py         NewRecruit text export
    model.py              ArmyList / ListUnit (format-independent)
    linking.py            list -> datasheets, weapon loads, targets
  deploy/                 Field Holomap back end (no UI)
    bases.py              base sizes (inches; estimated when the data has none), unit footprints
    roster.py             an army as it stands on the table: unit + attached characters, footprint
    placement.py          random spot in a deployment zone, keeping footprints on the board
    movement.py           move / advance / charge rings
    objectives.py         objectives as terrain: touching areas joined, distance to a unit
    arrange.py            where the boards viewed and the info panel go, boards as large as possible
    estimates.py          saved Estimates (primary scoring per pairing and first player), user_data/estimates.json
    scoring.py            score sheet maths: primary scoring options, VP per round, caps, Battle Ready, WTC result
    territory.py          the line between the two players' territories (the halves holding their zones)
    sight.py              line of sight by ray casting (dense terrain, ruin edges, board edges)
  analysis/               Engagement Optimizer back end (no UI)
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
    updater.py            the data check at start-up (once a day), in a window of its own
    appupdate.py          the packaged app's update at start-up: the offer, the download window
    launcher.py           choose attacker/defender lists, then a tool (list-free tools: apart, on the left)
    theme.py, widgets.py  the dark theme (colours, fonts, ttk styles), shared widgets
    translucent.py        see-through fills on a canvas: stipples, or images where Tk ignores them (macOS)
    charts.py             canvas heatmap and bar chart with tooltips
    richtext.py           Wahapedia HTML -> text window, stratagem cards
    views/rules.py        army-rules and unit-abilities windows (reusable)
    views/scoresheet.py   score sheet parts: two players face to face, the rows of a primary mission
    tools/
      cogitator/          the Disposition Cogitator: the matrix of Force Dispositions (needs no list)
                          estimate.py: a pairing's Estimate window (primaries to score | its three layouts)
      auspex/             the Armies Auspex: one unit against another (army panels | results)
      optimizer/          the Engagement Optimizer (test plans | run | results window)
      holomap/           the Field Holomap: missions + army summaries | the pairing's three layouts
                          score_oracle.py: the floating Score Oracle window, with the score sheet
  README.md               this file
tests/                    unit tests + small fixtures
assets/icon/              the app's icon: skull_icon.png and what is made from it (icon.ico for Windows,
                          icon.icns for the macOS .app, icon.png for windows elsewhere); set by theme.set_icon
assets/fonts/             the display font (Caliban Angelus), loaded by the app itself: no install needed
assets/screenshots/       the screenshots of the root README
assets/demo/user_data/    the work saved for the demonstration lists (tests, army plan, Estimates): a copy
                          of user_data/ made by hand, put in place at the first start while there is no
                          user_data/ yet (lists.library.install_demo)
lists/                    your army lists; the ones in the repository are the demonstration lists the app ships with
user_data/                saved test plans, army plans and Estimates (git-ignored)
wahapedia_data/           downloaded data (git-ignored)
```

Dependencies only point downwards: `ui → lists → data → core`. Nothing in `core`
imports from `data`, `lists` or `ui`, so the engine can be reused (CLI, tests,
a future web front end) without tkinter.

## Armies Auspex

One unit (with its Leader and Support characters) against another, simulated again at every
change: `command_center.core.simulate()` with the trials of `ctx.settings` (20,000). The
attacker's and defender's modifiers and the weapons ticked make one `Modifiers` set. Maluses
can be ignored per kind (Skill, hit roll, wound roll): each one is dropped, the bonuses stay.
Distance rules only come into play with the attacker's **effective range** (`∞` by default:
every weapon shoots): out-of-range weapons don't shoot, below 2" only [CLOSE-QUARTERS] ones
do, Rapid Fire and Melta apply within half the weapon's range, Conversion beyond 12", and a
Hidden defender is not visible from further than its distance (15" unless typed), except to
attacks that ignore cover. A target
that is not visible is only shot at by [INDIRECT FIRE] weapons. The defender's additional
invulnerable save never replaces a better one of its own. The wound allocation order is the list on
the right (drag to reorder; Precision attacks go to the chosen character). Results: expected
damage, models slain and the chance to destroy the unit, the distribution of models slain,
and a line per weapon (attacks, hits, wounds, unsaved, damage).

## Disposition Cogitator

Opens from the launcher without choosing any list (its button stands apart, left of the
Armies Auspex's: it is registered with `needs_armies=False`). At its centre, a matrix of every
Force Disposition against every other; each cell names the primary mission its row's
disposition plays against its column's, and the one played in return. Dispositions have their
colour code (`theme.DISPOSITION_COLORS`): Take and Hold green, Purge the Foe red, Disruption
deep blue, Reconnaissance teal, Priority Assets yellow.

Click a matchup to open its **Estimate**, a floating window (one per pairing, several can
be open; the two cells of a pairing, either side of the diagonal, open the same one). Its
players are Player 1 and Player 2: Player 1 has the disposition of the upper cell's row,
and the attacker's side of the layouts. Top half: the two primary missions face to face, as
on the Score Oracle's sheet, to tick or count option by option and see the VP per battle
round (15 VP a round, 45 over the game). Bottom half: the pairing's three layouts, with the
deployment zones and the line between the two territories (a territory is the half of the
battlefield that includes a player's deployment zone; on diagonal deployments the line
follows the diagonal: `command_center/deploy/territory.py`).

A pairing has two Estimates, one per player going first: the header switches between them
(Player 1 first to begin with). A mirror pairing has one only, mirrored: what is scored for
the player going first shows on whichever player goes first. Each is saved as you go
(`user_data/estimates.json`, `command_center/deploy/estimates.py`) and is there again the
next time.

In the matrix, each cell has "1st ● / 2nd ●" in its bottom right corner: how hard the
matchup is for its row's disposition (Player 1, in the upper triangle) going first and
going second. A circle is coloured from its saved Estimate's margin (the row's primary VP
less the column's), in five groups relative to all the other Estimates (fifths by rank,
`difficulty_groups()`), from red (the hardest) to green (the easiest); it stays empty while
that Estimate hasn't been made.

## Engagement Optimizer

Tick attacking and defending units, then build each unit's tests (Tests tab): tick
some modifiers and press **Add test**. All ticked modifiers are applied **together**,
as one test; add as many tests as you like. An attacker test also says which phases
it runs in (Shooting, Fight or both); a modifier that means nothing in a phase (cover
in the Fight phase) is dropped there. Ticking a unit gives it a "No modifiers" test;
unticking it deletes all its tests. The modifiers are those of the Armies Auspex
(`analysis/variants.py`). The ones that take a value (crit rolls, Sustained Hits, Attacks,
Strength, AP, Damage, Blast / Cleave, Rapid Fire, Effective range; Hidden distance, Feel No
Pain and what it is against, additional invulnerable save, Toughness, Save) show it in the
**Value** column: click it to pick another from the drop-down or type one, which also ticks
the modifier. In a test such a modifier is written `key=value` (`sustained=D3`, `range=12"`),
always with the same spelling for the same value. A saved test has the fixed-value modifiers
of earlier versions rewritten, and loses those that no longer exist.

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

## Field Holomap

Uses each list's `Force Disposition:` line (shown as a badge, set in the list) to show the
primary mission each player plays, a compact view of both armies (Leaders and Support
characters merged into their unit), and the three battlefield layouts of the pairing:
deployment zones, terrain, objectives and, optionally, the table-setup measurements.
Needs the mission data from `python -m command_center fetch`.

Each layout can be taken off the view (Layout A / B / C, next to the legend). The boards
left and the legend and options are then rearranged to draw the boards as large as the
window allows: the legend and options in a cell beside the boards, in a column on their
right, or in a strip under them.

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

Targets (option): arrows from attackers to their targets in the Engagement Optimizer's army plan for
these two lists, edge to edge, redrawn as units move and as soon as the Engagement Optimizer re-plans.
By default the selected unit's 1st target (for a selected defender: the attackers aiming at
it); "2nd" adds the 2nd targets (dashed), "all" shows them for every attacker on the maps.
With Line of sight on too, the part of the selected unit's line of sight that reaches its
1st target (and 2nd, with "2nd") is shaded faint green instead of grey: no green, no line
of sight to that target.

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

### Score Oracle

A floating score sheet, one per Field Holomap (`score_oracle.py`; the maths are in
`command_center/deploy/scoring.py`). The two players face to face, a column per battle round
and one for the end of the battle.

- Primary mission: a row per scoring line of its card (`primary_options()`), placed in the
  rounds it can be scored in: a tick box where it is scored once, a - n + counter where it is
  scored "for each ..." (and, limited to 2, where it is scored at the end of "a turn": either
  player's). Ticking an "OR" line unticks its alternative. Without a known card, a row of VP
  cells to fill by hand.
- Secondary missions: a row each; "+ Secondary" draws one at random among those the player
  hasn't had (a mission is on a sheet once). A round's cell is a drop-down: nothing, "-" (not
  active), 1 to 5, or "x" (discarded); scoring or discarding locks the row and marks the rounds
  after as not active.
- Caps: 15 VP a battle round for the primary and for the secondaries (the end-of-battle column
  is outside it), 5 VP a secondary mission, 45 VP each over the game, Battle Ready 10 (scored
  by default). VP above a cap can be entered and don't count: the round's total shows a "!".
- CP gained and used per round (- n +), and what remains, carried over.
- The header gives the WTC result: the VP difference as a 20-point split.
- **Import Estimate** fills the two primaries from the Cogitator's Estimate of the game's
  pairing, with the player ticked "Went first" going first (`game_estimate()`: Player 1 is the
  disposition that comes first in the matrix; in a mirror game, the attacker). The circle next
  to it has that Estimate's difficulty colour, from the attacker's point of view; it is empty
  when there is none, or when nobody is ticked "Went first" yet.

## Adding a new window (tool)

1. Create `command_center/ui/tools/<name>.py` (or a package `command_center/ui/tools/<name>/`).
2. Subclass `ToolWindow` and register a factory:

```python
from command_center.ui.registry import Selection, register_tool
from command_center.ui.toolwindow import ToolWindow


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
**Armies Auspex →**. Reuse `command_center.ui.widgets`, `command_center.ui.theme` and `command_center.ui.views`
for a consistent look.

## Adding a list format

Write `command_center/lists/<format>.py` with `detect(text) -> bool` and
`parse(text, path, wd) -> ArmyList`, call `register_parser(...)`, and import the
module in `command_center/lists/__init__.py`. Datasheet linking, weapon loads and targets
then work unchanged.

## Engine rules (11th edition)

- Benefit of Cover worsens the BS of ranged attacks by 1 (not vs Ignores Cover / Torrent / melee).
- A unit uses the Toughness of the majority of its non-Character models.
- The defender sets the allocation order; Precision attacks go to one chosen Character first.
- Save rolls for a weapon's attacks are resolved from the lowest result to the highest.
- Normal damage is resolved before mortal wounds (Devastating Wounds); mortals spill over.
