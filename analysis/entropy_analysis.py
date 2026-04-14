import numpy as np
import matplotlib.pyplot as plt


def plot_entropy_histograms(x, categories, window_samples):
    """
    For each entropy measure, plot a grouped bar chart comparing the average
    value across data categories (mean bar height, std dev error bars).

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
    entropy_measures = {
        "shannon":       lambda w: _shannon_entropy(w),
        "approximate":   lambda w: _approximate_entropy(w, m=2, r=0.2),
        "sample":        lambda w: _sample_entropy(w, m=2, r=0.2),
        "spectral":      lambda w: _spectral_entropy(w),
        "permutation":   lambda w: _permutation_entropy(w, order=3),
        "svd":           lambda w: _svd_entropy(w, order=3),
    }

    # Compute per-window entropy values for each category
    results = {measure: {} for measure in entropy_measures}

    for name, indices in categories.items():
        per_window = {measure: [] for measure in entropy_measures}
        for idx in indices:
            window = x[int(idx):int(idx) + window_samples]
            if len(window) < window_samples:
                continue
            for measure, fn in entropy_measures.items():
                try:
                    per_window[measure].append(fn(window))
                except Exception:
                    pass
        for measure in entropy_measures:
            results[measure][name] = np.array(per_window[measure])

    # One subplot per entropy measure
    n_measures = len(entropy_measures)
    ncols = 3
    nrows = int(np.ceil(n_measures / ncols))
    colors = ["steelblue", "tomato", "mediumseagreen", "darkorange", "mediumpurple"]
    cat_names = list(categories.keys())

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes = axes.flatten()

    bar_width = 0.6 / len(cat_names)
    offsets = np.linspace(-(len(cat_names) - 1) / 2, (len(cat_names) - 1) / 2, len(cat_names)) * bar_width

    for ax, measure in zip(axes, entropy_measures):
        for name, offset, color in zip(cat_names, offsets, colors):
            vals = results[measure][name]
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
        ax.set_title(measure + " entropy")
        ax.set_ylabel("bits / nats")
        ax.set_xticks([])
        ax.legend(fontsize=7)

    for ax in axes[n_measures:]:
        ax.set_visible(False)

    fig.suptitle("Entropy Measure Comparison by Category", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.show()


# ── Entropy implementations ───────────────────────────────────────────────────

def _shannon_entropy(w, n_bins=50):
    """Shannon entropy of the amplitude histogram (bits)."""
    w = np.asarray(w, dtype=float)
    w = w[np.isfinite(w)]   # drop NaN / inf before ranging
    if len(w) == 0:
        return np.nan
    counts, _ = np.histogram(w, bins=n_bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    return -np.sum(probs * np.log2(probs))


def _spectral_entropy(w):
    """Normalised Shannon entropy of the power spectrum (bits)."""
    power = np.abs(np.fft.rfft(w)) ** 2
    power = power[power > 0]
    probs = power / power.sum()
    return -np.sum(probs * np.log2(probs))


def _permutation_entropy(w, order=3):
    """
    Permutation entropy (Bandt & Pompe, 2002).
    Measures complexity via the distribution of ordinal patterns.
    """
    n = len(w)
    patterns = {}
    for i in range(n - order + 1):
        key = tuple(np.argsort(w[i:i + order]))
        patterns[key] = patterns.get(key, 0) + 1
    total = sum(patterns.values())
    probs = np.array(list(patterns.values())) / total
    return -np.sum(probs * np.log2(probs))


def _svd_entropy(w, order=3):
    """
    SVD entropy: entropy of the singular value spectrum of the
    embedded trajectory matrix.
    """
    w = np.asarray(w, dtype=float)
    if np.any(np.isnan(w)):
        return np.nan
    n = len(w)
    if n < order:
        return np.nan
    # Build trajectory (Hankel) matrix
    m = n - order + 1
    mat = np.array([w[i:i + order] for i in range(m)])
    sv = np.linalg.svd(mat, compute_uv=False)
    sv = sv[sv > 0]
    probs = sv / sv.sum()
    return -np.sum(probs * np.log2(probs))


def _approximate_entropy(w, m=2, r=0.2):
    """
    Approximate Entropy (ApEn). r is given as a fraction of the signal std.
    Quantifies regularity — lower = more regular.
    """
    r_abs = r * np.std(w)
    n = len(w)

    def phi(m_):
        count = 0
        templates = np.array([w[i:i + m_] for i in range(n - m_ + 1)])
        for tmpl in templates:
            count += np.sum(np.max(np.abs(templates - tmpl), axis=1) <= r_abs)
        return np.log(count / (n - m_ + 1)) if count > 0 else 0.0

    return phi(m) - phi(m + 1)


def _sample_entropy(w, m=2, r=0.2):
    """
    Sample Entropy (SampEn). Like ApEn but excludes self-matches and is
    less biased on short signals.
    """
    r_abs = r * np.std(w)
    n = len(w)

    def count_matches(m_):
        templates = np.array([w[i:i + m_] for i in range(n - m_)])
        total = 0
        for i, tmpl in enumerate(templates):
            dists = np.max(np.abs(templates - tmpl), axis=1)
            dists[i] = np.inf  # exclude self
            total += np.sum(dists <= r_abs)
        return total

    A = count_matches(m + 1)
    B = count_matches(m)
    if B == 0 or A == 0:
        return np.nan
    return -np.log(A / B)
