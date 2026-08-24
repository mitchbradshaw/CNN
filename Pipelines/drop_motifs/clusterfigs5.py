"""
clusterfigs5.py
================
Figures 2 and 3: the dendrogram and the gradient rose, per span and pooled
across every span.

Impure windows are excluded from BOTH, before anything is computed. That
is the point of the exercise: a window holding several falls is a picture
of a burst, and a shape family that averages one in is describing
something that is not a motif. The count excluded is printed on every
figure rather than left implicit, because "clustered on the clean subset"
is only an honest claim if the size of the subset is visible.

The numeric cores are the existing ones - `cluster.feature_matrix`,
`cluster.build_linkage`, `cluster.cut_tree`, `gradients.rose_data` - which
is why `motifs5` writes its store in the shape those functions already
read. The drawing here is new only because it has to key colour and
composition on `catalogue_id`, which the shipped figures do not have.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from scipy.cluster.hierarchy import dendrogram

from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg

# Distinct hues for spans in the pooled figures. `tab20` rather than a
# continuous map because span identity is categorical - a continuous ramp
# would imply that ID 21 sits between ID 20 and ID 22 in some quantity,
# and it does not.
SPAN_CMAP = "tab20"

# Cophenetic correlation below which the tree is reporting the linkage
# algorithm rather than the data. Stated on the figure rather than
# enforced, following `cluster.build_linkage`'s own note.
COPHENETIC_FLOOR = 0.70

# Leaves above which per-leaf text labels are dropped for a colour strip.
# 362 pooled motifs at a legible font produced a 9,398-pixel-tall image.
LABEL_LIMIT = 70


# tab20 is ordered as ten DARK/LIGHT pairs of the same hue, so consecutive
# indices give two shades of one colour - with two spans that produced two
# near-identical blues and the legend could not be read. Walking the dark
# half first and the light half second keeps adjacent spans in different
# hues however many there are.
_TAB20_ORDER = tuple(range(0, 20, 2)) + tuple(range(1, 20, 2))


def span_colours(catalogue_ids):
    """`{catalogue_id: rgba}`, stable under the set of ids present."""
    mapper = cm.get_cmap(SPAN_CMAP)
    unique = sorted({int(c) for c in catalogue_ids})
    return {cid: mapper(_TAB20_ORDER[i % 20] / 19.0)
            for i, cid in enumerate(unique)}


def _catalogue_id_of(span_key):
    """`"id021"` -> `21`. The rose splits by `span_key`; colours are keyed
    by catalogue id so the rose and the dendrogram agree."""
    digits = "".join(c for c in str(span_key) if c.isdigit())
    return int(digits) if digits else -1


def _waveforms(events, snippets, field="detrended_mv"):
    """The DROP itself, onset to trough, not the whole window.

    Clustering the whole window would cluster the context - how much quiet
    each event happens to sit in - which varies with the bracket and is
    not a property of the motif. `cluster.event_waveform` returns the full
    stored array, so the slice happens here.
    """
    out = []
    for event in events:
        values = np.asarray(snippets[event["event_id"]][field], dtype=float)
        start = int(event["snippet_start_idx"])
        onset = int(np.clip(int(event["onset_idx"]) - start, 0, values.size - 1))
        trough = int(np.clip(int(event["trough_idx"]) - start, onset + 1,
                             values.size))
        drop = values[onset:trough]
        # Two samples is the minimum a resample can interpolate between;
        # a one-sample "drop" is a detection artefact and would otherwise
        # crash the feature matrix rather than being visible.
        out.append(drop if drop.size >= 2 else values[onset:onset + 2])
    return out


def _label(event):
    return (f"id{event['catalogue_id']:03d} "
            f"{event['drop_depth_mv']:.1f}mV/{event['fall_duration_s']:.0f}s")


def plot_dendrogram(events, snippets, out_path, *, title, n_clusters=None,
                    colour_by_span=False, excluded=0):
    """Ward tree over the pure drops. Returns `(path, info)` or `(None, ..)`.

    Fewer than three events is not a tree and is reported as such rather
    than drawn - two leaves always merge at one height, which looks like a
    result and is not.
    """
    if len(events) < 3:
        return None, {"reason": f"only {len(events)} pure motifs; "
                                f"a tree needs at least 3"}

    waveforms = _waveforms(events, snippets)
    features = dc.feature_matrix(waveforms)
    Z, cophenetic = dc.build_linkage(features)

    if n_clusters is None:
        n_clusters = dc.suggest_n_clusters(Z)
    n_clusters = max(2, min(int(n_clusters), len(events) - 1))
    labels = dc.cut_tree(Z, n_clusters=n_clusters)

    # Above this many leaves a per-leaf text label is unreadable at any
    # figure size that fits on a page: 362 pooled motifs at a legible font
    # produced a 9,398-pixel-tall image. Past the limit the labels are
    # replaced by a colour strip, which carries the only thing the pooled
    # tree is actually asked - which spans land together - in a form that
    # survives being shrunk.
    labelled = len(events) <= LABEL_LIMIT
    height = (max(4.0, 0.20 * len(events)) if labelled
              else min(16.0, max(6.0, 0.03 * len(events))))

    fig = plt.figure(figsize=(11.0, height))
    if labelled:
        ax = fig.add_subplot(111)
        strip = None
    else:
        grid = fig.add_gridspec(1, 2, width_ratios=[40, 1], wspace=0.01)
        ax = fig.add_subplot(grid[0, 0])
        strip = fig.add_subplot(grid[0, 1], sharey=ax)

    palette = span_colours([e["catalogue_id"] for e in events])
    result = dendrogram(
        Z, orientation="left", ax=ax,
        labels=[_label(e) for e in events] if labelled else None,
        no_labels=not labelled,
        color_threshold=None if colour_by_span else _cut_height(Z, n_clusters),
        above_threshold_color="0.6",
        leaf_font_size=max(5, min(8, int(220 / max(1, len(events))))))

    order = result["leaves"]
    if colour_by_span:
        # Repaint every link grey and carry span identity on the leaves
        # instead. Colouring LINKS by span is not possible in general - an
        # internal node can join two spans - and pretending otherwise
        # would draw a tree that contradicts its own legend.
        for line in ax.collections:
            line.set_color("0.55")
        if labelled:
            for tick, leaf in zip(ax.get_ymajorticklabels(), order):
                tick.set_color(palette[int(events[leaf]["catalogue_id"])])

    if strip is not None:
        # scipy places leaf i at y = 10i + 5, in leaf order.
        for position, leaf in enumerate(order):
            colour = (palette[int(events[leaf]["catalogue_id"])]
                      if colour_by_span else "0.4")
            strip.axhspan(10 * position, 10 * (position + 1),
                          color=colour, lw=0)
        strip.set_xticks([])
        strip.set_yticks([])
        strip.set_ylim(0, 10 * len(order))
        for side in ("top", "right", "bottom", "left"):
            strip.spines[side].set_visible(False)
        if colour_by_span:
            present = sorted({int(e["catalogue_id"]) for e in events})
            handles = [plt.Line2D([0], [0], color=palette[cid], lw=6,
                                  label=f"id{cid:03d}") for cid in present]
            ax.legend(handles=handles, loc="center left",
                      bbox_to_anchor=(1.03, 0.5), fontsize=7, frameon=False,
                      ncol=1 if len(present) <= 16 else 2)

    note = ""
    if cophenetic < COPHENETIC_FLOOR:
        note = (f"  ·  cophenetic r={cophenetic:.2f} is below "
                f"{COPHENETIC_FLOOR:g}: read this tree with caution")
    else:
        note = f"  ·  cophenetic r={cophenetic:.2f}"

    ax.set_title(
        f"{title}\nn={len(events)} pure motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + f", k={n_clusters}{note}",
        fontsize=10)
    ax.set_xlabel("Ward merge distance (z-normalised shape)")
    if strip is None:
        # `tight_layout` cannot lay out the shared-y colour strip and warns
        # rather than failing, which would leave a misleading warning in
        # every pooled run. `bbox_inches="tight"` on save does the job.
        fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)

    return str(out_path), {
        "n": len(events),
        "excluded": int(excluded),
        "n_clusters": int(n_clusters),
        "cophenetic_r": float(cophenetic),
        "labels": [int(v) for v in labels],
        "composition": _composition(events, labels),
    }


def _cut_height(Z, n_clusters):
    """The height that produces `n_clusters`, for scipy's colouring.

    Midway between the two merges that straddle the cut, so a float
    comparison inside scipy cannot land on the wrong side of it.
    """
    heights = np.sort(Z[:, 2])
    if n_clusters >= len(heights) + 1:
        return 0.0
    upper = heights[-(n_clusters - 1)]
    lower = heights[-n_clusters] if n_clusters <= len(heights) else 0.0
    return float((upper + lower) / 2.0)


def _composition(events, labels):
    out = {}
    for label, event in zip(labels, events):
        bucket = out.setdefault(str(int(label)), {})
        key = f"id{int(event['catalogue_id']):03d}"
        bucket[key] = bucket.get(key, 0) + 1
    return out


# -- the rose --------------------------------------------------------------

def plot_rose(events, snippets, out_path, *, title, split_by="span_key",
              colour_by_span=False, excluded=0, field="max_slope_mv_s",
              scale="raw"):
    """Fall-gradient rose over the pure motifs.

    `rose_data` is the shipped computation, unchanged, so a number quoted
    here is directly comparable to one on the existing figures. `max_slope`
    rather than `onset_slope` is its default for a measured reason
    recorded there: `np.gradient` is a central difference and halves the
    apparent steepness exactly at the corner where flat meets fall.
    """
    if not events:
        return None, {"reason": "no pure motifs"}

    data = dg.rose_data(events, snippets, scale=scale, field=field,
                        split_by=split_by)
    if not data["n"]:
        return None, {"reason": "no gradients computable"}

    fig = plt.figure(figsize=(7.6, 7.4))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    ax.set_thetamin(-90)
    ax.set_thetamax(0)

    if colour_by_span and len(data["groups"]) > 1:
        # Stacked, so the pooled shape is still the outline while each
        # span's contribution to every bin stays readable.
        palette = span_colours(_catalogue_id_of(k) for k in data["groups"])
        bottom = np.zeros_like(data["counts"], dtype=float)
        for key, group in sorted(data["groups"].items()):
            colour = palette[_catalogue_id_of(key)]
            ax.bar(data["bin_centres"], group["counts"], width=data["bin_width"],
                   bottom=bottom, color=colour, edgecolor="white",
                   linewidth=0.4, label=f"{key} (n={group['n']})")
            bottom = bottom + group["counts"]
        ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.10), fontsize=7,
                  frameon=False)
    else:
        ax.bar(data["bin_centres"], data["counts"], width=data["bin_width"],
               color="#2a6f97", edgecolor="white", linewidth=0.5)

    mean = np.deg2rad(data["mean_deg"])
    ax.plot([mean, mean], [0, max(data["counts"]) if len(data["counts"]) else 1],
            color="#c1272d", lw=2.0, zorder=5)

    ax.set_title(
        f"{title}\n"
        f"n={data['n']} pure motifs"
        + (f", {excluded} impure excluded" if excluded else "")
        + f"  ·  mean {data['mean_deg']:.1f}°  ·  R={data['resultant_length']:.3f}"
          f"  ·  circular SD {data['circular_sd_deg']:.1f}°\n"
        f"{data['caption']}  ·  uniformity p={data['uniformity_p']:.2g} "
        f"(KS over the quadrant, not Rayleigh)",
        fontsize=9, pad=26)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
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
        "groups": {
            str(k): {
                "n": int(v["n"]),
                "mean_deg": float(v["mean_deg"]),
                "resultant_length": float(v["resultant_length"]),
                "circular_sd_deg": float(v["circular_sd_deg"]),
                "median_slope_mv_s": float(v["median_slope_mv_s"]),
            } for k, v in data["groups"].items()
        },
    }
