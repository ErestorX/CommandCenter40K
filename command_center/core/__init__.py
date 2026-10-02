"""Pure rules engine: no file access, no UI. Safe to import from anywhere."""
from command_center.core.dice import Dice, DiceMod
from command_center.core.engine import SimResult, WeaponStats, simulate, wound_target
from command_center.core.keywords import WeaponKeywords, parse_weapon_keywords, target_matches
from command_center.core.models import ModelProfile, Target, TargetGroup, Unit, Weapon, WeaponLoad
from command_center.core.modifiers import Modifiers

__all__ = [
    "Dice", "DiceMod", "WeaponKeywords", "parse_weapon_keywords", "target_matches",
    "Weapon", "ModelProfile", "Unit", "WeaponLoad", "TargetGroup", "Target",
    "Modifiers", "simulate", "wound_target", "SimResult", "WeaponStats",
]
