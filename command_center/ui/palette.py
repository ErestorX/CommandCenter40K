"""The colours and font names of the app's look, apart from any toolkit: the tkinter front end
(command_center.ui.theme) and the Qt one (command_center.qt.theme) both draw from here."""
from __future__ import annotations

C = {
    "bg": "#0b0b0d",            # windows
    "panel": "#15151a",         # panels on a window
    "field": "#0e0e11",         # what holds content or is typed in: lists, tables, text, entries, cells
    "raised": "#22222a",        # buttons, table headings, a cell with a value
    "hover": "#2e2e38",
    "ink": "#e9e7e2", "muted": "#908d87", "dim": "#5c5a56",        # text; secondary; switched off
    "line": "#3b3b44", "grid": "#25252c",                           # borders; faint rules and tints
    "accent": "#d5352c",        # the red of the accent buttons
    "select": "#5a1d19",        # a selected row
    "att": "#e2554e", "def": "#6aa5ea",
    "bar": "#d5352c", "bar2": "#5e2623",
    "good": "#6fcf73", "warn": "#f0a030", "bad": "#5a1f1f",        # a win; VP lost, overkill; an invalid entry
}

DISPLAY_FAMILY = "Caliban Angelus"
BODY_IN_DISPLAY_FONT = False    # True: every text in the display font, numbers included

# Force Dispositions' colour code: ink (text), tint (a badge's background)
DISPOSITION_COLORS = {
    "take and hold": ("#6fcf73", "#17361a"),        # green
    "purge the foe": ("#f0625c", "#471715"),        # red
    "disruption": ("#8aa2f7", "#18214f"),           # deep blue
    "reconnaissance": ("#4fd1c5", "#0f3a38"),       # teal
    "priority assets": ("#f2cc4d", "#43360b"),      # yellow
}

# how hard a matchup is, by the group of its Estimate (command_center.deploy.estimates.difficulty_groups)
DIFFICULTY_COLORS = ("#c0392b", "#e67e22", "#f1c40f", "#8bc34a", "#2e7d32")        # the hardest group first
NO_ESTIMATE = C["field"]         # an empty circle: on the dark theme, an unfilled one


def disposition_colors(name: str) -> tuple[str, str]:
    """(ink, tint) of a Force Disposition; muted grey for one without a colour."""
    return DISPOSITION_COLORS.get(" ".join((name or "").lower().split()), (C["muted"], C["grid"]))
