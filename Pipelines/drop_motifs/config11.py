"""
config11.py
============
Everything drop_motifs11 must not hardcode inside a figure: which species
exist, what colour each one is, what size the type is, and how a figure
records what it was made from.

The contract this file exists to keep
--------------------------------------
More Lion's mane recordings and more Reishi windows are being prepared.
Every figure in this run must survive their arrival without an edit, so:

  - the species LIST is never written down; it is read off the store and
    ordered against `SPECIES_ORDER`, with anything unrecognised appended
    alphabetically after it;
  - colour, marker and dash are keyed by the STORE'S OWN species value,
    never by position in a sorted list, so oyster stays the same blue when
    a fourth species arrives and takes the next unused slot;
  - the seed for a per-species draw is a function of the species name
    alone, so adding a species cannot reshuffle another species' sample.

Colours continue `style10`'s assignment rather than starting a new one, so
a hue does not mean two different things across the drop_motifs series.

Typography is fixed here and nowhere else. One constant per role, applied
by `apply_style`, is the correction to drop_motifs10's drifting title
sizes.
"""

import datetime as _dt
import json
import os

import numpy as np
from matplotlib import pyplot as plt

from Pipelines.drop_motifs import style6, style10

# --------------------------------------------------------------------------
# species
# --------------------------------------------------------------------------

# Keyed by the value in the store's `species` column. The paper label is
# separate from the store key on purpose: the store says `sp385`, the
# paper says "Lion's mane", and neither should have to change for the
# other.
SPECIES = {
    "oyster": {
        "label": "Oyster",
        "colour": style10.SPECIES_COLOUR["oyster"],       # blue
        "marker": "o",
        "dash": "-",
    },
    "sp385": {
        "label": "Lion's mane",
        "colour": style10.SPECIES_COLOUR["sp385"],        # orange
        "marker": "s",
        "dash": (0, (4, 2)),
    },
    "reishi": {
        "label": "Reishi",
        "colour": style10.SPECIES_COLOUR["reishi"],       # dark green
        "marker": "^",
        "dash": (0, (1.5, 1.8)),
    },
    # drop_motifs12a's 10 Hz Lion's mane corpus. It is the SAME ORGANISM as
    # `sp385` - `lionsmane12.locate_id385` measures the 1 Hz excerpt inside
    # region B at r = 0.9995 - detected at ten times the rate over 350x the
    # duration, and it retires `sp385`. It therefore inherits `sp385`'s
    # orange, marker and dash rather than taking a spare slot: a hue must
    # not mean two different things across the drop_motifs series, and here
    # it means the same organism in both runs.
    #
    # The cost, which is real and is a deliberate trade: a store holding BOTH
    # keys at once would draw them identically. No store does - 12a writes one
    # or the other - and if one ever did, the fix is to stop carrying two keys
    # for one organism, not to give one organism two hues.
    "lionsmane": {
        "label": "Lion's mane",
        "colour": style10.SPECIES_COLOUR["sp385"],        # orange
        "marker": "s",
        "dash": (0, (4, 2)),
    },
}

# Drawing order for the species already known. A species not in here is
# drawn after these, in alphabetical order, and takes the next unused
# entry in `SPARE_SLOTS` - so a fourth species is a config line, not a
# figure edit, and it never displaces an existing colour.
#
# `lionsmane` sits where `sp385` does because it replaces it; the two never
# appear in one store, so sharing the slot cannot collide.
SPECIES_ORDER = ("oyster", "sp385", "lionsmane", "reishi")

# Reserved for species that arrive later. Hues continue style7's pool and
# stay clear of red, yellow, black and white.
SPARE_SLOTS = (
    {"colour": "#8257C4", "marker": "D", "dash": (0, (5, 1.5))},       # purple
    {"colour": "#2E9E95", "marker": "v", "dash": (0, (1, 1))},         # teal
    {"colour": "#5158C4", "marker": "P", "dash": (0, (6, 2, 1, 2))},   # indigo
    {"colour": "#4E7396", "marker": "X", "dash": (0, (3, 1, 1, 1))},   # slate
)

# `reishi_1hz` is the SAME organism as `reishi_10hz`, decimated, and it is
# a rate control rather than a corpus in its own right. Including it in a
# species figure would draw many Reishi events twice at two rates and
# quietly double-count them, so it is excluded by default and can only be
# put back deliberately.
CONTROL_CORPORA = ("reishi_1hz",)


def _slot(species):
    """One unknown species' spare slot, chosen by its NAME.

    By name and not by its position among the other unknowns, for the same
    reason the known species are keyed by store value: a slot picked by
    position changes when a fifth species arrives, and - worse - differs
    between a call that passes every species and a call that passes one.
    That inconsistency was a real bug: `_species_ramp` asked for one
    species' colour and got a different answer from the legend beside it.

    Two unknown names can land on the same slot. They would then share
    colour, marker and dash, which is visible and fixable by giving the
    species a real entry in `SPECIES` - the intended end state anyway.
    """
    known = SPECIES.get(species)
    if known is not None:
        return dict(known)
    spare = SPARE_SLOTS[_checksum(species) % len(SPARE_SLOTS)]
    return {"label": str(species), "marker": spare["marker"],
            "colour": spare["colour"], "dash": spare["dash"]}


def resolve(species_keys):
    """`{key: {label, colour, marker, dash}}` for exactly these species.

    The only way a figure is allowed to learn a species' appearance. Keys
    it does not recognise are given a spare slot keyed by name, so any two
    calls over any two subsets agree.
    """
    return {key: _slot(key) for key in dict.fromkeys(species_keys)}


def order(species_keys):
    """The species present, in the run's fixed order. Never a sorted list."""
    keys = set(species_keys)
    known = [k for k in SPECIES_ORDER if k in keys]
    return known + sorted(keys - set(known))


def _entry(species, resolved=None):
    """One species' appearance, whether or not the config has heard of it.

    An unknown key falls back to `resolve`, NOT to a neutral default. The
    difference is the whole reproducibility contract: a caller that has not
    threaded a `resolved` table through - `figures11_s3._species_ramp` was
    one - would otherwise silently drop a new species onto a grey constant
    while every other panel gave it a spare slot, and `style6.BASE_RULE` is
    a greyscale float that `matplotlib.colors.to_rgb` rejects outright. A
    fourth species must need no code edit anywhere, so the fallback is the
    same allocation the resolved table would have made.
    """
    if resolved is not None and species in resolved:
        return resolved[species]
    return resolve([species])[species]


def label_of(species, resolved=None):
    return _entry(species, resolved)["label"]


def colour_of(species, resolved=None):
    return _entry(species, resolved)["colour"]


def marker_of(species, resolved=None):
    return _entry(species, resolved)["marker"]


def dash_of(species, resolved=None):
    return _entry(species, resolved)["dash"]


def handles(species_keys, counts=None, resolved=None):
    """Legend handles in run order. Colour is never the only cue."""
    from matplotlib.lines import Line2D

    table = resolved if resolved is not None else resolve(species_keys)
    out = []
    for key in order(species_keys):
        text = table[key]["label"]
        if counts:
            text = f"{text}  (n = {int(counts.get(key, 0)):,})"
        out.append(Line2D([0], [0], color=table[key]["colour"],
                          linestyle=table[key]["dash"],
                          marker=table[key]["marker"], markersize=5,
                          lw=1.6, label=text))
    return out


# --------------------------------------------------------------------------
# seeds
# --------------------------------------------------------------------------

SEED = 20260903


def _checksum(name):
    """A fixed checksum over a name, reproducible across processes.

    Python's `hash` is salted per process for str, so it cannot be used for
    anything that must be the same on two runs of the same command - a
    seeded sample, or a colour slot.
    """
    digest = 0
    for char in str(name).encode("utf-8"):
        digest = (digest * 131 + char) % 1_000_003
    return digest


def seed_for(species):
    """A stable seed per species, independent of every other species.

    Adding a species does not change another species' sample, because the
    seed is a function of the name alone.
    """
    return SEED + _checksum(species) % 1000


def rng_for(species):
    return np.random.default_rng(seed_for(species))


# --------------------------------------------------------------------------
# typography - one size per role, across every figure in the run
# --------------------------------------------------------------------------

FS_SUPTITLE = 12.0
FS_TITLE = 10.0          # panel titles
FS_LABEL = 9.0           # axis labels
FS_TICK = 8.0            # tick labels
FS_ANNOT = 8.0           # in-axes numeric annotation, never a sentence
FS_LEGEND = 8.5
FS_FOOTER = 7.0

TITLE_PAD = 6.0


def apply_style():
    """The house style plus this run's fixed type scale."""
    style10.apply_style()
    plt.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 200,
        "axes.titlesize": FS_TITLE,
        "axes.labelsize": FS_LABEL,
        "xtick.labelsize": FS_TICK,
        "ytick.labelsize": FS_TICK,
        "legend.fontsize": FS_LEGEND,
        "legend.frameon": False,
        "axes.titlepad": TITLE_PAD,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def panel_title(ax, text, n=None):
    """A noun phrase, with n where there is one. No questions, no verdicts."""
    if n is not None:
        text = f"{text}  (n = {int(n):,})"
    ax.set_title(text, fontsize=FS_TITLE, pad=TITLE_PAD)


def legend_axis(ax):
    """Turn an axes into a bare canvas for a legend.

    A dedicated axes rather than `loc=` inside a data panel: drop_motifs10's
    rose put panel 2's legend on top of panel 1's tick labels, and the only
    reliable fix is to stop legends sharing space with data at all.
    """
    ax.set_axis_off()
    return ax


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------

def footer(fig, store, n, extra=""):
    """One grey line, below everything: where the data came from and how much.

    Placed at a NEGATIVE figure fraction, hanging under the axes, and not
    at a small positive one. `savefig(bbox_inches="tight")` grows the saved
    bounds to include artists outside the figure, so a negative y is always
    clear of the lowest axis label; a positive y is only clear of it when
    the figure happens to have bottom margin left, which a small
    single-axes figure with a two-line x label does not - the footer landed
    on top of that label.
    """
    stamp = _dt.date.today().isoformat()
    text = f"store: {store}  |  n = {int(n):,} events  |  {stamp}"
    if extra:
        text += f"  |  {extra}"
    fig.text(0.005, -0.018, text, fontsize=FS_FOOTER, color="0.45",
             ha="left", va="top")


def write_manifest(png_path, payload):
    """The JSON that sits beside every figure.

    Written from the same dict the figure was drawn from, so a number in
    the manifest and a number on the page cannot drift apart.
    """
    path = os.path.splitext(png_path)[0] + ".json"
    payload = dict(payload)
    payload.setdefault("figure", os.path.basename(png_path))
    payload.setdefault("run", "drop_motifs11")
    payload.setdefault("written",
                       _dt.datetime.now().isoformat(timespec="seconds"))
    payload.setdefault("seed", SEED)
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


def save(fig, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
