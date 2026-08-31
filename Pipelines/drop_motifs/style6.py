"""
style6.py
==========
The shared drawing decisions for the drop_motifs6 figure set, and the
four numeric fixes every figure in it depends on.

This module holds no figures. It holds the things that were wrong in
`drop_motifs5` and are fixed once here rather than five times across the
drawing modules - because each of them was wrong in exactly one place and
still spoiled every plot downstream.

The four fixes
--------------
1. `baseline_level` - align on the FLAT SECTION before the drop, not on
   the single sample at the onset index. `overlays5` subtracted
   `values[onset]`, one sample, which is a noise draw: on catalogue ID 8
   that put four traces at four different pre-drop heights in a panel
   whose whole claim is that they start together. The median over the
   pre-onset run is the same operation the older `figures.event_trace`
   already used and got right.

2. `common_window` - one window length for every motif in a set. The
   detector brackets each event on its own UP runs, so every window is a
   different length by construction, and an overlay of them is a set of
   traces that stop at different places for reasons that have nothing to
   do with the motif. The fix is the operator's: keep detection as it is,
   then cut every window to the SMALLEST common extent, measured
   separately before and after the onset so the drops stay aligned.

3. `outlier_mask` / `family_ylim` - a robust flag on drop depth, and
   y-limits computed from the inliers ONLY. An outlier is still drawn,
   de-emphasised, and is allowed to run off the top or bottom of the
   axes; what it is not allowed to do is set the scale and squash the
   family it is an outlier of. Nothing is silently dropped - the count is
   returned so the caller can state it.

4. `TIME_CMAP` - a blue-green ramp. Yellow is not usable in the report
   this feeds, and `plasma` ends in it. This ramp is `viridis` truncated
   below its yellow end, so it keeps viridis's perceptual uniformity and
   its greyscale-safety while never reaching the excluded hue.

Line weights
------------
`LW` scales every line in the set. It is 1.4 rather than 1.0 because
these figures are read at report size, where the 0.5-0.9 pt lines of the
previous set disappear. Every drawing module multiplies by `LW` rather
than hard-coding a width, so the whole set restyles from one number.
"""

import numpy as np
from matplotlib import colors
from matplotlib import pyplot as plt

# ---------------------------------------------------------------------------
# line weights
# ---------------------------------------------------------------------------

LW = 1.4
# The global multiplier: +40%, the middle of the operator's 30-50% range.
#
# The BASE widths below are the ones drop_motifs5 actually drew with, kept
# here as named constants so the boost is a single arithmetic claim that a
# test can check. Multiplying a base by `LW` is the only way a width is
# set in this figure set - nothing hard-codes a number, so the whole set
# restyles from `LW` alone.

BASE_TRACE = 0.9          # overlays5 drew a pure overlay trace at 0.9 pt
BASE_SIGNAL = 0.5         # ... and the whole-span background at 0.5 pt
BASE_MEDOID = 1.5
BASE_FAMILY = 0.7
BASE_OUTLIER = 0.7
BASE_TREE = 1.1
BASE_RULE = 0.9

LW_TRACE = BASE_TRACE * LW        # one motif in an overlay
LW_SIGNAL = BASE_SIGNAL * LW      # the whole-span background trace
LW_MEDOID = BASE_MEDOID * LW      # the representative trace on a cluster panel
LW_FAMILY = BASE_FAMILY * LW      # a family member behind a medoid
LW_OUTLIER = BASE_OUTLIER * LW    # a flagged outlier, drawn de-emphasised
LW_TREE = BASE_TREE * LW          # dendrogram links
LW_RULE = BASE_RULE * LW          # onset markers, cut lines, axis rules

ALPHA_TRACE = 0.85
ALPHA_FAMILY = 0.28
ALPHA_OUTLIER = 0.40

# ---------------------------------------------------------------------------
# colour
# ---------------------------------------------------------------------------

# Deep blue -> teal -> green, built explicitly rather than truncated from
# a shipped map. Three candidates were measured first and all three failed
# on a property that matters here:
#
#   viridis[0.04:0.62]  starts dark PURPLE, not blue - which is the half
#                       of the purple-yellow ramp being replaced
#   YlGnBu_r[:0.5]      ends cyan; blue is still the dominant channel at
#                       the "green" end, so the ramp has no green in it
#   GnBu_r[:0.6]        ends at luminance 0.77, near-white, and a trace in
#                       it is invisible against the page
#
# These five stops are blue-dominant at the start and green-dominant at
# the end, monotone in luminance from 0.22 to 0.57 (so the ramp still
# reads as an ordering in greyscale and in print), and reach no yellow.
TIME_CMAP_STOPS = (
    "#0B3D91",   # deep blue
    "#1668B0",   # blue
    "#128A8A",   # teal
    "#1FA35C",   # green
    "#4FBF52",   # bright green
)


def time_cmap(n=256):
    """The blue-green ramp, as a colormap object."""
    return colors.LinearSegmentedColormap.from_list(
        "bluegreen6", list(TIME_CMAP_STOPS), N=n)


TIME_CMAP = time_cmap()

OUTLIER_COLOUR = "#b3411f"    # flagged as an outlier; drawn, not counted in scale
IMPURE_COLOUR = "#c1272d"     # window holds more than one fall
MEAN_COLOUR = "#c1272d"       # the mean-direction vector on a rose
RULE_COLOUR = "#3d3d3d"
SIGNAL_COLOUR = "0.25"

# Categorical, for span identity. Unchanged from drop_motifs5: span
# identity is not a quantity and must not be drawn on a ramp.
SPAN_CMAP = "tab20"
_TAB20_ORDER = tuple(range(0, 20, 2)) + tuple(range(1, 20, 2))


def span_colours(catalogue_ids):
    """`{catalogue_id: rgba}`, stable under the set of ids present."""
    mapper = plt.get_cmap(SPAN_CMAP)
    unique = sorted({int(c) for c in catalogue_ids})
    return {cid: mapper(_TAB20_ORDER[i % 20] / 19.0)
            for i, cid in enumerate(unique)}


def time_colours(onsets_h, lo=0.0, hi=1.0):
    """One blue-green colour per event, by position in the span.

    Returns `(colours, norm)`. The norm is what a colourbar is built from,
    so the bar and the traces provably share one mapping.
    """
    onsets = np.asarray(onsets_h, dtype=float)
    if onsets.size == 0:
        return [], None
    low, high = float(onsets.min()), float(onsets.max())
    if high - low <= 0:
        fractions = np.full(onsets.shape, 0.5)
    else:
        fractions = (onsets - low) / (high - low)
    cols = [TIME_CMAP(lo + (hi - lo) * f) for f in fractions]
    return cols, colors.Normalize(vmin=low, vmax=high)


# ---------------------------------------------------------------------------
# fix 1: baseline
# ---------------------------------------------------------------------------

MIN_BASELINE_SAMPLES = 3
BASELINE_FRACTION = 0.5
# The flat run is measured over the LATTER half of the pre-onset region by
# default. The earlier half of a window can still hold the tail of the
# previous event's recovery, and including that pulls the level away from
# the one the drop actually starts from.


def baseline_level(values, onset, *, fraction=BASELINE_FRACTION):
    """The level of the flat section immediately before the drop.

    Median, not mean: a pre-onset region that clips the tail of a previous
    recovery has a skewed distribution, and the median is the estimator
    that ignores the tail rather than averaging it in.

    Falls back to the onset sample only when there is no pre-onset region
    to measure - a window that starts at its own onset. That is the case
    `overlays5` applied to every window.
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0
    onset = int(np.clip(onset, 0, values.size - 1))
    if onset < MIN_BASELINE_SAMPLES:
        return float(values[onset])
    start = int(onset * (1.0 - fraction))
    start = min(start, onset - MIN_BASELINE_SAMPLES)
    return float(np.median(values[max(0, start):onset]))


def aligned_trace(values, onset, fs, *, baseline_removed=True):
    """`(t_from_onset_s, values_mV)` for one motif.

    Time is seconds from the onset and is never normalised by the event's
    own duration: a shape drawn on its own time axis and one drawn on a
    shared one are different claims, and only the second can be read for
    how fast the drop was.
    """
    values = np.asarray(values, dtype=float)
    onset = int(np.clip(onset, 0, max(values.size - 1, 0)))
    t = (np.arange(values.size) - onset) / float(fs)
    if baseline_removed:
        values = values - baseline_level(values, onset)
    return t, values


# ---------------------------------------------------------------------------
# fix 2: one window length for the whole set
# ---------------------------------------------------------------------------

def common_window(pre_lengths, post_lengths, *, quantile=None):
    """`(pre, post)` samples every motif in a set can supply.

    The plain answer is the minimum on each side, which is what the
    operator asked for and what guarantees no motif is padded. `quantile`
    relaxes that: at 0.1 the shortest tenth are allowed to fall short and
    are trimmed by the caller instead, which stops one unusually tight
    window from cropping the whole set to nothing. The default is the
    strict minimum.
    """
    pre = np.asarray(pre_lengths, dtype=int)
    post = np.asarray(post_lengths, dtype=int)
    if pre.size == 0 or post.size == 0:
        return 0, 0
    if quantile:
        return (int(np.quantile(pre, quantile)),
                int(np.quantile(post, quantile)))
    return int(pre.min()), int(post.min())


def cut_to_common(values, onset, pre, post):
    """One motif cut to `pre` samples before its onset and `post` after.

    Returns `(cut_values, new_onset)`. The onset stays at index `pre` for
    every motif in the set, which is what makes the overlay aligned by
    construction rather than by the reader's eye.

    A motif shorter than asked for is padded with NaN rather than with an
    edge value: matplotlib draws no line through a NaN, so a trace that
    genuinely has no data there shows as absent instead of as a flat
    stretch that was never recorded.
    """
    values = np.asarray(values, dtype=float)
    onset = int(np.clip(onset, 0, max(values.size - 1, 0)))
    out = np.full(int(pre) + int(post), np.nan, dtype=float)

    take_pre = min(int(pre), onset)
    take_post = min(int(post), values.size - onset)
    out[int(pre) - take_pre:int(pre) + take_post] = \
        values[onset - take_pre:onset + take_post]
    return out, int(pre)


def uniform_set(traces, onsets, *, quantile=None):
    """Cut a whole set of motifs to one common window.

    `traces` and `onsets` are parallel; returns `(stacked, onset_index)`
    with `stacked` of shape `(n_motifs, pre + post)`. Every row shares an
    onset index, so a column of the array is the same time-from-onset for
    every motif - which is the property the overlays, the cluster panels
    and the feature matrix all assume and none of them previously had.
    """
    traces = [np.asarray(v, dtype=float) for v in traces]
    onsets = [int(o) for o in onsets]
    if not traces:
        return np.zeros((0, 0)), 0

    pre_lengths = [o for o in onsets]
    post_lengths = [len(v) - o for v, o in zip(traces, onsets)]
    pre, post = common_window(pre_lengths, post_lengths, quantile=quantile)
    pre, post = max(int(pre), 1), max(int(post), 2)

    rows = [cut_to_common(v, o, pre, post)[0] for v, o in zip(traces, onsets)]
    return np.vstack(rows), pre


# ---------------------------------------------------------------------------
# fix 3: outliers are drawn but do not set the scale
# ---------------------------------------------------------------------------

OUTLIER_MAD_MULT = 3.5
# Modified z-score threshold. 3.5 is Iglewicz and Hoaglin's published
# value for the MAD-based score and is used unchanged rather than tuned,
# so "outlier" here means the same thing it means in the literature.

_MAD_TO_SIGMA = 0.6745


def outlier_mask(values, *, mult=OUTLIER_MAD_MULT):
    """Boolean mask of robust outliers in a 1-D set of magnitudes.

    MAD rather than standard deviation, because the quantity being
    screened is exactly the one the outliers inflate: two events ten times
    the family depth pull a standard deviation far enough that they stop
    being outliers by their own test. The MAD does not move.

    All-`False` when fewer than four values or when the MAD is zero - with
    that little to go on, or with no spread at all, every point is
    reported as an inlier rather than an arbitrary one being singled out.
    """
    values = np.asarray(values, dtype=float)
    if values.size < 4:
        return np.zeros(values.size, dtype=bool)
    finite = np.isfinite(values)
    if finite.sum() < 4:
        return np.zeros(values.size, dtype=bool)

    median = np.median(values[finite])
    mad = np.median(np.abs(values[finite] - median))
    if mad <= 0:
        return np.zeros(values.size, dtype=bool)

    score = np.zeros(values.size, dtype=float)
    score[finite] = _MAD_TO_SIGMA * (values[finite] - median) / mad
    return np.abs(score) > float(mult)


def family_ylim(stacked, inlier_mask=None, *, pad=0.08):
    """y-limits from the INLIERS only, so an outlier cannot set the scale.

    The operator's instruction, stated exactly: an outlier may be drawn
    and may run off the axes, but the axes must be scaled to show the main
    family properly. Matplotlib clips a line to the axes by default, so
    drawing the outlier and then setting these limits is all that is
    needed - the trace leaves the frame and the family stays legible.

    Returns `None` when there is nothing finite to measure, which the
    caller passes to `set_ylim` as "leave it to autoscale".
    """
    stacked = np.atleast_2d(np.asarray(stacked, dtype=float))
    if stacked.size == 0:
        return None
    if inlier_mask is not None:
        inlier_mask = np.asarray(inlier_mask, dtype=bool)
        if inlier_mask.any():
            stacked = stacked[inlier_mask]

    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    low, high = float(finite.min()), float(finite.max())
    if high <= low:
        high = low + 1.0
    margin = (high - low) * float(pad)
    return low - margin, high + margin


# ---------------------------------------------------------------------------
# figure furniture
# ---------------------------------------------------------------------------

def apply_style():
    """Report-weight defaults. Called once per figure-drawing entry point."""
    plt.rcParams.update({
        "axes.linewidth": 0.9 * LW,
        "xtick.major.width": 0.8 * LW,
        "ytick.major.width": 0.8 * LW,
        "grid.linewidth": 0.6 * LW,
        "lines.solid_capstyle": "round",
        "axes.grid": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })


def strip_axis(ax):
    """No ticks, no spines, transparent - for a thumbnail."""
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.patch.set_alpha(0.0)
