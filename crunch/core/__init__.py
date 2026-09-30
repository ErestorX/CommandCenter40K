"""Pure rules engine: no file access, no UI. Safe to import from anywhere."""
from crunch.core.dice import Dice, DiceMod
from crunch.core.engine import SimResult, WeaponStats, simulate, wound_target
from crunch.core.keywords import WeaponKeywords, parse_weapon_keywords, target_matches
from crunch.core.models import ModelProfile, Target, TargetGroup, Unit, Weapon, WeaponLoad
from crunch.core.modifiers import Modifiers

__all__ = [
    "Dice", "DiceMod", "WeaponKeywords", "parse_weapon_keywords", "target_matches",
    "Weapon", "ModelProfile", "Unit", "WeaponLoad", "TargetGroup", "Target",
    "Modifiers", "simulate", "wound_target", "SimResult", "WeaponStats",
]
