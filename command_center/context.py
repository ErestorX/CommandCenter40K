"""Shared application state handed to every window/tool: loaded data plus user settings.

Tools should read data through the context (ctx.wd, ctx.rules) rather than loading their own,
so everything is loaded once and new tools get it for free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from command_center.analysis.army_plans import ArmyPlanStore
from command_center.data.missionbook import MissionBook
from command_center.data.rules import RulesBook
from command_center.data.wahapedia import Wahapedia
from command_center.deploy.estimates import EstimateStore


@dataclass
class Settings:
    trials: int = 20_000        # Monte Carlo trials per simulation


class AppContext:
    def __init__(self, data_dir: str | Path | None = None, settings: Settings | None = None):
        self.wd = Wahapedia(data_dir)          # raises FileNotFoundError if no data yet
        self.settings = settings or Settings()
        self._rules: RulesBook | None = None
        self._missions: MissionBook | None = None
        self._army_plans: ArmyPlanStore | None = None
        self._estimates: EstimateStore | None = None

    @property
    def rules(self) -> RulesBook:
        """Rules text tables, loaded on first use."""
        if self._rules is None:
            self._rules = RulesBook(self.wd)
        return self._rules

    @property
    def missions(self) -> MissionBook:
        """Primary missions and battlefield layouts (written by `command_center fetch`), loaded on first use."""
        if self._missions is None:
            self._missions = MissionBook(Path(self.wd.data_dir).parent / "missions" / "json")
        return self._missions

    @property
    def army_plans(self) -> ArmyPlanStore:
        """The Engagement Optimizer's army plans, one per pair of lists, shared by every window (subscribe to
        hear about changes)."""
        if self._army_plans is None:
            self._army_plans = ArmyPlanStore()
        return self._army_plans

    @property
    def estimates(self) -> EstimateStore:
        """The Disposition Cogitator's saved Estimates, which the Score Oracle imports."""
        if self._estimates is None:
            self._estimates = EstimateStore()
        return self._estimates
