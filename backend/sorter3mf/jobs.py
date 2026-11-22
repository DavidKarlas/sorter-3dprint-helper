"""Background builds: one job per "build my 3MF" request.

Jobs live in memory and their files on disk under CACHE_DIR/jobs/<id>/; both
are dropped JOB_TTL_S after they finish. A server restart forgets them,
which is fine for files that take seconds to rebuild.
"""

from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .bom import BuildConfig
from .build import BuildResult, PrintOptions, run_build
from .catalog import load_catalog

# How far along the bar each stage starts and how much of it it covers.
STAGES = {"queued": (0.0, 0.0), "bom": (0.0, 0.02), "parts": (0.02, 0.78), "pack": (0.80, 0.05),
          "write": (0.85, 0.15), "done": (1.0, 0.0)}


@dataclass
class Job:
    id: str
    created: float
    status: str = "queued"  # queued | running | done | failed
    stage: str = "queued"
    progress: float = 0.0
    message: str = "Waiting for a free builder"
    error: str | None = None
    result: BuildResult | None = None
    finished: float | None = None
    dir: Path = field(default_factory=Path)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_JOBS, thread_name_prefix="build")


def _jobs_root() -> Path:
    d = config.CACHE_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _expire() -> None:
    now = time.time()
    with _lock:
        old = [j for j in _jobs.values() if j.finished and now - j.finished > config.JOB_TTL_S]
        for j in old:
            _jobs.pop(j.id, None)
    for j in old:
        shutil.rmtree(j.dir, ignore_errors=True)


def submit(cfg: BuildConfig, opts: PrintOptions) -> Job:
    _expire()
    jid = uuid.uuid4().hex[:16]
    job = Job(id=jid, created=time.time(), dir=_jobs_root() / jid)
    with _lock:
        _jobs[jid] = job

    def progress(stage: str, frac: float, msg: str) -> None:
        start, span = STAGES.get(stage, (job.progress, 0.0))
        job.stage = stage
        job.progress = min(1.0, start + span * max(0.0, min(1.0, frac)))
        job.message = msg

    def run() -> None:
        job.status = "running"
        try:
            job.result = run_build(load_catalog(), cfg, opts, job.dir, progress)
            job.status = "done"
        except Exception as e:
            traceback.print_exc()
            job.status = "failed"
            job.error = str(e) or e.__class__.__name__
            job.message = "Build failed"
        finally:
            job.finished = time.time()

    _pool.submit(run)
    return job


def get(jid: str) -> Job | None:
    with _lock:
        return _jobs.get(jid)
