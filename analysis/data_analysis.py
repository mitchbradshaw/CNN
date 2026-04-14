import numpy as np
import scipy.io
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