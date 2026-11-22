import json
import zipfile
from xml.etree import ElementTree as ET

import numpy as np

from sorter3mf.printers import get_printer, layout, project_settings
from sorter3mf.threemf import (FORBIDDEN_NAME_CHARS, MeshData, ObjectSpec, PlateSpec, bambu_name, column_count,
                               plate_origin, write_project)

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def cube(size=10.0):
    v = np.array([[x, y, z] for x in (-size / 2, size / 2) for y in (-size / 2, size / 2) for z in (0, size)], dtype=np.float32)
    t = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4],
                  [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]], dtype=np.int32)
    return v, t


def test_plate_grid_matches_bambu_studio():
    # PartPlate.hpp compute_colum_count; checked against a Bambu Studio CLI export
    assert [column_count(n) for n in (1, 2, 3, 4, 5, 8, 9, 10, 36)] == [1, 2, 2, 2, 3, 3, 3, 4, 6]
    bed = get_printer("bambu-lab-a1").bed
    assert plate_origin(0, 8, bed) == (0.0, 0.0)
    x, y = plate_origin(7, 8, bed)  # row 2, column 1 of a 3-column grid
    assert (round(x, 1), round(y, 1)) == (307.2, -614.4)


def test_project_settings_expand_per_filament():
    p = get_printer("bambu-lab-a1")
    colours = ["#000000", "#FFFFFF", "#9B9EA0"]
    s = project_settings(p, "Bambu PLA Matte", colours, {"sparse_infill_density": "25%"})
    lay = layout()
    for k in lay["per_filament"]:
        assert len(s[k]) == 3, k
    for k in lay["process_filaments_printer"]:
        assert len(s[k]) == 5, k
    assert len(s["flush_volumes_matrix"]) == 9
    assert s["filament_colour"] == colours
    assert s["sparse_infill_density"] == "25%"
    assert "sparse_infill_density" in s["different_settings_to_system"][0]
    assert s["printer_settings_id"] == "Bambu Lab A1 0.4 nozzle"


def test_written_project_places_instances_on_their_plates(tmp_path):
    printer = get_printer("bambu-lab-a1")
    v, t = cube()
    meshes = {"cube": MeshData("cube", v, t, "cube.stl")}
    plates = [PlateSpec(f"P{i}", [ObjectSpec("cube", "cube", 1, 50 + 10 * i, 60, 90.0 if i % 2 else 0.0,
                                             {"enable_support": "1"})]) for i in range(5)]
    out = tmp_path / "t.3mf"
    write_project(out, bed=printer.bed, plates=plates, meshes=meshes,
                  settings=project_settings(printer, "Bambu PLA Matte", ["#000000"]),
                  app_version=printer.bambu_studio_version, title="t")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"3D/3dmodel.model", "Metadata/model_settings.config", "Metadata/project_settings.config",
                "3D/Objects/object_1.model", "[Content_Types].xml", "_rels/.rels"} <= names
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        json.loads(z.read("Metadata/project_settings.config"))
    items = {i.get("objectid"): [float(x) for x in i.get("transform").split()] for i in root.find("m:build", NS)}
    plates_xml = cfg.findall("plate")
    assert len(plates_xml) == 5
    for idx, pl in enumerate(plates_xml):
        ox, oy = plate_origin(idx, 5, printer.bed)
        for mi in pl.findall("model_instance"):
            oid = next(m.get("value") for m in mi.findall("metadata") if m.get("key") == "object_id")
            tx, ty = items[oid][9], items[oid][10]
            assert ox <= tx <= ox + printer.bed.width and oy <= ty <= oy + printer.bed.depth
    obj = cfg.find("object")
    assert any(m.get("key") == "enable_support" for m in obj.findall("metadata"))


def test_names_bambu_studio_refuses_are_cleaned(tmp_path):
    assert bambu_name("Overhead camera mount — A/B connector") == "Overhead camera mount — A-B connector"
    assert bambu_name('a<b>:c|d?e*f"g\\h') == "a(b) -c-def'g-h"
    printer = get_printer("bambu-lab-a1")
    v, t = cube()
    out = tmp_path / "n.3mf"
    write_project(out, bed=printer.bed, plates=[PlateSpec("Charcoal 1/3", [ObjectSpec("cube", "A/B: part", 1, 50, 50)])],
                  meshes={"cube": MeshData("cube", v, t, "cube.stl")},
                  settings=project_settings(printer, "Bambu PLA Matte", ["#000000"]),
                  app_version=printer.bambu_studio_version, title="t")
    with zipfile.ZipFile(out) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    names = [m.get("value") for m in cfg.iter("metadata") if m.get("key") in ("name", "plater_name")]
    assert names and not any(set(n) & set(FORBIDDEN_NAME_CHARS) for n in names), names


def test_overrides_fill_every_nozzle_variant():
    from sorter3mf.build import RECOMMENDED, PrintOptions, print_overrides
    x1 = get_printer("bambu-lab-x1-carbon")
    assert len(x1.settings["outer_wall_speed"]) == 2
    s = project_settings(x1, "Bambu PLA Matte", ["#000000"], print_overrides(PrintOptions(**RECOMMENDED)))
    assert s["outer_wall_speed"] == ["80", "80"]
    assert s["outer_wall_acceleration"] == ["2500", "2500"]
    assert s["wall_loops"] == "3" and s["sparse_infill_pattern"] == "gyroid"
    changed = s["different_settings_to_system"][0].split(";")
    assert {"outer_wall_speed", "outer_wall_acceleration", "wall_loops", "sparse_infill_pattern"} <= set(changed)
    # the defaults leave walls and the outer wall to the preset
    keep = project_settings(x1, "Bambu PLA Matte", ["#000000"], print_overrides(PrintOptions()))
    assert keep["outer_wall_speed"] == x1.settings["outer_wall_speed"]
    assert keep["outer_wall_acceleration"] == x1.settings["outer_wall_acceleration"]
    assert keep["wall_loops"] == x1.settings["wall_loops"]
    assert keep["sparse_infill_pattern"] == "gyroid"
    # the plate type is a project choice, not a change to the process preset
    plate = project_settings(x1, "Bambu PLA Matte", ["#000000"], {"curr_bed_type": "Textured PEI Plate"})
    assert plate["curr_bed_type"] == "Textured PEI Plate"
    assert "curr_bed_type" not in plate["different_settings_to_system"][0]
