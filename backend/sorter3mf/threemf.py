"""Writing a Bambu Studio project (.3mf) with plates and print settings.

The layout follows what Bambu Studio itself writes (checked against a
project its CLI exported, see tools/validate_3mf.py):

- every distinct mesh is stored once, in 3D/Objects/object_<k>.model;
- each printed piece is its own object with one instance, whose component
  points at the shared mesh, placed by its build item transform;
- Metadata/model_settings.config names the objects, assigns each a filament
  ("extruder") and per-object settings, and lists which instances sit on
  which plate;
- Metadata/project_settings.config carries the full printer/process/
  filament settings (see printers.project_settings).

Plates are laid out the way Bambu Studio lays them out, in a grid of
ceil-ish(sqrt(n)) columns, each plate 1.2 bed widths/depths from the last
(PartPlate.cpp: compute_colum_count, compute_shape_position,
LOGICAL_PART_PLATE_GAP = 1/5). An instance belongs on a plate only if it sits
inside that plate's square, so positions are computed the same way.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

from .printers import Bed

MAX_PLATES = 36  # PartPlate.hpp MAX_PLATE_COUNT
PLATE_GAP = 1.0 / 5.0


def column_count(n: int) -> int:
    value = math.sqrt(n)
    rounded = round(value)
    return rounded + 1 if value > rounded else rounded


def plate_origin(index: int, n_plates: int, bed: Bed) -> tuple[float, float]:
    cols = column_count(n_plates)
    row, col = divmod(index, cols)
    return col * bed.width * (1 + PLATE_GAP), -row * bed.depth * (1 + PLATE_GAP)


@dataclass
class MeshData:
    key: str
    vertices: np.ndarray
    triangles: np.ndarray
    source_name: str


@dataclass
class ObjectSpec:
    mesh_key: str
    name: str
    extruder: int  # 1-based filament slot
    x: float  # centre of the piece on the plate, bed coordinates
    y: float
    rotation_deg: float = 0.0  # about z
    settings: dict[str, str] = field(default_factory=dict)


@dataclass
class PlateSpec:
    name: str
    objects: list[ObjectSpec]


# Bambu Studio refuses to open a project with any of these in an object or
# plate name ("Invalid name, the following characters are not allowed"). Its
# CLI does not check, so tools/validate_3mf.py checks for them separately.
FORBIDDEN_NAME_CHARS = '<>:/\\|?*"'
_NAME_MAP = {"/": "-", "\\": "-", "|": "-", ":": " -", '"': "'", "<": "(", ">": ")", "?": "", "*": ""}


def bambu_name(name: str) -> str:
    """A name Bambu Studio accepts: forbidden characters swapped for the
    nearest harmless ones ("A/B connector" -> "A-B connector")."""
    out = "".join(_NAME_MAP.get(ch, ch) for ch in name)
    return " ".join(out.split()) or "part"


def _transform(rot_deg: float, x: float, y: float, z: float = 0.0) -> str:
    # 3MF applies a transform to row vectors: p' = p . M, so M is the
    # transpose of the usual column-vector rotation matrix.
    a = math.radians(rot_deg)
    c, s = math.cos(a), math.sin(a)
    if abs(c) < 1e-12:
        c = 0.0
    if abs(s) < 1e-12:
        s = 0.0
    m = [c, s, 0, -s, c, 0, 0, 0, 1, x, y, z]
    return " ".join(f"{v:.6f}".rstrip("0").rstrip(".") if v != 0 else "0" for v in m)


def _mesh_model(object_id: int, mesh: MeshData) -> str:
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        ' <resources>\n'
        f'  <object id="{object_id}" p:UUID="{uuid.uuid4()}" type="model">\n'
        '   <mesh>\n    <vertices>\n'
    )
    verts = "".join(
        f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n' for x, y, z in mesh.vertices.tolist()
    )
    tris = "".join(
        f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n' for a, b, c in mesh.triangles.tolist()
    )
    tail = "    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n"
    return head + verts + "    </vertices>\n    <triangles>\n" + tris + tail


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def write_project(path: Path, *, bed: Bed, plates: list[PlateSpec], meshes: dict[str, MeshData],
                  settings: dict, app_version: str, title: str, description: str = "") -> None:
    if not plates:
        raise ValueError("no plates to write")
    if len(plates) > MAX_PLATES:
        raise ValueError(f"Bambu Studio opens at most {MAX_PLATES} plates per project, got {len(plates)}")

    used = []
    for pl in plates:
        for ob in pl.objects:
            if ob.mesh_key not in used:
                used.append(ob.mesh_key)
    mesh_ids = {k: i + 1 for i, k in enumerate(used)}  # sub-model object ids 1..M
    mesh_files = {k: f"3D/Objects/object_{mesh_ids[k]}.model" for k in used}

    today = _dt.date.today().isoformat()
    n_plates = len(plates)
    root = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n',
        f' <metadata name="Application">BambuStudio-{app_version}</metadata>\n',
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n',
        f' <metadata name="CreationDate">{today}</metadata>\n',
        f' <metadata name="Description">{_xml_text(description)}</metadata>\n',
        f' <metadata name="ModificationDate">{today}</metadata>\n',
        f' <metadata name="Title">{_xml_text(title)}</metadata>\n',
        ' <resources>\n',
    ]
    build = [f' <build p:UUID="{uuid.uuid4()}">\n']
    cfg = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    plate_xml = []

    next_id = len(used) + 1
    identify = 1000
    for pi, pl in enumerate(plates):
        ox, oy = plate_origin(pi, n_plates, bed)
        instances = []
        for ob in pl.objects:
            oid = next_id
            next_id += 1
            mk = ob.mesh_key
            mesh = meshes[mk]
            root.append(
                f'  <object id="{oid}" p:UUID="{uuid.uuid4()}" type="model">\n'
                '   <components>\n'
                f'    <component p:path="/{mesh_files[mk]}" objectid="{mesh_ids[mk]}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
                '   </components>\n'
                '  </object>\n'
            )
            wx = ox + bed.origin[0] + ob.x
            wy = oy + bed.origin[1] + ob.y
            build.append(
                f'  <item objectid="{oid}" p:UUID="{uuid.uuid4()}" transform="{_transform(ob.rotation_deg, wx, wy)}" printable="1"/>\n'
            )
            faces = int(len(mesh.triangles))
            name = bambu_name(ob.name)
            meta = [f'    <metadata key="name" value={quoteattr(name)}/>\n',
                    f'    <metadata key="extruder" value="{ob.extruder}"/>\n']
            meta += [f'    <metadata key={quoteattr(k)} value={quoteattr(str(v))}/>\n' for k, v in ob.settings.items()]
            cfg.append(
                f'  <object id="{oid}">\n' + "".join(meta) +
                f'    <metadata face_count="{faces}"/>\n'
                f'    <part id="{mesh_ids[mk]}" subtype="normal_part" uuid="{uuid.uuid4()}">\n'
                f'      <metadata key="name" value={quoteattr(name)}/>\n'
                '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                f'      <metadata key="source_file" value={quoteattr(mesh.source_name)}/>\n'
                '      <metadata key="source_object_id" value="0"/>\n'
                '      <metadata key="source_volume_id" value="0"/>\n'
                '      <metadata key="source_offset_x" value="0"/>\n'
                '      <metadata key="source_offset_y" value="0"/>\n'
                '      <metadata key="source_offset_z" value="0"/>\n'
                f'      <mesh_stat face_count="{faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
                '    </part>\n'
                '  </object>\n'
            )
            identify += 1
            instances.append(
                '    <model_instance>\n'
                f'      <metadata key="object_id" value="{oid}"/>\n'
                '      <metadata key="instance_id" value="0"/>\n'
                f'      <metadata key="identify_id" value="{identify}"/>\n'
                '    </model_instance>\n'
            )
        plate_xml.append(
            '  <plate>\n'
            f'    <metadata key="plater_id" value="{pi + 1}"/>\n'
            f'    <metadata key="plater_name" value={quoteattr(bambu_name(pl.name))}/>\n'
            '    <metadata key="locked" value="false"/>\n'
            '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
            '    <metadata key="gcode_file" value=""/>\n'
            + "".join(instances) +
            '  </plate>\n'
        )
    root.append(' </resources>\n')
    build.append(' </build>\n')
    root += build
    root.append('</model>\n')
    cfg += plate_xml
    cfg.append('  <assemble>\n  </assemble>\n</config>\n')

    rels = ['<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n']
    for k in used:
        rels.append(f' <Relationship Target="/{mesh_files[k]}" Id="rel-{mesh_ids[k]}" '
                    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n')
    rels.append('</Relationships>\n')

    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        f'    <header_item key="X-BBL-Client-Version" value="{app_version}"/>\n'
        '  </header>\n</config>\n'
    )
    sequence = {f"plate_{i + 1}": {"nozzle_sequence": [], "optimal_assignment": [], "sequence": []}
                for i in range(n_plates)}

    tmp = path.with_suffix(".partial")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("3D/3dmodel.model", "".join(root))
        z.writestr("3D/_rels/3dmodel.model.rels", "".join(rels))
        for k in used:
            z.writestr(mesh_files[k], _mesh_model(mesh_ids[k], meshes[k]))
        z.writestr("Metadata/model_settings.config", "".join(cfg))
        z.writestr("Metadata/project_settings.config", json.dumps(settings, indent=4))
        z.writestr("Metadata/slice_info.config", slice_info)
        z.writestr("Metadata/filament_sequence.json", json.dumps(sequence, separators=(",", ":")))
    tmp.replace(path)


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
