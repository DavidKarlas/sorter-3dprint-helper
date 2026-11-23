from sorter3mf.bom import BuildConfig, apportion, build_bom
from sorter3mf.catalog import Catalog, Color


def part(pid, quantities, color=None, **kw):
    return {"id": pid, "name": pid, "uid": pid[:4], "quantities": quantities,
            "color": color or {"role": "frame"}, "stl": f"https://x/{pid}-000000000000.stl", **kw}


def catalog(parts, assemblies=()):
    raw = {
        "sections": [
            {"id": "feeder", "name": "Feeder", "scales_with_layers": False},
            {"id": "layer", "name": "Distribution frame", "scales_with_layers": True},
            {"id": "funnel", "name": "Funnels", "scales_with_layers": True},
            {"id": "bins", "name": "Bins", "scales_with_layers": True},
            {"id": "electronics", "name": "Electronics", "scales_with_layers": False},
        ],
        "color_roles": [{"id": "frame", "name": "Frame", "default": "charcoal"},
                        {"id": "bin", "name": "Bins", "default": "ivory-white"}],
        "parts": list(parts),
        "assemblies": list(assemblies),
        "settings": {},
    }
    return Catalog(raw=raw, colors=[Color("charcoal", "Charcoal", "#000000"), Color("ivory-white", "Ivory White", "#FFFFFF"),
                                    Color("ash-gray", "Ash Gray", "#9B9EA0")], source="test", fetched_at=0)


def tree_assemblies():
    """machine -> feeder -> ch1..ch3 (a stator each); superstructure -> layer x per-layer
    (a bracket pair each), plus bins and funnels."""
    return [
        {"id": "machine", "name": "Sorter", "lines": [{"assembly": "feeder", "qty": 1}, {"assembly": "superstructure", "qty": 1}]},
        {"id": "feeder", "name": "Feeder", "lines": [{"assembly": "ch1", "qty": 1}, {"assembly": "ch2", "qty": 1}, {"assembly": "ch3", "qty": 1}]},
        {"id": "ch1", "name": "C1", "lines": [{"part": "stator", "qty": 1}]},
        {"id": "ch2", "name": "C2", "lines": [{"part": "stator", "qty": 1}]},
        {"id": "ch3", "name": "C3", "lines": [{"part": "stator", "qty": 1}]},
        {"id": "superstructure", "name": "Superstructure", "lines": [
            {"assembly": "layer", "qty": "per-layer"},
            {"part": "funnel-third", "qty": "per-third-layer"}, {"part": "funnel-half", "qty": "per-half-layer"},
            {"assembly": "bins-third", "qty": "per-third-layer"}, {"assembly": "bins-half", "qty": "per-half-layer"}]},
        {"id": "layer", "name": "Layer", "lines": [{"part": "bracket", "qty": 2}]},
        {"id": "bins-third", "name": "Third bins", "lines": [{"part": "bin-third-left", "qty": 6}]},
        {"id": "bins-half", "name": "Half bins", "lines": [{"part": "bin-half-left", "qty": 6}]},
    ]


def by_id(lines):
    return {l.id: l for l in lines}


def test_layer_multipliers_and_scopes():
    cat = catalog([
        part("bracket", {"layer": 2, "feeder": 1}),
        part("cover", {"layer": 6}, layer_scope="non-bottom"),
        part("foot", {"layer": 6}, layer_scope="bottom-only"),
    ])
    b = by_id(build_bom(cat, BuildConfig(layers=["third", "third", "half"])))
    assert b["bracket"].qty == 2 * 3 + 1
    assert b["cover"].qty == 6 * 2
    assert b["foot"].qty == 6


def test_bins_and_funnels_follow_layer_sizes_and_selection():
    cat = catalog([
        part("bin-third-left", {"bins": 6}, {"role": "bin"}, optional=True),
        part("bin-half-left", {"bins": 6}, {"role": "bin"}, optional=True),
        part("funnel-third", {"funnel": 1}),
        part("funnel-half", {"funnel": 1}),
    ], tree_assemblies())
    layers = ["third", "third", "half"]
    default = by_id(build_bom(cat, BuildConfig(layers=layers)))  # bins left out by default
    assert default["bin-third-left"].qty == 0 and default["funnel-third"].qty == 2 and default["funnel-half"].qty == 1
    on = by_id(build_bom(cat, BuildConfig(layers=layers, excluded=[], include_optional=False)))
    assert on["bin-third-left"].qty == 12  # bins follow the selection, not "optional"
    assert on["bin-half-left"].qty == 6
    assert on["bin-third-left"].units[0].color_id == "ivory-white"


def test_zero_layers_drop_everything_that_scales():
    cat = catalog([part("gear", {"feeder": 4}), part("bracket", {"layer": 2}),
                   part("foot", {"layer": 6}, layer_scope="bottom-only"), part("funnel-third", {"funnel": 1})])
    b = by_id(build_bom(cat, BuildConfig(layers=[])))
    assert b["gear"].qty == 4 and b["bracket"].qty == 0 and b["foot"].qty == 0 and b["funnel-third"].qty == 0


def test_tree_places_can_be_switched_off():
    cat = catalog([part("stator", {"feeder": 3}), part("bracket", {"layer": 2}), part("lonely", {"feeder": 1})],
                  tree_assemblies())
    every = by_id(build_bom(cat, BuildConfig(excluded=[])))
    assert every["stator"].qty == 3
    leaves = {u.leaf for u in every["stator"].uses}
    assert leaves == {"machine/feeder/ch1", "machine/feeder/ch2", "machine/feeder/ch3"}
    # the tree does not know "lonely": it is still counted, in the untracked bucket
    assert [u.leaf for u in every["lonely"].uses] == ["~untracked/feeder"]
    no_c2 = by_id(build_bom(cat, BuildConfig(excluded=["machine/feeder/ch2"])))
    assert no_c2["stator"].qty == 2 and no_c2["bracket"].qty == 6
    no_feeder = by_id(build_bom(cat, BuildConfig(excluded=["machine/feeder"])))
    assert no_feeder["stator"].qty == 0 and no_feeder["bracket"].qty == 6


def test_selection_tree_counts():
    from sorter3mf.bom import selection_tree
    cat = catalog([part("stator", {"feeder": 3}), part("bracket", {"layer": 2})], tree_assemblies())
    cfg = BuildConfig(excluded=["machine/feeder/ch1"])
    t = selection_tree(cat, cfg, build_bom(cat, cfg))
    assert t["total"] == 3 + 6 and t["selected"] == 2 + 6
    feeder = next(c for c in t["children"] if c["key"] == "machine/feeder")
    assert [c["selected"] for c in feeder["children"]] == [0, 1, 1]


def test_optional_toggle_and_overrides():
    cat = catalog([part("extra", {"feeder": 2}, optional=True), part("gear", {"feeder": 4})])
    assert by_id(build_bom(cat, BuildConfig(include_optional=False)))["extra"].qty == 0
    b = by_id(build_bom(cat, BuildConfig(qty_overrides={"gear": 1})))
    assert b["gear"].qty == 1 and b["gear"].needed == 4
    assert sum(u.count for u in b["gear"].units) == 1


def test_colours_split_fixed_and_by_section():
    nema = part("nema", {"feeder": 3, "electronics": 1}, {"by_section": {
        "feeder": {"split": [{"color": "charcoal", "qty": 1}, {"color": "ash-gray", "qty": 2}]},
        "electronics": {"fixed": "ash-gray"}}})
    stator = part("stator", {"feeder": 2}, {"fixed": "ash-gray", "why": "camera"})
    b = by_id(build_bom(catalog([nema, stator]), BuildConfig(role_colors={"frame": "ivory-white"})))
    counts = {}
    for u in b["nema"].units:
        counts[u.color_id] = counts.get(u.color_id, 0) + u.count
    assert counts == {"charcoal": 1, "ash-gray": 3}
    assert {u.color_id for u in b["stator"].units} == {"ash-gray"}


def test_colour_filter_leaves_out_switched_off_colours():
    nema = part("nema", {"feeder": 3}, {"split": [{"color": "charcoal", "qty": 1}, {"color": "ash-gray", "qty": 2}]})
    gear = part("gear", {"feeder": 4})  # frame role: charcoal
    stator = part("stator", {"feeder": 2}, {"fixed": "ash-gray"})
    cat = catalog([nema, gear, stator])
    b = by_id(build_bom(cat, BuildConfig(excluded_colors=["ash-gray"])))
    assert b["nema"].needed == b["nema"].qty == 1
    assert {u.color_id for u in b["nema"].units} == {"charcoal"}
    assert b["gear"].qty == 4
    assert b["stator"].needed == b["stator"].qty == 0 and not b["stator"].units
    # what the colour held is still known, for the filter's counts
    assert sum(u.count for u in b["stator"].selected_units) == 2
    # a count asked for by hand is printed in the part's own colour
    b = by_id(build_bom(cat, BuildConfig(excluded_colors=["ash-gray"], qty_overrides={"stator": 1})))
    assert b["stator"].qty == 1 and [(u.color_id, u.count) for u in b["stator"].units] == [("ash-gray", 1)]


def test_alternative_swaps_parts():
    parts = [part("opi-wall", {"electronics": 1}), part("opi-pro-wall", {})]
    asms = [
        {"id": "electronics", "lines": [{"assembly": "orange-pi-mount", "qty": 1},
                                        {"assembly": "orange-pi-pro-housing", "qty": 1, "optional": True}]},
        {"id": "orange-pi-mount", "lines": [{"part": "opi-wall", "qty": 1}]},
        {"id": "orange-pi-pro-housing", "lines": [{"part": "opi-pro-wall", "qty": 1}]},
    ]
    cat = catalog(parts, asms)
    default = by_id(build_bom(cat, BuildConfig()))
    assert "opi-wall" in default and "opi-pro-wall" not in default
    pro = by_id(build_bom(cat, BuildConfig(alternatives={"orange-pi-board": "orange-pi-pro"})))
    assert "opi-wall" not in pro and pro["opi-pro-wall"].qty == 1


def test_engraved_download_is_used_when_available():
    p = part("x", {"feeder": 1}, stamped=[{"stl": "https://x/x-uid-stamped-top-111111111111.stl"}])
    b = by_id(build_bom(catalog([p]), BuildConfig(engrave_ids=True)))
    assert "stamped" in b["x"].stl_url
    b = by_id(build_bom(catalog([p]), BuildConfig(engrave_ids=False)))
    assert "stamped" not in b["x"].stl_url


def test_apportion():
    assert apportion([2, 1], 2) == [1, 1]  # 1.33 / 0.67: the larger remainder gets the spare
    assert sum(apportion([3, 3, 3], 7)) == 7
    assert apportion([5], 9) == [9]
