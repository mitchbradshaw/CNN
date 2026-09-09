"""
round2figs1.py
===============
Every figure round 2 ships. Matplotlib Agg only - `CLAUDE.md` rule 1.

The drawing rules are `nullfigs1`'s, unchanged, and its channel palette is
imported rather than retyped so a channel is the same colour in both
rounds' figures:

  A PANEL THAT STATES A NUMBER STATES ITS N AND ITS p.
  A NULL IS DRAWN AS A DISTRIBUTION, NOT AS AN ERROR BAR.
  WHEN THE NULL REPRODUCES THE OBSERVATION, THE TITLE SAYS SO.
  THE JSON BESIDE THE FIGURE IS WHAT THE PAPER QUOTES.

One rule is added, for this round specifically:

  A CUT THAT IS ONE FAMILY PLUS OUTLIERS IS DRAWN AS ONE FAMILY PLUS
  OUTLIERS. The linkage panel annotates every cell with the SIZES its
  selected cut produces, not just its k, because the silhouette rule's
  winner on this store is a 1092/5 split and a bare "k = 2" hides that.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs.nullfigs1 import (CAPTION_SIZE, CHANNEL_COLOURS,
                                             LABEL_SIZE, OBSERVED_COLOUR,
                                             TITLE_SIZE, _save)

FAMILY_COLOURS = ["#1b4965", "#c1666b", "#5fa8a0", "#e0a458", "#7d5ba6",
                  "#8a5a44", "#4a7c59", "#b07aa1", "#76b7b2", "#9c755f"]
NULL_COLOUR = "#b8b8b8"
FLOOR_COLOUR = "#c1666b"


def family_colour(index):
    return FAMILY_COLOURS[int(index) % len(FAMILY_COLOURS)]


def _caption(fig, text, y=0.006):
    fig.text(0.5, y, text, ha="center", va="bottom", fontsize=CAPTION_SIZE,
             color="#3d3d3d", wrap=True)


# ---------------------------------------------------------------------------
# Task A - the tree
# ---------------------------------------------------------------------------

def plot_dendrogram(Z, labels, rows, out_path, *, title, cophenetic,
                    floor=0.70, k=None):
    """The tree, leaves coloured by channel, with the faithfulness stated.

    The cophenetic correlation is in the title rather than the caption
    because it is the number that decides whether the picture below it
    means anything, and a reader who reads one line reads the title.
    """
    channels = np.asarray([int(r["channel"]) for r in rows])
    fig = plt.figure(figsize=(18.0, 9.0))
    ax = fig.add_axes([0.05, 0.20, 0.93, 0.68])

    dn = dendrogram(Z, ax=ax, no_labels=True, color_threshold=0,
                    above_threshold_color="#8f8f8f")
    leaves = dn["leaves"]

    # A rug under the tree: one tick per leaf, in its channel's colour. The
    # leaves are too many to label, and the question the tree is asked in
    # this round is whether shape sorts by electrode, so channel is what
    # the leaf axis has to carry.
    lo, hi = ax.get_ylim()
    rug = lo - 0.055 * (hi - lo)
    for position, leaf in enumerate(leaves):
        ax.plot([position * 10 + 5], [rug], marker="|", ms=7, mew=1.1,
                color=CHANNEL_COLOURS[channels[leaf] % len(CHANNEL_COLOURS)],
                clip_on=False)
    ax.set_ylim(rug - 0.01 * (hi - lo), hi)
    ax.set_xticks([])
    ax.set_ylabel("merge distance (z-normalised, 200 pt)",
                  fontsize=LABEL_SIZE)
    ax.spines[["top", "right", "bottom"]].set_visible(False)

    verdict = ("FAITHFUL" if cophenetic >= floor else
               "NOT A FAITHFUL SUMMARY OF THE DISTANCES")
    ax.set_title(f"{title}\ncophenetic r = {cophenetic:.3f} "
                 f"(floor {floor:.2f}) — {verdict}",
                 fontsize=TITLE_SIZE, pad=14)

    ax.legend(handles=[Line2D([], [], color=CHANNEL_COLOURS[c], lw=3,
                              label=f"CH{c}") for c in range(5)],
              loc="upper right", frameon=False, fontsize=CAPTION_SIZE,
              ncol=5)

    caption = (f"n = {len(rows)} refined motifs, corrected store. "
               f"Leaf rug is the recording channel.")
    if cophenetic < floor:
        caption += ("  The merge heights do NOT reproduce the pairwise "
                    "distances well: any cut of this tree is a convention, "
                    "not a discovered partition.")
    if k:
        caption += f"  Drawn cut: k = {k}."
    _caption(fig, caption)
    return _save(fig, out_path)


def plot_family_atlas(waveforms, labels, rows, out_path, *, title,
                      cophenetic=None, floor=0.70, max_show=90):
    """One panel per family: every member faintly, the medoid on top.

    Traces are drawn in the space they were CLUSTERED in - z-normalised,
    200 points - not in millivolts, because the panel's claim is about
    shape and drawing it in mV would let amplitude do work the clustering
    never saw. The millivolt numbers are in the panel's own subtitle.
    """
    labels = np.asarray(labels)
    families = sorted(set(labels.tolist()))
    n_fam = len(families)
    cols = min(n_fam, 4)
    fig_rows = int(np.ceil(n_fam / cols))
    fig = plt.figure(figsize=(4.6 * cols, 3.7 * fig_rows + 1.1))

    for position, family in enumerate(families):
        ax = fig.add_subplot(fig_rows, cols, position + 1)
        members = np.flatnonzero(labels == family)
        colour = family_colour(position)
        show = members if members.size <= max_show else np.random.default_rng(
            20260903).choice(members, max_show, replace=False)
        for index in show:
            ax.plot(waveforms[index], color=colour, alpha=0.10, lw=0.7)
        centroid = np.mean([waveforms[i] for i in members], axis=0)
        ax.plot(centroid, color=colour, lw=2.4)
        ax.plot(centroid, color="white", lw=0.9, alpha=0.7)

        depths = [abs(float(rows[i]["drop_depth_mv"])) for i in members]
        falls = [abs(float(rows[i]["fall_duration_s"])) for i in members]
        held = sorted({int(rows[i]["channel"]) for i in members})
        ax.set_title(
            f"F{family}  n = {members.size}\n"
            f"median {np.median(depths):.2f} mV, {np.median(falls):.2f} s\n"
            f"channels {''.join(str(c) for c in held)} "
            f"({len(held)} of 5)",
            fontsize=CAPTION_SIZE + 0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines[["top", "right"]].set_visible(False)

    head = title
    if cophenetic is not None:
        head += (f"   —   cophenetic r = {cophenetic:.3f}"
                 f"{'' if cophenetic >= floor else '  (BELOW THE 0.70 FLOOR: '
                                                   'this is a cut, not a '
                                                   'discovered partition)'}")
    fig.suptitle(head, fontsize=TITLE_SIZE, y=0.995)
    fig.tight_layout(rect=[0, 0.035, 1, 0.965])
    _caption(fig, "Traces are the z-normalised 200-point vectors the tree "
                  "was built from; the heavy line is the family mean. "
                  "Millivolts and seconds are in each panel's subtitle, "
                  "never in its axes.")
    return _save(fig, out_path)


def plot_linkage_selection(cells, verdict, out_path, *, floor=0.70):
    """The whole grid on one axis, with the rule printed above it.

    Every bar is annotated with the SIZES its selected cut produces, not
    just its k: the rule's winner here is a 1092/5 split, and a bare
    "k = 2" would hide that this tree's best cut is one family plus five
    outliers. The annotation sits in a reserved band above the tallest bar
    rather than floating over each one, because at these heights a label
    placed just above its own bar collides with its neighbour's.
    """
    order = sorted(cells, key=lambda c: -c["cophenetic_r"])
    names = [f"{c['method']}\n{c['metric']}" for c in order]
    rs = [c["cophenetic_r"] for c in order]
    sils = [c["silhouette_at_selected_k"] or 0.0 for c in order]

    fig = plt.figure(figsize=(14.5, 8.8))
    ax = fig.add_axes([0.070, 0.325, 0.585, 0.415])
    ax2 = fig.add_axes([0.745, 0.325, 0.225, 0.415])

    colours = [("#b8b8b8" if c["method_invalid"] else
                (OBSERVED_COLOUR if c["cophenetic_r"] >= floor
                 else FLOOR_COLOUR)) for c in order]
    ceiling = 1.0
    ax.bar(range(len(order)), rs, color=colours, width=0.60,
           edgecolor="white", lw=1.0)
    ax.axhline(floor, color=FLOOR_COLOUR, lw=1.6, ls="--", zorder=1)
    ax.text(-0.44, floor + 0.015, f"cophenetic floor {floor:.2f}",
            ha="left", va="bottom", fontsize=CAPTION_SIZE,
            color=FLOOR_COLOUR)

    # One annotation band, above every bar, so nothing collides.
    band = ceiling * 0.90
    for index, cell in enumerate(order):
        shape = cell.get("cut_shape_at_selected_k") or {}
        sizes = shape.get("sizes", [])
        shown = " / ".join(str(v) for v in sizes[:3])
        if len(sizes) > 3:
            shown += " / …"
        ax.annotate("", xy=(index, rs[index] + 0.012),
                    xytext=(index, band - 0.035),
                    arrowprops=dict(arrowstyle="-", lw=0.6, color="#c8c8c8"))
        ax.text(index, band, f"k = {cell['selected_k']}\n{shown}",
                ha="center", va="bottom", fontsize=CAPTION_SIZE - 0.5,
                color=("#8f8f8f" if cell["method_invalid"]
                       else OBSERVED_COLOUR), linespacing=1.35)
        if shape.get("degenerate"):
            ax.text(index, band - 0.030, "one family + outliers",
                    ha="center", va="top", fontsize=CAPTION_SIZE - 2,
                    color=FLOOR_COLOUR, style="italic")

    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(names, fontsize=CAPTION_SIZE)
    for index, cell in enumerate(order):
        if cell["method_invalid"]:
            ax.get_xticklabels()[index].set_color("#8f8f8f")
    ax.set_ylabel("cophenetic correlation", fontsize=LABEL_SIZE)
    ax.set_ylim(0, ceiling)
    ax.set_xlim(-0.6, len(order) - 0.4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("How faithfully each tree reproduces its own distance "
                 "matrix", fontsize=TITLE_SIZE, pad=26)

    ax2.barh(range(len(order)), sils, color=colours, height=0.58,
             edgecolor="white")
    ax2.set_yticks(range(len(order)))
    ax2.set_yticklabels([f"{c['method']} · {c['metric'][:4]}"
                         for c in order], fontsize=CAPTION_SIZE - 1)
    ax2.invert_yaxis()
    ax2.set_xlabel("silhouette at the selected k", fontsize=CAPTION_SIZE)
    ax2.set_xlim(0, 1.0)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_title("separation of that cut", fontsize=CAPTION_SIZE + 1,
                  pad=26)

    invalid = [c for c in order if c["method_invalid"]]
    if invalid:
        fig.text(0.070, 0.286,
                 "Grey: Ward minimises a variance and presumes squared "
                 "Euclidean geometry, so Ward × correlation is computed "
                 "for completeness and is never eligible.",
                 ha="left", va="top", fontsize=CAPTION_SIZE - 0.5,
                 color="#6f6f6f", style="italic")

    fig.text(0.5, 0.955,
             "THE RULE, FIXED BEFORE THE NUMBERS WERE READ",
             ha="center", va="top", fontsize=CAPTION_SIZE + 1.5,
             color=OBSERVED_COLOUR, weight="bold")
    fig.text(0.5, 0.925,
             "k = argmax mean silhouette over k ∈ 2..12, ties to the "
             "smaller k.   Linkage = highest cophenetic r among the valid "
             "cells; ties within 0.005 to the higher silhouette, then to "
             "Ward.",
             ha="center", va="top", fontsize=CAPTION_SIZE,
             color="#3d3d3d")

    selected = verdict["selected"]
    lines = [f"SELECTED:  {selected['method']} linkage on "
             f"{selected['metric']} distance,  k = {selected['k']},  "
             f"cophenetic r = {selected['cophenetic_r']:.3f},  "
             f"silhouette = {selected['silhouette']:.3f}"]
    if verdict.get("degeneracy_warning"):
        lines.append(verdict["degeneracy_warning"])
    if verdict.get("finding"):
        lines.append(verdict["finding"])

    fig.text(0.5, 0.215, lines[0], ha="center", va="top",
             fontsize=CAPTION_SIZE + 1.5, color=OBSERVED_COLOUR,
             weight="bold")
    if len(lines) > 1:
        wrapped = _wrap(" ".join(lines[1:]), 148)
        fig.text(0.5, 0.175, wrapped, ha="center", va="top",
                 fontsize=CAPTION_SIZE, color="#3d3d3d", linespacing=1.5)
    return _save(fig, out_path)


def _wrap(text, width):
    """Hard-wrap for figure text. matplotlib's `wrap=True` measures against
    the FIGURE width and silently does nothing inside a `fig.text` that is
    centred, which is how the first draft of this panel ran its caption off
    both edges."""
    import textwrap

    return "\n".join(textwrap.wrap(text, width))


# ---------------------------------------------------------------------------
# Task B - channel decodability
# ---------------------------------------------------------------------------

def plot_decode(results, headline_text, verdict, chance, out_path, *,
                title="Task B — can you tell which electrode an event came "
                      "from?"):
    """Balanced accuracy by representation, over its permutation null.

    The null is drawn as a shaded band spanning its 5th-95th percentile
    with the median as a line, not as an error bar on the observed value:
    the p is a rank within an empirical distribution, and an error bar
    would imply a symmetric parametric one nobody assumed. Chance is drawn
    twice - the nominal 1/5 and the realised stratified-dummy score - so a
    reader can see that the two agree rather than take it on trust.
    """
    representations = [r for r in ("amplitude", "shape", "both")
                       if r in results]
    models = sorted({m for r in representations for m in results[r]})

    fig = plt.figure(figsize=(15.5, 8.2))
    ax = fig.add_axes([0.065, 0.235, 0.50, 0.545])

    width = 0.34
    positions = np.arange(len(representations))
    model_colours = {models[0]: OBSERVED_COLOUR}
    if len(models) > 1:
        model_colours[models[1]] = "#5fa8a0"

    for offset, model in enumerate(models):
        xs = positions + (offset - (len(models) - 1) / 2) * width
        heights = [results[r][model]["balanced_accuracy"] * 100
                   for r in representations]
        ax.bar(xs, heights, width=width * 0.92,
               color=model_colours.get(model, "#b8b8b8"),
               edgecolor="white", lw=1.1,
               label=model.replace("_", " "))

        for x, representation in zip(xs, representations):
            entry = results[representation][model]
            null = np.asarray(entry["null_values"], dtype=float) * 100
            lo, hi = np.percentile(null, [5, 95])
            ax.add_patch(plt.Rectangle(
                (x - width * 0.46, lo), width * 0.92, max(hi - lo, 0.05),
                facecolor=NULL_COLOUR, alpha=0.55, edgecolor="none",
                zorder=3))
            ax.plot([x - width * 0.46, x + width * 0.46],
                    [np.median(null)] * 2, color="#6f6f6f", lw=1.3,
                    zorder=4)
            p = entry["p_permutation"]
            ax.text(x, entry["balanced_accuracy"] * 100 + 1.0,
                    f"{entry['balanced_accuracy'] * 100:.1f}%\n"
                    f"p {'≤' if entry['at_p_floor'] else '='} "
                    f"{max(p, entry['p_floor']):.4f}",
                    ha="center", va="bottom", fontsize=CAPTION_SIZE - 0.5,
                    color=OBSERVED_COLOUR)

    ax.axhline(chance["nominal"] * 100, color=FLOOR_COLOUR, lw=1.6, ls="--")
    ax.text(len(representations) - 0.45, chance["nominal"] * 100 + 0.5,
            f"chance, 1 of 5 = {chance['nominal'] * 100:.0f}%",
            ha="right", fontsize=CAPTION_SIZE, color=FLOOR_COLOUR)
    ax.axhline(chance["realised"] * 100, color=FLOOR_COLOUR, lw=1.0,
               ls=":", alpha=0.8)

    ax.set_xticks(positions)
    ax.set_xticklabels([r.upper() for r in representations],
                       fontsize=LABEL_SIZE)
    ax.set_ylabel("balanced accuracy, 5-fold (%)", fontsize=LABEL_SIZE)
    tallest = max(results[r][m]["balanced_accuracy"] * 100
                  for r in representations for m in models)
    ax.set_ylim(0, tallest + 12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE, loc="upper left")
    shuffles = max(
        entry["n_permutations"]
        for representation in representations
        for entry in results[representation].values())
    ax.set_title(f"grey band = permutation null, 5th–95th percentile "
                 f"({shuffles} label shuffles)",
                 fontsize=CAPTION_SIZE + 1, pad=10)

    # -- the two confusion matrices ---------------------------------------
    best = {r: max(results[r], key=lambda m: results[r][m]
                   ["balanced_accuracy"]) for r in ("amplitude", "shape")}
    for index, representation in enumerate(("amplitude", "shape")):
        cax = fig.add_axes([0.645 + index * 0.180, 0.300, 0.150, 0.420])
        entry = results[representation][best[representation]]
        matrix = np.asarray(entry["confusion_matrix"], dtype=float)
        rows = matrix.sum(axis=1, keepdims=True)
        normalised = np.divide(matrix, np.where(rows > 0, rows, 1))
        cax.imshow(normalised, cmap="Blues", vmin=0, vmax=1)
        labels = entry["confusion_labels"]
        cax.set_xticks(range(len(labels)))
        cax.set_yticks(range(len(labels)))
        cax.set_xticklabels([f"{c}" for c in labels],
                            fontsize=CAPTION_SIZE - 1)
        cax.set_yticklabels([f"CH{c}" for c in labels],
                            fontsize=CAPTION_SIZE - 1)
        for i in range(len(labels)):
            for j in range(len(labels)):
                cax.text(j, i, f"{normalised[i, j] * 100:.0f}",
                         ha="center", va="center",
                         fontsize=CAPTION_SIZE - 1.5,
                         color="white" if normalised[i, j] > 0.5 else "#3d3d3d")
        cax.set_title(f"{representation}\n{best[representation].replace('_', ' ')}",
                      fontsize=CAPTION_SIZE)
        cax.set_xlabel("predicted", fontsize=CAPTION_SIZE - 1)
        if index == 0:
            cax.set_ylabel("true", fontsize=CAPTION_SIZE - 1)

    fig.suptitle(title, fontsize=TITLE_SIZE, y=0.975)
    fig.text(0.5, 0.925, _wrap(headline_text, 118), ha="center", va="top",
             fontsize=CAPTION_SIZE + 1.5, color=OBSERVED_COLOUR,
             linespacing=1.5)
    _caption(fig, _wrap(
        f"VERDICT: {verdict['verdict'].upper()} — {verdict['gloss']}.  "
        f"Shape's margin above chance is "
        f"{verdict['shape_margin_as_fraction_of_amplitude_margin'] * 100:.0f}% "
        f"of amplitude's; the pre-set falsification threshold was "
        f"{verdict['falsification_threshold'] * 100:.0f}%.  Confusion "
        "matrices are row-normalised percentages (rows = true channel).  "
        + _column_note(results, best["shape"], "shape"), 150),
        y=0.025)
    return _save(fig, out_path)


# ---------------------------------------------------------------------------
# Task C - is the partition real
# ---------------------------------------------------------------------------

def plot_partition_validity(random_null, coassociation, stability, labels,
                            out_path, *, title="Task C — is the partition "
                                               "real, or is it just a cut?"):
    """Left: the real grouping against random groupings of the same sizes.
    Right: the bootstrap co-association matrix, ordered by family.

    The co-association matrix is ordered by family and NOT re-ordered
    within one, so a family that is really two things shows as two blocks
    rather than being tidied into one. That is the failure this panel
    exists to make visible.
    """
    labels = np.asarray(labels)
    fig = plt.figure(figsize=(15.0, 7.4))

    # -- A: the random-partition null -------------------------------------
    #
    # The null is TIGHT - 1000 random partitions of fixed sizes land within
    # a few hundredths of each other - and the observed value is a long way
    # outside it. A plain histogram over the full span therefore draws the
    # null as a hairline and the panel reads as two vertical rules with
    # nothing between them. So the null gets its own shaded range, the
    # histogram is binned over THAT range rather than over the whole axis,
    # and the gap is annotated in units of the null's own spread - which is
    # the quantity that makes "far outside" mean something.
    ax = fig.add_axes([0.055, 0.22, 0.36, 0.56])
    draws = np.asarray(random_null["null_values"], dtype=float)
    observed = float(random_null["observed"])
    lo, hi = float(draws.min()), float(draws.max())
    sigma = float(draws.std())

    ax.axvspan(lo, hi, color=NULL_COLOUR, alpha=0.35, zorder=1)
    ax.hist(draws, bins=np.linspace(lo, hi, 36), color="#8f8f8f",
            edgecolor="white", lw=0.4, zorder=2)
    ax.axvline(random_null["null_median"], color="#4f4f4f", lw=1.4,
               ls="--", zorder=3)

    top = ax.get_ylim()[1]
    ax.axvline(observed, color=OBSERVED_COLOUR, lw=2.6, zorder=4)
    ax.annotate(
        f"real\n{observed:.3f}", xy=(observed, top * 0.55),
        xytext=(observed + (lo - observed) * 0.30, top * 0.72),
        fontsize=CAPTION_SIZE + 1, color=OBSERVED_COLOUR, ha="center",
        va="center", weight="bold",
        arrowprops=dict(arrowstyle="->", lw=1.4, color=OBSERVED_COLOUR))
    ax.text(np.median(draws), top * 0.92,
            f"random partitions\nmedian {random_null['null_median']:.3f}\n"
            f"range {lo:.3f}–{hi:.3f}",
            ha="center", va="top", fontsize=CAPTION_SIZE, color="#3d3d3d")

    span = hi - lo
    ax.set_xlim(min(observed, lo) - span * 0.55, hi + span * 0.30)
    ax.set_xlabel("mean within-family distance to centroid",
                  fontsize=LABEL_SIZE)
    ax.set_ylabel(f"random partitions (n = {random_null['n_null']})",
                  fontsize=LABEL_SIZE)
    ax.spines[["top", "right"]].set_visible(False)
    p = max(random_null["p"], random_null["p_floor"])
    gap = (random_null["null_median"] - observed) / sigma if sigma else \
        float("inf")
    ax.set_title(
        f"A — the tree found structure: p "
        f"{'≤' if random_null['at_p_floor'] else '='} {p:.4f}\n"
        f"the real grouping is {gap:.0f} null SDs tighter than a random "
        f"one of the same sizes\n"
        f"{random_null['family_sizes_held_fixed']}",
        fontsize=CAPTION_SIZE + 1.5, pad=8)

    # -- B: the co-association matrix -------------------------------------
    ax2 = fig.add_axes([0.50, 0.20, 0.40, 0.60])
    order = np.argsort(labels, kind="stable")
    matrix = np.asarray(coassociation)[np.ix_(order, order)]
    image = ax2.imshow(matrix, cmap="magma", vmin=0, vmax=1,
                       interpolation="nearest")
    boundaries, cursor = [], 0
    for family in sorted(set(labels.tolist())):
        cursor += int(np.sum(labels == family))
        boundaries.append(cursor)
    for edge in boundaries[:-1]:
        ax2.axhline(edge - 0.5, color="white", lw=1.0)
        ax2.axvline(edge - 0.5, color="white", lw=1.0)

    centres, previous = [], 0
    for edge in boundaries:
        centres.append((previous + edge) / 2)
        previous = edge
    ax2.set_xticks(centres)
    ax2.set_yticks(centres)
    names = []
    for family in sorted(set(labels.tolist())):
        entry = stability.get("per_family_stability", {}).get(int(family), {})
        value = entry.get("stability")
        names.append(f"F{family}\nn={entry.get('n', 0)}"
                     + (f"\n{value:.2f}" if value is not None
                        and np.isfinite(value) else ""))
    ax2.set_xticklabels(names, fontsize=CAPTION_SIZE - 1)
    ax2.set_yticklabels(names, fontsize=CAPTION_SIZE - 1)
    fig.colorbar(image, ax=ax2, fraction=0.042,
                 label="co-association")
    ax2.set_title(
        f"B — bootstrap stability, {stability['n_resamples']} resamples\n"
        f"within-family {stability['mean_within_family_coassociation']:.3f}  "
        f"vs between-family "
        f"{stability['mean_between_family_coassociation']:.3f}",
        fontsize=CAPTION_SIZE + 1.5, pad=8)

    fig.suptitle(title, fontsize=TITLE_SIZE, y=0.965)
    _caption(fig, _wrap(
        "A asks whether the tree found anything: it compares the real "
        "grouping to random groupings OF THE SAME SIZES, which is the test "
        "the family-count comparison was reaching for and could not make.  "
        "B asks whether each family survives resampling — the number under "
        "each label is that family's mean co-association, and it is the "
        "quantity to quote in place of the family count the surrogate nulls "
        "rejected.", 150))
    return _save(fig, out_path)


# ---------------------------------------------------------------------------
# Task B2 - cross-electrode transfer
# ---------------------------------------------------------------------------

def plot_transfer(matrix, adjusted, detail, medoid_waveforms, out_path, *,
                  channels, k, title="Task B2 — do shapes learned on one "
                                     "electrode describe another?"):
    """Left: the ARI transfer matrix. Right: each channel's medoids.

    The medoid panel is what turns the matrix from a number into a claim a
    reader can check: if the five channels' medoids are the same shapes,
    high ARI means transfer; if they are different shapes, a high ARI would
    need explaining.
    """
    matrix = np.asarray(matrix, dtype=float)
    fig = plt.figure(figsize=(15.5, 7.6))

    ax = fig.add_axes([0.055, 0.19, 0.38, 0.62])
    display = np.where(np.isfinite(matrix), matrix, np.nan)
    image = ax.imshow(display, cmap="viridis", vmin=0,
                      vmax=max(0.25, np.nanmax(display)))
    ax.set_xticks(range(len(channels)))
    ax.set_yticks(range(len(channels)))
    ax.set_xticklabels([f"CH{c}" for c in channels], fontsize=CAPTION_SIZE)
    ax.set_yticklabels([f"CH{c}" for c in channels], fontsize=CAPTION_SIZE)
    ax.set_xlabel("applied to  (B)", fontsize=LABEL_SIZE)
    ax.set_ylabel("shapes learned on  (A)", fontsize=LABEL_SIZE)

    for i in range(len(channels)):
        for j in range(len(channels)):
            if i == j:
                ax.text(j, i, "—", ha="center", va="center",
                        fontsize=CAPTION_SIZE, color="#6f6f6f")
                continue
            if not np.isfinite(matrix[i, j]):
                continue
            entry = detail[f"{channels[i]}->{channels[j]}"]
            bright = matrix[i, j] > 0.5 * np.nanmax(display)
            ax.text(j, i,
                    f"{matrix[i, j]:.3f}\n"
                    f"({adjusted[i, j]:+.3f})\n"
                    f"p{'≤' if entry['at_p_floor'] else '='}"
                    f"{max(entry['p'], entry['p_floor']):.3f}",
                    ha="center", va="center", fontsize=CAPTION_SIZE - 1.5,
                    color="#20202a" if bright else "white")
    fig.colorbar(image, ax=ax, fraction=0.045, label="adjusted Rand index")
    ax.set_title(f"ARI between B's own clustering and B assigned to A's "
                 f"medoids, k = {k}\n(bracketed value is ARI minus its "
                 f"permutation-null median)",
                 fontsize=CAPTION_SIZE + 1, pad=8)

    # -- the medoids themselves -------------------------------------------
    ax2 = fig.add_axes([0.53, 0.19, 0.43, 0.62])
    for index, channel in enumerate(channels):
        waves = medoid_waveforms.get(channel)
        if waves is None:
            continue
        colour = CHANNEL_COLOURS[channel % len(CHANNEL_COLOURS)]
        for order, wave in enumerate(waves):
            ax2.plot(wave, color=colour, lw=1.7,
                     alpha=0.85 if order == 0 else 0.5,
                     label=f"CH{channel}" if order == 0 else None)
    ax2.set_xticks([])
    ax2.set_yticks([])
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(frameon=False, fontsize=CAPTION_SIZE, ncol=5,
               loc="lower right")
    ax2.set_title("every channel's family medoids, on one normalised axis",
                  fontsize=CAPTION_SIZE + 1, pad=8)
    ax2.set_xlabel("resampled to 200 points; each event z-normalised, so "
                   "this axis carries shape and not millivolts",
                   fontsize=CAPTION_SIZE - 1)

    fig.suptitle(title, fontsize=TITLE_SIZE, y=0.965)
    return _save(fig, out_path)


# ---------------------------------------------------------------------------
# Task D - the floor
# ---------------------------------------------------------------------------

def plot_floor_sensitivity(noise, floors, before, under_global,
                           under_channel, calibration, out_path, *,
                           multiplier, global_floor=0.1,
                           title="Task D — the global floor is a "
                                 "channel-dependent filter"):
    """Three panels: what each floor is, what it keeps, and what it does to
    the amplitude comparison the paper rests on.

    Panel B draws the SURVIVING FRACTION rather than the surviving count,
    because the claim is about the floor's severity per electrode and a
    count conflates that with how many events the electrode had.
    """
    channels = sorted(noise)
    fig = plt.figure(figsize=(16.0, 7.8))

    # -- A: the floors themselves -----------------------------------------
    ax = fig.add_axes([0.055, 0.22, 0.26, 0.56])
    values = [floors[c] for c in channels]
    ax.bar(range(len(channels)), values,
           color=[CHANNEL_COLOURS[c % len(CHANNEL_COLOURS)]
                  for c in channels],
           width=0.62, edgecolor="white", lw=1.0)
    ax.axhline(global_floor, color=FLOOR_COLOUR, lw=1.8, ls="--")
    ax.text(len(channels) - 0.4, global_floor * 1.03,
            f"global {global_floor} mV", ha="right", va="bottom",
            fontsize=CAPTION_SIZE, color=FLOOR_COLOUR)
    for index, channel in enumerate(channels):
        ax.text(index, values[index] * 1.03, f"{values[index]:.3f}",
                ha="center", va="bottom", fontsize=CAPTION_SIZE - 1)
    ax.set_xticks(range(len(channels)))
    ax.set_xticklabels([f"CH{c}" for c in channels], fontsize=CAPTION_SIZE)
    ax.set_ylabel("depth floor (mV)", fontsize=LABEL_SIZE)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"A — {multiplier}σ of each channel's own slope noise\n"
                 f"floor = {multiplier} × σ_slope / fs",
                 fontsize=CAPTION_SIZE + 1.5, pad=8)

    # -- B: what each floor keeps -----------------------------------------
    ax2 = fig.add_axes([0.385, 0.22, 0.26, 0.56])
    width = 0.36
    positions = np.arange(len(channels))
    for offset, (population, colour, label) in enumerate((
            (under_global, FLOOR_COLOUR, f"global {global_floor} mV"),
            (under_channel, OBSERVED_COLOUR, f"per-channel {multiplier}σ"))):
        kept = []
        for channel in channels:
            total = before["per_channel"].get(channel, {}).get("n", 0)
            n = population["per_channel"].get(channel, {}).get("n", 0)
            kept.append(100.0 * n / total if total else 0.0)
        ax2.bar(positions + (offset - 0.5) * width, kept, width=width * 0.92,
                color=colour, edgecolor="white", lw=1.0, label=label)
        for x, value in zip(positions + (offset - 0.5) * width, kept):
            ax2.text(x, value + 1.2, f"{value:.0f}", ha="center",
                     va="bottom", fontsize=CAPTION_SIZE - 1.5)
    ax2.set_xticks(positions)
    ax2.set_xticklabels([f"CH{c}" for c in channels], fontsize=CAPTION_SIZE)
    ax2.set_ylabel("% of the unfloored population kept",
                   fontsize=LABEL_SIZE)
    ax2.set_ylim(0, 108)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(frameon=False, fontsize=CAPTION_SIZE, loc="lower left",
               bbox_to_anchor=(0.0, -0.02))
    ax2.set_title("B — the global floor's severity is set by how quiet\n"
                  "each electrode happens to be",
                  fontsize=CAPTION_SIZE + 1.5, pad=8)

    # -- C: the amplitude comparison --------------------------------------
    ax3 = fig.add_axes([0.715, 0.22, 0.255, 0.56])
    for population, colour, label, marker in (
            (before, "#b8b8b8", "no floor", "o"),
            (under_global, FLOOR_COLOUR, f"global {global_floor} mV", "s"),
            (under_channel, OBSERVED_COLOUR,
             f"per-channel {multiplier}σ", "^")):
        medians = [population["per_channel"].get(c, {}).get(
            "median_depth_mv", np.nan) for c in channels]
        ax3.plot(range(len(channels)), medians, marker=marker, ms=8,
                 color=colour, lw=1.6, label=label)
    ax3.set_xticks(range(len(channels)))
    ax3.set_xticklabels([f"CH{c}" for c in channels], fontsize=CAPTION_SIZE)
    ax3.set_ylabel("median drop depth (mV)", fontsize=LABEL_SIZE)
    ax3.set_yscale("log")
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.legend(frameon=False, fontsize=CAPTION_SIZE - 0.5)
    ax3.set_title(
        f"C — spread across electrodes:  "
        f"{before['amplitude_spread']:.2f}× unfloored,  "
        f"{under_global['amplitude_spread']:.2f}× global,  "
        f"{under_channel['amplitude_spread']:.2f}× per-channel",
        fontsize=CAPTION_SIZE + 1.5, pad=8)

    fig.suptitle(title, fontsize=TITLE_SIZE, y=0.965)
    _caption(fig, _wrap(
        "SENSITIVITY RESULT — the global 0.1 mV floor remains the headline "
        "store; it is the operator's stated instrument figure, and "
        "replacing it is a decision about the instrument rather than "
        f"about an analysis.  The multiplier was fixed at {multiplier}σ "
        "before the per-channel numbers were computed; "
        "TASK_D_floor.json carries the floors every other multiplier in "
        + ", ".join(str(m) for m in calibration) + " would have given.",
        150))
    return _save(fig, out_path)


def _column_note(results, model, representation):
    """What the confusion matrix actually does, computed from the matrix.

    An earlier draft asserted "the forest answers CH1 for every true
    channel", which was true of one run's panel and false of the next -
    the selected model changed and so did the collapse. A caption that
    describes a figure must be derived from it.
    """
    entry = results[representation][model]
    matrix = np.asarray(entry["confusion_matrix"], dtype=float)
    rows = matrix.sum(axis=1, keepdims=True)
    normalised = np.divide(matrix, np.where(rows > 0, rows, 1))
    labels = entry["confusion_labels"]

    share = normalised.sum(axis=0) / normalised.shape[0]
    heaviest = int(np.argmax(share))
    diagonal = float(np.mean(np.diag(normalised)))
    if share[heaviest] < 0.30:
        return (f"The {representation.upper()} matrix has no strongly "
                f"preferred column; its mean diagonal is "
                f"{diagonal * 100:.0f}%, against {100 / len(labels):.0f}% "
                f"for a classifier answering at random.")
    return (f"Read the {representation.upper()} matrix's columns: with "
            f"little site information to go on it answers "
            f"CH{labels[heaviest]} for {share[heaviest] * 100:.0f}% of "
            f"events across every true channel, and its mean diagonal is "
            f"only {diagonal * 100:.0f}%.")
