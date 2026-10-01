"""Deployment support, independent of the UI: base sizes and unit footprints on the battlefield."""
from crunch.deploy.bases import Base, Footprint, parse_base, unit_footprint

__all__ = ["Base", "Footprint", "parse_base", "unit_footprint"]
