"""BSData's files for 40k (https://github.com/BSData/wh40k-11e): the army data NewRecruit builds its
lists from, so the names in a list are the names here. Read into the engine's objects (Unit,
ModelProfile, Weapon), and the rules text the windows show (abilities, enhancements, detachments).

The files (BattleScribe's data model, in JSON):
- one per catalogue (a faction, a Chapter, a library of shared units) plus the game system; a
  catalogue imports others (catalogueLinks). INDEX_FILE, written when they are downloaded (or on first
  use), lists them, so that only the catalogues a list needs are read.
- entries: units, models, upgrades (wargear, enhancements, detachments...), in groups of options
  (a group has no "type"), often linked from shared ones (entryLinks, infoLinks: a "targetId").
- profiles: "Unit" (M T Sv W LD OC InSv Base), "Ranged Weapons", "Melee Weapons", "Abilities",
  "Transport"...; rules (name and description); categories, the keywords ("Faction: Blood Angels" is
  the Faction keyword Blood Angels).
- modifiers, which change all that depending on what is selected: not applied here.

The files are community work, updated daily, and have gaps (the Space Marines' base sizes, a blank
value here and there): everything is read forgivingly. A blank stays blank (command_center.data.armies
fills what Wahapedia has), what can't be read is left out, nothing raises."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from command_center import config
from command_center.core.dice import Dice
from command_center.core.keywords import parse_weapon_keywords
from command_center.core.models import ModelProfile, Unit, Weapon
from command_center.util import norm, to_int

INDEX_FILE = "index.json"          # the files: id, name, library or not, catalogues each one imports
MANIFEST_FILE = "manifest.json"    # what was downloaded: commit, its date (command_center.data.fetch)
WEAPON_TYPES = ("Ranged Weapons", "Melee Weapons")
ATTACHMENT = ("Leader", "Support")                  # abilities naming the units a character can join

# Groups of options under units that aren't the unit's gear: Crusade, Boarding Actions, enhancements.
NOT_GEAR = re.compile(
    r"crusade|battle (trait|honour|scar)|relic|upgrade|modification|enhancement|mighty champions|specialism"
    r"|mark of chaos|boons? of|chaos boons|commendation|deeds of|advancement|angels ascendant|chapter command"
    r"|boarding|breaching|bossloot|aeldari paths|ascendant lord|warband champion|strains|archeotech|assets"
    r"|trials of|hymns of|gifts of|skull harvest|shrewd strategy|beloved of|grudges|rewards of|blackstone"
    r"|tyrannic war|armageddon|lone wolf|lord of|patron specialism", re.I)


def key(name: str) -> str:
    """A name as entries are told apart: norm(), without BSData's " [Legends]" or " (Upgrade)"."""
    return norm(re.sub(r"\s*(\[legends\]|\(upgrade\))", "", name or "", flags=re.I))


def to_html(text: str) -> str:
    """BSData's text (markdown-like: **bold**, ^^KEYWORD^^, line breaks) -> the HTML the windows show."""
    t = html.escape(text or "").replace("\r", "")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\^\^(.+?)\^\^", r"<b>\1</b>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", t)
    return re.sub(r"\n", "<br>", t.strip())


def chars(profile: dict) -> dict[str, str]:
    """A profile's characteristics, by name: {"M": '6"', "T": "4", ...}."""
    return {c.get("name", ""): (c.get("$text") or "").strip() for c in profile.get("characteristics", []) or []}


def attached_names(text: str) -> set[str]:
    """The units a Leader or Support ability names, as key()s. Its list comes in several layouts
    ("- **^^Intercessor Squad^^**", "■ Wyches", "A, B and C."), after the first colon."""
    body = re.split(r"\n\s*\n", (text or "").split(":", 1)[-1].strip())[0]
    names = set()
    for part in re.split(r"\n|,|\s+and\s+(?=[^,]*$)", body):
        n = re.sub(r"\s+", " ", re.sub(r"[*^■•\-–\[\] ]", " ", part)).strip(" .")
        if n and len(n) < 60:
            names.add(key(n))
    return names


def build_index(folder: Path) -> list[dict]:
    """What each file holds: read them all once (the download writes this, see write_index)."""
    out = []
    for f in sorted(Path(folder).glob("*.json")):
        if f.name in (INDEX_FILE, MANIFEST_FILE):
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        book = doc.get("catalogue") or doc.get("gameSystem") if isinstance(doc, dict) else None
        if not isinstance(book, dict) or "id" not in book:
            continue
        out.append({"file": f.name, "id": book["id"], "name": book.get("name", ""), "type": book.get("type", ""),
                    "library": bool(book.get("library")),
                    "links": [l["targetId"] for l in book.get("catalogueLinks", []) or [] if l.get("targetId")]})
    return out


def write_index(folder: Path) -> list[dict]:
    index = build_index(folder)
    (Path(folder) / INDEX_FILE).write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


class BSData:
    """The files of a folder, read when needed; units built once."""

    def __init__(self, folder: str | Path | None = None):
        d = Path(folder) if folder else config.find_bsdata_dir()
        if not d or not (d / config.BSDATA_SYSTEM_FILE).exists():
            raise FileNotFoundError("No BSData files found.")
        self.folder = d
        try:
            self.index = json.loads((d / INDEX_FILE).read_text(encoding="utf-8"))
            if {e["file"] for e in self.index} != {f.name for f in d.glob("*.json")} - {INDEX_FILE, MANIFEST_FILE}:
                raise ValueError("index out of date")
        except (OSError, ValueError, KeyError, TypeError):
            try:
                self.index = write_index(d)
            except OSError:
                self.index = build_index(d)
        try:
            self.manifest = json.loads((d / MANIFEST_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest = {}
        self._entry = {e["id"]: e for e in self.index}
        self._books: dict[str, dict] = {}
        self._by_id: dict[str, dict] = {}            # every entry, profile, rule... of the books read
        self._owner: dict[str, str] = {}             # entry id -> the book it is defined in
        self._units_of: dict[str, dict[str, dict]] = {}
        self._units: dict[str, Unit] = {}
        self._weapons: dict[int, Weapon | None] = {}
        self._enhancements: dict[str | None, dict[str, dict]] = {}
        system =next((e for e in self.index if e.get("type") == "gameSystem"), None)
        self.system_id = system["id"] if system else ""

    @property
    def revision(self) -> str:
        """When the files were last changed (the commit's date), as downloaded; "" if not known."""
        return str(self.manifest.get("date", ""))[:10]

    # ---- the books --------------------------------------------------------
    def book(self, book_id: str) -> dict | None:
        if book_id in self._books:
            return self._books[book_id]
        entry = self._entry.get(book_id)
        book = None
        if entry:
            try:
                doc = json.loads((self.folder / entry["file"]).read_text(encoding="utf-8"))
                book = doc.get("catalogue") or doc.get("gameSystem")
            except (OSError, ValueError):
                book = None
        self._books[book_id] = book
        if book:
            self._index_ids(book, book_id)
        return book

    def _index_ids(self, node, book_id: str) -> None:
        if isinstance(node, dict):
            if "id" in node and "targetId" not in node and node["id"] not in self._by_id:
                self._by_id[node["id"]] = node
                self._owner[node["id"]] = book_id
            for v in node.values():
                if isinstance(v, (dict, list)):
                    self._index_ids(v, book_id)
        elif isinstance(node, list):
            for x in node:
                self._index_ids(x, book_id)

    def catalogue_for(self, title: str) -> str | None:
        """The catalogue a list is built from, by its title ("Imperium - Adeptus Astartes - Blood Angels -
        My list"): the one whose name starts it, else the one whose last part ("Blood Angels") is the most
        specific part of the title. None when none fits."""
        t = norm(title)
        catalogues = [e for e in self.index if e.get("type") == "catalogue" and not e.get("library")]
        starts = [e for e in catalogues if t.startswith(norm(e["name"]))]
        if starts:
            return max(starts, key=lambda e: len(e["name"]))["id"]
        parts = [norm(p) for p in (title or "").split(" - ")]
        best = None
        for e in catalogues:
            last = norm(e["name"].split(" - ")[-1])
            if last in parts:
                rank = (parts.index(last), len(e["name"]))
                if best is None or rank > best[0]:
                    best = (rank, e["id"])
        return best[1] if best else None

    def reach(self, book_id: str | None) -> list[str]:
        """A catalogue, those it imports (and theirs), then the game system; every catalogue if None."""
        if not book_id:
            return [e["id"] for e in self.index if e.get("type") == "catalogue"] + [self.system_id]
        out, todo = [], [book_id]
        while todo:
            b = todo.pop(0)
            if b in out or b not in self._entry:
                continue
            out.append(b)
            todo += self._entry[b].get("links", [])
        return out + ([self.system_id] if self.system_id not in out else [])

    def _load(self, books: list[str]) -> list[dict]:
        return [b for b in (self.book(i) for i in books) if b]

    # ---- following links --------------------------------------------------
    def target(self, node: dict) -> dict | None:
        return self._by_id.get(node["targetId"]) if "targetId" in node else node

    def children(self, node: dict):
        """(name, entry) of the entries and groups right under an entry or group, links followed (the
        link's name kept: it is the name the list shows)."""
        for k in ("selectionEntries", "selectionEntryGroups", "entryLinks"):
            for e in node.get(k, []) or []:
                t = self.target(e)
                if t:
                    yield e.get("name") or t.get("name", ""), t

    def walk(self, node: dict, gear_only: bool = False, depth: int = 0, seen: set | None = None):
        """(name, entry) of everything under an entry, each once; `gear_only`: not into the groups that
        aren't the unit's gear (NOT_GEAR: Crusade, enhancements...)."""
        seen = set() if seen is None else seen
        for name, e in self.children(node):
            if id(e) in seen or depth > 10:
                continue
            seen.add(id(e))
            if gear_only and is_group(e) and (NOT_GEAR.search(name) or NOT_GEAR.search(e.get("name", ""))):
                continue
            yield name, e
            yield from self.walk(e, gear_only, depth + 1, seen)

    def profiles(self, node: dict) -> list[dict]:
        out = list(node.get("profiles", []) or [])
        out += [p for p in (self.target(l) for l in node.get("infoLinks", []) or [] if l.get("type") == "profile") if p]
        for g in node.get("infoGroups", []) or []:
            out += self.profiles(g)
        return out

    def rules(self, node: dict) -> list[tuple[str, dict]]:
        """(name, rule) of the rules an entry has, linked ones included."""
        out = [(r.get("name", ""), r) for r in node.get("rules", []) or []]
        for link in node.get("infoLinks", []) or []:
            if link.get("type") == "rule":
                r = self.target(link)
                if r:
                    out.append((link.get("name") or r.get("name", ""), r))
        return out

    # ---- units ------------------------------------------------------------
    def _units_in(self, book_id: str) -> dict[str, dict]:
        """key(name) -> the unit (or single model) entries a catalogue offers, its own and linked."""
        if book_id not in self._units_of:
            found: dict[str, dict] = {}
            book = self.book(book_id) or {}
            for k in ("sharedSelectionEntries", "selectionEntries", "entryLinks"):
                for e in book.get(k, []) or []:
                    t = self.target(e)
                    if t and t.get("type") in ("unit", "model"):
                        found.setdefault(key(e.get("name") or t.get("name", "")), t)
            self._units_of[book_id] = found
        return self._units_of[book_id]

    def find(self, name: str, title: str = "") -> dict | None:
        """The unit entry a list names, in the catalogues its title points to (all of them if none)."""
        books = self.reach(self.catalogue_for(title)) if title else self.reach(None)
        self._load(books)
        k = key(name)
        for b in books:
            hit = self._units_in(b).get(k)
            if hit:
                return hit
        return None

    def unit(self, entry: dict) -> Unit:
        """The engine's Unit for a unit entry (built once)."""
        uid = entry.get("id", "")
        if uid not in self._units:
            self._units[uid] = self._build(entry)
        return self._units[uid]

    def _models(self, entry: dict) -> list[tuple[str, dict]]:
        found = [(n, e) for n, e in self.walk(entry, gear_only=True) if e.get("type") == "model"]
        if entry.get("type") == "model":
            found.insert(0, (entry.get("name", ""), entry))
        out, names = [], set()
        for n, e in found:
            if key(n) not in names:
                names.add(key(n))
                out.append((n, e))
        return out

    def _stat_profile(self, model: dict, unit: dict, name: str) -> dict | None:
        candidates = [p for node in (model, unit) for p in self.profiles(node) if p.get("typeName") == "Unit"]
        if not candidates:
            candidates = [p for _, e in self.walk(unit, gear_only=True) for p in self.profiles(e) if p.get("typeName") == "Unit"]
        if not candidates:
            return None
        said = key(name)
        return next((p for p in candidates if key(p.get("name", "")) == said),
                    next((p for p in candidates if said.startswith(key(p.get("name", "")))), candidates[0]))

    @staticmethod
    def _model_profile(name: str, p: dict | None) -> ModelProfile:
        c = chars(p) if p else {}
        inv = to_int(c.get("InSv"))
        return ModelProfile(name=name, M=c.get("M", ""), T=to_int(c.get("T"), 4), Sv=to_int(c.get("Sv"), 7),
                            inv=inv if inv else None, W=to_int(c.get("W"), 1), base=c.get("Base", ""))

    def weapon(self, p: dict) -> Weapon | None:
        """A weapon profile as the engine's Weapon; None when it can't be read (a blank or "*" value)."""
        if id(p) in self._weapons:
            return self._weapons[id(p)]
        c = chars(p)
        w = None
        skill = c.get("BS") or c.get("WS") or ""
        try:
            attacks = Dice.parse(c.get("A", ""))
            if c.get("A", "") not in ("", "-") and attacks.mean > 0:
                w = Weapon(name=re.sub(r"^\W+\s*", "", p.get("name", "")).strip(),
                           type="Melee" if p.get("typeName", "").startswith("Melee") else "Ranged",
                           range=c.get("Range", ""), A=attacks,
                           skill=None if skill.upper() in ("N/A", "", "-") else to_int(skill),
                           S=to_int(c.get("S"), 4), AP=abs(to_int(c.get("AP"), 0)), D=Dice.parse(c.get("D", "")),
                           keywords=parse_weapon_keywords(c.get("Keywords", "")))
        except ValueError:
            w = None
        self._weapons[id(p)] = w
        return w

    def _own_weapons(self, e: dict, depth: int = 0) -> list[Weapon]:
        """The weapons an item is: its profiles, and those of what it is made of (not of its options)."""
        out = [w for w in (self.weapon(p) for p in self.profiles(e) if p.get("typeName") in WEAPON_TYPES) if w]
        for _, d in self.children(e):
            if not is_group(d) and d.get("type") != "model" and depth < 4:
                out += self._own_weapons(d, depth + 1)
        return out

    def _build(self, entry: dict) -> Unit:
        name = entry.get("name", "")
        models = [self._model_profile(n, self._stat_profile(m, entry, n)) for n, m in self._models(entry)]
        if not models:
            models = [self._model_profile(name, self._stat_profile(entry, entry, name))]
        gear: dict[str, list[Weapon]] = {}
        weapons: list[Weapon] = []

        def add(k: str, ws: list[Weapon]) -> None:
            if not k:
                return
            have = gear.setdefault(k, [])
            for w in ws:
                if w not in have:
                    have.append(w)
                if w not in weapons:
                    weapons.append(w)

        for node in [entry] + [m for _, m in self._models(entry)]:          # profiles right on the unit / models
            for w in (self.weapon(p) for p in self.profiles(node) if p.get("typeName") in WEAPON_TYPES):
                if w:
                    add(norm(w.name), [w])
                    add(norm(w.base_name), [w])
        for n, e in self.walk(entry, gear_only=True):
            if is_group(e) or e.get("type") == "model":
                continue
            ws = self._own_weapons(e)
            add(norm(n), ws)
            add(norm(e.get("name", "")), ws)
            for w in ws:
                add(norm(w.name), [w])
                add(norm(w.base_name), [w])
        keywords = {self._keyword(l.get("name", "")) for node in [entry] + [m for _, m in self._models(entry)]
                    for l in node.get("categoryLinks", []) or []} - {""}
        other = {"warlord"} | {k for k, ws in gear.items() if not ws} | self._enhancement_names(entry)
        other |= {norm(p.get("name", "")) for p in self.profiles(entry) if p.get("typeName") != "Unit"}
        return Unit(entry.get("id", ""), name, "", models, weapons, keywords, "support" in keywords,
                    frozenset(other - {""}), gear, "bsdata")

    @staticmethod
    def _keyword(category: str) -> str:
        return re.sub(r"^faction:\s*", "", category.strip(), flags=re.I).lower()

    def faction_keywords(self, unit_id: str) -> set[str]:
        """norm()-ed Faction keywords of a unit ("bloodangels", "adeptusastartes")."""
        e = self._by_id.get(unit_id) or {}
        nodes = [e] + [m for _, m in self._models(e)] if e else []
        return {norm(l.get("name", "").split(":", 1)[1]) for n in nodes for l in n.get("categoryLinks", []) or []
                if l.get("name", "").lower().startswith("faction:")}

    def has(self, unit_id: str) -> bool:
        return unit_id in self._units

    def attaches(self, unit_id: str) -> set[str] | None:
        """key()s of the units a character can join, from its Leader and Support abilities; None if it
        has neither (or names none)."""
        e = self._by_id.get(unit_id)
        if not e:
            return None
        names: set[str] = set()
        for node in [e] + [m for _, m in self._models(e)]:
            for p in self.profiles(node):
                if p.get("typeName") == "Abilities" and p.get("name") in ATTACHMENT:
                    names |= attached_names(chars(p).get("Description", ""))
        return names or None

    def abilities(self, unit_id: str) -> dict[str, list[tuple[str, str]]]:
        """{"Core": [(name, html)], "Faction": [...], "Datasheet": [...], "Wargear": [...], "Other": [...]},
        as command_center.data.rules.RulesBook.unit_abilities gives Wahapedia's."""
        e = self._by_id.get(unit_id)
        out: dict[str, list[tuple[str, str]]] = {}
        if not e:
            return out

        def put(kind: str, name: str, text: str) -> None:
            if name and all(n != name for n, _ in out.get(kind, [])):
                out.setdefault(kind, []).append((name, text))

        nodes = [e] + [m for _, m in self._models(e)]
        for node in nodes:
            for name, r in self.rules(node):
                kind = "Core" if self._owner.get(r.get("id", "")) == self.system_id else "Faction"
                put(kind, name, to_html(r.get("description", "")))
            for p in self.profiles(node):
                c = chars(p)
                if p.get("typeName") == "Abilities":
                    put("Datasheet", p.get("name", ""), to_html(c.get("Description", "")))
                elif p.get("typeName") not in ("Unit",) + WEAPON_TYPES:
                    put("Other", f"{p.get('typeName')}: {p.get('name', '')}",
                        to_html("\n".join(f"{k}: {v}" if len(c) > 1 else v for k, v in c.items())))
        for _, d in self.walk(e, gear_only=True):
            if is_group(d) or d.get("type") == "model":
                continue
            for p in self.profiles(d):
                if p.get("typeName") == "Abilities":
                    put("Wargear", p.get("name", ""), to_html(chars(p).get("Description", "")))
        return out

    # ---- enhancements and detachments ------------------------------------
    def _groups_named(self, books: list[str], name: str) -> list[dict]:
        return [g for b in self._load(books) for g in b.get("sharedSelectionEntryGroups", []) or []
                if g.get("name") == name]

    def enhancements(self, book_id: str | None) -> dict[str, dict]:
        """key(name) -> {"name", "description" (HTML), "cost", "detachment"} of the enhancements a
        catalogue offers (with what it imports). They are laid out as: group "Enhancements" -> one group
        "<Detachment> Enhancements" per detachment -> one entry per enhancement, with its profile."""
        if book_id in self._enhancements:
            return self._enhancements[book_id]
        out: dict[str, dict] = {}
        for g in self._groups_named(self.reach(book_id), "Enhancements"):
            for n, group in self.children(g):
                detachment = re.sub(r"\s+Enhancements$", "", n)
                for name, e in self.walk(group):
                    if is_group(e):
                        continue
                    name = re.sub(r"\s*\(Upgrade\)\s*$", "", name, flags=re.I)
                    text = "\n\n".join(chars(p).get("Description") or ", ".join(f"{k} {v}" for k, v in chars(p).items())
                                       for p in self.profiles(e))
                    cost = next((c.get("value") for c in e.get("costs", []) or [] if c.get("name") == "pts"), None)
                    out.setdefault(key(name), {"name": name, "description": to_html(text), "cost": cost,
                                               "detachment": detachment})
        self._enhancements[book_id] = out
        return out

    def _enhancement_names(self, entry: dict) -> set[str]:
        owner = self._owner.get(entry.get("id", ""))
        return {norm(e["name"]) for e in self.enhancements(owner).values()} if owner else set()

    def detachment(self, name: str, title: str) -> dict | None:
        """{"name", "rules": [{"name", "description" (HTML)}], "enhancements": [...], "tags": [categories]}
        of a detachment the list's catalogue offers; None if it has none by that name."""
        book_id = self.catalogue_for(title)
        books = self.reach(book_id)
        for g in self._groups_named(books, "Detachment"):
            for n, e in self.walk(g):
                if key(n) == key(name) and not is_group(e):
                    return {"name": n,
                            "rules": [{"name": rn, "description": to_html(r.get("description", ""))}
                                      for rn, r in self.rules(e)],
                            "enhancements": [x for x in self.enhancements(book_id).values()
                                             if key(x["detachment"]) == key(name)],
                            "tags": [l.get("name", "") for l in e.get("categoryLinks", []) or []]}
        return None


def is_group(entry: dict) -> bool:
    """A group of options (groups carry no "type" in these files)."""
    return entry.get("type") in (None, "selectionEntryGroup")
