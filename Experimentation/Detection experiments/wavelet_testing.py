
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

import os
import numpy as np
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Catalogue.gramian.gramian_calc import plot_gramian_suite

from Working.Detection.analysis.wavelet_analysis import (
    load_signal,
    compute_scalogram,
    detect_high_energy_regions,
    cluster_peaks,
    cluster_peaks_poly,
    plot_wavelet_activity_overview,
)

# 328001.npy -- good window for spike detection testing

FOLDER   = "DATA/RAW"
FILENAME = "M2_concat_fs1_CH2.npy"
FS       = 1.0   # Hz (matches folder name)

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
x, t = load_raw_data(FILENAME,FS,"VECTOR")

# ---------------------------------------------------------------------------
# Wavelet activity overview
# ---------------------------------------------------------------------------
g, g_sum, scales, freqs = compute_scalogram(x, fs=FS)

regions, peaks, threshold = detect_high_energy_regions(
    g_sum,
    method="percentile",
    pct=80,
)

clusters, poly_vals = cluster_peaks_poly(
    g_sum, t,
    degree=10,
    threshold_method="percentile",
    pct=80,
)

plot_wavelet_activity_overview(
    x, t, g, g_sum, freqs,
    regions=regions,
    peaks=peaks,
    cluster_regions=clusters,
    poly_values=poly_vals,
    threshold=threshold,
    show_regions=False,
    show_peaks=False,
    fs=FS,
    title=f"Wavelet Activity — {FILENAME}",
    dark=False,
)