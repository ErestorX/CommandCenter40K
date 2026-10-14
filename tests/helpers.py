"""Shared test fixtures, bundled in tests/fixtures: a tiny Wahapedia-format dataset, BSData files cut
from the real ones (scripts/bsdata_fixture.py: a Space Marines catalogue with the fixture lists' units),
and NewRecruit lists."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from command_center.data.armies import Armies
from command_center.data.bsdata import BSData
from command_center.data.wahapedia import Wahapedia

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_DATA = FIXTURES / "wahapedia"
FIXTURE_BSDATA = FIXTURES / "bsdata"
FIXTURE_LIST = FIXTURES / "lists" / "SpaceMarines.txt"


@lru_cache(maxsize=1)
def fixture_wd() -> Wahapedia:
    return Wahapedia(FIXTURE_DATA)


def fixture_bs() -> BSData:
    return BSData(FIXTURE_BSDATA)


def fixture_armies() -> Armies:
    """BSData first, completed by Wahapedia: what the app links lists with."""
    return Armies(fixture_wd(), fixture_bs())
