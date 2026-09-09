"""
clusterfigs8.py
================
drop_motifs8. The per-span dendrogram is `clusterfigs73`'s, called with
`orient_rises_as_drops=False`. What is new here is the pooled pair and a
correction to the rose that the orientation change forced.

1. THE ROSE HAS TWO QUADRANTS WHEN THERE ARE RISES
--------------------------------------------------
The rose was built for falls: its axis runs -90 to 0 degrees and every
angle is `arctan(slope / reference)` of a NEGATIVE slope. A rise's slope
is positive, so its angle was positive, so `np.digitize` clamped it into
the last bin and every inverted motif was drawn at 0 degrees regardless of
how steep it was. Visible on the drop_motifs7.3 ID 22 rose as two short
bars, orange and pink, pinned against the top edge.

Now a rise points up and to the right, at its own steepness, measured the
same way a fall is: the snippet is negated, the vetted `fall_gradients` is
run on it, and the resulting angle is flipped back for display. The
circular statistics stay over the FALLS alone - "mean fall gradient" is
what they mean, and averaging a population of falls with a population of
rises would produce a number describing neither.

2. THE POOLED PAGE
------------------
One tree over every pure motif in the catalogue, A4, with no per-leaf
strip - at several hundred leaves a thumbnail is under a millimetre - and
TWO rows of family overlays sitting on the tree, at two different cuts.
The upper row is the coarse cut, the lower the fine one, so the page shows
both how few kinds there are and what each kind splits into.

Pooled panels cannot use "the recording's scale", because there are
sixteen recordings and their millivolt-per-second differs by three orders
of magnitude. One pooled scale was tried and collapsed five of the eight
fine-cut panels to vertical hairlines - the same failure
`overlays7.group_aspect` records. Each panel is locked to ITS OWN
family's scale instead, at a readable proportion, and the figure says so:
shape is comparable within a panel, not across the row.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style7, style73, style8
from Pipelines.drop_motifs.clusterfigs6 import (_contiguous_blocks, _medoid,
                                                choose_family_count)
from Pipelines.drop_motifs.clusterfigs7 import (COPHENETIC_FLOOR, _composition,
                                                _cut_height, _leaves_under,
                                                _waveform_of)
from Pipelines.drop_motifs.clusterfigs72 import PAGE_HEIGHT_IN, PAGE_WIDTH_IN
from Pipelines.drop_motifs.clusterfigs73 import _ranked_axis  # noqa: F401
from Pipelines.drop_motifs.clusterfigs73 import plot_dendrogram_page  # noqa: F401
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

# The two cuts drawn on the pooled page.
POOLED_COARSE_MAX = 5
POOLED_FINE_MAX = 10

COARSE_BOX_H = 0.088
FINE_BOX_H = 0.072

# Clear space between the two rows of panels, as a fraction of the page.
ROW_GAP = 0.012

# A family with fewer members than this is counted, not drawn.
MIN_PANEL_MEMBERS = 2


def _sign_of(row):
    return int(row.get("signal_sign", 1))


def _oriented_snippets(rows, snippets, field="detrended_mv"):
    """A copy of `snippets` with every rise negated.

    Used only to MEASURE a rise the way a fall is measured. The store is
    never touched: it holds the signal as recorded, which is the one thing
    a motif library must not lie about.
    """
    rise_ids = {r["event_id"] for r in rows if _sign_of(r) < 0}
    if not rise_ids:
        return snippets, rise_ids
    out = {}
    for key, arrays in snippets.items():
        if key in rise_ids:
            arrays = dict(arrays)
            arrays[field] = -np.asarray(arrays[field], dtype=float)
        out[key] = arrays
    return out, rise_ids


# ===========================================================================
# the rose
# ===========================================================================

def plot_rose(rows, snippets, out_path, *, title, excluded=0,
              field="max_slope_mv_s", scale="raw", n_bins=18,
              colour_by="family"):
    """Gradient rose. Falls point down-right, rises up-right.

    `colour_by="span"` colours each motif by its catalogue ID and legends
    it, which is what the pooled rose needs; `"family"` keeps the per-span
    scheme where colour is the family hue and position in the span.
    """
    if not rows:
        return None, {"reason": "no motifs"}
    style7.apply_style()

    measured, rise_ids = _oriented_snippets(rows, snippets)
    data = dg.rose_data(rows, measured, scale=scale, field=field,
                        split_by="span_key")
    if not data["n"]:
        return None, {"reason": "no gradients computable"}

    from Pipelines.drop_motifs.overlays7 import assign_hues, group_key

    gradients = data["gradients"]
    by_id = {r["event_id"]: r for r in rows}
    members = [by_id.get(g.get("event_id")) for g in gradients]

    # Flip the rises back: measured as falls, drawn as rises.
    angles = np.asarray(data["angles"], dtype=float).copy()
    is_rise = np.array([g.get("event_id") in rise_ids for g in gradients])
    angles[is_rise] = -angles[is_rise]

    keys = sorted({group_key(m) for m in members if m},
                  key=lambda k: (-k[0], k[1]))
    hues = assign_hues(keys)
    span_ids = sorted({int(m["catalogue_id"]) for m in members if m})
    span_colour = style8.span_colours(span_ids)

    colours = []
    for m in members:
        if m is None:
            colours.append("0.6")
        elif colour_by == "span":
            colours.append(span_colour[int(m["catalogue_id"])])
        else:
            sign, band = group_key(m)
            _, cmap = style7.family_ramp(hues[(sign, band)], inverted=sign < 0)
            same = [x["onset_h"] for x in members
                    if x and group_key(x) == (sign, band)]
            low, high = min(same), max(same)
            frac = 0.5 if high <= low else (m["onset_h"] - low) / (high - low)
            colours.append(cmap(0.15 + 0.75 * frac))

    any_rise = bool(is_rise.any())
    lo = -np.pi / 2
    hi = np.pi / 2 if any_rise else 0.0
    bins = n_bins * 2 if any_rise else n_bins
    edges = np.linspace(lo, hi, bins + 1)
    width = float(edges[1] - edges[0])
    which = np.clip(np.digitize(angles, edges) - 1, 0, bins - 1)

    fig = plt.figure(figsize=(10.4, 9.2))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    ax.set_thetamin(np.rad2deg(lo))
    ax.set_thetamax(np.rad2deg(hi))

    order = np.argsort([m["onset_h"] if m else 0 for m in members])
    heights = np.zeros(bins)
    for i in order:
        b = int(which[i])
        ax.bar(float(edges[b]) + width / 2.0, 1.0, width=width * 0.92,
               bottom=heights[b], color=colours[i], edgecolor="white",
               linewidth=0.5, zorder=3)
        heights[b] += 1.0

    peak = float(heights.max()) if heights.size else 1.0

    # -- the mean of the FALLS, on its own ray -----------------------------
    falls = angles[~is_rise]
    mean_deg = (float(np.rad2deg(dg.circular_mean(falls))) if falls.size
                else float("nan"))
    resultant = dg.resultant_length(falls) if falls.size else float("nan")
    label_radius = peak
    if np.isfinite(mean_deg):
        theta, radius, label_theta, label_radius, rotation = \
            style73.mean_marker(mean_deg, peak)
        ax.plot([theta, theta], [0.0, radius], color=style7.MEAN_COLOUR,
                lw=2.4 * style7.LW, zorder=5, solid_capstyle="round")
        ax.plot([theta], [radius], marker="o", markersize=8.0,
                color=style7.MEAN_COLOUR, markeredgecolor="white",
                markeredgewidth=1.2, zorder=6, clip_on=False)
        ax.text(label_theta, label_radius, f"  mean fall {mean_deg:.1f}°",
                rotation=rotation, rotation_mode="anchor", ha="left",
                va="center", fontsize=10, fontweight="bold",
                color=style7.MEAN_COLOUR, zorder=7, clip_on=False,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8,
                          pad=1.5))

        def _theta_label(value, _):
            degrees = ((np.rad2deg(value) + 180.0) % 360.0) - 180.0
            if abs(degrees - mean_deg) < 9.0:
                return ""
            return f"{degrees:.0f}°"

        ax.xaxis.set_major_formatter(FuncFormatter(_theta_label))

    ax.set_rlabel_position(-95)
    ax.set_ylim(0, max(label_radius * 1.06, 1.0))
    ax.grid(alpha=0.3, lw=style7.LW_RULE * 0.6)

    if colour_by == "span":
        handles = style8.span_legend_handles(span_ids, span_colour)
        legend_title = "catalogue ID"
        ncol = 2 if len(handles) > 8 else 1
        # Outside the axes: a sixteen-entry legend inside the quadrant
        # lands on the mean's own label, which is the one annotation on
        # the figure that has to stay legible.
        ax.legend(handles=handles, loc="center left",
                  bbox_to_anchor=(1.06, 0.5), bbox_transform=ax.transAxes,
                  fontsize=8.5, frameon=True, framealpha=0.9,
                  edgecolor="0.8", title=legend_title, title_fontsize=9,
                  ncol=ncol)
        handles = []
    else:
        handles = [plt.Line2D([0], [0], color=style7.family_ramp(
            hues[k], inverted=k[0] < 0)[1](0.7), lw=6,
            label=("drops" if k[0] > 0 else "rises") + f" band {k[1] + 1}")
            for k in keys]
        legend_title, ncol = "family", 1
    if handles:
        ax.legend(handles=handles, loc="lower right",
                  bbox_to_anchor=(1.04, 0.0), bbox_transform=ax.transAxes,
                  fontsize=8.5, frameon=True, framealpha=0.85,
                  edgecolor="0.8", title=legend_title, title_fontsize=9,
                  ncol=ncol)

    n_rise = int(is_rise.sum())
    ax.set_title(
        f"{title}\nn={data['n']} motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + (f"  ·  {n_rise} rises drawn above the axis" if n_rise else "")
        + f"  ·  mean fall {mean_deg:.1f}°  ·  R={resultant:.3f}\n"
        f"angle = gradient, {data['caption']}"
        f"  ·  radius = motif count, one segment per motif"
        + ("  ·  statistics over the falls only" if n_rise else ""),
        fontsize=9.5, pad=26)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": int(data["n"]),
        "n_rises": n_rise,
        "excluded": int(excluded),
        "mean_fall_deg": float(mean_deg),
        "resultant_length": float(resultant),
        "colour_by": colour_by,
    }


# ===========================================================================
# the pooled dendrogram
# ===========================================================================

def _pooled_family_aspect(members, keep):
    """This family's own millivolt-per-second, at a readable proportion.

    Per family, not per figure: the pooled set holds 0.1 mV micro-spikes
    from ID 385 beside 98 mV sharkfins from ID 24, and one scale that
    renders either renders the other as a line.
    """
    return style7.seconds_per_mv(
        [abs(float(keep[i].get("drop_depth_mv", 0.0))) for i in members],
        [abs(float(keep[i].get("fall_duration_s", 0.0))) for i in members],
        target=style8.READABLE_RATIO)


def _family_panel(fig, rect, members, keep, snippets, features, cmap,
                  aspect, label, fontsize):
    """One overlaid family, in a box of exactly `rect`.

    `aspect` is ignored when the family can supply its own - see
    `_pooled_family_aspect`. Passing one figure-wide scale was tried first
    and collapsed five of the eight fine-cut panels to vertical hairlines,
    which is the same failure `overlays7.group_aspect` records: pooled
    across sixteen recordings the millivolt-per-second differs by a
    thousand, and no single number renders them all.
    """
    traces, onsets, depths = [], [], []
    for leaf in members:
        row = keep[leaf]
        arrays = snippets.get(row["event_id"])
        if arrays is None:
            continue
        values = np.asarray(arrays["detrended_mv"], dtype=float)
        onset = int(np.clip(int(row["onset_idx"])
                            - int(row["snippet_start_idx"]),
                            0, values.size - 1))
        traces.append(values - style7.baseline_level(values, onset))
        onsets.append(onset)
        depths.append(abs(float(row["drop_depth_mv"])))
    if not traces:
        return None

    stacked, onset_index = style7.uniform_set(traces, onsets)
    fs = float(keep[members[0]]["fs"])
    t = (np.arange(stacked.shape[1]) - onset_index) / fs
    outliers = style7.outlier_mask(np.asarray(depths))
    # Deliberately NOT shape-locked. Two attempts failed and both failed
    # the same way: one pooled scale, and then each family's own scale,
    # each collapsed most panels to vertical hairlines. With a fixed box,
    # `adjustable="datalim"` satisfies an aspect by widening the VIEW, so
    # a panel whose data does not already match its box loses its content
    # into the middle of it. Pooled across sixteen recordings there is no
    # common millivolt-per-second to lock to anyway; the per-span figures
    # are where shape is claimed, and the caption says so.
    aspect = None

    ax = fig.add_axes(rect, zorder=6)
    ax.set_facecolor("white")
    for values, is_outlier in zip(stacked, outliers):
        ax.plot(t, values,
                color=style7.OUTLIER_COLOUR if is_outlier else cmap(0.45),
                lw=style7.LW_FAMILY,
                ls=style7.OUTLIER_DASH if is_outlier else "-",
                alpha=style7.ALPHA_OUTLIER if is_outlier
                else style7.ALPHA_FAMILY, zorder=2)
    ax.plot(t, stacked[_medoid(features, members)], color=cmap(0.88),
            lw=style7.LW_MEDOID, alpha=0.95, zorder=4)
    ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
               lw=style7.LW_RULE * 0.7, alpha=0.55, zorder=1)

    ylim = style7.family_ylim(stacked, ~outliers)
    if ylim:
        ax.set_ylim(*ylim)
    falls = [abs(float(keep[leaf]["fall_duration_s"])) for leaf in members]
    median_fall = float(np.median([f for f in falls if f > 0] or [1.0]))
    ax.set_xlim(max(float(t[0]), -1.5 * median_fall),
                min(float(t[-1]), 4.0 * median_fall))
    for spine in ax.spines.values():
        spine.set_edgecolor(cmap(0.78))
        spine.set_linewidth(1.4 * style7.LW)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    style7.apply_aspect(ax, aspect, adjustable="datalim")
    ax.text(0.04, 0.94, label, transform=ax.transAxes, ha="left", va="top",
            fontsize=fontsize, color=cmap(0.88), fontweight="bold",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.75,
                      pad=1.0))
    return median_fall


def plot_pooled_dendrogram_page(rows, snippets, out_path, *, title,
                                excluded=0, coarse_max=POOLED_COARSE_MAX,
                                fine_max=POOLED_FINE_MAX):
    """One A4 tree over every motif, with family overlays at TWO cuts."""
    if len(rows) < 6:
        return None, {"reason": f"only {len(rows)} motifs pooled"}
    style7.apply_style()

    waveforms, keep = [], []
    for row in rows:
        wave = _waveform_of(row, snippets, orient_rises_as_drops=False)
        if wave is not None:
            waveforms.append(wave)
            keep.append(row)
    if len(keep) < 6:
        return None, {"reason": "fewer than 6 motifs had waveforms"}

    features = dc.feature_matrix(waveforms)
    Z, cophenetic = dc.build_linkage(features)
    n = len(keep)

    coarse_k = choose_family_count(Z, n, max_families=int(coarse_max))
    fine_k = int(min(max(coarse_k * 2, coarse_k + 1), fine_max, n - 1))
    coarse_labels = dc.cut_tree(Z, n_clusters=coarse_k)
    fine_labels = dc.cut_tree(Z, n_clusters=fine_k)
    coarse_cut = _cut_height(Z, coarse_k)
    fine_cut = _cut_height(Z, fine_k)

    # ONE pooled scale. Not any recording's - there are sixteen of them and
    # their millivolt-per-second differs by three orders of magnitude - so
    # it is derived from the pooled median event and captioned as pooled.
    aspect = style7.seconds_per_mv(
        [abs(float(r.get("drop_depth_mv", 0.0))) for r in keep],
        [abs(float(r.get("fall_duration_s", 0.0))) for r in keep],
        target=style8.READABLE_RATIO)

    fig = plt.figure(figsize=(PAGE_WIDTH_IN, PAGE_HEIGHT_IN))
    left, right = 0.092, 0.980
    tree_bottom, tree_top = 0.055, 0.912
    ax_tree = fig.add_axes([left, tree_bottom, right - left,
                            tree_top - tree_bottom])

    def link_colour(node):
        families = {int(coarse_labels[i]) for i in _leaves_under(Z, node, n)}
        if len(families) == 1:
            _, cmap = style7.family_ramp(sorted(families)[0] - 1)
            return matplotlib.colors.to_hex(cmap(0.62))
        return "0.62"

    dendro = dendrogram(Z, orientation="top", ax=ax_tree, no_labels=True,
                        link_color_func=link_colour)
    for line in ax_tree.get_lines():
        line.set_linewidth(style7.LW_TREE * 0.75)
    _ranked_axis(ax_tree, Z[:, 2])

    for cut, dash in ((coarse_cut, "--"), (fine_cut, (0, (5, 3)))):
        ax_tree.axhline(cut, color=style7.RULE_COLOUR, lw=style7.LW_RULE,
                        ls=dash, alpha=0.75)
    ax_tree.set_ylabel("Ward merge distance — ranked axis, real labels",
                       fontsize=9)
    ax_tree.set_xticks([])
    ax_tree.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)

    spans = sorted({int(r["catalogue_id"]) for r in keep})
    ax_tree.set_title(
        f"{title}\nn={n} motifs pooled from {len(spans)} spans"
        + (f", {excluded} impure excluded" if excluded else "")
        + f"  ·  cophenetic r = {cophenetic:.3f}"
        + ("  (below 0.70 — read with caution)"
           if cophenetic < COPHENETIC_FLOOR else "")
        + f"\nupper row: {coarse_k} families at the coarse cut"
          f"  ·  lower row: {fine_k} at the fine cut"
        + "\npanels are NOT shape-locked — pooled over sixteen recordings"
          " there is no common mV per second; see the per-span figures"
          " for true proportion",
        fontsize=10.5, pad=12)

    leaves = dendro["leaves"]
    x_lo, x_hi = ax_tree.get_xlim()

    def leaf_fraction(position):
        x = 5.0 + 10.0 * position
        return left + ((x - x_lo) / (x_hi - x_lo)) * (right - left)

    def cut_fraction(height):
        display = ax_tree.transData.transform((0.0, height))
        return float(fig.transFigure.inverted().transform(display)[1])

    from Pipelines.drop_motifs.clusterfigs72 import _family_positions

    info_rows, skipped_rows, taken = [], [], []
    for labels, cut, box_h, fontsize, name in (
            (coarse_labels, coarse_cut, COARSE_BOX_H, 7.0, "coarse"),
            (fine_labels, fine_cut, FINE_BOX_H, 6.0, "fine")):
        every = _contiguous_blocks([labels[leaf] for leaf in leaves])
        # A panel holding one trace shows no family, and at the fine cut
        # there are always a few. Counted and reported rather than drawn.
        blocks = [b for b in every if b[2] - b[1] >= MIN_PANEL_MEMBERS]
        skipped_rows.append(len(every) - len(blocks))
        if not blocks:
            continue
        box_w = min(0.150, (right - left) / len(blocks) * 0.88)
        centres = [np.mean([leaf_fraction(i) for i in range(start, end)])
                   for _, start, end in blocks]
        placed = _family_positions(centres, box_w, left, right)
        cut_y = float(np.clip(cut_fraction(cut), tree_bottom + box_h / 2.0,
                              tree_top - box_h / 2.0))

        # On a ranked axis the top ten merges occupy a tenth of the height,
        # so a coarse cut at k=5 and a fine one at k=10 land within a few
        # percent of each other and the two rows of panels overlap. The
        # lower row is pushed down until it clears, and a dashed connector
        # says which line it actually belongs to.
        offset = 0.0
        for other_y, other_h in taken:
            need = (box_h + other_h) / 2.0 + ROW_GAP
            if abs(cut_y - other_y) < need:
                offset = (other_y - need) - cut_y
        row_y = float(np.clip(cut_y + offset, tree_bottom + box_h / 2.0,
                              tree_top - box_h / 2.0))
        taken.append((row_y, box_h))

        fig.text(left - 0.012, row_y, f"{name} cut", rotation=90,
                 ha="right", va="center", fontsize=8, color="0.35")

        drawn = []
        for (family, start, end), x_centre in zip(blocks, placed):
            members = [leaves[i] for i in range(start, end)]
            # Coloured by the COARSE family the branch belongs to, so a
            # fine panel is visibly a child of the coarse one above it.
            parent = int(coarse_labels[members[0]])
            _, cmap = style7.family_ramp(parent - 1)
            rect = [x_centre - box_w / 2.0, row_y - box_h / 2.0, box_w, box_h]
            median_fall = _family_panel(
                fig, rect, members, keep, snippets, features, cmap, aspect,
                f"n={len(members)}", fontsize)
            if median_fall is None:
                continue
            own = float(np.mean([leaf_fraction(i)
                                 for i in range(start, end)]))
            # Back to the branch, and back up to the cut line the panel was
            # pushed away from - both, because either alone leaves the
            # panel claiming a place it is not sitting in.
            if abs(own - x_centre) > 0.004 or abs(offset) > 0.002:
                fig.add_artist(plt.Line2D(
                    [x_centre, own], [row_y + box_h / 2.0, cut_y],
                    transform=fig.transFigure, color=cmap(0.78),
                    lw=style7.LW_RULE * 0.7, alpha=0.7, zorder=5,
                    ls=(0, (3, 2))))
            drawn.append({"family": int(family), "n": len(members),
                          "median_fall_s": median_fall,
                          "spans": sorted({int(keep[i]["catalogue_id"])
                                           for i in members})})
        info_rows.append(drawn)

    fig.savefig(out_path, dpi=170)
    plt.close(fig)

    return str(out_path), {
        "n": n,
        "excluded": int(excluded),
        "spans": spans,
        "singleton_families_not_drawn": skipped_rows,
        "cophenetic_r": float(cophenetic),
        "coarse_k": int(coarse_k),
        "fine_k": int(fine_k),
        "pooled_aspect_seconds_per_mv": float(aspect),
        "coarse_families": info_rows[0] if info_rows else [],
        "fine_families": info_rows[1] if len(info_rows) > 1 else [],
        "composition": _composition(keep, coarse_labels),
    }
