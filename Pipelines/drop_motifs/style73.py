"""
style73.py
===========
drop_motifs7.3. Three pieces of geometry, all pure - no figure is built
here, which is what lets each one be tested on its own.

1. THE PAGE IS FITTED TO THE PANELS
-----------------------------------
7.2 locked each panel's height-to-width ratio and then dropped it into a
fixed gridspec cell. `set_aspect` answers a box it cannot satisfy by
SHRINKING the axes inside its cell, so on catalogue ID 22 the five family
panels came out as slivers - one of them about an inch wide - adrift in a
page of white space, and the last row, holding a single panel, sat hard
against the left margin instead of under the middle of the page.

The fix is ordering: solve each panel's box first (`panel_box`), then make
a figure that size and place the panels in it (`centred_row`). Nothing
shrinks, because nothing is asked to fit a cell it does not fit.

`panel_box` also enforces a lower bound on width, because a faithfully
drawn sliver is still unreadable. Crossing that bound is a distortion on
top of whatever `style7.span_locked_aspect` already applied, so it is
returned and captioned rather than absorbed.

2. THE MERGE-DISTANCE AXIS IS RANKED, NOT LINEAR
------------------------------------------------
Ward merge distances are strongly right-skewed: ID 22's root merge sits at
22 with everything else below 3, so on a linear axis one link occupied
most of an A4 page and the forty merges that carry the structure were
crushed into the bottom seventh. `rank_scale_functions` builds a monotone
map that gives every merge a share of the height, blended with the linear
map so distance is still readable as distance.

The axis stops being proportional, so it is tick-labelled with actual
merge heights rather than with a regular grid.

3. THE ROSE'S MEAN IS ON THE ROSE
---------------------------------
It was a legend key: a horizontal purple swatch in the bottom-left corner
labelled "mean -9.2 degrees". A horizontal swatch cannot express an angle,
which is the one thing the number is about. `mean_marker` returns polar
coordinates on the ray itself, so the marker and its label are at the mean
angle by construction.
"""

import numpy as np

# ---------------------------------------------------------------------------
# 1. panel geometry
# ---------------------------------------------------------------------------

# The box a shape-locked motif panel is allowed to occupy, in inches.
# Height leads: for these motifs the tall panel is the readable one, and
# the width follows from the shape.
PANEL_HEIGHT_IN = 5.0
PANEL_MAX_HEIGHT_IN = 6.5
PANEL_MIN_HEIGHT_IN = 2.2
PANEL_MIN_WIDTH_IN = 3.6
PANEL_MAX_WIDTH_IN = 8.6

# The one HARD rule. The four bounds above are goals: when a shape cannot
# satisfy them and still be itself, the shape wins to within this factor
# and the figure says by how much it lost.
#
# Which matters, because the first way to widen a narrow panel is not to
# stretch it - it is to make the whole panel BIGGER, growing height and
# width together. That keeps the shape exact and is what the complaint
# ("too narrow and small to accurately assess") actually asks for.
# Stretching is the fallback for when the page has run out of height.
MAX_DISTORTION = 1.6

DEFAULT_BOX_IN = (5.2, 3.4)


def box_ratio(aspect, x_range, y_range):
    """height / width of the box that satisfies `aspect` exactly.

    `set_aspect(a)` means one y unit is drawn `a` times the display length
    of one x unit, so a box holding `x_range` by `y_range` at that aspect
    has height/width = a * y_range / x_range.
    """
    x_range, y_range, aspect = float(x_range), float(y_range), float(aspect)
    if not np.isfinite([aspect, x_range, y_range]).all() or x_range <= 0:
        return float("nan")
    return aspect * y_range / x_range


def panel_box(aspect, x_range, y_range, *,
              height_in=PANEL_HEIGHT_IN,
              max_height_in=PANEL_MAX_HEIGHT_IN,
              min_height_in=PANEL_MIN_HEIGHT_IN,
              min_width_in=PANEL_MIN_WIDTH_IN,
              max_width_in=PANEL_MAX_WIDTH_IN,
              max_distortion=MAX_DISTORTION):
    """`(width_in, height_in, fill_aspect, distortion)` for one panel.

    `fill_aspect` is what `set_aspect` must be given for the data to fill
    the returned box exactly, so the panel never shrinks inside it.

    `distortion` is `fill_aspect / aspect`: 1.0 when the box reproduces the
    shape, above 1 when the panel is drawn taller than the recording, below
    1 when it is drawn wider. It is a second departure on top of any
    compression `style7.span_locked_aspect` already reported, and the two
    are stated separately because they have different causes.
    """
    ratio = box_ratio(aspect, x_range, y_range)
    if not np.isfinite(ratio) or ratio <= 0:
        fallback = float(aspect) if float(aspect) > 0 else 1.0
        return DEFAULT_BOX_IN[0], DEFAULT_BOX_IN[1], fallback, 1.0

    height = float(height_in)
    width = height / ratio

    if width < min_width_in:
        # Grow the panel rather than stretch it: taller AND wider, shape
        # untouched, until the page height runs out.
        height = min(min_width_in * ratio, float(max_height_in))
        width = height / ratio
    elif width > max_width_in:
        width = float(max_width_in)
        height = width * ratio

    # Only now, with the panel as large as the page allows, is a stretch
    # considered - and only as far as the cap below permits.
    if width < min_width_in:
        width = min(float(min_width_in), width * max_distortion)
    if height < min_height_in:
        height = min(float(min_height_in), height * max_distortion)

    width = min(width, float(max_width_in))
    height = min(height, float(max_height_in))

    fill = (height / width) * (float(x_range) / float(y_range))
    distortion = fill / float(aspect)

    # The hard rule, enforced last so nothing above can slip past it.
    if distortion > max_distortion:
        height = width * ratio * max_distortion
    elif distortion < 1.0 / max_distortion:
        width = height / ratio * max_distortion

    fill = (height / width) * (float(x_range) / float(y_range))
    return width, height, fill, fill / float(aspect)


def distortion_caption(distortion):
    """What an extra stretch did, in words. Empty when there was none."""
    if not np.isfinite(distortion) or abs(distortion - 1.0) <= 0.02:
        return ""
    if distortion > 1.0:
        return (f"drawn {distortion:.2f}x taller than the recording "
                f"(panel widened to the readable minimum)")
    return (f"drawn {1.0 / distortion:.2f}x wider than the recording "
            f"(panel width capped)")


def shape_caption(true_ratio, compression, distortion):
    """The one statement a reader needs about proportion.

    Quoting `style7.fidelity_caption` and `distortion_caption` side by side
    reads as a contradiction - ID 3's overlay said "shape as in the
    recording (3.8:1)" on one line and "drawn 1.47x wider" on the next,
    both true and referring to different steps. This composes the two: what
    the panel actually shows, against what the recording holds.
    """
    if not np.isfinite(true_ratio) or compression <= 0 or distortion <= 0:
        return "shape not locked"
    drawn = true_ratio * distortion / compression
    if abs(np.log(drawn / true_ratio)) <= 0.02:
        return f"shape as in the recording ({true_ratio:.3g}:1 height-to-width)"
    return (f"most-departed panel drawn at {drawn:.3g}:1 height-to-width; "
            f"in the recording that motif is {true_ratio:.3g}:1")


def centred_row(widths, gap, total):
    """Left edges for a row of boxes, centred in `total`.

    7.2 left this to gridspec, which centres each panel in its own CELL -
    so a row holding one panel put it over the left third of the page and
    a row of two put a gutter down the middle wider than either panel.
    """
    widths = [float(w) for w in widths]
    if not widths:
        return []
    span = sum(widths) + float(gap) * (len(widths) - 1)
    cursor = max((float(total) - span) / 2.0, 0.0)
    lefts = []
    for width in widths:
        lefts.append(cursor)
        cursor += width + float(gap)
    return lefts


def row_span(widths, gap):
    """Total width a row of boxes needs, including the gaps between them."""
    widths = [float(w) for w in widths]
    if not widths:
        return 0.0
    return sum(widths) + float(gap) * (len(widths) - 1)


# ---------------------------------------------------------------------------
# 2. the merge-distance axis
# ---------------------------------------------------------------------------

# How far towards a pure rank axis to go. At 1.0 every merge gets an equal
# share of the height and the axis carries no sense of distance at all; at
# 0.0 it is the linear axis this replaces. 0.8 keeps a visible difference
# between a near merge and a far one while taking the root merge's
# monopoly away.
RANK_WEIGHT = 0.8


def _interp_extrapolate(values, knots, targets):
    """Piecewise-linear map, extended linearly past both ends.

    `np.interp` clamps outside its range, which would pile every padded
    value - the headroom above the root merge, the margin below zero -
    onto one line.
    """
    v = np.asarray(values, dtype=float)
    out = np.interp(v, knots, targets)

    low = v < knots[0]
    if low.any():
        slope = (targets[1] - targets[0]) / (knots[1] - knots[0])
        out = np.where(low, targets[0] + (v - knots[0]) * slope, out)
    high = v > knots[-1]
    if high.any():
        slope = (targets[-1] - targets[-2]) / (knots[-1] - knots[-2])
        out = np.where(high, targets[-1] + (v - knots[-1]) * slope, out)
    return out


def rank_scale_functions(heights, weight=RANK_WEIGHT):
    """`(forward, inverse)` for `ax.set_yscale("function", functions=...)`.

    Both are monotone increasing and are each other's inverse, which is
    what matplotlib requires of a function scale; violating either gives a
    silently unreadable axis rather than an error.
    """
    values = np.asarray(list(heights), dtype=float).ravel()
    values = np.unique(values[np.isfinite(values)])
    if values.size < 2:
        def identity(v):
            return np.asarray(v, dtype=float)
        return identity, identity

    knots = values if values[0] <= 0 else np.concatenate(([0.0], values))
    linear = (knots - knots[0]) / (knots[-1] - knots[0])
    ranked = np.linspace(0.0, 1.0, knots.size)
    targets = (1.0 - float(weight)) * linear + float(weight) * ranked
    # Scaled back onto the original range so limits and tick labels stay
    # in merge-distance units and only their SPACING changes.
    targets = knots[0] + targets * (knots[-1] - knots[0])
    targets = np.maximum.accumulate(targets)

    def forward(v):
        return _interp_extrapolate(v, knots, targets)

    def inverse(v):
        return _interp_extrapolate(v, targets, knots)

    return forward, inverse


def merge_ticks(heights, n=6):
    """A few actual merge heights to label a ranked axis with.

    A regular grid would imply the axis is proportional. Labelling real
    merges says what the axis is: an ordering with distances attached.
    """
    values = np.unique(np.asarray(list(heights), dtype=float))
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        return []
    # Identical motifs merge at a distance that is zero up to floating
    # error, and a tick reading "2.1e-15" says nothing to anyone.
    values = values[values > values.max() * 1e-6]
    if values.size == 0:
        return []
    if values.size <= n:
        return [float(v) for v in values]
    picks = np.linspace(0, values.size - 1, int(n)).round().astype(int)
    return [float(values[i]) for i in np.unique(picks)]


# ---------------------------------------------------------------------------
# 3. the rose's mean
# ---------------------------------------------------------------------------

# Where on its own ray the mean marker sits, as a fraction of the rose's
# longest bar. Past the bars so it is never buried under them.
MEAN_MARKER_FRACTION = 1.12
MEAN_LABEL_FRACTION = 1.20
MEAN_MIN_RADIUS = 1.0


def mean_marker(mean_deg, peak_radius):
    """Where to draw the mean direction and its label, in polar data
    coordinates.

    Returns `(theta, radius, label_theta, label_radius, rotation_deg)`.
    Both the marker and the text are ON the ray, so the figure cannot
    repeat 7.2's fault of stating the mean as a horizontal swatch in a
    corner - a shape that cannot express an angle.
    """
    theta = float(np.deg2rad(float(mean_deg)))
    peak = float(peak_radius)
    if not np.isfinite(peak) or peak <= 0:
        peak = MEAN_MIN_RADIUS
    radius = max(peak * MEAN_MARKER_FRACTION, MEAN_MIN_RADIUS)
    label_radius = max(peak * MEAN_LABEL_FRACTION, radius * 1.06)

    # Text laid along the ray, folded into the half turn that reads left
    # to right: at -80 degrees the unfolded rotation reads bottom-to-top.
    rotation = float(mean_deg) % 180.0
    if rotation > 90.0:
        rotation -= 180.0
    return theta, radius, theta, label_radius, rotation
