"""Monte Carlo attack simulation (numpy).

attacks -> hit -> wound -> save -> damage -> feel no pain, then damage is allocated model by model.

Rules applied (11th edition):
- Benefit of Cover worsens the Ballistic Skill of ranged attacks by 1 (2+ becomes 3+);
  it does nothing against [IGNORES COVER], [TORRENT] or melee attacks.
- A unit uses the Toughness held by the majority of its non-CHARACTER models (ties: higher value).
- The defender chooses the allocation order (Target.model_order). A [PRECISION] attack goes to one
  chosen CHARACTER model first (Target.precision_pos), if it is still alive.
- Save rolls for one weapon's attacks are rolled together and resolved from the lowest result to
  the highest, each against the model currently first in the allocation order.
- Normal damage is resolved before mortal wounds ([DEVASTATING WOUNDS]); mortal wounds spill over,
  excess normal damage is lost.
- A qualified ability such as "LETHAL HITS: non-MONSTER/VEHICLE" only applies when the target matches.
- A [PSYCHIC] weapon ignores every malus to its hit rolls and its Skill (e.g. -1 to be hit, cover);
  bonuses still apply.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from command_center.core.dice import Dice
from command_center.core.keywords import target_matches
from command_center.core.models import Target, WeaponLoad
from command_center.core.modifiers import Modifiers


def wound_target(S: int, T: int) -> int:
    if S >= 2 * T:
        return 2
    if S > T:
        return 3
    if S == T:
        return 4
    if 2 * S <= T:
        return 6
    return 5


def _clamp(m: int) -> int:
    return max(-1, min(1, m))


def _s_vs_t_wound_mod(S: int, T: int, mods: Modifiers) -> int:
    """Wound roll modifiers that depend on Strength vs Toughness (both after modifiers)."""
    m = 0
    if (mods.wound_plus_if_weaker == "lt" and S < T) or (mods.wound_plus_if_weaker == "le" and S <= T):
        m += 1
    if (mods.wound_minus_if_stronger == "gt" and S > T) or (mods.wound_minus_if_stronger == "ge" and S >= T):
        m -= 1
    return m


def _fnp_applies(against: str, psychic: bool, mortal: bool) -> bool:
    """Whether a Feel No Pain restricted to `against` (all | psychic | mortal | psychic_mortal) is used."""
    if against == "psychic":
        return psychic
    if against == "mortal":
        return mortal
    if against == "psychic_mortal":
        return psychic or mortal
    return True


def _roll_d6(rng, n: int, reroll: str, success) -> np.ndarray:
    r = rng.integers(1, 7, size=n)
    if reroll == "fails":
        mask = ~success(r)
    elif reroll == "ones":
        mask = r == 1
    elif reroll == "ones_twos":
        mask = (r <= 2) & ~success(r)
    else:
        return r
    return np.where(mask, rng.integers(1, 7, size=n), r)


@dataclass
class WeaponStats:
    name: str
    source: str
    count: int
    tags: list[str]
    attacks: float
    hits: float
    wounds: float
    unsaved: float     # failed saves + devastating wounds, against the first allocation group
    damage: float      # damage actually dealt after allocation/overkill


@dataclass
class SimResult:
    target: Target
    trials: int
    damage: np.ndarray        # per trial, damage actually dealt
    slain: np.ndarray         # per trial, models destroyed
    chars_slain: np.ndarray   # per trial, CHARACTER models destroyed
    weapons: list[WeaponStats]
    mod_tags: list[str]

    @property
    def total_wounds(self) -> int:
        return sum(g.count * g.profile.W for g in self.target.groups)

    def stats(self) -> dict:
        d, s, n = self.damage, self.slain, len(self.damage)
        sd = float(d.std(ddof=1)) if n > 1 else 0.0
        half = 1.96 * sd / math.sqrt(n)
        pct = lambda a: dict(zip(("p5", "p25", "p50", "p75", "p95"), np.percentile(a, [5, 25, 50, 75, 95])))
        n_models = self.target.models
        n_chars = sum(g.count for g in self.target.groups if g.character)
        return {
            "damage_mean": float(d.mean()), "damage_sd": sd,
            "damage_ci95": (float(d.mean()) - half, float(d.mean()) + half),
            "damage_pct": pct(d),
            "slain_mean": float(s.mean()), "slain_sd": float(s.std(ddof=1)) if n > 1 else 0.0,
            "slain_pct": pct(s),
            "p_wipe": float((s >= n_models).mean()),
            "p_slain_at_least": [float((s >= k).mean()) for k in range(n_models + 1)],
            "slain_hist": np.bincount(s, minlength=n_models + 1)[: n_models + 1] / n,
            "p_character_slain": float((self.chars_slain > 0).mean()) if n_chars else None,
        }

    def report(self) -> str:
        st = self.stats()
        lo, hi = st["damage_ci95"]
        pc, sp = st["damage_pct"], st["slain_pct"]
        lines = [f"-> {self.target.name} ({self.target.models} models, {self.total_wounds} wounds)"]
        for w in self.weapons:
            lines.append(f"   {w.count}x {w.name:<32} att {w.attacks:5.1f}  hit {w.hits:5.1f}  "
                         f"wnd {w.wounds:5.1f}  unsv {w.unsaved:5.1f}  dmg {w.damage:5.1f}"
                         + (f"  <{', '.join(w.tags)}>" if w.tags else ""))
        lines += [
            f"  damage  mean {st['damage_mean']:.2f} (95% CI {lo:.2f}-{hi:.2f})  sd {st['damage_sd']:.2f}   "
            f"p5 {pc['p5']:.0f} | median {pc['p50']:.0f} | p95 {pc['p95']:.0f}",
            f"  slain   mean {st['slain_mean']:.2f}  sd {st['slain_sd']:.2f}   90% band "
            f"{sp['p5']:.0f}-{sp['p95']:.0f}   wipe {st['p_wipe']:.1%}",
            "  P(>=k slain): " + "  ".join(f"{k}:{p:.0%}" for k, p in enumerate(st["p_slain_at_least"])
                                           if k and p >= 0.005),
        ]
        if st["p_character_slain"] is not None:
            lines.append(f"  P(character slain): {st['p_character_slain']:.1%}")
        if self.mod_tags:
            lines.append(f"  modifiers: {', '.join(self.mod_tags)}")
        return "\n".join(lines)


def simulate(loads: list[WeaponLoad], target: Target, mods: Modifiers,
             trials: int = 20_000, seed: int | None = None) -> SimResult:
    rng = np.random.default_rng(seed)
    groups = target.groups
    T = max(1, target.toughness + mods.toughness_mod)
    tkw = target.keywords
    n_target = target.models
    G = len(groups)

    # stream of damage entries, later allocated trial by trial
    e_trial, e_dmg, e_mortal, e_prec, e_weapon, e_unsaved, e_sr = [], [], [], [], [], [], []
    stats = []

    for wi, ld in enumerate(loads):
        w, kw = ld.weapon, ld.weapon.keywords
        # ---------- attacks ----------
        attacks = np.zeros(trials, dtype=np.int64)
        bonus_dice = (kw.blast + kw.cleave) * (n_target // 5)
        for _ in range(ld.count):
            a = w.A.roll(rng, trials)
            if mods.extra_attacks:
                a = np.maximum(1, a + mods.extra_attacks.roll(rng, trials))   # Attacks can't drop below 1
            attacks += a + bonus_dice
            if mods.half_range and kw.rapid_fire:
                attacks += kw.rapid_fire.roll(rng, trials)
        idx = np.repeat(np.arange(trials), attacks)

        # ---------- hits ----------
        lethal = (kw.lethal_hits is not None and target_matches(kw.lethal_hits, tkw)) or mods.add_lethal_hits
        own = kw.sustained_hits[0] if kw.sustained_hits and target_matches(kw.sustained_hits[1], tkw) else Dice()
        sustained = max(own, mods.add_sustained_hits, key=lambda d: d.mean)   # never both: keep the bigger
        if kw.torrent or w.skill is None:
            crit = np.zeros(idx.size, bool)
            normal_hit = np.ones(idx.size, bool)
        else:
            indirect = kw.indirect_fire and mods.not_visible
            skill = w.skill
            if not w.melee:
                if (mods.cover or indirect) and not kw.ignores_cover and not kw.psychic:
                    skill += 1                  # Benefit of Cover: worsen BS by 1
                if mods.plunging_fire:
                    skill -= 1                  # Plunging Fire: improve BS by 1
                skill = max(2, skill)           # a characteristic can't be better than 2+
            hit_mods = [mods.hit_mod, mods.to_be_hit_mod, 1 if kw.heavy and mods.stationary else 0]
            if kw.psychic:
                hit_mods = [max(0, m) for m in hit_mods]     # [PSYCHIC]: maluses are ignored
            need = skill - _clamp(sum(hit_mods))
            crit_on = mods.crit_hit_on
            if kw.conversion and mods.beyond_12:
                crit_on = min(crit_on, 4)

            if indirect:
                # Indirect Fire at a non-visible target: fixed, unmodifiable hit rolls, no re-rolls.
                # Unspotted: unmodified 1-5 fail (only 6s hit). Spotted: 4+.
                fixed = 4 if mods.spotted else 6

                def hit_ok(r, fixed=fixed):
                    return r >= fixed
                crit_on = max(crit_on, fixed)
            else:
                def hit_ok(r, need=need, crit_on=crit_on):
                    return (r >= crit_on) | ((r != 1) & (r >= need))
            r = _roll_d6(rng, idx.size, "none" if indirect else mods.reroll_hits, hit_ok)
            crit = r >= crit_on
            normal_hit = hit_ok(r) & ~crit
        auto_wound_idx = idx[crit] if lethal else idx[:0]
        roll_idx = idx[normal_hit | (crit & (not lethal))]
        if sustained:
            c_idx = idx[crit]
            roll_idx = np.concatenate([roll_idx, np.repeat(c_idx, sustained.roll(rng, c_idx.size))])

        # ---------- wounds ----------
        S = max(1, w.S + mods.extra_strength)
        wmod = _clamp(mods.wound_mod + (1 if kw.lance and mods.charged else 0) + _s_vs_t_wound_mod(S, T, mods))
        need_w = wound_target(S, T) - wmod
        crit_w = mods.crit_wound_on
        for cond, v in kw.anti:
            if target_matches(cond, tkw):
                crit_w = min(crit_w, v)

        def wound_ok(r):
            return (r >= crit_w) | ((r != 1) & (r >= need_w))
        rr = "fails" if kw.twin_linked else mods.reroll_wounds
        rw = _roll_d6(rng, roll_idx.size, rr, wound_ok)
        dev = (kw.devastating_wounds is not None and target_matches(kw.devastating_wounds, tkw)) \
            or mods.add_devastating_wounds
        crit_wound = (rw >= crit_w) & dev
        normal_idx = np.concatenate([roll_idx[wound_ok(rw) & ~crit_wound], auto_wound_idx])
        dev_idx = roll_idx[crit_wound]

        # ---------- damage per wound ----------
        fnp_norm = _fnp_applies(mods.fnp_against, kw.psychic, mortal=False)
        fnp_dev = _fnp_applies(mods.fnp_against, kw.psychic, mortal=True)

        def dmg(k, fnp):
            d = w.D.roll(rng, k) + (kw.melta if mods.half_range else 0)
            if mods.extra_damage:
                d = d + mods.extra_damage.roll(rng, k)
            if mods.halve_damage:
                d = (d + 1) // 2
            d = np.maximum(1, d - mods.damage_reduction)
            if mods.feel_no_pain and fnp and k:
                owner = np.repeat(np.arange(k), d)
                ignored = rng.integers(1, 7, size=owner.size) >= mods.feel_no_pain
                d = d - np.bincount(owner, weights=ignored, minlength=k).astype(np.int64)
            return d

        # ---------- saves, one result per allocation group ----------
        ap = max(0, w.AP + mods.extra_ap + mods.ap_mod)
        sr = rng.integers(1, 7, size=normal_idx.size)
        unsaved = np.empty((normal_idx.size, G), bool)
        for gi, g in enumerate(groups):
            p = g.profile
            sv = max(2, p.Sv - mods.save_char_mod)
            armour_ok = (sr != 1) & (sr - ap + min(1, mods.save_mod) >= sv)
            inv = mods.invuln_override or p.inv
            inv_ok = (sr >= inv) if inv else np.zeros(sr.size, bool)
            unsaved[:, gi] = ~(armour_ok | inv_ok)

        n_norm, n_dev = normal_idx.size, dev_idx.size
        e_trial += [normal_idx, dev_idx]
        e_dmg += [dmg(n_norm, fnp_norm), dmg(n_dev, fnp_dev)]
        e_mortal += [np.zeros(n_norm, bool), np.ones(n_dev, bool)]
        e_prec += [np.full(n_norm + n_dev, kw.precision or mods.add_precision)]
        e_weapon += [np.full(n_norm + n_dev, wi)]
        e_unsaved += [unsaved, np.ones((n_dev, G), bool)]
        e_sr += [sr, np.zeros(n_dev, np.int64)]
        stats.append(WeaponStats(
            w.name, ld.source, ld.count, kw.tags(),
            attacks=attacks.sum() / trials,
            hits=(roll_idx.size + auto_wound_idx.size) / trials,
            wounds=(n_norm + n_dev) / trials,
            unsaved=(unsaved[:, target.order()[0]].sum() + n_dev) / trials if G else 0.0,
            damage=0.0,
        ))

    damage, slain, chars, per_weapon = _allocate(
        trials, target, loads,
        np.concatenate(e_trial) if e_trial else np.zeros(0, np.int64),
        np.concatenate(e_dmg) if e_dmg else np.zeros(0, np.int64),
        np.concatenate(e_mortal) if e_mortal else np.zeros(0, bool),
        np.concatenate(e_prec) if e_prec else np.zeros(0, bool),
        np.concatenate(e_weapon) if e_weapon else np.zeros(0, np.int64),
        np.concatenate(e_unsaved) if e_unsaved else np.zeros((0, G), bool),
        np.concatenate(e_sr) if e_sr else np.zeros(0, np.int64),
    )
    for ws, dealt in zip(stats, per_weapon):
        ws.damage = dealt / trials
    return SimResult(target, trials, damage, slain, chars, stats, mods.tags())


def _allocate(trials, target, loads, trial, dmg, mortal, prec, weapon, unsaved, save_roll):
    """Resolve damage model by model, per trial, in weapon order.

    Within one weapon's attacks, save rolls are resolved from lowest to highest result against
    the current allocation group, then mortal wounds (e.g. from [DEVASTATING WOUNDS]) are applied."""
    groups = target.groups
    n_w = len(loads)
    damage = np.zeros(trials, np.int64)
    slain = np.zeros(trials, np.int64)
    chars = np.zeros(trials, np.int64)
    per_weapon = [0] * n_w
    if trial.size == 0:
        return damage, slain, chars, per_weapon

    # model list in the defender's allocation order
    m_group = target.order()
    m_w = [groups[gi].profile.W for gi in m_group]
    m_char = [groups[gi].character for gi in m_group]
    n_models = len(m_w)
    pp = target.precision_pos
    prec_model = pp if pp is not None and 0 <= pp < n_models and m_char[pp] else None

    # order entries by trial, keeping weapon order and (normal before mortal) within a weapon
    # per trial: weapon by weapon; within a weapon, normal damage first, resolved from the lowest
    # save roll to the highest (11th ed. Inflict Damage), then that weapon's mortal wounds
    order = np.lexsort((save_roll, mortal, weapon, trial))
    trial, dmg, mortal, prec, weapon = (a[order].tolist() for a in (trial, dmg, mortal, prec, weapon))
    unsaved = unsaved[order].tolist()
    starts = np.searchsorted(np.asarray(trial), np.arange(trials + 1)).tolist()

    for t in range(trials):
        a, b = starts[t], starts[t + 1]
        if a == b:
            continue
        rem = m_w[:]
        alive = n_models
        cur = 0                      # first alive model in allocation order
        dealt = killed_chars = 0
        for e in range(a, b):
            if alive == 0:
                break
            d = dmg[e]
            if d <= 0:
                continue
            if mortal[e]:
                while d > 0 and alive:
                    while rem[cur] <= 0:
                        cur += 1
                    take = d if d < rem[cur] else rem[cur]
                    rem[cur] -= take
                    d -= take
                    dealt += take
                    per_weapon[weapon[e]] += take
                    if rem[cur] <= 0:
                        alive -= 1
                        killed_chars += m_char[cur]
                continue
            while rem[cur] <= 0:
                cur += 1
            tgt = cur
            if prec[e] and prec_model is not None and rem[prec_model] > 0:
                tgt = prec_model
            if not unsaved[e][m_group[tgt]]:
                continue
            take = d if d < rem[tgt] else rem[tgt]
            rem[tgt] -= take
            dealt += take
            per_weapon[weapon[e]] += take
            if rem[tgt] <= 0:
                alive -= 1
                killed_chars += m_char[tgt]
        damage[t] = dealt
        slain[t] = n_models - alive
        chars[t] = killed_chars
    return damage, slain, chars, per_weapon
