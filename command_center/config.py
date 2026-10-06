"""Project-wide paths and constants. Change locations here, not in individual modules."""
from __future__ import annotations

import sys
from pathlib import Path

# The packaged app (PyInstaller, see .github/workflows/release.yml): what the user owns (lists, data,
# saved work) lives next to the .exe, what ships with the app (fonts) inside the bundle.
FROZEN = getattr(sys, "frozen", False)
PROJECT_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) if FROZEN else PROJECT_ROOT
LISTS_DIR = PROJECT_ROOT / "lists"

EDITION = "wh40k11ed"
WAHAPEDIA_BASE_URL = "https://wahapedia.ru/{edition}/"
# Mission deck page (no CSV export): Force Dispositions, primary / secondary missions, deployments.
# Change the season here when a new deck is published.
MISSION_DECK_URL = "https://wahapedia.ru/{edition}/the-rules/mission-deck-2026-27/"
# Battlefield layouts (deployment zones, objectives, terrain per Force Disposition pairing), published
# as data by Rapid Ingress: https://rapidingress.com/40k-layout-reference
LAYOUTS_BASE_URL = "https://rapidingress.com/"

# Where fetch writes by default, followed by other places the data may already live.
DATA_ROOT = PROJECT_ROOT / "wahapedia_data"
DATA_ROOT_CANDIDATES = [DATA_ROOT, PROJECT_ROOT / "data"]

# Per-user state that isn't part of the code (saved test plans, ...). Git-ignored.
USER_DATA_DIR = PROJECT_ROOT / "user_data"
FONTS_DIR = BUNDLE_ROOT / "assets" / "fonts"     # the display font (see command_center.ui.theme)

ATTRIBUTION = "Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are (c) Games Workshop."
ATTRIBUTION_SHORT = "Powered by Wahapedia · rules and stats © Games Workshop"


def raw_dir(root: Path = DATA_ROOT, edition: str = EDITION) -> Path:
    """Folder holding the untouched Wahapedia CSVs."""
    return Path(root) / edition / "raw"


def find_data_dir(edition: str = EDITION) -> Path | None:
    """First raw-CSV folder that actually contains data, or None."""
    for root in DATA_ROOT_CANDIDATES:
        d = raw_dir(root, edition)
        if (d / "Datasheets.csv").exists():
            return d
    return None
