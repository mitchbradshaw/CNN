"""
overlays72.py
==============
drop_motifs7.2. One change from `overlays7`, and everything else is
imported from it unchanged.

THE MOTIF IS DRAWN AS IT LOOKS IN THE RECORDING.

drop_motifs7 locked the height-to-width ratio, which fixed the flattening,
but it derived the scale from an arbitrary target proportion
(`TARGET_MEDIAN_RATIO`, 0.55) rather than from the recording. So every
motif in every panel came out at the same proportion regardless of what it
actually looked like, which is a different distortion from the one it
replaced and, on catalogue ID 3, a worse one:

    in the span panel   the median motif occupies 3.83 : 1, tall
    in the overlay      it was drawn at 0.55 : 1, wide

A spike that is nearly four times taller than it is wide was being drawn
nearly twice as wide as it is tall - which is what the operator saw.

Here the scale is measured from the span panel itself: its data extent in
seconds and millivolts, and its box in inches, are all known, so the
millivolt-per-second it implies is a measurement rather than a choice.
Every motif panel is locked to it, and a motif therefore has the same
proportion in the overlay that it has in the recording above.

The one concession is a cap. Catalogue ID 22's motifs genuinely occupy
17 : 1 in its span panel, and a 17 : 1 panel shows nothing. Past
`style7.MAX_PANEL_RATIO` the scale is compressed and the figure says so,
rather than quietly presenting a compressed panel as an exact one.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm

from Pipelines.drop_motifs import passes7, style7
from Pipelines.drop_motifs.overlays7 import (RECORDED_FIELD, _span_panel,
                                             assign_hues, drawable_groups,
                                             draw_group, group_title,
                                             prepare_group)

FIGURE_WIDTH_IN = 15.0

# THE canonical span panel, in inches: the box the span plot occupies in
# the overlays figure. Every figure for a span measures against this one
# reference, not against its own width.
#
# Otherwise "the true ratio in the recording" would be a property of
# whichever figure you happened to be looking at - the same ID 3 motif
# reported 4.4:1 on the overlays page and 7.0:1 on the family page, purely
# because those figures are different widths. The ratio is a claim about
# the recording and has to be quoted the same way everywhere.
REFERENCE_SPAN_WIDTH_IN = FIGURE_WIDTH_IN * 0.90
REFERENCE_SPAN_HEIGHT_IN = 2.6


def span_aspect(x, fs, rows):
    """`(aspect, true_ratio, compression)` from the span panel's geometry."""
    x = np.asarray(x, dtype=float)
    span_seconds = len(x) / float(fs)
    span_mv = float(np.ptp(x)) * 1000.0
    return style7.span_locked_aspect(
        span_seconds, span_mv,
        REFERENCE_SPAN_WIDTH_IN, REFERENCE_SPAN_HEIGHT_IN,
        [abs(float(r.get("drop_depth_mv", 0.0))) for r in rows],
        [abs(float(r.get("fall_duration_s", 0.0))) for r in rows])


def plot_span_and_overlays(x, fs, span_offset, rows, snippets, summary,
                           out_path, band_labels=()):
    """Span on top, one row per family beneath, all at the span's scale."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    groups, dropped = drawable_groups(rows)
    hues = assign_hues([k for k, _ in groups])
    aspect, true_ratio, compression = span_aspect(x, fs, rows)
    n_rows = len(groups)

    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, 4.4 + 3.8 * n_rows))
    grid = fig.add_gridspec(n_rows + 1, 2,
                            height_ratios=[1.10] + [1.0] * n_rows,
                            hspace=0.52, wspace=0.30)

    ax_span = fig.add_subplot(grid[0, :])
    _span_panel(ax_span, x, fs, span_offset, groups, hues, snippets)

    for i, ((sign, band), members) in enumerate(groups):
        hue = hues[(sign, band)]
        pure = [r for r in members if int(r.get("is_pure", 1))] or members

        left = fig.add_subplot(grid[i + 1, 0])
        shape = prepare_group(pure, snippets, hue, baseline_removed=True,
                              inverted=sign < 0)
        # ONE scale for every family, because it is the recording's scale
        # and not a per-family convenience: two families drawn at two
        # scales cannot be compared to each other or to the span above.
        draw_group(left, shape, aspect)
        left.set_ylabel("mV, detrended,\nbaseline removed")
        left.set_xlabel("time from onset (s)")
        left.set_title(group_title(sign, band, band_labels, len(pure),
                                   shape["n_outliers"] if shape else 0,
                                   shape["hue_name"] if shape else ""),
                       fontsize=9)

        right = fig.add_subplot(grid[i + 1, 1])
        kept = prepare_group(members, snippets, hue, baseline_removed=False,
                             field=RECORDED_FIELD, inverted=sign < 0)
        draw_group(right, kept, None, show_zero=False)
        right.set_ylabel("mV, as recorded")
        right.set_xlabel("time from onset (s)")
        n_impure = sum(1 for r in members if not int(r.get("is_pure", 1)))
        right.set_title(
            f"all windows, n={len(members)}  ·  baseline kept"
            + (f"  ·  {n_impure} impure dashed" if n_impure else "")
            + "\ncontext view — not shape-locked",
            fontsize=8.5)

        if shape is not None and shape["norm"] is not None:
            bar = fig.colorbar(cm.ScalarMappable(norm=shape["norm"],
                                                 cmap=shape["cmap"]),
                               ax=left, fraction=0.040, pad=0.02)
            bar.set_label("onset (h)", fontsize=7.5)
            bar.ax.tick_params(labelsize=6.5)

    kept_counts = summary.get("per_pass_kept", {})
    passes = ", ".join(f"{passes7.PASS_LABELS[k]} {v}"
                       for k, v in kept_counts.items() if v)
    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']}  ·  n={len(rows)} motifs"
        f" in {n_rows} famil{'ies' if n_rows != 1 else 'y'}"
        f"  ·  one hue per family\n"
        + (f"passes: {passes}\n" if passes else "")
        + style7.fidelity_caption(true_ratio, compression)
        + "; every family panel shares the span plot's own scale"
        + (f"  ·  {dropped} single-member famil"
           f"{'ies' if dropped != 1 else 'y'} not shown" if dropped else "")
        + f"\n{str(summary.get('note',''))[:110]}",
        fontsize=10.5, y=0.997)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def plot_family_overlay(x, fs, rows, snippets, summary, out_path,
                        band_labels=()):
    """The family overlays alone, larger, all at the span's own scale."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    pure = [r for r in rows if int(r.get("is_pure", 1))] or rows
    groups, dropped = drawable_groups(pure)
    hues = assign_hues([k for k, _ in groups])

    n = len(groups)
    cols = min(n, 2)
    grid_rows = int(np.ceil(n / cols))
    width = 8.2 * cols
    aspect, true_ratio, compression = span_aspect(x, fs, pure)

    fig = plt.figure(figsize=(width, 5.4 * grid_rows))
    grid = fig.add_gridspec(grid_rows, cols, hspace=0.46, wspace=0.32)

    for i, ((sign, band), members) in enumerate(groups):
        ax = fig.add_subplot(grid[i // cols, i % cols])
        group = prepare_group(members, snippets, hues[(sign, band)],
                              baseline_removed=True, inverted=sign < 0)
        draw_group(ax, group, aspect)
        ax.set_xlabel("time from onset (s)")
        ax.set_ylabel("mV, detrended, baseline removed")
        ax.set_title(group_title(sign, band, band_labels, len(members),
                                 group["n_outliers"] if group else 0,
                                 group["hue_name"] if group else ""),
                     fontsize=9.5)
        if group is not None and group["norm"] is not None:
            bar = fig.colorbar(cm.ScalarMappable(norm=group["norm"],
                                                 cmap=group["cmap"]),
                               ax=ax, fraction=0.040, pad=0.02)
            bar.set_label("onset (h)", fontsize=7.5)
            bar.ax.tick_params(labelsize=6.5)

    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']} — motif families"
        f"  ·  one hue per family  ·  amplitude NOT normalised\n"
        + style7.fidelity_caption(true_ratio, compression)
        + (f"  ·  {dropped} single-member family not shown" if dropped else ""),
        fontsize=11)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
