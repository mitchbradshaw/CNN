"""
clusterfigs73.py
=================
drop_motifs7.3's dendrogram page and rose. The layout is 7.2's - A4, tree
down the length, family overlays sitting on the tree at the cut, motifs
along the bottom - and two things change.

1. THE MERGE-DISTANCE AXIS IS RANKED
------------------------------------
Ward distances are strongly right-skewed. On catalogue ID 22 the root
merge sits at about 22 and every other merge below 3, so a linear axis
spent most of an A4 page drawing one link, put the family panels down in
the bottom quarter, and left a field of white space above them - which is
what the operator saw.

`style73.rank_scale_functions` gives every merge a share of the height,
blended with the linear map so a near merge still looks nearer than a far
one. The axis is no longer proportional, so it is tick-labelled with real
merge heights instead of a regular grid, and its label says so.

The cut line, and therefore the family panels, are positioned through
`transData`, so they follow the new scale without being told about it.

2. THE ROSE'S MEAN IS ON THE ROSE
---------------------------------
It was a legend key: a horizontal swatch in the bottom-left corner reading
"mean -9.2 degrees". A horizontal swatch cannot express an angle, and on
ID 22 it was not drawn at all - the family legend was built with a second
`ax.legend()` call, which REPLACES the first rather than adding to it, so
the mean's label was silently discarded.

The mean is now a ray, a marker and a label at the mean angle, and the one
remaining legend is the family legend.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, FuncFormatter
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style7, style73
from Pipelines.drop_motifs.clusterfigs6 import (MAX_FAMILIES,
                                                _contiguous_blocks, _medoid,
                                                choose_family_count)
from Pipelines.drop_motifs.clusterfigs7 import (COPHENETIC_FLOOR, _aligned,
                                                _composition, _cut_height,
                                                _leaves_under, _waveform_of)
from Pipelines.drop_motifs.clusterfigs72 import (FAMILY_BOX_H,
                                                 MAX_FAMILY_BOX_W,
                                                 MOTIFS_PER_FAMILY,
                                                 PAGE_HEIGHT_IN, PAGE_WIDTH_IN,
                                                 THUMBNAIL_LIMIT,
                                                 _family_positions)
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

# Headroom above the root merge, as a fraction of the tree's drawn height.
# In display space, not data space - on a ranked axis the two are no
# longer the same thing, and it is the display gap that has to clear the
# top of the axes.
TREE_HEADROOM = 0.06


def _ranked_axis(ax, heights):
    """Put `ax` on the ranked merge-distance scale and label it honestly."""
    forward, inverse = style73.rank_scale_functions(heights)
    ax.set_yscale("function", functions=(forward, inverse))

    top = float(np.max(heights))
    low, high = forward(np.array([0.0])), forward(np.array([top]))
    padded = high[0] + TREE_HEADROOM * (high[0] - low[0])
    ax.set_ylim(0.0, float(inverse(np.array([padded]))[0]))

    ticks = style73.merge_ticks(heights)
    if ticks:
        ax.yaxis.set_major_locator(FixedLocator(ticks))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2g}"))
    return forward, inverse


def plot_dendrogram_page(rows, snippets, out_path, *, title, excluded=0,
                         max_families=MAX_FAMILIES, span_aspect=None,
                         true_ratio=float("nan"), compression=1.0):
    """The A4 page, with the tree spread over a ranked distance axis."""
    if len(rows) < 3:
        return None, {"reason": f"only {len(rows)} motifs; a tree needs 3"}
    style7.apply_style()

    waveforms, keep = [], []
    for row in rows:
        wave = _waveform_of(row, snippets)
        if wave is not None:
            waveforms.append(wave)
            keep.append(row)
    if len(keep) < 3:
        return None, {"reason": "fewer than 3 motifs had waveforms"}

    features = dc.feature_matrix(waveforms)
    Z, cophenetic = dc.build_linkage(features)
    n = len(keep)

    high_k = choose_family_count(
        Z, n, max_families=min(int(max_families),
                               max(3, n // MOTIFS_PER_FAMILY)))
    high_labels = dc.cut_tree(Z, n_clusters=high_k)
    high_cut = _cut_height(Z, high_k)

    aspect = span_aspect if span_aspect else 1.0

    fig = plt.figure(figsize=(PAGE_WIDTH_IN, PAGE_HEIGHT_IN))
    # Wider than 7.2's 0.070: without `bbox_inches="tight"` - which would
    # undo the A4 proportions this page is for - the y label has to be
    # given its room rather than allowed to grow into the margin.
    left, right = 0.092, 0.980
    box_w = min(MAX_FAMILY_BOX_W, (right - left) / high_k * 0.94)
    motif_bottom, motif_top = 0.045, 0.205
    thumbnails = n <= THUMBNAIL_LIMIT
    # Past the thumbnail limit the strip is dropped, and in 7.2 its band
    # was left empty - ID 10, at 113 motifs, spent the bottom third of an
    # A4 page on nothing. The tree takes the room instead.
    tree_bottom = 0.235 if thumbnails else motif_bottom
    tree_top = 0.930

    ax_tree = fig.add_axes([left, tree_bottom, right - left,
                            tree_top - tree_bottom])

    def link_colour(node):
        families = {int(high_labels[i]) for i in _leaves_under(Z, node, n)}
        if len(families) == 1:
            _, cmap = style7.family_ramp(sorted(families)[0] - 1)
            return matplotlib.colors.to_hex(cmap(0.62))
        return "0.62"

    dendro = dendrogram(Z, orientation="top", ax=ax_tree, no_labels=True,
                        link_color_func=link_colour)
    for line in ax_tree.get_lines():
        line.set_linewidth(style7.LW_TREE)

    # Applied AFTER the tree is drawn: every link is either a vertical or a
    # horizontal segment, so a monotone map of y moves the vertices without
    # bending anything between them.
    _ranked_axis(ax_tree, Z[:, 2])

    ax_tree.axhline(high_cut, color=style7.RULE_COLOUR, lw=style7.LW_RULE,
                    ls="--", alpha=0.8)
    ax_tree.set_ylabel("Ward merge distance — ranked axis, real labels",
                       fontsize=9)
    ax_tree.set_xticks([])
    ax_tree.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)
    ax_tree.set_title(
        f"{title}\nn={n} motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + f"  ·  {high_k} families at the dashed cut"
        f"  ·  cophenetic r = {cophenetic:.3f}"
        + ("  (below 0.70 — read with caution)"
           if cophenetic < COPHENETIC_FLOOR else "")
        + f"\n{style7.fidelity_caption(true_ratio, compression)}"
          f"; every motif below and every family panel shares it",
        fontsize=11, pad=12)

    leaves = dendro["leaves"]
    x_lo, x_hi = ax_tree.get_xlim()

    def leaf_fraction(position):
        """Leaf `position` -> figure x. scipy places leaf i at data
        x = 5 + 10i under `orientation="top"`, left to right."""
        x = 5.0 + 10.0 * position
        return left + ((x - x_lo) / (x_hi - x_lo)) * (right - left)

    # -- the motifs, along the bottom -------------------------------------
    if thumbnails:
        slot = (right - left) / max(n, 1)
        cell = slot * 0.88
        for position, leaf in enumerate(leaves):
            row = keep[leaf]
            _, cmap = style7.family_ramp(int(high_labels[leaf]) - 1)
            ax = fig.add_axes([leaf_fraction(position) - cell / 2.0,
                               motif_bottom, cell, motif_top - motif_bottom])
            t, values = _aligned(row, snippets)
            if t is not None:
                ax.plot(t, values, color=cmap(0.62), lw=style7.LW_TRACE)
            ax.axvline(0.0, color=style7.RULE_COLOUR,
                       lw=style7.LW_RULE * 0.6, alpha=0.45)
            style7.strip_axis(ax)
            style7.apply_aspect(ax, aspect, adjustable="datalim")
            ax.text(0.5, -0.03,
                    f"{abs(float(row['drop_depth_mv'])):.0f}mV\n"
                    f"{float(row['fall_duration_s']):.0f}s"
                    + ("\n↑" if int(row.get("signal_sign", 1)) < 0 else ""),
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=5.8, color="#555555")
        fig.text((left + right) / 2.0, motif_top + 0.004,
                 "each motif, under its own leaf — mV, baseline removed, "
                 "real seconds, shape as in the recording",
                 ha="center", va="bottom", fontsize=9)
    else:
        fig.text((left + right) / 2.0, 0.018,
                 f"per-leaf motif strip omitted: {n} motifs would give each "
                 f"one under 3 mm — see the overlay figure for the shapes",
                 ha="center", va="bottom", fontsize=9, color="0.35")

    # -- the family panels, ON the tree at the cut ------------------------
    blocks = _contiguous_blocks([high_labels[leaf] for leaf in leaves])
    centres = [np.mean([leaf_fraction(i) for i in range(start, end)])
               for _, start, end in blocks]
    placed = _family_positions(centres, box_w, left, right)

    cut_display = ax_tree.transData.transform((0.0, high_cut))
    cut_y = fig.transFigure.inverted().transform(cut_display)[1]
    # The ranked axis lifts the cut towards the top of the page, which is
    # the point - but a panel centred on it must still fit inside the tree.
    cut_y = float(np.clip(cut_y, tree_bottom + FAMILY_BOX_H / 2.0,
                          tree_top - FAMILY_BOX_H / 2.0))

    info_families = []
    for (family, start, end), x_centre in zip(blocks, placed):
        members = [leaves[i] for i in range(start, end)]
        _, cmap = style7.family_ramp(int(family) - 1)

        traces, onsets, depths = [], [], []
        for leaf in members:
            row = keep[leaf]
            arrays = snippets.get(row["event_id"])
            if arrays is None:
                continue
            values = np.asarray(arrays["detrended_mv"], dtype=float)
            if int(row.get("signal_sign", 1)) < 0:
                values = -values
            onset = int(np.clip(int(row["onset_idx"])
                                - int(row["snippet_start_idx"]),
                                0, values.size - 1))
            traces.append(values - style7.baseline_level(values, onset))
            onsets.append(onset)
            depths.append(abs(float(row["drop_depth_mv"])))
        if not traces:
            continue

        stacked, onset_index = style7.uniform_set(traces, onsets)
        fs = float(keep[members[0]]["fs"])
        t = (np.arange(stacked.shape[1]) - onset_index) / fs
        outliers = style7.outlier_mask(np.asarray(depths))

        ax = fig.add_axes([x_centre - box_w / 2.0,
                           cut_y - FAMILY_BOX_H / 2.0,
                           box_w, FAMILY_BOX_H], zorder=6)
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
            spine.set_linewidth(1.5 * style7.LW)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        style7.apply_aspect(ax, aspect, adjustable="datalim")

        ax.text(0.035, 0.94, f"f{family}  n={len(members)}",
                transform=ax.transAxes, ha="left", va="top", fontsize=7.0,
                color=cmap(0.88), fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75,
                          pad=1.0))
        own = float(np.mean([leaf_fraction(i) for i in range(start, end)]))
        if abs(own - x_centre) > 0.004:
            fig.add_artist(plt.Line2D(
                [x_centre, own], [cut_y - FAMILY_BOX_H / 2.0, cut_y],
                transform=fig.transFigure, color=cmap(0.78),
                lw=style7.LW_RULE * 0.8, alpha=0.7, zorder=5))
        info_families.append({"family": int(family), "n": len(members),
                              "median_fall_s": median_fall})

    fig.savefig(out_path, dpi=170)
    plt.close(fig)

    return str(out_path), {
        "n": n,
        "excluded": int(excluded),
        "n_families": int(high_k),
        "cophenetic_r": float(cophenetic),
        "aspect_seconds_per_mv": float(aspect),
        "true_height_to_width": float(true_ratio),
        "shape_compression": float(compression),
        "merge_axis": "ranked",
        "families": info_families,
        "labels": [int(v) for v in high_labels],
        "composition": _composition(keep, high_labels),
    }


# ===========================================================================
# the rose
# ===========================================================================

def plot_rose(rows, snippets, out_path, *, title, excluded=0,
              field="max_slope_mv_s", scale="raw", n_bins=18):
    """Fall-gradient rose, one segment per motif, mean drawn on its ray."""
    if not rows:
        return None, {"reason": "no motifs"}
    style7.apply_style()

    data = dg.rose_data(rows, snippets, scale=scale, field=field,
                        split_by="span_key")
    if not data["n"]:
        return None, {"reason": "no gradients computable"}

    from Pipelines.drop_motifs.overlays7 import assign_hues, group_key

    angles = np.asarray(data["angles"], dtype=float)
    gradients = data["gradients"]
    by_id = {r["event_id"]: r for r in rows}
    members = [by_id.get(g.get("event_id")) for g in gradients]

    keys = sorted({group_key(m) for m in members if m},
                  key=lambda k: (-k[0], k[1]))
    hues = assign_hues(keys)

    colours = []
    for m in members:
        if m is None:
            colours.append("0.6")
            continue
        sign, band = group_key(m)
        _, cmap = style7.family_ramp(hues[(sign, band)], inverted=sign < 0)
        same = [x["onset_h"] for x in members
                if x and group_key(x) == (sign, band)]
        low, high = min(same), max(same)
        frac = 0.5 if high <= low else (m["onset_h"] - low) / (high - low)
        colours.append(cmap(0.15 + 0.75 * frac))

    lo, hi = data["lo"], data["hi"]
    edges = np.linspace(lo, hi, n_bins + 1)
    width = float(edges[1] - edges[0])
    which = np.clip(np.digitize(angles, edges) - 1, 0, n_bins - 1)

    fig = plt.figure(figsize=(9.6, 8.8))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    ax.set_thetamin(-90)
    ax.set_thetamax(0)

    order = np.argsort([m["onset_h"] if m else 0 for m in members])
    heights = np.zeros(n_bins)
    for i in order:
        b = int(which[i])
        ax.bar(float(edges[b]) + width / 2.0, 1.0, width=width * 0.92,
               bottom=heights[b], color=colours[i], edgecolor="white",
               linewidth=0.6, zorder=3)
        heights[b] += 1.0

    peak = float(heights.max()) if heights.size else 1.0

    # -- the mean, on its own ray -----------------------------------------
    theta, radius, label_theta, label_radius, rotation = style73.mean_marker(
        data["mean_deg"], peak)
    ax.plot([theta, theta], [0.0, radius], color=style7.MEAN_COLOUR,
            lw=2.4 * style7.LW, zorder=5, solid_capstyle="round")
    ax.plot([theta], [radius], marker="o", markersize=8.0,
            color=style7.MEAN_COLOUR, markeredgecolor="white",
            markeredgewidth=1.2, zorder=6, clip_on=False)
    ax.text(label_theta, label_radius, f"  mean {data['mean_deg']:.1f}°",
            rotation=rotation, rotation_mode="anchor", ha="left", va="center",
            fontsize=10, fontweight="bold", color=style7.MEAN_COLOUR,
            zorder=7, clip_on=False,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.5))

    # The label runs outward along its ray, straight through wherever the
    # theta tick nearest that angle is printed. Suppressing that one tick
    # is cheaper than moving every other one, and the mean's own label
    # already states the angle the tick would have.
    def _theta_label(value, _):
        degrees = ((np.rad2deg(value) + 180.0) % 360.0) - 180.0
        if abs(degrees - float(data["mean_deg"])) < 9.0:
            return ""
        return f"{degrees:.0f}°"

    ax.xaxis.set_major_formatter(FuncFormatter(_theta_label))

    ax.set_rlabel_position(-95)
    ax.set_ylim(0, max(label_radius * 1.06, 1.0))
    ax.text(np.deg2rad(-96), peak * 0.55, "number of motifs", rotation=90,
            ha="center", va="center", fontsize=9, color="0.3")
    ax.grid(alpha=0.3, lw=style7.LW_RULE * 0.6)

    # ONE legend. 7.2 built two with two `ax.legend()` calls, and the
    # second replaced the first - which is how the mean's label vanished
    # from ID 22 while surviving on ID 3.
    handles = [plt.Line2D([0], [0], color=style7.family_ramp(
        hues[k], inverted=k[0] < 0)[1](0.7), lw=6,
        label=("drops" if k[0] > 0 else "rises") + f" band {k[1] + 1}")
        for k in keys]
    if handles:
        ax.legend(handles=handles, loc="lower right",
                  bbox_to_anchor=(1.02, 0.0), bbox_transform=ax.transAxes,
                  fontsize=8.5, frameon=True, framealpha=0.85,
                  edgecolor="0.8", title="family", title_fontsize=9)

    ax.set_title(
        f"{title}\nn={data['n']} motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + f"  ·  mean {data['mean_deg']:.1f}°"
          f"  ·  R={data['resultant_length']:.3f}"
          f"  ·  circular SD {data['circular_sd_deg']:.1f}°"
          f"  ·  uniformity p={data['uniformity_p']:.1g}\n"
        f"angle = fall gradient, {data['caption']}"
        f"  ·  radius = motif count, one segment per motif",
        fontsize=9.5, pad=26)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": int(data["n"]),
        "excluded": int(excluded),
        "mean_deg": float(data["mean_deg"]),
        "resultant_length": float(data["resultant_length"]),
        "circular_sd_deg": float(data["circular_sd_deg"]),
        "uniformity_p": float(data["uniformity_p"]),
    }
