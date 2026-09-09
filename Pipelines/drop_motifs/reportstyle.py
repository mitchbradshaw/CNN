"""
reportstyle.py
===============
The house style for the report figure set in `Plots/drop_motifs_report/`.

Four figures are redrawn from earlier drop_motifs generations for the
written report, and the report imposes three rules on all of them. They
are collected here rather than repeated in each figure, so "every figure
obeys them" is a property of one file:

1. **Type is 8-10 pt and nothing overlaps.** Earlier generations ran
   annotations down to 6.3 pt, which is legible on a 200 dpi PNG viewed at
   full size and is not legible on a printed page. One constant per role,
   all inside the band, and every figure places its axes explicitly rather
   than trusting a tight bounding box to sort the collisions out.

2. **Vector PDF.** `save` writes a PDF with real text and real paths, so
   the figure scales without resampling. Fonts are embedded as TrueType
   (`pdf.fonttype = 42`) rather than as Type 3, because Type 3 text is not
   selectable or searchable in most readers and several journals reject it.

3. **No process text.** These figures carry a descriptive title, axis
   labels and a legend. What an earlier caption said about the operator's
   list, the window purity or which pass fired belongs in the report's
   prose, not on the plate. Provenance still has to be recoverable, so it
   goes to the JSON written beside every figure instead of onto it.

Colour continues the series rather than starting again: species keep the
`config11` assignment, and time-within-a-span uses `style6.TIME_CMAP`, the
blue-to-green ramp. Yellow, red, black and white stay excluded.

No detection logic. This module is import-safe from any figure script and
imports nothing below `Working/`.
"""

import datetime as _dt
import json
import os

import numpy as np
from matplotlib import pyplot as plt

from Pipelines.drop_motifs import style6

# --------------------------------------------------------------------------
# rule 1 - type
# --------------------------------------------------------------------------
#
# One constant per role, every one of them inside 8-10 pt. `config11` has
# the same shape of table but reaches 7.0 pt for its footer and 8.0 for
# annotation; the report's floor is 8.0 everywhere and its footer is gone
# altogether under rule 3.

FS_SUPTITLE = 10.0       # the figure's one title
FS_TITLE = 9.0           # panel titles
FS_LABEL = 9.0           # axis labels
FS_TICK = 8.0            # tick labels
FS_ANNOT = 8.0           # in-axes annotation
FS_LEGEND = 8.5

FS_MIN = 8.0
FS_MAX = 10.0

TITLE_PAD = 5.0


def apply_style():
    """The report type scale. Call once at the top of every figure."""
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "font.size": FS_TICK,
        "axes.titlesize": FS_TITLE,
        "axes.labelsize": FS_LABEL,
        "xtick.labelsize": FS_TICK,
        "ytick.labelsize": FS_TICK,
        "legend.fontsize": FS_LEGEND,
        "legend.frameon": False,
        "axes.titlepad": TITLE_PAD,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "lines.solid_capstyle": "round",
        # Rule 2. Set here and not at save time: the backend reads it when
        # the figure is written, and a figure saved through any other path
        # in this package must come out the same way.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })


def check_type_sizes(fig, lo=FS_MIN, hi=FS_MAX):
    """Every text artist on `fig` whose size is outside the band.

    Rule 1 is checked rather than asserted. A figure that grows a colorbar
    label or a legend title picks up matplotlib's default size for it, and
    the default is not in the band - which is exactly the drift this
    returns a list of. Empty text is ignored; it draws nothing.
    """
    bad = []
    for text in fig.findobj(plt.Text):
        if not str(text.get_text()).strip():
            continue
        size = float(text.get_fontsize())
        if size < lo - 1e-6 or size > hi + 1e-6:
            bad.append({"text": str(text.get_text())[:60],
                        "fontsize": size})
    return bad


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------

# The blue-to-green ramp from `style6`: deep blue -> blue -> teal -> green.
# Monotone in luminance so it still reads as an ordering in greyscale, and
# it reaches no yellow. This is what replaces `overlays5`'s `plasma`, which
# ran purple to yellow and put its most-saturated end on the excluded hue.
TIME_CMAP = style6.TIME_CMAP

# Truncated at both ends, for `overlays5`'s reason: the extremes of a ramp
# are near-black and near-white and a trace drawn in either disappears
# against the axes or the page.
TIME_LO, TIME_HI = 0.06, 0.94

RULE_COLOUR = "#3D3D3D"
SIGNAL_COLOUR = "0.25"
GRID_ALPHA = 0.18


def time_colours(values, lo=TIME_LO, hi=TIME_HI, cmap=TIME_CMAP):
    """`(colours, norm)` - one colour per event by its position in the span.

    The same quantity the colourbar is labelled with, so a trace can be
    read back to its place in the recording by eye.
    """
    from matplotlib import colors as mcolors

    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return [], None
    low, high = float(values.min()), float(values.max())
    span = high - low
    fractions = (np.full(values.shape, 0.5) if span <= 0
                 else (values - low) / span)
    return ([cmap(lo + (hi - lo) * f) for f in fractions],
            mcolors.Normalize(vmin=low, vmax=high))


# --------------------------------------------------------------------------
# rule 2 - output, and the JSON that carries what rule 3 took off the page
# --------------------------------------------------------------------------

OUT_DIR = os.path.join("Plots", "drop_motifs_report")


def save(fig, path, *, tight=False, proof_png=None, proof_dpi=110):
    """Write the figure as a vector PDF and return the path.

    `tight=False` by default and that is deliberate. Every figure here
    places its axes at explicit figure fractions so panels line up with
    their captions and strips; a tight bounding box re-crops after that
    layout is decided and pulls the two apart. A figure that has no such
    coupling may ask for it.

    `proof_png` writes the SAME figure to a raster file as well. The PDF is
    the deliverable; the proof exists because rule 1 - "no text overlaps
    anything" - can only be settled by looking, and there is no PDF
    rasteriser in this environment to look with. It is written from the
    same figure object, so it cannot show a different layout.
    """
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    kwargs = {"facecolor": "white"}
    if tight:
        kwargs["bbox_inches"] = "tight"
    fig.savefig(path, format="pdf", **kwargs)
    if proof_png:
        os.makedirs(os.path.dirname(str(proof_png)) or ".", exist_ok=True)
        fig.savefig(str(proof_png), format="png", dpi=proof_dpi, **kwargs)
    plt.close(fig)
    return path


def write_manifest(pdf_path, payload):
    """The JSON beside every figure.

    Rule 3 takes the provenance sentences off the plate; this is where they
    go instead, so a reader can still check any number the figure states -
    and the numbers the figure no longer states - without re-running
    anything.
    """
    path = os.path.splitext(str(pdf_path))[0] + ".json"
    payload = dict(payload)
    payload.setdefault("figure", os.path.basename(str(pdf_path)))
    payload.setdefault("run", "drop_motifs_report")
    payload.setdefault("written",
                       _dt.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=_jsonable)
    return path


def _jsonable(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)
