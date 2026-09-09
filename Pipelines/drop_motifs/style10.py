"""
style10.py
===========
One colour per SPECIES, and the accessibility rules that go with it.

drop_motifs8 needed one colour per span and drop_motifs9 one per channel.
This run's figures are about species, so species is what colour carries -
and because that is the claim the figures exist to make, colour alone is
never allowed to carry it. Every species-coded figure also carries the
species in a legend, and where a species appears as a line it carries a
dash pattern too, so the reading survives a colour-blind reader, a
greyscale print and a projector.

The four corpus labels collapse onto three species, and that collapse is
the point: `reishi_10hz` and `reishi_1hz` are the SAME organism at two
sampling rates. They therefore share a hue and differ only in lightness
and dash, so a figure in which the two reishi arms behave differently
reads immediately as a rate effect rather than as a species effect.

Hues come from `style7.FAMILY_RAMPS` rather than from a new palette, so
this figure set sits beside drop_motifs7-9's without a colour meaning two
things across the series. Red, yellow, black and white stay excluded, as
they have been since 7.
"""

import numpy as np
from matplotlib import colors as mcolors

from Pipelines.drop_motifs import style7, style8  # noqa: F401  (re-export)
from Pipelines.drop_motifs.corpora10 import (CORPUS_385, CORPUS_OYSTER,
                                             CORPUS_REISHI_1HZ,
                                             CORPUS_REISHI_10HZ, SPECIES_385,
                                             SPECIES_OYSTER, SPECIES_REISHI)

# Fixed order, never cycled: a figure drawn over two species must give
# them the same colours it gives them in a figure drawn over three.
SPECIES_ORDER = (SPECIES_OYSTER, SPECIES_385, SPECIES_REISHI)

SPECIES_COLOUR = {
    SPECIES_OYSTER: "#2F7FBF",     # blue, the mid stop of style7's blue ramp
    SPECIES_385: "#D4813A",        # orange, from the inverted pool - the
                                   # third species is the odd one out and
                                   # is drawn from outside the drop hues
    SPECIES_REISHI: "#14532D",     # green, dark stop
}

# Never colour-alone: every species also has a dash and a marker.
SPECIES_DASH = {
    SPECIES_OYSTER: "-",
    SPECIES_385: (0, (4, 2)),
    SPECIES_REISHI: (0, (1.5, 1.8)),
}

SPECIES_MARKER = {
    SPECIES_OYSTER: "o",
    SPECIES_385: "s",
    SPECIES_REISHI: "^",
}

# The two reishi arms share the species hue and separate by lightness, so
# "same organism, two rates" is visible before the legend is read.
CORPUS_COLOUR = {
    CORPUS_OYSTER: SPECIES_COLOUR[SPECIES_OYSTER],
    CORPUS_385: SPECIES_COLOUR[SPECIES_385],
    CORPUS_REISHI_10HZ: SPECIES_COLOUR[SPECIES_REISHI],
    CORPUS_REISHI_1HZ: "#3FA96B",          # the same green, two stops up
}

CORPUS_DASH = {
    CORPUS_OYSTER: "-",
    CORPUS_385: (0, (4, 2)),
    CORPUS_REISHI_10HZ: "-",
    CORPUS_REISHI_1HZ: (0, (1.5, 1.8)),
}

SPECIES_LABEL = {
    SPECIES_OYSTER: "oyster",
    SPECIES_385: "sp385 (Mushroom_260720)",
    SPECIES_REISHI: "reishi",
}


def apply_style():
    """The house style, unchanged - `style7`'s rcParams."""
    style7.apply_style()


def colour_of(species):
    return SPECIES_COLOUR.get(species, style7.RULE_COLOUR)


def dash_of(species):
    return SPECIES_DASH.get(species, "-")


def marker_of(species):
    return SPECIES_MARKER.get(species, "o")


def species_handles(species=SPECIES_ORDER, counts=None):
    """Legend handles, in fixed order. A legend is always present."""
    from matplotlib.lines import Line2D
    handles = []
    for name in species:
        label = SPECIES_LABEL.get(name, name)
        if counts:
            label = f"{label}  (n={counts.get(name, 0)})"
        handles.append(Line2D([0], [0], color=colour_of(name),
                              linestyle=dash_of(name),
                              marker=marker_of(name), markersize=5,
                              lw=style7.LW_TRACE, label=label))
    return handles


def corpus_handles(corpora, counts=None):
    from matplotlib.lines import Line2D
    handles = []
    for name in corpora:
        label = name if not counts else f"{name}  (n={counts.get(name, 0)})"
        handles.append(Line2D([0], [0], color=CORPUS_COLOUR.get(name, "0.4"),
                              linestyle=CORPUS_DASH.get(name, "-"),
                              lw=style7.LW_TRACE, label=label))
    return handles


def composition_bar(ax, counts, order=SPECIES_ORDER, height=1.0):
    """A one-row stacked bar of species composition for a family panel.

    Replaces drop_motifs9's channel-composition bar. A 2px surface gap
    between segments, so adjacent fills of similar lightness stay
    separable - the same rule the rest of the figure set follows for
    stacked marks.
    """
    total = sum(counts.get(name, 0) for name in order)
    if not total:
        return
    left = 0.0
    for name in order:
        n = counts.get(name, 0)
        if not n:
            continue
        width = n / total
        ax.barh([0], [width], left=[left], height=height,
                color=colour_of(name), edgecolor="white", linewidth=1.0)
        left += width
    ax.set_xlim(0, 1)
    ax.set_axis_off()


def scale_ticks(values, n=5):
    """Log-spaced ticks for an axis spanning orders of magnitude."""
    values = np.asarray([v for v in values if v > 0], dtype=float)
    if values.size == 0:
        return []
    lo, hi = np.log10(values.min()), np.log10(values.max())
    return list(np.logspace(lo, hi, int(n)))


def cophenetic_note(r, floor=0.70):
    """The caption every tree in this run carries.

    Below the floor the dendrogram is a picture of the linkage algorithm
    rather than of the data, and drop_motifs9's shipped 0.681 was above it
    only because 22 all-zero feature vectors were stacked at the origin.
    The number is stated on the figure either way.
    """
    verdict = "well supported" if r >= floor else "BELOW the 0.70 floor"
    return f"cophenetic r = {r:.3f} ({verdict})"


def readable_grey(fig, ax):
    """Recessive grid and axes, as everywhere else in this figure set."""
    ax.grid(True, color="0.88", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return fig, ax
