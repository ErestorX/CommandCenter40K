"""Rules windows shared by tools: army/detachment rules with stratagem cards, and unit abilities."""
from __future__ import annotations

from command_center.config import ATTRIBUTION_SHORT
from command_center.data.rules import RulesBook
from command_center.ui.richtext import RichTextWindow
from command_center.util import norm

# =============================================================================
# content builders
# =============================================================================
def _strat_meta(s: dict) -> str:
    bits = [f"{s.get('cp_cost', '?')} CP", s.get("type", "")]
    if s.get("turn"):
        bits.append(s["turn"])
    if s.get("phase"):
        bits.append(s["phase"])
    return "  ·  ".join(b for b in bits if b)


def show_army_rules(master, book: RulesBook, army) -> RichTextWindow:
    w = RichTextWindow(master, f"{army.faction} — army & detachment rules", width=1120, height=860)
    w.h1(army.faction)
    w.meta(f"{army.path.stem}  ·  {army.points} pts" + (f"  ·  {army.detachment}" if army.detachment else ""))

    rules = book.army_rules(army.faction_id)
    w.h2("Army rules")
    if not rules:
        w.meta("No army rule found for this faction.")
    for r in rules:
        w.h3(r["name"])
        w.html(r.get("description", ""))

    dets = book.detachments(army.faction_id, army.detachment_names)
    if not dets:
        w.h2("Detachment")
        w.meta(f"Could not match “{army.detachment or 'no detachment'}” to a Wahapedia detachment.")
    taken = {norm(n) for u in army.units for n, _ in u.unit_gear}
    for m_u in army.units:
        for m in m_u.models:
            taken |= {norm(n) for n, _ in m.gear}
    for d in dets:
        c = book.detachment_content(d)
        w.h2(f"Detachment: {d['name']}")
        extra = [x for x in (d.get("type"), f"{d['dp']} DP" if d.get("dp") else "", d.get("force_disposition")) if x]
        if extra:
            w.meta("  ·  ".join(extra))
        for r in c["rules"]:
            w.h3(r["name"])
            w.html(r.get("description", ""))
        if c["enhancements"]:
            w.h3("Enhancements")
            for e in c["enhancements"]:
                mine = "  ← in this list" if norm(e["name"]) in taken else ""
                w.h3(f"• {e['name']}", f"{e.get('cost', '?')} pts{mine}")
                w.html(e.get("description", ""))
        if c["stratagems"]:
            w.h3("Stratagems")
            w.cards(c["stratagems"])

    core = book.core_stratagems()
    if core:
        w.h2("Core stratagems")
        w.cards(core)
    w.gap()
    w.meta("Powered by Wahapedia · rules © Games Workshop")
    w.done()
    return w


def show_unit_abilities(master, book: RulesBook, units: list) -> RichTextWindow:
    """units: ListUnit objects (bodyguard first, then attached characters)."""
    names = " + ".join(u.label for u in units)
    w = RichTextWindow(master, f"{names} — abilities", width=700)
    w.h1(names)
    for u in units:
        ds = u.datasheet
        if not ds:
            continue
        row = book.datasheet_row(ds.id)
        w.h2(u.label + ("  (Support)" if u.is_support else "  (Leader)" if u is not units[0] and u.is_character else ""))
        for p in ds.models:
            inv = f"  {p.inv}++" if p.inv else ""
            w.meta(f"{p.name}:  M {p.M}   T {p.T}   Sv {p.Sv}+{inv}   W {p.W}")
        inv_descr = book.invuln_description(ds.id)
        if inv_descr:
            w.html(inv_descr)
        ab = book.unit_abilities(ds.id)
        for kind in ("Core", "Faction"):
            if ab.get(kind):
                w.text.insert("end", f"{kind}: ", ("bold",))
                w.text.insert("end", ", ".join(n for n, _ in ab[kind]) + "\n")
        for kind, title in (("Datasheet", "Abilities"), ("Wargear", "Wargear abilities"), ("Other", "Other")):
            for name, desc in ab.get(kind, []):
                w.h3(name, title if kind != "Datasheet" else "")
                if desc:
                    w.html(desc)
        if row.get("leader_head") or row.get("leader_footer"):
            w.h3("Attachment")
            w.html(row.get("leader_head", "") + "<br>" + row.get("leader_footer", ""))
        if row.get("damaged_w"):
            w.h3(f"Damaged: {row['damaged_w']} wounds remaining")
            w.html(row.get("damaged_description", ""))
        w.text.insert("end", "Keywords: ", ("bold",))
        w.text.insert("end", ", ".join(sorted(k.upper() for k in ds.keywords)) + "\n", ("kw",))
    w.gap()
    w.meta("Powered by Wahapedia · rules © Games Workshop")
    w.done()
    return w
