"""
wm_testing.py
=============
HPC-ready window-matrix builder with checkpoint / resume support.

Computes on M2_concat_fs1_CH{CH}.npy (250+ hours at 1 Hz):
  Stage 1  — 22 Catch22 summary statistics
  Stage 2  — 4 fast entropy measures (Shannon, SVD, spectral, permutation)
  Stage 3  — 2 slow entropy measures (sample, approximate)  [O(n²) per window]
  Stage 4  — CNN confidence scores for all 4 gramian image types
  Stage 5  — Random-forest class probabilities (optional)

Checkpoint / resume
-------------------
Progress is flushed to MATRICES/<CSVFILE> after every BATCH_SIZE windows.
If elapsed time exceeds TIMEOUT_MIN the script saves and exits cleanly so a
subsequent HPC job can resume by running the same command again — any column
with no NaN values is considered done and will be skipped automatically.

Usage
-----
  python wm_testing.py                       # first run or resume from checkpoint
  python wm_testing.py --reset               # delete checkpoint and start fresh
  python wm_testing.py --status              # print completion report and exit
  python wm_testing.py --timeout 90          # override timeout (minutes)
  python wm_testing.py --no-cnn              # skip all CNN stages
  python wm_testing.py --no-slow-entropy     # skip sample / approximate entropy
"""

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


import argparse
import logging
import os
import sys
import time

import numpy as np

from Working.Preprocessing.window_matrix.matrix_calc import WindowMatrix, create_matrix_at_timescale, load_matrix
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Detection.analysis.entropy_analysis import (
    _shannon_entropy,
    _svd_entropy,
    _sample_entropy,
    _spectral_entropy,
    _permutation_entropy,
    _approximate_entropy,
)
from Working.Detection.aeon_features.transformations import catch22_features, CATCH22_FEATURE_NAMES

# ===========================================================================
# Config — edit these to match your dataset and HPC environment
# ===========================================================================

CH       = 2
FILENAME = f"M2_concat_fs1_CH{CH}.npy"   # must be in DATA/RAW/
WINSIZE  = 10     # window length in minutes
FS       = 1.0    # sample rate (Hz)
STEPFRAC = 1.0    # 1.0 = non-overlapping windows; 0.5 = 50 % overlap

CSVFILE  = f"M2_concat_fs1_CH{CH}_WIN{WINSIZE}min_STEP{int(STEPFRAC * 100)}pct.csv"

# Stop computing and save if this many minutes have elapsed.
# Set a few minutes below your HPC job time-limit to leave cleanup headroom.
TIMEOUT_MIN = 19

# Windows processed between each CSV save (larger = fewer I/O writes but
# more re-work if the job is killed mid-batch)
BATCH_SIZE     = 50
CNN_BATCH_SIZE = 32   # windows per GPU forward pass

# CNN model paths — set any entry to None to skip that image type
CNN_MODELS = {
    "fusion":     "models/fusion_cnn.pth",
    "GASF":       "models/GASF_cnn.pth",
    "GADF":       "models/GADF_cnn.pth",
    "recurrence": "models/recurrence_cnn.pth",
}

# Path to a saved Random-Forest joblib pipeline, or None to skip
RF_MODEL_PATH: str | None = None   # e.g. "models/rf_pipeline.joblib"

# ===========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("wm_builder")

CSV_PATH = os.path.join("MATRICES", CSVFILE)


# ---------------------------------------------------------------------------
# Timeout manager
# ---------------------------------------------------------------------------

class TimeoutManager:
    def __init__(self, timeout_minutes: float):
        self._start    = time.time()
        self._deadline = self._start + timeout_minutes * 60

    def elapsed_min(self) -> float:
        return (time.time() - self._start) / 60

    def remaining_min(self) -> float:
        return max(0.0, (self._deadline - time.time()) / 60)

    def is_expired(self) -> bool:
        return time.time() >= self._deadline


# ---------------------------------------------------------------------------
# Load or create window matrix
# ---------------------------------------------------------------------------

def load_or_create_wm() -> WindowMatrix:
    log.info("Loading signal: %s", FILENAME)
    x, _ = load_raw_data(FILENAME, FS)
    n_hours = len(x) / FS / 3600
    log.info("  %d samples  |  %.1f h  |  fs=%.1f Hz", len(x), n_hours, FS)

    if os.path.exists(CSV_PATH):
        log.info("Checkpoint found: %s", CSV_PATH)
        wm = load_matrix(CSV_PATH, x, WINSIZE, FS)
    else:
        log.info("No checkpoint — creating fresh window matrix")
        wm = create_matrix_at_timescale(STEPFRAC, x, WINSIZE, FS)
        wm.save_window(CSVFILE)

    log.info("  %d windows  |  %d columns already present", len(wm), len(wm.columns))
    return wm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pending(wm: WindowMatrix, first_col: str) -> list[int]:
    """Windows that still need computing (NaN in first_col, or col absent)."""
    if first_col not in wm.df.columns:
        return list(wm.df.index)
    return wm.df.index[wm.df[first_col].isna()].tolist()


def _is_complete(wm: WindowMatrix, col_names: list[str]) -> bool:
    return (
        all(c in wm.df.columns for c in col_names)
        and not wm.df[col_names].isna().any().any()
    )


def _ensure_cols(wm: WindowMatrix, col_names: list[str]) -> None:
    for c in col_names:
        if c not in wm.df.columns:
            wm.df[c] = np.nan


# ---------------------------------------------------------------------------
# Generic incremental computation (scalar or fixed-length vector)
# ---------------------------------------------------------------------------

def compute_incremental(
    wm:         WindowMatrix,
    stage_name: str,
    col_names:  list[str],
    fn,                         # fn(signal_1d) → scalar  or  ndarray aligned with col_names
    timeout:    TimeoutManager,
) -> bool:
    """
    Compute missing values window-by-window, saving a checkpoint after every
    BATCH_SIZE windows.

    Returns True if the stage is fully complete, False if timeout stopped it.
    """
    _ensure_cols(wm, col_names)
    todo = _pending(wm, col_names[0])

    if not todo:
        log.info("[%s] complete — skipping", stage_name)
        return True

    scalar   = len(col_names) == 1
    n_total  = len(wm.df)
    n_before = n_total - len(todo)
    log.info("[%s] %d / %d windows pending", stage_name, len(todo), n_total)

    for batch_start in range(0, len(todo), BATCH_SIZE):
        if timeout.is_expired():
            wm.save_window(CSVFILE)
            log.warning(
                "[%s] TIMEOUT — saved checkpoint (%d / %d done)  exiting",
                stage_name, n_before + batch_start, n_total,
            )
            return False

        batch = todo[batch_start : batch_start + BATCH_SIZE]
        for idx in batch:
            sig = wm.get_window_signal(idx)
            try:
                out = fn(sig)
            except Exception as exc:
                log.warning("[%s] window %d raised %s — storing NaN", stage_name, idx, exc)
                out = np.nan if scalar else [np.nan] * len(col_names)

            if scalar:
                wm.df.at[idx, col_names[0]] = float(out)
            else:
                arr = np.asarray(out, dtype=float)
                for col, val in zip(col_names, arr):
                    wm.df.at[idx, col] = float(val)

        wm.save_window(CSVFILE)
        n_done = n_before + min(batch_start + BATCH_SIZE, len(todo))
        log.info(
            "[%s] %d / %d  |  %.1f min elapsed  |  %.1f min left",
            stage_name, n_done, n_total,
            timeout.elapsed_min(), timeout.remaining_min(),
        )

    return True


# ---------------------------------------------------------------------------
# CNN incremental (GPU-batched gramian image inference)
# ---------------------------------------------------------------------------

def compute_cnn_incremental(
    wm:         WindowMatrix,
    image_type: str,
    model_path: str,
    timeout:    TimeoutManager,
) -> bool:
    """
    Batch CNN inference for one gramian image type with checkpointing.
    Returns True if complete, False if timeout.
    """
    import torch
    import torch.nn.functional as F
    from Working.Catalogue.cnn.apply_cnn import load_model, window_to_tensor
    from Working.Catalogue.cnn.cnn_rangapur import get_transforms

    col_int  = f"cnn_p_{image_type}_interesting"
    col_nint = f"cnn_p_{image_type}_notinteresting"
    stage    = f"CNN:{image_type}"

    if not os.path.isfile(model_path):
        log.warning("[%s] model not found at '%s' — skipping", stage, model_path)
        return True

    _ensure_cols(wm, [col_int, col_nint])
    todo = _pending(wm, col_int)

    if not todo:
        log.info("[%s] complete — skipping", stage)
        return True

    device    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model     = load_model(model_path, device)
    transform = get_transforms(224, is_train=False, is_rgb=(image_type == "fusion"))

    x              = wm._x
    window_samples = wm._window_samples
    n_total        = len(wm.df)
    n_before       = n_total - len(todo)
    log.info("[%s] device=%s  %d / %d windows pending", stage, device, len(todo), n_total)

    for batch_start in range(0, len(todo), CNN_BATCH_SIZE):
        if timeout.is_expired():
            wm.save_window(CSVFILE)
            log.warning("[%s] TIMEOUT — saved checkpoint  exiting", stage)
            return False

        batch = todo[batch_start : batch_start + CNN_BATCH_SIZE]
        tensors: list = []
        valid:   list = []
        for idx in batch:
            try:
                t = window_to_tensor(x, idx, window_samples, transform, image_type)
                tensors.append(t)
                valid.append(idx)
            except Exception as exc:
                log.warning("[%s] image gen failed at window %d: %s", stage, idx, exc)

        if tensors:
            with torch.no_grad():
                batch_t = torch.cat(tensors, dim=0).to(device)
                probs   = F.softmax(model(batch_t), dim=1).cpu().numpy()
            for idx, row in zip(valid, probs):
                wm.df.at[idx, col_int]  = float(row[0])
                wm.df.at[idx, col_nint] = float(row[1])

        wm.save_window(CSVFILE)
        n_done = n_before + min(batch_start + CNN_BATCH_SIZE, len(todo))
        log.info(
            "[%s] %d / %d  |  %.1f min elapsed  |  %.1f min left",
            stage, n_done, n_total,
            timeout.elapsed_min(), timeout.remaining_min(),
        )

    return True


# ---------------------------------------------------------------------------
# Random-forest incremental
# ---------------------------------------------------------------------------

def compute_rf_incremental(
    wm:         WindowMatrix,
    model_path: str,
    timeout:    TimeoutManager,
) -> bool:
    """
    sklearn/joblib pipeline inference with checkpointing.
    Returns True if complete, False if timeout.
    """
    import joblib
    from Working.Catalogue.aeon_classification.classification import ThresholdedPipeline
    sys.modules["__main__"].ThresholdedPipeline = ThresholdedPipeline  # type: ignore[attr-defined]

    stage    = "RF"
    col_int  = "rf_p_interesting"
    col_nint = "rf_p_notinteresting"

    if not os.path.isfile(model_path):
        log.warning("[%s] model not found at '%s' — skipping", stage, model_path)
        return True

    _ensure_cols(wm, [col_int, col_nint])
    todo = _pending(wm, col_int)

    if not todo:
        log.info("[%s] complete — skipping", stage)
        return True

    model   = joblib.load(model_path)
    win_len = wm._window_samples
    n_total = len(wm.df)
    n_before = n_total - len(todo)
    log.info("[%s] %d / %d windows pending", stage, len(todo), n_total)

    for batch_start in range(0, len(todo), BATCH_SIZE):
        if timeout.is_expired():
            wm.save_window(CSVFILE)
            log.warning("[%s] TIMEOUT — saved checkpoint  exiting", stage)
            return False

        batch = todo[batch_start : batch_start + BATCH_SIZE]
        sigs:  list = []
        valid: list = []
        for idx in batch:
            sig = wm.get_window_signal(idx)
            if len(sig) < win_len:
                continue
            sigs.append(sig.reshape(1, -1))
            valid.append(idx)

        if sigs:
            X      = np.stack(sigs).astype(np.float32)   # (B, 1, win_len)
            probas = model.predict_proba(X)               # (B, 2): col0=not-int, col1=int
            for idx, row in zip(valid, probas):
                wm.df.at[idx, col_int]  = float(row[1])
                wm.df.at[idx, col_nint] = float(row[0])

        wm.save_window(CSVFILE)
        n_done = n_before + min(batch_start + BATCH_SIZE, len(todo))
        log.info(
            "[%s] %d / %d  |  %.1f min elapsed  |  %.1f min left",
            stage, n_done, n_total,
            timeout.elapsed_min(), timeout.remaining_min(),
        )

    return True


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(wm: WindowMatrix) -> None:
    catch22_cols  = [f"catch22_{n}" for n in CATCH22_FEATURE_NAMES]
    fast_entropy  = [
        "shannon entropy", "svd entropy",
        "spectral entropy", "permutation entropy",
    ]
    slow_entropy  = ["sample entropy", "approximate entropy"]
    cnn_col_groups = {
        img: [f"cnn_p_{img}_interesting", f"cnn_p_{img}_notinteresting"]
        for img in CNN_MODELS
    }
    rf_cols = ["rf_p_interesting", "rf_p_notinteresting"]

    def _status(cols: list[str]) -> str:
        if not all(c in wm.df.columns for c in cols):
            return "not started"
        pending = wm.df[cols].isna().any(axis=1).sum()
        if pending == 0:
            return "DONE"
        return f"{len(wm.df) - pending} / {len(wm.df)}"

    print("\n" + "=" * 56)
    print("  Window Matrix Status")
    print("=" * 56)
    print(f"  File      : {CSV_PATH}")
    print(f"  Windows   : {len(wm)}")
    print(f"  Columns   : {len(wm.columns)}")
    print(f"  Catch22   : {_status(catch22_cols)}")
    print(f"  Entropy   : {_status(fast_entropy)}  (fast)")
    print(f"  Entropy   : {_status(slow_entropy)}  (slow — sample + approx)")
    for img, cols in cnn_col_groups.items():
        print(f"  CNN {img:>12s}: {_status(cols)}")
    print(f"  RF probs  : {_status(rf_cols)}")
    print("=" * 56 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="HPC window-matrix builder with checkpoint / resume",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--reset", action="store_true",
        help="Delete the existing checkpoint CSV and start fresh",
    )
    p.add_argument(
        "--status", action="store_true",
        help="Print completion status and exit without computing",
    )
    p.add_argument(
        "--timeout", type=float, default=TIMEOUT_MIN,
        metavar="MIN",
        help=f"Timeout in minutes (default {TIMEOUT_MIN})",
    )
    p.add_argument(
        "--no-cnn", action="store_true",
        help="Skip all CNN inference stages",
    )
    p.add_argument(
        "--no-slow-entropy", action="store_true",
        help="Skip sample entropy and approximate entropy (O(n²) per window)",
    )
    p.add_argument(
        "--no-rf", action="store_true",
        help="Skip the random-forest stage",
    )
    args = p.parse_args()

    if args.reset and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        log.info("Checkpoint removed: %s", CSV_PATH)

    wm = load_or_create_wm()

    if args.status:
        print_status(wm)
        return

    timeout = TimeoutManager(args.timeout)
    log.info("Timeout: %.1f minutes", args.timeout)

    # ── Stage 1: Catch22 (22-element vector, ~0.1 s/window) ─────────────────
    catch22_cols = [f"catch22_{n}" for n in CATCH22_FEATURE_NAMES]
    if not compute_incremental(wm, "Catch22", catch22_cols, catch22_features, timeout):
        sys.exit(0)

    # ── Stage 2: Fast entropy measures (~0.01–0.05 s/window each) ───────────
    fast_entropy_stages = [
        ("shannon entropy",     _shannon_entropy),
        ("spectral entropy",    _spectral_entropy),
        ("svd entropy",         _svd_entropy),
        ("permutation entropy", _permutation_entropy),
    ]
    for col, fn in fast_entropy_stages:
        if not compute_incremental(wm, col, [col], fn, timeout):
            sys.exit(0)

    # ── Stage 3: Slow entropy measures (O(n²) per window, ~0.5–5 s/window) ──
    if not args.no_slow_entropy:
        slow_entropy_stages = [
            ("sample entropy",      _sample_entropy),
            ("approximate entropy", _approximate_entropy),
        ]
        for col, fn in slow_entropy_stages:
            if not compute_incremental(wm, col, [col], fn, timeout):
                sys.exit(0)
    else:
        log.info("Skipping slow entropy stages (--no-slow-entropy)")

    # ── Stage 4: CNN confidence scores (4 image types) ──────────────────────
    if not args.no_cnn:
        for image_type, model_path in CNN_MODELS.items():
            if model_path is None:
                continue
            if not compute_cnn_incremental(wm, image_type, model_path, timeout):
                sys.exit(0)
    else:
        log.info("Skipping CNN stages (--no-cnn)")

    # ── Stage 5: Random-forest probabilities ────────────────────────────────
    if not args.no_rf and RF_MODEL_PATH is not None:
        if not compute_rf_incremental(wm, RF_MODEL_PATH, timeout):
            sys.exit(0)

    log.info("All stages complete!")
    print_status(wm)


if __name__ == "__main__":
    main()
