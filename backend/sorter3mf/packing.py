"""Rectangle packing onto build plates (MaxRects, best short side fit).

Each piece is the axis-aligned box around its footprint, grown by the gap
wanted between parts. Pieces go largest first; each one lands on whichever
open plate fits it best, and a new plate is opened when none does. Pieces may
turn 90 degrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    def contains(self, o: "Rect") -> bool:
        e = 1e-9
        return o.x >= self.x - e and o.y >= self.y - e and o.x1 <= self.x1 + e and o.y1 <= self.y1 + e

    def overlaps(self, o: "Rect") -> bool:
        return o.x < self.x1 and o.x1 > self.x and o.y < self.y1 and o.y1 > self.y


@dataclass
class Placement:
    item: object
    x: float  # centre of the piece's box, in plate coordinates
    y: float
    rotated: bool


@dataclass
class Bin:
    width: float
    height: float
    free: list[Rect] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    oversize: bool = False

    def __post_init__(self) -> None:
        if not self.free:
            self.free = [Rect(0, 0, self.width, self.height)]

    def block(self, r: Rect) -> None:
        """Mark an area unusable (a printer's excluded corner)."""
        self._split_free(r)

    def find(self, w: float, h: float, allow_rotate: bool):
        best = None  # (short, long, rect, rotated)
        for fr in self.free:
            for rw, rh, rot in ((w, h, False), (h, w, True)) if allow_rotate and w != h else ((w, h, False),):
                if rw <= fr.w + 1e-9 and rh <= fr.h + 1e-9:
                    short = min(fr.w - rw, fr.h - rh)
                    long_ = max(fr.w - rw, fr.h - rh)
                    if best is None or (short, long_) < (best[0], best[1]):
                        best = (short, long_, Rect(fr.x, fr.y, rw, rh), rot)
        return best

    def place(self, item, rect: Rect, rotated: bool) -> None:
        self._split_free(rect)
        self.placements.append(Placement(item, rect.x + rect.w / 2, rect.y + rect.h / 2, rotated))

    def _split_free(self, used: Rect) -> None:
        out: list[Rect] = []
        for fr in self.free:
            if not fr.overlaps(used):
                out.append(fr)
                continue
            if used.x > fr.x:
                out.append(Rect(fr.x, fr.y, used.x - fr.x, fr.h))
            if used.x1 < fr.x1:
                out.append(Rect(used.x1, fr.y, fr.x1 - used.x1, fr.h))
            if used.y > fr.y:
                out.append(Rect(fr.x, fr.y, fr.w, used.y - fr.y))
            if used.y1 < fr.y1:
                out.append(Rect(fr.x, used.y1, fr.w, fr.y1 - used.y1))
        out = [r for r in out if r.w > 1e-6 and r.h > 1e-6]
        # drop free rects contained in another
        pruned = []
        for i, a in enumerate(out):
            if any(j != i and b.contains(a) and (not a.contains(b) or j < i) for j, b in enumerate(out)):
                continue
            pruned.append(a)
        self.free = pruned


def center_bin(b: "Bin", width: float, height: float, gap: float, edge: float,
               blocked: list[Rect] | None = None) -> None:
    """Move everything on a plate so the group sits in the middle of the bed.

    The packer fills from the front-left corner, so a lone big part (a rotor)
    ends up against the edge; the middle of the bed heats most evenly and is
    where the slicer itself would put it. The group moves as one, so the gaps
    between parts stay as packed. Each piece's reserved box (with any support
    room) has to stay `edge` inside the bed and a `gap` clear of blocked
    areas; when the full move breaks that, a move along one axis is tried,
    and otherwise the plate is left as packed."""
    if not b.placements or b.oversize:
        return

    def box(p: Placement, dx: float, dy: float) -> Rect:
        w, h = (p.item.h, p.item.w) if p.rotated else (p.item.w, p.item.h)
        return Rect(p.x + dx - w / 2, p.y + dy - h / 2, w, h)

    boxes = [box(p, 0, 0) for p in b.placements]
    x0, x1 = min(r.x for r in boxes), max(r.x1 for r in boxes)
    y0, y1 = min(r.y for r in boxes), max(r.y1 for r in boxes)
    dx = width / 2 - (x0 + x1) / 2
    dy = height / 2 - (y0 + y1) / 2
    grown = [Rect(r.x - gap, r.y - gap, r.w + 2 * gap, r.h + 2 * gap) for r in blocked or []]

    def ok(sx: float, sy: float) -> bool:
        for p in b.placements:
            r = box(p, sx, sy)
            if r.x < edge - 1e-6 or r.y < edge - 1e-6 or r.x1 > width - edge + 1e-6 or r.y1 > height - edge + 1e-6:
                return False
            if any(g.overlaps(r) for g in grown):
                return False
        return True

    for sx, sy in ((dx, dy), (dx, 0.0), (0.0, dy)):
        if (abs(sx) > 1e-6 or abs(sy) > 1e-6) and ok(sx, sy):
            for p in b.placements:
                p.x += sx
                p.y += sy
            return


def _convex_overlaps_rect(poly: list[tuple[float, float]], r: Rect) -> bool:
    """Separating-axis test between a convex polygon and an axis-aligned rect."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if max(xs) <= r.x or min(xs) >= r.x1 or max(ys) <= r.y or min(ys) >= r.y1:
        return False
    corners = [(r.x, r.y), (r.x1, r.y), (r.x1, r.y1), (r.x, r.y1)]
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        ax, ay = y1 - y0, x0 - x1  # edge normal
        if ax == 0 and ay == 0:
            continue
        pp = [ax * x + ay * y for x, y in poly]
        rp = [ax * x + ay * y for x, y in corners]
        if max(pp) <= min(rp) or max(rp) <= min(pp):
            return False
    return True


def outline_fits(poly: list[tuple[float, float]], width: float, height: float, edge: float,
                 blocked: list[Rect] | None = None, clearance: float = 0.0) -> bool:
    """Whether a convex outline (already placed, plate coordinates) stays
    `edge` inside the plate and `clearance` away from every blocked area."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if min(xs) < edge - 1e-6 or min(ys) < edge - 1e-6 or max(xs) > width - edge + 1e-6 or max(ys) > height - edge + 1e-6:
        return False
    for r in blocked or []:
        grown = Rect(r.x - clearance, r.y - clearance, r.w + 2 * clearance, r.h + 2 * clearance)
        if _convex_overlaps_rect(poly, grown):
            return False
    return True


@dataclass
class PackItem:
    key: object
    w: float  # footprint box, without the gap
    h: float


def pack(items: list[PackItem], width: float, height: float, gap: float, edge: float | None = None,
         blocked: list[Rect] | None = None, allow_rotate: bool = True) -> list[Bin]:
    """Pack items onto as few width x height plates as this greedy pass manages.

    `gap` is the clear distance kept between pieces, `edge` the distance kept
    from the plate's edge (defaults to `gap`) and from blocked areas. Items
    too big for an empty plate get a plate of their own, flagged `oversize`,
    centred."""
    edge = gap if edge is None else edge
    # Each piece reserves its box plus half a gap on every side, so two
    # neighbours end up a full gap apart. The packing frame is offset from the
    # plate by (edge - gap/2) so the outermost pieces keep `edge` to the rim.
    off = edge - gap / 2
    fw, fh = width - 2 * edge + gap, height - 2 * edge + gap

    def new_bin() -> Bin:
        b = Bin(fw, fh)
        for r in blocked or []:
            # grown by half a gap: with each piece's own half gap, pieces stay
            # a full gap clear of the blocked area
            b.block(Rect(r.x - off - gap / 2, r.y - off - gap / 2, r.w + gap, r.h + gap))
        return b

    bins: list[Bin] = []
    order = sorted(items, key=lambda it: (max(it.w, it.h), it.w * it.h), reverse=True)
    for it in order:
        w, h = it.w + gap, it.h + gap
        best = None
        for b in bins:
            if b.oversize:
                continue
            found = b.find(w, h, allow_rotate)
            if found and (best is None or found[:2] < best[1][:2]):
                best = (b, found)
        if best is None:
            b = new_bin()
            found = b.find(w, h, allow_rotate)
            if found is None:
                ob = Bin(fw, fh, oversize=True)
                rot = allow_rotate and it.w > width and it.w <= height and it.h <= width
                ob.placements.append(Placement(it, width / 2 - off, height / 2 - off, rot))
                bins.append(ob)
                continue
            bins.append(b)
            best = (b, found)
        b, (_, _, rect, rot) = best
        b.place(it, rect, rot)
    # placements are in the packing frame; shift them back to plate coordinates
    for b in bins:
        for p in b.placements:
            p.x += off
            p.y += off
    return bins
