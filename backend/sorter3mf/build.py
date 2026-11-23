"""From a machine config to finished .3mf files.

    BOM lines (bom.py) -> one piece per printed copy -> grouped (by colour, or
    by section and colour) -> packed onto plates (packing.py) -> split into
    projects of at most 36 plates -> written (threemf.py).

The slow parts (downloading and preparing meshes) report progress through a
callback so the job runner can show it.
"""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from . import config
from .bom import BomLine, BuildConfig, build_bom
from .catalog import Catalog
from .packing import PackItem, Rect, center_bin, outline_fits, pack
from .palettes import Palette, palette_for
from .palettes import resolve as resolve_color
from .parts import PreparedPart, fetch_stl, prepare
from .printers import Printer, get_printer, project_settings
from .threemf import MAX_PLATES, MeshData, ObjectSpec, PlateSpec, write_project

Progress = Callable[[str, float, str], None]  # stage, fraction 0..1, message

BED_TYPES = ["Textured PEI Plate", "Cool Plate", "Engineering Plate", "High Temp Plate", "Supertack Plate"]
INFILL_PATTERNS = ["gyroid", "adaptivecubic", "grid", "cubic", "triangles", "crosshatch", "lightning", "zig-zag"]
BRIMS = {"auto": "auto_brim", "none": "no_brim", "outer": "outer_only"}
# A plate type is usable with a filament when the filament profile gives it a
# bed temperature; 0 means "not for this plate" (PETG on the Cool Plate, PLA
# Matte on the Engineering Plate), and Bambu Studio will not slice it.
BED_TEMP_KEYS = {"Textured PEI Plate": "textured_plate_temp", "Cool Plate": "cool_plate_temp",
                 "Engineering Plate": "eng_plate_temp", "High Temp Plate": "hot_plate_temp",
                 "Supertack Plate": "supertack_plate_temp"}


def bed_types_for(printer: Printer, filament: str) -> list[str]:
    vals = printer.filaments.get(filament, {})
    out = []
    for bed, key in BED_TEMP_KEYS.items():
        try:
            if float(str(vals.get(key, "0")).strip() or 0) > 0:
                out.append(bed)
        except ValueError:
            pass
    return out


def grams_factor(cat: Catalog, printer: Printer, filament: str) -> float:
    """The catalog's grams were sliced in its own filament (PLA Matte). Same
    volume, other filament: scale by density."""
    try:
        mine = float(str(printer.filaments[filament]["filament_density"]).strip())
        theirs = float(cat.settings.get("density_g_cm3") or 0)
        return mine / theirs if mine > 0 and theirs > 0 else 1.0
    except (KeyError, ValueError):
        return 1.0


# What the Sorter community prints these parts with: a slower, gentler outer
# wall, a third wall and gyroid infill. Bambu's 0.20 mm Standard preset has 2
# walls, grid infill, a 200 mm/s outer wall at 5000-6000 mm/s^2. Gyroid is the
# default; walls and the outer wall keep the preset unless set (the UI's
# "Recommended" fills these in).
RECOMMENDED = {"wall_loops": 3, "infill_pattern": "gyroid", "outer_wall_speed": 80.0,
               "outer_wall_acceleration": 2500}


@dataclass
class PrintOptions:
    printer: str = "bambu-lab-a1"
    filament: str = "Bambu PLA Matte"
    bed_type: str = "Textured PEI Plate"
    layer_height: float = 0.2
    infill_density: int = 15
    infill_pattern: str = RECOMMENDED["infill_pattern"]
    # None keeps the process preset's value
    wall_loops: int | None = None
    outer_wall_speed: float | None = None  # mm/s
    outer_wall_acceleration: int | None = None  # mm/s^2
    brim: str = "auto"
    supports: str = "catalog"  # catalog | tree | off: for parts the catalog prints with support
    spacing_mm: float = 4.0  # between parts
    edge_mm: float = 2.0  # from the bed's edge
    # Extra room on every side of a part printed with supports. Supports
    # reach past the part's own outline, tree supports much further (a tall
    # part's branches route around it), and Bambu Studio refuses a plate whose
    # toolpaths cross ("gcode path conflicts"). None picks the default for the
    # support type: 8 mm normal, 20 mm tree, both checked by slicing full
    # builds with tools/validate_3mf.py (12 mm tree still conflicted).
    support_clearance_mm: float | None = None
    group_by: str = "color"  # color | section
    max_plates_per_file: int = MAX_PLATES


@dataclass
class PlacedPiece:
    part_id: str
    name: str
    uid: str
    color_id: str | None
    section: str
    x: float
    y: float
    rotation: float
    width: float
    depth: float


@dataclass
class Plate:
    name: str
    color_id: str | None
    section: str | None
    color_name: str
    color_hex: str
    pieces: list[PlacedPiece]
    oversize: bool = False
    grams: float = 0.0
    seconds: int = 0


@dataclass
class OutputFile:
    name: str
    path: Path
    plates: list[int]  # indexes into BuildResult.plates
    colours: list[str]
    size: int = 0


@dataclass
class BuildResult:
    plates: list[Plate]
    files: list[OutputFile]
    warnings: list[str] = field(default_factory=list)
    footprints: dict[str, list[list[float]]] = field(default_factory=dict)  # part id -> hull
    bed: dict = field(default_factory=dict)


def print_overrides(opts: PrintOptions) -> dict[str, str]:
    o = {
        "curr_bed_type": opts.bed_type,
        "layer_height": f"{opts.layer_height:g}",
        "sparse_infill_density": f"{int(opts.infill_density)}%",
        "sparse_infill_pattern": opts.infill_pattern,
        "brim_type": BRIMS.get(opts.brim, "auto_brim"),
    }
    if opts.wall_loops:
        o["wall_loops"] = str(int(opts.wall_loops))
    if opts.outer_wall_speed:
        o["outer_wall_speed"] = f"{opts.outer_wall_speed:g}"
    if opts.outer_wall_acceleration:
        o["outer_wall_acceleration"] = str(int(opts.outer_wall_acceleration))
    return o


def support_settings(part: dict, opts: PrintOptions, cat: Catalog) -> dict[str, str]:
    """Per-object support for parts the catalog slices with support on."""
    if not part.get("support_intentional") or opts.supports == "off":
        return {}
    s = {"enable_support": "1"}
    if opts.supports == "tree":
        s["support_type"] = "tree(auto)"
    else:
        s["support_type"] = cat.settings.get("support_type") or "normal(auto)"
        th = cat.settings.get("support_threshold_deg")
        if th:
            s["support_threshold_angle"] = str(int(th))
    return s


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "sorter"


def prepare_parts(lines: list[BomLine], progress: Progress) -> tuple[dict[str, PreparedPart], list[str]]:
    """Download (or reuse) and pose every STL the BOM prints."""
    wanted = {l.id: l for l in lines if l.to_print > 0}
    out: dict[str, PreparedPart] = {}
    errors: list[str] = []
    total = len(wanted) or 1
    done = 0
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client, \
            ThreadPoolExecutor(max_workers=config.DOWNLOAD_WORKERS) as pool:
        futs = {pool.submit(lambda l=l: prepare(l.id, fetch_stl(l.stl_url, client), l.stl_url)): pid
                for pid, l in wanted.items()}
        for f in as_completed(futs):
            pid = futs[f]
            try:
                out[pid] = f.result()
            except Exception as e:  # one bad part should not sink the build
                errors.append(f"{wanted[pid].part['name']}: could not be prepared ({e})")
            done += 1
            progress("parts", done / total, f"Preparing parts {done}/{len(wanted)}")
    return out, errors


def plan_plates(cat: Catalog, lines: list[BomLine], prepared: dict[str, PreparedPart],
                printer: Printer, opts: PrintOptions, palette: Palette | None = None,
                gfactor: float = 1.0) -> tuple[list[Plate], list[str]]:
    bed = printer.bed
    palette = palette or palette_for(cat, opts.filament)
    warnings: list[str] = []
    section_order = {s["id"]: i for i, s in enumerate(cat.sections)}
    section_name = {s["id"]: s["name"] for s in cat.sections}
    role_order = {}
    for i, r in enumerate(cat.color_roles):
        role_order.setdefault(resolve_color(palette, cat, r["default"]).id, i)

    groups: dict[tuple, list[PackItem]] = {}
    for l in lines:
        pp = prepared.get(l.id)
        if pp is None or l.to_print <= 0:
            continue
        if pp.height > bed.height:
            warnings.append(f"{l.part['name']} is {pp.height:.0f} mm tall, taller than the "
                            f"{printer.name}'s {bed.height:.0f} mm build height.")
        clear = opts.support_clearance_mm
        if clear is None:
            clear = 20.0 if opts.supports == "tree" else 8.0
        pad = 2 * clear if support_settings(l.part, opts, cat) else 0.0
        for u in l.left:
            key = (u.section, u.color_id) if opts.group_by == "section" else (None, u.color_id)
            for _ in range(u.count):
                groups.setdefault(key, []).append(PackItem((l, u), pp.width + pad, pp.depth + pad))

    def gkey(k):
        sec, col = k
        return (section_order.get(sec, 99) if sec else 0, role_order.get(col, 50), col or "")

    blocked = [Rect(x0 - bed.origin[0], y0 - bed.origin[1], x1 - x0, y1 - y0) for x0, y0, x1, y1 in bed.exclude]
    plates: list[Plate] = []
    too_big: dict[str, int] = {}
    for k in sorted(groups, key=gkey):
        sec, col = k
        bins = pack(groups[k], bed.width, bed.depth, opts.spacing_mm, opts.edge_mm, blocked)
        for b in bins:
            if b.oversize:
                # The packer works with boxes. A round part whose box clips
                # an excluded corner can still sit centred on its own plate:
                # check the real outline before calling it too big.
                p = b.placements[0]
                l, _ = p.item.key
                ang = math.pi / 2 if p.rotated else 0.0
                c, s = math.cos(ang), math.sin(ang)
                poly = [(p.x + x * c - y * s, p.y + x * s + y * c) for x, y in prepared[l.id].hull.tolist()]
                if len(poly) >= 3 and outline_fits(poly, bed.width, bed.depth, opts.edge_mm, blocked, opts.spacing_mm):
                    b.oversize = False
            else:
                center_bin(b, bed.width, bed.depth, opts.spacing_mm, opts.edge_mm, blocked)
        colour = resolve_color(palette, cat, col)
        label = colour.name
        if sec:
            label = f"{section_name.get(sec, sec)} · {label}"
        for bi, b in enumerate(bins):
            name = f"{label} {bi + 1} of {len(bins)}" if len(bins) > 1 else label
            pieces = []
            grams = 0.0
            secs = 0
            for p in b.placements:
                l, u = p.item.key
                pp = prepared[l.id]
                pieces.append(PlacedPiece(
                    part_id=l.id, name=l.part["name"], uid=l.part.get("uid", ""), color_id=u.color_id,
                    section=u.section, x=round(p.x, 3), y=round(p.y, 3), rotation=90.0 if p.rotated else 0.0,
                    width=pp.width, depth=pp.depth))
                grams += (l.part.get("grams") or 0) * gfactor
                secs += l.part.get("print_seconds") or 0
            if b.oversize:
                big = pieces[0]
                too_big[big.part_id] = too_big.get(big.part_id, 0) + 1
            plates.append(Plate(name=name, color_id=col, section=sec, color_name=colour.name, color_hex=colour.hex,
                                pieces=pieces,
                                oversize=b.oversize, grams=round(grams, 1), seconds=secs))
    for pid, n in too_big.items():
        pp = prepared[pid]
        name = cat.parts_by_id[pid]["name"]
        where = f"the {n} copies each get a plate of their own" if n > 1 else "it gets a plate of its own"
        warnings.append(f"{name} ({pp.width:.0f} x {pp.depth:.0f} mm) does not fit the {printer.name} bed: "
                        f"{where} and will not slice there.")
    return plates, warnings


def split_files(plates: list[Plate], per_file: int) -> list[list[int]]:
    """Plate indexes per project. A colour/section group is kept in one file
    when it fits; only a group bigger than a whole file is split."""
    per_file = max(1, min(per_file, MAX_PLATES))
    runs: list[list[int]] = []
    for i, p in enumerate(plates):
        key = (p.section, p.color_id)
        if runs and (plates[runs[-1][0]].section, plates[runs[-1][0]].color_id) == key:
            runs[-1].append(i)
        else:
            runs.append([i])
    files: list[list[int]] = [[]]
    for run in runs:
        if files[-1] and len(files[-1]) + len(run) > per_file:
            files.append([])
        for i in run:
            if len(files[-1]) >= per_file:
                files.append([])
            files[-1].append(i)
    return [f for f in files if f]


def run_build(cat: Catalog, cfg: BuildConfig, opts: PrintOptions, out_dir: Path,
              progress: Progress, basename: str = "sorter-v2-parts") -> BuildResult:
    printer = get_printer(opts.printer)
    if opts.filament not in printer.filaments:
        raise ValueError(f"{printer.name} has no {opts.filament} profile")
    if opts.bed_type not in bed_types_for(printer, opts.filament):
        raise ValueError(f"{opts.filament} is not printed on the {opts.bed_type} "
                         f"(its profile has no bed temperature for it)")
    progress("bom", 0.0, "Working out what to print")
    palette = palette_for(cat, opts.filament)
    lines = build_bom(cat, cfg, palette)
    if not any(l.to_print > 0 for l in lines):
        raise ValueError("Nothing to print: every part is switched off or already printed.")

    prepared, errors = prepare_parts(lines, progress)
    progress("pack", 0.0, "Arranging plates")
    plates, warnings = plan_plates(cat, lines, prepared, printer, opts, palette,
                                   grams_factor(cat, printer, opts.filament))
    warnings = errors + warnings
    for pp in prepared.values():
        if pp.note:
            name = cat.parts_by_id[pp.key]["name"]
            warnings.append(f"{name}: {pp.note}.")

    groups = split_files(plates, opts.max_plates_per_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = print_overrides(opts)
    files: list[OutputFile] = []
    by_id = {l.id: l for l in lines}
    for fi, idxs in enumerate(groups):
        progress("write", fi / max(1, len(groups)), f"Writing project {fi + 1}/{len(groups)}")
        colours: list[str] = []
        for i in idxs:
            for pc in plates[i].pieces:
                hx = resolve_color(palette, cat, pc.color_id).hex
                if hx not in colours:
                    colours.append(hx)
        plate_specs = []
        for i in idxs:
            objs = []
            for pc in plates[i].pieces:
                part = by_id[pc.part_id].part
                objs.append(ObjectSpec(
                    mesh_key=pc.part_id,
                    name=f"{pc.name} [{pc.uid}]" if pc.uid else pc.name,
                    extruder=colours.index(resolve_color(palette, cat, pc.color_id).hex) + 1,
                    x=pc.x, y=pc.y, rotation_deg=pc.rotation,
                    settings=support_settings(part, opts, cat)))
            plate_specs.append(PlateSpec(plates[i].name, objs))
        meshes = {pid: MeshData(pid, prepared[pid].vertices, prepared[pid].triangles,
                                by_id[pid].stl_url.rsplit("/", 1)[-1])
                  for pid in {pc.part_id for i in idxs for pc in plates[i].pieces}}
        name = f"{basename}.3mf" if len(groups) == 1 else f"{basename}-{fi + 1}-of-{len(groups)}.3mf"
        path = out_dir / _safe(name)
        write_project(
            path, bed=printer.bed, plates=plate_specs, meshes=meshes,
            settings=project_settings(printer, opts.filament, colours, overrides),
            app_version=printer.bambu_studio_version,
            title="Sorter V2 printed parts" + (f" ({fi + 1} of {len(groups)})" if len(groups) > 1 else ""),
            description="Generated by sorter-3dprint-helper from the Sorter V2 parts catalog.")
        files.append(OutputFile(name=path.name, path=path, plates=idxs, colours=colours, size=path.stat().st_size))
    progress("done", 1.0, "Done")

    footprints = {pid: pp.hull.round(2).tolist() for pid, pp in prepared.items()}
    bed = printer.bed
    return BuildResult(plates=plates, files=files, warnings=warnings, footprints=footprints,
                       bed={"width": bed.width, "depth": bed.depth,
                            "exclude": [[x0 - bed.origin[0], y0 - bed.origin[1], x1 - x0, y1 - y0]
                                        for x0, y0, x1, y1 in bed.exclude]})
