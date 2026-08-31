"""
clusterfigs7.py
================
The full-page dendrogram, rebuilt as three ROWS, and the gradient rose.

    +-------------------------------------------------------------+
    |  the tree, root at the top, branches running DOWN to the     |
    |  leaves along the bottom of the row                          |
    +-------------------------------------------------------------+
    |  one motif per leaf, left to right, under its own leaf       |
    +-------------------------------------------------------------+
    |  one overlay per family, left to right, under its own branch |
    +-------------------------------------------------------------+

drop_motifs6 laid this out as three columns with the tree on its side.
Rows put the leaf order along the x axis, which is the direction a page
has more of, and it puts each motif directly beneath the branch it hangs
from - so the association is read vertically instead of traced across.

The height-to-width ratio
-------------------------
The same fault the overlays had, and the same fix. Every drop_motifs6
thumbnail filled its own little box, so a 3 s event and a 300 s event were
drawn the same width and the shapes could not be compared. Every motif
panel and every family panel here is locked to one millivolt-per-second
scale, derived from the figure's own median event and stated on the
figure. A slow shallow event is now drawn wide and flat because it IS wide
and flat.

Colour
------
One hue per family, matching `overlays7`, so a family has the same colour
in the tree, in its thumbnails, in its overlay panel and in the overlay
figure for the same span.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style7
from Pipelines.drop_motifs.clusterfigs6 import (MAX_FAMILIES, MAX_FAMILY_SHARE,
                                                MIN_FAMILIES, OVER_SHARE_WEIGHT,
                                                SINGLETON_WEIGHT,
                                                _contiguous_blocks, _medoid,
                                                choose_family_count)
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

COPHENETIC_FLOOR = 0.70

# Leaves above which the per-leaf motif row is dropped. Past this each
# thumbnail is under three millimetres wide on a full-page spread.
THUMBNAIL_LIMIT = 70


def _waveform_of(row, snippets, field="detrended_mv"):
    """The drop itself, onset to trough, oriented as a fall."""
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None
    values = np.asarray(arrays[field], dtype=float)
    if int(row.get("signal_sign", 1)) < 0:
        values = -values
    start = int(row["snippet_start_idx"])
    onset = int(np.clip(int(row["onset_idx"]) - start, 0, values.size - 1))
    trough = int(np.clip(int(row["trough_idx"]) - start, onset + 1, values.size))
    drop = values[onset:trough]
    return drop if drop.size >= 2 else values[onset:onset + 2]


def _aligned(row, snippets, field="detrended_mv"):
    """`(t_s, mV)` - real seconds, baseline removed, never scaled."""
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None, None
    values = np.asarray(arrays[field], dtype=float)
    if int(row.get("signal_sign", 1)) < 0:
        values = -values
    onset = int(np.clip(int(row["onset_idx"]) - int(row["snippet_start_idx"]),
                        0, values.size - 1))
    return style7.aligned_trace(values, onset, float(row["fs"]))


def _cut_height(Z, n_clusters):
    heights = np.sort(Z[:, 2])
    if n_clusters >= len(heights) + 1:
        return 0.0
    upper = heights[-(n_clusters - 1)]
    lower = heights[-n_clusters] if n_clusters <= len(heights) else 0.0
    return float((upper + lower) / 2.0)


def _leaves_under(Z, node, n):
    if node < n:
        return [int(node)]
    stack, out = [int(node)], []
    while stack:
        current = stack.pop()
        if current < n:
            out.append(int(current))
            continue
        stack.extend([int(Z[current - n, 0]), int(Z[current - n, 1])])
    return out


def _composition(rows, labels):
    out = {}
    for label, row in zip(labels, rows):
        bucket = out.setdefault(str(int(label)), {})
        key = f"id{int(row['catalogue_id']):03d}"
        bucket[key] = bucket.get(key, 0) + 1
    return out


def plot_dendrogram_page(rows, snippets, out_path, *, title, excluded=0,
                         max_families=MAX_FAMILIES):
    """Three rows: the tree, the motifs, the family overlays."""
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

    low_k = max(2, min(int(dc.suggest_n_clusters(Z)), n - 1))
    high_k = choose_family_count(Z, n, max_families=max_families)
    high_labels = dc.cut_tree(Z, n_clusters=high_k)
    high_cut = _cut_height(Z, high_k)

    aspect = style7.seconds_per_mv(
        [abs(float(r.get("drop_depth_mv", 0.0))) for r in keep],
        [abs(float(r.get("fall_duration_s", 0.0))) for r in keep])

    thumbnails = n <= THUMBNAIL_LIMIT
    width = float(np.clip(0.62 * n + 5.0, 16.0, 46.0))
    fig = plt.figure(figsize=(width, 18.0))

    left, right = 0.045, 0.985
    tree_top, tree_bottom = 0.930, 0.680
    motif_top, motif_bottom = 0.664, 0.436
    panel_top, panel_bottom = 0.392, 0.068

    ax_tree = fig.add_axes([left, tree_bottom, right - left,
                            tree_top - tree_bottom])

    def link_colour(node):
        """Colour a link by the family it sits inside, grey above the cut."""
        families = {int(high_labels[i]) for i in _leaves_under(Z, node, n)}
        if len(families) == 1:
            _, cmap = style7.family_ramp(sorted(families)[0] - 1)
            return matplotlib.colors.to_hex(cmap(0.62))
        return "0.62"

    dendro = dendrogram(Z, orientation="top", ax=ax_tree, no_labels=True,
                        link_color_func=link_colour)
    for line in ax_tree.get_lines():
        line.set_linewidth(style7.LW_TREE)
    ax_tree.axhline(high_cut, color=style7.RULE_COLOUR, lw=style7.LW_RULE,
                    ls="--", alpha=0.75)
    ax_tree.set_ylabel("Ward merge distance\n(z-normalised shape)", fontsize=9)
    ax_tree.set_xticks([])
    ax_tree.grid(False)
    ax_tree.set_title(
        f"{title}\nn={n} motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + f"  ·  {high_k} families at the dashed cut"
        f"  ·  cophenetic r = {cophenetic:.3f}"
        + ("  (below 0.70 — read with caution)"
           if cophenetic < COPHENETIC_FLOOR else "")
        + f"\nmotif row: {style7.aspect_caption(aspect)}"
          f"  ·  family panels are locked per family and state their own",
        fontsize=12, pad=14)

    leaves = dendro["leaves"]
    x_lo, x_hi = ax_tree.get_xlim()

    def leaf_fraction(position):
        """Leaf at `position` -> figure x. scipy places leaf i at data
        x = 5 + 10i under `orientation="top"`, left to right."""
        x = 5.0 + 10.0 * position
        return left + ((x - x_lo) / (x_hi - x_lo)) * (right - left)

    # -- row 2: one motif per leaf ----------------------------------------
    if thumbnails:
        slot = (right - left) / max(n, 1)
        cell = slot * 0.86
        for position, leaf in enumerate(leaves):
            row = keep[leaf]
            family = int(high_labels[leaf])
            _, cmap = style7.family_ramp(family - 1)
            ax = fig.add_axes([leaf_fraction(position) - cell / 2.0,
                               motif_bottom, cell, motif_top - motif_bottom])
            t, values = _aligned(row, snippets)
            if t is not None:
                ax.plot(t, values, color=cmap(0.62), lw=style7.LW_TRACE)
            ax.axvline(0.0, color=style7.RULE_COLOUR,
                       lw=style7.LW_RULE * 0.6, alpha=0.45)
            style7.strip_axis(ax)
            style7.apply_aspect(ax, aspect)
            ax.text(0.5, -0.02,
                    f"{abs(float(row['drop_depth_mv'])):.0f}mV\n"
                    f"{float(row['fall_duration_s']):.0f}s"
                    + ("\n↑" if int(row.get("signal_sign", 1)) < 0 else ""),
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=6.0, color="#555555")
        fig.text((left + right) / 2.0, motif_top + 0.006,
                 "each motif, under its own leaf — mV, baseline removed, "
                 "real seconds, shared scale",
                 ha="center", va="bottom", fontsize=10)

    # -- row 3: one overlay per family ------------------------------------
    blocks = _contiguous_blocks([high_labels[leaf] for leaf in leaves])
    for family, start, end in blocks:
        members = [leaves[i] for i in range(start, end)]
        x0 = leaf_fraction(start) - (right - left) / max(n, 1) * 0.5
        x1 = leaf_fraction(end - 1) + (right - left) / max(n, 1) * 0.5
        _, cmap = style7.family_ramp(int(family) - 1)

        ax = fig.add_axes([x0 + 0.004, panel_bottom,
                           max(x1 - x0 - 0.008, 0.012),
                           panel_top - panel_bottom])

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
        # This family's own scale, not the figure's. One shared scale
        # collapsed a 0.3 mV family to a hairline beside a 13 mV one -
        # the same failure `overlays7.group_aspect` records.
        family_aspect = style7.seconds_per_mv(
            depths, [float(keep[leaf]["fall_duration_s"]) for leaf in members])
        family_falls = [abs(float(keep[leaf]["fall_duration_s"]))
                        for leaf in members]

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
                   lw=style7.LW_RULE * 0.8, alpha=0.6, zorder=1)
        ylim = style7.family_ylim(stacked, ~outliers)
        if ylim:
            ax.set_ylim(*ylim)
        median_fall = float(np.median([f for f in family_falls if f > 0])
                            or 1.0) if any(f > 0 for f in family_falls) else 1.0
        ax.set_xlim(max(float(t[0]), -1.5 * median_fall),
                    min(float(t[-1]), 4.0 * median_fall))
        ax.set_facecolor("#fcfcfc")
        for spine in ax.spines.values():
            spine.set_edgecolor(cmap(0.75))
            spine.set_linewidth(1.6 * style7.LW)
        ax.tick_params(labelsize=6.2)
        ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
        style7.apply_aspect(ax, family_aspect)

        falls = family_falls
        ax.set_title(f"family {family}  n={len(members)}\n"
                     f"median fall {np.median(falls):.0f} s"
                     + (f"  ·  {int(outliers.sum())} off-scale"
                        if outliers.any() else ""),
                     fontsize=7.6, color=cmap(0.88), fontweight="bold", pad=3)

    fig.text((left + right) / 2.0, panel_bottom - 0.030,
             "families at the cut — medoid bold over its members; "
             "time from onset (s), amplitude in mV, NOT normalised",
             ha="center", va="top", fontsize=10)

    fig.savefig(out_path, dpi=135, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": n,
        "excluded": int(excluded),
        "n_clusters_low": int(low_k),
        "n_families": int(high_k),
        "cophenetic_r": float(cophenetic),
        "aspect_seconds_per_mv": float(aspect),
        "labels": [int(v) for v in high_labels],
        "composition": _composition(keep, high_labels),
    }


# ===========================================================================
# the rose
# ===========================================================================

def plot_rose(rows, snippets, out_path, *, title, excluded=0,
              field="max_slope_mv_s", scale="raw", n_bins=18):
    """Fall-gradient rose, one segment per motif, coloured by family hue.

    Same scheme as the overlays: a motif's colour is its family's hue and
    its position in the span, so the rose can be read against the panels
    rather than being a third unrelated colour language.
    """
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
        same = [x["onset_h"] for x in members if x and group_key(x) == (sign, band)]
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
    mean = np.deg2rad(data["mean_deg"])
    ax.plot([mean, mean], [0, peak], color=style7.MEAN_COLOUR,
            lw=2.2 * style7.LW, zorder=5,
            label=f"mean {data['mean_deg']:.1f}°")

    ax.set_rlabel_position(-95)
    ax.set_ylim(0, max(peak * 1.08, 1.0))
    ax.text(np.deg2rad(-96), peak * 0.55, "number of motifs", rotation=90,
            ha="center", va="center", fontsize=9, color="0.3")
    ax.grid(alpha=0.3, lw=style7.LW_RULE * 0.6)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.04, 0.02), fontsize=9,
              frameon=False)

    handles = [plt.Line2D([0], [0], color=style7.family_ramp(
        hues[k], inverted=k[0] < 0)[1](0.7), lw=6,
        label=("drops" if k[0] > 0 else "rises") + f" band {k[1] + 1}")
        for k in keys]
    if len(handles) > 1:
        ax.add_artist(ax.legend(handles=handles, loc="upper right",
                                bbox_to_anchor=(1.22, 1.06), fontsize=8,
                                frameon=False, title="family"))

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
