"""Colour palettes per filament line, and moving colours between them.

PLA Matte uses the catalog's own palette (sorter-v2 `bambu-colors.ts`, the
same 25 colours as Bambu's table, with the ids the catalog's roles and fixed
colours use: charcoal, ash-gray, ...). Every other Bambu line uses Bambu
Studio's colour table (profiles/_colors.json, written by
tools/make_profile_templates.py). A generic filament has no palette of its
own and offers the catalog's.

Colours chosen in one palette, and the catalog's fixed colours ("must be
ash gray"), are carried into another palette as the nearest colour there:
Charcoal becomes PETG Matte Black, Ash Gray becomes Gray.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .catalog import Catalog, Color

COLORS_FILE = Path(__file__).resolve().parent / "profiles" / "_colors.json"
CATALOG_LINE = "PLA Matte"
NEUTRAL = Color(id="any", name="Any colour", hex="#9D9D9D")


@dataclass
class Palette:
    id: str  # the filament line, e.g. "PETG Matte"
    colors: list[Color]
    by_id: dict[str, Color] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_id = {c.id: c for c in self.colors}


@lru_cache(maxsize=None)
def _bambu_lines() -> dict[str, list[tuple[str, str]]]:
    if not COLORS_FILE.exists():
        return {}
    raw = json.loads(COLORS_FILE.read_text())
    return {line: [(c["name"], c["hex"]) for c in cols] for line, cols in raw.items()}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def line_of(filament: str) -> str:
    """"Bambu PETG Matte" -> "PETG Matte"; generic filaments use the catalog line."""
    line = filament.removeprefix("Bambu ").strip()
    return line if filament.startswith("Bambu ") and line in _bambu_lines() else CATALOG_LINE


def palette_for(cat: Catalog, filament: str) -> Palette:
    line = line_of(filament)
    if line == CATALOG_LINE:
        return Palette(CATALOG_LINE, list(cat.colors))
    seen: set[str] = set()
    colors = []
    for name, hx in _bambu_lines()[line]:
        cid = _slug(name)
        if cid in seen:
            continue
        seen.add(cid)
        colors.append(Color(id=cid, name=name, hex=hx))
    return Palette(line, colors)


def all_palettes(cat: Catalog, filaments: list[str]) -> dict[str, list[Color]]:
    out = {}
    for f in filaments:
        p = palette_for(cat, f)
        out.setdefault(p.id, p.colors)
    return out


# ---------------------------------------------------------------- nearest colour
def _lab(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def nearest(palette: Palette, hex_colour: str) -> Color:
    """The palette colour closest to `hex_colour` (CIE76 distance in Lab)."""
    if not palette.colors:
        return NEUTRAL
    a = _lab(hex_colour)
    return min(palette.colors, key=lambda c: math.dist(a, _lab(c.hex)))


def resolve(palette: Palette, cat: Catalog, color_id: str | None) -> Color:
    """A colour id from this palette, or from the catalog's (a role default, a
    fixed colour), as a colour of this palette."""
    if not color_id:
        return NEUTRAL
    if color_id in palette.by_id:
        return palette.by_id[color_id]
    known = cat.colors_by_id.get(color_id)
    if known:
        return nearest(palette, known.hex)
    for cols in _bambu_lines().values():  # an id picked in another line's palette
        for name, hx in cols:
            if _slug(name) == color_id:
                return nearest(palette, hx)
    return NEUTRAL
