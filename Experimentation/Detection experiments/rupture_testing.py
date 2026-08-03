
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
from Working.Detection.rupture.rupture_detect import detect_change_points, plot_change_points

FOLDER   = "DATA/RAW"
FILENAME = "M2_concat_fs1_CH2.npy"
FS       = 1.0   # Hz (matches folder name)

# ---------------------------------------------------------------------------
# Load — a short slice of a real recording, sliced only so this demo runs
# quickly. detect_change_points itself makes no window-length assumption and
# can be called on the full multi-hour signal directly — but note ruptures'
# pure-Python implementation is slow in absolute terms (see the `jump`
# parameter docs in rupture_detect.py); raise `jump` and/or pre-downsample
# before running this on a full multi-hour recording.
# ---------------------------------------------------------------------------
x, t = load_raw_data(FILENAME, FS)
x = x[:54000]   # 1.5 hours at fs=1.0
t = t[:54000]

# ---------------------------------------------------------------------------
# Stage 1: penalty sensitivity sweep (Pelt, l2 cost)
#
# There is no dataset-independent "correct" penalty — per the module
# docstring, check whether the number of change points is stable across an
# order-of-magnitude sweep before trusting a single run.
# ---------------------------------------------------------------------------
print("=" * 62)
print("  STAGE 1: Penalty sensitivity sweep (algo=pelt, model=l2)")
print("=" * 62)
for pen in (1, 10, 30, 100):
    result = detect_change_points(x, t, algo="pelt", cost_model="l2", penalty=pen)
    print(f"  pen={pen:>5}  ->  {result.n_bkps} change point(s)")

# ---------------------------------------------------------------------------
# Stage 2: visualise a chosen penalty
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2: Detection + visualisation at pen=30")
print("=" * 62)
result = detect_change_points(x, t, algo="pelt", cost_model="l2", penalty=30)
print(f"  Change-point sample indices: {result.bkps_idx.tolist()}")
print(f"  Change-point times (hours): {[round(bt / 3600, 3) for bt in result.bkps_t]}")

plot_change_points(x, t, result, style="both")

# ---------------------------------------------------------------------------
# Stage 3: alternative algorithm — Binseg with an exact breakpoint count.
# rbf's cost is dominated by an O(n^2) Gram-matrix computation, so this uses
# a shorter slice to keep the demo fast; the API is identical on longer data.
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 3: Binseg with n_bkps=4 (rbf cost, shorter slice)")
print("=" * 62)
x_short, t_short = x[:2000], t[:2000]
result_binseg = detect_change_points(x_short, t_short, algo="binseg", cost_model="rbf", n_bkps=4)
plot_change_points(x_short, t_short, result_binseg, style="shaded", title="Binseg (rbf), n_bkps=4")
