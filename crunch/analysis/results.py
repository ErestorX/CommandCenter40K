"""Querying sweep results: metrics, filters, hidden data points and two-level aggregation.

Aggregation for an attacker/defender pair, in one phase:
  1. for each attacker test, combine the defender tests (def_mode);
  2. combine those values (att_mode).
"best"/"worst" keep the underlying test, so its spread (5th-95th percentile) can still be shown.

The total of a pair adds its Shooting and Fight values (each phase picks its own attacker test),
capped at what the defending unit has. The chance to destroy the unit is combined as "destroyed in
either phase" (1 - (1 - a)(1 - b)). Both treat the phases as separate: the Fight phase is not run
against the survivors of the Shooting phase, so totals are optimistic when the first phase does a lot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import prod
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
    cap: Callable[[TestRecord], float] | None = None    # most a pair's total can be (None: probability)


METRICS: dict[str, Metric] = {m.key: m for m in [
    Metric("dmg_mean", "Expected damage", lambda v: f"{v:.1f}", "dmg_p5", "dmg_p95", cap=lambda r: r.wounds),
    Metric("slain_mean", "Models slain", lambda v: f"{v:.1f}", "slain_p5", "slain_p95", cap=lambda r: r.models),
    Metric("frac_wounds", "Share of unit's wounds", lambda v: f"{v:.0%}", cap=lambda r: 1.0),
    Metric("p_wipe", "Chance to destroy the unit", lambda v: f"{v:.0%}"),
    Metric("pts_removed", "Points removed", lambda v: f"{v:.0f}", cap=lambda r: r.def_points),
    Metric("pts_per_100", "Points removed per 100 pts", lambda v: f"{v:.1f}",
           cap=lambda r: 100 * r.def_points / max(1, r.att_points)),
]}

TOTAL = "Total"
PHASE_VIEWS = {TOTAL: "Total (Shooting + Fight)", "Shooting": "Shooting", "Fight": "Fight"}
PHASE_ORDER = ("Shooting", "Fight")

ATT_MODES = {"best": "Best attacker test", "mean": "Average of attacker tests",
             "worst": "Worst attacker test"}
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
    parts: dict[str, "Agg"] = field(default_factory=dict)    # a total: phase -> that phase's value


def add_phases(metric: Metric, parts: dict[str, Agg]) -> Agg:
    """Total of one pair over its phases (see the module docstring)."""
    if len(parts) == 1:
        return next(iter(parts.values()))
    values = [a.value for a in parts.values()]
    records = [r for a in parts.values() for r in a.records]
    if metric.cap is None:
        v = 1 - prod(1 - x for x in values)
    else:
        v = min(sum(values), metric.cap(records[0]))
    return Agg(v, None, records, False, parts)


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
                  records: list[TestRecord] | None = None, phase: str = TOTAL) -> list[tuple[str, str, Agg]]:
        """[(phase, attacker test, value over defender tests)] for one pair, best first.
        phase: one phase, or TOTAL for the tests of every phase."""
        groups: dict[tuple[str, str], list[Agg]] = {}
        for r in (records if records is not None else self.visible()):
            if r.attacker == attacker and r.defender == defender and phase in (TOTAL, r.phase):
                groups.setdefault((r.phase, r.att_test), []).append(Agg(getattr(r, metric), r, [r]))
        out = [(ph, t, _combine(items, def_mode, same_scenario=True)) for (ph, t), items in groups.items()]
        return sorted(out, key=lambda x: -x[2].value)

    def pair(self, attacker: str, defender: str, metric: str, att_mode: str, def_mode: str,
             records: list[TestRecord] | None = None, phase: str = TOTAL) -> Agg | None:
        """Value of a pair in one phase, or its total over the phases (phase=TOTAL)."""
        if phase != TOTAL:
            sc = self.scenarios(attacker, defender, metric, def_mode, records, phase)
            return _combine([a for _, _, a in sc], att_mode) if sc else None
        parts = {ph: a for ph in PHASE_ORDER
                 if (a := self.pair(attacker, defender, metric, att_mode, def_mode, records, ph))}
        return add_phases(METRICS[metric], parts) if parts else None

    def by_pair(self, records: list[TestRecord] | None = None) -> dict[tuple[str, str], list[TestRecord]]:
        out: dict[tuple[str, str], list[TestRecord]] = {}
        for r in (records if records is not None else self.visible()):
            out.setdefault((r.attacker, r.defender), []).append(r)
        return out

    def matrix(self, metric: str, att_mode: str, def_mode: str, phase: str = TOTAL):
        vis = self.visible()
        atts = list(dict.fromkeys(r.attacker for r in vis))
        defs = list(dict.fromkeys(r.defender for r in vis))
        groups = self.by_pair(vis)
        cells = [[self.pair(a, d, metric, att_mode, def_mode, groups[(a, d)], phase) if (a, d) in groups else None
                  for d in defs] for a in atts]
        return atts, defs, cells
