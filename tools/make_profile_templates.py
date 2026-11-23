#!/usr/bin/env python3
"""Regenerate backend/sorter3mf/profiles/*.json from a local Bambu Studio.

The backend never runs a slicer. What it needs from Bambu Studio is the exact
`Metadata/project_settings.config` Bambu Studio writes for a printer, process
and filament, so a generated project opens with those presets selected. This
tool asks Bambu Studio for it: for each printer it resolves the system
presets, has the Bambu Studio CLI export a one-object project, and keeps the
project settings it wrote. It also exports 1-, 2- and 3-filament projects
once to learn which keys hold one value per filament (`_layout.json`).

It also writes `_colors.json`: each Bambu filament line's colours (name and
hex) from Bambu Studio's own `filaments_color_codes.json`, so the colour
pickers offer what that filament actually comes in.

Run it when Bambu Studio updates its profiles, then commit the JSON:

    python3 tools/make_profile_templates.py
    python3 tools/make_profile_templates.py --bambu /path/to/BambuStudio --profiles /path/to/profiles/BBL

Bambu Studio's profiles are AGPL-3.0; the generated JSON is derived from them.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "sorter3mf" / "profiles"

MAC_APP = Path("/Applications/BambuStudio.app/Contents")
DEFAULT_BIN = MAC_APP / "MacOS" / "BambuStudio"
DEFAULT_PROFILES = MAC_APP / "Resources" / "profiles" / "BBL"

# Every plate the app writes is one colour, so a two-nozzle printer (H2C)
# prints everything with its first (left) nozzle: the template records how
# many extruders there are and the bed area each one reaches, and the backend
# maps every filament to extruder 1. The P1P is left out because Bambu Studio
# 2.9 ships no PLA profile that lists it; P1P owners can pick the P1S (same
# bed).
PRINTERS = [
    ("bambu-lab-a1", "Bambu Lab A1"),
    ("bambu-lab-a1-mini", "Bambu Lab A1 mini"),
    ("bambu-lab-p1s", "Bambu Lab P1S"),
    ("bambu-lab-p2s", "Bambu Lab P2S"),
    ("bambu-lab-x1-carbon", "Bambu Lab X1 Carbon"),
    ("bambu-lab-x1e", "Bambu Lab X1E"),
    ("bambu-lab-h2s", "Bambu Lab H2S"),
    ("bambu-lab-h2c", "Bambu Lab H2C"),
]
PROCESS_BASE = "0.20mm Standard"
FILAMENTS = ["Bambu PLA Matte", "Bambu PLA Basic", "Bambu PETG Matte", "Bambu PETG HF", "Bambu PETG Basic",
             "Generic PLA"]

# Two Bambu Studio sample colours, only so the 2/3-filament exports differ.
SAMPLE_COLOURS = ["#333333", "#A0A0A0"]


class Profiles:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[tuple[str, str], dict] = {}

    def load(self, kind: str, name: str) -> dict:
        return json.loads((self.root / kind / f"{name}.json").read_text())

    def resolve(self, kind: str, name: str) -> dict:
        key = (kind, name)
        if key not in self._cache:
            d = self.load(kind, name)
            base = dict(self.resolve(kind, d["inherits"])) if d.get("inherits") else {}
            base.update(d)
            self._cache[key] = base
        return dict(self._cache[key])

    def names(self, kind: str) -> list[str]:
        return sorted(p.stem for p in (self.root / kind).glob("*.json"))

    def compatible(self, kind: str, base: str, machine: str) -> str | None:
        """The instantiable preset called `base` or `base @...` that lists
        `machine` among its compatible printers."""
        hits = []
        for n in self.names(kind):
            if not (n == base or n.startswith(base + " @")):
                continue
            try:
                d = self.resolve(kind, n)
            except Exception:
                continue
            if d.get("instantiation") == "false":
                continue
            if machine in (d.get("compatible_printers") or []):
                hits.append(n)
        # prefer the plainest name ("... @BBL A1" over "... @BBL A1 0.2 nozzle")
        return sorted(hits, key=len)[0] if hits else None


def system_json(p: Profiles, kind: str, name: str, colour: str | None = None) -> dict:
    d = p.resolve(kind, name)
    d.pop("inherits", None)
    d["from"] = "system"
    if colour:
        d["filament_colour"] = [colour]
    return d


def write_cube(path: Path) -> None:
    v = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 20), (20, 0, 20), (20, 20, 20), (0, 20, 20)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    lines = ["solid cube"]
    for t in f:
        lines.append(" facet normal 0 0 0\n  outer loop")
        for i in t:
            lines.append("   vertex %g %g %g" % v[i])
        lines.append("  endloop\n endfacet")
    lines.append("endsolid cube")
    path.write_text("\n".join(lines) + "\n")


def export(bambu: Path, work: Path, machine: dict, process: dict, filaments: list[dict], stl: Path, tag: str) -> dict:
    files = []
    for i, (kind, d) in enumerate([("machine", machine), ("process", process)] + [("filament", f) for f in filaments]):
        fp = work / f"{tag}-{i}-{kind}.json"
        fp.write_text(json.dumps(d, indent=1))
        files.append(fp)
    out = work / f"{tag}.3mf"
    cmd = [str(bambu),
           "--load-settings", f"{files[0]};{files[1]}",
           "--load-filaments", ";".join(str(f) for f in files[2:]),
           "--export-3mf", str(out), str(stl)]
    # Bambu Studio drops a result.json in its working directory
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"Bambu Studio failed ({r.returncode}) for {tag}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    with zipfile.ZipFile(out) as z:
        return json.loads(z.read("Metadata/project_settings.config"))


def write_colors(profiles: Path) -> None:
    """Single-colour entries of Bambu Studio's colour table, per filament line
    ("PETG Matte": [{name, hex, code}, ...]) for the lines in FILAMENTS."""
    src = profiles / "filament" / "filaments_color_codes.json"
    if not src.exists():
        sys.exit(f"no colour table at {src}")
    data = json.loads(src.read_text())["data"]
    wanted = {f.removeprefix("Bambu ") for f in FILAMENTS if f.startswith("Bambu ")}
    out: dict[str, list[dict]] = {}
    for e in data:
        if e.get("fila_type") in wanted and len(e.get("fila_color") or []) == 1:
            name = (e.get("fila_color_name") or {}).get("en") or e.get("fila_color_code")
            out.setdefault(e["fila_type"], []).append(
                {"name": name, "hex": e["fila_color"][0][:7].upper(), "code": e.get("fila_color_code")})
    (OUT / "_colors.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote _colors.json: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(out.items())))


def bed_of(machine: dict) -> dict:
    def pts(v):
        return [[float(c) for c in s.split("x")] for s in (v or [])]
    return {
        "printable_area": pts(machine.get("printable_area")),
        "bed_exclude_area": pts(machine.get("bed_exclude_area")),
        "printable_height": float(machine.get("printable_height", 250)),
        "extruders": len(machine.get("nozzle_diameter") or ["0.4"]),
        # what each nozzle of a multi-nozzle printer reaches ("0x0,325x0,...")
        "extruder_printable_area": [pts(a.split(",")) for a in machine.get("extruder_printable_area") or []],
    }


def classify(n1: dict, n2: dict, n3: dict) -> dict:
    per_filament, bracketed, square, other = [], [], [], []
    for k in n1:
        a, b, c = n1[k], n2[k], n3[k]
        if not all(isinstance(x, list) for x in (a, b, c)):
            continue
        lens = (len(a), len(b), len(c))
        if lens[0] == lens[1] == lens[2]:
            continue
        if lens == (1, 2, 3):
            per_filament.append(k)
        elif lens == (3, 4, 5):
            bracketed.append(k)
        elif lens[1] == 4 * lens[0] and lens[2] == 9 * lens[0]:
            square.append(k)  # N x N, once per extruder
        else:
            other.append([k, list(lens)])
    if other:
        sys.exit(f"unexpected per-filament key shapes, teach the backend about them: {other}")
    return {"per_filament": sorted(per_filament),
            "process_filaments_printer": sorted(bracketed),
            "filament_matrix": sorted(square)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bambu", type=Path, default=Path(os.environ.get("BAMBU_STUDIO_BIN", DEFAULT_BIN)))
    ap.add_argument("--profiles", type=Path, default=Path(os.environ.get("BAMBU_PROFILES", DEFAULT_PROFILES)))
    args = ap.parse_args()
    if not args.bambu.exists():
        sys.exit(f"Bambu Studio not found at {args.bambu} (pass --bambu)")
    if not args.profiles.is_dir():
        sys.exit(f"Bambu Studio profiles not found at {args.profiles} (pass --profiles)")

    prof = Profiles(args.profiles)
    OUT.mkdir(parents=True, exist_ok=True)
    write_colors(args.profiles)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        stl = work / "cube.stl"
        write_cube(stl)

        layout = None
        index = []
        for slug, model in PRINTERS:
            machine_name = f"{model} 0.4 nozzle"
            try:
                machine = system_json(prof, "machine", machine_name)
            except FileNotFoundError:
                print(f"skip {machine_name}: no such profile")
                continue
            process_name = prof.compatible("process", PROCESS_BASE, machine_name)
            if not process_name:
                print(f"skip {machine_name}: no {PROCESS_BASE} process")
                continue
            process = system_json(prof, "process", process_name)

            filament_values: dict[str, dict] = {}
            settings = None
            for fil in FILAMENTS:
                fname = prof.compatible("filament", fil, machine_name)
                if not fname:
                    print(f"  {machine_name}: no {fil} profile")
                    continue
                f1 = system_json(prof, "filament", fname, SAMPLE_COLOURS[0])
                n1 = export(args.bambu, work, machine, process, [f1], stl, f"{slug}-{fil}-1".replace(" ", "_"))
                if layout is None:
                    f2 = system_json(prof, "filament", fname, SAMPLE_COLOURS[1])
                    n2 = export(args.bambu, work, machine, process, [f1, f2], stl, f"{slug}-2")
                    n3 = export(args.bambu, work, machine, process, [f1, f2, f1], stl, f"{slug}-3")
                    layout = classify(n1, n2, n3)
                    (OUT / "_layout.json").write_text(json.dumps(layout, indent=1) + "\n")
                if settings is None:
                    settings = n1
                filament_values[fil] = {k: n1[k][0] for k in layout["per_filament"]}
                print(f"  {machine_name}: {fname}")
            if settings is None:
                continue
            doc = {
                "id": slug,
                "name": model,
                "machine": machine_name,
                "process": process_name,
                "bambu_studio_version": settings.get("version"),
                "bed": bed_of(machine),
                "filaments": filament_values,
                "settings": settings,
            }
            (OUT / f"{slug}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            index.append({"id": slug, "name": model})
            print(f"wrote {slug}.json ({process_name})")
    (OUT / "_index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"done: {len(index)} printers, Bambu Studio on {platform.system()}")


if __name__ == "__main__":
    main()
