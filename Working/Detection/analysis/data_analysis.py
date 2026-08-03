import numpy as np
import scipy.io
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import find_peaks, peak_prominences, peak_widths
import glob
import os
import re
import json
import random
import matplotlib.pyplot as plt


def plot_feature_histograms(x, categories, window_samples):
    """
    For each statistical feature, plot a grouped bar chart comparing the
    distribution of that feature across data categories.

    One subplot per feature. Each bar is the average value of that feature
    across all windows in the category, with error bars showing std dev.

    Parameters
    ----------
    x : np.ndarray
        Raw time-series signal.
    categories : dict[str, np.ndarray]
        Mapping of category name -> array of start sample indices.
        e.g. {"interesting": interesting, "notinteresting": notinteresting}
    window_samples : int
        Number of samples per window.
    """
    features = {
        "mean":     lambda w: np.mean(w),
        "std":      lambda w: np.std(w),
        "median":   lambda w: np.median(w),
        "max":      lambda w: np.max(w),
        "min":      lambda w: np.min(w),
        "range":    lambda w: np.max(w) - np.min(w),
        "rms":      lambda w: np.sqrt(np.mean(w ** 2)),
        "skewness": lambda w: _skewness(w),
        "kurtosis": lambda w: _kurtosis(w),
    }

    # Compute per-window feature values for each category
    # results[feature][category] = list of per-window values
    results = {feat: {} for feat in features}

    for name, indices in categories.items():
        per_window = {feat: [] for feat in features}
        for idx in indices:
            window = x[int(idx):int(idx) + window_samples]
            if len(window) < window_samples:
                continue
            for feat, fn in features.items():
                per_window[feat].append(fn(window))
        for feat in features:
            results[feat][name] = np.array(per_window[feat])

    # One subplot per feature
    n_features = len(features)
    ncols = 3
    nrows = int(np.ceil(n_features / ncols))
    colors = ["steelblue", "tomato", "mediumseagreen", "darkorange", "mediumpurple"]
    cat_names = list(categories.keys())

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes = axes.flatten()

    bar_width = 0.6 / len(cat_names)
    offsets = np.linspace(-(len(cat_names) - 1) / 2, (len(cat_names) - 1) / 2, len(cat_names)) * bar_width

    for ax, (feat, _) in zip(axes, features.items()):
        for name, offset, color in zip(cat_names, offsets, colors):
            vals = results[feat][name]
            if len(vals) == 0:
                continue
            ax.bar(
                offset,
                np.mean(vals),
                width=bar_width,
                yerr=np.std(vals),
                label=f"{name} (n={len(vals)})",
                color=color,
                alpha=0.8,
                capsize=4,
                error_kw={"elinewidth": 1.2},
            )
        ax.set_title(feat)
        ax.set_ylabel("value")
        ax.set_xticks([])
        ax.legend(fontsize=7)

    # Hide any unused subplots
    for ax in axes[n_features:]:
        ax.set_visible(False)

    fig.suptitle("Statistical Feature Comparison by Category", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.show()


def _skewness(w):
    mu, sigma = np.mean(w), np.std(w)
    if sigma == 0:
        return 0.0
    return np.mean(((w - mu) / sigma) ** 3)


def _kurtosis(w):
    mu, sigma = np.mean(w), np.std(w)
    if sigma == 0:
        return 0.0
    return np.mean(((w - mu) / sigma) ** 4) - 3  # excess kurtosis

# ── Per-window signal operations ──────────────────────────────────────────────
# All plain functions (normalise, half_width) can be passed directly to
# add_computed_column.  Parameterised operations are factory functions that
# return the callable, e.g.:
#   wm.add_computed_column("detrended", make_detrend(j=10))

def normalise(w):
    """
    Global normalisation: subtract the window's median from every sample.
    normalise(p_i) = p_i - median(window)
    """
    return w.astype(float) - np.median(w)

# kept as alias for backward compatibility
median_normalise = normalise


def make_detrend(j):
    """
    Factory: returns fn(w) that removes local trend via rolling-median subtraction.
    detrend(p_i, j) = p_i - median(p_{i-j} … p_{i+j})

    Removes low-frequency variation; reveals features shorter than 2j+1 samples.
    """
    size = 2 * j + 1
    def _detrend(w):
        trend = median_filter(w.astype(float), size=size, mode="nearest")
        return w.astype(float) - trend
    return _detrend


def make_smooth(j):
    """
    Factory: returns fn(w) that smooths via rolling median.
    smooth(p_i, j) = median(p_{i-j} … p_{i+j})

    Removes high-frequency variation; reveals features longer than 2j+1 samples.
    """
    size = 2 * j + 1
    def _smooth(w):
        return median_filter(w.astype(float), size=size, mode="nearest")
    return _smooth


def make_denoise(i=1):
    """
    Factory: returns fn(w) that denoises via short rolling mean.
    denoise(p_i, i) = mean(p_{i-i} … p_{i+i})

    Uses mean over a very short window (default i=1 → 3 points).
    Note: slightly distorts sharp edges compared to median smoothing.
    """
    size = 2 * i + 1
    def _denoise(w):
        return uniform_filter1d(w.astype(float), size=size, mode="nearest")
    return _denoise


def make_filter(j, k=None):
    """
    Factory: returns fn(w) = detrend(smooth(w, j), k).
    Default k = 2*j.

    Equivalent to a time-domain band-pass: smooth removes high-frequency noise,
    detrend removes the low-frequency trend left behind.

    Examples
    --------
    make_filter(1, 2)    # finds narrow spikes
    make_filter(100, 500)  # finds long slow changes
    """
    if k is None:
        k = 2 * j
    _s = make_smooth(j)
    _d = make_detrend(k)
    def _filter(w):
        return _d(_s(w))
    return _filter


def half_width(w):
    """
    Half-width of the most prominent peak, measured at half-prominence on the
    steeper (faster-changing) side.  Returns NaN if no peak is found.

    Uses scipy.signal peak detection with prominence ranking.
    """
    peaks, _ = find_peaks(w)
    if len(peaks) == 0:
        return np.nan
    prom = peak_prominences(w, peaks)[0]
    dominant = peaks[np.argmax(prom)]
    _, _, left_ips, right_ips = peak_widths(w, [dominant], rel_height=0.5)
    left_hw  = float(dominant - left_ips[0])
    right_hw = float(right_ips[0] - dominant)
    return min(left_hw, right_hw)

