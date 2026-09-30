"""Shared application state handed to every window/tool: loaded data plus user settings.

Tools should read data through the context (ctx.wd, ctx.rules) rather than loading their own,
so everything is loaded once and new tools get it for free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from crunch.data.missionbook import MissionBook
from crunch.data.rules import RulesBook
from crunch.data.wahapedia import Wahapedia


@dataclass
class Settings:
    trials: int = 20_000        # Monte Carlo trials per simulation


class AppContext:
    def __init__(self, data_dir: str | Path | None = None, settings: Settings | None = None):
        self.wd = Wahapedia(data_dir)          # raises FileNotFoundError if no data yet
        self.settings = settings or Settings()
        self._rules: RulesBook | None = None
        self._missions: MissionBook | None = None

    @property
    def rules(self) -> RulesBook:
        """Rules text tables, loaded on first use."""
        if self._rules is None:
            self._rules = RulesBook(self.wd)
        return self._rules

    @property
    def missions(self) -> MissionBook:
        """Primary missions and battlefield layouts (written by `crunch fetch`), loaded on first use."""
        if self._missions is None:
            self._missions = MissionBook(Path(self.wd.data_dir).parent / "missions" / "json")
        return self._missions
