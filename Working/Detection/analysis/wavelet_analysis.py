"""
analysis/wavelet_analysis.py
-----------------------------
Presentation-quality visual analysis of Morse-wavelet energy patterns
in electrophysiological time-series.

Reuses the Morse-wavelet transform and normalisation from
dehshibi_detection_analysis.py without duplicating any wavelet mathematics.

WHAT THE SCALOGRAM PHYSICALLY REPRESENTS
-----------------------------------------
The Continuous Wavelet Transform (CWT) slides a scaled, shifted copy of the
Morse mother wavelet across the signal and measures how well the two match
at each (time, scale) pair.  Because the Morse wavelet is optimally
concentrated in both time and frequency (Lilly & Olhede 2008), the resulting
scalogram g[k, τ] is a clean time–frequency energy map:
  - A bright *horizontal band* at frequency f_k means the signal contains a
    sustained oscillation at that frequency.
  - A bright *vertical stripe* at time τ means the signal briefly contains
    energy across many frequencies simultaneously — the hallmark of a
    transient event such as a spike or burst.

WHY SUMMING NORMALISED COLUMNS REVEALS TRANSIENTS
---------------------------------------------------
Per-scale normalisation (Eq. 3 of Dehshibi & Adamatzky 2021) divides each
frequency band by its own maximum, so no single dominant frequency swamps
the sum.  Summing normalised energy across all scales then produces a scalar
profile Ω(τ) that peaks wherever the signal has broad-spectrum, transient
character — exactly where spikes or bursts occur.  Background activity and
slow drifts produce low, flat Ω because their energy is confined to a few
frequency bands and not boosted by the per-scale normalisation.

LIMITATIONS FOR NOISY BIOLOGICAL SIGNALS
-----------------------------------------
1. Electrode artefacts (movement, contact changes) create large broad-
   spectrum bursts that mimic spikes in Ω.  Visual inspection of each
   flagged segment in the raw signal panel is essential.
2. The default 64-scale grid covers 0.001–0.4 Hz (periods 2.5 s–1000 s)
   which targets fungal spike durations.  Adjust f_lo / f_hi for other
   organisms or sampling rates.
3. L1 normalisation (φ/s) is amplitude-sensitive: large baseline drifts
   can dominate the scalogram even after per-scale normalisation.
   Consider high-pass filtering before analysis if drift is severe.
4. Ω is not a probability; only *relative* changes (peak vs. baseline)
   are meaningful.  Its absolute value depends on η and the number of scales.

WAVELET DETECTION VS AMPLITUDE THRESHOLDING
--------------------------------------------
Simple amplitude thresholding (x > V_th) captures only the *peak* of an
event and is highly sensitive to DC drift.  Wavelet energy integrates over
the *shape and duration* of transient events, making it robust to slow
baselines and capable of detecting events that are small in amplitude but
morphologically distinct from background noise.  The trade-off is higher
computational cost and a less direct link to physical units.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple, Union

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks, savgol_filter
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker

# ---------------------------------------------------------------------------
# Reuse existing Morse-wavelet machinery — no duplication
# ---------------------------------------------------------------------------
try:
    from .dehshibi_detection_analysis import (
        BETA, ETA, GAMMA,
        _morse_peak_frequency,
        compute_morse_wavelet_transform,
        normalise_wavelet_coefficients,
    )
except ImportError:
    from Working.Detection.analysis.dehshibi_detection_analysis import (
        BETA, ETA, GAMMA,
        _morse_peak_frequency,
        compute_morse_wavelet_transform,
        normalise_wavelet_coefficients,
    )


# ===========================================================================
# 1. Signal loading
# ===========================================================================

def load_signal(
    source: Union[str, np.ndarray],
    fs: float = 1.0,
    scale_to_mv: bool = True,
    matname: str = "x",
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Load a signal from a file path or accept a raw array.

    Understands the two-row .npy format used by the 10-minute window files:
        data[0] = signal in volts, data[1] = absolute sample indices.

    Parameters
    ----------
    source : str or np.ndarray
        Path to a .npy or .mat file, or a pre-loaded 1-D signal array.
        Pre-loaded arrays are returned as-is (no unit conversion).
    fs : float
        Sampling frequency in Hz.
    scale_to_mv : bool
        When loading from a file, multiply signal by 1000 (V → mV).
        Ignored when source is already an array.
    matname : str
        Variable name inside .mat files.

    Returns
    -------
    x  : 1-D float array, signal values.
    t  : 1-D float array, time in seconds relative to window start.
    fs : float, sampling frequency (echoed back for convenience).
    """
    if isinstance(source, np.ndarray):
        x = source.ravel().astype(float)
        t = np.arange(len(x)) / fs
        return x, t, fs

    ext = os.path.splitext(source)[1].lower()

    if ext == ".npy":
        data = np.load(source)
        if data.ndim == 2 and data.shape[0] == 2:
            x_raw = data[0].astype(float)
            t     = (data[1] - data[1][0]) / fs
        elif data.ndim == 1:
            x_raw = data.astype(float)
            t     = np.arange(len(x_raw)) / fs
        else:
            raise ValueError(
                f"Unsupported .npy shape {data.shape}. Expected (2, N) or (N,)."
            )
        x = x_raw * 1000.0 if scale_to_mv else x_raw

    elif ext == ".mat":
        import scipy.io
        mat   = scipy.io.loadmat(source)
        x_raw = mat[matname].ravel().astype(float)
        x     = x_raw * 1000.0 if scale_to_mv else x_raw
        t     = np.arange(len(x)) / fs

    else:
        raise ValueError(
            f"Unsupported extension '{ext}'. Use .npy or .mat."
        )

    return x, t, fs


# ===========================================================================
# 2. Scalogram computation
# ===========================================================================

def compute_scalogram(
    signal: np.ndarray,
    fs: float = 1.0,
    scales: Optional[np.ndarray] = None,
    beta: float = BETA,
    gamma: float = GAMMA,
    eta: float = ETA,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute the normalised Morse-wavelet scalogram and column-sum energy profile.

    Delegates entirely to the existing pipeline in dehshibi_detection_analysis.py.

    Parameters
    ----------
    signal : 1-D array, signal values (any units).
    fs     : sampling frequency in Hz.
    scales : CWT scale array.  Auto-computed to cover 0.001–0.4 Hz if None.
    beta, gamma : Morse wavelet shape parameters (paper defaults: 20, 3).
    eta    : Eq. 3 normalisation scaling constant (paper default: 240).

    Returns
    -------
    g      : (n_scales × N) normalised scalogram.
             Values lie in [1, eta] after per-scale normalisation.
    g_sum  : (N,) Ω(τ) — column sum of g; high at transient events.
    scales : (n_scales,) CWT scale values used.
    freqs  : (n_scales,) corresponding physical frequencies in Hz.
             freqs[k] = ω₀ · fs / (2π · scales[k])
    """
    phi, used_scales = compute_morse_wavelet_transform(
        signal, scales=scales, beta=beta, gamma=gamma, fs=fs
    )
    g, g_sum = normalise_wavelet_coefficients(phi, eta=eta)

    omega_0 = _morse_peak_frequency(beta, gamma)
    freqs   = omega_0 * fs / (2.0 * np.pi * used_scales)

    return g, g_sum, used_scales, freqs


# ===========================================================================
# 3. High-energy region detection
# ===========================================================================

def detect_high_energy_regions(
    g_sum: np.ndarray,
    method: str = "percentile",
    pct: float = 75.0,
    z_factor: float = 1.5,
    mad_factor: float = 2.0,
    window_frac: float = 0.1,
    ma_factor: float = 1.5,
    min_region_samples: int = 5,
    merge_gap_samples: int = 10,
    peak_prominence_frac: float = 0.05,
) -> Tuple[List[Tuple[int, int]], np.ndarray, Union[float, np.ndarray]]:
    """
    Identify intervals of elevated wavelet energy in Ω(τ).

    Four thresholding strategies are available.

    method='percentile'  (default, pct=75)
        threshold = np.percentile(g_sum, pct)
        ✓ Simplest and most interpretable.
        ✓ Scale-invariant — works regardless of recording length or amplitude.
        ✗ Always returns regions even for flat/noisy signals; raise pct to
          90–95 for sparse events.

    method='zscore'  (z_factor=1.5)
        threshold = mean + z_factor × std
        ✓ Uses the signal's own statistics; ~7% false positives at z=1.5
          under a Gaussian assumption.
        ✗ Sensitive to outliers that inflate std, effectively lowering
          the threshold for the rest of the recording.

    method='mad'  (mad_factor=2.0)
        threshold = median + mad_factor × 1.4826 × MAD
        ✓ Breakdown-resistant; robust to artefacts and rare spike events.
        ✓ Best default for sparse biological transients.
        ✗ Under-estimates threshold when events occupy > 50% of the signal.

    method='moving_average'  (window_frac=0.1, ma_factor=1.5)
        threshold(τ) = local_mean(τ) + ma_factor × local_std(τ)
        ✓ Adapts to slow drifts in background wavelet energy.
        ✓ Essential for long recordings where electrode conditions vary.
        ✗ Introduces boundary effects; window_frac requires tuning.

    Parameters
    ----------
    g_sum      : 1-D array, Ω(τ) from compute_scalogram().
    method     : 'percentile', 'zscore', 'mad', or 'moving_average'.
    pct        : percentile threshold (method='percentile').
    z_factor   : std multiplier (method='zscore').
    mad_factor : MAD multiplier (method='mad').
    window_frac: fraction of N used as moving-average window.
    ma_factor  : local-std multiplier (method='moving_average').
    min_region_samples : discard detected regions shorter than this.
    merge_gap_samples  : merge adjacent regions separated by fewer samples.
    peak_prominence_frac : minimum peak prominence as a fraction of g_sum range.

    Returns
    -------
    regions   : list of (start, end) sample-index tuples.
    peaks     : 1-D int array of local-maxima indices within detected regions.
    threshold : scalar or 1-D array, the computed decision boundary.
    """
    N = len(g_sum)

    # ---- Compute threshold ----------------------------------------------
    if method == "percentile":
        threshold: Union[float, np.ndarray] = float(np.percentile(g_sum, pct))
        mask = g_sum > threshold

    elif method == "zscore":
        mu    = float(g_sum.mean())
        sigma = float(g_sum.std())
        threshold = mu + z_factor * sigma
        mask = g_sum > threshold

    elif method == "mad":
        med       = float(np.median(g_sum))
        mad_val   = float(np.median(np.abs(g_sum - med)))
        threshold = med + mad_factor * 1.4826 * mad_val
        mask = g_sum > threshold

    elif method == "moving_average":
        win = max(3, int(N * window_frac))
        if win % 2 == 0:
            win += 1
        ma_mean = uniform_filter1d(g_sum,       size=win, mode="nearest")
        ma_sq   = uniform_filter1d(g_sum ** 2,  size=win, mode="nearest")
        ma_std  = np.sqrt(np.maximum(ma_sq - ma_mean ** 2, 0.0))
        threshold = ma_mean + ma_factor * ma_std
        mask = g_sum > threshold

    else:
        raise ValueError(
            f"Unknown method '{method}'. "
            "Choose: percentile, zscore, mad, moving_average."
        )

    # ---- Extract contiguous True runs -----------------------------------
    padded = np.concatenate([[False], mask, [False]])
    diff   = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff ==  1)
    ends   = np.flatnonzero(diff == -1) - 1
    raw_regions: List[Tuple[int, int]] = list(zip(starts.tolist(), ends.tolist()))

    # ---- Merge nearby regions -------------------------------------------
    if merge_gap_samples > 0 and len(raw_regions) > 1:
        merged: List[Tuple[int, int]] = [raw_regions[0]]
        for s, e in raw_regions[1:]:
            prev_s, prev_e = merged[-1]
            if s - prev_e <= merge_gap_samples:
                merged[-1] = (prev_s, e)
            else:
                merged.append((s, e))
        raw_regions = merged

    # ---- Filter by minimum length ---------------------------------------
    regions = [(s, e) for s, e in raw_regions if (e - s + 1) >= min_region_samples]

    # ---- Find local maxima inside detected regions ----------------------
    prom = peak_prominence_frac * (float(g_sum.max()) - float(g_sum.min()))
    all_peaks, _ = find_peaks(g_sum, prominence=prom)
    if len(all_peaks) > 0 and len(regions) > 0:
        region_mask = np.zeros(N, dtype=bool)
        for s, e in regions:
            region_mask[s : e + 1] = True
        peaks = all_peaks[region_mask[all_peaks]]
    else:
        peaks = np.array([], dtype=int)

    return regions, peaks, threshold


# ===========================================================================
# 4. Peak clustering
# ===========================================================================

def cluster_peaks(
    peaks: np.ndarray,
    min_peaks: int = 3,
    max_gap_samples: int = 300,
    pad_samples: int = 30,
    signal_length: int = 0,
) -> List[Tuple[int, int]]:
    """
    Group nearby peaks into clusters and return the span of each valid cluster.

    Two peaks are assigned to the same cluster if the gap between them is at
    most max_gap_samples.  Clusters with fewer than min_peaks peaks are
    discarded as isolated events (likely noise or single transients).  Each
    surviving cluster is expanded by pad_samples on each side so that the
    highlighted region encompasses the full burst of activity, not just the
    individual peak tips.

    Parameters
    ----------
    peaks : 1-D int array of peak sample indices returned by
            detect_high_energy_regions().  Must be sorted ascending.
    min_peaks : minimum peaks required to form a valid cluster.
                Default 3.  Raise to focus on sustained bursts; lower to
                capture shorter events.
    max_gap_samples : maximum gap between consecutive peaks that still
                      keeps them in the same cluster.  At fs=1 Hz,
                      300 samples = 5 minutes.
    pad_samples : samples added before the first and after the last peak
                  in each cluster.  Default 30 (= 30 s at fs=1 Hz).
    signal_length : total signal length; used to clip the cluster end to a
                    valid index.  Pass 0 to skip clipping.

    Returns
    -------
    cluster_regions : list of (start, end) sample-index tuples, one per
                      valid cluster, in ascending time order.
    """
    if len(peaks) == 0:
        return []

    peaks_sorted = np.sort(np.asarray(peaks, dtype=int))

    # Greedy grouping: start a new group when the gap exceeds max_gap_samples
    groups: List[List[int]] = []
    current: List[int] = [int(peaks_sorted[0])]
    for pk in peaks_sorted[1:]:
        if pk - current[-1] <= max_gap_samples:
            current.append(int(pk))
        else:
            groups.append(current)
            current = [int(pk)]
    groups.append(current)

    max_idx = (signal_length - 1) if signal_length > 0 else int(peaks_sorted[-1]) + pad_samples
    cluster_regions: List[Tuple[int, int]] = []
    for group in groups:
        if len(group) >= min_peaks:
            s = max(0, group[0] - pad_samples)
            e = min(max_idx, group[-1] + pad_samples)
            cluster_regions.append((s, e))

    return cluster_regions


# ===========================================================================
# 5. Polynomial-fit peak clustering
# ===========================================================================

def cluster_peaks_poly(
    g_sum: np.ndarray,
    t: np.ndarray,
    degree: int = 6,
    threshold_method: str = "percentile",
    pct: float = 60.0,
    z_factor: float = 0.5,
    min_region_samples: int = 10,
    merge_gap_samples: int = 30,
) -> Tuple[List[Tuple[int, int]], np.ndarray]:
    """
    Identify high-energy cluster regions by fitting a low-degree polynomial
    to the Ω(τ) column-sum profile.

    How it works
    ------------
    A single degree-n polynomial is fitted to the full Ω(τ) curve using
    least-squares.  Because the polynomial is a smooth global function it
    can only model broad, sustained features of the signal:

      * An isolated peak occupies one or two samples.  Its influence on a
        polynomial fitted to thousands of samples is negligible — the curve
        barely moves.
      * A cluster of peaks elevates Ω(τ) over a sustained window of time.
        The polynomial must "bulge" upward to fit that elevated region,
        creating a visible hump.

    Regions where the fitted polynomial exceeds a threshold are returned as
    the detected cluster spans.

    Choosing the degree
    -------------------
    The degree determines the shortest timescale the polynomial can resolve.
    Each "hump" it can model spans roughly N/degree samples, where N is the
    signal length:

        degree = 3   →  1-2 very coarse bumps across the whole signal
        degree = 6   →  ~3 medium-scale bumps  (good starting point)
        degree = 10  →  ~5 features, more locally sensitive
        degree = 20  →  starts to capture sub-cluster structure

    Higher degree = more sensitive to shorter clusters, but also increasingly
    susceptible to isolated peaks and edge artefacts (Runge's phenomenon).
    Normalising the x-axis to [-1, 1] before fitting substantially reduces
    numerical ill-conditioning for higher degrees.

    Limitations
    -----------
    * **Global fit**: a large cluster at one end of the recording slightly
      elevates the polynomial everywhere else too.  Use a moderate degree
      and inspect the poly_values overlay to catch false positives.
    * **Runge oscillations**: for degree > ~15 on long signals, the
      polynomial can oscillate wildly near the boundaries.  Cap at ~12
      unless the signal is short.
    * **Outlier sensitivity**: one very large spike in Ω(τ) pulls the
      polynomial toward it, which can create a false positive nearby.
      Pre-filtering Ω(τ) with a short median filter before calling this
      function can help in artefact-heavy recordings.

    Threshold methods
    -----------------
    'percentile' (default, pct=60)
        Regions where poly > percentile(poly_values, pct).
        pct=50 ≈ "above the median of the smooth envelope" = above average.
        Raise pct (e.g. 70-80) to keep only the most pronounced humps.

    'z_score' (z_factor=0.5)
        Regions where poly > mean(poly) + z_factor * std(poly).
        z_factor=0 is equivalent to pct≈50 for symmetric polynomial shapes.
        Useful when you want to reason about the threshold in units of
        standard deviations of the polynomial's own variability.

    Parameters
    ----------
    g_sum  : 1-D array, Ω(τ) from compute_scalogram().
    t      : 1-D array, time axis (seconds).  Not used in the fit itself;
             included so the function signature matches cluster_peaks().
    degree : polynomial degree.  Default 6.
    threshold_method : 'percentile' or 'z_score'.
    pct    : percentile threshold for method='percentile'.
    z_factor : std multiplier for method='z_score'.
    min_region_samples : discard detected regions shorter than this.
    merge_gap_samples  : merge adjacent regions separated by fewer samples.

    Returns
    -------
    cluster_regions : list of (start, end) sample-index tuples.
    poly_values     : 1-D float array, the evaluated polynomial (same
                      length as g_sum).  Pass as poly_values= to
                      plot_wavelet_activity_overview() to overlay the fit
                      on the Ω(τ) panel for visual validation.
    """
    N = len(g_sum)

    # Normalise x to [-1, 1] to reduce numerical ill-conditioning
    x_norm = np.linspace(-1.0, 1.0, N)

    coeffs      = np.polyfit(x_norm, g_sum, degree)
    poly_values = np.polyval(coeffs, x_norm)

    # ---- Threshold ----------------------------------------------------------
    if threshold_method == "percentile":
        threshold = float(np.percentile(poly_values, pct))
    elif threshold_method == "z_score":
        threshold = float(poly_values.mean() + z_factor * poly_values.std())
    else:
        raise ValueError(
            f"Unknown threshold_method '{threshold_method}'. "
            "Choose: percentile, z_score."
        )

    mask = poly_values > threshold

    # ---- Extract contiguous True runs ---------------------------------------
    padded = np.concatenate([[False], mask, [False]])
    diff   = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff ==  1)
    ends   = np.flatnonzero(diff == -1) - 1
    raw_regions: List[Tuple[int, int]] = list(zip(starts.tolist(), ends.tolist()))

    # ---- Merge nearby regions -----------------------------------------------
    if merge_gap_samples > 0 and len(raw_regions) > 1:
        merged: List[Tuple[int, int]] = [raw_regions[0]]
        for s, e in raw_regions[1:]:
            prev_s, prev_e = merged[-1]
            if s - prev_e <= merge_gap_samples:
                merged[-1] = (prev_s, e)
            else:
                merged.append((s, e))
        raw_regions = merged

    # ---- Filter by minimum length -------------------------------------------
    cluster_regions = [
        (s, e) for s, e in raw_regions if (e - s + 1) >= min_region_samples
    ]

    return cluster_regions, poly_values


# ===========================================================================
# 6. Three-panel overview figure
# ===========================================================================

def plot_wavelet_activity_overview(
    signal: np.ndarray,
    t: np.ndarray,
    g: np.ndarray,
    g_sum: np.ndarray,
    freqs: np.ndarray,
    regions: Optional[List[Tuple[int, int]]] = None,
    peaks: Optional[np.ndarray] = None,
    cluster_regions: Optional[List[Tuple[int, int]]] = None,
    threshold: Optional[Union[float, np.ndarray]] = None,
    poly_values: Optional[np.ndarray] = None,
    show_regions: bool = True,
    show_peaks: bool = True,
    fs: float = 1.0,
    title: str = "Wavelet Activity Overview",
    smooth_signal: bool = False,
    smooth_window: int = 11,
    smooth_poly: int = 2,
    cmap: str = "inferno",
    log_scalogram: bool = False,
    dark: bool = True,
    figsize: Tuple[float, float] = (16, 10),
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Three-panel presentation-quality figure with a shared time axis.

    Panel layout
    ------------
    Top (40%)    : Raw signal.
                   Optional Savitzky-Golay smoothed overlay.
                   High-energy regions shaded with semi-transparent spans.
                   Downward triangle markers at Ω(τ) peak times.

    Middle (40%) : Normalised Morse-wavelet scalogram.
                   Y-axis = frequency in Hz, log scale (low freq at bottom).
                   Colorbar attached to the right.

    Bottom (20%) : Ω(τ) column-sum energy profile.
                   Threshold line (scalar) or adaptive-threshold curve (array).
                   Same region shading as top panel.
                   Upward triangle markers at detected peaks.

    Parameters
    ----------
    signal, t      : 1-D signal and time arrays from load_signal().
    g, g_sum, freqs: outputs of compute_scalogram().
    regions, peaks, threshold : outputs of detect_high_energy_regions().
    fs             : sampling frequency in Hz.
    title          : figure suptitle.
    smooth_signal  : overlay a Savitzky-Golay smoothed trace on the signal panel.
    smooth_window  : Savitzky-Golay window length (must be odd, >= smooth_poly+2).
    smooth_poly    : Savitzky-Golay polynomial order.
    cmap           : matplotlib colormap for the scalogram (default 'inferno').
    log_scalogram  : apply log1p to scalogram values before display, which
                     compresses the dynamic range and reveals low-energy structure
                     that would otherwise be hidden by bright hot spots.
    dark           : dark background theme (True) or light (False).
    figsize        : (width, height) in inches.
    save_path      : file path to save figure (e.g. 'overview.png').

    Returns
    -------
    fig : matplotlib.figure.Figure
    """
    regions         = regions or []
    cluster_regions = cluster_regions or []
    peaks           = np.asarray(peaks, dtype=int) if peaks is not None else np.array([], dtype=int)

    # ---- Colour palette -------------------------------------------------
    if dark:
        bg, fg        = "#1a1a1a", "#dddddd"
        grid_c        = "#2e2e2e"
        sig_c         = "#5599ff"
        smooth_c      = "#ffffff"
        sum_c         = "#44ff99"
        thr_c, hi_c   = "#ff4444", "#ffaa44"
        peak_c        = "#ffee44"
        clust_c       = "#ff4488"   # distinct pink-red for clusters
        poly_c        = "#cccccc"   # light grey polynomial overlay
        spine_c       = "#444444"
    else:
        bg, fg        = "#f8f8f8", "#111111"
        grid_c        = "#e0e0e0"
        sig_c         = "#1155cc"
        smooth_c      = "#cc2222"
        sum_c         = "#117744"
        thr_c, hi_c   = "#cc0000", "#ff8800"
        peak_c        = "#cc6600"
        clust_c       = "#cc0055"   # distinct dark-pink for clusters
        poly_c        = "#555555"   # dark grey polynomial overlay
        spine_c       = "#bbbbbb"

    # ---- Figure and axes ------------------------------------------------
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor(bg)

    gs = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[3, 3, 2], hspace=0.06)
    ax_sig   = fig.add_subplot(gs[0])
    ax_scalo = fig.add_subplot(gs[1], sharex=ax_sig)
    ax_sum   = fig.add_subplot(gs[2], sharex=ax_sig)

    for ax in (ax_sig, ax_scalo, ax_sum):
        ax.set_facecolor(bg)
        for sp in ax.spines.values():
            sp.set_edgecolor(spine_c)
        ax.tick_params(colors=fg, labelsize=9)
        ax.grid(True, color=grid_c, linewidth=0.5, linestyle="--", alpha=0.6)

    # ---- Helper: shade regions on a given axes --------------------------
    # When cluster_regions are present, threshold regions become a subtle
    # background hint; clusters are the prominent foreground layer.
    def _shade(ax: plt.Axes) -> None:
        if show_regions:
            bg_alpha = 0.07 if cluster_regions else 0.18
            for i, (s, e) in enumerate(regions):
                ax.axvspan(
                    t[s], t[min(e, len(t) - 1)],
                    color=hi_c, alpha=bg_alpha, linewidth=0, zorder=1,
                    label="High-energy region" if (i == 0 and not cluster_regions) else "_",
                )
        for i, (s, e) in enumerate(cluster_regions):
            t_s = t[s]
            t_e = t[min(e, len(t) - 1)]
            ax.axvspan(
                t_s, t_e,
                color=clust_c, alpha=0.25, linewidth=0, zorder=2,
                label="Peak cluster" if i == 0 else "_",
            )
            # Boundary markers so the cluster edges are easy to read
            ax.axvline(t_s, color=clust_c, linewidth=1.0,
                       linestyle="--", alpha=0.55, zorder=3)
            ax.axvline(t_e, color=clust_c, linewidth=1.0,
                       linestyle="--", alpha=0.55, zorder=3)

    # ================================================================
    # TOP: Raw signal
    # ================================================================
    ax_sig.plot(t, signal, color=sig_c, linewidth=0.9, alpha=0.85,
                zorder=2, label="Signal")

    if smooth_signal:
        win_s = min(smooth_window, len(signal) - 1)
        if win_s % 2 == 0:
            win_s -= 1
        sig_smooth = savgol_filter(signal, win_s, smooth_poly)
        ax_sig.plot(t, sig_smooth, color=smooth_c, linewidth=1.8,
                    alpha=0.9, zorder=3, label="Smoothed")

    _shade(ax_sig)

    if show_peaks and len(peaks) > 0:
        ax_sig.scatter(
            t[peaks], signal[peaks],
            color=peak_c, s=35, marker="v", zorder=5, label="Energy peak",
        )

    # Annotate each cluster with its peak count at the top of the panel
    if cluster_regions and show_peaks and len(peaks) > 0:
        xform = ax_sig.get_xaxis_transform()   # x=data coords, y=[0,1] axes fraction
        for s, e in cluster_regions:
            t_s   = t[s]
            t_e   = t[min(e, len(t) - 1)]
            t_mid = (t_s + t_e) / 2.0
            n_pks = int(np.sum((peaks >= s) & (peaks <= e)))
            ax_sig.text(
                t_mid, 0.97,
                f"{n_pks}",
                transform=xform,
                ha="center", va="top",
                fontsize=8, fontweight="bold",
                color=clust_c,
            )

    ax_sig.set_ylabel("Signal (mV)", color=fg, fontsize=10, labelpad=6)
    ax_sig.yaxis.label.set_color(fg)
    ax_sig.legend(fontsize=8, loc="upper right",
                  labelcolor=fg, facecolor=bg, edgecolor=spine_c, framealpha=0.7)
    plt.setp(ax_sig.get_xticklabels(), visible=False)

    # ================================================================
    # MIDDLE: Scalogram
    # ================================================================
    # Flip rows so lowest frequency is at the bottom (conventional orientation).
    # Row 0 of g = smallest scale = highest frequency.
    g_display = g[::-1, :]
    freqs_asc = freqs[::-1]          # now ascending: low → high

    if log_scalogram:
        g_display = np.log1p(g_display)

    # Clip at 99th percentile to prevent hot spots from washing out detail.
    vmax = float(np.percentile(g_display, 99))
    vmin = float(g_display.min())

    im = ax_scalo.pcolormesh(
        t, freqs_asc, g_display,
        cmap=cmap,
        shading="nearest",
        vmin=vmin, vmax=vmax,
        rasterized=True,    # keeps file size manageable for PDF/SVG export
    )
    ax_scalo.set_yscale("log")
    ax_scalo.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:.3f}" if v < 0.01 else f"{v:.2f}")
    )
    ax_scalo.yaxis.set_minor_formatter(mticker.NullFormatter())

    cb = fig.colorbar(im, ax=ax_scalo, fraction=0.025, pad=0.012, shrink=0.9)
    cb.set_label(
        "log₁₊(g)" if log_scalogram else "Normalised energy  g",
        color=fg, fontsize=8,
    )
    cb.ax.tick_params(colors=fg, labelsize=7)
    cb.outline.set_edgecolor(spine_c)

    _shade(ax_scalo)

    ax_scalo.set_ylabel("Frequency (Hz)", color=fg, fontsize=10, labelpad=6)
    ax_scalo.yaxis.label.set_color(fg)
    plt.setp(ax_scalo.get_xticklabels(), visible=False)

    # ================================================================
    # BOTTOM: Column-sum energy profile
    # ================================================================
    ax_sum.plot(t, g_sum, color=sum_c, linewidth=1.2, zorder=2, label="Ω(τ)")

    if poly_values is not None:
        ax_sum.plot(t, poly_values, color=poly_c, linewidth=2.0,
                    linestyle="-", alpha=0.9, zorder=4, label="Poly fit")

    if threshold is not None:
        thr_arr = np.asarray(threshold)
        if thr_arr.ndim == 0 or thr_arr.size == 1:
            thr_val = float(thr_arr)
            ax_sum.axhline(thr_val, color=thr_c, linewidth=1.4,
                           linestyle="--", alpha=0.85, zorder=3,
                           label=f"Threshold ({thr_val:.0f})")
        else:
            ax_sum.plot(t, thr_arr, color=thr_c, linewidth=1.2,
                        linestyle="--", alpha=0.85, zorder=3,
                        label="Adaptive threshold")

    _shade(ax_sum)

    if show_peaks and len(peaks) > 0:
        ax_sum.scatter(
            t[peaks], g_sum[peaks],
            color=peak_c, s=45, marker="^", zorder=5, label="Peak",
        )

    ax_sum.set_ylabel("Ω(τ)", color=fg, fontsize=10, labelpad=6)
    ax_sum.yaxis.label.set_color(fg)
    ax_sum.legend(fontsize=8, loc="upper right",
                  labelcolor=fg, facecolor=bg, edgecolor=spine_c, framealpha=0.7)

    # Auto-select time unit for x-axis label
    t_max = float(t[-1])
    if t_max > 3600:
        t_unit, t_scale = "hours",   1.0 / 3600
    elif t_max > 60:
        t_unit, t_scale = "minutes", 1.0 / 60
    else:
        t_unit, t_scale = "seconds", 1.0

    if t_scale != 1.0:
        ax_sum.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v * t_scale:.1f}")
        )
    ax_sum.set_xlabel(f"Time ({t_unit})", color=fg, fontsize=10, labelpad=5)
    ax_sum.xaxis.label.set_color(fg)

    # ---- Suptitle -------------------------------------------------------
    n_r = len(regions)
    n_p = len(peaks)
    n_c = len(cluster_regions)
    cluster_str = f"{n_c} cluster(s)  ·  " if cluster_regions else ""
    fig.suptitle(
        f"{title}\n"
        f"{cluster_str}{n_r} high-energy region(s)  ·  {n_p} peak(s)  ·  "
        f"{g.shape[0]} scales  ·  fs = {fs} Hz",
        color=fg, fontsize=11, y=0.995,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.97])

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=bg)
        print(f"  Saved: {save_path}")

    plt.show()
    return fig
