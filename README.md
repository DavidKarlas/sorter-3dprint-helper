# Sorter V2 print helper

A small web app that turns the [Sorter V2](https://github.com/basicallysource/sorter-v2)
printed parts into Bambu Studio projects you open and print: every part
downloaded, posed, laid out on plates one colour at a time, with your printer,
filament and print settings already chosen.

You pick the machine (layers and bin sizes, Orange Pi housing, optional
parts), which parts of it to print (any branch of the assembly tree: the
feeder, C-channel 2, the bins, the PSU housing...), the colours (and which
of them to print now, say only the black parts), and the printer and print
settings. The
app works out what to print the same way the
[parts calculator](https://parts-calculator.basically.website/) does, and
writes one `.3mf` (or a few, see below) that loads straight into Bambu Studio.

## Running it

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)) and frontend (Node 20+):

```bash
cd backend && uv sync && uv run uvicorn sorter3mf.api:app --reload    # http://127.0.0.1:8000
cd frontend && npm install && npm run dev                               # http://127.0.0.1:5173
```

Vite proxies `/api` to the backend. For one process, build the frontend
(`npm run build`) and the backend serves `frontend/dist` itself.

With Docker:

```bash
docker build -t sorter-3dprint-helper .
docker run -p 8000:8000 -v sorter3mf-cache:/data sorter-3dprint-helper
```

Tests: `cd backend && uv run pytest`.

### The published image

`.github/workflows/docker.yml` runs the tests and builds the image for
amd64 and arm64 on every push and pull request. Pushes to `main` publish
`ghcr.io/davidkarlas/sorter-3dprint-helper:latest` (and `:sha-<commit>`); a
tag `v1.2.3` also publishes `:1.2.3` and `:1.2`. Pull requests only build.
The image has this repository's URL built in as the source link. GitHub
creates the package as private on its first publish: make it public in the
package's settings, or give the cluster a pull secret.

### Running on Kubernetes

The image runs as uid/gid 10001, needs no capabilities, and writes only to
`/data`, so it works with `runAsNonRoot`, `readOnlyRootFilesystem` (give it
an `emptyDir` for `/tmp`) and `allowPrivilegeEscalation: false`. For
`/data` an `emptyDir` is enough (the cache refills itself); with a
PersistentVolumeClaim set `fsGroup: 10001` so the user can write to it.

- **One replica.** Builds and their progress live in the process's memory,
  so a second pod would answer "no such build" for the first one's jobs.
  One pod handles this easily: a full build takes about 5 s of CPU and
  ~210 MB of memory, and `SORTER3MF_MAX_JOBS` (2) run at once.
- **Outbound HTTPS** to `raw.githubusercontent.com` (the catalog) and
  `assets.basically.website` (the STLs).
- **Probes:** `GET /api/health`.
- **Source link:** the published image already points at this repository;
  set `SORTER3MF_SOURCE_URL` only when you deploy a fork (see Licence).

```yaml
securityContext:            # pod
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
containers:
  - name: app
    image: ghcr.io/davidkarlas/sorter-3dprint-helper:latest
    ports: [{containerPort: 8000}]
    securityContext:
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities: {drop: [ALL]}
    resources:
      requests: {cpu: 500m, memory: 256Mi}
      limits: {memory: 512Mi}
    readinessProbe: {httpGet: {path: /api/health, port: 8000}}
    livenessProbe: {httpGet: {path: /api/health, port: 8000}}
    volumeMounts: [{name: data, mountPath: /data}, {name: tmp, mountPath: /tmp}]
volumes:
  - {name: data, emptyDir: {}}
  - {name: tmp, emptyDir: {}}
```

### Configuration

| Variable | Default | What it does |
|---|---|---|
| `SORTER_REPO` | unset | Path to a local sorter-v2 checkout. Read the catalog from there instead of GitHub. |
| `SORTER_RAW_BASE` | `https://raw.githubusercontent.com/basicallysource/sorter-v2/main` | Where the catalog is fetched from. |
| `SORTER_CATALOG_TTL` | `600` | Seconds a fetched catalog is reused. |
| `SORTER3MF_CACHE` | `~/.cache/sorter3mf` | Downloaded STLs, prepared meshes, finished builds. |
| `SORTER3MF_JOB_TTL` | `3600` | Seconds a finished build stays downloadable. |
| `SORTER3MF_MAX_JOBS` | `2` | Builds that run at once. |
| `SORTER3MF_SOURCE_URL` | unset | This app's source repository, linked from the page (see Licence). |

## How it works

1. **The catalog.** The parts list, quantities, colours and STL links come
   from `parts-calculator/src/lib/data/catalog.generated.json` in sorter-v2,
   and the colour palette from `bambu-colors.ts` next to it. Nothing is copied
   into this repo.
2. **What to print** (`backend/sorter3mf/bom.py`) mirrors the parts
   calculator: section quantities times the layer count (with each part's
   `layer_scope`), bins and funnels from each layer's size, the Orange Pi
   alternative, and per-section colours (role, fixed, split). If the
   calculator changes how it counts, this file changes with it. Layers can
   go down to zero, which prints the rest of the machine without any.
2. **Where each copy goes** (`tree.py`) follows the calculator's
   `src/lib/uses.ts`: the sections say how many, the assembly tree says
   where, and every copy is attributed to one place in the tree (C-channel 2,
   the camera lamp of C-channel 3, a distribution layer...). Those places are
   the checkboxes. Copies the tree cannot place land in a "not in the
   assembly tree yet" group, so nothing goes missing. Bins start unticked, as
   in the calculator. A colour filter under the tree leaves out the pieces of
   the colours switched off, in the filament's own colours (after the
   palette move below), so "only Black" means the pieces printed in Black.
4. **Parts** (`parts.py`) are downloaded from the asset service. The URLs are
   content-addressed, so every download is checked against the hash in its
   name and cached for good. Parts the catalog says are not exported in their
   print pose are turned using `orientation.json` (the 90° frame bracket uses
   the pose from the curated bracket plate; the Orange Pi housing walls are
   laid flat). Each part is also turned about Z so its footprint box is as
   small as possible.
5. **Plates** (`packing.py`) are filled per colour (or per section and
   colour), so no plate needs a filament change. Footprint boxes are packed
   with MaxRects; parts may turn 90°. Each plate's parts are then moved as
   one group to the middle of the bed (a lone rotor or stator sits dead
   centre), unless that would bring them too close to an excluded corner. Parts that print with support get extra
   room (8 mm, 20 mm with tree supports), because supports reach past the
   part and Bambu Studio refuses a plate whose toolpaths cross. The printer's excluded bed
   corner (X1/P1) is kept clear.
6. **The project** (`threemf.py`, `printers.py`) is written the way Bambu
   Studio writes its own: one shared mesh per part, one object per printed
   piece, plates in `model_settings.config`, and the full printer + process +
   filament settings in `project_settings.config` with one filament slot per
   colour. Supports are set per object, only on the parts that need them.

Bambu Studio opens at most **36 plates per project**. A full machine needs
more, so a build that does not fit is split into several files. A colour stays
in one file where it can. Each file is a complete project.

### Printer profiles

`backend/sorter3mf/profiles/*.json` were written by Bambu Studio itself:
`tools/make_profile_templates.py` asks the Bambu Studio CLI to export a
project for each printer (0.20 mm Standard process; Bambu PLA Matte, PLA
Basic, PETG Matte, PETG HF, PETG Basic, and Generic PLA) and keeps the
settings it wrote. Re-run it after a Bambu Studio update. It needs Bambu
Studio installed.

### Print settings

Projects start from Bambu's 0.20 mm Standard process for the printer, with
gyroid infill. Walls and the outer wall's speed and acceleration are left to
the preset (2 walls, a 200 mm/s outer wall at 5000 mm/s² or more) unless you
set them. "Recommended" sets what the Sorter community prints these parts
with when walls come out rough: 3 walls and an outer wall at 80 mm/s and
2500 mm/s². Sliced in Bambu Studio, C-channel 2 on an A1 with those settings
and gyroid takes about 24% more filament and 49% more time (1138 g / 34 h
against 920 g / 23 h with the preset and adaptive cubic). Bambu Studio shows
the process as modified and lists the keys that differ. Dry the filament if
the roll has been open a while.

### Filaments and colours

Each Bambu filament line offers the colours it is sold in, taken from Bambu
Studio's own colour table (`profiles/_colors.json`, written by the same
tool). PLA Matte is the catalog's palette. When you switch filament, every
colour choice moves to the nearest colour in the new palette, and so do the
catalog's fixed colours: Charcoal becomes PETG Matte Black, and the gray
rotors and stators stay gray. The colour filter moves with them; where two
colours land on one, it stays off only if both were off. The plate types offered are the ones the
filament's profile has a bed temperature for (PETG Matte: no Cool Plate;
PLA Matte: no Engineering Plate). Gram figures come from the catalog's PLA
Matte slices, scaled by the filament's density.

Supported: A1, A1 mini, P1S, P2S, X1 Carbon, X1E, H2S. Bambu Studio 2.9 ships
no PLA profile for the P1P, so it is left out (use the P1S, same bed).
Two-nozzle printers (H2D) are not supported yet.

### What is already printed

The parts list has a **Printed** column: how many pieces of each part are
done (per colour, for a part that comes in more than one). The ✓ marks a part
fully printed. A build prints only what is left, and the totals count only
that. Printed counts move with the colours when you switch filament: a piece
printed in Charcoal counts for the part that is now PETG Black. A count in a
colour the part no longer uses (you changed a role colour) does not count,
and stays visible so you can clear it.

### Checking output with Bambu Studio

```bash
python3 tools/validate_3mf.py path/to/sorter-v2-parts-1-of-2.3mf ...
```

This loads each project in the Bambu Studio CLI and slices every plate. It
fails if a plate is missing, slices a different number of objects than it
holds, or Bambu Studio refuses it (for example, toolpaths of two parts
crossing). Run it after changing the packer or the 3MF writer.

## Why not estampo

[estampo](https://estampo.dev/) was considered. It slices one arranged plate
in Docker and writes a sliced `.gcode.3mf`. This build needs dozens of plates,
a colour per plate, per-part supports and an unsliced project you can still
edit, so the project is written directly. estampo remains a good fit for
slicing in CI.

## Known limits

- Packing uses footprint boxes. Bambu Studio's own Arrange (per plate) can
  often fit a little more.
- Grams and hours are the catalog's per-part figures (A1, 0.20 mm, 15%
  adaptive cubic, PLA Matte) added up, with grams scaled by density for
  other filaments. Hours are not adjusted: PETG prints slower. A full plate
  prints faster than the sum.
- Purge volumes between colours are an estimate. Bambu Studio recalculates
  them when you change a colour. With one colour per plate they are not used.
- What is printed is kept in the browser (with the other settings), so it
  does not follow you to another browser or computer.
- The project declares itself a Bambu Studio project (the `Application`
  metadata) so Bambu Studio loads its plates and settings. An older Bambu
  Studio may warn that the file comes from a newer version.

## Licence

GNU Affero General Public License v3.0 only, see `LICENSE`, the same licence
as the Bambu Studio profiles the printer templates in
`backend/sorter3mf/profiles/` are exported from.

The AGPL covers use over a network: if you run a modified version where
others can use it, offer them its source. Set `SORTER3MF_SOURCE_URL` to your
repository and the page links to it.

The part models are not in this repository. The app downloads them from the
Sorter V2 asset service at build time, and they carry the Sorter V2
project's licence, as do the `.3mf` files built from them.
