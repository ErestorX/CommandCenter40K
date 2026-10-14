# Study: BSData instead of Wahapedia for the army data

Branch `bsdata_study`, 14 October 2026. BSData: [BSData/wh40k-11e](https://github.com/BSData/wh40k-11e) at
`43519e4` (13 Oct 2026). Wahapedia: the app's export of 13 Oct 2026.

**Question.** Users bring NewRecruit (NR) lists. NR builds lists from BSData's files, while the app
reads Wahapedia's export, so names differ and a list has to be matched to the data loosely
(`lists/linking.py`, `Unit.profile`). How much of what the app reads from Wahapedia can come from
BSData instead?

**Since done, on this branch:** the app reads BSData first and completes it with Wahapedia (stages
1 to 3 below; the options' modifiers, stage 4, are not applied). How it works is described in
`command_center/README.md` ("Where a list's units come from").

**Short answer.** Everything a list names: units, models, their stats, their weapons, wargear,
enhancements, keywords, abilities. On the four lists of `lists/`, every one of these is found **by its
exact name**, with no matching rules at all. Not stratagems, missions and battlefield layouts, which
BSData doesn't have; nor the base sizes of the Space Marines codex, which BSData leaves empty. So:
**BSData for the armies, Wahapedia kept for the rest** (stratagems, missions, layouts, and base sizes
where BSData has none).

## What BSData is

- One JSON file per faction or library, plus the game system (`Warhammer 40,000.json`): 46 files,
  52 MB, 4.8 MB as the repository's zip (downloaded in under 2 s). Wahapedia's CSVs: 6.9 MB.
- The BattleScribe data model: entries (units, models, upgrades), groups of options, links to shared
  entries, profiles (`Unit`: M T Sv W LD OC **InSv Base**; `Ranged Weapons`, `Melee Weapons`, `Abilities`,
  `Transport`...), rules, categories (the keywords), costs, and modifiers that change all these
  depending on what is selected. All 46 files are read and indexed in 0.8 s.
- Community data, very active: the repository was created in May 2026 and had 30 commits in the four
  days before this study. **No licence file and no releases**: updates would be followed by commit.
- NewRecruit builds its lists from these files, which is why the names in a list are BSData's names.

## Method

Two throwaway scripts, kept in `scripts/bsdata_study/` so the numbers can be measured again:

```
git clone --depth 1 https://github.com/BSData/wh40k-11e.git <somewhere>
python scripts/bsdata_study/spike.py <somewhere> lists/*.txt     # the lists, linked by exact names
python scripts/bsdata_study/survey.py <somewhere>               # every faction against Wahapedia
```

`spike.py` holds a small reader (`BSData`: files, ids, links, profiles, the units a catalogue reaches).
It finds each list unit, model line and item by its exact (case-folded) name, then compares what it
finds with the app's Wahapedia data. `survey.py` compares the two sources on every faction.

## Results on the lists of `lists/`

DemOrks, TestMarines, Tacticus Encarmine Assault, Warpstrike of Devotees:

| Found by exact name in BSData | |
|---|---|
| units | 43 / 43 |
| model lines, each with its stat profile | 62 / 62 |
| items on a model line (weapons) | 148 / 148 |
| items on a unit line (enhancements, wargear options, abilities) | 58 / 58 ("Warlord" aside) |

The same lists linked to Wahapedia needed the matching rules added on `main` just before this study:
"w/" read as "with", a profile found by the start of its name, "Astartes Chainsword" taken for the
Chainsword. Before those rules, two weapons were lost (the Bladeguard's and the Sanguinary Priests'
melee weapons). Seven model lines had another model's profile: the Company Veterans had the
Ancient's, the Intercessor w/ Grenade Launcher the Sergeant's. Five more had the right one only
because it was the datasheet's first. With BSData, the list's names are the data's names.

What was found agrees with Wahapedia:
- **weapons**: 194 profiles compared, no stat difference; 2 keyword differences (the Slugga's
  "Lethal Hits (non-monster/vehicle)", in Wahapedia only);
- **model stats** (M T Sv W invulnerable): no difference;
- **base sizes**: 32 of the 62 model lines have none in BSData (all Space Marines); one difference
  (Tankbusta Nob: 32mm in BSData, 40mm in Wahapedia);
- **Leaders**: the units each can lead, read from the ability's text, are the same as Wahapedia's
  table but for one (BSData also lets the Captain with Jump Pack lead Assault Squads with Jump
  Packs, a Legends unit);
- **keywords**: BSData adds structural categories (the unit's own name, "Leader", "Support"), and the
  rest differs on a few: "Grenades" against Wahapedia's "Explosives", "Jump Pack" against "Jump
  Packs", Wahapedia's "Deathwing" on the Bladeguard and model keywords ("Ancient", "Champion").

## Results on all factions

| | |
|---|---|
| Wahapedia datasheets not in BSData | 12 (Chaos Lords and Sorcerers on mounts, Soul Grinder, X-101, Sir Hekhtur...) |
| units in both (same faction, " [Legends]" suffix aside) | 1,490 |
| weapon profiles of those units spelled the same in both | 7,733 / 9,812 (79 %) |
| stat profiles named the same, compared | 1,665 |
| … differing (M T Sv W invulnerable) | 57 (3.4 %) |
| base sizes missing in BSData | 149 compared (206 profiles: **the whole Space Marines codex**; also 37 Heresy Legends, 8 Ultramarines, 3 Space Wolves, 1 Blood Angels) |
| base sizes differing | 150 (9 %) |
| Leader abilities | 401: 1,191 of the 1,309 units they name are units (91 %) |
| modifiers on profiles | 671: 655 only test what is selected |

Notes:
- **About one weapon name in five is spelled differently** in the two sources. That is the root of
  the linking problems: no set of matching rules will catch them all.
- The 57 stat differences:
  - About a dozen are notation: aircraft Move "20+" against "-".
  - A few are conditional saves that BSData writes "4+* / 5" (Howling Banshees, Wyches); the survey
    keeps the first figure.
  - Some look like BSData slips: a blank invulnerable save on the Bannernob.
  - The rest are plain disagreements, and they go both ways. Captain in Phobos Armour: T5 in BSData,
    T4 in Wahapedia. Kill Team models with jump packs: 10" and 12" against 5" and 6". War Dog Moirax:
    T9 W14 against T10 W12.

  Neither source is right every time, and this study can't say which is.
- Base sizes in BSData are written like Wahapedia's ("32mm", "75x42mm", "60mm Flying", "Hull" for
  "Use model", "~25mm"), so `deploy.bases.parse_base` would need little change. The differences are
  real disagreements (Vyper "60mm Flying" against "105 x 70mm", Ynnari Archon 25mm against 32mm).
- Weapons with several profiles are named "➤ Name - mode" ("➤ Heavy missile launcher - krak"; a few
  are odd, like "➤ Melta Rifle HUNTER:Monster/Vehicle"). Wahapedia writes "Name - mode".
- Leader lists are free text in at least four layouts ("■ Name", "- **^^Name^^**", comma lists,
  upper-case keywords). The 9 % not read are mostly Crucible and Legends entries and keywords
  ("CHOSEN") rather than names.

## What the app reads, and where it could come from

| The app needs | Wahapedia today | BSData |
|---|---|---|
| datasheet of a list unit | `Datasheets`, matched by name | the unit entry, **exact name** |
| model profiles (M T Sv W OC, invulnerable) | `Datasheets_models` | `Unit` profile per model entry, exact name |
| base sizes (Field Holomap) | `base_size` | `Base`, **empty for the Space Marines codex** → Wahapedia |
| weapons a model carries | `Datasheets_wargear` + loose matching | the model entry's upgrades, exact names |
| weapon keywords | description text | `Keywords` text (same parser) |
| unit and Faction keywords | `Datasheets_keywords` | categories ("Faction: Blood Angels") |
| abilities, wargear abilities | `Datasheets_abilities`, `Abilities` | profiles and rule links, with their text |
| Leader / Support | `Datasheets_leader`, `is_support` | Leader text (91 % read) / "Support" category |
| enhancements | `Enhancements` | entries with their text, exact names |
| detachments, their rule, Force Disposition | `Detachments`, `Detachment_abilities` | "Detachment" entries with their rule text and Force Disposition |
| army rules | `Abilities` by faction | uneven: Orks carry theirs; the Space Marines' only through unit links |
| **stratagems** | `Stratagems` | **none** → Wahapedia |
| **missions, battlefield layouts** | mission deck, terrain files | **none** → Wahapedia (separate download today already) |
| options' effect on stats (Relic Shield: W 6) | not modelled | modifiers: 655 of 671 testable from the list |

One thing BSData can do that Wahapedia can't is the last row. A Captain with Jump Pack's profile
carries "set W to 6 when the Relic Shield is selected". With the exact entries of a list, the app
could apply most such modifiers. Evaluating them is a small piece of BattleScribe's engine, though:
it should be a stage of its own, not part of the switch.

## Risks

- **No licence.** BSData publishes community data with no licence file. The app would download it at
  run time, as it does Wahapedia's export, and not ship it. The README and the About text would
  credit BSData next to Wahapedia.
- **Young and moving.** The 11th edition files are five months old and changing daily: base sizes for
  the most played faction are still missing. Their shape (JSON, the BattleScribe model) is stable, but
  the reader must be forgiving: groups carry no `type` field, links, hidden entries, odd names.
- **Lists from elsewhere.** A list exported by NR from older or newer data than the app downloaded
  could name something the app doesn't have. The app would then fall back to Wahapedia and the
  current matching rules, which stay.
- **Two sources to keep.** Stratagems, missions and layouts stay on Wahapedia, so its download stays.
  What changes is that unit data comes from BSData first.

## Recommendation

Go ahead, in stages, each shippable on its own:

1. **Download and index**: the repository's zip, checked by its last commit (GitHub API) once a day
   like the Wahapedia check; unpacked under `wahapedia_data/`'s sibling `bsdata_data/`; files read
   on demand, an index of units per catalogue cached. Settings: which source is used, to compare.
2. **Units from BSData**: a `data/bsdata.py` reader building the same `Unit`, `ModelProfile` and
   `Weapon` objects, per list entry (each model line its own profile and weapons). `link_datasheets`
   tries BSData by exact names first, then Wahapedia as today. Base sizes from Wahapedia where BSData
   has none. Tests on fixture files cut from the real ones.
3. **Rules from BSData**: abilities, enhancements, detachment rules, Leader and Support (Wahapedia's
   leader table as a fallback where the text isn't read). Stratagems still from Wahapedia, by detachment name.
4. **Options' modifiers**: apply those that only test selections (Relic Shield, wargear, detachment).

Stages 1 and 2 are where the linking problems go away; 3 and 4 add what Wahapedia can't give.

## Not studied

- NR's richer exports (its JSON or BattleScribe roster files) carry each selection's profiles with the
  modifiers already applied, so they would need no data at all for units. The launcher asks for the
  text export today. A sample export would tell whether it's worth offering as well.
- Detachment points, damaged profiles and transport capacity in BSData: present in the data, not compared.
