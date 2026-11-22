"""Runtime configuration, all from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Where the parts catalog comes from. The catalog is the generated file the
# Sorter V2 parts calculator ships (parts, quantities, colours, STL URLs).
# SORTER_REPO points at a local checkout of basicallysource/sorter-v2 and wins
# over the URLs, which is handy while working on the catalog itself.
SORTER_REPO = os.environ.get("SORTER_REPO", "").strip()
RAW_BASE = os.environ.get(
    "SORTER_RAW_BASE",
    "https://raw.githubusercontent.com/basicallysource/sorter-v2/main",
).rstrip("/")
CATALOG_PATH = "parts-calculator/src/lib/data/catalog.generated.json"
COLORS_PATH = "parts-calculator/src/lib/bambu-colors.ts"

# How long a fetched catalog is trusted before it is fetched again.
CATALOG_TTL_S = int(os.environ.get("SORTER_CATALOG_TTL", "600"))

# Downloaded STLs, prepared meshes and finished projects. STL URLs are
# content-addressed (the name carries a hash of the bytes), so a cached STL
# never goes stale.
CACHE_DIR = Path(os.environ.get("SORTER3MF_CACHE", Path.home() / ".cache" / "sorter3mf"))

# Finished files are kept this long for download.
JOB_TTL_S = int(os.environ.get("SORTER3MF_JOB_TTL", "3600"))
MAX_PARALLEL_JOBS = int(os.environ.get("SORTER3MF_MAX_JOBS", "2"))
DOWNLOAD_WORKERS = int(os.environ.get("SORTER3MF_DOWNLOAD_WORKERS", "8"))

# The built React app, served by the backend in production.
FRONTEND_DIST = Path(
    os.environ.get("SORTER3MF_FRONTEND", Path(__file__).resolve().parents[2] / "frontend" / "dist")
)

USER_AGENT = "sorter-3dprint-helper/0.1 (+https://github.com/basicallysource/sorter-v2)"

# Where this app's source can be had. The AGPL asks a server that runs a
# modified version to offer its users the source; set this to the repository
# (or the fork that is deployed) and the page links to it.
SOURCE_URL = os.environ.get("SORTER3MF_SOURCE_URL", "").strip()
