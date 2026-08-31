"""
clusterfigs72.py
=================
drop_motifs7.2's dendrogram page.

    +---------------------------------------------------+
    |                                                   |
    |   the tree, root at the top, running down the      |
    |   length of an A4-proportioned page                |
    |                                                   |
    |        [fam 1]  [fam 2]  [fam 3]  [fam 4]         |  <- ON the tree,
    |         at the cut line, uniform boxes             |     at the cut
    |                                                   |
    |   ...leaves...                                    |
    +---------------------------------------------------+
    |  one motif per leaf, along the bottom             |
    +---------------------------------------------------+

Three changes from `clusterfigs7`.

1. A4 PROPORTIONS, TREE DOWN THE PAGE. The three-row layout gave the tree
   a quarter of the height and left the family row competing for space
   with it. The tree now runs down most of the page.

2. THE FAMILY OVERLAYS SIT ON THE TREE AT THE CUT. They were a separate
   row whose panels were each as wide as their branch, so a two-leaf
   family got a sliver and a twenty-leaf family got a slab - sizing that
   carried no meaning and, as the operator put it, was distracting.
   They are now drawn over the tree at the height of the cut that
   produced them, each in a box of exactly the same size, centred on its
   own branch. Position says which branch; size says nothing, because
   size was never carrying information.

3. SHAPE IS THE RECORDING'S. Both the per-leaf motifs and the family
   panels are locked to the millivolt-per-second implied by the span
   panel, so a motif has the same proportion here that it has in the
   recording - see `overlays72` for the measurement this replaces.

Uniform boxes and preserved shape at the same time is what
`adjustable="datalim"` is for: the box is held at the size given and the
VIEW widens to satisfy the aspect, where box-adjustment would have made
every panel a different size again.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style7
from Pipelines.drop_motifs.clusterfigs6 import (MAX_FAMILIES,
                                                _contiguous_blocks, _medoid,
                                                choose_family_count)
from Pipelines.drop_motifs.clusterfigs7 import (COPHENETIC_FLOOR, _aligned,
                                                _composition, _cut_height,
                                                _leaves_under, _waveform_of)
from Working.Detection.drop_motifs import cluster as dc

# A4, scaled up so a 9 pt label is still 9 pt on a page this size.
A4_RATIO = 11.69 / 8.27
PAGE_WIDTH_IN = 13.0
PAGE_HEIGHT_IN = PAGE_WIDTH_IN * A4_RATIO

# The family panels, as a fraction of the figure. The width is derived
# from the family count so the row always tiles without overlapping, and
# every box is still the same size as every other - uniform, but uniform
# at a size that fits.
MAX_FAMILY_BOX_W = 0.150
FAMILY_BOX_H = 0.105

# At most one family per this many motifs. Seventeen motifs cut into seven
# families gave four panels of one or two traces each, which is a picture
# of the cut rather than of any shape family.
MOTIFS_PER_FAMILY = 4

THUMBNAIL_LIMIT = 70


def _family_positions(centres, box_width, left, right):
    """Non-overlapping x centres, as close to `centres` as possible.

    Two families whose branches are close together would otherwise draw
    two equal boxes on top of each other. Swept left to right, each box
    pushed just far enough right to clear the previous one, then the whole
    row shifted back if it has run past the right margin.
    """
    order = np.argsort(centres)
    placed = np.array(centres, dtype=float)
    cursor = left + box_width / 2.0
    for i in order:
        placed[i] = max(placed[i], cursor)
        cursor = placed[i] + box_width
    overshoot = (placed[order[-1]] + box_width / 2.0) - right
    if overshoot > 0:
        placed -= overshoot
    return np.clip(placed, left + box_width / 2.0, right - box_width / 2.0)


def plot_dendrogram_page(rows, snippets, out_path, *, title, excluded=0,
                         max_families=MAX_FAMILIES, span_aspect=None,
                         true_ratio=float("nan"), compression=1.0):
    """The A4 page: tree down the length, families on it at the cut,
    motifs along the bottom."""
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
    box_w = min(MAX_FAMILY_BOX_W, (0.980 - 0.070) / high_k * 0.94)
    high_labels = dc.cut_tree(Z, n_clusters=high_k)
    high_cut = _cut_height(Z, high_k)

    aspect = span_aspect if span_aspect else 1.0

    fig = plt.figure(figsize=(PAGE_WIDTH_IN, PAGE_HEIGHT_IN))
    left, right = 0.070, 0.980
    motif_bottom, motif_top = 0.045, 0.205
    tree_bottom, tree_top = 0.235, 0.930

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
    ax_tree.axhline(high_cut, color=style7.RULE_COLOUR, lw=style7.LW_RULE,
                    ls="--", alpha=0.8)
    ax_tree.set_ylabel("Ward merge distance (z-normalised shape)", fontsize=9)
    ax_tree.set_xticks([])
    ax_tree.grid(False)
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
    if n <= THUMBNAIL_LIMIT:
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
            # datalim, not box: every thumbnail keeps the cell it was
            # given, so the row reads as a row, and the shape is preserved
            # by widening the view instead.
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

    # -- the family panels, ON the tree at the cut ------------------------
    blocks = _contiguous_blocks([high_labels[leaf] for leaf in leaves])
    centres = [np.mean([leaf_fraction(i) for i in range(start, end)])
               for _, start, end in blocks]
    placed = _family_positions(centres, box_w, left, right)

    # The cut height in figure coordinates, so the panels sit on the line
    # they came from rather than near it.
    cut_display = ax_tree.transData.transform((0.0, high_cut))
    cut_y = fig.transFigure.inverted().transform(cut_display)[1]

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
        # Uniform boxes, true shape: see the module docstring.
        style7.apply_aspect(ax, aspect, adjustable="datalim")

        ax.text(0.035, 0.94, f"f{family}  n={len(members)}",
                transform=ax.transAxes, ha="left", va="top", fontsize=7.0,
                color=cmap(0.88), fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75,
                          pad=1.0))
        # A short leader from the panel down to its own branch, so a panel
        # nudged sideways to avoid a collision still says which branch.
        own = float(np.mean([leaf_fraction(i) for i in range(start, end)]))
        if abs(own - x_centre) > 0.004:
            fig.add_artist(plt.Line2D(
                [x_centre, own], [cut_y - FAMILY_BOX_H / 2.0, cut_y],
                transform=fig.transFigure, color=cmap(0.78),
                lw=style7.LW_RULE * 0.8, alpha=0.7, zorder=5))
        info_families.append({"family": int(family), "n": len(members),
                              "median_fall_s": median_fall})

    fig.savefig(out_path, dpi=170, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": n,
        "excluded": int(excluded),
        "n_families": int(high_k),
        "cophenetic_r": float(cophenetic),
        "aspect_seconds_per_mv": float(aspect),
        "true_height_to_width": float(true_ratio),
        "shape_compression": float(compression),
        "families": info_families,
        "labels": [int(v) for v in high_labels],
        "composition": _composition(keep, high_labels),
    }
