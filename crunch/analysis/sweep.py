"""Sweep: every selected attacker x every selected defender x each phase x each attacker scenario
x each defender scenario. Pure Python/numpy (no UI) so it can run in worker processes.

Scenarios of the same attacker/defender/phase share a random seed ("common random numbers"),
so differences between scenarios aren't drowned in dice noise.
"""
from __future__ import annotations

import os
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Callable

from crunch.analysis.variants import (ATTACKER_VARIANTS, DEFENDER_VARIANTS, PHASE_LABEL, combined)
from crunch.core.engine import simulate
from crunch.core.models import Target, WeaponLoad


@dataclass
class AttackerSpec:
    name: str                                  # "Kabalite Warriors + Archon"
    points: int
    loads: dict[str, list[WeaponLoad]]         # phase -> weapons firing in that phase
    variants: dict[str, list[str]]             # phase -> variant keys (only tested phases present)


@dataclass
class DefenderSpec:
    name: str
    points: int
    target: Target
    variants: list[str]


@dataclass
class TestCase:
    id: int
    attacker: str
    defender: str
    phase: str
    att_variant: str
    def_variant: str
    att_points: int
    def_points: int
    loads: list[WeaponLoad]
    target: Target
    seed: int


@dataclass
class TestRecord:
    """One finished test, flat and serialisable (CSV/JSON friendly)."""
    id: int
    attacker: str
    defender: str
    phase: str                 # "Shooting" / "Fight"
    att_test: str              # attacker scenario label
    def_test: str              # defender scenario label
    att_points: int
    def_points: int
    models: int
    wounds: int
    dmg_mean: float
    dmg_sd: float
    dmg_p5: float
    dmg_p95: float
    slain_mean: float
    slain_p5: float
    slain_p95: float
    p_wipe: float
    frac_wounds: float         # expected share of the unit's wounds removed
    pts_removed: float         # defender points x expected share of models slain
    pts_per_100: float         # points removed per 100 attacker points
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def build_cases(attackers: list[AttackerSpec], defenders: list[DefenderSpec]) -> list[TestCase]:
    cases: list[TestCase] = []
    for a in attackers:
        for d in defenders:
            for phase, keys in a.variants.items():
                loads = a.loads.get(phase) or []
                if not loads:
                    continue                 # nothing fires in this phase
                seed = zlib.crc32(f"{a.name}|{d.name}|{phase}".encode())
                for ak in keys:
                    av = ATTACKER_VARIANTS.get(ak)
                    if not av or phase not in av.phases:
                        continue
                    for dk in d.variants:
                        dv = DEFENDER_VARIANTS.get(dk)
                        if not dv or phase not in dv.phases:
                            continue
                        cases.append(TestCase(len(cases), a.name, d.name, phase, ak, dk,
                                              a.points, d.points, loads, d.target, seed))
    return cases


def run_case(case: TestCase, trials: int) -> TestRecord:
    """Run one test. Top-level so worker processes can import it."""
    av, dv = ATTACKER_VARIANTS[case.att_variant], DEFENDER_VARIANTS[case.def_variant]
    base = dict(id=case.id, attacker=case.attacker, defender=case.defender, phase=PHASE_LABEL[case.phase],
                att_test=av.label, def_test=dv.label, att_points=case.att_points, def_points=case.def_points,
                models=case.target.models, wounds=sum(g.count * g.profile.W for g in case.target.groups))
    try:
        r = simulate(case.loads, case.target, combined(av, dv), trials=trials, seed=case.seed)
    except Exception as e:  # noqa: BLE001 - one bad test must not stop the sweep
        return TestRecord(**base, dmg_mean=0, dmg_sd=0, dmg_p5=0, dmg_p95=0, slain_mean=0, slain_p5=0,
                          slain_p95=0, p_wipe=0, frac_wounds=0, pts_removed=0, pts_per_100=0, error=str(e))
    st = r.stats()
    models = max(1, case.target.models)
    pts_removed = case.def_points * st["slain_mean"] / models
    return TestRecord(
        **base,
        dmg_mean=st["damage_mean"], dmg_sd=st["damage_sd"],
        dmg_p5=float(st["damage_pct"]["p5"]), dmg_p95=float(st["damage_pct"]["p95"]),
        slain_mean=st["slain_mean"], slain_p5=float(st["slain_pct"]["p5"]), slain_p95=float(st["slain_pct"]["p95"]),
        p_wipe=st["p_wipe"], frac_wounds=st["damage_mean"] / max(1, base["wounds"]),
        pts_removed=pts_removed, pts_per_100=100 * pts_removed / max(1, case.att_points),
    )


def _run_chunk(chunk: list[TestCase], trials: int) -> list[TestRecord]:
    return [run_case(c, trials) for c in chunk]


def default_workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def run_sweep(cases: list[TestCase], trials: int = 5_000, workers: int | None = None,
              progress: Callable[[int, int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> list[TestRecord]:
    """Run all cases; `progress(done, total)` is called as results arrive (from this thread)."""
    total = len(cases)
    workers = default_workers() if workers is None else workers
    done: list[TestRecord] = []
    if total == 0:
        return done
    if workers <= 1 or total < 8:
        for c in cases:
            if cancelled and cancelled():
                break
            done.append(run_case(c, trials))
            if progress:
                progress(len(done), total)
        return done
    size = max(1, min(16, total // (workers * 4)))
    chunks = [cases[i:i + size] for i in range(0, total, size)]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_chunk, ch, trials) for ch in chunks]
            for fut in as_completed(futures):
                if cancelled and cancelled():
                    for f in futures:
                        f.cancel()
                    break
                done.extend(fut.result())
                if progress:
                    progress(len(done), total)
    except (OSError, RuntimeError, ImportError) as e:      # no multiprocessing available: run here
        if done:
            raise
        return run_sweep(cases, trials, 1, progress, cancelled)
    done.sort(key=lambda r: r.id)
    return done


def to_csv(records: list[TestRecord], path) -> None:
    import csv
    rows = [r.as_dict() for r in records]
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
