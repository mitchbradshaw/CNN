"""
score_windows.py
================
Score every consecutive window of a recording with a trained fusion CNN and
persist the result as a WindowMatrix CSV.

Extracted verbatim (behaviour-preserving) from the `python - <<'PYEOF'`
heredoc that used to live inside HPC/Catalogue/score_job.sh, so the analysis
logic is version-controlled, importable and runnable off-cluster.

Pipeline
--------
  1. Load the raw signal                      (Working.Preprocessing)
  2. Build consecutive, non-overlapping windows (Working.Preprocessing)
  3. Add CNN P(interesting) per window         (Working.Catalogue)
  4. Write MATRICES/<recording>_<fs>_<win>min_<n>wins_consecutive.csv

Usage
-----
    python Pipelines/cnn_scoring/score_windows.py
    python Pipelines/cnn_scoring/score_windows.py --file M2_concat_fs1.mat \\
        --model MODELS/fusion_cnn_3.pth --timescale 10 --fs 1.0
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
import os

import numpy as np

from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Preprocessing.window_matrix.matrix_calc import create_matrix
from Working.Catalogue.cnn.apply_cnn import add_cnn_scores


def score_consecutive_windows(filename: str,
                              model_path: str,
                              timescale: float = 10,
                              fs: float = 1.0,
                              batch_size: int = 64,
                              out_dir: str = "MATRICES",
                              matname: str = "x") -> str:
    """
    Score every non-overlapping `timescale`-minute window of `filename` and
    save the resulting WindowMatrix to CSV.

    Returns the path the CSV was written to.
    """
    print("Loading signal...")
    x, _ = load_raw_data(filename, fs, matname)

    window_samples    = int(timescale * 60 * fs)
    n_windows         = len(x) // window_samples
    consecutive_starts = np.arange(n_windows) * window_samples

    print(f"Signal length : {len(x):,} samples")
    print(f"Window size   : {window_samples} samples ({timescale} min)")
    print(f"Windows       : {n_windows}")

    wm = create_matrix(consecutive_starts, x, timescale=timescale, fs=fs)
    add_cnn_scores(wm, model_path=model_path, batch_size=batch_size)

    stem = os.path.splitext(os.path.basename(filename))[0]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"{stem}_{timescale:g}min_{n_windows}wins_consecutive.csv"
    )
    wm.df.to_csv(out_path)
    print(f"Saved -> {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file",       default="M2_concat_fs1.mat",
                   help="Recording in DATA/raw/ or DATA/derived/ (default: M2_concat_fs1.mat)")
    p.add_argument("--model",      default="MODELS/fusion_cnn_3.pth")
    p.add_argument("--timescale",  type=float, default=10, help="Window length in minutes")
    p.add_argument("--fs",         type=float, default=1.0, help="Sample rate in Hz")
    p.add_argument("--batch_size", type=int,   default=64)
    p.add_argument("--out_dir",    default="MATRICES")
    p.add_argument("--matname",    default="x", help="Variable name inside a .mat file")
    args = p.parse_args()

    score_consecutive_windows(
        filename=args.file,
        model_path=args.model,
        timescale=args.timescale,
        fs=args.fs,
        batch_size=args.batch_size,
        out_dir=args.out_dir,
        matname=args.matname,
    )


if __name__ == "__main__":
    main()
