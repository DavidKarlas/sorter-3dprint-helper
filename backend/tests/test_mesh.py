import math
import struct

import numpy as np

from sorter3mf.mesh import Mesh, convex_hull_2d, largest_face_down, min_area_angle, print_pose, read_stl, rot_x, rot_z

BOX_TRIS = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
            (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def box_vertices(w, d, h):
    return [(0, 0, 0), (w, 0, 0), (w, d, 0), (0, d, 0), (0, 0, h), (w, 0, h), (w, d, h), (0, d, h)]


def binary_stl(verts, tris):
    out = bytearray(b"\0" * 80) + struct.pack("<I", len(tris))
    for t in tris:
        out += struct.pack("<3f", 0, 0, 0)
        for i in t:
            out += struct.pack("<3f", *verts[i])
        out += b"\0\0"
    return bytes(out)


def ascii_stl(verts, tris):
    lines = ["solid t"]
    for t in tris:
        lines.append("facet normal 0 0 0\nouter loop")
        lines += ["vertex %g %g %g" % verts[i] for i in t]
        lines.append("endloop\nendfacet")
    return ("\n".join(lines) + "\nendsolid t\n").encode()


def test_read_binary_and_ascii_weld_vertices():
    v = box_vertices(10, 20, 30)
    for data in (binary_stl(v, BOX_TRIS), ascii_stl(v, BOX_TRIS)):
        m = read_stl(data)
        assert len(m.vertices) == 8 and len(m.triangles) == 12
        assert np.allclose(m.size, [10, 20, 30])


def test_lay_flat_puts_the_big_face_down():
    # a 100 x 60 x 4 slab standing on its edge
    m = read_stl(binary_stl(box_vertices(100, 60, 4), BOX_TRIS)).transformed(rot_x(90))
    assert m.size[2] > 50
    flat = m.transformed(largest_face_down(m))
    assert flat.size[2] < 4.5


def test_min_area_angle_unrotates_a_turned_rectangle():
    pts = np.array([[0, 0], [100, 0], [100, 20], [0, 20]], dtype=float)
    r = rot_z(math.radians(30))[:2, :2]
    turned = pts @ r.T
    hull = convex_hull_2d(turned)
    ang = min_area_angle(hull)
    back = turned @ rot_z(ang)[:2, :2].T
    size = back.max(axis=0) - back.min(axis=0)
    assert sorted(np.round(size, 3)) == [20, 100]


def quad_mesh(quads):
    """A mesh from quads given with the way each should face (two triangles
    each, wound so their normals point that way)."""
    verts, tris = [], []
    for corners, facing in quads:
        base = len(verts)
        verts += corners
        for a, b, c in ((0, 1, 2), (0, 2, 3)):
            p = [np.array(corners[i], float) for i in (a, b, c)]
            if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), facing) < 0:
                b, c = c, b
            tris.append((base + a, base + b, base + c))
    return Mesh(np.array(verts, float), np.array(tris))


def cup(w=60.0, h=30.0, t=2.0):
    """An open-top box: outer walls, a floor `t` thick, a rim, the inside."""
    o, i = (0.0, w), (t, w - t)

    def ring(z, lo, hi):
        return [(lo, lo, z), (hi, lo, z), (hi, hi, z), (lo, hi, z)]

    def sides(lo, hi, z0, z1, out):
        a, b = ring(z0, lo, hi), ring(z1, lo, hi)
        centre = np.array([w / 2, w / 2, 0.0])
        res = []
        for k in range(4):
            q = [a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]]
            mid = np.mean(np.array(q), axis=0)
            d = mid - centre
            d[2] = 0
            res.append((q, d if out else -d))
        return res

    quads = [(ring(0, *o), (0, 0, -1)), (ring(t, *i), (0, 0, 1))]
    quads += sides(*o, 0, h, True) + sides(*i, t, h, False)
    a, b = ring(h, *o), ring(h, *i)
    quads += [([a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]], (0, 0, 1)) for k in range(4)]
    return quad_mesh(quads)


def test_print_pose_keeps_a_part_that_prints_well():
    assert print_pose(cup()) == (None, None)
    slab = read_stl(binary_stl(box_vertices(100, 60, 4), BOX_TRIS))
    assert print_pose(slab) == (None, None)


def test_print_pose_lays_a_part_on_an_edge_flat():
    slab = read_stl(binary_stl(box_vertices(100, 60, 4), BOX_TRIS))
    slab = Mesh(slab.vertices - slab.vertices.mean(axis=0), slab.triangles).transformed(rot_x(45))
    rot, why = print_pose(slab)
    assert rot is not None and "0 mm² rests on the bed" in why
    assert slab.transformed(rot).size[2] < 4.5


def test_print_pose_turns_an_upside_down_cup_over():
    upside_down = cup().transformed(rot_x(180))
    rot, why = print_pose(upside_down)
    assert rot is not None
    turned = upside_down.transformed(rot)
    # open side up again: 4 corners on the bed (the floor), 8 at the top (the rim)
    v = np.round(turned.vertices, 6)
    corners = lambda z: {tuple(p[:2]) for p in v if abs(p[2] - z) < 1e-6}
    assert len(corners(v[:, 2].min())) == 4 and len(corners(v[:, 2].max())) == 8
    assert print_pose(turned) == (None, None)


def test_print_pose_lays_down_a_plate_standing_on_its_end():
    # 100 x 60 x 4 plate standing on its 60 x 4 end: a real face, but a tall,
    # wobbly print that breaks along its layers
    plate = read_stl(binary_stl(box_vertices(100, 60, 4), BOX_TRIS))
    plate = Mesh(plate.vertices - plate.vertices.mean(axis=0), plate.triangles).transformed(rot_x(90)).transformed(
        np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float))
    assert plate.size[2] > 99
    rot, why = print_pose(plate)
    assert rot is not None and plate.transformed(rot).size[2] < 4.5
    # a block that is merely taller than wide keeps its pose
    block = read_stl(binary_stl(box_vertices(38, 35, 68), BOX_TRIS))
    assert print_pose(block) == (None, None)


def test_supported_parts_are_only_taken_off_an_edge():
    upside_down = cup().transformed(rot_x(180))
    assert print_pose(upside_down, edge_only=True) == (None, None)
    slab = read_stl(binary_stl(box_vertices(100, 60, 4), BOX_TRIS))
    slab = Mesh(slab.vertices - slab.vertices.mean(axis=0), slab.triangles).transformed(rot_x(45))
    assert print_pose(slab, edge_only=True)[0] is not None
