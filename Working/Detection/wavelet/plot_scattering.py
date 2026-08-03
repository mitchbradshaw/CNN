"""
plot_scattering.py
====================
Scalogram-style visualisation for `ScatteringResult` objects produced by
`wavelet.scattering_transform.compute_wavelet_scattering`.

Layout
------
Order-0 coefficients (the local average of the *raw*, signed signal -- see
`scattering_transform.py`) have no associated scale/frequency band and a
completely different amplitude range from order >= 1 coefficients, so they
are not part of the heatmap. Instead:

    Top    : order-0 trend, plotted as an ordinary line (mirrors the
             "raw signal on top" panel used in `matrix_profiling` and
             `gramian` plots).
    Bottom : order-1 and order-2 coefficients as a heatmap (scale/frequency
             band on the y-axis, time on the x-axis, colour = magnitude in
             dB relative to the loudest coefficient in the plot). Rows are
             grouped by order and sorted by centre frequency (high to low)
             within each group, with separator lines and group labels,
             mirroring the grouped-heatmap convention used in
             `dendrogram.dendrogram_cluster.plot_preprocessed_heatmap`.

Why dB and not raw magnitude
------------------------------
Order-1 and order-2 coefficients routinely differ by 1-2 orders of magnitude
(order-2 coefficients are, by construction, a modulus-and-averaging cascade
applied *again* to an already-small order-1 output), and individual
coefficients within an order can also span a wide range depending on how
much energy the recording has at that scale. A linear color scale makes all
but the single largest coefficient invisible. Converting to dB relative to
the plot's own maximum (`ref`, computed from the data being plotted, not a
hardcoded constant) compresses this range so structure at every scale stays
visible; `clip_db` sets how far below that reference is still shown.
"""

from __future__ import annotations

import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.transforms import blended_transform_factory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Working.Detection.wavelet.scattering_transform import ScatteringResult


def plot_scattering_scalogram(
    result: ScatteringResult,
    figsize: tuple[float, float] = (14, 8),
    cmap: str = "magma",
    clip_db: float = -60.0,
    show_order0: bool = True,
    time_unit: str = "hours",
) -> plt.Figure:
    """
    Plot scattering coefficients as a scalogram-style heatmap.

    Parameters
    ----------
    result : ScatteringResult
        Output of `compute_wavelet_scattering`.
    figsize : tuple
        Figure size in inches (width, height).
    cmap : str
        Matplotlib colourmap name for the heatmap. A sequential map (this is
        a magnitude, not a signed quantity) works best -- e.g. "magma",
        "viridis", "turbo".
    clip_db : float
        Heatmap colour floor, in dB relative to the loudest order>=1
        coefficient in the plotted result (which is always 0 dB). Coefficients
        quieter than this are clipped to the floor colour. More negative =
        more low-energy detail shown, at the cost of contrast. Default -60.
    show_order0 : bool
        If True (default) and order-0 coefficients are present, draw them as
        a line plot above the heatmap. If False, or no order-0 row exists,
        only the heatmap is drawn.
    time_unit : {"hours", "seconds"}
        Units for the x-axis, derived from `result.t_scattering`.

    Returns
    -------
    plt.Figure
    """
    if time_unit not in ("hours", "seconds"):
        raise ValueError(f"time_unit must be 'hours' or 'seconds', got '{time_unit}'.")

    t_axis = result.t_scattering / 3600.0 if time_unit == "hours" else result.t_scattering
    xlabel = "Time (hours)" if time_unit == "hours" else "Time (s)"

    heatmap_rows, group_info = _group_and_sort_rows(result, min_order=1)
    if heatmap_rows.size == 0:
        raise ValueError(
            "No order>=1 coefficients found to plot (result.max_order may be 0). "
            "Recompute with max_order>=1."
        )
    Z_db = _to_db(result.Sx[heatmap_rows, :], clip_db)
    n_rows = Z_db.shape[0]

    order0_rows = np.where(result.order == 0)[0]
    draw_order0 = show_order0 and order0_rows.size > 0

    if draw_order0:
        fig, (ax_top, ax_heat) = plt.subplots(
            2, 1, figsize=figsize, sharex=True,
            gridspec_kw={"height_ratios": [1, 4], "hspace": 0.06},
        )
        for row in order0_rows:
            ax_top.plot(t_axis, result.Sx[row], linewidth=0.8, color="steelblue")
        ax_top.set_ylabel("Order 0\n(local mean)", fontsize=9)
        ax_top.tick_params(labelbottom=False)
    else:
        fig, ax_heat = plt.subplots(1, 1, figsize=figsize)
        ax_top = None

    extent = [t_axis[0], t_axis[-1], n_rows - 0.5, -0.5]
    im = ax_heat.imshow(Z_db, aspect="auto", cmap=cmap, extent=extent,
                         vmin=clip_db, vmax=0.0, interpolation="nearest")

    _draw_group_labels_and_separators(ax_heat, group_info, n_rows)

    ax_heat.set_xlabel(xlabel, fontsize=11)
    ax_heat.set_ylabel("Coefficient\n(grouped by order, sorted by frequency)", fontsize=10)

    title_ax = ax_top if ax_top is not None else ax_heat
    title_ax.set_title(
        f"Wavelet Scattering Scalogram  "
        f"(J={result.J}, Q={result.Q}, max_order={result.max_order})",
        fontsize=13,
    )

    cbar = fig.colorbar(im, ax=[ax_heat] if ax_top is None else [ax_top, ax_heat],
                         orientation="vertical", fraction=0.03, pad=0.02)
    cbar.set_label("Magnitude (dB rel. to plot max)", fontsize=9)

    if result.border_effects_flagged:
        ax_heat.text(
            0.99, -0.14,
            "border effects flagged (short input relative to J) — see docstring",
            transform=ax_heat.transAxes, ha="right", va="top",
            fontsize=8, color="firebrick",
        )

    plt.show()
    return fig


# ===========================================================================
# Helpers
# ===========================================================================

def _to_db(Z: np.ndarray, clip_db: float) -> np.ndarray:
    """
    Convert non-negative magnitudes to dB relative to their own max, floored
    at `clip_db`. `ref` is derived from `Z` itself so this never hardcodes an
    absolute scale -- it adapts to whatever channel/units the caller passed in.
    """
    ref = Z.max()
    if ref <= 0:
        return np.full_like(Z, clip_db)
    floor = ref * 10 ** (clip_db / 20.0)
    return 20.0 * np.log10(np.clip(Z, floor, None) / ref)


def _group_and_sort_rows(
    result: ScatteringResult,
    min_order: int = 0,
) -> tuple[np.ndarray, list[tuple[str, int, int]]]:
    """
    Build a row order that groups coefficients by scattering order and sorts
    each group by descending centre frequency, so the y-axis reads like a
    conventional high-to-low frequency scalogram within each order.

    Parameters
    ----------
    min_order : int
        Lowest order to include (e.g. 1 to exclude the signed order-0 row,
        which has no associated frequency).

    Returns
    -------
    ordered_rows : np.ndarray[int]
        Row indices into `result.Sx`, in display order.
    group_info : list[(label, start_row, end_row)]
        Row-span for each non-empty order group, in display coordinates.
    """
    ordered_rows: list[int] = []
    group_info: list[tuple[str, int, int]] = []

    labels = {0: "Order 0 (mean)", 1: "Order 1", 2: "Order 2"}
    for order_val in sorted(o for o in labels if o >= min_order):
        idx = np.where(result.order == order_val)[0]
        if idx.size == 0:
            continue
        freq = result.freq_hz[idx]
        sort_order = np.argsort(-np.nan_to_num(freq, nan=-np.inf))
        idx_sorted = idx[sort_order]

        start = len(ordered_rows)
        ordered_rows.extend(idx_sorted.tolist())
        group_info.append((labels[order_val], start, len(ordered_rows)))

    return np.array(ordered_rows, dtype=int), group_info


def _draw_group_labels_and_separators(
    ax: plt.Axes,
    group_info: list[tuple[str, int, int]],
    n_rows: int,
) -> None:
    """Draw separator lines and group name labels between order bands."""
    trans = blended_transform_factory(ax.transAxes, ax.transData)

    for label, start, end in group_info:
        if start > 0:
            ax.axhline(start - 0.5, color="white", linewidth=0.8, alpha=0.5, zorder=3)

        mid = (start + end - 1) / 2.0
        ax.text(
            -0.01, mid, label,
            transform=trans, ha="right", va="center",
            fontsize=8, fontweight="bold", color="#444444",
            clip_on=False,
        )


# ===========================================================================
# Demo — sanity-check on real project data
# ===========================================================================

if __name__ == "__main__":
    from Working.Preprocessing.manage_data.load_data import load_raw_data
    from Working.Detection.wavelet.scattering_transform import compute_wavelet_scattering

    FILE = "M2_concat_fs1_CH0.npy"
    FS = 1.0

    x, t = load_raw_data(FILE, FS)
    n_demo = min(len(x), 6000)
    x, t = x[:n_demo], t[:n_demo]

    result = compute_wavelet_scattering(x, t, J=8, Q=8)
    plot_scattering_scalogram(result)
