"""Fetching part STLs and putting each one into its print pose.

STL URLs on the asset service are content-addressed: the name ends in the
first 12 hex digits of the sha256 of the bytes. A download is checked against
that, and the cached copy is reused forever.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from . import config
from .mesh import Mesh, convex_hull_2d, largest_face_down, min_area_angle, read_stl, rot_x, rot_z, simplify_polygon

# Bump when the preparation below changes, so cached prepared meshes are redone.
PREP_VERSION = 3
HINTS: dict = json.loads((Path(__file__).resolve().parent / "orientation.json").read_text())

_HASH_RE = re.compile(r"-([0-9a-f]{12})\.stl$")


def _stl_dir() -> Path:
    d = config.CACHE_DIR / "stl"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prep_dir() -> Path:
    d = config.CACHE_DIR / "prepared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cached_stl_path(url: str) -> Path:
    name = url.rsplit("/", 1)[-1]
    if not name.endswith(".stl") or "/" in name or ".." in name:
        name = hashlib.sha256(url.encode()).hexdigest()[:24] + ".stl"
    return _stl_dir() / name


def fetch_stl(url: str, client: httpx.Client) -> Path:
    path = cached_stl_path(url)
    if path.exists() and path.stat().st_size > 84:
        return path
    r = client.get(url, timeout=120)
    r.raise_for_status()
    data = r.content
    m = _HASH_RE.search(url)
    if m and hashlib.sha256(data).hexdigest()[:12] != m.group(1):
        raise ValueError(f"{url}: downloaded bytes do not match the hash in the name")
    tmp = path.with_suffix(f".tmp{threading.get_ident()}")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


@dataclass
class PreparedPart:
    """A part in its print pose: resting on z=0, centred on its footprint box."""
    key: str
    vertices: np.ndarray  # float32 (n, 3)
    triangles: np.ndarray  # int32 (m, 3)
    width: float  # footprint box, x
    depth: float  # footprint box, y
    height: float
    hull: np.ndarray  # footprint outline (k, 2), centred like the mesh
    note: str | None  # what was done to the pose, for the build report


def _hint_rotation(part_id: str, mesh: Mesh, stl_url: str) -> tuple[np.ndarray, str | None]:
    hint = HINTS.get(part_id)
    if not hint:
        return np.eye(3), None
    if "matrix" in hint:
        note = "turned to the pose of the curated plate"
        src = hint.get("derived_from")
        if src and src not in stl_url.rsplit("/", 1)[-1]:
            note += " (measured on an older export; check it)"
        return np.array(hint["matrix"], dtype=np.float64), note
    if hint.get("rotate") == "flip":
        return rot_x(180), "turned upside down, top face on the bed"
    if hint.get("rotate") == "lay-flat":
        return largest_face_down(mesh), "laid flat on its largest face"
    return np.eye(3), None


def prepare(part_id: str, stl_path: Path, stl_url: str) -> PreparedPart:
    sig = hashlib.sha1(json.dumps([PREP_VERSION, stl_path.name, HINTS.get(part_id)], sort_keys=True).encode()).hexdigest()[:16]
    cache = _prep_dir() / f"{part_id}-{sig}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        note = str(z["note"]) or None
        return PreparedPart(part_id, z["v"], z["t"], float(z["dims"][0]), float(z["dims"][1]),
                            float(z["dims"][2]), z["hull"], note)

    mesh = read_stl(stl_path.read_bytes())
    lo, hi = mesh.bounds
    mesh = Mesh(mesh.vertices - (lo + hi) / 2, mesh.triangles)
    rot, note = _hint_rotation(part_id, mesh, stl_url)
    mesh = mesh.transformed(rot)
    # turn about z so the footprint box is as small as it gets
    hull = convex_hull_2d(mesh.vertices[:, :2])
    ang = min_area_angle(hull)
    if ang:
        mesh = mesh.transformed(rot_z(ang))
    lo, hi = mesh.bounds
    v = mesh.vertices - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    hull = simplify_polygon(convex_hull_2d(v[:, :2]))
    size = hi - lo
    out = PreparedPart(part_id, v.astype(np.float32), mesh.triangles.astype(np.int32),
                       float(size[0]), float(size[1]), float(size[2]), hull.astype(np.float32), note)
    tmp = cache.with_suffix(f".tmp{threading.get_ident()}.npz")
    np.savez_compressed(tmp, v=out.vertices, t=out.triangles, hull=out.hull,
                        dims=np.array([out.width, out.depth, out.height]), note=np.array(note or ""))
    tmp.replace(cache)
    return out
