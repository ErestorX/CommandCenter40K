"""Querying sweep results: metrics, filters, hidden data points and two-level aggregation.

Aggregation for an attacker/defender pair:
  1. for each attacker scenario (phase + attacker test), combine the defender tests (def_mode);
  2. combine those scenario values (att_mode).
"best"/"worst" keep the underlying test, so its spread (5th-95th percentile) can still be shown.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Callable

from crunch.analysis.sweep import TestRecord


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    fmt: Callable[[float], str]
    lo: str | None = None          # record field for the lower whisker
    hi: str | None = None


METRICS: dict[str, Metric] = {m.key: m for m in [
    Metric("dmg_mean", "Expected damage", lambda v: f"{v:.1f}", "dmg_p5", "dmg_p95"),
    Metric("slain_mean", "Models slain", lambda v: f"{v:.1f}", "slain_p5", "slain_p95"),
    Metric("frac_wounds", "Share of unit's wounds", lambda v: f"{v:.0%}"),
    Metric("p_wipe", "Chance to destroy the unit", lambda v: f"{v:.0%}"),
    Metric("pts_removed", "Points removed", lambda v: f"{v:.0f}"),
    Metric("pts_per_100", "Points removed per 100 pts", lambda v: f"{v:.1f}"),
]}

ATT_MODES = {"best": "Best attacker scenario", "mean": "Average of attacker scenarios",
             "worst": "Worst attacker scenario"}
DEF_MODES = {"mean": "Average of defender tests", "min": "Defender's best option",
             "max": "Defender's worst option"}

DIMS = {"attacker": "Attackers", "defender": "Defenders", "phase": "Phase",
        "att_test": "Attacker tests", "def_test": "Defender tests"}


@dataclass
class Agg:
    value: float
    record: TestRecord | None          # a test identifying the scenario (None when scenarios are mixed)
    records: list[TestRecord]          # every test that went into it
    exact: bool = True                 # value is exactly `record`'s (so its spread applies)


def _combine(items: list[Agg], mode: str, same_scenario: bool = False) -> Agg:
    records = [r for a in items for r in a.records]
    if mode in ("best", "max"):
        a = max(items, key=lambda a: a.value)
        return Agg(a.value, a.record, records, a.exact)
    if mode in ("worst", "min"):
        a = min(items, key=lambda a: a.value)
        return Agg(a.value, a.record, records, a.exact)
    if len(items) == 1:
        return items[0]
    # an average: keeps its scenario identity only if all items share it
    return Agg(fmean(a.value for a in items), items[0].record if same_scenario else None, records, False)


class ResultSet:
    def __init__(self, records: list[TestRecord]):
        self.records = [r for r in records if not r.error]
        self.errors = [r for r in records if r.error]
        self.hidden: set[int] = set()
        self.excluded: dict[str, set[str]] = {d: set() for d in DIMS}

    # ---- filtering -----------------------------------------------------------------
    def values(self, dim: str) -> list[str]:
        """Distinct values of a dimension, in first-seen order."""
        return list(dict.fromkeys(getattr(r, dim) for r in self.records))

    def passes_filters(self, r: TestRecord) -> bool:
        return all(getattr(r, d) not in ex for d, ex in self.excluded.items())

    def visible(self) -> list[TestRecord]:
        return [r for r in self.records if r.id not in self.hidden and self.passes_filters(r)]

    # ---- aggregation ------------------------------------------------------------------
    def scenarios(self, attacker: str, defender: str, metric: str, def_mode: str,
                  records: list[TestRecord] | None = None) -> list[tuple[str, str, Agg]]:
        """[(phase, attacker test, value over defender tests)] for one pair, best first."""
        groups: dict[tuple[str, str], list[Agg]] = {}
        for r in (records if records is not None else self.visible()):
            if r.attacker == attacker and r.defender == defender:
                groups.setdefault((r.phase, r.att_test), []).append(Agg(getattr(r, metric), r, [r]))
        out = [(ph, t, _combine(items, def_mode, same_scenario=True)) for (ph, t), items in groups.items()]
        return sorted(out, key=lambda x: -x[2].value)

    def pair(self, attacker: str, defender: str, metric: str, att_mode: str, def_mode: str,
             records: list[TestRecord] | None = None) -> Agg | None:
        sc = self.scenarios(attacker, defender, metric, def_mode, records)
        return _combine([a for _, _, a in sc], att_mode) if sc else None

    def by_pair(self, records: list[TestRecord] | None = None) -> dict[tuple[str, str], list[TestRecord]]:
        out: dict[tuple[str, str], list[TestRecord]] = {}
        for r in (records if records is not None else self.visible()):
            out.setdefault((r.attacker, r.defender), []).append(r)
        return out

    def matrix(self, metric: str, att_mode: str, def_mode: str):
        vis = self.visible()
        atts = list(dict.fromkeys(r.attacker for r in vis))
        defs = list(dict.fromkeys(r.defender for r in vis))
        groups = self.by_pair(vis)
        cells = [[self.pair(a, d, metric, att_mode, def_mode, groups.get((a, d), [])) if (a, d) in groups else None
                  for d in defs] for a in atts]
        return atts, defs, cells
