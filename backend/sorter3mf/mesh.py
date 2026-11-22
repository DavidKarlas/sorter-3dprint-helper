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
