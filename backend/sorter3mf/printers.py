"""Printer templates and the project settings Bambu Studio reads from a 3MF.

The templates in profiles/ were written by Bambu Studio itself (see
tools/make_profile_templates.py): the full `project_settings.config` for a
system printer + process + one filament. Building a project for N colours
expands the per-filament keys to N values, the way Bambu Studio's own
multi-filament exports are laid out (`_layout.json`).

A two-nozzle printer (H2C) prints every plate with its first nozzle: each
plate is one colour, so there is nothing for the second one to do. Every
filament is mapped to extruder 1 by hand ("Manual"), and the strip of bed that
nozzle cannot reach is kept clear like an excluded corner.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROFILES = Path(__file__).resolve().parent / "profiles"

# Settings that belong to the project, not to the process preset: changing
# them does not make the preset "modified" in Bambu Studio.
PROJECT_KEYS = {"curr_bed_type"}


@dataclass
class Bed:
    width: float
    depth: float
    origin: tuple[float, float]  # printable area min corner
    height: float
    exclude: list[tuple[float, float, float, float]]  # x0, y0, x1, y1 in bed coords


@dataclass
class Printer:
    id: str
    name: str
    machine: str
    process: str
    bambu_studio_version: str
    bed: Bed
    filaments: dict[str, dict]
    settings: dict
    extruders: int = 1

    @property
    def note(self) -> str | None:
        """What a user of this printer should know about the projects."""
        if self.extruders < 2:
            return None
        return (f"{self.extruders} nozzles: every plate is one colour, so all of it prints with the left "
                f"nozzle (filaments mapped by hand), on the {self.bed.width - _unreachable(self.bed):.0f} mm "
                f"of the bed it reaches.")


def _unreachable(bed: Bed) -> float:
    """Width of the strips added for the first nozzle's reach."""
    return sum(x1 - x0 for x0, y0, x1, y1 in bed.exclude if y1 - y0 >= bed.depth - 1e-6)


def _bed(doc: dict) -> Bed:
    pts = doc["printable_area"]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    excl = []
    if doc.get("bed_exclude_area"):
        ex = doc["bed_exclude_area"]
        exs = [p[0] for p in ex]
        eys = [p[1] for p in ex]
        if max(exs) > min(exs) and max(eys) > min(eys):
            excl.append((min(exs), min(eys), max(exs), max(eys)))
    # a multi-nozzle printer: keep to what the first nozzle reaches
    reach = (doc.get("extruder_printable_area") or [None])[0]
    if reach:
        a0, a1 = min(p[0] for p in reach), max(p[0] for p in reach)
        b0, b1 = min(p[1] for p in reach), max(p[1] for p in reach)
        for strip in ((x0, y0, a0, y1), (a1, y0, x1, y1), (x0, y0, x1, b0), (x0, b1, x1, y1)):
            if strip[2] - strip[0] > 1e-6 and strip[3] - strip[1] > 1e-6:
                excl.append(strip)
    return Bed(width=x1 - x0, depth=y1 - y0, origin=(x0, y0), height=doc["printable_height"], exclude=excl)


@lru_cache(maxsize=None)
def layout() -> dict:
    return json.loads((PROFILES / "_layout.json").read_text())


@lru_cache(maxsize=None)
def printers() -> dict[str, Printer]:
    out = {}
    for entry in json.loads((PROFILES / "_index.json").read_text()):
        doc = json.loads((PROFILES / f"{entry['id']}.json").read_text())
        out[doc["id"]] = Printer(
            id=doc["id"], name=doc["name"], machine=doc["machine"], process=doc["process"],
            bambu_studio_version=doc.get("bambu_studio_version") or "",
            bed=_bed(doc["bed"]), filaments=doc["filaments"], settings=doc["settings"],
            extruders=int(doc["bed"].get("extruders") or 1),
        )
    return out


def get_printer(printer_id: str) -> Printer:
    p = printers().get(printer_id)
    if not p:
        raise KeyError(f"unknown printer {printer_id!r}")
    return p


def _lightness(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def flush_volume(src: str, dst: str) -> int:
    """Purge volume (mm3) for a filament change, an approximation of Bambu
    Studio's colour-based estimate: going from dark to light needs much more
    than the reverse. Bambu Studio recalculates these when colours change."""
    if src.upper() == dst.upper():
        return 0
    return int(round(min(800, 108 + 581 * max(0.0, _lightness(dst) - _lightness(src)))))


def project_settings(printer: Printer, filament: str, colours: list[str],
                     overrides: dict[str, str] | None = None) -> dict:
    """The project settings for this printer with one filament slot per colour."""
    if filament not in printer.filaments:
        raise KeyError(f"{printer.name} has no {filament!r} profile")
    lay = layout()
    s = copy.deepcopy(printer.settings)
    base = copy.deepcopy(printer.settings)
    colours = colours or ["#FFFFFF"]
    n = len(colours)
    vals = printer.filaments[filament]
    for k in lay["per_filament"]:
        s[k] = [vals[k]] * n
    s["filament_colour"] = list(colours)
    if "filament_self_index" in s:
        s["filament_self_index"] = [str(i + 1) for i in range(n)]
    for k in lay["process_filaments_printer"]:
        v = base[k]  # [process, filament, printer] in the one-filament template
        s[k] = [v[0]] + [v[1]] * n + [v[-1]]
    for k in lay["filament_matrix"]:
        # N x N, once per extruder (the one-filament template has one value each)
        per_extruder = max(1, len(base.get(k) or [0]))
        s[k] = [str(flush_volume(a, b)) for a in colours for b in colours] * per_extruder
    if printer.extruders > 1:
        # every filament on the first (left) nozzle, chosen by hand so Bambu
        # Studio does not move one to the other nozzle
        s["filament_map"] = ["1"] * n
        s["filament_map_mode"] = "Manual"
        # The nozzles fitted, per extruder ("Standard#1": one standard-flow
        # nozzle; the H2C's second extruder changes between up to six). A
        # file without any does not slice ("No valid nozzle found"), so say
        # each extruder has one nozzle of its default kind; only the first
        # is used.
        kinds = s.get("default_nozzle_volume_type") or ["Standard"] * printer.extruders
        s["extruder_nozzle_stats"] = [f"{k}#1" for k in kinds]

    changed = []
    for k, v in (overrides or {}).items():
        if k not in s:
            continue
        if isinstance(s[k], list) and not isinstance(v, list):
            # per nozzle-variant settings (outer_wall_speed is ["200", "350"] on
            # an X1): the override applies to every variant
            v = [v] * len(s[k])
        if s[k] != v and k not in PROJECT_KEYS:
            changed.append(k)
        s[k] = v
    if changed and "different_settings_to_system" in s:
        # Bambu Studio shows the process preset as modified and lists these keys
        prev = [x for x in s["different_settings_to_system"][0].split(";") if x]
        s["different_settings_to_system"][0] = ";".join(sorted(set(prev) | set(changed)))
    return s
