"""
run_matrix_profile.py
---------------------
Computes the matrix profile for one channel/window via stumpy (GPU
`gpu_stump` with a CPU `stump` fallback) and saves it in the v2 artifact
format described in MATRIX_PROFILE_UI_PROMPT.md §2.2.

Usage (called by mp_job.sh, or via `Pipelines/run_recipe/run_recipe.py` —
see MATRIX_PROFILE_UI_PROMPT.md §5 for why HPC jobs should go through
`run_recipe.py` rather than this file directly):
    python run_matrix_profile.py
"""

import datetime
import os
import time

import numpy as np
import stumpy

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
from Working.Preprocessing.manage_data.load_data import load_raw_data

# ── Config (used only by the __main__ demo driver below) ───────────────────
CH         = 2
FILE       = f"M2_concat_fs1_CH{CH}.npy"
FS         = 1.0          # Hz
WINDOW_MIN = 50            # minutes
OUT_DIR    = "Results/Detection/matrix_profile"


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Load data (demo driver only) ────────────────────────────────────────────
def load_matrix_data(FILE, FS, WINDOW_MIN):
    m = int(WINDOW_MIN * 60 * FS)
    print(f"Loading {FILE} ...")
    x, t = load_raw_data(FILE, FS)
    print(f"  n = {len(x):,} samples  |  m = {m} samples  |  duration = {len(x)/FS/3600:.2f} h")
    return x, t, m


# ── Compute matrix profile ────────────────────────────────────────────────────
def matrix_profile(x, t, m, backend="auto"):
    """Compute the matrix profile for window length `m`.

    Fixes MATRIX_PROFILE_UI_PROMPT.md §7 item 2: earlier versions of this
    function discarded `profile[:, 2:4]` (the left/right nearest-neighbour
    index columns), which made every saved artifact chain-incapable
    (`stumpy.allc` needs them — see `compute_chains` below). All four
    columns are kept here.

    Parameters
    ----------
    x, t : array
    m : int
        Window length in samples.
    backend : "auto" | "stump" | "gpu_stump"
        "auto" (default) tries `gpu_stump` and falls back to `stump` on any
        failure (no GPU, no numba.cuda, etc). "stump"/"gpu_stump" force
        that backend and let a failure raise, rather than silently falling
        back — a caller that explicitly asked for the GPU path wants to
        know if it didn't get it.

    Returns
    -------
    dict with keys: mp (float32), mpi (int32), left_i (int32), right_i
    (int32), t_mp (float32), backend (str, the backend actually used),
    elapsed_s (float).
    """
    if backend not in ("auto", "stump", "gpu_stump"):
        raise ValueError(f"backend must be one of auto/stump/gpu_stump, got {backend!r}")

    t0 = time.time()
    used = backend

    def _run_gpu():
        import numba.cuda
        if not numba.cuda.is_available():
            raise RuntimeError("no GPU")
        device_ids = [device.id for device in numba.cuda.list_devices()]
        return stumpy.gpu_stump(x, m=m, device_id=device_ids)

    if backend == "gpu_stump":
        profile = _run_gpu()
    elif backend == "stump":
        profile = stumpy.stump(x, m=m)
    else:  # auto
        try:
            profile = _run_gpu()
            used = "gpu_stump"
        except Exception:
            profile = stumpy.stump(x, m=m)
            used = "stump"

    elapsed = time.time() - t0

    mp = np.asarray(profile[:, 0], dtype=np.float32)
    mpi = np.asarray(profile[:, 1], dtype=np.int32)
    left_i = np.asarray(profile[:, 2], dtype=np.int32)
    right_i = np.asarray(profile[:, 3], dtype=np.int32)
    t_mp = np.asarray(t[:len(mp)], dtype=np.float32)

    return {
        "mp": mp, "mpi": mpi, "left_i": left_i, "right_i": right_i,
        "t_mp": t_mp, "backend": used, "elapsed_s": elapsed,
        "approx": False, "approx_percentage": 1.0,
    }


# ── Approximate / anytime profile (SCRIMP++) ────────────────────────────────
def matrix_profile_scrump(x, t, m, percentage=1.0, pre_scrump=True, on_progress=None):
    """Approximate (or, at `percentage=1.0`, exact) matrix profile via
    SCRIMP++ (`stumpy.scrump`) — an *anytime* algorithm: unlike `stump`,
    which is opaque until it returns, this yields progressive refinement,
    which is what makes a real progress bar possible
    (MATRIX_PROFILE_UI_PROMPT.md §3.2).

    `on_progress(fraction_done)` is called once after the internal
    `.update()` step. `approx=False` is only correct at `percentage=1.0`
    (SCRIMP++ converges to the exact profile there) — this function sets
    it accordingly; callers must not override it.
    """
    t0 = time.time()
    approx_mp = stumpy.scrump(x, m, percentage=percentage, pre_scrump=pre_scrump)
    approx_mp.update()
    if on_progress is not None:
        on_progress(percentage)
    elapsed = time.time() - t0

    mp = np.asarray(approx_mp.P_, dtype=np.float32)
    mpi = np.asarray(approx_mp.I_, dtype=np.int32)
    left_i = np.asarray(approx_mp.left_I_, dtype=np.int32)
    right_i = np.asarray(approx_mp.right_I_, dtype=np.int32)
    t_mp = np.asarray(t[:len(mp)], dtype=np.float32)

    return {
        "mp": mp, "mpi": mpi, "left_i": left_i, "right_i": right_i,
        "t_mp": t_mp, "backend": "scrump", "elapsed_s": elapsed,
        "approx": percentage < 1.0, "approx_percentage": percentage,
    }


# ── Time Series Chains ──────────────────────────────────────────────────────
def compute_chains(x, t, m, backend="auto"):
    """Time series chains via `stumpy.allc`, using the profile's left/right
    nearest-neighbour index columns.

    Fixes MATRIX_PROFILE_UI_PROMPT.md §7 item 1: the previous version
    unpacked `matrix_profile()`'s (already-broken) 4-tuple return into 3
    names — a `ValueError` — then called `stumpy.allc(mp.left_I_,
    mp.right_I_)` on what would have been a plain `float32` ndarray with
    no such attributes. `stumpy.allc` takes the left/right index columns
    directly, which is what `matrix_profile()` now returns.
    """
    result = matrix_profile(x, t, m, backend=backend)
    return stumpy.allc(result["left_i"], result["right_i"])


# ── Save (v2 format, MATRIX_PROFILE_UI_PROMPT.md §2.2) ─────────────────────
def build_mp_artifact_path(source_file, channel, window_min,
                            out_dir="Results/Detection/matrix_profile"):
    """`mp_v2_{source_stem}_CH{ch}_WIN{scale_min:g}min.npz` — see
    MATRIX_PROFILE_UI_PROMPT.md §2.2. `:g` formatting keeps an off-ladder
    float window (e.g. 4.704) readable without trailing zeros, while an
    integer-valued window (e.g. 10.0) prints as "10", not "10.0"."""
    stem = os.path.splitext(source_file)[0]
    filename = f"mp_v2_{stem}_CH{int(channel)}_WIN{window_min:g}min.npz"
    return os.path.join(out_dir, filename)


def save_matrix_profile(mp, mpi, left_i, right_i, m, fs, window_min, *,
                         source_file, channel, n_samples, data_sha1,
                         backend, recording_id=None, config_hash=None,
                         approx=False, approx_percentage=1.0,
                         elapsed_s=None, has_chain_indices=True,
                         out_dir="Results/Detection/matrix_profile"):
    """Save one matrix-profile artifact in the v2 format.

    Fixes MATRIX_PROFILE_UI_PROMPT.md §7 item 3: `m` is now a required
    parameter (the previous version referenced a bare `m`, which only
    happened to work under `if __name__ == "__main__":` where `m` was a
    module global — calling this from anywhere else raised `NameError`).

    Returns the path written to.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = build_mp_artifact_path(source_file, channel, window_min, out_dir)
    np.savez_compressed(
        out_path,
        mp=np.asarray(mp, dtype=np.float32),
        mpi=np.asarray(mpi, dtype=np.int32),
        left_i=np.asarray(left_i, dtype=np.int32),
        right_i=np.asarray(right_i, dtype=np.int32),
        m=np.int32(m),
        fs=np.float32(fs),
        window_min=np.float32(window_min),
        n_samples=np.int64(n_samples),
        source_file=str(source_file),
        channel=int(channel),
        recording_id=int(recording_id) if recording_id is not None else -1,
        data_sha1=str(data_sha1),
        config_hash=str(config_hash or ""),
        approx=bool(approx),
        approx_percentage=np.float32(approx_percentage),
        has_chain_indices=bool(has_chain_indices),
        backend=str(backend),
        stumpy_version=str(getattr(stumpy, "__version__", "unknown")),
        created_at=_now_iso(),
        elapsed_s=np.float32(elapsed_s) if elapsed_s is not None else np.float32(-1.0),
    )
    return out_path


if __name__ == "__main__":
    x, t, m = load_matrix_data(FILE, FS, WINDOW_MIN)
    result = matrix_profile(x, t, m)
    from Working.database.matrix_profile_store import compute_data_sha1
    npy_path = os.path.join("DATA", "derived", "channels", FILE)
    sha1 = compute_data_sha1(npy_path) if os.path.isfile(npy_path) else ""
    out_path = save_matrix_profile(
        result["mp"], result["mpi"], result["left_i"], result["right_i"],
        m, FS, WINDOW_MIN,
        source_file=FILE, channel=CH, n_samples=len(x), data_sha1=sha1,
        backend=result["backend"], elapsed_s=result["elapsed_s"],
        out_dir=OUT_DIR,
    )
    print(f"\nSaved -> {out_path}")
    print(f"  mp       shape: {result['mp'].shape}")
    print(f"  mpi      shape: {result['mpi'].shape}")
    print(f"  backend: {result['backend']}   elapsed: {result['elapsed_s']:.1f}s")
