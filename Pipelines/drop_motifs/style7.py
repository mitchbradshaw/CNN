"""
style7.py
==========
What drop_motifs7 changes about how the figures look. Everything numeric
still comes from `style6` - the baseline rule, the common window, the
outlier screen - which is imported rather than restated.

Two changes, both from the operator's review of drop_motifs6.

1. ONE HUE PER FAMILY
---------------------
drop_motifs6 drew every overlay panel on the same blue-green ramp, so two
panels side by side looked alike and neither could be tied back to the
span plot above them. Each family (a scale band, or the inverted pass) now
gets its OWN hue, and its own gradient through time within that hue, and
its own colourbar. The shaded windows on the span plot use the same hue,
so a trace in the second panel and the stretch of signal it came from are
the same colour.

Red, yellow, black and white are excluded at the operator's request. That
costs the set its two conventional "attention" colours, so the things that
used them are re-cued rather than re-coloured:

  - impure windows were red; they are now a dashed grey, which reads as
    "set aside" without competing with a family hue
  - outliers were red; they are now a heavier dashed grey for the same
    reason

2. THE HEIGHT-TO-WIDTH RATIO IS FIXED, NOT FITTED
-------------------------------------------------
This is the substantive one. Every drop_motifs6 panel filled its axes,
which means the ratio between a millivolt and a second was whatever each
panel's own data extent happened to imply. A 3 mV event over 200 s and a
20 mV event over 3 s were drawn the same size and shape, and on ID 34 the
motifs flattened into near-horizontal lines.

Here one millivolt-per-second scale is chosen per figure and every panel
in that figure is locked to it (`set_aspect`, `adjustable="box"`). A motif
twice as steep as its neighbour is drawn twice as steep. Panels then stop
being uniform rectangles - a long shallow event gets a wide short box, a
fast deep one a narrow tall box - which is exactly the compensation the
operator asked for, and matplotlib shrinks the box within its cell rather
than overflowing, so nothing can run off the page.

The scale is derived from the span's own median event so that a typical
motif lands at a readable proportion, and it is stated on the figure. It
cannot be a global constant: these spans run from 3 s events to 2500 s
events, and one constant would render fifteen of the sixteen unreadable.
"""

import numpy as np
from matplotlib import colors
from matplotlib import pyplot as plt

from Pipelines.drop_motifs.style6 import (ALPHA_FAMILY, ALPHA_OUTLIER,  # noqa: F401
                                          ALPHA_TRACE, BASE_FAMILY,
                                          BASE_MEDOID, BASE_OUTLIER,
                                          BASE_RULE, BASE_SIGNAL, BASE_TRACE,
                                          BASE_TREE, LW, LW_FAMILY, LW_MEDOID,
                                          LW_OUTLIER, LW_RULE, LW_SIGNAL,
                                          LW_TRACE, LW_TREE, MIN_BASELINE_SAMPLES,
                                          OUTLIER_MAD_MULT, aligned_trace,
                                          apply_style, baseline_level,
                                          common_window, cut_to_common,
                                          family_ylim, outlier_mask,
                                          strip_axis, uniform_set)

# ---------------------------------------------------------------------------
# one hue per family
# ---------------------------------------------------------------------------

# Each ramp runs mid -> dark within a single hue, so a whole family reads
# as one colour while position in time stays legible along it. Neither end
# is near white (invisible on the page) or near black (excluded), and no
# ramp passes through red or yellow.
# Six, because spans here reach six scale bands and a pool of four made
# the fifth family repeat the first - two panels in one figure captioned
# "green", which is worse than no colour coding at all.
FAMILY_RAMPS = (
    ("green",  ("#7FD8A0", "#3FA96B", "#14532D")),
    ("blue",   ("#7FC4EA", "#2F7FBF", "#10395F")),
    ("purple", ("#C2A4E8", "#8257C4", "#452170")),
    ("teal",   ("#7FD6CE", "#2E9E95", "#0D4F4A")),
    ("indigo", ("#A6ABEA", "#5158C4", "#232870")),
    ("slate",  ("#9DB4CE", "#4E7396", "#1F3A52")),
)

# The inverted pass gets hues from outside the drop set, so a rise is
# never mistaken for another scale band of drops.
INVERTED_RAMPS = (
    ("orange", ("#F5BE86", "#D4813A", "#8A4A06")),
    ("pink",   ("#F0A9CB", "#C75E96", "#7D1F52")),
)

# Excluded on request: red, yellow, black, white. What used red now uses
# a neutral grey and is distinguished by dash pattern instead of hue.
IMPURE_COLOUR = "#8A8A8A"
IMPURE_DASH = (0, (4, 2))
OUTLIER_COLOUR = "#5F5F5F"
OUTLIER_DASH = (0, (1.5, 1.8))

RULE_COLOUR = "#3D3D3D"
SIGNAL_COLOUR = "0.30"
MEAN_COLOUR = "#5B2D90"      # was red; the rose's mean vector


def family_ramp(index, inverted=False):
    """`(name, colormap)` for family `index`.

    Drops and rises draw from disjoint pools, so the hue alone says which
    a panel is before the title is read.
    """
    pool = INVERTED_RAMPS if inverted else FAMILY_RAMPS
    name, stops = pool[int(index) % len(pool)]
    return name, colors.LinearSegmentedColormap.from_list(
        f"family_{name}", list(stops), N=256)


def family_colours(onsets_h, index, inverted=False, lo=0.0, hi=1.0):
    """One colour per event within a family, by position in the span.

    Returns `(colours, norm, cmap, name)`.
    """
    name, cmap = family_ramp(index, inverted=inverted)
    onsets = np.asarray(onsets_h, dtype=float)
    if onsets.size == 0:
        return [], None, cmap, name
    low, high = float(onsets.min()), float(onsets.max())
    if high - low <= 0:
        fractions = np.full(onsets.shape, 0.5)
    else:
        fractions = (onsets - low) / (high - low)
    cols = [cmap(lo + (hi - lo) * f) for f in fractions]
    return cols, colors.Normalize(vmin=low, vmax=high), cmap, name


# ---------------------------------------------------------------------------
# the height-to-width ratio
# ---------------------------------------------------------------------------

# The proportion a TYPICAL motif in a figure is drawn at: its depth over
# its fall duration, as displayed. Below 1 the median event is wider than
# it is tall, which suits a drop-and-recover shape; the point is not the
# number itself but that everything in the figure is measured against it.
TARGET_MEDIAN_RATIO = 0.55

# Bounds on the derived scale. Without them a span whose median event is
# nearly flat, or nearly instantaneous, asks for an axes box thousands of
# times longer in one direction than the other, and matplotlib answers by
# shrinking the box to a hairline.
MIN_SECONDS_PER_MV = 1e-4
MAX_SECONDS_PER_MV = 1e5


def seconds_per_mv(depths_mv, falls_s, target=TARGET_MEDIAN_RATIO):
    """The figure's millivolt-per-second scale, as an aspect number.

    Returned value `a` is what `set_aspect` wants: one millivolt of y is
    drawn `a` times the display length of one second of x. Derived so the
    MEDIAN event in the figure lands at `target` height-to-width, which
    makes the scale a property of the events rather than of the axis
    limits - the fault this replaces.

    Both medians are taken over the whole figure, not per panel, so the
    panels stay comparable to each other.
    """
    depths = np.abs(np.asarray(depths_mv, dtype=float))
    falls = np.abs(np.asarray(falls_s, dtype=float))
    good = np.isfinite(depths) & np.isfinite(falls) & (depths > 0) & (falls > 0)
    if not good.any():
        return 1.0
    median_depth = float(np.median(depths[good]))
    median_fall = float(np.median(falls[good]))
    aspect = float(target) * median_fall / median_depth
    return float(np.clip(aspect, MIN_SECONDS_PER_MV, MAX_SECONDS_PER_MV))


def apply_aspect(ax, aspect):
    """Lock one axes to the figure's millivolt-per-second scale.

    `adjustable="box"` so the BOX is reshaped to satisfy the scale and the
    data limits are left alone. The alternative, `adjustable="datalim"`,
    would silently widen the view to fit a fixed box - which is the
    fit-to-axes behaviour being removed.
    """
    if aspect and np.isfinite(aspect) and aspect > 0:
        ax.set_aspect(float(aspect), adjustable="box")


def aspect_caption(aspect):
    """A readable statement of the scale, for the figure."""
    if not aspect or not np.isfinite(aspect) or aspect <= 0:
        return "aspect not locked"
    if aspect >= 1:
        return f"height-to-width locked: 1 mV drawn as {aspect:.3g} s of width"
    return f"height-to-width locked: 1 s drawn as {1.0 / aspect:.3g} mV of height"
