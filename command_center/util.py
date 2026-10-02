"""Small text helpers shared by the data, list and UI layers."""
from __future__ import annotations

import html
import re


def norm(s: str) -> str:
    """Loose name key for matching: lowercase, letters/digits only, curly quotes folded."""
    s = html.unescape(s or "").lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]", "", s)


def strip_html(text: str) -> str:
    """HTML fragment -> single-line plain text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def to_int(s, default=None):
    """First integer found in a value ('3+' -> 3, '-2' -> -2), else `default`."""
    m = re.search(r"-?\d+", str(s or ""))
    return int(m.group()) if m else default


def clean_glyphs(s: str) -> str:
    """Characters some Windows/Tk fonts can't draw -> plain equivalents."""
    return (s or "").replace("‑", "-").replace("­", "").replace(" ", " ").replace(" ", " ")
