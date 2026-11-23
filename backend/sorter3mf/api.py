"""HTTP API (FastAPI). Run with:  uv run uvicorn sorter3mf.api:app --reload

  GET  /api/options                 everything the settings form needs
  POST /api/bom                     the parts list for a config (no downloads)
  POST /api/jobs                    start building the .3mf files
  GET  /api/jobs/{id}               progress, then the plates and files
  GET  /api/jobs/{id}/files/{name}  one finished .3mf
  GET  /api/jobs/{id}/zip           all of them in one zip
"""

from __future__ import annotations

import io
import zipfile
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import config, jobs
from .bom import (ALTERNATIVES, ANY_COLOR, DEFAULT_LAYERS, BuildConfig, build_bom, default_excluded,
                  default_role_colors, required_color, selection_tree)
from .build import BED_TYPES, BRIMS, INFILL_PATTERNS, RECOMMENDED, PrintOptions, bed_types_for, grams_factor
from .catalog import load_catalog
from .palettes import all_palettes, line_of, palette_for
from .palettes import resolve as resolve_color
from .printers import printers

app = FastAPI(title="Sorter V2 3D print helper", version="0.1.0")


class BuildRequest(BaseModel):
    # the machine
    layers: list[Literal["third", "half"]] = Field(default_factory=lambda: list(DEFAULT_LAYERS), max_length=16)
    # assembly-tree places not to print (see /api/bom "tree"); None = the default (no bins)
    excluded: Optional[list[str]] = Field(None, max_length=5000)
    include_optional: bool = True
    alternatives: dict[str, str] = Field(default_factory=dict)
    role_colors: dict[str, str] = Field(default_factory=dict)
    qty_overrides: dict[str, int] = Field(default_factory=dict)
    engrave_ids: bool = True
    # colours not to print: ids of the filament's palette ("any" for a part
    # with no colour); see /api/bom "colors"
    excluded_colors: list[str] = Field(default_factory=list, max_length=500)
    # pieces already printed: part id -> colour id (as above) -> count
    printed: dict[str, dict[str, int]] = Field(default_factory=dict, max_length=5000)
    # the printer and print settings
    printer: str = "bambu-lab-a1"
    filament: str = "Bambu PLA Matte"
    bed_type: str = "Textured PEI Plate"
    layer_height: float = Field(0.2, ge=0.08, le=0.32)
    infill_density: int = Field(15, ge=0, le=100)
    infill_pattern: str = RECOMMENDED["infill_pattern"]
    # None keeps the process preset's value
    wall_loops: Optional[int] = Field(None, ge=1, le=10)
    outer_wall_speed: Optional[float] = Field(None, ge=10, le=1000)
    outer_wall_acceleration: Optional[int] = Field(None, ge=200, le=30000)
    brim: Literal["auto", "none", "outer"] = "auto"
    supports: Literal["catalog", "tree", "off"] = "catalog"
    spacing_mm: float = Field(4.0, ge=1, le=30)
    edge_mm: float = Field(2.0, ge=0, le=20)
    group_by: Literal["color", "section"] = "color"
    # turn parts exported on an edge or upside down onto a flat face
    auto_orient: bool = True

    @field_validator("qty_overrides")
    @classmethod
    def _qty(cls, v: dict[str, int]) -> dict[str, int]:
        for k, n in v.items():
            if n < 0 or n > 1000:
                raise ValueError(f"quantity for {k} must be 0..1000")
        return v

    @field_validator("printed")
    @classmethod
    def _printed(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        for k, per in v.items():
            if len(per) > 100 or any(n < 0 or n > 10000 for n in per.values()):
                raise ValueError(f"printed counts for {k} must be 0..10000")
        return v

    @field_validator("bed_type")
    @classmethod
    def _bed(cls, v: str) -> str:
        if v not in BED_TYPES:
            raise ValueError(f"bed_type must be one of {BED_TYPES}")
        return v

    @field_validator("infill_pattern")
    @classmethod
    def _pattern(cls, v: str) -> str:
        if v not in INFILL_PATTERNS:
            raise ValueError(f"infill_pattern must be one of {INFILL_PATTERNS}")
        return v

    def split(self) -> tuple[BuildConfig, PrintOptions]:
        cfg = BuildConfig(layers=list(self.layers),
                          excluded=list(self.excluded) if self.excluded is not None else None,
                          include_optional=self.include_optional, alternatives=dict(self.alternatives),
                          role_colors=dict(self.role_colors), qty_overrides=dict(self.qty_overrides),
                          engrave_ids=self.engrave_ids, excluded_colors=list(self.excluded_colors),
                          printed={k: dict(v) for k, v in self.printed.items()})
        opts = PrintOptions(printer=self.printer, filament=self.filament, bed_type=self.bed_type,
                            layer_height=self.layer_height, infill_density=self.infill_density,
                            infill_pattern=self.infill_pattern, wall_loops=self.wall_loops,
                            outer_wall_speed=self.outer_wall_speed,
                            outer_wall_acceleration=self.outer_wall_acceleration, brim=self.brim,
                            supports=self.supports, spacing_mm=self.spacing_mm, edge_mm=self.edge_mm,
                            group_by=self.group_by, auto_orient=self.auto_orient)
        return cfg, opts


def _check_printer(req: BuildRequest) -> None:
    p = printers().get(req.printer)
    if not p:
        raise HTTPException(422, f"unknown printer {req.printer!r}")
    if req.filament not in p.filaments:
        raise HTTPException(422, f"{p.name} has no {req.filament} profile")
    if req.bed_type not in bed_types_for(p, req.filament):
        raise HTTPException(422, f"{req.filament} is not printed on the {req.bed_type}")


def _orientation_note(part: dict) -> str | None:
    for a in part.get("attributes") or []:
        if a.get("label") == "Print orientation":
            return a.get("value")
    return None


def _filament_order(names) -> list[str]:
    """PLA first, then PETG, Bambu before generic."""
    return sorted(names, key=lambda f: ("PETG" in f, f.startswith("Generic"), f))


def _all_filaments() -> list[str]:
    return _filament_order({f for p in printers().values() for f in p.filaments})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/options")
def options() -> dict:
    cat = load_catalog()
    return {
        "source_url": config.SOURCE_URL or None,
        "catalog": {"source": cat.source, "fetched_at": cat.fetched_at, "printer": cat.settings.get("printer"),
                    "process": cat.settings.get("process"), "filament": cat.settings.get("filament")},
        "sections": [{"id": s["id"], "name": s["name"], "scales_with_layers": bool(s.get("scales_with_layers"))}
                     for s in cat.sections],
        "color_roles": cat.color_roles,
        "colors": [{"id": c.id, "name": c.name, "hex": c.hex} for c in cat.colors],
        # one palette per filament line; "filaments" says which line a filament uses
        "palettes": {line: [{"id": c.id, "name": c.name, "hex": c.hex} for c in cols]
                     for line, cols in all_palettes(cat, _all_filaments()).items()},
        "filaments": {f: {"palette": line_of(f)} for f in _all_filaments()},
        "alternatives": [{"id": a["id"], "label": a["label"],
                          "options": [{"id": o["id"], "label": o["label"]} for o in a["options"]]}
                         for a in ALTERNATIVES],
        "printers": [{"id": p.id, "name": p.name, "process": p.process, "filaments": _filament_order(p.filaments),
                      "bed_types": {f: bed_types_for(p, f) for f in p.filaments},
                      "bed": {"width": p.bed.width, "depth": p.bed.depth, "height": p.bed.height},
                      "bambu_studio_version": p.bambu_studio_version}
                     for p in printers().values()],
        "bed_types": BED_TYPES,
        "infill_patterns": INFILL_PATTERNS,
        "brims": list(BRIMS),
        "recommended": RECOMMENDED,
        "defaults": {**BuildRequest().model_dump(), "role_colors": default_role_colors(cat),
                     "excluded": default_excluded(cat)},
    }


@app.post("/api/bom")
def bom(req: BuildRequest) -> dict:
    cat = load_catalog()
    cfg, opts = req.split()
    palette = palette_for(cat, opts.filament)
    printer = printers().get(opts.printer)
    gf = grams_factor(cat, printer, opts.filament) if printer else 1.0
    lines = build_bom(cat, cfg, palette)
    out = []
    for l in lines:
        p = l.part
        need = required_color(p)
        if need:
            need = {**need, "color_id": resolve_color(palette, cat, need["color_id"]).id}
        out.append({
            "id": l.id, "name": p["name"], "uid": p.get("uid"), "needed": l.needed, "qty": l.qty,
            "sections": list(p["quantities"]),
            "units": [{"section": u.section, "color_id": u.color_id, "count": u.count} for u in l.units],
            # what is left after the pieces already printed, and how many those were
            "left": [{"section": u.section, "color_id": u.color_id, "count": u.count} for u in l.left],
            "to_print": l.to_print, "printed": sum(l.printed.values()),
            "grams": round(p["grams"] * gf, 2) if p.get("grams") is not None else None,
            "print_seconds": p.get("print_seconds"),
            "optional": bool(p.get("optional")), "in_bins": l.in_bins,
            "support": bool(p.get("support_intentional")),
            "required_color": need,
            "orientation_note": _orientation_note(p),
            "low_tolerance": bool(p.get("low_tolerance")),
            "render": p.get("render"), "stl_url": l.stl_url,
        })
    printing = [l for l in lines if l.to_print > 0]
    # pieces per colour the ticked places still need, before the colour
    # filter, so the colours switched off still show what they hold
    per_color: dict[str, int] = {}
    for l in lines:
        for u in l.selected_units:
            cid = u.color_id or ANY_COLOR
            per_color[cid] = per_color.get(cid, 0) + u.count
    return {
        "palette": palette.id,
        "grams_factor": round(gf, 4),
        "tree": selection_tree(cat, cfg, lines),
        "colors": [{"id": cid, "count": n} for cid, n in sorted(per_color.items(), key=lambda x: (-x[1], x[0]))],
        "lines": out,
        "totals": {
            "part_types": len(printing),
            "pieces": sum(l.to_print for l in printing),
            "grams": round(sum(l.to_print * (l.part.get("grams") or 0) for l in printing) * gf, 1),
            "seconds": sum(l.to_print * (l.part.get("print_seconds") or 0) for l in printing),
            # pieces already printed, of what this machine needs
            "printed": sum(sum(l.printed.values()) for l in lines),
        },
    }


@app.post("/api/jobs")
def create_job(req: BuildRequest) -> dict:
    _check_printer(req)
    cfg, opts = req.split()
    job = jobs.submit(cfg, opts)
    return {"id": job.id}


def _job_or_404(jid: str) -> jobs.Job:
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "No such build (finished builds are kept for an hour).")
    return job


@app.get("/api/jobs/{jid}")
def job_status(jid: str) -> dict:
    job = _job_or_404(jid)
    out = {"id": job.id, "status": job.status, "stage": job.stage, "progress": round(job.progress, 3),
           "message": job.message, "error": job.error}
    r = job.result
    if r:
        file_of = {i: f.name for f in r.files for i in f.plates}
        out["result"] = {
            "bed": r.bed,
            "warnings": r.warnings,
            "footprints": r.footprints,
            "files": [{"name": f.name, "url": f"/api/jobs/{job.id}/files/{f.name}", "plates": f.plates,
                       "colours": f.colours, "size": f.size} for f in r.files],
            "zip_url": f"/api/jobs/{job.id}/zip" if len(r.files) > 1 else None,
            "plates": [{
                "index": i, "name": p.name, "file": file_of.get(i), "section": p.section,
                "color": {"id": p.color_id, "name": p.color_name, "hex": p.color_hex},
                "oversize": p.oversize, "grams": p.grams, "seconds": p.seconds,
                "pieces": [{"part_id": pc.part_id, "name": pc.name, "x": pc.x, "y": pc.y,
                            "rotation": pc.rotation, "w": pc.width, "d": pc.depth} for pc in p.pieces],
            } for i, p in enumerate(r.plates)],
        }
    return out


@app.get("/api/jobs/{jid}/files/{name}")
def job_file(jid: str, name: str) -> FileResponse:
    job = _job_or_404(jid)
    f = next((f for f in (job.result.files if job.result else []) if f.name == name), None)
    if not f or not f.path.exists():
        raise HTTPException(404, "No such file")
    return FileResponse(f.path, media_type="model/3mf", filename=f.name)


@app.get("/api/jobs/{jid}/zip")
def job_zip(jid: str) -> StreamingResponse:
    job = _job_or_404(jid)
    if not job.result:
        raise HTTPException(409, "The build has not finished")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:  # a 3mf is already compressed
        for f in job.result.files:
            z.write(f.path, f.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="sorter-v2-parts.zip"'})


if config.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
