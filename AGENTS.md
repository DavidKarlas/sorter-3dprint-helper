# AGENTS.md

Working rules for this repository. `README.md` says what the app does and how
it works; read it first.

## Where things live

| Path | What it is |
|---|---|
| `backend/sorter3mf/bom.py` | What to print for a machine config. Mirrors the sorter-v2 parts calculator. |
| `backend/sorter3mf/tree.py` | The assembly tree as checkboxes: which place each copy belongs to (after the calculator's `uses.ts`) |
| `backend/sorter3mf/parts.py`, `mesh.py`, `orientation.json` | STL download, cache, print pose, footprint |
| `backend/sorter3mf/packing.py` | Plate packing (MaxRects) and the outline check |
| `backend/sorter3mf/build.py` | Config → plates → files. Per-object supports and print overrides. |
| `backend/sorter3mf/threemf.py` | The Bambu Studio project writer |
| `backend/sorter3mf/printers.py`, `profiles/` | Printer templates and project settings |
| `backend/sorter3mf/palettes.py`, `profiles/_colors.json` | Colours per filament line, nearest-colour mapping (mirrored in `frontend/src/palette.ts`) |
| `backend/sorter3mf/api.py`, `jobs.py` | FastAPI app and background builds |
| `frontend/src/` | React app (Vite, TypeScript) |
| `tools/` | Dev tools that need a local Bambu Studio |

## Rules

- **Never hand-edit `backend/sorter3mf/profiles/*.json`.** Regenerate them
  with `tools/make_profile_templates.py`. `_layout.json` records which
  settings keys hold one value per filament. The backend expands those keys
  for N colours and relies on that file being right.
- **`bom.py` follows the parts calculator.** The counting rules live in
  sorter-v2 `parts-calculator/src/lib/filament.ts`, `src/routes/+page.svelte`
  (`variantCount`), `src/lib/alternatives.svelte.ts` and `src/lib/uses.ts`. Change `bom.py`
  when those change, and keep `tests/test_bom.py` in step.
- **After touching `threemf.py`, `packing.py` or `build.py`**, build a real
  project and run `tools/validate_3mf.py` on it. Unit tests cannot see what
  Bambu Studio refuses: toolpath conflicts, plates it drops, settings it
  rejects.
- **Selection keys are tree paths** (`machine/feeder/channel-two/...`, a
  `/#parts` suffix for an assembly's own parts). They are saved in people's
  browsers, so a catalog change that renames an assembly id quietly resets
  that checkbox. That is acceptable, but don't build anything that relies on
  keys staying stable.
- **No binaries in git**: no STL, 3MF, zip or image. Parts come from the
  asset service by URL. Builds go to the cache directory.
- **3MF transforms apply to row vectors** (`p' = p · M`), so the matrix
  written is the transpose of the usual rotation. `orientation.json`
  matrices use the column-vector convention.
- Frontend look follows sorter-v2 `software/sorter-design-system`: planes
  told apart by fill, no panel borders, 1px corners, the primary only for
  what is acted on. Tokens are in `frontend/src/styles.css`.
