"""Mission deck: Force Dispositions, primary missions, secondary missions and deployment maps.

Wahapedia has no CSV export for these, so they are scraped from its mission deck page
(config.MISSION_DECK_URL). Each Force Disposition card lists, for every opposing disposition, the
primary mission played; each primary mission card names its pair of dispositions.

    <edition>/missions/raw/mission_deck.html     the page as downloaded
    <edition>/missions/json/*.json               the parsed cards
    <edition>/missions/maps/*.png                deployment maps
    <edition>/missions/archive/<date>/           earlier versions of the page

The page is only re-parsed into JSON when its parsed content changes (the HTML itself also
carries ads and tokens that change on every visit).
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

SECTIONS = {
    "force_dispositions": "Force-Disposition-Cards",
    "primary_missions": "Primary-Mission-deck",
    "deployments": "Deployment-deck",
    "secondary_missions": "Secondary-Mission-deck",
}
PAGE_FILE = "mission_deck.html"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOCK = {"div", "p", "li", "br", "h1", "h2", "h3", "h4", "tr"}


# -----------------------------------------------------------------------------
# a tiny DOM, enough to query cards by class name
# -----------------------------------------------------------------------------
@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def find_all(self, cls: str) -> list["Node"]:
        out = []
        for c in self.children:
            if isinstance(c, Node):
                if cls in c.classes:
                    out.append(c)
                out += c.find_all(cls)
        return out

    def find(self, cls: str) -> "Node | None":
        for c in self.children:
            if isinstance(c, Node):
                if cls in c.classes:
                    return c
                hit = c.find(cls)
                if hit:
                    return hit
        return None

    def kids(self) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node)]

    def text(self) -> str:
        """Plain text; block elements become line breaks."""
        parts: list[str] = []

        def walk(n):
            for c in n.children:
                if isinstance(c, str):
                    parts.append(c)
                else:
                    sep = "\n" if c.tag in _BLOCK else " " if _is_layout(c) else ""
                    parts.append(sep)
                    walk(c)
                    parts.append(sep)
        walk(self)
        t = html_lib.unescape("".join(parts)).replace("\xa0", " ")
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r" ([.,;:)])", r"\1", t)
        return re.sub(r"\s*\n\s*", "\n", t).strip()

    def line(self) -> str:
        return " ".join(self.text().split())


def _is_layout(n: Node) -> bool:
    """Card layout spans (VP values, labels): kept apart from the text around them."""
    return n.tag == "span" and any(c.startswith(("caPm", "caAct")) for c in n.classes)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(n)
        if tag not in _VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):     # tolerate unclosed tags
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(text: str) -> Node:
    b = _TreeBuilder()
    b.feed(text)
    b.close()
    return b.root


# -----------------------------------------------------------------------------
# page -> cards
# -----------------------------------------------------------------------------
def _sections(page: str) -> dict[str, Node]:
    """Each deck section of the page (from its <h2 id=...> to the next deck heading)."""
    starts = []
    for key, anchor in SECTIONS.items():
        m = re.search(rf'<h2[^>]*id="{re.escape(anchor)}"', page)
        if m:
            starts.append((m.start(), key))
    starts.sort()
    ends = [m.start() for m in re.finditer(r'<h2[^>]*id="Twist-deck"', page)]
    out = {}
    for i, (pos, key) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else min([e for e in ends if e > pos] or [len(page)])
        out[key] = parse_html(page[pos:end])
    return out


def _fd_key(node: Node) -> str:
    """'PurgeTheFoe' from a disposition icon (class 'PurgeTheFoe2' or data-fd)."""
    if node.attrs.get("data-fd"):
        return node.attrs["data-fd"]
    for c in node.classes:
        if c.endswith("2") and c[:-1].isalpha():
            return c[:-1]
    return ""


def _actions(card: Node) -> list[dict]:
    out = []
    for a in card.find_all("caAct"):
        hdr, typ = a.find("caActHdr"), a.find("caActType")
        rows = {}
        for r in a.find_all("caActRow"):
            lbl = r.find("caActLbl")
            label = lbl.line().rstrip(":") if lbl else ""
            rows[label.lower().replace(" ", "_") or f"row{len(rows)}"] = r.line()[len(lbl.line()) if lbl else 0:].strip()
        out.append({"name": hdr.line() if hdr else "", "type": typ.line() if typ else "", **rows})
    return out


def _vp(node: Node) -> list[dict]:
    """VP values of one scoring line: [{"vp": "5VP", "notes": ["TACTICAL", "(UP TO 5VP)"]}]."""
    cols = node.find_all("caPmVPCol")
    if not cols:
        return [{"vp": v.line(), "notes": []} for v in node.find_all("caPmVP")]
    return [{"vp": (c.find("caPmVP") or c).line(), "notes": [n.line() for n in c.find_all("caPmCumul")]}
            for c in cols]


def _scoring(card: Node) -> list[dict]:
    blocks = []
    for b in card.find_all("caPmBlock"):
        block = {"round": "", "when": "", "conditions": []}
        for k in b.kids():
            cls = k.classes
            if "caPmHdr" in cls:
                block["round"] = k.line()
            elif "caPmWhen" in cls:
                block["when"] = re.sub(r"^WHEN:\s*", "", k.line())
            elif "caPmScore" in cls:
                layout = {"caPmVP", "caPmVPCol", "caPmVPPair", "caPmPlus", "caPmOr"}
                spans = [s for s in k.kids() if not s.classes & layout]
                block["conditions"].append({
                    "text": " ".join(s.line() for s in spans),
                    "vp": _vp(k),
                    "additional": k.find("caPmPlus") is not None,     # "+" line: adds to the one above
                    "alternative": k.find("caPmOr") is not None,      # "OR" line: instead of the one above
                })
        blocks.append(block)
    return blocks


def _card_common(card: Node) -> dict:
    name, legend, body = card.find("ca7Name"), card.find("ca7Legend"), card.find("ca7Body")
    return {
        "name": name.line() if name else "",
        "legend": legend.line() if legend else "",
        "intro": [i.line() for i in card.find_all("caPmIntro")],      # set-up rules: "WHEN DRAWN: ..."
        "actions": _actions(card),
        "scoring": _scoring(card),
        "text": body.text() if body else "",
    }


def parse_deck(page: str, page_url: str = "") -> dict:
    """The mission deck page -> {"force_dispositions", "primary_missions", "secondary_missions", "deployments"}."""
    sec = _sections(page)
    empty = Node("root")
    cards = {k: sec.get(k, empty).find_all("cgCardCA7") for k in SECTIONS}

    dispositions, names = [], {}
    for c in cards["force_dispositions"]:
        head = c.find("ca7Head")
        key = next((cl[len("ca7Hdr"):] for cl in (head.classes if head else ()) if cl.startswith("ca7Hdr")), "")
        name = c.find("ca7Name").line()
        names[key] = name
        rows = []
        for r in c.find_all("caFdRow"):
            icons = [i for i in (r.find("caFdIcons") or empty).kids()]
            opp = _fd_key(icons[1]) if len(icons) > 1 else ""
            rows.append({"opponent_key": opp, "mission": (r.find("caFdMissionName") or empty).line()})
        legend = c.find("ca7Legend")
        dispositions.append({"key": key, "name": name, "legend": legend.line() if legend else "", "matchups": rows})
    for d in dispositions:
        for r in d["matchups"]:
            r["opponent"] = names.get(r["opponent_key"], r["opponent_key"])

    primaries = []
    for c in cards["primary_missions"]:
        mine, opp = c.find("ca7FdPlayer"), c.find("ca7FdOpp")
        mk = _fd_key(mine.find("ca7FdTip")) if mine and mine.find("ca7FdTip") else ""
        ok = _fd_key(opp.find("ca7FdTip")) if opp and opp.find("ca7FdTip") else ""
        primaries.append({**_card_common(c),
                          "force_disposition": names.get(mk, mk), "force_disposition_key": mk,
                          "opponent_force_disposition": names.get(ok, ok), "opponent_force_disposition_key": ok})

    secondaries = [{**_card_common(c), "fixed": c.find("ca7Fixed") is not None}
                   for c in cards["secondary_missions"]]

    deployments = []
    for c in cards["deployments"]:
        img = next((n for n in _walk(c) if n.tag == "img"), None)
        src = img.attrs.get("src", "") if img else ""
        deployments.append({"name": c.find("ca7Name").line(),
                            "image": f"maps/{src.rsplit('/', 1)[-1]}" if src else "",
                            "image_url": urljoin(page_url, src) if src else ""})

    return {"force_dispositions": dispositions, "primary_missions": primaries,
            "secondary_missions": secondaries, "deployments": deployments}


def _walk(n: Node):
    for c in n.children:
        if isinstance(c, Node):
            yield c
            yield from _walk(c)


def content_hash(deck: dict) -> str:
    return hashlib.sha256(json.dumps(deck, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# -----------------------------------------------------------------------------
# update step (called by crunch.data.fetch)
# -----------------------------------------------------------------------------
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_deck(missions_dir: Path, deck: dict, fetch: Callable[[str], bytes | None] | None = None,
               refresh_maps: bool = False, log: Callable[[str], None] = print) -> None:
    """Write the JSON files and download missing (or all, with refresh_maps) deployment maps."""
    json_dir = missions_dir / "json"
    if json_dir.exists():
        shutil.rmtree(json_dir)
    for key in SECTIONS:
        _write_json(json_dir / f"{key}.json", deck[key])
    if fetch is None:
        return
    for d in deck["deployments"]:
        if not d["image_url"]:
            continue
        path = missions_dir / d["image"]
        if path.exists() and not refresh_maps:
            continue
        log(f"  GET {d['image']}")
        try:
            blob = fetch(d["image_url"])
        except RuntimeError as e:
            log(f"    map not downloaded: {e}")
            continue
        if blob:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        time.sleep(0.5)


def update_missions(edition_dir: Path, url: str, fetch: Callable[[str], bytes | None], force: bool = False,
                    old: dict | None = None, page: bytes | None = None,
                    log: Callable[[str], None] = print) -> dict | None:
    """Fetch (or use `page`), parse, and store the mission deck if it changed.
    old: the previous manifest entry. Returns the new manifest entry, or None when unchanged."""
    missions_dir = edition_dir / "missions"
    raw_dir = missions_dir / "raw"
    if page is None:
        log(f"  GET {url}")
        page = fetch(url)
        if page is None:
            raise RuntimeError(f"mission deck page not found: {url}")
    deck = parse_deck(page.decode("utf-8", errors="replace"), url)
    if not deck["primary_missions"] and not deck["secondary_missions"]:
        raise RuntimeError("no mission cards found on the page - has its layout changed?")
    digest = content_hash(deck)
    old = old or {}
    if not force and digest == old.get("content_sha256") and (missions_dir / "json").exists():
        log("Missions already up to date.")
        write_deck(missions_dir, deck, fetch, log=log)       # still fetch any map that went missing
        return None

    prev = raw_dir / PAGE_FILE
    if prev.exists() and old.get("content_sha256") and digest != old.get("content_sha256"):
        stamp = (old.get("fetched_at") or "unknown")[:10]
        arch = missions_dir / "archive" / stamp
        arch.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prev, arch / PAGE_FILE)
        log(f"Archived previous mission page to {arch}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    prev.write_bytes(page)
    write_deck(missions_dir, deck, fetch, refresh_maps=digest != old.get("content_sha256"), log=log)
    counts = {k: len(deck[k]) for k in SECTIONS}
    log("Missions: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items()))
    return {"source": url, "content_sha256": digest, "counts": counts,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def rebuild_missions(edition_dir: Path, url: str = "") -> dict | None:
    """Re-parse the saved page into JSON, offline. None if no page was saved."""
    page = edition_dir / "missions" / "raw" / PAGE_FILE
    if not page.exists():
        return None
    deck = parse_deck(page.read_text(encoding="utf-8", errors="replace"), url)
    write_deck(edition_dir / "missions", deck)
    return {k: len(deck[k]) for k in SECTIONS}
