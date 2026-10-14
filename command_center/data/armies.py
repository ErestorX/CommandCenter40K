"""Where a list's units come from: BSData first, Wahapedia for what BSData doesn't have.

- A unit is looked for in BSData (command_center.data.bsdata) by the exact name the list gives it, in
  the catalogues the list's title points to. Found, it is completed from Wahapedia's datasheet of that
  name (its Unit.fallback): the base sizes BSData leaves blank, and the items the list names that
  BSData doesn't have (command_center.lists.linking.match_weapon). Not found, the unit is Wahapedia's
  datasheet, matched as before (command_center.data.wahapedia).
- An enhancement that gives a weapon (Imperium's Sword): BSData's profile of it, on whichever unit the
  list gives it to (Unit.gear, by the enhancement's name).
- Whether a character can join a unit: the units its BSData Leader or Support ability names; when it
  has none (or is a Wahapedia unit), Wahapedia's table.

Without BSData's files (not downloaded yet), everything is Wahapedia's, as it always was. What is blank
in both stays blank: an estimated base is drawn for a blank base size (command_center.deploy.bases)."""
from __future__ import annotations

from command_center.core.models import Unit
from command_center.data.bsdata import BSData, key
from command_center.data.wahapedia import Wahapedia


class Armies:
    """What list parsing and linking read: the same calls as Wahapedia's (faction_id, can_lead...),
    answered from BSData first."""

    def __init__(self, wd: Wahapedia, bs: BSData | None = None):
        self.wd = wd
        self.bs = bs
        self._by_id: dict[str, Unit] = {}        # every unit handed out, by id (BSData's and Wahapedia's ids differ)

    def faction_id(self, name: str) -> str | None:
        return self.wd.faction_id(name)

    @property
    def last_update(self) -> str:
        return self.wd.last_update

    def datasheet_for(self, name: str, army) -> Unit | None:
        """The unit a list names: BSData's, completed from Wahapedia; else Wahapedia's; None if neither has it."""
        fallback = self.wd.datasheet_for(name, army)
        unit = None
        if self.bs:
            entry = self.bs.find(name, army.title)
            if entry:
                unit = self.bs.unit(entry)
                self._complete(unit, fallback, army.faction_id)
        unit = unit or fallback
        if unit:
            self._by_id[unit.id] = unit
            if self.bs:
                for k, ws in self.bs.enhancement_weapons(army.title).items():
                    unit.gear.setdefault(k, ws)
        return unit

    @staticmethod
    def _complete(unit: Unit, fallback: Unit | None, faction_id: str | None) -> None:
        unit.fallback = fallback
        unit.faction_id = (fallback.faction_id if fallback else "") or faction_id or ""
        if not fallback:
            return
        for m in unit.models:
            if not m.base.strip():
                m.base = fallback.profile(m.name).base

    def unit_by_id(self, unit_id: str) -> Unit | None:
        if unit_id in self._by_id:
            return self._by_id[unit_id]
        return self.wd.unit(unit_id) if unit_id in self.wd.datasheets else None

    def can_lead(self, leader_id: str, bodyguard_id: str) -> bool:
        """Can this character (Leader or Support) join this unit? By ids as Unit.id gives them."""
        leader, bodyguard = self.unit_by_id(leader_id), self.unit_by_id(bodyguard_id)
        if not leader or not bodyguard:
            return self.wd.can_lead(leader_id, bodyguard_id)
        names = self.bs.attaches(leader.id) if self.bs and leader.source == "bsdata" else None
        if names:
            said = {key(bodyguard.name)} | ({key(bodyguard.fallback.name)} if bodyguard.fallback else set())
            return any(k in names or k.rstrip("s") in names or k + "s" in names for k in said)
        lid, bid = wahapedia_id(leader), wahapedia_id(bodyguard)
        return bool(lid and bid and self.wd.can_lead(lid, bid))


def wahapedia_id(unit: Unit | None) -> str | None:
    """A unit's Wahapedia datasheet id: its own, or its fallback's for a BSData unit."""
    if unit is None:
        return None
    if unit.source == "wahapedia":
        return unit.id
    return unit.fallback.id if unit.fallback else None
