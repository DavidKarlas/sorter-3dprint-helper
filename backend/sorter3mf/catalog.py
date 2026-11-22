"""The Sorter V2 parts catalog: fetched, cached, and lightly indexed.

The catalog is `catalog.generated.json` from the parts calculator in the
sorter-v2 repository. This module never edits it; it only reads it. The
filament colour palette comes from the same app's `bambu-colors.ts`, parsed
the same way the catalog generator parses it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import config


@dataclass
class Color:
    id: str
    name: str
    hex: str


@dataclass
class Catalog:
    raw: dict
    colors: list[Color]
    source: str
    fetched_at: float
    parts_by_id: dict = field(default_factory=dict)
    assemblies_by_id: dict = field(default_factory=dict)
    colors_by_id: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.parts_by_id = {p["id"]: p for p in self.raw.get("parts", [])}
        self.assemblies_by_id = {a["id"]: a for a in self.raw.get("assemblies", [])}
        self.colors_by_id = {c.id: c for c in self.colors}

    @property
    def sections(self) -> list[dict]:
        return self.raw.get("sections", [])

    @property
    def color_roles(self) -> list[dict]:
        return self.raw.get("color_roles", [])

    @property
    def settings(self) -> dict:
        return self.raw.get("settings", {})

    def color(self, color_id: str | None) -> Color:
        if color_id and color_id in self.colors_by_id:
            return self.colors_by_id[color_id]
        # an id the palette does not know still prints; show it as neutral grey
        return Color(id=color_id or "any", name=color_id or "Any colour", hex="#9D9D9D")


_COLOR_RE = re.compile(
    r"\{\s*id:\s*'([^']+)',\s*name:\s*'([^']+)',\s*hex:\s*'(#[0-9A-Fa-f]{6})'"
)


def parse_colors(ts_source: str) -> list[Color]:
    return [Color(id=m[0], name=m[1], hex=m[2].upper()) for m in _COLOR_RE.findall(ts_source)]


def _read(rel: str) -> tuple[bytes, str]:
    if config.SORTER_REPO:
        p = Path(config.SORTER_REPO) / rel
        return p.read_bytes(), str(p)
    url = f"{config.RAW_BASE}/{rel}"
    r = httpx.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.content, url


_lock = threading.Lock()
_cached: Catalog | None = None


def load_catalog(force: bool = False) -> Catalog:
    """The catalog, fetched at most once per CATALOG_TTL_S."""
    global _cached
    with _lock:
        fresh = _cached and (time.time() - _cached.fetched_at) < config.CATALOG_TTL_S
        if _cached and fresh and not force:
            return _cached
        try:
            raw_bytes, source = _read(config.CATALOG_PATH)
            colors_bytes, _ = _read(config.COLORS_PATH)
        except Exception:
            if _cached:  # keep serving the last good copy if the source is down
                return _cached
            raise
        _cached = Catalog(
            raw=json.loads(raw_bytes),
            colors=parse_colors(colors_bytes.decode("utf-8")),
            source=source,
            fetched_at=time.time(),
        )
        return _cached


def set_catalog_for_tests(cat: Catalog) -> None:
    global _cached
    with _lock:
        _cached = cat
