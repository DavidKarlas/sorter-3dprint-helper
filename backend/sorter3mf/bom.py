"""What to print: the printed-parts bill of materials for one machine config.

This mirrors the parts calculator (sorter-v2/parts-calculator) so a build
here prints the same counts the calculator lists:

- section quantities times the layer multiplier (`machineQty` /
  `effectiveMult` in src/lib/filament.ts),
- bins and funnels counted from the per-layer size choice (`variantCount` in
  src/routes/+page.svelte),
- every copy attributed to a place in the assembly tree (tree.py, after
  src/lib/uses.ts), so places can be switched off: C-channel 2, the bins...
- the Orange Pi housing alternative (src/lib/alternatives.svelte.ts),
- colours resolved per section: role, fixed, split and by_section specs
  (`colorUnits` in src/lib/filament.ts).

On top of the places, colours can be switched off ("print only what is black
today"): a colour filter on the filament's own colours. Pieces already
printed, counted per part and colour, are left out of what is still to print.

When the calculator changes how it counts, change it here too.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import palettes
from . import tree as treemod
from .catalog import Catalog

# src/lib/alternatives.svelte.ts: whole-assembly alternatives. The first
# option is the default.
ALTERNATIVES = [
    {
        "id": "orange-pi-board",
        "label": "Orange Pi board",
        "parent": "electronics",
        "options": [
            {"id": "orange-pi-5", "label": "Orange Pi 5", "assembly": "orange-pi-mount"},
            {"id": "orange-pi-pro", "label": "Orange Pi 5 Pro, Max or Ultra", "assembly": "orange-pi-pro-housing"},
        ],
    }
]

DEFAULT_LAYERS = ["third", "third", "half"]

# The colour id the colour filter uses for a part the catalog gives no colour.
ANY_COLOR = "any"


def variant_count(part_id: str, layers: list[str]) -> int | None:
    """src/routes/+page.svelte variantCount(): bins and funnels follow the
    per-layer size (18 bins for a 'third' layer, 12 for a 'half' one)."""
    n_third = sum(1 for s in layers if s == "third")
    n_half = sum(1 for s in layers if s == "half")
    return {
        "funnel-third": n_third,
        "funnel-half": n_half,
        "bin-half-left": n_half * 6,
        "bin-half-right": n_half * 6,
        "bin-third-left": n_third * 6,
        "bin-third-center": n_third * 6,
        "bin-third-rightback": n_third * 6,
    }.get(part_id)


@dataclass
class BuildConfig:
    layers: list[str] = field(default_factory=lambda: list(DEFAULT_LAYERS))
    # tree places (leaf or any node above one) that are not printed; None means
    # the default, which leaves out the bins as the parts calculator does
    excluded: list[str] | None = None
    include_optional: bool = True
    alternatives: dict[str, str] = field(default_factory=dict)
    role_colors: dict[str, str] = field(default_factory=dict)
    qty_overrides: dict[str, int] = field(default_factory=dict)
    engrave_ids: bool = True
    # colours not to print: ids of the filament's palette (ANY_COLOR for a part
    # with no colour); with no palette, catalog colour ids
    excluded_colors: list[str] = field(default_factory=list)
    # pieces already printed: part id -> colour id (as above) -> count
    printed: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class ColorUnit:
    section: str
    color_id: str | None
    count: int


@dataclass
class BomLine:
    part: dict
    needed: int  # what the selected places need
    qty: int  # what will be printed (needed unless overridden)
    units: list[ColorUnit]  # qty split by section and colour
    stl_url: str
    in_bins: bool
    uses: list[treemod.Use] = field(default_factory=list)  # every place, selected or not
    # what the selected places still need (less what is printed) before the
    # colour filter, so the filter can show what each colour holds, including
    # the colours switched off
    selected_units: list[ColorUnit] = field(default_factory=list)
    # `units` less the pieces already printed: what a build prints
    left: list[ColorUnit] = field(default_factory=list)
    # pieces already printed, per colour, as far as `units` needs them
    printed: dict[str, int] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.part["id"]

    @property
    def to_print(self) -> int:
        return sum(u.count for u in self.left)


def _forced_optional(chosen: dict[str, str]) -> dict[str, bool]:
    """Assembly id -> whether its line in the parent is switched off by the
    alternative choices (the unchosen option's line resolves to zero)."""
    out = {}
    for alt in ALTERNATIVES:
        pick = chosen.get(alt["id"])
        if not any(o["id"] == pick for o in alt["options"]):
            pick = alt["options"][0]["id"]
        for o in alt["options"]:
            out[o["assembly"]] = o["id"] != pick
    return out


def _apply_alternatives(cat: Catalog, chosen: dict[str, str]) -> dict[str, dict]:
    """Per-part quantities after the alternative choices
    (alternatives.svelte.ts applyChoice): the chosen option's parts keep their
    quantities (or get the parent section's line qty when they have none), the
    others get none."""
    quantities = {pid: dict(p.get("quantities") or {}) for pid, p in cat.parts_by_id.items()}
    for alt in ALTERNATIVES:
        pick = chosen.get(alt["id"])
        if not any(o["id"] == pick for o in alt["options"]):
            pick = alt["options"][0]["id"]
        per_option: dict[str, list[tuple[str, int]]] = {}
        section = None
        for o in alt["options"]:
            asm = cat.assemblies_by_id.get(o["assembly"])
            members = []
            for line in (asm or {}).get("lines", []):
                pid = line.get("part")
                if pid in cat.parts_by_id and isinstance(line.get("qty"), int):
                    members.append((pid, line["qty"]))
                    own = cat.parts_by_id[pid].get("quantities") or {}
                    if section is None and own:
                        section = next(iter(own))
            per_option[o["id"]] = members
        for o in alt["options"]:
            for pid, qty in per_option[o["id"]]:
                own = cat.parts_by_id[pid].get("quantities") or {}
                if o["id"] == pick:
                    quantities[pid] = dict(own) if own else ({section: qty} if section else {})
                else:
                    quantities[pid] = {}
    return quantities


def _effective_mult(part: dict, section: str, layers: int, scaling: dict[str, bool]) -> int:
    if section == "layer":
        scope = part.get("layer_scope")
        if scope == "non-bottom":
            return max(0, layers - 1)
        if scope == "bottom-only":
            return 1 if layers >= 1 else 0
    return layers if scaling.get(section) else 1


def _resolve_color(spec: dict, section: str | None) -> dict:
    if "by_section" in spec:
        subs = spec["by_section"]
        sub = (section and subs.get(section)) or next(iter(subs.values()))
        return _resolve_color(sub, section)
    return spec


def color_units(part: dict, cat_qty: int, role_colors: dict[str, str], section: str) -> list[tuple[str | None, int]]:
    c = _resolve_color(part.get("color") or {}, section)
    if "split" in c:
        return [(s["color"], int(s["qty"])) for s in c["split"]]
    if "fixed" in c:
        return [(c["fixed"], cat_qty)]
    if "role" in c:
        return [(role_colors.get(c["role"]), cat_qty)]
    return [(None, cat_qty)]


def required_color(part: dict) -> dict | None:
    c = _resolve_color(part.get("color") or {}, None)
    if "fixed" in c and c.get("why"):
        return {"color_id": c["fixed"], "why": c["why"]}
    return None


def apportion(weights: list[int], total: int) -> list[int]:
    """Split `total` in proportion to `weights` (largest remainder)."""
    s = sum(weights)
    if s <= 0:
        return [total] + [0] * (len(weights) - 1) if weights else []
    raw = [w * total / s for w in weights]
    out = [int(x) for x in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def default_role_colors(cat: Catalog) -> dict[str, str]:
    return {r["id"]: r["default"] for r in cat.color_roles}


def part_stl(part: dict, engrave: bool) -> str:
    """The download the calculator hands out (partDownload): the default
    uid-stamped variant when engraving is on and one exists, else the master."""
    stamped = part.get("stamped") or []
    if engrave and stamped and stamped[0].get("stl"):
        return stamped[0]["stl"]
    return part["stl"]


def _section_counts(part: dict, q: dict, layers: list[str], scaling: dict[str, bool],
                    order: dict[str, int]) -> list[tuple[str, int]]:
    """How many copies each section needs, in catalog section order."""
    vc = variant_count(part["id"], layers)
    if vc is not None:
        return [(next(iter(q)), vc)]
    out = [(sec, per * _effective_mult(part, sec, len(layers), scaling)) for sec, per in q.items()]
    return sorted(out, key=lambda x: order.get(x[0], 99))


def _units_for(part: dict, section: str, count: int, roles: dict[str, str]) -> list[ColorUnit]:
    """`count` copies in one section, split by colour. A split colour spec
    gives its proportions per section instance; scale it to `count`."""
    spec = _resolve_color(part.get("color") or {}, section)
    if "split" in spec:
        qtys = [int(x["qty"]) for x in spec["split"]]
        return [ColorUnit(section, x["color"], n) for x, n in zip(spec["split"], apportion(qtys, count))]
    return [ColorUnit(section, cid, count) for cid, _ in color_units(part, count, roles, section)]


def _in_palette(units: list[ColorUnit], cat: Catalog, palette: "palettes.Palette | None") -> list[ColorUnit]:
    """The units in the filament's colours; units that land on the same colour
    in the same section are merged."""
    if palette is None:
        return units
    merged: dict[tuple[str, str | None], int] = {}
    for u in units:
        cid = palettes.resolve(palette, cat, u.color_id).id if u.color_id else None
        merged[(u.section, cid)] = merged.get((u.section, cid), 0) + u.count
    return [ColorUnit(sec, cid, n) for (sec, cid), n in merged.items()]


def _less_printed(units: list[ColorUnit], printed: dict[str, int]) -> tuple[list[ColorUnit], dict[str, int]]:
    """`units` less the pieces already printed in each colour (taken from the
    first sections first), and how many of those printed pieces were used."""
    rest = {k: max(0, int(n)) for k, n in (printed or {}).items()}
    left: list[ColorUnit] = []
    used: dict[str, int] = {}
    for u in units:
        key = u.color_id or ANY_COLOR
        take = min(u.count, rest.get(key, 0))
        if take:
            rest[key] -= take
            used[key] = used.get(key, 0) + take
        if u.count > take:
            left.append(ColorUnit(u.section, u.color_id, u.count - take))
    return left, used


def default_excluded(cat: Catalog, layers: list[str] | None = None) -> list[str]:
    """Leaves holding only bins: off unless asked for, like the calculator's
    "Print bins" toggle. The tree's shape does not depend on the layers (a
    place with zero copies is still walked), so neither does this."""
    root, raw = treemod.walk(cat, list(DEFAULT_LAYERS), _forced_optional({}))
    leaf_for = treemod.leaf_of(root)
    holds: dict[str, set[bool]] = {}
    for pid, uses in raw.items():
        is_bin = "bins" in (cat.parts_by_id[pid].get("quantities") or {})
        for path, _n in uses:
            holds.setdefault(leaf_for.get(path, path), set()).add(is_bin)
    return sorted(leaf for leaf, kinds in holds.items() if kinds == {True})


def build_bom(cat: Catalog, cfg: BuildConfig, palette: "palettes.Palette | None" = None) -> list[BomLine]:
    """The parts list. With a palette, every colour (role choices and the
    catalog's fixed colours) is carried into that filament's palette."""
    layers = list(cfg.layers if cfg.layers is not None else DEFAULT_LAYERS)
    roles = {**default_role_colors(cat), **(cfg.role_colors or {})}
    scaling = {s["id"]: bool(s.get("scales_with_layers")) for s in cat.sections}
    order = {s["id"]: i for i, s in enumerate(cat.sections)}
    quantities = _apply_alternatives(cat, cfg.alternatives or {})
    excluded = set(cfg.excluded if cfg.excluded is not None else default_excluded(cat, layers))
    colors_off = set(cfg.excluded_colors or [])

    root, raw = treemod.walk(cat, layers, _forced_optional(cfg.alternatives or {}))
    leaf_for = treemod.leaf_of(root)

    lines: list[BomLine] = []
    for pid, part in cat.parts_by_id.items():
        if part.get("retired_at"):
            continue
        q = quantities.get(pid) or {}
        if not q:
            continue  # not in the build (a candidate's part, an unchosen alternative)
        part = copy.copy(part)
        part["quantities"] = q
        in_bins = "bins" in q

        counts = _section_counts(part, q, layers, scaling, order)
        if part.get("optional") and not in_bins and not cfg.include_optional:
            counts = [(sec, 0) for sec, _ in counts]
        uses = treemod.allocate(counts, raw.get(pid, []), leaf_for)

        per_section: dict[str, int] = {}
        for u in uses:
            if not treemod.is_excluded(u.leaf, excluded):
                per_section[u.section] = per_section.get(u.section, 0) + u.count
        selected = _in_palette([cu for sec, n in sorted(per_section.items(), key=lambda x: order.get(x[0], 99))
                                for cu in _units_for(part, sec, n, roles)], cat, palette)
        selected = [u for u in selected if u.count > 0]
        units = [u for u in selected if (u.color_id or ANY_COLOR) not in colors_off]
        needed = sum(u.count for u in units)

        qty = needed
        if pid in (cfg.qty_overrides or {}):
            qty = max(0, int(cfg.qty_overrides[pid]))
        if qty != needed:
            # A count asked for by hand is printed even when the filter would
            # leave the part out: in the selected places' colours, or else
            # the colour of its first section.
            if not units:
                units = selected
            if not units:
                first = counts[0][0] if counts else next(iter(q))
                units = _in_palette(_units_for(part, first, 0, roles), cat, palette)
            counts_ = apportion([u.count for u in units], qty)
            units = [ColorUnit(u.section, u.color_id, n) for u, n in zip(units, counts_)]
        units = [u for u in units if u.count > 0]
        done = (cfg.printed or {}).get(pid) or {}
        left, used = _less_printed(units, done)
        lines.append(BomLine(part=part, needed=needed, qty=qty, units=units,
                             stl_url=part_stl(part, cfg.engrave_ids), in_bins=in_bins, uses=uses,
                             selected_units=_less_printed(selected, done)[0], left=left, printed=used))
    lines.sort(key=lambda l: (min((order.get(s, 99) for s in l.part["quantities"]), default=99), l.part["name"]))
    return lines


def selection_tree(cat: Catalog, cfg: BuildConfig, lines: list[BomLine]) -> dict:
    """The assembly tree with piece counts per place, for the checkboxes.
    Places with nothing to print at this configuration are left out."""
    layers = list(cfg.layers if cfg.layers is not None else DEFAULT_LAYERS)
    excluded = set(cfg.excluded if cfg.excluded is not None else default_excluded(cat, layers))
    root, _ = treemod.walk(cat, layers, _forced_optional(cfg.alternatives or {}))
    treemod.leaf_of(root)
    per_leaf: dict[str, int] = {}
    names: dict[str, list[str]] = {}
    sections = {s["id"]: s["name"] for s in cat.sections}
    for l in lines:
        for u in l.uses:
            if u.count <= 0:
                continue
            per_leaf[u.leaf] = per_leaf.get(u.leaf, 0) + u.count
            names.setdefault(u.leaf, [])
            if l.part["name"] not in names[u.leaf]:
                names[u.leaf].append(l.part["name"])

    def leaf_dict(key: str, name: str, mult: int) -> dict | None:
        total = per_leaf.get(key, 0)
        if total <= 0:
            return None
        return {"key": key, "name": name, "mult": mult, "total": total,
                "selected": 0 if treemod.is_excluded(key, excluded) else total,
                "parts": names.get(key, []), "children": []}

    def visit(node: treemod.TreeNode) -> dict | None:
        if node.leaf:
            return leaf_dict(node.key, node.name, node.mult)
        kids = []
        own = leaf_dict(f"{node.key}/{treemod.OWN}", "Parts of its own", 1) if node.own else None
        if own:
            own["name"] = ", ".join(own["parts"][:3]) + ("…" if len(own["parts"]) > 3 else "")
            kids.append(own)
        kids += [d for c in node.children if (d := visit(c))]
        if not kids:
            return None
        return {"key": node.key, "name": node.name, "mult": node.mult,
                "total": sum(k["total"] for k in kids), "selected": sum(k["selected"] for k in kids),
                "parts": [], "children": kids}

    top = visit(root) or {"key": treemod.ROOT, "name": "Sorter V2", "mult": 1, "total": 0, "selected": 0,
                         "parts": [], "children": []}
    untracked = [leaf_dict(k, sections.get(k.split("/", 1)[1], k), 1)
                 for k in sorted(per_leaf) if k.startswith(treemod.UNTRACKED + "/")]
    untracked = [u for u in untracked if u]
    if untracked:
        top["children"].append({"key": treemod.UNTRACKED, "name": "Not in the assembly tree yet", "mult": 1,
                                "total": sum(u["total"] for u in untracked),
                                "selected": sum(u["selected"] for u in untracked), "parts": [],
                                "children": untracked})
        top["total"] += sum(u["total"] for u in untracked)
        top["selected"] += sum(u["selected"] for u in untracked)
    return top
