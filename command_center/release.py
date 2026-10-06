"""The packaged app's own updates (no UI here: see command_center.ui.appupdate).

The app built by .github/workflows/release.yml carries the tag it was built from (version.txt). Once a
day it asks GitHub for the latest release; when that one is newer, its zip is downloaded and unpacked
aside, and a small script takes over once the app has closed: it replaces the .exe and its _internal
folder, then starts the app again. Lists, data and saved work, next to the .exe, are not touched.

From the source there is no version: nothing is checked (git pull is the update)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from command_center import config

LATEST_URL = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
USER_AGENT = "CommandCenter40K (app update check)"
MAX_AGE_HOURS = 24                # GitHub is asked again once the last check is older than this
TIMEOUT = 5                       # seconds, for the check at start-up; the download takes what it takes
BUNDLE_DIR = "_internal"          # PyInstaller's folder next to the .exe: everything that ships with the app


def current_version() -> str:
    """The tag the running app was built from; "" from the source."""
    if not config.FROZEN:
        return ""
    try:
        return (config.BUNDLE_ROOT / "version.txt").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return ""


def version_key(tag: str) -> tuple[int, ...] | None:
    """"v1.2.3" -> (1, 2, 3); None for anything that isn't a version (a build from a branch)."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (tag or "").strip())
    return tuple(int(n) for n in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = version_key(latest), version_key(current)
    return bool(a and b and a > b)


def _state_path() -> Path:
    return config.USER_DATA_DIR / "app_update.json"


def is_due(max_age_hours: float = MAX_AGE_HOURS, now: datetime | None = None, path: Path | None = None) -> bool:
    try:
        last = datetime.fromisoformat(json.loads((path or _state_path()).read_text(encoding="utf-8"))["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return (now or datetime.now(timezone.utc)) - last > timedelta(hours=max_age_hours)


def mark_checked(when: datetime | None = None, path: Path | None = None) -> None:
    path = path or _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": (when or datetime.now(timezone.utc)).isoformat()}), encoding="utf-8")


def latest_release(timeout: float = TIMEOUT) -> tuple[str, str] | None:
    """(tag, address of its zip) of the latest release; None when it has no zip of the app."""
    req = urllib.request.Request(LATEST_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    for asset in data.get("assets", []):
        if asset.get("name") == config.RELEASE_ASSET:
            return data.get("tag_name", ""), asset["browser_download_url"]
    return None


def download(url: str, log=None) -> Path:
    """Download a release's zip and unpack it in a new temporary folder. Returns the folder of the new
    app (the one holding its .exe); it is inside the temporary folder that install() removes."""
    tmp = Path(tempfile.mkdtemp(prefix="cc40k-update-"))
    archive = tmp / config.RELEASE_ASSET
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(archive, "wb") as out:
        total, got = int(resp.headers.get("Content-Length") or 0), 0
        while chunk := resp.read(1 << 18):
            out.write(chunk)
            got += len(chunk)
            if log:
                log(f"Downloading: {got / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else ""))
    if log:
        log("Unpacking")
    with zipfile.ZipFile(archive) as z:
        z.extractall(tmp / "new")
    archive.unlink()
    for bundle in (tmp / "new").rglob(BUNDLE_DIR):
        if bundle.is_dir() and any(bundle.parent.glob("*.exe")):
            return bundle.parent
    raise FileNotFoundError(f"No app in {config.RELEASE_ASSET}")


def swap_script(new_dir: Path, app_dir: Path, exe_name: str, pid: int, tmp: Path) -> str:
    """The batch file that installs new_dir over app_dir once process `pid` is over, starts the app
    again and removes `tmp`. Only the .exe and its _internal folder are replaced."""
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)',
        f'robocopy "{new_dir / BUNDLE_DIR}" "{app_dir / BUNDLE_DIR}" /MIR /R:5 /W:1 >nul',
        "if errorlevel 8 goto run",                                   # the copy failed: keep the .exe there is
        f'copy /y "{new_dir / exe_name}" "{app_dir / exe_name}" >nul',
        ":run",
        f'start "" "{app_dir / exe_name}"',
        'cd /d "%TEMP%"',
        f'(goto) 2>nul & rmdir /s /q "{tmp}"',                        # the script removes itself with the rest
        ""])


def install(new_dir: Path, app_dir: Path | None = None, exe_name: str | None = None, pid: int | None = None) -> None:
    """Hand over to the script that installs the app unpacked by download(). The caller must then exit:
    the script waits for this process to be over."""
    app_dir = Path(app_dir or config.PROJECT_ROOT)
    exe_name = exe_name or Path(sys.executable).name
    if not (new_dir / exe_name).is_file() or not (new_dir / BUNDLE_DIR).is_dir():
        raise FileNotFoundError(f"{exe_name} is not in the downloaded app")
    tmp = next(p for p in new_dir.parents if p.name.startswith("cc40k-update-"))
    script = tmp / "install.bat"
    script.write_text(swap_script(new_dir, app_dir, exe_name, pid or os.getpid(), tmp), encoding="utf-8")
    # Not the packaged app's own environment (PyInstaller's variables): the app starts afresh.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(["cmd", "/c", str(script)], cwd=tempfile.gettempdir(), env=env, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
