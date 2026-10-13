"""Cap the BLAS thread pool for the taste model's small solves (no numpy import here).

The model, meter and pair choice solve many tiny systems (k <= 64 dims, a few hundred rows). OpenBLAS starts one
thread per core for each of them; on a busy 32-core host that cost 4.4 s wall / 108 s CPU for one quick meter instead
of 0.25 s with a single thread (review round 2). `slop taste sheet / record / meter / fit` run inside `small_blas()`:

  * with threadpoolctl installed (scikit-learn ships it): the BLAS pools are limited while the block runs;
  * without it, and before numpy is imported: OPENBLAS_NUM_THREADS / MKL_NUM_THREADS are set (unless the user set
    them), which numpy reads once at import — the CLI imports numpy lazily, so this works for one-shot commands.

The tap server's child process gets OPENBLAS_NUM_THREADS the same way (server.serve), so its refits and meter do not
fight the background image embedding (torch keeps its own thread setting).
"""
from __future__ import annotations

import contextlib
import os
import sys

SMALL = 4
BLAS_ENV = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def blas_env(n: int = SMALL) -> dict[str, str]:
    """environment entries that cap BLAS threads in a NEW process (only those the user has not set)"""
    return {k: str(n) for k in BLAS_ENV if not os.environ.get(k)}


@contextlib.contextmanager
def small_blas(n: int = SMALL):
    n = max(1, min(n, os.cpu_count() or n))
    try:
        from threadpoolctl import threadpool_limits
    except Exception:  # noqa: BLE001 — not installed: the environment fallback (works before numpy is imported)
        if "numpy" not in sys.modules:
            for k, v in blas_env(n).items():
                os.environ[k] = v
        yield
        return
    with threadpool_limits(limits=n, user_api="blas"):
        yield
