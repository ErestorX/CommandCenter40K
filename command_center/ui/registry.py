"""Tool registry: every feature window registers itself here and appears in the launcher.

Add a tool
----------
1. Create a module or package under command_center/ui/tools/ (it is imported automatically).
2. Subclass ToolWindow (command_center.ui.toolwindow) and decorate a factory:

    @register_tool("gameplan", "Game plan", "Deployment and objectives for both lists", order=20)
    def open_gameplan(app, selection):
        return GamePlanWindow(app, selection)

The launcher shows one button per tool, in `order`, enabled once both army lists are chosen.
A tool that works without army lists registers with needs_armies=False: its button stands apart, on
the left, always enabled, and its factory may be handed None as the selection.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import tkinter as tk

    from command_center.lists import ArmyList
    from command_center.ui.app import App


@dataclass(frozen=True)
class Selection:
    """What the launcher hands to a tool."""
    attacker: "ArmyList"
    defender: "ArmyList"


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    description: str
    open: Callable[["App", "Selection | None"], "tk.Toplevel"]
    order: int = 100
    needs_armies: bool = True          # False: opens without army lists chosen


_TOOLS: dict[str, Tool] = {}


def register_tool(key: str, title: str, description: str = "", order: int = 100, needs_armies: bool = True):
    def deco(factory):
        _TOOLS[key] = Tool(key, title, description, factory, order, needs_armies)
        return factory
    return deco


def tools() -> list[Tool]:
    return sorted(_TOOLS.values(), key=lambda t: (t.order, t.title))


def get_tool(key: str) -> Tool:
    return _TOOLS[key]


def discover(package: str = "command_center.ui.tools") -> list[Tool]:
    """Import every module/package in `package` so their @register_tool decorators run."""
    pkg = importlib.import_module(package)
    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{package}.{info.name}")
    return tools()
