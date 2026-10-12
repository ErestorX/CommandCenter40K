"""The folder of army lists: adding one from its pasted text, under a new name, and deleting one.

    problem = name_problem("My list", lists_dir) or text_problem(text, wd)      # None: fine
    path = save_list(text, "My list", lists_dir)
    if can_delete(path, lists_dir):
        delete_list(path, lists_dir)

The demonstration lists the app comes with (DEMO_LISTS) are not the user's: they are never deleted.
What was saved for a list (tests, army plans, games) is not in this folder: command_center.context
forgets it.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from command_center import config
from command_center.data.wahapedia import Wahapedia

FORBIDDEN = '\\/:*?"<>|'          # not allowed in a file name
DEMO_LISTS = ("DemOrks.txt", "TestMarines.txt")     # the demonstration lists, by file name


def in_folder(path: Path, lists_dir: Path) -> bool:
    """Is this file directly in the lists folder (and not one picked from elsewhere)?"""
    try:
        return Path(path).resolve().parent == Path(lists_dir).resolve()
    except OSError:
        return False


def is_demo(path: Path, lists_dir: Path) -> bool:
    """One of the demonstration lists the app comes with, in the lists folder."""
    return Path(path).name in DEMO_LISTS and in_folder(path, lists_dir)


def can_delete(path: Path, lists_dir: Path) -> bool:
    """A list of the user's own, in the lists folder: not a demonstration list, not a file from elsewhere."""
    path = Path(path)
    return path.suffix.lower() == ".txt" and path.is_file() and in_folder(path, lists_dir) and not is_demo(path, lists_dir)


def delete_list(path: Path, lists_dir: Path, remove=None) -> None:
    """Delete a list's file. ValueError for one that can't be (see can_delete). remove(path): how the file
    goes (to the system's bin, say); without it, it is deleted for good."""
    path = Path(path)
    if not can_delete(path, lists_dir):
        raise ValueError(f"{path.name} can't be deleted: it is not one of your lists in {lists_dir}")
    (remove or Path.unlink)(path)


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
