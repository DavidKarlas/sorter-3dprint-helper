import math
import struct

import numpy as np

from sorter3mf.mesh import convex_hull_2d, largest_face_down, min_area_angle, read_stl, rot_x, rot_z

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
