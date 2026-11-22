from sorter3mf.bom import BuildConfig, build_bom
from sorter3mf.build import bed_types_for
from sorter3mf.catalog import Catalog, Color
from sorter3mf.palettes import line_of, nearest, palette_for, resolve
from sorter3mf.printers import get_printer, project_settings

CATALOG_COLORS = [Color("charcoal", "Charcoal", "#000000"), Color("ash-gray", "Ash Gray", "#9B9EA0"),
                  Color("ivory-white", "Ivory White", "#FFFFFF"), Color("marine-blue", "Marine Blue", "#0078BF")]


def cat(parts=()):
    raw = {"sections": [{"id": "feeder", "name": "Feeder", "scales_with_layers": False}],
           "color_roles": [{"id": "frame", "name": "Frame", "default": "charcoal"}],
           "parts": list(parts), "assemblies": [], "settings": {"density_g_cm3": 1.32}}
    return Catalog(raw=raw, colors=CATALOG_COLORS, source="t", fetched_at=0)


def test_lines():
    assert line_of("Bambu PETG Matte") == "PETG Matte"
    assert line_of("Bambu PLA Matte") == "PLA Matte"
    assert line_of("Generic PLA") == "PLA Matte"  # no palette of its own: the catalog's


def test_catalog_colours_carry_over_to_petg_matte():
    c = cat()
    petg = palette_for(c, "Bambu PETG Matte")
    assert len(petg.colors) == 17
    assert resolve(petg, c, "charcoal").name == "Black"
    assert resolve(petg, c, "ash-gray").name == "Gray"
    assert resolve(petg, c, "ivory-white").name == "White"
    assert resolve(petg, c, "gray").name == "Gray"  # already a PETG Matte id
    # an id from another Bambu line moves by its colour
    assert resolve(petg, c, "dark-gray").name in ("Gray", "Black")
    pla = palette_for(c, "Bambu PLA Matte")
    assert resolve(pla, c, "charcoal").id == "charcoal"
    assert nearest(petg, "#0078BF").name in ("Cyan", "Dark Blue")


def test_bom_colours_are_in_the_filament_palette():
    stator = {"id": "stator", "name": "Stator", "uid": "s", "quantities": {"feeder": 2},
              "color": {"fixed": "ash-gray", "why": "camera"}, "stl": "https://x/stator-000000000000.stl"}
    frame = {"id": "frame", "name": "Frame", "uid": "f", "quantities": {"feeder": 3},
             "color": {"role": "frame"}, "stl": "https://x/frame-000000000000.stl"}
    c = cat([stator, frame])
    lines = {l.id: l for l in build_bom(c, BuildConfig(excluded=[]), palette_for(c, "Bambu PETG Matte"))}
    assert {u.color_id for u in lines["stator"].units} == {"gray"}
    assert {u.color_id for u in lines["frame"].units} == {"black"}
    # a role colour chosen in the PETG palette is kept as is
    lines = {l.id: l for l in build_bom(c, BuildConfig(excluded=[], role_colors={"frame": "turquoise"}),
                                       palette_for(c, "Bambu PETG Matte"))}
    assert {u.color_id for u in lines["frame"].units} == {"turquoise"}


def test_plate_types_follow_the_filament():
    a1 = get_printer("bambu-lab-a1")
    assert "Cool Plate" not in bed_types_for(a1, "Bambu PETG Matte")
    assert "Textured PEI Plate" in bed_types_for(a1, "Bambu PETG Matte")
    assert "Engineering Plate" not in bed_types_for(a1, "Bambu PLA Matte")
    assert "Cool Plate" in bed_types_for(a1, "Bambu PLA Matte")


def test_petg_project_settings_name_the_petg_profile():
    a1 = get_printer("bambu-lab-a1")
    s = project_settings(a1, "Bambu PETG Matte", ["#000000", "#7F7E83"])
    assert s["filament_settings_id"] == ["Bambu PETG Matte @BBL A1"] * 2
    assert s["filament_type"] == ["PETG", "PETG"]
