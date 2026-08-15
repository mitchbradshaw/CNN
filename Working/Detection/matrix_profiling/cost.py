"""
cost.py
========
Per-machine cost calibration and routing-tier estimation for matrix
profile computation (MATRIX_PROFILE_UI_PROMPT.md §3).

`stump` is O(n^2/T) in series length and effectively flat in window
length `m` (the sliding dot-product update is incremental), so a single
calibrated constant per backend is enough: `t_est(n) = k_backend * n**2`.
Never falls back to a hardcoded constant — `estimate_seconds` returns
`None` when uncalibrated, which is the honest answer (a wrong estimate
here would route a long job into the "wait with a spinner" interactive
path).
"""

import datetime
import json
import multiprocessing
import os
import time

import numpy as np
import stumpy

from Working.config import MP_BACKGROUND_BUDGET_S, MP_INTERACTIVE_BUDGET_S

CALIBRATION_PATH = os.path.join("DATA", "db", "mp_calibration.json")
CALIBRATION_N0 = 20_000
BACKENDS = ("stump", "gpu_stump")


def _gpu_name():
    try:
        import numba.cuda
        if numba.cuda.is_available():
            name = numba.cuda.list_devices()[0].name
            return name.decode() if isinstance(name, bytes) else str(name)
    except Exception:
        pass
    return None


def _calibration_key(backend):
    """Calibration is per (backend, cpu_count, gpu_name, stumpy_version) —
    any of those changing invalidates a prior calibration rather than
    silently reusing a stale constant."""
    return json.dumps({
        "backend": backend,
        "cpu_count": multiprocessing.cpu_count(),
        "gpu_name": _gpu_name() if backend == "gpu_stump" else None,
        "stumpy_version": str(getattr(stumpy, "__version__", "unknown")),
    }, sort_keys=True)


def _load_calibration():
    if not os.path.isfile(CALIBRATION_PATH):
        return {}
    with open(CALIBRATION_PATH, "r") as f:
        return json.load(f)


def _save_calibration(data):
    """Write the calibration file atomically.

    A plain `open(path, "w")` truncates first and writes second, so any reader
    that arrives between those two steps — another process, a background
    thread, or a test that shares the path — sees a partial file and fails
    with a `JSONDecodeError`. Writing to a sibling temp file and renaming it
    over the target makes the swap a single filesystem operation: a reader
    sees either the whole old file or the whole new one, never a fragment.

    `os.replace` is atomic on NTFS and POSIX alike, and unlike `os.rename` it
    overwrites an existing destination on Windows.
    """
    directory = os.path.dirname(CALIBRATION_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = CALIBRATION_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, CALIBRATION_PATH)


def calibrate(backend="stump", force=False, n0=CALIBRATION_N0, seed=0):
    """Time one `stump`/`gpu_stump` call on a synthetic `n0`-sample series
    and solve for `k` in `t_est(n) = k * n**2`, writing the result to
    `DATA/db/mp_calibration.json` keyed by the current machine/library
    signature (`_calibration_key`).

    Skips recalibration (returns the existing entry) unless `force=True`.
    Cheap — a few seconds at `n0=20_000` — so re-running whenever
    `cpu_count` or `stumpy_version` changes is not a burden.

    Sanity anchor (MATRIX_PROFILE_UI_PROMPT.md §3.1): ~300h at 1Hz
    (n ~= 1.08e6) exceeding 20 min implies `k_cpu` on the order of 1e-9 —
    a useful plausibility check on a fresh calibration, not a substitute
    for one.
    """
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}, got {backend!r}")

    key = _calibration_key(backend)
    data = _load_calibration()
    if not force and key in data:
        return data[key]

    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n0).astype(np.float64)
    m = max(4, n0 // 200)

    t0 = time.time()
    if backend == "gpu_stump":
        import numba.cuda
        device_ids = [d.id for d in numba.cuda.list_devices()]
        stumpy.gpu_stump(x, m=m, device_id=device_ids)
    else:
        stumpy.stump(x, m=m)
    elapsed = time.time() - t0

    entry = {
        "k": elapsed / (n0 ** 2),
        "n0": n0,
        "elapsed_s": elapsed,
        "calibrated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    data[key] = entry
    _save_calibration(data)
    return entry


def estimate_seconds(n, backend="stump"):
    """Estimated wall-clock seconds for an n-sample matrix profile on this
    machine, or `None` if this (backend, cpu_count, gpu_name,
    stumpy_version) combination has never been calibrated."""
    if backend not in BACKENDS:
        backend = "stump"
    entry = _load_calibration().get(_calibration_key(backend))
    if entry is None:
        return None
    return entry["k"] * (n ** 2)


def routing_tier(seconds):
    """'interactive' | 'background' | 'hpc' from an estimated-seconds
    value, or 'unknown' if `seconds` is None (uncalibrated)."""
    if seconds is None:
        return "unknown"
    if seconds <= MP_INTERACTIVE_BUDGET_S:
        return "interactive"
    if seconds <= MP_BACKGROUND_BUDGET_S:
        return "background"
    return "hpc"


def max_span_samples_for_background(backend="stump"):
    """The `n` at which `estimate_seconds(n, backend) == MP_BACKGROUND_BUDGET_S`
    — the span above which even a background run should be refused in
    favour of HPC export (MATRIX_PROFILE_UI_PROMPT.md §3.3). `None` if
    uncalibrated, meaning "no guard" (unbounded) rather than a guessed cap.
    """
    entry = _load_calibration().get(_calibration_key(backend))
    if entry is None or entry["k"] <= 0:
        return None
    return int((MP_BACKGROUND_BUDGET_S / entry["k"]) ** 0.5)
