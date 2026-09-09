"""
clusterfigs9.py
================
drop_motifs9's three figures. All three are new drawing code; the
clustering, the gradients and the palette underneath them are the vetted
ones from `Working.Detection.drop_motifs` and `style7`.

1. THE POOLED DENDROGRAM, WITH PANELS THAT ARE ACTUALLY LEGIBLE
---------------------------------------------------------------
`clusterfigs8.plot_pooled_dendrogram_page` had three faults, all visible
on `Plots/drop_motifs8_fig2a/ALL_dendrogram.png`:

  THE PANEL CONTENT RAN OFF THE BOX. `_family_panel` set its y limits from
  `family_ylim(stacked, ~outliers)` - the non-outlier members - and then
  set x limits that clipped the trace. Neither computation knew about the
  MEDOID, so the representative line, the one thing the panel exists to
  show, was routinely half outside the axes. Here the view is derived from
  the medoid first: the medoid's full excursion over the visible x range
  is inside the y range by construction, and the members only widen it.

  PANELS OVERLAPPED. Boxes were centred on their branch and then nudged
  apart, which cannot converge when branches cluster. Panels now sit in
  EVENLY SPACED SLOTS across the page and a leader line runs from each to
  its branch, so overlap is impossible by construction and the boxes can
  be much larger.

  MEMBERS COMPETED WITH THE REPRESENTATIVE. Members were drawn at
  `ALPHA_FAMILY` = 0.28 whatever the count; at n=389 that is a solid
  block. Member alpha now falls with the population - the more there are
  the fainter each is - and the medoid gets a white halo so it reads on
  top of any density.

2. THE ROSE, ASKED TO ANSWER A QUESTION
---------------------------------------
The ask is whether drop HEIGHT is grouped by drop SLOPE - specifically
whether small drops fall more steeply than large ones. A rose alone cannot
answer that: it is a marginal distribution of angle and has thrown the
height away. So the figure is four panels that share one measurement:

    1  the rose proper, colour-coded by CHANNEL
    2  the same rose, stacked by drop-height quartile
    3  height against angle, per motif, with the correlation
    4  THE CONTROL: fall duration against height, log-log

PANEL 4 IS NOT OPTIONAL, and panel 3 must not be read without it. A fall's
slope IS its depth divided by its duration. If every drop took the same
time, "bigger drops are steeper" would be a restatement of "bigger drops
are bigger" - a true sentence about arithmetic and an empty one about
mycelium. Panel 3 on the Fig2A run gives rho = -0.77, which looks like a
strong biological result and is mostly not one.

The quantity that decides it is how fall duration scales with depth. Fit
`duration ∝ depth^b`:

    b near 0   duration is constant, so slope ∝ depth and panel 3 is
               arithmetic
    b near 1   duration tracks depth, so slope is size-independent and
               panel 3 would be flat

Panel 4 fits b, draws both reference regimes through the median point, and
states which one the data is nearer. That is the answer to the question as
asked; panel 3 is the picture of it.

The two roses are what was asked for and are drawn from the same
`gradients.rose_data` call, so no panel can disagree with another.

THE ANGLE FLOOR. `fall_gradients` measures a slope with `np.gradient`,
which needs at least three samples to mean anything. The sliding window
finds falls as short as one sample, whose "gradient" is an artefact of the
sample spacing. Every panel here therefore excludes falls under
`MIN_FALL_SAMPLES` and says how many it dropped. The store keeps them -
this is a plotting decision, not a detection one.

3. THE FAMILY ATLAS
-------------------
Every motif in the run, grouped by the same cut of the same tree the
dendrogram draws, one panel per family, with a channel-composition bar
under each. This is the "all motifs across all five channels" view: the
grouping is the clustering's, so the atlas and the dendrogram are two
renderings of one answer rather than two analyses.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from scipy.cluster.hierarchy import dendrogram
from scipy.stats import linregress, spearmanr

from Pipelines.drop_motifs import style7
from Pipelines.drop_motifs.clusterfigs6 import _medoid, choose_family_count
from Pipelines.drop_motifs.clusterfigs7 import (COPHENETIC_FLOOR, _cut_height,
                                                _leaves_under, _waveform_of)
from Pipelines.drop_motifs.clusterfigs73 import _ranked_axis
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

PAGE_W, PAGE_H = 16.5, 15.5

# A fall shorter than this cannot carry a gradient: `np.gradient` is a
# central difference and needs a point either side of the one it reports.
MIN_FALL_SAMPLES = 3

# Panels smaller than this show no family and are counted instead.
MIN_PANEL_MEMBERS = 3

# How many merges the drawn tree shows. The full tree at n>1000 is a solid
# block; the last 45 merges are the ones a cut at <=8 families acts on.
TRUNCATE_P = 45

# Widest a family panel may be drawn, width:height. Past this a fall reads
# as a horizontal line however steep it really is - the operator's note
# that the panels "look too flat". Under 1.0 the box is taller than it is
# wide, which is the proportion a DROP wants.
MAX_PANEL_ASPECT = 0.95

# Where the second, finer cut is allowed to land. The coarse cut on the
# Fig2A store chooses three families over a thousand motifs; that is a
# true statement about how few kinds there are and a useless one about
# what is in them.
FINE_FAMILY_RANGE = (6, 10)

# How much of each family's window a panel shows. `uniform_set` defaults to
# the STRICT MINIMUM pre/post any member can supply, which at n=1035 means
# one unusually tight snippet crops the whole family to a couple of
# samples - that is why the drop_motifs9 panels first drew as straight
# lines over +-0.1 s. At 0.25 the shortest quarter are NaN-padded (drawn as
# absent, never as invented flat signal) and the panel shows the window the
# bulk of the family actually has.
PANEL_WINDOW_QUANTILE = 0.25

# Distinct, colour-blind-safe hues for the five channels. Not `family_ramp`:
# that ramp encodes family, and using it for channel too would make two
# different meanings share one visual channel on the same page.
CHANNEL_COLOURS = ["#1b6ca8", "#d95f02", "#1b9e77", "#7570b3", "#b8336a"]


def channel_colour(channel):
    return CHANNEL_COLOURS[int(channel) % len(CHANNEL_COLOURS)]


def _member_alpha(n):
    """Fainter as the family grows, so density reads as density.

    At n=3 a member is nearly solid; by n=400 it is a wash that the medoid
    sits on top of. Clamped so a huge family never becomes invisible.
    """
    return float(np.clip(1.6 / np.sqrt(max(int(n), 1)), 0.045, 0.55))


# ===========================================================================
# shared: build the tree once
# ===========================================================================

def build_tree(rows, snippets, max_families=8, fine_families=None):
    """The linkage plus TWO cuts of it, coarse and fine.

    One place builds the tree so the dendrogram, the atlas and any quoted
    family count provably describe the same one.

    The second cut exists because the coarse cut on this data lands at
    three families over a thousand motifs, which says how few KINDS there
    are but shows almost nothing of what each kind contains. `fine_k` is
    twice the coarse count, clamped into `FINE_FAMILY_RANGE`, and both cuts
    are drawn on every pooled figure so the two readings sit side by side.
    """
    waveforms, keep = [], []
    for row in rows:
        wave = _waveform_of(row, snippets, orient_rises_as_drops=False)
        if wave is not None:
            waveforms.append(wave)
            keep.append(row)
    if len(keep) < 6:
        return None

    features = dc.feature_matrix(waveforms)
    Z, cophenetic = dc.build_linkage(features)
    n = len(keep)
    k = choose_family_count(Z, n, max_families=int(max_families))

    lo, hi = FINE_FAMILY_RANGE
    if fine_families:
        fine_k = int(fine_families)
    else:
        # The TOP of the range, not twice the coarse count. Twice 4 is 8,
        # and on this store k=8 splits only the small odd family while the
        # two families holding 82% of the motifs come through untouched -
        # so the second row repeated the first. k=10 is where the 479 and
        # the 390 actually divide (441+38 and 207+183).
        fine_k = int(np.clip(max(hi, k * 2), lo, hi))
    fine_k = int(min(max(fine_k, k + 1), max(n - 1, k + 1)))

    return dict(keep=keep, features=features, Z=Z, cophenetic=cophenetic,
                labels=dc.cut_tree(Z, n_clusters=k), k=int(k),
                cut=_cut_height(Z, k),
                fine_labels=dc.cut_tree(Z, n_clusters=fine_k),
                fine_k=int(fine_k), fine_cut=_cut_height(Z, fine_k))


# ===========================================================================
# the family panel — the thing that was cropping
# ===========================================================================

def _panel_traces(members, keep, snippets):
    """`(stacked, t, medoid_index, depths)` for one family, onset-aligned."""
    traces, onsets, depths = [], [], []
    for leaf in members:
        row = keep[leaf]
        arrays = snippets.get(row["event_id"])
        if arrays is None:
            continue
        values = np.asarray(arrays["detrended_mv"], dtype=float)
        onset = int(np.clip(int(row["onset_idx"]) - int(row["snippet_start_idx"]),
                            0, values.size - 1))
        traces.append(values - style7.baseline_level(values, onset))
        onsets.append(onset)
        depths.append(abs(float(row["drop_depth_mv"])))
    if not traces:
        return None
    stacked, onset_index = style7.uniform_set(
        traces, onsets, quantile=PANEL_WINDOW_QUANTILE)
    fs = float(keep[members[0]]["fs"])
    t = (np.arange(stacked.shape[1]) - onset_index) / fs
    return stacked, t, np.asarray(depths, dtype=float)


def draw_family_panel(ax, members, keep, snippets, features, cmap, *,
                      label=None, fontsize=7.0, show_axes=False):
    """One family overlaid, with the medoid guaranteed fully in view.

    The fix for the cropping is the order of operations. The x window is
    chosen first, from the family's own median fall; the y window is then
    computed over ONLY THE VISIBLE x range and is seeded with the medoid's
    own extent, so the representative cannot fall outside the axes. Member
    traces widen the window to their 2nd-98th percentile, which keeps a
    single wild member from flattening everyone else without clipping the
    bulk of the population.
    """
    built = _panel_traces(members, keep, snippets)
    if built is None:
        return None
    stacked, t, depths = built

    medoid_i = _medoid(features, members)
    medoid = stacked[medoid_i]

    falls = [abs(float(keep[leaf]["fall_duration_s"])) for leaf in members]
    median_fall = float(np.median([f for f in falls if f > 0] or [1.0]))
    x_lo = max(float(t[0]), -1.2 * median_fall)
    x_hi = min(float(t[-1]), 4.0 * median_fall)
    if not np.isfinite([x_lo, x_hi]).all() or x_hi <= x_lo:
        x_lo, x_hi = float(t[0]), float(t[-1])
    visible = (t >= x_lo) & (t <= x_hi)
    if visible.sum() < 2:
        visible = np.ones_like(t, dtype=bool)
        x_lo, x_hi = float(t[0]), float(t[-1])

    outliers = style7.outlier_mask(depths)

    # Seed the y window with the MEDOID, then widen for the members. This
    # is the whole fix: the representative is in view by construction.
    #
    # The widening uses the NON-OUTLIER members only. Outliers are drawn -
    # hiding them would misrepresent the family - but a handful of them
    # setting the scale is what flattens the other ninety-odd percent into
    # a horizontal band, which is the second half of the legibility
    # complaint this figure exists to answer.
    # NaN-safe throughout: the quantile window pads short members with NaN
    # on purpose, so a column can be entirely NaN and `nanmin` alone would
    # warn and return NaN.
    def _finite(values):
        values = np.asarray(values, dtype=float)
        return values[np.isfinite(values)]

    medoid_visible = _finite(medoid[visible])
    inliers = stacked[~outliers] if (~outliers).any() else stacked
    body = _finite(inliers[:, visible])
    if medoid_visible.size:
        lo, hi = float(medoid_visible.min()), float(medoid_visible.max())
    elif body.size:
        lo, hi = float(body.min()), float(body.max())
    else:
        return None
    if body.size:
        lo = min(lo, float(np.percentile(body, 1)))
        hi = max(hi, float(np.percentile(body, 99)))
    if not np.isfinite([lo, hi]).all() or hi <= lo:
        lo, hi = lo - 0.5, lo + 0.5
    pad = 0.10 * (hi - lo or 1.0)

    alpha = _member_alpha(len(stacked))
    for values, is_outlier in zip(stacked, outliers):
        ax.plot(t, values,
                color=style7.OUTLIER_COLOUR if is_outlier else cmap(0.50),
                lw=style7.LW_FAMILY * 0.85,
                ls=style7.OUTLIER_DASH if is_outlier else "-",
                alpha=min(alpha * 1.4, 0.6) if is_outlier else alpha,
                zorder=2, solid_capstyle="round")

    # The medoid, with a white halo so it reads on top of any density.
    ax.plot(t, medoid, color=cmap(0.95), lw=style7.LW_MEDOID * 1.15,
            alpha=1.0, zorder=6, solid_capstyle="round",
            path_effects=[path_effects.Stroke(linewidth=style7.LW_MEDOID * 2.6,
                                              foreground="white", alpha=0.9),
                          path_effects.Normal()])
    ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
               lw=style7.LW_RULE * 0.7, alpha=0.5, zorder=1)

    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(lo - pad, hi + pad)
    for spine in ax.spines.values():
        spine.set_edgecolor(cmap(0.80))
        spine.set_linewidth(1.3 * style7.LW)
    ax.grid(False)
    if not show_axes:
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        ax.tick_params(labelsize=6, length=2, pad=1)
    if label:
        ax.text(0.035, 0.94, label, transform=ax.transAxes, ha="left",
                va="top", fontsize=fontsize, color=cmap(0.95),
                fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8,
                          pad=1.2))
    return median_fall


# ===========================================================================
# 1. the dendrogram page
# ===========================================================================

def plot_dendrogram(rows, snippets, out_path, *, title, tree=None,
                    max_families=8, excluded=0):
    """Tree on top, family panels in evenly spaced slots beneath the cut."""
    tree = tree or build_tree(rows, snippets, max_families=max_families)
    if tree is None:
        return None, {"reason": "fewer than 6 motifs had waveforms"}
    style7.apply_style()

    keep, Z, labels = tree["keep"], tree["Z"], tree["labels"]
    features, n = tree["features"], len(tree["keep"])

    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    left, right = 0.055, 0.985
    # TWO rows of panels: the coarse cut nearest the tree, the fine cut
    # below it. The fine row is shorter only because it holds more boxes.
    fine_bottom, fine_h = 0.040, 0.180
    panel_bottom, panel_h = fine_bottom + fine_h + 0.058, 0.200
    tree_bottom, tree_top = panel_bottom + panel_h + 0.055, 0.900
    ax_tree = fig.add_axes([left, tree_bottom, right - left,
                            tree_top - tree_bottom])

    def link_colour(node):
        families = {int(labels[i]) for i in _leaves_under(Z, node, n)}
        if len(families) == 1:
            _, cmap = style7.family_ramp(sorted(families)[0] - 1)
            return matplotlib.colors.to_hex(cmap(0.62))
        return "0.68"

    # TRUNCATED. At n=1736 every leaf is a third of a pixel wide and the
    # tree renders as a solid block of colour - which is what the
    # drop_motifs8 pooled page did. Showing the last `TRUNCATE_P` merges
    # shows the structure that a cut at k families actually acts on; the
    # leaf counts are printed on the stubs, so nothing is hidden, it is
    # summarised. The full leaf ORDER is still used below to place panels.
    dendrogram(Z, orientation="top", ax=ax_tree, no_labels=True,
               link_color_func=link_colour,
               truncate_mode="lastp", p=int(min(TRUNCATE_P, n - 1)),
               show_leaf_counts=True, leaf_font_size=6, leaf_rotation=90)
    for line in ax_tree.get_lines():
        line.set_linewidth(style7.LW_TREE * 0.9)
    ax_tree.axhline(tree["cut"], color=style7.RULE_COLOUR,
                    lw=style7.LW_RULE, ls="--", alpha=0.85)
    ax_tree.axhline(tree["fine_cut"], color=style7.RULE_COLOUR,
                    lw=style7.LW_RULE, ls=(0, (5, 3)), alpha=0.55)
    # A ranked axis, not a log one: Ward heights here run from ~1e-4 to
    # ~150 and on a log scale the thousand near-zero merges swamp the page.
    _ranked_axis(ax_tree, Z[:, 2])
    ax_tree.set_ylabel("Ward merge distance — ranked axis, real labels",
                       fontsize=9)
    ax_tree.tick_params(axis="x", labelsize=5.5)
    ax_tree.grid(axis="y", alpha=0.14, lw=style7.LW_RULE * 0.5)
    for side in ("top", "right"):
        ax_tree.spines[side].set_visible(False)

    cophenetic = tree["cophenetic"]
    ax_tree.set_title(
        f"{title}\n"
        f"n={n} motifs  ·  {tree['k']} families at the coarse cut,"
        f" {tree['fine_k']} at the fine cut"
        + (f"  ·  {excluded} impure excluded" if excluded else "")
        + f"  ·  cophenetic r = {cophenetic:.3f}"
        + ("  (below 0.70 — the tree flattens real structure)"
           if cophenetic < COPHENETIC_FLOOR else "")
        + "\npanels are onset-aligned and each is scaled to its own family"
          " — shape is comparable WITHIN a panel, not across the row",
        fontsize=10.5, pad=10)

    # The FULL leaf order, computed without drawing, because the drawn
    # tree is truncated and its own `leaves` are stubs, not motifs.
    leaves = dendrogram(Z, no_plot=True)["leaves"]
    rank_of = {leaf: i for i, leaf in enumerate(leaves)}

    def leaf_fraction(position):
        """Figure x for leaf RANK `position`, via its fraction along the row.

        The truncated tree keeps the same left-to-right leaf order as the
        full one, so a family's mean leaf rank still points at where its
        branch is drawn, to within a stub's width.
        """
        return left + ((position + 0.5) / n) * (right - left)

    def families_in_leaf_order(label_array):
        """Family ids in the order the tree lays their leaves out."""
        seen, ordered = set(), []
        for leaf in leaves:
            family = int(label_array[leaf])
            if family not in seen:
                seen.add(family)
                ordered.append(family)
        return ordered

    def draw_row(label_array, row_bottom, row_h, *, name, fontsize,
                 parent_labels=None, connect=True):
        """One row of family panels, evenly spaced and centred.

        EVENLY SPACED SLOTS: overlap is impossible by construction, which
        is what the nudge-apart placement in clusterfigs8 could not
        guarantee. The box is also capped at `MAX_PANEL_ASPECT` so a drop
        is never drawn wider than it is tall and flattened into a line.
        """
        ordered = families_in_leaf_order(label_array)
        members_of = {f: [i for i in range(n) if int(label_array[i]) == f]
                      for f in ordered}
        drawable = [f for f in ordered
                    if len(members_of[f]) >= MIN_PANEL_MEMBERS]
        skipped = len(ordered) - len(drawable)
        if not drawable:
            return [], skipped

        gap = 0.012
        slot_w = (right - left + gap) / len(drawable)
        box_w = min(slot_w - gap, row_h * MAX_PANEL_ASPECT * PAGE_H / PAGE_W)
        row_w = len(drawable) * box_w + (len(drawable) - 1) * gap
        row_left = left + ((right - left) - row_w) / 2.0
        slot_w = box_w + gap

        fig.text(left - 0.008, row_bottom + row_h / 2.0, name, rotation=90,
                 ha="right", va="center", fontsize=8.5, color="0.35")

        drawn = []
        for index, family in enumerate(drawable):
            members = members_of[family]
            # A fine panel is coloured by the COARSE family it descends
            # from, so the second row reads as a split of the first.
            hue_family = (int(parent_labels[members[0]]) if parent_labels
                          is not None else family)
            _, cmap = style7.family_ramp(hue_family - 1)
            x0 = row_left + index * slot_w
            ax = fig.add_axes([x0, row_bottom, box_w, row_h], zorder=5)
            composition = {}
            for leaf in members:
                channel = int(keep[leaf]["channel"])
                composition[channel] = composition.get(channel, 0) + 1
            draw_family_panel(ax, members, keep, snippets, features, cmap,
                              label=f"{len(members)}", fontsize=fontsize)

            if connect:
                branch_x = float(np.mean(
                    [leaf_fraction(i) for i, leaf in enumerate(leaves)
                     if int(label_array[leaf]) == family]))
                fig.add_artist(Line2D(
                    [x0 + box_w / 2.0, branch_x],
                    [row_bottom + row_h + 0.004, tree_bottom - 0.004],
                    color=cmap(0.72), lw=0.9, ls=(0, (4, 3)), alpha=0.75,
                    zorder=3))

            share = ", ".join(f"CH{c} {composition[c]}"
                              for c in sorted(composition))
            fig.text(x0 + box_w / 2.0, row_bottom - 0.008, share,
                     ha="center", va="top", fontsize=5.6, color="0.4")
            drawn.append({"family": int(family), "n": len(members),
                          "by_channel": composition})
        return drawn, skipped

    info_families, skipped = draw_row(
        labels, panel_bottom, panel_h,
        name=f"coarse cut — {tree['k']} families", fontsize=8.0)
    fine_families, fine_skipped = draw_row(
        tree["fine_labels"], fine_bottom, fine_h,
        name=f"fine cut — {tree['fine_k']} families", fontsize=6.5,
        parent_labels=labels, connect=False)
    if not info_families:
        return None, {"reason": "no family large enough to draw"}
    drawable = info_families

    fig.text(left, 0.006,
             f"{len(info_families)} coarse and {len(fine_families)} fine"
             " families drawn"
             + (f"; {skipped + fine_skipped} with fewer than"
                f" {MIN_PANEL_MEMBERS} members counted but not drawn"
                if skipped + fine_skipped else "")
             + "  ·  member opacity falls with family size; the solid haloed"
               " line is the medoid (the real member closest to the centre,"
               " not an average)",
             ha="left", va="bottom", fontsize=7.5, color="0.35")

    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return str(out_path), {"n": n, "k": tree["k"],
                           "fine_k": tree["fine_k"],
                           "cophenetic": float(cophenetic),
                           "families": info_families,
                           "fine_families": fine_families,
                           "families_skipped": int(skipped + fine_skipped)}


# ===========================================================================
# 2. the rose, and the height-against-slope test
# ===========================================================================

def _gradient_table(rows, snippets):
    """Per-motif angle, slope, depth and channel, with short falls removed.

    Returns `(table, n_excluded)`. The exclusion is the `MIN_FALL_SAMPLES`
    floor: a one- or two-sample fall has no measurable gradient and would
    otherwise sit in the rose at an angle set by the sample spacing.
    """
    by_id = {r["event_id"]: r for r in rows}
    long_enough = [r for r in rows
                   if float(r.get("fall_duration_s", 0.0))
                   * float(r["fs"]) >= MIN_FALL_SAMPLES]
    n_excluded = len(rows) - len(long_enough)
    if not long_enough:
        return None, n_excluded

    data = dg.rose_data(long_enough, snippets, scale="raw",
                        field="max_slope_mv_s", split_by="span_key")
    if not data["n"]:
        return None, n_excluded

    angles = np.asarray(data["angles"], dtype=float)
    gradients = data["gradients"]
    depths, channels, slopes, durations = [], [], [], []
    for gradient in gradients:
        row = by_id[gradient["event_id"]]
        depths.append(abs(float(row["drop_depth_mv"])))
        channels.append(int(row["channel"]))
        slopes.append(float(gradient["max_slope_mv_s"]))
        durations.append(float(row["fall_duration_s"]))

    # A drop whose steepest sample over onset->trough is not NEGATIVE never
    # actually descends in the detrended trace, whatever its raw depth
    # says. Its angle falls outside the rose's [-90, 0] range, so the two
    # roses were already silently dropping it while the scatter still drew
    # it - the panels described different populations. Excluded here, once,
    # for every panel, and counted.
    falling = np.asarray(slopes, dtype=float) < 0.0
    n_not_falling = int((~falling).sum())

    return dict(angles=angles[falling],
                depths=np.asarray(depths, dtype=float)[falling],
                channels=np.asarray(channels, dtype=int)[falling],
                slopes=np.asarray(slopes, dtype=float)[falling],
                durations=np.asarray(durations, dtype=float)[falling],
                n_not_falling=n_not_falling,
                data=data), n_excluded


def _bootstrap_rho(x, y, n_boot=2000, seed=0):
    """Percentile CI for Spearman rho, so the number carries its own error."""
    rng = np.random.default_rng(seed)
    n = len(x)
    if n < 8:
        return (float("nan"), float("nan"))
    stats = []
    for _ in range(int(n_boot)):
        pick = rng.integers(0, n, n)
        if len(np.unique(x[pick])) < 3 or len(np.unique(y[pick])) < 3:
            continue
        stats.append(spearmanr(x[pick], y[pick]).statistic)
    if not stats:
        return (float("nan"), float("nan"))
    return (float(np.percentile(stats, 2.5)),
            float(np.percentile(stats, 97.5)))


def plot_rose(rows, snippets, out_path, *, title, n_bins=18):
    """Rose by channel, rose by drop height, and height against angle.

    The third panel is the one that answers the question the first two
    only illustrate: it reports Spearman rho between |drop height| and
    fall angle with a p-value and a bootstrap CI.
    """
    built, n_excluded = _gradient_table(rows, snippets)
    if built is None:
        return None, {"reason": "no motif had a measurable gradient",
                      "n_excluded_short": int(n_excluded)}
    style7.apply_style()

    angles = built["angles"]
    depths = built["depths"]
    channels = built["channels"]
    degrees = np.rad2deg(angles)

    durations = built["durations"]

    fig = plt.figure(figsize=(22.0, 7.6))
    ax_ch = fig.add_subplot(1, 4, 1, projection="polar")
    ax_h = fig.add_subplot(1, 4, 2, projection="polar")
    ax_s = fig.add_subplot(1, 4, 3)
    ax_d = fig.add_subplot(1, 4, 4)

    lo, hi = -np.pi / 2.0, 0.0
    edges = np.linspace(lo, hi, int(n_bins) + 1)
    centres = (edges[:-1] + edges[1:]) / 2.0
    width = edges[1] - edges[0]

    def setup_polar(ax, heading):
        ax.set_theta_zero_location("E")
        ax.set_theta_direction(1)
        ax.set_thetamin(-90)
        ax.set_thetamax(0)
        ax.set_xticks(np.deg2rad([-90, -75, -60, -45, -30, -15, 0]))
        ax.set_xticklabels(["-90°\nvertical", "-75°", "-60°", "-45°",
                            "-30°", "-15°", "0°\nflat"], fontsize=7.5)
        ax.tick_params(axis="y", labelsize=6.5)
        ax.grid(alpha=0.25, lw=0.6)
        ax.set_title(heading, fontsize=10, pad=16)

    # -- panel 1: by channel ------------------------------------------------
    setup_polar(ax_ch, "1. fall angle, stacked by channel")
    bottoms = np.zeros(int(n_bins))
    present = sorted(set(channels.tolist()))
    for channel in present:
        counts, _ = np.histogram(angles[channels == channel], bins=edges)
        ax_ch.bar(centres, counts, width=width * 0.92, bottom=bottoms,
                  color=channel_colour(channel), edgecolor="white",
                  linewidth=0.4, alpha=0.92,
                  label=f"CH{channel} (n={int((channels == channel).sum())})")
        bottoms = bottoms + counts
    ax_ch.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2,
                 fontsize=7.5, frameon=False)

    # -- panel 2: by drop-height quartile -----------------------------------
    setup_polar(ax_h, "2. the same falls, by drop height")
    quartiles = np.nanpercentile(depths, [25, 50, 75])
    height_band = np.digitize(depths, quartiles)
    band_cmap = plt.get_cmap("viridis")
    band_names = [f"Q1  < {quartiles[0]:.2f} mV",
                  f"Q2  {quartiles[0]:.2f}–{quartiles[1]:.2f}",
                  f"Q3  {quartiles[1]:.2f}–{quartiles[2]:.2f}",
                  f"Q4  > {quartiles[2]:.2f} mV"]
    bottoms = np.zeros(int(n_bins))
    for band in range(4):
        counts, _ = np.histogram(angles[height_band == band], bins=edges)
        ax_h.bar(centres, counts, width=width * 0.92, bottom=bottoms,
                 color=band_cmap(band / 3.0), edgecolor="white",
                 linewidth=0.4, alpha=0.92, label=band_names[band])
        bottoms = bottoms + counts
    ax_h.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2,
                fontsize=7.5, frameon=False, title="drop height",
                title_fontsize=7.5)

    # -- panel 3: the actual test -------------------------------------------
    rho, p_value = spearmanr(depths, degrees)
    ci_lo, ci_hi = _bootstrap_rho(depths, degrees)

    for channel in present:
        mask = channels == channel
        ax_s.scatter(degrees[mask], depths[mask], s=11, alpha=0.45,
                     color=channel_colour(channel), linewidths=0,
                     label=f"CH{channel}")
    # Median height per angle bin: the trend, without assuming a line.
    bin_index = np.digitize(degrees, np.rad2deg(edges)) - 1
    xs, ys = [], []
    for b in range(int(n_bins)):
        mask = bin_index == b
        if mask.sum() >= 5:
            xs.append(float(np.rad2deg(centres[b])))
            ys.append(float(np.median(depths[mask])))
    if len(xs) >= 2:
        ax_s.plot(xs, ys, color="#111111", lw=2.0, marker="o", ms=4,
                  zorder=6, label="median height per angle bin",
                  path_effects=[path_effects.Stroke(linewidth=4.0,
                                                    foreground="white"),
                                path_effects.Normal()])
    ax_s.set_yscale("log")
    ax_s.set_xlabel("fall angle (degrees; -90° = vertical, 0° = flat)")
    ax_s.set_ylabel("drop height |depth| (mV, log)")
    ax_s.legend(fontsize=7.5, frameon=False, loc="best")
    ax_s.grid(alpha=0.2, lw=0.6)
    for side in ("top", "right"):
        ax_s.spines[side].set_visible(False)

    steeper = "steeper" if rho < 0 else "shallower"
    verdict = ("no usable relationship" if not np.isfinite(rho)
               else "NO relationship worth reporting" if abs(rho) < 0.1
               else f"WEAK: bigger drops fall {steeper}" if abs(rho) < 0.3
               else f"MODERATE: bigger drops fall {steeper}" if abs(rho) < 0.5
               else f"STRONG: bigger drops fall {steeper}")
    ax_s.set_title(
        f"3. drop height against fall angle\n"
        f"Spearman ρ = {rho:+.3f}  (95% CI {ci_lo:+.3f} to {ci_hi:+.3f})\n"
        f"p = {p_value:.2g},  n = {len(depths)}",
        fontsize=9.5, pad=8)

    # -- panel 4: is panel 3 just arithmetic? -------------------------------
    #
    # A fall's slope is its depth over its duration. If duration were the
    # SAME for every drop, "bigger drops are steeper" would be true by
    # construction and would say nothing about the biology. The only way to
    # tell the two apart is to look at duration against depth directly.
    #
    #   duration independent of depth (exponent 0)  -> slope ∝ depth, the
    #       correlation in panel 3 is arithmetic
    #   duration ∝ depth (exponent 1)               -> slope is constant,
    #       and panel 3 would show nothing
    #
    # The measured exponent says which regime the data is in, and that is
    # the honest answer to "are drop heights grouped by drop slope".
    positive = (depths > 0) & (durations > 0)
    log_depth = np.log10(depths[positive])
    log_duration = np.log10(durations[positive])
    fit = linregress(log_depth, log_duration)
    rho_dd, p_dd = spearmanr(depths[positive], durations[positive])

    for channel in present:
        mask = (channels == channel)[positive]
        ax_d.scatter(depths[positive][mask], durations[positive][mask],
                     s=11, alpha=0.40, color=channel_colour(channel),
                     linewidths=0)
    grid = np.linspace(log_depth.min(), log_depth.max(), 50)
    ax_d.plot(10 ** grid, 10 ** (fit.intercept + fit.slope * grid),
              color="#111111", lw=2.0, zorder=6,
              label=f"fit: duration ∝ depth^{fit.slope:.2f}",
              path_effects=[path_effects.Stroke(linewidth=4.0,
                                                foreground="white"),
                            path_effects.Normal()])
    # The two regimes, anchored at the median point, for reference.
    anchor_x, anchor_y = np.median(depths[positive]), np.median(durations[positive])
    ax_d.plot(10 ** grid, anchor_y * np.ones_like(grid), color="#b8336a",
              lw=1.4, ls="--", alpha=0.9,
              label="exponent 0: slope ∝ depth (trivial)")
    ax_d.plot(10 ** grid, anchor_y * (10 ** grid) / anchor_x, color="#1b9e77",
              lw=1.4, ls=":", alpha=0.9,
              label="exponent 1: slope constant")
    ax_d.set_xscale("log")
    ax_d.set_yscale("log")
    ax_d.set_xlabel("drop height |depth| (mV, log)")
    ax_d.set_ylabel("fall duration (s, log)")
    ax_d.legend(fontsize=7.0, frameon=False, loc="best")
    ax_d.grid(alpha=0.2, lw=0.6)
    for side in ("top", "right"):
        ax_d.spines[side].set_visible(False)

    if fit.slope < 0.25:
        reading = ("duration barely grows with depth — so panel 3 is mostly"
                   " ARITHMETIC (slope = depth / duration)")
    elif fit.slope > 0.75:
        reading = ("duration grows nearly in step with depth — slope is"
                   " roughly size-independent")
    else:
        reading = ("duration grows with depth, but sub-linearly — panel 3 is"
                   " part real, part arithmetic")
    ax_d.set_title(
        f"4. THE CONTROL: fall duration against drop height\n"
        f"duration ∝ depth$^{{{fit.slope:.3f}}}$   (r² = {fit.rvalue ** 2:.3f})\n"
        f"Spearman ρ = {rho_dd:+.3f},  p = {p_dd:.2g}",
        fontsize=9.5, pad=8)

    fig.suptitle(
        f"{title}\n"
        f"angle = arctan(max fall slope / 1.00 mV per s) — the reference is"
        f" stated, not implied"
        + (f"  ·  {n_excluded} excluded: fall shorter than"
           f" {MIN_FALL_SAMPLES} samples" if n_excluded else "")
        + (f"  ·  {built['n_not_falling']} excluded: steepest sample not"
           " descending" if built["n_not_falling"] else ""),
        fontsize=11)
    fig.tight_layout(rect=[0, 0.075, 1, 0.86])
    fig.text(0.5, 0.038,
             f"PANEL 3 SAYS: {verdict}.", ha="center", va="center",
             fontsize=10.5, fontweight="bold", color="#111111")
    fig.text(0.5, 0.012,
             f"PANEL 4 SAYS: {reading}.", ha="center", va="center",
             fontsize=10.5, color="#7a1f3d")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)

    per_channel = {}
    for channel in present:
        mask = channels == channel
        per_channel[f"CH{channel}"] = {
            "n": int(mask.sum()),
            "median_angle_deg": float(np.median(degrees[mask])),
            "median_depth_mv": float(np.median(depths[mask])),
            "mean_angle_deg": float(np.rad2deg(
                dg.circular_mean(angles[mask]))),
            "resultant_length": float(dg.resultant_length(angles[mask])),
        }
    return str(out_path), {
        "n": int(len(depths)),
        "n_excluded_short_fall": int(n_excluded),
        "n_excluded_not_falling": int(built["n_not_falling"]),
        "spearman_rho_depth_vs_angle": float(rho),
        "spearman_p": float(p_value),
        "rho_ci95": [ci_lo, ci_hi],
        "verdict": verdict,
        "duration_vs_depth_exponent": float(fit.slope),
        "duration_vs_depth_r2": float(fit.rvalue ** 2),
        "spearman_rho_depth_vs_duration": float(rho_dd),
        "control_reading": reading,
        "per_channel": per_channel,
        "height_quartiles_mv": [float(q) for q in quartiles],
    }


# ===========================================================================
# 3. the family atlas
# ===========================================================================

def plot_family_atlas(rows, snippets, out_path, *, title, tree=None,
                      max_families=8, n_cols=4):
    """Every motif in the run, one panel per family, plus a composition bar.

    Same tree and same cut as the dendrogram, so this is a second view of
    one grouping rather than a second grouping.
    """
    tree = tree or build_tree(rows, snippets, max_families=max_families)
    if tree is None:
        return None, {"reason": "fewer than 6 motifs had waveforms"}
    style7.apply_style()

    keep, labels, features = tree["keep"], tree["labels"], tree["features"]
    fine_labels = tree["fine_labels"]
    n = len(keep)

    def blocks_of(label_array):
        families = sorted({int(f) for f in label_array},
                          key=lambda f: -int((label_array == f).sum()))
        members_of = {f: [i for i in range(n) if int(label_array[i]) == f]
                      for f in families}
        drawable = [f for f in families
                    if len(members_of[f]) >= MIN_PANEL_MEMBERS]
        return families, members_of, drawable

    families, members_of, drawable = blocks_of(labels)
    fine_all, fine_members_of, fine_drawable = blocks_of(fine_labels)
    if not drawable:
        return None, {"reason": "no family large enough"}

    # The coarse cut on one block of rows, the fine cut underneath it, so
    # the atlas carries the same two readings the dendrogram now draws.
    n_cols = int(min(n_cols, max(len(drawable), len(fine_drawable))))
    coarse_rows = int(np.ceil(len(drawable) / n_cols))
    fine_rows = int(np.ceil(len(fine_drawable) / n_cols)) if fine_drawable else 0
    n_rows = coarse_rows + fine_rows
    # Explicit margins, not `tight_layout`: the composition bar under each
    # panel is a second axes in the same column, and tight_layout treats
    # the pair as unrelated and warns that it cannot lay them out. Fixed
    # spacing also keeps the panels the same size run to run.
    fig, axes = plt.subplots(
        n_rows * 2, n_cols,
        figsize=(4.3 * n_cols, 3.9 * n_rows),
        gridspec_kw=dict(height_ratios=[6, 1] * n_rows, hspace=0.55,
                         wspace=0.26))
    axes = np.atleast_2d(axes)
    # Reserve a fixed number of INCHES for the two-line suptitle plus each
    # panel's own two-line title, then convert to a figure fraction. A
    # fraction alone would shrink the reserved band as rows are added and
    # the titles would collide again at n_rows > 1.
    fig_h = 3.9 * n_rows
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.06,
                        top=1.0 - (1.15 / fig_h))

    channels_present = sorted({int(r["channel"]) for r in keep})
    info_families = []

    plan = ([(f, members_of[f], labels, "coarse", i)
             for i, f in enumerate(drawable)]
            + [(f, fine_members_of[f], fine_labels, "fine",
                coarse_rows * n_cols + i)
               for i, f in enumerate(fine_drawable)])

    for family, members, label_array, which, index in plan:
        row_i, col_i = divmod(index, n_cols)
        ax = axes[row_i * 2, col_i]
        ax_bar = axes[row_i * 2 + 1, col_i]
        # A fine family is coloured by the coarse family it came out of.
        hue_family = (int(labels[members[0]]) if which == "fine" else family)
        _, cmap = style7.family_ramp(hue_family - 1)

        draw_family_panel(ax, members, keep, snippets, features, cmap,
                          show_axes=True)

        depths = [abs(float(keep[m]["drop_depth_mv"])) for m in members]
        falls = [float(keep[m]["fall_duration_s"]) for m in members]
        ax.set_title(
            f"family {family}  ·  n={len(members)}\n"
            f"median depth {np.median(depths):.3g} mV  ·  "
            f"median fall {np.median(falls):.3g} s",
            fontsize=9, color=cmap(0.95))
        ax.set_xlabel("s from onset", fontsize=7)
        ax.set_ylabel("mV", fontsize=7)

        composition = {c: 0 for c in channels_present}
        for leaf in members:
            composition[int(keep[leaf]["channel"])] += 1
        total = max(sum(composition.values()), 1)
        offset = 0.0
        for channel in channels_present:
            share = composition[channel] / total
            if share <= 0:
                continue
            ax_bar.barh([0], [share], left=[offset],
                        color=channel_colour(channel), height=0.75,
                        edgecolor="white", linewidth=0.8)
            if share > 0.09:
                ax_bar.text(offset + share / 2.0, 0, f"CH{channel}",
                            ha="center", va="center", fontsize=6.5,
                            color="white", fontweight="bold")
            offset += share
        ax_bar.set_xlim(0, 1)
        ax_bar.set_ylim(-0.5, 0.5)
        ax_bar.set_xticks([])
        ax_bar.set_yticks([])
        for spine in ax_bar.spines.values():
            spine.set_visible(False)
        dominant = max(composition, key=composition.get)
        ax_bar.set_xlabel(
            f"channel mix — {100 * composition[dominant] / total:.0f}%"
            f" CH{dominant}", fontsize=6.8, color="0.35", labelpad=2)

        info_families.append({
            "cut": which, "family": int(family), "n": len(members),
            "by_channel": {f"CH{c}": composition[c] for c in channels_present},
            "median_depth_mv": float(np.median(depths)),
            "median_fall_s": float(np.median(falls)),
        })

    used = {entry[4] for entry in plan}
    for index in range(n_rows * n_cols):
        if index in used:
            continue
        row_i, col_i = divmod(index, n_cols)
        axes[row_i * 2, col_i].set_visible(False)
        axes[row_i * 2 + 1, col_i].set_visible(False)

    fig.suptitle(
        f"{title}\n{n} motifs over {len(channels_present)} channels, grouped"
        f" by the same cut of the same tree the dendrogram draws"
        f"  ·  {len(drawable)} of {len(families)} families have at least"
        f" {MIN_PANEL_MEMBERS} members",
        fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.955])
    fig.savefig(out_path, dpi=190)
    plt.close(fig)
    return str(out_path), {"n": n, "k": tree["k"],
                           "fine_k": tree["fine_k"],
                           "families": info_families}
