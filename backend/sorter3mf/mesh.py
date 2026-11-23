"""Triangle meshes: reading STL, putting a part into its print pose, and the
2D footprint the plate packer works with.

Everything here is numpy only. A mesh is an indexed triangle list (welded
vertices), which is what a 3MF stores.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import numpy as np


@dataclass
class Mesh:
    vertices: np.ndarray  # (n, 3) float64
    triangles: np.ndarray  # (m, 3) int64

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    @property
    def size(self) -> np.ndarray:
        lo, hi = self.bounds
        return hi - lo

    def transformed(self, rot: np.ndarray) -> "Mesh":
        """Rotate by a 3x3 matrix (column-vector convention: v' = R @ v)."""
        return Mesh(self.vertices @ rot.T, self.triangles)


# ------------------------------------------------------------------ reading
def read_stl(data: bytes) -> Mesh:
    """Parse binary or ASCII STL bytes into a welded indexed mesh."""
    tris = _stl_triangles(data)
    return weld(tris)


def _stl_triangles(data: bytes) -> np.ndarray:
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + count * 50 == len(data):
            rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            arr = np.frombuffer(data, dtype=rec, count=count, offset=84)
            return arr["v"].astype(np.float64)
    text = data.decode("ascii", errors="ignore")
    if "facet" not in text:
        raise ValueError("not an STL file (neither a valid binary STL nor ASCII facets)")
    nums = [line.split()[1:4] for line in text.splitlines() if line.strip().startswith("vertex")]
    if not nums or len(nums) % 3:
        raise ValueError("ASCII STL has a broken vertex list")
    return np.asarray(nums, dtype=np.float64).reshape(-1, 3, 3)


def weld(tris: np.ndarray, decimals: int = 5) -> Mesh:
    """Merge identical vertices (STL repeats each one per triangle) and drop
    triangles that collapse to a line or a point."""
    flat = tris.reshape(-1, 3)
    keys = np.round(flat, decimals)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3).astype(np.int64)
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return Mesh(uniq.astype(np.float64), faces[ok])


# ------------------------------------------------------------------ rotations
def rot_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def rot_z(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def rotation_onto(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The smallest rotation taking unit vector a onto unit vector b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        if c > 0:
            return np.eye(3)
        # 180 degrees: any axis perpendicular to a
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def largest_face_down(mesh: Mesh) -> np.ndarray:
    """Rotation that rests the part on its largest flat face.

    Groups triangles by their (rounded) normal and sums the areas; the normal
    with the biggest total area among faces lying on the part's outer surface
    in that direction is turned to point straight down. That is "lay flat",
    the same idea as the slicer's lay-on-face tool."""
    v = mesh.vertices
    t = mesh.triangles
    p0, p1, p2 = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    area2 = np.linalg.norm(cross, axis=1)
    keep = area2 > 1e-9
    normals = cross[keep] / area2[keep, None]
    areas = area2[keep] / 2
    centroids = ((p0 + p1 + p2) / 3)[keep]
    key = np.round(normals, 3)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    best, best_area = None, -1.0
    for i in np.argsort(-np.bincount(inv, weights=areas))[:12]:
        n = uniq[i] / np.linalg.norm(uniq[i])
        # only faces at the part's extreme along n can be the bed contact
        extent = v @ n
        top = extent.max()
        sel = inv == i
        on_hull = np.abs(centroids[sel] @ n - top) < 0.05
        a = float(areas[sel][on_hull].sum())
        if a > best_area:
            best, best_area = n, a
    if best is None:
        return np.eye(3)
    return rotation_onto(best, np.array([0.0, 0.0, -1.0]))


# ------------------------------------------------------------------ print pose
#
# Most parts are exported in the pose they print in, and the designer's pose
# carries what geometry cannot see (layer lines across the load, a clean
# face, round holes). A few are exported in their assembly pose instead:
# standing on an edge, upside down with a roof that would print in mid-air,
# or a flat plate standing tall on its narrow end. `print_pose` finds those
# and only those, and turns them onto the flat face that leaves the least
# overhang.

DOWN = np.array([0.0, 0.0, -1.0])
OVERHANG_COS = math.cos(math.radians(45))  # facing down past 45 degrees: needs support or a bridge
# "rests on an edge": less on the bed than this (mm2), or than this share of
# the best flat face
EDGE_CONTACT = 20.0
EDGE_SHARE = 0.02
# "upside down": another face leaves this much less overhang (mm2), and this
# share of what the exported pose has
OVERHANG_GAIN = 2000.0
OVERHANG_GAIN_SHARE = 0.6
# "stands tall on a small end": less on the bed than this share of the best
# flat face, at least this many times as tall as lying on it, and lying down
# adds no overhang (a thin bracket standing on its end wobbles and breaks
# along its layers)
SMALL_END_SHARE = 0.1
TALL_RATIO = 3.0
# a face to stand on has at least this share of the best flat face's area
BASE_SHARE = 0.15


@dataclass
class Pose:
    down: np.ndarray  # the part's direction that faces the bed
    contact: float  # mm2 of flat face on the bed
    overhang: float  # mm2 facing down past 45 degrees, above the bed
    height: float


class _Faces:
    def __init__(self, mesh: Mesh):
        v = mesh.vertices
        t = mesh.triangles
        p0, p1, p2 = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        cross = np.cross(p1 - p0, p2 - p0)
        area2 = np.linalg.norm(cross, axis=1)
        keep = area2 > 1e-9
        self.vertices = v
        self.normals = cross[keep] / area2[keep, None]
        self.areas = area2[keep] / 2
        self.centroids = ((p0 + p1 + p2) / 3)[keep]

    def pose(self, down: np.ndarray) -> Pose:
        depth = self.vertices @ down
        above = depth.max() - self.centroids @ down  # each face's height over the bed
        facing = self.normals @ down  # 1: straight down
        contact = float(self.areas[(facing > 0.999) & (above < 0.05)].sum())
        overhang = float(self.areas[(facing > OVERHANG_COS) & (above > 0.3)].sum())
        return Pose(down, contact, overhang, float(depth.max() - depth.min()))

    def flat_sides(self, limit: int = 40) -> list[np.ndarray]:
        """Outward directions of the part's flat outer faces, biggest first:
        the faces it could stand on."""
        key = np.round(self.normals, 3)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        out = []
        for i in np.argsort(-np.bincount(inv, weights=self.areas))[:limit]:
            n = uniq[i] / np.linalg.norm(uniq[i])
            sel = inv == i
            if np.any(np.abs(self.centroids[sel] @ n - (self.vertices @ n).max()) < 0.05):
                out.append(n)
        return out


def print_pose(mesh: Mesh, edge_only: bool = False) -> tuple[np.ndarray | None, str | None]:
    """A rotation for a part exported in a pose it cannot print in well, and
    why; (None, None) when the exported pose is kept. `edge_only` turns only
    a part that rests on an edge (for parts printed with supports on purpose,
    whose overhangs are expected)."""
    faces = _Faces(mesh)
    now = faces.pose(DOWN)
    sides = [faces.pose(d) for d in faces.flat_sides()]
    if not sides:
        return None, None
    biggest = max(p.contact for p in sides)

    def pick(poses: list[Pose]) -> Pose:
        # least overhang; near-ties go to the bigger face, then the lower part
        least = min(p.overhang for p in poses)
        near = [p for p in poses if p.overhang <= least + max(200.0, 0.1 * least)]
        return max(near, key=lambda p: (round(p.contact), -p.height))

    best = pick([p for p in sides if p.contact >= BASE_SHARE * biggest])
    on_edge = now.contact < max(EDGE_CONTACT, EDGE_SHARE * biggest)
    gain = now.overhang - best.overhang
    upside_down = gain >= max(OVERHANG_GAIN, OVERHANG_GAIN_SHARE * now.overhang) and best.contact >= now.contact
    if edge_only:
        upside_down = False
    if not (on_edge or upside_down) and not edge_only and now.contact < SMALL_END_SHARE * biggest:
        # standing tall on a small end: lie it down, on whichever low face
        # adds no overhang
        low = [p for p in sides if p.contact >= BASE_SHARE * biggest and now.height >= TALL_RATIO * p.height
               and p.overhang <= now.overhang + 200.0]
        if low:
            best = pick(low)
        else:
            return None, None
    elif not (on_edge or upside_down):
        return None, None
    why = (f"turned onto a flat face: as exported {now.contact:,.0f} mm² rests on the bed and "
           f"{now.overhang:,.0f} mm² faces down in mid-air, now {best.contact:,.0f} and {best.overhang:,.0f} mm²")
    return rotation_onto(best.down, DOWN), why


# ------------------------------------------------------------------ footprint
def convex_hull_2d(points: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain over (n, 2) points; returns the hull CCW."""
    pts = np.unique(np.round(points, 3), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        out: list = []
        for p in seq:
            while len(out) >= 2:
                o, a = out[-2], out[-1]
                if (a[0] - o[0]) * (p[1] - o[1]) - (a[1] - o[1]) * (p[0] - o[0]) <= 0:
                    out.pop()
                else:
                    break
            out.append(p)
        return out

    lower = half(pts)
    upper = half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def min_area_angle(hull: np.ndarray) -> float:
    """Z rotation (radians) that makes the hull's axis-aligned bounding box
    smallest: one of the hull's edges always lies on that box (rotating
    calipers), so trying each edge direction is enough."""
    if len(hull) < 3:
        return 0.0
    best_angle, best_area = 0.0, math.inf
    edges = np.roll(hull, -1, axis=0) - hull
    for dx, dy in edges:
        if abs(dx) + abs(dy) < 1e-9:
            continue
        ang = -math.atan2(dy, dx)
        c, s = math.cos(ang), math.sin(ang)
        xs = hull[:, 0] * c - hull[:, 1] * s
        ys = hull[:, 0] * s + hull[:, 1] * c
        area = (xs.max() - xs.min()) * (ys.max() - ys.min())
        if area < best_area - 1e-6:
            best_area, best_angle = area, ang
    # keep the part as modelled when that is (nearly) as good
    c0 = hull.max(axis=0) - hull.min(axis=0)
    if c0[0] * c0[1] <= best_area * 1.02:
        return 0.0
    return best_angle


def simplify_polygon(poly: np.ndarray, max_points: int = 48) -> np.ndarray:
    """Thin a hull for display (the browser draws it)."""
    if len(poly) <= max_points:
        return poly
    idx = np.linspace(0, len(poly), max_points, endpoint=False).astype(int)
    return poly[idx]
