"""Deployment support, independent of the UI: base sizes and unit footprints on the battlefield."""
from command_center.deploy.bases import FORMATIONS, Base, Footprint, parse_base, unit_footprint

__all__ = ["FORMATIONS", "Base", "Footprint", "parse_base", "unit_footprint"]
