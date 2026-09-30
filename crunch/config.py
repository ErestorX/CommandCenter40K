"""Project-wide paths and constants. Change locations here, not in individual modules."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LISTS_DIR = PROJECT_ROOT / "lists"

EDITION = "wh40k11ed"
WAHAPEDIA_BASE_URL = "https://wahapedia.ru/{edition}/"
# Mission deck page (no CSV export): Force Dispositions, primary / secondary missions, deployments.
# Change the season here when a new deck is published.
MISSION_DECK_URL = "https://wahapedia.ru/{edition}/the-rules/mission-deck-2026-27/"

# Where fetch writes by default, followed by other places the data may already live.
DATA_ROOT = PROJECT_ROOT / "wahapedia_data"
DATA_ROOT_CANDIDATES = [DATA_ROOT, PROJECT_ROOT / "data"]

# Per-user state that isn't part of the code (saved test plans, ...). Git-ignored.
USER_DATA_DIR = PROJECT_ROOT / "user_data"

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
