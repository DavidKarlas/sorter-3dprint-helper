"""The machine's assembly tree, as checkboxes: where each printed copy goes.

Mirrors sorter-v2 parts-calculator src/lib/uses.ts. The catalog's section
quantities say HOW MANY of a part the machine needs; the assembly tree says
WHERE they go (C-channel 1, the camera lamp of C-channel 3, ...). Every copy a
part needs is attributed to one place in the tree, walking it in order; copies
the tree cannot explain land in a "not in the assembly tree yet" bucket, so a
part's uses always add up to exactly what the machine needs.

Unlike uses.ts, places are tree *paths*, not assembly ids: the C-channel drive
of C-channel 1 and that of C-channel 2 are different checkboxes.

A "leaf" is what a checkbox switches: an assembly with no sub-assemblies, or,
for one that has both sub-assemblies and parts of its own, a synthetic
`<path>/#parts` child holding just those parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog

ROOT = "machine"
UNTRACKED = "~untracked"
OWN = "#parts"
MAX_DEPTH = 16


@dataclass
class Use:
    leaf: str
    section: str | None
    count: int


@dataclass
class TreeNode:
    key: str
    name: str
    mult: int  # how many of this assembly the machine has at this place
    children: list["TreeNode"] = field(default_factory=list)
    own: dict[str, int] = field(default_factory=dict)  # part id -> copies listed directly here (raw)
    leaf: bool = False


def line_qty(line: dict, layers: list[str], forced_optional: dict[str, bool]) -> int:
    """filament.ts lineQty(): a line's count for this layer configuration."""
    optional = forced_optional.get(line.get("assembly"), line.get("optional", False))
    if optional:
        return 0
    q = line.get("qty", 0)
    n = len(layers)
    half = sum(1 for s in layers if s == "half")
    if isinstance(q, str):
        return {
            "per-layer": n,
            "non-bottom-layers": max(0, n - 1),
            "middle-layers": max(0, n - 2),
            "per-half-layer": half,
            "per-third-layer": n - half,
        }.get(q, 0)
    return int(q)


def concrete_lines(asm: dict, args: dict | None) -> list[dict]:
    """filament.ts concreteLines(): param slots become part lines, '$x' args
    are resolved against this instantiation."""
    params = asm.get("params") or {}

    def value(name: str) -> str:
        return (args or {}).get(name) or (params.get(name) or {}).get("default", "")

    out = []
    for line in asm.get("lines") or []:
        if line.get("param"):
            line = {k: v for k, v in line.items() if k != "param"} | {"part": value(line["param"])}
        elif line.get("args"):
            line = dict(line)
            line["args"] = {k: value(v[1:]) if isinstance(v, str) and v.startswith("$") else v
                            for k, v in line["args"].items()}
        out.append(line)
    return out


def walk(cat: Catalog, layers: list[str], forced_optional: dict[str, bool]) -> tuple[TreeNode, dict[str, list[tuple[str, int]]]]:
    """The tree from ROOT, and per part its raw (node path, copies) in walk order."""
    raw: dict[str, list[tuple[str, int]]] = {}

    def visit(aid: str, mult: int, path: str, args: dict | None, depth: int) -> TreeNode:
        asm = cat.assemblies_by_id.get(aid) or {}
        node = TreeNode(key=path, name=asm.get("name", aid), mult=mult)
        if depth > MAX_DEPTH:
            return node
        for line in concrete_lines(asm, args):
            n = line_qty(line, layers, forced_optional) * mult
            if line.get("assembly"):
                child = visit(line["assembly"], n, f"{path}/{line['assembly']}", line.get("args"), depth + 1)
                node.children.append(child)
            elif line.get("part") in cat.parts_by_id:
                node.own[line["part"]] = node.own.get(line["part"], 0) + n
                raw.setdefault(line["part"], []).append((path, n))
        return node

    root = visit(ROOT, 1, ROOT, None, 0)

    # drop sub-trees that hold no printed part at all (cables, PCBs, hardware-only boxes)
    def prune(node: TreeNode) -> bool:
        node.children = [c for c in node.children if prune(c)]
        return bool(node.children or node.own)

    prune(root)
    return root, raw


def leaf_of(root: TreeNode) -> dict[str, str]:
    """node path -> the leaf key its own parts are switched by."""
    out: dict[str, str] = {}

    def visit(node: TreeNode) -> None:
        if node.children:
            out[node.key] = f"{node.key}/{OWN}"
        else:
            out[node.key] = node.key
            node.leaf = True
        for c in node.children:
            visit(c)

    visit(root)
    return out


def allocate(section_counts: list[tuple[str, int]], raw_uses: list[tuple[str, int]],
             leaf_for: dict[str, str]) -> list[Use]:
    """Attribute `section_counts` (the authority, in section order) to tree
    places in walk order. A place never takes more than is still needed;
    whatever the tree does not explain goes to the untracked bucket."""
    remaining = [[s, c] for s, c in section_counts if c > 0]
    uses: list[Use] = []
    si = 0
    for path, n in raw_uses:
        while n > 0 and si < len(remaining):
            sec, left = remaining[si]
            take = min(n, left)
            uses.append(Use(leaf_for.get(path, path), sec, take))
            n -= take
            remaining[si][1] -= take
            if remaining[si][1] == 0:
                si += 1
    for sec, left in remaining[si:]:
        if left > 0:
            uses.append(Use(f"{UNTRACKED}/{sec}", sec, left))
    # merge repeats of the same (leaf, section)
    merged: dict[tuple[str, str | None], int] = {}
    for u in uses:
        merged[(u.leaf, u.section)] = merged.get((u.leaf, u.section), 0) + u.count
    return [Use(leaf, sec, c) for (leaf, sec), c in merged.items()]


def is_excluded(leaf: str, excluded: set[str]) -> bool:
    """A leaf is off when it, or any node above it, is in `excluded`."""
    if leaf in excluded:
        return True
    parts = leaf.split("/")
    return any("/".join(parts[:i]) in excluded for i in range(1, len(parts)))
