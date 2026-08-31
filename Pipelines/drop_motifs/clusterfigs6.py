"""
clusterfigs6.py
================
The full-page dendrogram and the gradient rose.

The dendrogram
--------------
drop_motifs5 drew the tree with text labels and nothing else, so a reader
could see that two motifs merged but never what either looked like. The
operator asked for the three-part layout the earlier `drop_motifs` figures
used, with two corrections to it.

    +----------------+-------------+------------------------------+
    |                |  the drop   |                              |
    |   the tree     |  at each    |   one panel per cluster at   |
    |   leaves top   |  leaf, at   |   the HIGHER cut: the medoid  |
    |   to bottom    |  the LOW    |   bold over its family faint  |
    |                |  cut        |                              |
    +----------------+-------------+------------------------------+

Correction 1 - THE TIME AXIS IS SECONDS. The earlier hero figure drew its
cluster overlays on `t / fall_duration`, so every motif was stretched to a
common width and the height-to-time ratio of every drop in the figure was
wrong. That is what the operator meant by the plots being "extended" and
mis-representing the ratio. Here the x axis is seconds for every panel,
shared within a panel, and a drop that took 30 s is drawn a fifth as wide
as one that took 150 s - because it was.

Correction 2 - NOT NORMALISED. Amplitude is millivolts throughout. The
baseline is removed, which is a shift; nothing is scaled.

Two cuts, which is what makes the figure readable
-------------------------------------------------
The tree is cut twice. The LOW cut is the fine structure and drives the
per-leaf thumbnails. The HIGH cut is the small number of families the
figure is actually about, and drives the right-hand panels; the cut line
is drawn on the tree so the reader can see where the families came from.
Panels are placed at the vertical extent of the leaves they contain, so a
family's panel sits beside its own branch and the intersection is legible
without a leader line.

The rose
--------
Three faults were reported and all three are fixed here.

  - "what are the green bars showing?" They were `tab20` CATEGORICAL span
    colours in the pooled figure and a single flat blue in the per-span
    ones - two unrelated schemes, neither explained. Every rose now uses
    ONE scheme: each motif is a segment coloured by its onset time on the
    same blue-green ramp as the overlays, so a bar's colour means the
    same thing everywhere in the figure set.
  - the radius was unlabelled. It is the motif count, and now says so.
  - each motif's own contribution is now a visible segment with a white
    edge, rather than being summed invisibly into a bar.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style6
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

COPHENETIC_FLOOR = 0.70

# Leaves above which the per-leaf thumbnail column is dropped: past this
# each row is under two millimetres on a full page and a thumbnail in it
# is a smudge. The tree and the family panels still carry the figure.
THUMBNAIL_LIMIT = 60

# The high cut. Deliberately small: the right-hand column is the part of
# the figure a reader takes away, and eight panels is about what a page
# holds at a size where the traces can be read.
MAX_FAMILIES = 8


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
    trough = int(np.clip(int(row["trough_idx"]) - start, onset + 1,
                         values.size))
    drop = values[onset:trough]
    return drop if drop.size >= 2 else values[onset:onset + 2]


def _display_trace(row, snippets, field="detrended_mv"):
    """`(t_s, mV)` for drawing: real seconds, baseline removed, not scaled.

    Detrended, matching the signal the depth and the shape clustering are
    both computed on. See the note in `overlays6` on why the drawn signal
    and the captioned numbers must be the same one.
    """
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None, None
    values = np.asarray(arrays[field], dtype=float)
    if int(row.get("signal_sign", 1)) < 0:
        values = -values
    onset = int(np.clip(int(row["onset_idx"]) - int(row["snippet_start_idx"]),
                        0, values.size - 1))
    return style6.aligned_trace(values, onset, float(row["fs"]))


def _cut_height(Z, n_clusters):
    """The height producing `n_clusters`, midway between the two merges."""
    heights = np.sort(Z[:, 2])
    if n_clusters >= len(heights) + 1:
        return 0.0
    upper = heights[-(n_clusters - 1)]
    lower = heights[-n_clusters] if n_clusters <= len(heights) else 0.0
    return float((upper + lower) / 2.0)


def _contiguous_blocks(sequence):
    """`[(value, start, end), ...]` over runs of an equal value."""
    blocks, start = [], 0
    for i in range(1, len(sequence) + 1):
        if i == len(sequence) or sequence[i] != sequence[start]:
            blocks.append((int(sequence[start]), start, i))
            start = i
    return blocks


def _medoid(features, members):
    """Index (into `members`) of the least-outlying member of a family.

    The medoid is a REAL motif, unlike a mean waveform, which is the
    reason to draw it: a family's representative should be something that
    was recorded rather than an average of things that were.
    """
    if len(members) == 1:
        return 0
    block = features[members]
    distances = np.linalg.norm(block[:, None, :] - block[None, :, :], axis=-1)
    return int(np.argmin(distances.sum(axis=1)))


# A family holding more than this fraction of the tree is not a family,
# it is the tree. See `choose_family_count`.
MAX_FAMILY_SHARE = 0.5

MIN_FAMILIES = 3

# Relative weights of the two ways a cut can be a bad page. An over-large
# family hides structure the figure exists to show; a singleton panel
# merely wastes a row. Four to one, so a cut only accepts a singleton when
# it buys a real improvement in balance.
OVER_SHARE_WEIGHT = 2.0
SINGLETON_WEIGHT = 0.5


def choose_family_count(Z, n, *, max_families=MAX_FAMILIES,
                        max_share=MAX_FAMILY_SHARE,
                        min_families=MIN_FAMILIES):
    """How many families the right-hand column should show.

    `cluster.suggest_n_clusters` optimises the tree's own elbow, and on
    catalogue ID 1 it answered 2 - which put 24 of 31 motifs in one panel
    whose traces visibly held two different shapes. An elbow is the right
    criterion for "how many clusters does this data have"; it is the wrong
    one for "how many panels does this page want", which is what is being
    decided here.

    So: cut deeper until no single family holds more than half the motifs,
    stopping at `max_families` because the column has to fit on a page.
    The floor is three - two panels cannot show a family structure, they
    can only show a split.

    SINGLETONS ARE THE COMPETING COST. Cutting deeper to break up a large
    family also shears off one-member families, and a panel holding one
    trace shows no family at all while still taking a row of the page.

    The two costs are WEIGHED, not ranked. Ranking them was tried first -
    "fewest singletons, then balance" - and it reintroduced the defect it
    was meant to fix: on a tree with no perfect cut it chose k=3 and left
    62% of the motifs in one panel, because that cut happened to have no
    singleton. An over-large family is the more serious fault of the two,
    so it carries the heavier weight, and both are continuous so a cut
    that is slightly bad in both loses to one that is clearly good in one.
    """
    ceiling = max(2, min(int(max_families), int(n) - 1))
    floor = max(2, min(int(min_families), ceiling))

    best, best_cost = floor, float("inf")
    for k in range(floor, ceiling + 1):
        labels = dc.cut_tree(Z, n_clusters=k)
        _, counts = np.unique(labels, return_counts=True)

        over_share = max(0.0, counts.max() / float(n) - max_share)
        singleton_fraction = int((counts == 1).sum()) / float(k)
        cost = OVER_SHARE_WEIGHT * over_share + SINGLETON_WEIGHT * singleton_fraction

        if cost < best_cost - 1e-12:
            best, best_cost = k, cost
        if best_cost <= 0.0:
            break        # a cut with neither fault; nothing deeper can beat it
    return best


def plot_dendrogram_page(rows, snippets, out_path, *, title, excluded=0,
                         max_families=MAX_FAMILIES):
    """The full-page tree / leaves / families figure."""
    if len(rows) < 3:
        return None, {"reason": f"only {len(rows)} motifs; a tree needs 3"}
    style6.apply_style()

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

    low_k = max(2, min(int(dc.suggest_n_clusters(Z)), len(keep) - 1))
    high_k = choose_family_count(Z, len(keep), max_families=max_families)
    low_labels = dc.cut_tree(Z, n_clusters=low_k)
    high_labels = dc.cut_tree(Z, n_clusters=high_k)
    high_cut = _cut_height(Z, high_k)

    n = len(keep)
    thumbnails = n <= THUMBNAIL_LIMIT
    row_height = 0.30 if thumbnails else 0.10
    fig_height = float(np.clip(row_height * n + 3.0, 9.0, 44.0))
    fig = plt.figure(figsize=(17.0, fig_height))

    left, right = 0.045, 0.985
    bottom, top = 0.055, 0.915
    if thumbnails:
        tree_w, thumb_w, gap = 0.24, 0.26, 0.022
    else:
        tree_w, thumb_w, gap = 0.34, 0.0, 0.030
    panel_x = left + tree_w + gap + thumb_w + (gap if thumbnails else 0.0)
    panel_w = right - panel_x

    ax_tree = fig.add_axes([left, bottom, tree_w, top - bottom])
    palette = plt.get_cmap("tab10")

    def link_colour(node):
        """Colour a link by the HIGH-cut family it sits inside, grey above."""
        leaves = _leaves_under(Z, node, n)
        families = {int(high_labels[i]) for i in leaves}
        if len(families) == 1:
            return matplotlib.colors.to_hex(
                palette((families.pop() - 1) % 10))
        return "0.62"

    dendro = dendrogram(Z, orientation="left", ax=ax_tree, no_labels=True,
                        link_color_func=link_colour)
    for line in ax_tree.get_lines():
        line.set_linewidth(style6.LW_TREE)
    ax_tree.axvline(high_cut, color=style6.RULE_COLOUR, lw=style6.LW_RULE,
                    ls="--", alpha=0.75)
    ax_tree.set_xlabel(f"Ward merge distance\n(dashed: cut at k={high_k})",
                       fontsize=9)
    ax_tree.set_title(f"{n} motifs, {high_k} families\n"
                      f"cophenetic r = {cophenetic:.3f}"
                      + ("  (below 0.70 — read with caution)"
                         if cophenetic < COPHENETIC_FLOOR else ""),
                      fontsize=11)
    ax_tree.grid(False)

    leaves = dendro["leaves"]
    y_lo, y_hi = ax_tree.get_ylim()

    def leaf_fraction(position):
        """Leaf at `position` (0 = bottom) -> figure y. scipy puts leaf i
        at data y = 5 + 10i, bottom-first; both facts are used, not
        assumed away - getting either wrong silently pairs a thumbnail
        with the wrong branch."""
        y = 5.0 + 10.0 * position
        return bottom + ((y - y_lo) / (y_hi - y_lo)) * (top - bottom)

    # -- the per-leaf thumbnails ------------------------------------------
    if thumbnails:
        thumb_h = min(row_height * 0.80, (top - bottom) / max(n, 1) * 0.84)
        colours, _ = style6.time_colours([r["onset_h"] for r in keep])
        for position, leaf in enumerate(leaves):
            row = keep[leaf]
            ax = fig.add_axes([left + tree_w + gap,
                               leaf_fraction(position) - thumb_h / 2.0,
                               thumb_w, thumb_h])
            t, values = _display_trace(row, snippets)
            if t is not None:
                ax.plot(t, values, color=colours[leaf], lw=style6.LW_TRACE)
            ax.axvline(0.0, color=style6.RULE_COLOUR, lw=style6.LW_RULE * 0.6,
                       alpha=0.45)
            style6.strip_axis(ax)
            ax.text(0.995, 0.02,
                    f"{row['onset_h']:.2f} h   "
                    f"{abs(float(row['drop_depth_mv'])):.0f} mV   "
                    f"{float(row['fall_duration_s']):.0f} s"
                    + ("   ↑" if int(row.get("signal_sign", 1)) < 0 else ""),
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=6.4, color="#444444",
                    bbox=dict(facecolor="white", edgecolor="none",
                              alpha=0.72, pad=0.6))

    # -- one panel per family, at its own branch --------------------------
    blocks = _contiguous_blocks([high_labels[leaf] for leaf in leaves])

    # ONE x range for every family panel in the figure.
    #
    # Each panel's own common window is a different length, and only the
    # bottom panel carries tick labels. Letting each set its own limits
    # therefore drew panels of equal width covering different numbers of
    # seconds, under a single axis that appeared to serve all of them -
    # which is exactly the misrepresented height-to-time ratio this figure
    # set exists to fix, reintroduced one level up. The union of the
    # per-family windows is used instead, so a second is the same distance
    # in every panel and the families are directly comparable.
    panel_xlim = _shared_xlim(keep, leaves, blocks, snippets)

    for family, start, end in blocks:
        members = [leaves[i] for i in range(start, end)]
        y0 = leaf_fraction(start) - 0.004
        y1 = leaf_fraction(end - 1) + 0.004
        height = max(y1 - y0, 0.030)
        ax = fig.add_axes([panel_x + 0.045, y0, panel_w - 0.065, height])

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
            traces.append(values - style6.baseline_level(values, onset))
            onsets.append(onset)
            depths.append(abs(float(row["drop_depth_mv"])))

        if not traces:
            continue
        stacked, onset_index = style6.uniform_set(traces, onsets)
        fs = float(keep[members[0]]["fs"])
        t = (np.arange(stacked.shape[1]) - onset_index) / fs
        outliers = style6.outlier_mask(np.asarray(depths))

        colour = palette((int(family) - 1) % 10)
        # Every member faint, then the medoid bold on top: the family's
        # spread and its representative in one panel, which is what was
        # asked for.
        for values, is_outlier in zip(stacked, outliers):
            ax.plot(t, values,
                    color=style6.OUTLIER_COLOUR if is_outlier else colour,
                    lw=style6.LW_FAMILY,
                    alpha=style6.ALPHA_OUTLIER if is_outlier
                    else style6.ALPHA_FAMILY, zorder=2)
        medoid = _medoid(features, members)
        ax.plot(t, stacked[medoid], color=colour, lw=style6.LW_MEDOID,
                alpha=0.95, zorder=4)

        ax.axvline(0.0, color=style6.RULE_COLOUR, ls="--",
                   lw=style6.LW_RULE * 0.8, alpha=0.6, zorder=1)
        ylim = style6.family_ylim(stacked, ~outliers)
        if ylim:
            ax.set_ylim(*ylim)
        ax.set_xlim(*panel_xlim)
        ax.set_facecolor("#fcfcfc")
        for spine in ax.spines.values():
            spine.set_edgecolor(colour)
            spine.set_linewidth(1.6 * style6.LW)
        ax.tick_params(labelsize=6.8)
        ax.grid(alpha=0.15, lw=style6.LW_RULE * 0.5)
        if family != blocks[0][0]:
            ax.set_xticklabels([])

        falls = [float(keep[leaf]["fall_duration_s"]) for leaf in members]
        ax.text(0.012, 0.96,
                f"family {family}  n={len(members)}  ·  medoid bold  ·  "
                f"fall {np.median(falls):.0f} s median"
                + (f"  ·  {int(outliers.sum())} outlier off-scale"
                   if outliers.any() else ""),
                transform=ax.transAxes, ha="left", va="top",
                fontsize=7.6, color=colour, fontweight="bold")

    blocks_last = blocks[0][0] if blocks else None
    fig.text(panel_x + panel_w / 2.0, bottom - 0.030,
             "time from onset (s) — REAL seconds, shared within a panel; "
             "amplitude in mV, baseline removed, NOT normalised",
             ha="center", va="top", fontsize=10)
    if thumbnails:
        fig.text(left + tree_w + gap + thumb_w / 2.0, top + 0.008,
                 "each motif (mV; own time axis)",
                 ha="center", va="bottom", fontsize=9.5)
    fig.text(panel_x + panel_w / 2.0, top + 0.008,
             f"families at the k={high_k} cut — medoid bold, members faint",
             ha="center", va="bottom", fontsize=9.5)
    fig.suptitle(f"{title}\nn={n} motifs"
                 + (f", {excluded} impure excluded" if excluded else ""),
                 fontsize=14, y=0.975)

    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": n,
        "excluded": int(excluded),
        "n_clusters_low": int(low_k),
        "n_families": int(high_k),
        "cophenetic_r": float(cophenetic),
        "labels": [int(v) for v in high_labels],
        "fine_labels": [int(v) for v in low_labels],
        "composition": _composition(keep, high_labels),
    }


def _shared_xlim(rows, leaves, blocks, snippets):
    """The union of every family's common window, in seconds from onset."""
    low, high = 0.0, 0.0
    for _, start, end in blocks:
        members = [leaves[i] for i in range(start, end)]
        traces, onsets = [], []
        for leaf in members:
            row = rows[leaf]
            arrays = snippets.get(row["event_id"])
            if arrays is None:
                continue
            values = np.asarray(arrays["detrended_mv"], dtype=float)
            onset = int(np.clip(int(row["onset_idx"])
                                - int(row["snippet_start_idx"]),
                                0, values.size - 1))
            traces.append(values)
            onsets.append(onset)
        if not traces:
            continue
        stacked, onset_index = style6.uniform_set(traces, onsets)
        fs = float(rows[members[0]]["fs"])
        low = min(low, -onset_index / fs)
        high = max(high, (stacked.shape[1] - onset_index) / fs)
    if high <= low:
        return -1.0, 1.0
    return low, high


def _leaves_under(Z, node, n):
    """Every original observation under a linkage node."""
    if node < n:
        return [int(node)]
    stack, out = [int(node)], []
    while stack:
        current = stack.pop()
        if current < n:
            out.append(int(current))
            continue
        left, right = Z[current - n, 0], Z[current - n, 1]
        stack.extend([int(left), int(right)])
    return out


def _composition(rows, labels):
    out = {}
    for label, row in zip(labels, rows):
        bucket = out.setdefault(str(int(label)), {})
        key = f"id{int(row['catalogue_id']):03d}"
        bucket[key] = bucket.get(key, 0) + 1
    return out


# ===========================================================================
# the rose
# ===========================================================================

def plot_rose(rows, snippets, out_path, *, title, excluded=0,
              field="max_slope_mv_s", scale="raw", n_bins=18):
    """Fall-gradient rose, every motif its own segment, coloured by time.

    One colour scheme, stated on the figure: the blue-green onset-time
    ramp the overlays use. drop_motifs5 drew flat blue per span and
    `tab20` categorical colours pooled, and the operator could not tell
    what the green bars meant - because in one figure green was a span
    identity and in the other it meant nothing at all.
    """
    if not rows:
        return None, {"reason": "no motifs"}
    style6.apply_style()

    data = dg.rose_data(rows, snippets, scale=scale, field=field,
                        split_by="span_key")
    if not data["n"]:
        return None, {"reason": "no gradients computable"}

    angles = np.asarray(data["angles"], dtype=float)
    gradients = data["gradients"]
    onsets = np.array([float(g.get("onset_h", 0.0)) for g in gradients])
    colours, norm = style6.time_colours(onsets)

    lo, hi = data["lo"], data["hi"]
    edges = np.linspace(lo, hi, n_bins + 1)
    width = float(edges[1] - edges[0])
    which = np.clip(np.digitize(angles, edges) - 1, 0, n_bins - 1)

    fig = plt.figure(figsize=(9.4, 8.6))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    ax.set_thetamin(-90)
    ax.set_thetamax(0)

    # One stacked unit per motif, so a bar's height IS its count and every
    # motif's own contribution is a visible segment.
    order = np.argsort(onsets)
    heights = np.zeros(n_bins)
    for i in order:
        bin_index = int(which[i])
        ax.bar(float(edges[bin_index]) + width / 2.0, 1.0, width=width * 0.92,
               bottom=heights[bin_index], color=colours[i],
               edgecolor="white", linewidth=0.6, zorder=3)
        heights[bin_index] += 1.0

    peak = float(heights.max()) if heights.size else 1.0
    mean = np.deg2rad(data["mean_deg"])
    ax.plot([mean, mean], [0, peak], color=style6.MEAN_COLOUR,
            lw=2.2 * style6.LW, zorder=5,
            label=f"mean {data['mean_deg']:.1f}°")

    ax.set_rlabel_position(-95)
    ax.set_ylim(0, max(peak * 1.08, 1.0))
    ax.text(np.deg2rad(-96), peak * 0.55, "number of motifs",
            rotation=90, ha="center", va="center", fontsize=9, color="0.3")
    ax.grid(alpha=0.3, lw=style6.LW_RULE * 0.6)
    # Lower left. The wedge only ever occupies the upper right of a
    # -90..0 quadrant, so this corner is empty by construction - and the
    # upper right, where a legend conventionally goes, is where the title
    # and the data both are.
    ax.legend(loc="lower left", bbox_to_anchor=(-0.04, 0.02), fontsize=9,
              frameon=False)

    bar = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=style6.TIME_CMAP),
                       ax=ax, fraction=0.035, pad=0.10)
    bar.set_label("onset time in recording (h) — one segment per motif",
                  fontsize=9)
    bar.ax.tick_params(labelsize=8)

    ax.set_title(
        f"{title}\n"
        f"n={data['n']} motifs"
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
        "field": field,
        "scale": scale,
        "mean_deg": float(data["mean_deg"]),
        "resultant_length": float(data["resultant_length"]),
        "circular_sd_deg": float(data["circular_sd_deg"]),
        "uniformity_p": float(data["uniformity_p"]),
    }
