"""Shared application state handed to every window/tool: loaded data plus user settings.

Tools should read data through the context rather than loading their own, so everything is loaded once
and new tools get it for free:
    ctx.armies   what lists are parsed and linked with: BSData first, completed by Wahapedia
    ctx.rules    rules text (abilities, detachments, stratagems...)
    ctx.wd       Wahapedia alone; ctx.bs BSData alone (None when its files aren't downloaded yet)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from command_center.analysis.army_plans import ArmyPlanStore
from command_center.analysis.plan import PlanStore
from command_center.data.armies import Armies
from command_center.data.bsdata import BSData
from command_center.data.missionbook import MissionBook
from command_center.data.rules import RulesBook
from command_center.data.wahapedia import Wahapedia
from command_center.deploy.estimates import EstimateStore
from command_center.deploy.games import GameStore


@dataclass
class Settings:
    trials: int = 20_000        # Monte Carlo trials per simulation


class AppContext:
    def __init__(self, data_dir: str | Path | None = None, settings: Settings | None = None,
                 bsdata_dir: str | Path | None = None):
        self.wd = Wahapedia(data_dir)          # raises FileNotFoundError if no data yet
        try:
            self.bs: BSData | None = BSData(bsdata_dir)
        except (FileNotFoundError, OSError):
            self.bs = None                     # not downloaded yet: Wahapedia alone, as before
        self.armies = Armies(self.wd, self.bs)
        self.settings = settings or Settings()
        self._rules: RulesBook | None = None
        self._missions: MissionBook | None = None
        self._army_plans: ArmyPlanStore | None = None
        self._estimates: EstimateStore | None = None
        self._games: GameStore | None = None
        self.test_plans_path: Path | None = None        # the Engagement Optimizer's tests, when not the user's file

    @property
    def rules(self) -> RulesBook:
        """Rules text tables, loaded on first use."""
        if self._rules is None:
            self._rules = RulesBook(self.wd, self.bs)
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

    @property
    def games(self) -> GameStore:
        """The games under way, one per pair of lists: what the Field Holomap and its Score Oracle keep."""
        if self._games is None:
            self._games = GameStore()
        return self._games

    # what is saved for a list file, by its name: to say what goes with it, then to let it go
    def list_data(self, list_name: str) -> dict[str, int]:
        """How much is saved for a list: its units' tests (Engagement Optimizer), the army plans and the
        games (Field Holomap) it is part of."""
        return {"tests": len(PlanStore(self.test_plans_path).of_list(list_name)),
                "army plans": len(self.army_plans.of_list(list_name)), "games": len(self.games.of_list(list_name))}

    def forget_list(self, list_name: str) -> dict[str, int]:
        """Remove what is saved for a list, and nothing of any other list. How much went, as list_data counts it."""
        return {"tests": PlanStore(self.test_plans_path).forget(list_name),
                "army plans": self.army_plans.forget(list_name), "games": self.games.forget(list_name)}
