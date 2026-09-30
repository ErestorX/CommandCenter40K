"""Shared test fixtures: a tiny Wahapedia-format dataset and a NewRecruit list, bundled in tests/fixtures."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from crunch.data.wahapedia import Wahapedia

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_DATA = FIXTURES / "wahapedia"
FIXTURE_LIST = FIXTURES / "lists" / "SpaceMarines.txt"


@lru_cache(maxsize=1)
def fixture_wd() -> Wahapedia:
    return Wahapedia(FIXTURE_DATA)
