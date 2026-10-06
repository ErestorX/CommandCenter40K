"""Project-wide paths and constants. Change locations here, not in individual modules."""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "Command Center 40K"

# The packaged app (PyInstaller, see .github/workflows/release.yml): what ships with the app (fonts) is
# inside the bundle, what the user owns (lists, data, saved work) outside what an update replaces.
#   Windows: APP_DIR is the folder of the .exe, and the user's folders are in it.
#   macOS:   APP_DIR is the .app, which nothing is written in (macOS may run it from a read-only
#            place): the user's folders are in ~/Library/Application Support/<the app's name>.
FROZEN = getattr(sys, "frozen", False)
MACOS = sys.platform == "darwin"
if not FROZEN:
    APP_DIR = PROJECT_ROOT = BUNDLE_ROOT = Path(__file__).resolve().parent.parent
elif MACOS:
    APP_DIR = Path(sys.executable).resolve().parents[2]            # <name>.app/Contents/MacOS/<name>
    PROJECT_ROOT = Path.home() / "Library" / "Application Support" / APP_NAME
    BUNDLE_ROOT = Path(sys._MEIPASS)
else:
    APP_DIR = PROJECT_ROOT = Path(sys.executable).resolve().parent
    BUNDLE_ROOT = Path(sys._MEIPASS)
LISTS_DIR = PROJECT_ROOT / "lists"
BUNDLED_LISTS_DIR = BUNDLE_ROOT / "lists"        # macOS app: the lists it comes with, copied to LISTS_DIR once

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
# The work saved for the demonstration lists (lists/), copied to USER_DATA_DIR at the first start.
DEMO_USER_DATA_DIR = BUNDLE_ROOT / "assets" / "demo" / "user_data"
FONTS_DIR = BUNDLE_ROOT / "assets" / "fonts"     # the display font (see command_center.ui.theme)

# Where the packaged app looks for its own updates (command_center.release): the repository's latest
# release, and the zip attached to it by .github/workflows/release.yml.
GITHUB_REPO = "ErestorX/CommandCenter40K"
RELEASE_ASSET = "CommandCenter40K-macos.zip" if MACOS else "CommandCenter40K-windows.zip"

# The app's icon, made from skull_icon.png: icon.ico (Windows), icon.icns (the macOS .app), icon.png (windows elsewhere)
ICON_DIR = BUNDLE_ROOT / "assets" / "icon"

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
