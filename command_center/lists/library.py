"""The folder of army lists: adding one from its pasted text, under a new name.

    problem = name_problem("My list", lists_dir) or text_problem(text, wd)      # None: fine
    path = save_list(text, "My list", lists_dir)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

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
