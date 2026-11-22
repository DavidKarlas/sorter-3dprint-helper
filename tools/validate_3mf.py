#!/usr/bin/env python3
"""Check generated projects with a real Bambu Studio: load, slice every
plate, and compare what it sliced with what the file says is on each plate.

    python3 tools/validate_3mf.py out/sorter-v2-parts.3mf [more.3mf ...]
    python3 tools/validate_3mf.py --no-slice file.3mf      # load + re-export only

Needs Bambu Studio installed (BAMBU_STUDIO_BIN or --bambu). Exits non-zero
when Bambu Studio refuses a file, a plate is missing, a plate slices a
different number of objects than it holds, or slicing reports an error.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

DEFAULT_BIN = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"


def plates_in(path: Path) -> dict[int, list[str]]:
    """plate number -> object ids, from Metadata/model_settings.config."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("Metadata/model_settings.config"))
    out = {}
    for pl in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
        ids = []
        for mi in pl.findall("model_instance"):
            mm = {m.get("key"): m.get("value") for m in mi.findall("metadata")}
            ids.append(mm.get("object_id"))
        out[int(meta["plater_id"])] = ids
    return out


def sliced_plates(path: Path) -> tuple[dict[int, dict], list[str]]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        root = ET.fromstring(z.read("Metadata/slice_info.config"))
    out = {}
    warnings = []
    for pl in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
        idx = int(meta.get("index", 0))
        objs = pl.findall("object")
        # the plate's own "weight" is left empty on some plates; the
        # per-filament used_g always says it
        used = sum(float(f.get("used_g") or 0) for f in pl.findall("filament"))
        out[idx] = {
            "objects": len(objs),
            "skipped": sum(1 for o in objs if o.get("skipped") == "true"),
            "weight": meta.get("weight") or used,
            "prediction": meta.get("prediction"),
            "gcode": f"Metadata/plate_{idx}.gcode" in names,
        }
        for w in pl.findall("warning"):
            warnings.append(f"plate {idx}: {w.get('msg')} ({w.get('error_code', '')})")
    return out, warnings


FORBIDDEN = set('<>:/\\|?*"')


def bad_names(path: Path) -> list[str]:
    """Names Bambu Studio's GUI refuses to load ("Invalid name, the following
    characters are not allowed"). The CLI loads them anyway, so check here."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("Metadata/model_settings.config"))
    out = []
    for el in root.iter("metadata"):
        if el.get("key") in ("name", "plater_name") and FORBIDDEN & set(el.get("value") or ""):
            out.append(f'{el.get("key")} "{el.get("value")}"')
    return sorted(set(out))


def check(path: Path, bambu: str, do_slice: bool) -> bool:
    expected = plates_in(path)
    print(f"{path.name}: {len(expected)} plates, {sum(len(v) for v in expected.values())} objects")
    names = bad_names(path)
    if names:
        print(f"  FAIL: {len(names)} names Bambu Studio will refuse: " + ", ".join(names[:8]))
        return False
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.3mf"
        cmd = [bambu]
        if do_slice:
            cmd += ["--slice", "0"]
        cmd += ["--export-3mf", str(out), str(path.resolve())]
        t = time.time()
        # Bambu Studio drops a result.json in its working directory
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
        took = time.time() - t
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or not out.exists():
            print(f"  FAIL: Bambu Studio exited {r.returncode} after {took:.0f}s")
            for line in log.splitlines()[-15:]:
                print("   ", line)
            return False
        print(f"  Bambu Studio OK in {took:.0f}s")
        reloaded = plates_in(out)
        ok = True
        if len(reloaded) != len(expected):
            print(f"  FAIL: re-exported project has {len(reloaded)} plates, expected {len(expected)}")
            ok = False
        for n, ids in expected.items():
            if len(reloaded.get(n, [])) != len(ids):
                print(f"  FAIL: plate {n} came back with {len(reloaded.get(n, []))} objects, expected {len(ids)}")
                ok = False
        if not do_slice:
            return ok
        sliced, warns = sliced_plates(out)
        for n, ids in expected.items():
            s = sliced.get(n)
            if not s or not s["gcode"]:
                print(f"  FAIL: plate {n} was not sliced")
                ok = False
                continue
            if s["objects"] - s["skipped"] != len(ids):
                print(f"  FAIL: plate {n} sliced {s['objects'] - s['skipped']} objects, holds {len(ids)}")
                ok = False
        total_g = sum(float(s["weight"] or 0) for s in sliced.values())
        total_s = sum(int(float(s["prediction"] or 0)) for s in sliced.values())
        print(f"  sliced {len(sliced)} plates: {total_g:.0f} g, {total_s / 3600:.1f} h")
        # the same warning on every plate (e.g. timelapse) is printed once
        seen: dict[str, list[str]] = {}
        for w in warns:
            plate, _, msg = w.partition(": ")
            seen.setdefault(msg, []).append(plate.replace("plate ", ""))
        for msg, plates in seen.items():
            print(f"  warning on plate(s) {', '.join(plates)}: {msg}")
        return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--bambu", default=os.environ.get("BAMBU_STUDIO_BIN", DEFAULT_BIN))
    ap.add_argument("--no-slice", action="store_true", help="only load and re-export")
    args = ap.parse_args()
    if not Path(args.bambu).exists():
        sys.exit(f"Bambu Studio not found at {args.bambu}")
    results = [check(f, args.bambu, not args.no_slice) for f in args.files]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
