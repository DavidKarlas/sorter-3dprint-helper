import itertools
import random

from sorter3mf.packing import PackItem, Rect, center_bin, outline_fits, pack


def boxes(bins, items):
    """Actual (unpadded) boxes per plate: (x0, y0, x1, y1)."""
    size = {it.key: (it.w, it.h) for it in items}
    out = []
    for b in bins:
        plate = []
        for p in b.placements:
            w, h = size[p.item.key]
            if p.rotated:
                w, h = h, w
            plate.append((p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2))
        out.append(plate)
    return out


def test_everything_placed_inside_and_apart():
    rnd = random.Random(1)
    items = [PackItem(i, rnd.uniform(10, 120), rnd.uniform(10, 90)) for i in range(80)]
    gap, edge = 4.0, 2.0
    bins = pack(items, 256, 256, gap, edge)
    assert sum(len(b.placements) for b in bins) == len(items)
    for plate in boxes(bins, items):
        for x0, y0, x1, y1 in plate:
            assert x0 >= edge - 1e-6 and y0 >= edge - 1e-6
            assert x1 <= 256 - edge + 1e-6 and y1 <= 256 - edge + 1e-6
        for a, b in itertools.combinations(plate, 2):
            dx = max(b[0] - a[2], a[0] - b[2])
            dy = max(b[1] - a[3], a[1] - b[3])
            assert max(dx, dy) >= gap - 1e-6, (a, b)


def test_blocked_corner_is_avoided():
    items = [PackItem(i, 30, 30) for i in range(40)]
    blocked = [Rect(0, 0, 18, 28)]
    bins = pack(items, 256, 256, 4, 2, blocked)
    for plate in boxes(bins, items):
        for x0, y0, x1, y1 in plate:
            assert x0 >= 18 + 4 - 1e-6 or y0 >= 28 + 4 - 1e-6


def test_big_part_fits_with_small_edge_and_oversize_gets_own_plate():
    bins = pack([PackItem("beam", 248, 54)], 256, 256, gap=4, edge=2)
    assert len(bins) == 1 and not bins[0].oversize
    bins = pack([PackItem("huge", 300, 40), PackItem("small", 20, 20)], 256, 256, gap=4, edge=2)
    over = [b for b in bins if b.oversize]
    assert len(over) == 1 and over[0].placements[0].item.key == "huge"


def test_long_part_turns_to_fit():
    bins = pack([PackItem("tall", 40, 250)], 256, 200, gap=4, edge=2)
    assert not bins[0].oversize and bins[0].placements[0].rotated


def test_outline_check_clears_round_part_near_excluded_corner():
    import math
    r = 123.5
    circle = [(128 + r * math.cos(t / 32 * 2 * math.pi), 128 + r * math.sin(t / 32 * 2 * math.pi)) for t in range(32)]
    assert outline_fits(circle, 256, 256, 2, [Rect(0, 0, 18, 28)], clearance=4)
    square = [(4.5, 4.5), (251.5, 4.5), (251.5, 251.5), (4.5, 251.5)]
    assert not outline_fits(square, 256, 256, 2, [Rect(0, 0, 18, 28)], clearance=4)


def test_lone_big_part_is_centred():
    bins = pack([PackItem("rotor", 205, 205)], 256, 256, gap=4, edge=2)
    p = bins[0].placements[0]
    assert (p.x, p.y) != (128, 128)  # the packer leaves it in the corner
    center_bin(bins[0], 256, 256, gap=4, edge=2)
    assert (round(p.x, 6), round(p.y, 6)) == (128, 128)


def test_group_moves_as_one_and_keeps_its_gaps():
    items = [PackItem(i, 60, 40) for i in range(5)]
    bins = pack(items, 256, 256, gap=4, edge=2)
    before = [(p.x, p.y) for p in bins[0].placements]
    center_bin(bins[0], 256, 256, gap=4, edge=2)
    after = [(p.x, p.y) for p in bins[0].placements]
    shifts = {(round(a[0] - b[0], 6), round(a[1] - b[1], 6)) for a, b in zip(after, before)}
    assert len(shifts) == 1 and shifts != {(0, 0)}
    plate = boxes(bins, items)[0]
    assert round((min(b[0] for b in plate) + max(b[2] for b in plate)) / 2, 6) == 128
    assert round((min(b[1] for b in plate) + max(b[3] for b in plate)) / 2, 6) == 128


def test_centring_keeps_clear_of_an_excluded_corner():
    blocked = [Rect(0, 0, 18, 28)]
    # a part big enough that centring it fully would reach into the corner
    bins = pack([PackItem("wide", 230, 200)], 256, 256, gap=4, edge=2, blocked=blocked)
    center_bin(bins[0], 256, 256, gap=4, edge=2, blocked=blocked)
    (x0, y0, x1, y1), = boxes(bins, [PackItem("wide", 230, 200)])[0]
    assert x0 >= 18 + 4 - 1e-6 or y0 >= 28 + 4 - 1e-6
    assert x0 >= 2 - 1e-6 and y0 >= 2 - 1e-6 and x1 <= 254 + 1e-6 and y1 <= 254 + 1e-6
