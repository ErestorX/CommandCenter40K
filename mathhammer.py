#!/usr/bin/env python3
"""
mathhammer.py - Warhammer 40,000 attack simulator on Wahapedia's CSV export.

Powered by Wahapedia (https://wahapedia.ru). Rules, names and stats are (c) Games Workshop.

Usage
-----
    python fetch_wahapedia.py                                  # get the data first
    python mathhammer.py show --unit "Intercessor Squad"
    python mathhammer.py fight --attacker "Kabalite Warriors" --attacker-models 10 \
        --defender "Custodian Guard" --defender-models 5 --mod reroll_hits=ones --mod cover
    python app.py                                              # the graphical front end

Engine
------
Vectorised Monte Carlo (numpy) over the attack sequence of every selected weapon:
attacks -> hit -> wound -> save -> damage -> feel no pain, then damage is allocated
model by model (non-CHARACTER models first, CHARACTERs last, [PRECISION] picks a
CHARACTER first). Each model uses its own save; overkill from normal damage is lost,
mortal wounds from [DEVASTATING WOUNDS] spill over and are resolved after that weapon's
normal damage.

Rules applied (11th edition):
- Benefit of Cover worsens the Ballistic Skill of ranged attacks by 1 (2+ becomes 3+);
  it does nothing against [IGNORES COVER], [TORRENT] or melee attacks.
- A unit uses the Toughness held by the majority of its non-CHARACTER models
  (ties go to the higher value).
- The defender chooses the allocation order (Target.model_order). A [PRECISION] attack
  goes to one chosen CHARACTER model first (Target.precision_pos), if it is still alive.
- Save rolls for one weapon's attacks are rolled together and resolved from the lowest result
  to the highest, each against the model currently first in the allocation order.
- A qualified ability such as "LETHAL HITS: non-MONSTER/VEHICLE" only applies when the
  target matches the qualifier.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA_CANDIDATES = [
    HERE / "data" / "wh40k11ed" / "raw",
    HERE / "wahapedia_data" / "wh40k11ed" / "raw",
]


def find_data_dir() -> Path | None:
    for c in DATA_CANDIDATES:
        if (c / "Datasheets.csv").exists():
            return c
    return None


# =============================================================================
# DICE EXPRESSIONS  ("3", "D6", "2D3", "D6+1", "d6+3")
# =============================================================================
_DICE_RE = re.compile(r"^\s*(\d*)\s*[dD]\s*(\d+)\s*(?:\+\s*(\d+))?\s*$")


@dataclass(frozen=True)
class Dice:
    n: int = 0          # number of dice
    sides: int = 0      # die size
    flat: int = 0       # flat bonus

    @classmethod
    def parse(cls, text) -> "Dice":
        s = str(text if text is not None else "").strip()
        if s in ("", "-", "N/A", "n/a"):
            return cls()
        if s.isdigit():
            return cls(0, 0, int(s))
        m = _DICE_RE.match(s)
        if not m:
            raise ValueError(f"Unparseable dice expression: {text!r}")
        return cls(int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0))

    def __bool__(self) -> bool:
        return bool(self.n or self.flat)

    @property
    def mean(self) -> float:
        return self.n * (self.sides + 1) / 2 + self.flat

    def roll(self, rng: np.random.Generator, size) -> np.ndarray:
        out = np.full(size, self.flat, dtype=np.int64)
        for _ in range(self.n):
            out += rng.integers(1, self.sides + 1, size=size)
        return out

    def __str__(self) -> str:
        if not self.n:
            return str(self.flat)
        base = f"{'' if self.n == 1 else self.n}D{self.sides}"
        return base + (f"+{self.flat}" if self.flat else "")


# =============================================================================
# WEAPON KEYWORDS  (parsed from Datasheets_wargear.description)
# =============================================================================
def target_matches(cond: str, target_keywords: set[str]) -> bool:
    """cond "" = always; "infantry"; "monster/vehicle"; "non-monster/vehicle"."""
    if not cond:
        return True
    neg = cond.startswith("non-")
    wanted = {k.strip() for k in cond[4 if neg else 0:].split("/") if k.strip()}
    hit = bool(wanted & target_keywords)
    return not hit if neg else hit


@dataclass
class WeaponKeywords:
    # abilities that can carry a target qualifier store it as a string ("" = always, None = absent)
    lethal_hits: str | None = None
    devastating_wounds: str | None = None
    sustained_hits: tuple[Dice, str] | None = None
    anti: list[tuple[str, int]] = field(default_factory=list)   # [("infantry", 4)]
    torrent: bool = False
    twin_linked: bool = False
    heavy: bool = False
    lance: bool = False
    ignores_cover: bool = False
    precision: bool = False
    indirect_fire: bool = False
    conversion: bool = False
    assault: bool = False
    pistol: bool = False
    hazardous: bool = False
    extra_attacks: bool = False
    one_shot: bool = False
    psychic: bool = False
    close_quarters: bool = False
    blast: int = 0            # [BLAST] = 1, [BLAST X] = X
    cleave: int = 0
    melta: int = 0
    rapid_fire: Dice = field(default_factory=Dice)
    other: list[str] = field(default_factory=list)

    def tags(self) -> list[str]:
        t = []
        q = lambda c: f" ({c})" if c else ""
        if self.lethal_hits is not None:
            t.append("Lethal Hits" + q(self.lethal_hits))
        if self.sustained_hits:
            t.append(f"Sustained Hits {self.sustained_hits[0]}" + q(self.sustained_hits[1]))
        if self.devastating_wounds is not None:
            t.append("Dev Wounds" + q(self.devastating_wounds))
        t += [f"Anti-{k} {n}+" for k, n in self.anti]
        for name in ("torrent", "twin_linked", "heavy", "lance", "ignores_cover", "precision",
                     "indirect_fire", "conversion", "assault", "pistol", "hazardous",
                     "extra_attacks", "one_shot", "psychic", "close_quarters"):
            if getattr(self, name):
                t.append(name.replace("_", " ").title().replace("Twin Linked", "Twin-linked"))
        if self.blast:
            t.append("Blast" + (f" {self.blast}" if self.blast > 1 else ""))
        if self.cleave:
            t.append(f"Cleave {self.cleave}")
        if self.melta:
            t.append(f"Melta {self.melta}")
        if self.rapid_fire:
            t.append(f"Rapid Fire {self.rapid_fire}")
        return t + self.other


_BOOL_KW = {f.name for f in fields(WeaponKeywords) if f.type in ("bool", bool)}


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def parse_weapon_keywords(description: str) -> WeaponKeywords:
    kw = WeaponKeywords()
    for raw in re.split(r"[,\[\]]", strip_html(description).lower()):
        tok = raw.strip()
        if not tok:
            continue
        base, cond = tok, ""
        if ":" in tok:
            base, cond = (p.strip() for p in tok.split(":", 1))
        if m := re.match(r"anti-(.+?)\s+(\d)\+?$", base):
            kw.anti.append((m.group(1).strip(), int(m.group(2))))
        elif m := re.match(r"sustained hits\s+(\S+)$", base):
            kw.sustained_hits = (Dice.parse(m.group(1)), cond)
        elif base == "lethal hits":
            kw.lethal_hits = cond
        elif base == "devastating wounds":
            kw.devastating_wounds = cond
        elif m := re.match(r"rapid fire\s+(\S+)$", base):
            kw.rapid_fire = Dice.parse(m.group(1))
        elif m := re.match(r"melta\s+(\d+)$", base):
            kw.melta = int(m.group(1))
        elif m := re.match(r"blast(?:\s+(\d+))?$", base):
            kw.blast = int(m.group(1) or 1)
        elif m := re.match(r"cleave\s+(\d+)$", base):
            kw.cleave = int(m.group(1))
        else:
            name = base.replace("-", "_").replace(" ", "_")
            if name in _BOOL_KW:
                setattr(kw, name, True)
            else:
                kw.other.append(tok.title())
    return kw


# =============================================================================
# DATA MODEL
# =============================================================================
@dataclass
class Weapon:
    name: str
    type: str            # "Ranged" / "Melee"
    range: str
    A: Dice
    skill: int | None    # BS/WS target (None = N/A, e.g. Torrent)
    S: int
    AP: int              # stored as a positive number: AP-2 -> 2
    D: Dice
    keywords: WeaponKeywords

    @property
    def melee(self) -> bool:
        return self.type.lower() == "melee"

    @property
    def base_name(self) -> str:
        """'Plasma decimator – supercharge' -> 'Plasma decimator'."""
        return re.split(r"\s+[–—-]\s+", self.name, maxsplit=1)[0]

    def summary(self) -> str:
        sk = f"{self.skill}+" if self.skill else "N/A"
        tags = ", ".join(self.keywords.tags())
        return (f"{self.name} [{self.type}] A{self.A} {'WS' if self.melee else 'BS'}{sk} "
                f"S{self.S} AP-{self.AP} D{self.D}" + (f"  <{tags}>" if tags else ""))


@dataclass
class ModelProfile:
    name: str
    M: str
    T: int
    Sv: int
    inv: int | None
    W: int


@dataclass
class Unit:
    id: str
    name: str
    faction_id: str
    models: list[ModelProfile]
    weapons: list[Weapon]
    keywords: set[str]
    is_support: bool = False

    @property
    def is_character(self) -> bool:
        return "character" in self.keywords

    def profile(self, model_name: str = "") -> ModelProfile:
        n = norm(model_name)
        for m in self.models:
            if n and norm(m.name) in (n, n.rstrip("s")):
                return m
        return self.models[0]


def norm(s: str) -> str:
    """Loose name key: lowercase, letters/digits only, curly quotes folded."""
    s = html.unescape(s or "").lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]", "", s)


def _int(s, default=None):
    m = re.search(r"-?\d+", str(s or ""))
    return int(m.group()) if m else default


def read_table(data_dir: Path, name: str) -> list[dict]:
    path = Path(data_dir) / f"{name}.csv"
    if not path.exists():
        return []
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter="|")
    return [{k: (v or "").strip() for k, v in r.items() if k} for r in rows]


class Wahapedia:
    """Loads the raw CSVs once and builds Unit objects on demand."""

    def __init__(self, data_dir: str | Path | None = None):
        d = Path(data_dir) if data_dir else find_data_dir()
        if not d or not (d / "Datasheets.csv").exists():
            raise FileNotFoundError("No Wahapedia data found. Run fetch_wahapedia.py first.")
        self.data_dir = d
        self.datasheets = {r["id"]: r for r in read_table(d, "Datasheets")}
        self.factions = {r["id"]: r["name"] for r in read_table(d, "Factions")}
        self._models = self._by_ds(read_table(d, "Datasheets_models"))
        self._wargear = self._by_ds(read_table(d, "Datasheets_wargear"))
        self._keywords = self._by_ds(read_table(d, "Datasheets_keywords"))
        self.leads: dict[str, set[str]] = defaultdict(set)   # leader id -> bodyguard ids
        for r in read_table(d, "Datasheets_leader"):
            self.leads[r.get("leader_id", "")].add(r.get("attached_id", ""))
        lu = read_table(d, "Last_update")
        self.last_update = next(iter(lu[0].values()), "") if lu else ""
        self._cache: dict[str, Unit] = {}

    @staticmethod
    def _by_ds(rows):
        g = defaultdict(list)
        for r in rows:
            g[r.get("datasheet_id", "")].append(r)
        return g

    def faction_id(self, name: str) -> str | None:
        n = norm(name)
        for fid, fname in self.factions.items():
            if norm(fname) == n or norm(fid) == n:
                return fid
        return None

    def find(self, name: str, faction_id: str | None = None) -> str | None:
        """Datasheet id by name, preferring the given faction."""
        n = norm(name)
        hits = [i for i, r in self.datasheets.items() if norm(r["name"]) == n]
        if not hits:
            hits = [i for i, r in self.datasheets.items() if norm(r["name"]) in (n.rstrip("s"), n + "s")]
        if not hits:
            return None
        same = [i for i in hits if self.datasheets[i].get("faction_id") == faction_id]
        return (same or hits)[0]

    def unit(self, did: str) -> Unit:
        if did in self._cache:
            return self._cache[did]
        ds = self.datasheets[did]
        models = [
            ModelProfile(
                name=m.get("name") or ds["name"], M=m.get("M", ""),
                T=_int(m.get("T"), 4), Sv=_int(m.get("Sv"), 7),
                inv=_int(m.get("inv_sv")) if _int(m.get("inv_sv")) else None,
                W=_int(m.get("W"), 1),
            )
            for m in self._models.get(did, [])
        ] or [ModelProfile(ds["name"], "", 4, 7, None, 1)]
        weapons = []
        for w in self._wargear.get(did, []):
            skill = w.get("BS_WS", "")
            if not w.get("name") or w.get("A", "") in ("", "-") or (skill == "-" and "torrent" not in w.get("description", "").lower()):
                continue
            try:
                weapons.append(Weapon(
                    name=strip_html(w["name"]), type=w.get("type") or "Ranged", range=w.get("range") or "",
                    A=Dice.parse(w.get("A")),
                    skill=None if skill.upper() in ("N/A", "", "-") else _int(skill),
                    S=_int(w.get("S"), 4), AP=abs(_int(w.get("AP"), 0)), D=Dice.parse(w.get("D")),
                    keywords=parse_weapon_keywords(w.get("description", "")),
                ))
            except ValueError:
                continue
        kws = {k["keyword"].lower() for k in self._keywords.get(did, []) if k.get("keyword")}
        u = Unit(did, ds["name"], ds.get("faction_id", ""), models, weapons, kws,
                 ds.get("is_support", "").lower() == "true")
        self._cache[did] = u
        return u

    def unit_by_name(self, name: str, faction: str | None = None) -> Unit:
        did = self.find(name, self.faction_id(faction) if faction else None)
        if not did:
            raise KeyError(f"No datasheet matching {name!r}")
        return self.unit(did)

    def can_lead(self, leader_id: str, bodyguard_id: str) -> bool:
        return bodyguard_id in self.leads.get(leader_id, ())


# =============================================================================
# WHAT GETS SIMULATED
# =============================================================================
@dataclass
class WeaponLoad:
    weapon: Weapon
    count: int          # number of models/instances firing this weapon
    source: str = ""    # which unit it belongs to (for display)


@dataclass
class TargetGroup:
    profile: ModelProfile
    count: int
    character: bool = False
    label: str = ""


@dataclass
class Target:
    name: str
    groups: list[TargetGroup]
    keywords: set[str]
    model_order: list[int] | None = None   # group index of each model, in allocation order
    precision_pos: int | None = None       # position in model_order that [PRECISION] attacks go to first

    @property
    def models(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def toughness(self) -> int:
        """Toughness held by the majority of non-CHARACTER models (ties: the higher value)."""
        body = [g for g in self.groups if not g.character] or self.groups
        votes: dict[int, int] = {}
        for g in body:
            votes[g.profile.T] = votes.get(g.profile.T, 0) + g.count
        return max(votes, key=lambda t: (votes[t], t))

    def default_order(self) -> list[int]:
        """Non-CHARACTER models first, CHARACTERs last."""
        body = [i for i, g in enumerate(self.groups) if not g.character for _ in range(g.count)]
        chars = [i for i, g in enumerate(self.groups) if g.character for _ in range(g.count)]
        return body + chars

    def order(self) -> list[int]:
        o = self.model_order
        if o is None or sorted(o) != sorted(self.default_order()):
            return self.default_order()
        return list(o)


# =============================================================================
# MODIFIERS  (also the target schema for LLM-extracted abilities/stratagems)
# =============================================================================
@dataclass
class Modifiers:
    # --- attacker ---
    hit_mod: int = 0                 # +1 / -1 to hit (net capped at +/-1)
    wound_mod: int = 0               # +1 / -1 to wound (capped at +/-1)
    reroll_hits: str = "none"        # none | ones | fails
    reroll_wounds: str = "none"      # none | ones | fails
    crit_hit_on: int = 6
    crit_wound_on: int = 6
    extra_ap: int = 0
    extra_damage: int = 0
    extra_attacks: int = 0           # per model
    add_lethal_hits: bool = False
    add_sustained_hits: int = 0
    add_devastating_wounds: bool = False
    add_twin_linked: bool = False
    # --- situation ---
    stationary: bool = False         # Heavy
    charged: bool = False            # Lance
    half_range: bool = False         # Melta, Rapid Fire
    beyond_12: bool = False          # Conversion
    not_visible: bool = False        # Indirect Fire: target gets cover, hits of 1-5 fail, no hit re-rolls
    # --- defender ---
    cover: bool = False
    save_mod: int = 0
    invuln_override: int | None = None
    feel_no_pain: int | None = None
    damage_reduction: int = 0
    halve_damage: bool = False
    toughness_mod: int = 0

    @classmethod
    def from_pairs(cls, pairs: list[str]) -> "Modifiers":
        m = cls()
        for p in pairs:
            k, _, v = p.partition("=")
            k = k.strip()
            if not hasattr(m, k):
                raise KeyError(f"Unknown modifier {k!r}. Valid: {', '.join(f.name for f in fields(cls))}")
            cur = getattr(m, k)
            if isinstance(cur, bool):
                val = v.strip().lower() in ("1", "true", "yes", "y", "")
            elif isinstance(cur, str):
                val = v.strip()
            else:
                val = int(v) if v.strip() else None
            setattr(m, k, val)
        return m

    def tags(self) -> list[str]:
        default = Modifiers()
        return [f"{k}={v}" for k, v in asdict(self).items() if v != getattr(default, k)]


# =============================================================================
# ENGINE
# =============================================================================
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


def _roll_d6(rng, n: int, reroll: str, success) -> np.ndarray:
    r = rng.integers(1, 7, size=n)
    if reroll == "fails":
        mask = ~success(r)
    elif reroll == "ones":
        mask = r == 1
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
    T = target.toughness + mods.toughness_mod
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
        per_model_bonus = mods.extra_attacks + (kw.blast + kw.cleave) * (n_target // 5)
        for _ in range(ld.count):
            attacks += w.A.roll(rng, trials) + per_model_bonus
            if mods.half_range and kw.rapid_fire:
                attacks += kw.rapid_fire.roll(rng, trials)
        attacks = np.maximum(attacks, 0)
        idx = np.repeat(np.arange(trials), attacks)

        # ---------- hits ----------
        lethal = (kw.lethal_hits is not None and target_matches(kw.lethal_hits, tkw)) or mods.add_lethal_hits
        if kw.sustained_hits and target_matches(kw.sustained_hits[1], tkw):
            sustained = kw.sustained_hits[0]
        else:
            sustained = Dice(0, 0, mods.add_sustained_hits)
        if kw.torrent or w.skill is None:
            crit = np.zeros(idx.size, bool)
            normal_hit = np.ones(idx.size, bool)
        else:
            indirect = kw.indirect_fire and mods.not_visible
            skill = w.skill
            if not w.melee and (mods.cover or indirect) and not kw.ignores_cover:
                skill += 1                      # Benefit of Cover: worsen BS by 1
            need = skill - _clamp(mods.hit_mod + (1 if kw.heavy and mods.stationary else 0))
            crit_on = mods.crit_hit_on
            if kw.conversion and mods.beyond_12:
                crit_on = min(crit_on, 4)
            if indirect:
                need = max(need, 6)

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
        wmod = _clamp(mods.wound_mod + (1 if kw.lance and mods.charged else 0))
        need_w = wound_target(w.S, T) - wmod
        crit_w = mods.crit_wound_on
        for cond, v in kw.anti:
            if target_matches(cond, tkw):
                crit_w = min(crit_w, v)

        def wound_ok(r):
            return (r >= crit_w) | ((r != 1) & (r >= need_w))
        twin = kw.twin_linked or mods.add_twin_linked
        rr = "fails" if twin else mods.reroll_wounds
        rw = _roll_d6(rng, roll_idx.size, rr, wound_ok)
        dev = (kw.devastating_wounds is not None and target_matches(kw.devastating_wounds, tkw)) \
            or mods.add_devastating_wounds
        crit_wound = (rw >= crit_w) & dev
        normal_idx = np.concatenate([roll_idx[wound_ok(rw) & ~crit_wound], auto_wound_idx])
        dev_idx = roll_idx[crit_wound]

        # ---------- damage per wound ----------
        def dmg(k):
            d = w.D.roll(rng, k) + mods.extra_damage + (kw.melta if mods.half_range else 0)
            if mods.halve_damage:
                d = (d + 1) // 2
            d = np.maximum(1, d - mods.damage_reduction)
            if mods.feel_no_pain and k:
                owner = np.repeat(np.arange(k), d)
                ignored = rng.integers(1, 7, size=owner.size) >= mods.feel_no_pain
                d = d - np.bincount(owner, weights=ignored, minlength=k).astype(np.int64)
            return d

        # ---------- saves, one result per allocation group ----------
        ap = w.AP + mods.extra_ap
        sr = rng.integers(1, 7, size=normal_idx.size)
        unsaved = np.empty((normal_idx.size, G), bool)
        for gi, g in enumerate(groups):
            p = g.profile
            armour_ok = (sr != 1) & (sr - ap + min(1, mods.save_mod) >= p.Sv)
            inv = mods.invuln_override or p.inv
            inv_ok = (sr >= inv) if inv else np.zeros(sr.size, bool)
            unsaved[:, gi] = ~(armour_ok | inv_ok)

        n_norm, n_dev = normal_idx.size, dev_idx.size
        e_trial += [normal_idx, dev_idx]
        e_dmg += [dmg(n_norm), dmg(n_dev)]
        e_mortal += [np.zeros(n_norm, bool), np.ones(n_dev, bool)]
        e_prec += [np.full(n_norm + n_dev, kw.precision)]
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


# =============================================================================
# CLI
# =============================================================================
def cmd_show(a):
    wd = Wahapedia(a.data)
    u = wd.unit_by_name(a.unit, a.faction)
    print(f"{u.name}  ({wd.factions.get(u.faction_id, u.faction_id)})")
    for p in u.models:
        print(f"  {p.name}: M{p.M} T{p.T} Sv{p.Sv}+" + (f" {p.inv}++" if p.inv else "") + f" W{p.W}")
    print(f"  keywords: {', '.join(sorted(u.keywords)) or '-'}")
    for w in u.weapons:
        print("  - " + w.summary())


def cmd_fight(a):
    wd = Wahapedia(a.data)
    att = wd.unit_by_name(a.attacker, a.attacker_faction)
    dfn = wd.unit_by_name(a.defender, a.defender_faction)
    mods = Modifiers.from_pairs(a.mod or [])
    weapons = att.weapons
    if a.weapon:
        weapons = [w for w in weapons if a.weapon.lower() in w.name.lower()]
    weapons = [w for w in weapons if (w.melee if a.melee else not w.melee)]
    if not weapons:
        sys.exit("No matching weapons")
    target = Target(dfn.name, [TargetGroup(dfn.models[0], a.defender_models, dfn.is_character)], dfn.keywords)
    print(f"{att.name} x{a.attacker_models} ({'melee' if a.melee else 'ranged'})")
    if a.each:
        for w in weapons:
            r = simulate([WeaponLoad(w, a.attacker_models)], target, mods, a.trials, a.seed)
            print(r.report(), "\n")
    else:
        r = simulate([WeaponLoad(w, a.attacker_models) for w in weapons], target, mods, a.trials, a.seed)
        print(r.report())
    print("Powered by Wahapedia")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="show a unit's stats and weapons")
    s.add_argument("--data")
    s.add_argument("--unit", required=True)
    s.add_argument("--faction")
    s.set_defaults(fn=cmd_show)

    f = sub.add_parser("fight", help="attacker vs defender (all weapons of the chosen type fire together)")
    f.add_argument("--data")
    f.add_argument("--attacker", required=True)
    f.add_argument("--attacker-faction")
    f.add_argument("--attacker-models", type=int, default=1)
    f.add_argument("--defender", required=True)
    f.add_argument("--defender-faction")
    f.add_argument("--defender-models", type=int, default=1)
    f.add_argument("--weapon", help="substring of the weapon name")
    f.add_argument("--melee", action="store_true", help="use melee weapons (default: ranged)")
    f.add_argument("--each", action="store_true", help="one result per weapon instead of combined")
    f.add_argument("--mod", action="append", help="modifier key=value, repeatable (see Modifiers)")
    f.add_argument("--trials", type=int, default=20_000)
    f.add_argument("--seed", type=int, default=1)
    f.set_defaults(fn=cmd_fight)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (KeyError, FileNotFoundError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
