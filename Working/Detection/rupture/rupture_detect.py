"""
rupture_detect.py
==================
Change-point detection for mycelium bio-electric time series, built on the
``ruptures`` library.

What this module does — and does not — find
---------------------------------------------
Change-point detection partitions a signal into contiguous segments that are
*statistically distinct* from their neighbours under a chosen cost model
(e.g. a shift in mean/variance for "l2", a shift in the empirical distribution
for "rbf").  It is complementary to, and answers a different question than,
motif discovery (matrix_profiling/) or SAX symbolisation (sax/):

    Matrix profile / SAX  ->  "where does this same *shape* recur?"
    Change-point detection ->  "where does the signal's *statistical regime*
                                 change, regardless of shape?"

A detected change point marks a boundary between two segments with different
statistics under the cost model — it is not necessarily a spike, motif, or
event with any particular waveform. Two segments either side of a change
point can look visually similar and still be flagged distinct (e.g. a subtle
variance shift under "rbf"), and conversely a visually obvious transient can
be missed if it does not change the chosen statistic.

Not scale-invariant
--------------------
Unlike matrix profiling in this repo, this function does not require you to
choose a window length up front — algorithms here scan the whole signal and
place breakpoints wherever the cost model says segments differ, without a
fixed lookback. But "no fixed window" does not mean "scale invariant": the
`penalty` (or `n_bkps`) argument implicitly sets the scale of change that
gets reported (see `detect_change_points` docstring). A given signal will
often yield 3 change points at one penalty and 30 at another an order of
magnitude smaller, and there is no single "correct" answer independent of
this choice. If the segmentation you get looks unstable — segments merge,
split, or shift noticeably when you nudge the penalty — do not trust a
single run. Re-run across a small sweep of penalty values (e.g. logarithmically
spaced) and treat only change points that persist across that sweep as robust.

Workflow
--------
    x, t   = load_raw_data(FILENAME, FS)              # manage_data.load_data
    result = detect_change_points(x, t, penalty=50.0)  # tune penalty, see below
    plot_change_points(x, t, result)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
import ruptures as rpt

# ---------------------------------------------------------------------------
# Algorithm registry
# ---------------------------------------------------------------------------
_ALGOS: dict[str, type] = {
    "pelt": rpt.Pelt,
    "binseg": rpt.Binseg,
    "bottomup": rpt.BottomUp,
    "window": rpt.Window,
}

# Pelt is exact and penalty-only (no direct n_bkps support in ruptures).
_PENALTY_ONLY_ALGOS: frozenset[str] = frozenset({"pelt"})


# ===========================================================================
# Return type
# ===========================================================================
@dataclass
class ChangePointResult:
    """
    All outputs from ``detect_change_points``.

    Attributes
    ----------
    bkps_idx : np.ndarray, shape (n_bkps,)
        Sample indices of detected segment boundaries, i.e. the index of the
        first sample belonging to each new segment. Does NOT include index 0
        or the final sample count — ruptures internally appends n_samples as
        a sentinel "last breakpoint"; that sentinel is stripped here so every
        entry is a genuine, interior change point.
    bkps_t : np.ndarray, shape (n_bkps,)
        Timestamps corresponding to ``bkps_idx``, in the same units as the
        input ``t`` (whatever ``load_raw_data`` produced — seconds when ``t``
        came from ``np.arange(len(x)) / fs``).
    n_bkps : int
        Number of detected change points, i.e. ``len(bkps_idx)``.
    algo : str
        Algorithm used (key into the internal algorithm registry).
    cost_model : str
        ruptures cost model string used (e.g. "l1", "l2", "rbf").
    penalty : float or None
        Penalty value passed to ``predict``. None if ``n_bkps`` was used
        instead.
    n_bkps_requested : int or None
        Exact breakpoint count passed to ``predict``. None if ``penalty``
        was used instead.
    min_size : int
        Minimum segment length (in samples) enforced by the algorithm.
    jump : int
        Subsampling grid for candidate breakpoints (in samples) — larger
        values trade boundary precision for speed on long signals.
    n_samples : int
        Length of the input signal.
    elapsed_s : float
        Wall-clock time spent fitting + predicting, in seconds.
    algo_kwargs : dict
        Any extra keyword arguments forwarded to the ruptures algorithm
        constructor (e.g. ``width`` for ``algo="window"``).
    """

    bkps_idx: np.ndarray
    bkps_t: np.ndarray
    n_bkps: int
    algo: str
    cost_model: str
    penalty: float | None
    n_bkps_requested: int | None
    min_size: int
    jump: int
    n_samples: int
    elapsed_s: float
    algo_kwargs: dict = field(default_factory=dict)


# ===========================================================================
# Public entry point
# ===========================================================================
def detect_change_points(
    x: np.ndarray,
    t: np.ndarray,
    algo: str = "pelt",
    cost_model: str = "l2",
    penalty: float | None = None,
    n_bkps: int | None = None,
    min_size: int = 2,
    jump: int = 5,
    **algo_kwargs,
) -> ChangePointResult:
    """
    Detect statistically distinct segments in a time series using ``ruptures``.

    No fixed window length is assumed: every supported algorithm scans the
    entire signal and places breakpoints wherever segments differ under the
    chosen cost model, so this works directly on long, multi-hour recordings
    without pre-choosing a scale of interest. See the module docstring for
    what "change point" means here and why this is *not* scale-invariant.

    Parameters
    ----------
    x : np.ndarray, shape (n_samples,)
        Raw (or preprocessed) signal, matching the ``x`` returned by
        ``manage_data.load_data.load_raw_data``.
    t : np.ndarray, shape (n_samples,)
        Timestamps corresponding to ``x`` (same convention as ``load_raw_data``
        — seconds since recording start). Used only to build ``bkps_t``; not
        passed to ruptures, which only cares about sample order.
    algo : {"pelt", "binseg", "bottomup", "window"}
        Search method.
          "pelt"     — exact, penalty-driven, linear-time-ish via pruning.
                       Default; best general choice for long signals when you
                       don't know the number of change points in advance.
          "binseg"   — greedy binary segmentation, approximate but fast;
                       supports both ``penalty`` and ``n_bkps``.
          "bottomup" — greedy bottom-up merging, approximate; tends to be more
                       stable than binseg when change points are close together.
          "window"   — sliding-window comparison (accepts an optional
                       ``width`` kwarg via ``**algo_kwargs``); the one method
                       here that *does* use a local scale, included only
                       because ruptures exposes it — prefer "pelt" unless you
                       specifically want windowed comparison.
    cost_model : str
        ruptures cost model, forwarded as the ``model=`` argument to the
        chosen algorithm. Common choices:
          "l2"     — mean shift, Gaussian iid assumption. Fast, good default.
          "l1"     — mean shift, robust to outliers/heavy tails.
          "rbf"    — kernel-based; detects distributional changes beyond just
                     the mean (e.g. variance, shape). Slower, more general.
          "normal" — Gaussian mean AND variance shift (needs longer segments
                     to estimate covariance reliably).
          "ar"     — autoregressive model changes; use if the signal has
                     strong local temporal structure you want segmented on.
        See ``ruptures.costs`` for the full list.
    penalty : float, optional
        Complexity penalty added per extra segment. This is the primary
        control on segmentation granularity:
          - Larger penalty -> fewer, coarser segments (only large regime
            shifts survive).
          - Smaller penalty -> more, finer segments (increasingly sensitive
            to noise; can fragment into spurious single-sample segments).
        There is no dataset-independent "correct" value — it scales with the
        cost model's units and the signal's variance. Tuning approach:
        start from an order-of-magnitude guess, then sweep (e.g.
        ``[pen/10, pen/3, pen, pen*3, pen*10]``) and look for a plateau where
        the number of detected change points is stable across a range —
        that plateau is a more trustworthy choice than any single value.
        Required when ``algo="pelt"`` (Pelt does not support ``n_bkps``).
        Mutually exclusive with ``n_bkps``.
    n_bkps : int, optional
        Exact number of change points to return, if you know it a priori
        (e.g. from experimental metadata). Only supported for
        ``algo in {"binseg", "bottomup", "window"}``. Mutually exclusive
        with ``penalty``.
    min_size : int
        Minimum number of samples per segment. Prevents degenerate
        single-sample segments; raise this if you see implausibly short
        segments at low penalties. Default 2 (ruptures' own default).
    jump : int
        Only every ``jump``-th sample is considered as a candidate breakpoint.
        Purely a speed/precision trade-off — does not encode an assumption
        about the scale of the underlying change. Larger values speed up
        long signals at the cost of ±jump sample precision on boundary
        location. Default 5 (ruptures' own default).
        In practice, ruptures' pure-Python implementation is slow in
        absolute terms: on this repo's data (fs=1 Hz), Pelt/l2 took roughly
        20-35s for a 3-hour (~10,800-sample) slice, and Binseg/rbf took
        ~3 minutes for the same slice (rbf's cost is dominated by an O(n^2)
        Gram-matrix computation at fit time, largely independent of `jump`).
        For a full multi-hour recording (hundreds of thousands to millions
        of samples), raise `jump` well above the default (e.g. into the
        tens-to-hundreds) and/or pre-downsample `x`/`t` before calling this
        function — do not assume the default settings will finish quickly
        on the full signal.
    **algo_kwargs
        Extra keyword arguments forwarded to the algorithm constructor
        (e.g. ``width=200`` for ``algo="window"``).

    Returns
    -------
    ChangePointResult

    Raises
    ------
    ValueError
        If ``algo`` or ``cost_model`` is unrecognised, if both/neither of
        ``penalty``/``n_bkps`` are given, or if ``penalty`` is missing for
        ``algo="pelt"``.
    """
    if algo not in _ALGOS:
        raise ValueError(f"Unknown algo '{algo}'. Choose from {sorted(_ALGOS)}.")

    if penalty is not None and n_bkps is not None:
        raise ValueError("Provide at most one of `penalty` or `n_bkps`, not both.")

    if algo in _PENALTY_ONLY_ALGOS:
        if penalty is None:
            raise ValueError(
                f"algo='{algo}' requires `penalty` (it does not support `n_bkps`). "
                "See the `penalty` docstring for tuning guidance."
            )
    elif penalty is None and n_bkps is None:
        raise ValueError(
            "Provide either `penalty` or `n_bkps` for "
            f"algo='{algo}'. See the `detect_change_points` docstring."
        )

    x = np.asarray(x, dtype=float)
    n_samples = len(x)
    signal = x.reshape(-1, 1)

    algo_cls = _ALGOS[algo]
    detector = algo_cls(model=cost_model, min_size=min_size, jump=jump, **algo_kwargs)

    t0 = time.time()
    detector.fit(signal)
    if algo in _PENALTY_ONLY_ALGOS:
        bkps = detector.predict(pen=penalty)
    else:
        bkps = detector.predict(n_bkps=n_bkps, pen=penalty)
    elapsed = time.time() - t0

    # ruptures appends n_samples as a sentinel final "breakpoint" — strip it
    # so bkps_idx contains only genuine interior change points.
    bkps_idx = np.array(bkps[:-1], dtype=int)
    bkps_t = np.asarray(t)[bkps_idx]

    print(
        f"detect_change_points: algo={algo}  model={cost_model}  "
        f"n_samples={n_samples:,}  -> {len(bkps_idx)} change point(s)  "
        f"({elapsed:.2f}s)"
    )

    return ChangePointResult(
        bkps_idx=bkps_idx,
        bkps_t=bkps_t,
        n_bkps=len(bkps_idx),
        algo=algo,
        cost_model=cost_model,
        penalty=penalty,
        n_bkps_requested=n_bkps,
        min_size=min_size,
        jump=jump,
        n_samples=n_samples,
        elapsed_s=elapsed,
        algo_kwargs=dict(algo_kwargs),
    )


# ===========================================================================
# Visualisation
# ===========================================================================

# Alternating segment shading — muted, readable on light or dark backgrounds.
_SEGMENT_COLORS: tuple[str, str] = ("#5b9bd5", "#e05c5c")


def plot_change_points(
    x: np.ndarray,
    t: np.ndarray,
    result: ChangePointResult,
    style: str = "both",
    figsize: tuple[float, float] = (16, 5),
    dark: bool = False,
    title: str | None = None,
) -> plt.Figure:
    """
    Plot the raw signal with detected change points overlaid.

    Parameters
    ----------
    x : np.ndarray, shape (n_samples,)
        Same signal passed to ``detect_change_points``.
    t : np.ndarray, shape (n_samples,)
        Same timestamps passed to ``detect_change_points`` (seconds).
    result : ChangePointResult
        Output of ``detect_change_points``.
    style : {"lines", "shaded", "both"}
        "lines"  — dashed vertical line at each change point.
        "shaded" — alternating background colour per segment.
        "both"   — both overlays (default); shading gives an at-a-glance
                   segment count, lines pinpoint the exact boundary sample.
    figsize : tuple
        Figure size in inches.
    dark : bool
        If True, use a dark figure background (matches the ``dark`` option
        in dendrogram/dendrogram_cluster.py plots).
    title : str, optional
        Custom title. Defaults to a summary of the detection parameters.

    Returns
    -------
    plt.Figure
    """
    if style not in ("lines", "shaded", "both"):
        raise ValueError(f"style must be 'lines', 'shaded', or 'both', got '{style}'")

    x = np.asarray(x, dtype=float)
    t_hours = np.asarray(t, dtype=float) / 3600.0
    x_mv = x * 1000

    bkps_t_hours = result.bkps_t / 3600.0
    bkps_idx = result.bkps_idx

    bg = "#1a1a1a" if dark else "#ffffff"
    fg = "#dddddd" if dark else "#222222"
    grid_c = "#333333" if dark else "#eeeeee"

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    # ---- Shaded segments ---------------------------------------------------
    if style in ("shaded", "both"):
        boundaries = np.concatenate(([0], bkps_idx, [len(x)]))
        for i in range(len(boundaries) - 1):
            seg_start_h = t_hours[boundaries[i]]
            seg_end_idx = min(boundaries[i + 1], len(t_hours) - 1)
            seg_end_h = t_hours[seg_end_idx]
            ax.axvspan(
                seg_start_h, seg_end_h,
                facecolor=_SEGMENT_COLORS[i % 2], alpha=0.12 if dark else 0.10,
                zorder=1,
            )

    # ---- Signal --------------------------------------------------------------
    ax.plot(t_hours, x_mv, linewidth=0.6, color="steelblue" if not dark else "#7ec8e3", zorder=2)

    # ---- Change-point markers -------------------------------------------------
    if style in ("lines", "both"):
        for bt in bkps_t_hours:
            ax.axvline(x=bt, linestyle="dashed", linewidth=1.2, color="tomato", zorder=3)

    ax.set_xlabel("Time (hours)", fontsize=12, color=fg)
    ax.set_ylabel("Signal (mV)", fontsize=12, color=fg)
    ax.tick_params(colors=fg, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(grid_c)

    if title is None:
        pen_or_k = (
            f"pen={result.penalty:g}" if result.penalty is not None
            else f"n_bkps={result.n_bkps_requested}"
        )
        title = (
            f"Change-point detection  |  algo={result.algo}  model={result.cost_model}  "
            f"{pen_or_k}  |  {result.n_bkps} change point(s) found"
        )
    ax.set_title(title, fontsize=12, color=fg, pad=10)

    plt.tight_layout()
    plt.show()
    return fig
