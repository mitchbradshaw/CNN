"""
overlays6.py
=============
The span figure and the motif overlays, with the drop_motifs5 review's
corrections applied.

    idNNN_overlays.png   the whole span on top; below it one ROW PER
                         SCALE BAND, each row a baseline-removed overlay
                         beside an as-recorded one
    idNNN_overlay.png    the family overlay alone, larger

What changed from drop_motifs5, and why each change was needed
--------------------------------------------------------------
ALIGNMENT. drop_motifs5 subtracted `values[onset]` - the single sample at
the onset index - so every trace was shifted by that one sample's noise.
On catalogue ID 8 four traces then started at four visibly different
heights in a panel captioned "every drop starts at y=0". The baseline is
now the median of the flat run before the drop (`style6.baseline_level`).

ONE WINDOW LENGTH. The detector brackets each event on its own UP runs,
so every window is a different length and an overlay of them was a set of
traces stopping at different places for reasons unrelated to the motif.
Every set is now cut to the smallest common extent about the onset
(`style6.uniform_set`), which is the operator's own prescription: detect
as normal, then cut to the shortest, keeping the drops aligned.

ONE PANEL PER SCALE. ID 24 and ID 34 were unreadable because motifs an
order of magnitude apart in duration shared one axis. Rows are now scale
bands, and a band is only created where the spread warrants it.

FALLS AND RISES ARE NEVER MIXED. The inverted pass finds events that go
the other way. Drawing those on the same axes as the drops would be a
figure of two different phenomena claiming to be one family, so direction
splits a row just as scale does.

OUTLIERS DO NOT SET THE SCALE. Flagged on drop depth by a robust MAD
score, drawn de-emphasised, and allowed to run off the axes - the limits
come from the inliers alone (`style6.family_ylim`). Nothing is dropped:
the count is stated on the panel.

COLOUR. The time ramp is blue-green. The previous ramp was `plasma`,
which ends in the yellow this report may not use.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm

from Pipelines.drop_motifs import passes6, style6


def group_key(row):
    """`(sign, band)` - the two axes a set of motifs must not be mixed on."""
    return int(row.get("signal_sign", 1)), int(row.get("scale_band", 0))


def group_title(sign, band, labels, n, n_out):
    direction = "drops" if sign > 0 else "rises (inverted pass)"
    label = labels[band] if band < len(labels) else "all scales"
    title = f"{direction}  ·  {label}  ·  n={n}"
    if n_out:
        title += f"  ·  {n_out} outlier{'s' if n_out > 1 else ''} off-scale"
    return title


# Which stored array each panel draws.
#
# The SHAPE panels draw `detrended_mv` and the as-recorded panel draws
# `raw_mv`, and the split is not cosmetic. `drop_depth_mv` is measured on
# the detrended signal (`detect5` line 631), and so are the slope gate,
# the purity metric and therefore the outlier flag. Drawing raw millivolts
# in a panel whose caption quotes those numbers puts the picture and the
# figures it is captioned with on two different signals - which on ID 385
# showed as a panel of "drops" every one of which rose, because the slow
# trend the detector had removed was still in the drawn trace.
SHAPE_FIELD = "detrended_mv"
RECORDED_FIELD = "raw_mv"


def prepare_group(rows, snippets, *, baseline_removed, field=SHAPE_FIELD):
    """One group of motifs, ready to draw.

    Returns a dict with the stacked array (every row on ONE common window,
    onsets in the same column), the per-motif colours, the outlier mask
    and the y-limits computed from the inliers.
    """
    traces, onsets, depths, keep = [], [], [], []
    for row in rows:
        arrays = snippets.get(row["event_id"])
        if arrays is None:
            continue
        values = np.asarray(arrays[field], dtype=float)
        if values.size < 3:
            continue
        # The inverted pass stored the signal as recorded; negate for
        # display so a rise is compared against a drop as a shape rather
        # than as a mirror image. The panel title says which it is.
        if int(row.get("signal_sign", 1)) < 0:
            values = -values
        onset = int(row["onset_idx"]) - int(row["snippet_start_idx"])
        onset = int(np.clip(onset, 0, values.size - 1))

        if baseline_removed:
            values = values - style6.baseline_level(values, onset)

        traces.append(values)
        onsets.append(onset)
        depths.append(abs(float(row.get("drop_depth_mv", 0.0))))
        keep.append(row)

    if not traces:
        return None

    stacked, onset_index = style6.uniform_set(traces, onsets)
    fs = float(keep[0]["fs"])
    t = (np.arange(stacked.shape[1]) - onset_index) / fs

    outliers = style6.outlier_mask(np.asarray(depths))
    ylim = style6.family_ylim(stacked, ~outliers)
    colours, norm = style6.time_colours([r["onset_h"] for r in keep])

    return {"rows": keep, "stacked": stacked, "t": t, "onset_index": onset_index,
            "outliers": outliers, "ylim": ylim, "colours": colours,
            "norm": norm, "n_outliers": int(outliers.sum())}


def draw_group(ax, group, *, show_zero=True):
    """Draw one prepared group onto one axes."""
    if group is None:
        ax.text(0.5, 0.5, "no motifs", transform=ax.transAxes,
                ha="center", va="center", color="0.5")
        return 0

    t = group["t"]
    for values, colour, row, is_outlier in zip(
            group["stacked"], group["colours"], group["rows"],
            group["outliers"]):
        pure = bool(int(row.get("is_pure", 1)))
        if is_outlier:
            # Drawn, so nothing is hidden; de-emphasised and clipped by
            # the inlier limits, so it cannot squash the family.
            ax.plot(t, values, color=style6.OUTLIER_COLOUR,
                    lw=style6.LW_OUTLIER, alpha=style6.ALPHA_OUTLIER,
                    zorder=2)
        elif not pure:
            ax.plot(t, values, color=style6.IMPURE_COLOUR,
                    lw=style6.LW_OUTLIER, alpha=0.5, zorder=2)
        else:
            ax.plot(t, values, color=colour, lw=style6.LW_TRACE,
                    alpha=style6.ALPHA_TRACE, zorder=3)

    ax.axvline(0.0, color=style6.RULE_COLOUR, ls="--", lw=style6.LW_RULE,
               alpha=0.7, zorder=1)
    if show_zero:
        ax.axhline(0.0, color=style6.RULE_COLOUR, ls=":",
                   lw=style6.LW_RULE * 0.8, alpha=0.6, zorder=1)
    if group["ylim"]:
        ax.set_ylim(*group["ylim"])
    ax.set_xlim(float(t[0]), float(t[-1]))
    ax.grid(alpha=0.18, lw=style6.LW_RULE * 0.5)
    return len(group["rows"])


def _span_panel(ax, x, fs, span_offset, rows, colours):
    """The whole span, every window shaded where it sits."""
    t_h = (np.arange(len(x)) + span_offset) / fs / 3600.0
    ax.plot(t_h, np.asarray(x) * 1000.0, lw=style6.LW_SIGNAL,
            color=style6.SIGNAL_COLOUR, zorder=2)

    for row, colour in zip(rows, colours):
        start = int(row["snippet_start_idx"]) - span_offset
        end = int(row["snippet_end_idx"]) - span_offset
        lo = t_h[int(np.clip(start, 0, len(t_h) - 1))]
        hi = t_h[int(np.clip(end - 1, 0, len(t_h) - 1))]
        pure = bool(int(row.get("is_pure", 1)))
        inverted = int(row.get("signal_sign", 1)) < 0
        ax.axvspan(lo, hi,
                   color=(colour if pure else style6.IMPURE_COLOUR),
                   alpha=(0.13 if pure else 0.20),
                   hatch="///" if inverted else None,
                   lw=0, zorder=1)

    ax.set_xlabel("time in recording (h)")
    ax.set_ylabel("amplitude (mV, raw)")
    ax.margins(x=0.005)
    ax.grid(alpha=0.18, lw=style6.LW_RULE * 0.5)


def plot_span_and_overlays(x, fs, span_offset, rows, snippets, summary,
                           out_path, band_labels=()):
    """The span figure: whole span on top, one row per (direction, band)."""
    if not rows:
        return None
    style6.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    groups = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)
    # Falls before rises, fine scales before coarse.
    order = sorted(groups, key=lambda k: (-k[0], k[1]))

    n_rows = len(order)
    fig = plt.figure(figsize=(14.5, 4.6 + 3.4 * n_rows))
    grid = fig.add_gridspec(n_rows + 1, 2,
                            height_ratios=[1.15] + [1.0] * n_rows,
                            hspace=0.42, wspace=0.17)

    all_colours, norm = style6.time_colours([r["onset_h"] for r in rows])
    ax_span = fig.add_subplot(grid[0, :])
    _span_panel(ax_span, x, fs, span_offset, rows, all_colours)

    for i, key in enumerate(order):
        sign, band = key
        members = groups[key]
        pure = [r for r in members if int(r.get("is_pure", 1))]

        left = fig.add_subplot(grid[i + 1, 0])
        group = prepare_group(pure or members, snippets, baseline_removed=True)
        draw_group(left, group)
        left.set_ylabel("amplitude (mV,\nbaseline removed)")
        left.set_xlabel("time from onset (s)")
        left.set_title(
            group_title(sign, band, band_labels, len(pure or members),
                        group["n_outliers"] if group else 0)
            + "  ·  detrended, aligned on the flat run before the drop",
            fontsize=9)

        right = fig.add_subplot(grid[i + 1, 1])
        group_raw = prepare_group(members, snippets, baseline_removed=False,
                                  field=RECORDED_FIELD)
        draw_group(right, group_raw, show_zero=False)
        right.set_ylabel("amplitude (mV,\nas recorded)")
        right.set_xlabel("time from onset (s)")
        n_impure = sum(1 for r in members if not int(r.get("is_pure", 1)))
        right.set_title(
            f"all windows, n={len(members)}  ·  baseline kept"
            + (f"  ·  {n_impure} impure drawn red" if n_impure else ""),
            fontsize=9)

    if norm is not None:
        bar = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=style6.TIME_CMAP),
                           ax=fig.get_axes(), fraction=0.018, pad=0.015)
        bar.set_label("onset time in recording (h)", fontsize=8)
        bar.ax.tick_params(labelsize=7)

    per_pass = summary.get("per_pass_kept", {})
    passes = ", ".join(f"{passes6.PASS_LABELS[k]} {v}"
                       for k, v in per_pass.items() if v)
    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']}  ·  {summary.get('morphology','')}"
        f"  ·  n={len(rows)} motifs over {n_rows} panel"
        f"{'s' if n_rows > 1 else ''}\n"
        + (f"passes: {passes}\n" if passes else "")
        + f"{str(summary.get('note',''))[:110]}",
        fontsize=11, y=0.995)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def plot_family_overlay(rows, snippets, summary, out_path, band_labels=()):
    """The overlay alone, one panel per (direction, band), drawn larger."""
    if not rows:
        return None
    style6.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    pure = [r for r in rows if int(r.get("is_pure", 1))]
    groups = {}
    for row in (pure or rows):
        groups.setdefault(group_key(row), []).append(row)
    order = sorted(groups, key=lambda k: (-k[0], k[1]))

    n = len(order)
    cols = min(n, 2)
    grid_rows = int(np.ceil(n / cols))
    fig = plt.figure(figsize=(7.6 * cols, 5.0 * grid_rows))
    grid = fig.add_gridspec(grid_rows, cols, hspace=0.38, wspace=0.20)

    for i, key in enumerate(order):
        sign, band = key
        ax = fig.add_subplot(grid[i // cols, i % cols])
        group = prepare_group(groups[key], snippets, baseline_removed=True)
        draw_group(ax, group)
        ax.set_xlabel("time from onset (s)")
        ax.set_ylabel("amplitude (mV, baseline removed)")
        ax.set_title(group_title(sign, band, band_labels, len(groups[key]),
                                 group["n_outliers"] if group else 0),
                     fontsize=10)

    _, norm = style6.time_colours([r["onset_h"] for r in (pure or rows)])
    if norm is not None:
        bar = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=style6.TIME_CMAP),
                           ax=fig.get_axes(), fraction=0.02, pad=0.015)
        bar.set_label("onset time in recording (h)", fontsize=8)

    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']} — motif families"
        f"  ·  every trace aligned on the flat run before its drop"
        f"  ·  one common window  ·  amplitude NOT normalised",
        fontsize=11)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
