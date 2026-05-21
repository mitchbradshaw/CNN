import os
import numpy as np
from manage_data.load_data import load_raw_data
from gramian.gramian_calc import plot_gramian_suite

from analysis.wavelet_analysis import (
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