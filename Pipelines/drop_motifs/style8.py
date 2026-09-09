"""
style8.py
==========
drop_motifs8. Two additions to `style7`/`style73`, both about the pooled
run over all sixteen spans.

1. HOW TALL A PANEL MAY BE DEPENDS ON HOW MUCH FIDELITY IS LEFT
---------------------------------------------------------------
7.2 capped every panel at `style7.MAX_PANEL_RATIO` (6:1). Measured over
the whole catalogue, the true height-to-width of a span's median motif
runs from 3.6:1 to 202:1:

    ID 35    3.58     drawn exactly
    ID 22   10.13     drawn at 6:1, compressed 1.7x
    ID 10   28.02     drawn at 6:1, compressed 4.7x
    ID 24   69.60     drawn at 6:1, compressed 11.6x
    ID 385 202.56     drawn at 6:1, compressed 34x

At the top of that range the cap is doing the worst of both things. The
panel is as tall and narrow as the rules allow - unreadable, which is what
the operator saw on ID 385 - while being thirty-four times away from the
recording, so the height is not buying any fidelity to pay for it.

`readable_max_ratio` therefore backs the cap off as the truth recedes: a
span still close to its true shape keeps the tall cap and the claim that
goes with it, and a span whose claim is already lost is drawn at a
proportion chosen for reading. It is monotone - more distortion never
buys a taller panel - and the figure states the true ratio either way, so
the drawn proportion is not carrying the claim.

2. ONE COLOUR PER SPAN
----------------------
The pooled dendrogram and rose put every span on one axis, so colour has
to say which span a motif came from rather than which family. Sixteen
colours are needed and only six family hues exist, so each hue is used at
two lightnesses. Red, yellow, black and white stay excluded, and the
assignment is by catalogue ID rather than by position, so running over a
subset does not recolour everything.
"""

import numpy as np
from matplotlib import colors as mcolors

from Pipelines.drop_motifs import style7

# ---------------------------------------------------------------------------
# 1. the readable cap
# ---------------------------------------------------------------------------

# The proportion a panel falls back to once its shape claim is gone.
# Not 1:1 - "as wide as it is tall" is its own false statement about a
# motif that is nothing of the kind - just a proportion that reads.
READABLE_RATIO = 2.0

# Compression, as a multiple, at which the backing-off starts and ends.
# Below `FAITHFUL` the panel is still close enough to the recording to be
# worth its height; at `LOST` the number on the caption is doing all the
# work and the picture may as well be legible.
FAITHFUL_COMPRESSION = 2.0
LOST_COMPRESSION = 16.0


def readable_max_ratio(true_ratio, max_ratio=None,
                       readable=READABLE_RATIO,
                       faithful=FAITHFUL_COMPRESSION,
                       lost=LOST_COMPRESSION):
    """The tallest proportion worth drawing, given `true_ratio`.

    Interpolated geometrically in the compression the cap would impose, so
    two spans a hair apart in true ratio are drawn a hair apart - a hard
    two-regime switch would put ID 25 and ID 24, which differ by 2%, at
    visibly different proportions.
    """
    cap = float(style7.MAX_PANEL_RATIO if max_ratio is None else max_ratio)
    ratio = float(true_ratio)
    if not np.isfinite(ratio) or ratio <= 0 or ratio <= cap:
        return cap

    compression = ratio / cap
    if compression <= faithful:
        return cap

    t = np.log(compression / faithful) / np.log(float(lost) / faithful)
    t = float(np.clip(t, 0.0, 1.0))
    return float(cap * (float(readable) / cap) ** t)


def span_locked_aspect(span_seconds, span_mv, width_in, height_in,
                       depths_mv, falls_s):
    """`style7.span_locked_aspect`, with the cap chosen by the span itself.

    Measured once to learn the true ratio, then again with the cap that
    ratio earns. The first call cannot be skipped: the cap is a function
    of the answer.
    """
    _, true_ratio, _ = style7.span_locked_aspect(
        span_seconds, span_mv, width_in, height_in, depths_mv, falls_s)
    if not np.isfinite(true_ratio):
        return style7.span_locked_aspect(
            span_seconds, span_mv, width_in, height_in, depths_mv, falls_s)
    return style7.span_locked_aspect(
        span_seconds, span_mv, width_in, height_in, depths_mv, falls_s,
        max_ratio=readable_max_ratio(true_ratio))


# ---------------------------------------------------------------------------
# 2. one colour per span
# ---------------------------------------------------------------------------

# Two samples along each family ramp, light then dark, giving twelve
# distinguishable colours from the six drop hues before the two inverted
# hues are needed. Every one inherits the ramps' exclusions.
_RAMP_STOPS = (0.30, 0.80)


def _palette():
    """Sixteen colours: each ramp sampled light, then each sampled dark."""
    pool = []
    for stop in _RAMP_STOPS:
        for index in range(len(style7.FAMILY_RAMPS)):
            _, cmap = style7.family_ramp(index)
            pool.append(cmap(stop))
        for index in range(len(style7.INVERTED_RAMPS)):
            _, cmap = style7.family_ramp(index, inverted=True)
            pool.append(cmap(stop))
    return pool


def _slot(catalogue_id):
    """A span's fixed position in the palette.

    Taken from the CATALOGUE's order, not from the order of whatever
    subset is being drawn. Keying on position within the argument - the
    obvious thing, and what this did first - means adding one span
    recolours every span after it, so a pooled figure and a per-span
    figure of the same motifs disagree.
    """
    from Pipelines.drop_motifs.spans5 import SPANS5

    catalogue = sorted(SPANS5)
    try:
        return catalogue.index(int(catalogue_id))
    except ValueError:
        return len(catalogue) + int(catalogue_id)


def span_colours(catalogue_ids):
    """`{catalogue_id: colour}`, stable under adding or removing spans."""
    pool = _palette()
    return {int(cid): pool[_slot(cid) % len(pool)]
            for cid in {int(v) for v in catalogue_ids}}


def span_legend_handles(catalogue_ids, colours=None):
    """Legend entries for a pooled figure, in catalogue order."""
    from matplotlib import pyplot as plt

    colours = colours or span_colours(catalogue_ids)
    return [plt.Line2D([0], [0], color=colours[cid], lw=6, label=f"ID {cid}")
            for cid in sorted(colours)]


def is_excluded_hue(colour):
    """True for red, yellow, black or white - the operator's exclusions.

    Kept here so the pooled palette is checked by the same rule the family
    ramps are, rather than by eye.
    """
    h, s, v = mcolors.rgb_to_hsv(mcolors.to_rgb(colour))
    if v <= 0.12 or v >= 0.95:
        return True
    if s <= 0.35:
        return False
    return min(h, 1.0 - h) < 15.0 / 360.0 or 0.12 < h < 0.20
