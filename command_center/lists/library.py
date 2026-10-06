"""The folder of army lists: adding one from its pasted text, under a new name.

    problem = name_problem("My list", lists_dir) or text_problem(text, wd)      # None: fine
    path = save_list(text, "My list", lists_dir)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from command_center import config
from command_center.data.wahapedia import Wahapedia

FORBIDDEN = '\\/:*?"<>|'          # not allowed in a file name


def clean_name(name: str) -> str:
    """A list's name as typed: trimmed, without a ".txt" the user may have added."""
    name = " ".join(name.split())
    return name[:-4].rstrip() if name.lower().endswith(".txt") else name


def name_problem(name: str, lists_dir: Path) -> str | None:
    """What is wrong with a name for a new list (None: nothing). It has to be new: a list is never
    saved over another one."""
    name = clean_name(name)
    if not name:
        return "Give the list a name."
    bad = sorted(set(name) & set(FORBIDDEN))
    if bad or name.endswith(".") or any(ord(ch) < 32 for ch in name):
        return "A name can't contain  " + " ".join(bad or ["a final dot or control characters"])
    taken = {p.stem.lower() for p in Path(lists_dir).glob("*.txt")} if Path(lists_dir).exists() else set()
    if name.lower() in taken:
        return f'There is already a list named "{name}": give it a new name.'
    return None


def text_problem(text: str, wd: Wahapedia) -> str | None:
    """What is wrong with a pasted list (None: nothing): empty, not a format the app reads, or without units."""
    from command_center.lists import parse_list
    if not text.strip():
        return "Paste the list's text first."
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pasted.txt"
            path.write_text(text, encoding="utf-8")
            army = parse_list(path, wd)
    except Exception as e:  # noqa: BLE001 - whatever the parser trips on, the user is told
        return f"This doesn't read as a NewRecruit text export ({e})."
    if not army.units:
        return "No unit found in this text: is it NewRecruit's text export, in the NR format?"
    return None


def install_folder(source: Path, target: Path) -> bool:
    """Copy a folder the app comes with to its place among the user's, if it isn't there yet. Nothing
    once it is there: what is in it is the user's. True when copied."""
    source, target = Path(source), Path(target)
    if target.exists() or not source.is_dir():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    except OSError:                # nothing to start with: lists can still be added from the launcher
        return False
    return True


def install_demo() -> None:
    """First start: put in place what the app comes with to try it out. The demonstration lists, for an
    app that carries them inside itself (macOS), and the work saved for them (tests, army plan,
    Estimates: assets/demo/user_data), for as long as the user has no saved work of their own."""
    install_folder(config.BUNDLED_LISTS_DIR, config.LISTS_DIR)
    install_folder(config.DEMO_USER_DATA_DIR, config.USER_DATA_DIR)


def save_list(text: str, name: str, lists_dir: Path) -> Path:
    """Save a list's text as <lists_dir>/<name>.txt. ValueError if the name isn't a new, valid one."""
    problem = name_problem(name, lists_dir)
    if problem:
        raise ValueError(problem)
    lists_dir = Path(lists_dir)
    lists_dir.mkdir(parents=True, exist_ok=True)
    path = lists_dir / f"{clean_name(name)}.txt"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path
