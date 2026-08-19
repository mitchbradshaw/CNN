"""
cluster.py
===========
Is the rise-then-drop sub-shape itself a recurring motif, and if so how
many kinds of it are there?

Two axes, kept separate, mirroring what `seed_replicas.py` already
established on this data:

  WHAT SHAPE IS IT     resample to a common length, z-normalise, cluster.
  HOW CLEAN IS IT      roughness of the member against its own cluster's
                       mean waveform.

Keeping them separate rather than folding roughness into the distance is
the finding `seed_replicas.py` demonstrated is real here: z-normalised
Euclidean distance cannot tell a clean copy of a shape from a jagged span
following the same trend, because the noise is zero-mean and cancels in
the sum of squared differences. Measured there, roughness varied by 16x
among matches at essentially identical distance. So roughness is used as a
QC filter on what gets drawn, and its excluded fraction is reported - it
is not a clustering dimension, and there is no composite distance with
weights nobody can justify.

Why resample-and-z-normalise before clustering, and why the OVERLAYS then
do neither
-----------------------------------------------------------------------
The two recordings' drops differ by two orders of magnitude in duration
(seconds on Mushroom_260720, minutes on M2_aug) and by a factor of four in
amplitude. Asking "is this the same shape" across them is only meaningful
after both are removed - that is exactly what
`Working.distances.scale_invariant_distance` does internally, and it is
the reason a cluster containing both recordings' events is evidence for
scale-freeness rather than an artefact.

The rendered overlays must then do the opposite and normalise NOTHING.
The submission this serves names the failure directly: "normalisation of
amplitude destroys the evidence of scaling laws for depolarisation
events". The clustering maths z-normalises so that "same shape" has a
definition; the figure shows millivolts so that the scaling is visible.
Both are correct and they must not be conflated - `feature_matrix` below
is the only place normalisation happens.

Ward on the resampled vectors rather than average-linkage on a pairwise
matrix
--------------------------------------------------------------------
`family_search.cluster_order` builds an O(n^2) `scale_invariant_distance`
matrix and runs average linkage on it. That is the right tool there,
because its exemplars are of wildly different lengths and the pairwise
resampling is unavoidable. Here every event is resampled to one common
length anyway, so the vectors are directly Euclidean-comparable and Ward
applies - the same choice `Working/Catalogue/dendrogram/dendrogram_cluster
.py` makes on window-matrix features. Ward is preferred because it
minimises within-cluster variance and so produces the compact, roughly
even clusters that a per-cluster overlay figure needs to be legible.

The pairwise matrix is still built (`distance_matrix`) because the
heatmap and the cophenetic check want it, and because it is the control:
if Ward on the vectors and average linkage on the scale-invariant matrix
disagree about the gross structure, that is worth knowing before the
figure is believed.

No plotting library - CLAUDE.md rule 1.
"""

import numpy as np
from scipy.cluster.hierarchy import cophenet, dendrogram, fcluster, linkage
from scipy.spatial.distance import pdist, squareform

from Working.distances import (
    DISTANCE_SCALE_INVARIANT,
    native_length_distance,
    resample_to_length,
    scale_invariant_distance,
    z_normalize,
)

# Common length every drop is resampled to before clustering. 200 points
# is comfortably above the shortest real drop's own sample count (a
# Mushroom icicle snippet is ~35 samples at 1 Hz) so no event is
# upsampled into detail it does not have beyond a factor of six, and
# comfortably below the longest (an M2_aug snippet is ~2000 samples) so
# the vectors stay small. Exposed rather than buried: change it and the
# Ward distances change scale, though not the tree's structure.
DEFAULT_RESAMPLE_LENGTH = 200

DEFAULT_LINKAGE = "ward"
DEFAULT_MAX_ROUGHNESS = 2.0     # matches seed_replicas.DEFAULT_MAX_ROUGHNESS


def roughness(values):
    """RMS first difference of the z-normalised span.

    Identical definition to `Pipelines.motif_report.seed_replicas.
    roughness`, restated here rather than imported because `Working/` must
    not depend on `Pipelines/` - the dependency runs the other way, the
    same rule `dsax._letter` documents for `Adapters/`. Four lines, and
    `tests/test_drop_motifs_detect.py` is where a divergence would show.
    z-normalising first makes it independent of amplitude, so it measures
    only how much of the span's variance sits at the sampling frequency.
    """
    values = np.asarray(values, dtype=float).ravel()
    if len(values) < 2:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(z_normalize(values)) ** 2)))


# -- features --------------------------------------------------------------

def event_waveform(snippets, event, field="detrended_mv"):
    """One event's samples, from the store.

    Defaults to the DETRENDED trace because that is what detection ran on
    and what "the same shape" was defined against; the raw trace is what
    the overlays draw. Passing the wrong one here is the kind of mistake
    that produces a plausible dendrogram of baseline drift, so the default
    is the safe one and the choice is explicit.
    """
    return np.asarray(snippets[event["event_id"]][field], dtype=float)


def feature_matrix(waveforms, n_samples=DEFAULT_RESAMPLE_LENGTH):
    """(n_events, n_samples) of resampled, z-normalised drops.

    THE only place normalisation happens in this pipeline. Everything
    downstream of a linkage is shape; everything drawn is millivolts.
    """
    return np.vstack([
        z_normalize(resample_to_length(w, n_samples)) for w in waveforms
    ])


def distance_matrix(waveforms, metric=DISTANCE_SCALE_INVARIANT):
    """Pairwise distance, divided by sqrt(n) so it reads as RMS z-score
    difference per sample and stays comparable across lengths - the same
    convention `motif_report --max-distance-norm` and
    `family_search.cross_scale_matrix` already use, so a number here is
    directly comparable to a number on the existing figures.
    """
    n = len(waveforms)
    D = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = waveforms[i], waveforms[j]
            if metric == DISTANCE_SCALE_INVARIANT:
                common = max(len(a), len(b))
                d = scale_invariant_distance(a, b) / np.sqrt(common)
            else:
                common = min(len(a), len(b))
                d = native_length_distance(a, b) / np.sqrt(common)
            D[i, j] = D[j, i] = d
    return D


# -- the tree --------------------------------------------------------------

def build_linkage(features, method=DEFAULT_LINKAGE):
    """Ward linkage over the resampled, z-normalised vectors.

    Returns `(Z, cophenetic_r)`. The cophenetic correlation is how
    faithfully the tree's merge heights reproduce the original pairwise
    distances - below about 0.7 the dendrogram is a picture of the linkage
    algorithm rather than of the data, and the figure should say so rather
    than be believed. `dendrogram_cluster.py` reports the same number for
    the same reason.
    """
    features = np.asarray(features, dtype=float)
    if len(features) < 2:
        raise ValueError(
            f"clustering needs at least 2 events, got {len(features)} - "
            "a run that found fewer has nothing to cluster and should be "
            "reported as such, not silently clustered into one group")
    condensed = pdist(features, metric="euclidean")
    Z = linkage(condensed, method=method)
    coph, _ = cophenet(Z, condensed)
    return Z, float(coph)


def cut_tree(Z, n_clusters=None, height=None):
    """Flat labels from the tree, 1-based as scipy returns them.

    Exactly one of `n_clusters` / `height`. Two ways to cut because they
    answer different questions: `n_clusters` when the figure needs a fixed
    number of panels, `height` when the claim is about a distance.
    """
    if (n_clusters is None) == (height is None):
        raise ValueError("pass exactly one of n_clusters or height")
    if n_clusters is not None:
        return fcluster(Z, int(n_clusters), criterion="maxclust")
    return fcluster(Z, float(height), criterion="distance")


def suggest_n_clusters(Z, max_k=10):
    """The largest gap in the merge heights, capped.

    A heuristic and reported as one, not a model-selection result: the
    biggest jump between consecutive merge heights is where the tree is
    saying "these two groups were much further apart than anything merged
    below". Same idea as `dendrogram_cluster._suggest_n_clusters`; it
    exists so a run has a defensible default cut rather than a magic
    number, and the editorial choice of the final cut stays with a human.
    """
    heights = Z[:, 2]
    if len(heights) < 3:
        return 2
    # Walk the last `max_k` merges: merge i from the end produces i+1
    # clusters if cut just above it.
    tail = heights[-min(max_k, len(heights)):]
    gaps = np.diff(tail)
    if gaps.size == 0:
        return 2
    best = int(np.argmax(gaps))
    return int(len(tail) - best)


def leaf_order(Z):
    """Left-to-right leaf order, without drawing anything.

    `no_plot=True` keeps this module free of matplotlib while still using
    scipy's own ordering, so the headless cluster table and the drawn
    figure can never disagree about which leaf is where.
    """
    return list(dendrogram(Z, no_plot=True)["leaves"])


# -- roughness QC ----------------------------------------------------------

def cluster_mean_waveform(features, labels, cluster_id):
    """The cluster's mean SHAPE, in feature space.

    The mean of the resampled z-normalised vectors, not of the raw
    millivolts: averaging raw traces of different duration and amplitude
    produces a smear that is not a member of the family and not a shape.
    """
    members = features[labels == cluster_id]
    return members.mean(axis=0) if len(members) else None


def roughness_report(features, labels, max_ratio=DEFAULT_MAX_ROUGHNESS):
    """Per-event roughness relative to its own cluster's mean waveform.

    `split_by_roughness` in `seed_replicas.py` measures each match against
    a hand-picked seed. There is no seed here - these families were found,
    not sought - so the cluster's own mean is the reference. Same reading
    of the threshold: nothing kept is more than `max_ratio` times as
    jagged as the shape it is supposed to be an instance of.

    Returns `{"ratios": array, "keep": bool array, "excluded_fraction":
    float, "per_cluster": {...}}`. Nothing is deleted here - the caller
    decides what to draw, and the excluded fraction is reported either way.
    """
    features = np.asarray(features, dtype=float)
    labels = np.asarray(labels)
    ratios = np.full(len(features), np.nan, dtype=float)
    per_cluster = {}

    for cluster_id in sorted(set(labels.tolist())):
        mask = labels == cluster_id
        mean_shape = cluster_mean_waveform(features, labels, cluster_id)
        reference = roughness(mean_shape)
        member_roughness = np.array([roughness(f) for f in features[mask]])
        if reference > 0:
            cluster_ratios = member_roughness / reference
        else:
            # A perfectly smooth mean (a cluster of one, or of identical
            # members) gives no reference to divide by. inf would exclude
            # everything including the member that IS the mean, so the
            # honest answer is "no ratio is defined here".
            cluster_ratios = np.ones(int(mask.sum()))
        ratios[mask] = cluster_ratios
        per_cluster[int(cluster_id)] = {
            "n": int(mask.sum()),
            "mean_roughness": float(reference),
            "ratio_min": float(cluster_ratios.min()) if cluster_ratios.size else 0.0,
            "ratio_max": float(cluster_ratios.max()) if cluster_ratios.size else 0.0,
            "n_excluded": int((cluster_ratios > max_ratio).sum()),
        }

    keep = ratios <= max_ratio
    return {
        "ratios": ratios,
        "keep": keep,
        "max_ratio": float(max_ratio),
        "excluded_fraction": float((~keep).mean()) if len(keep) else 0.0,
        "per_cluster": per_cluster,
    }


# -- composition -----------------------------------------------------------

def cluster_composition(events, labels):
    """Per-cluster breakdown by source recording.

    This is the number the cross-dataset claim rests on and it is reported
    as a table, not left to be read off leaf colours: a cluster mixing
    both recordings' events is a same-shape-across-datasets finding, a
    cluster that is pure one recording is a divergence finding, and a
    reviewer will want the count either way.
    """
    labels = np.asarray(labels)
    rows = []
    for cluster_id in sorted(set(labels.tolist())):
        members = [e for e, lab in zip(events, labels) if lab == cluster_id]
        by_recording = {}
        for event in members:
            # Keyed on the SPAN, not the source file: three of the shipped
            # spans share one file, and a composition table that merged
            # them would hide exactly the structure this table exists to
            # report.
            key = (event.get("span_label") or event.get("span_key")
                   or f"{event['source_file']} (id={event['recording_id']})")
            by_recording[key] = by_recording.get(key, 0) + 1
        depths = [e["drop_depth_mv"] for e in members]
        falls = [e["fall_duration_s"] for e in members]
        rows.append({
            "cluster_id": int(cluster_id),
            "n": len(members),
            "n_recordings": len(by_recording),
            "composition": by_recording,
            "pure": len(by_recording) == 1,
            "median_depth_mv": float(np.median(depths)) if depths else 0.0,
            "median_fall_s": float(np.median(falls)) if falls else 0.0,
            "depth_range_mv": [float(min(depths)), float(max(depths))] if depths else [0.0, 0.0],
            "fall_range_s": [float(min(falls)), float(max(falls))] if falls else [0.0, 0.0],
        })
    return rows


def cluster_events(events, snippets, *, n_clusters=None, height=None,
                   n_samples=DEFAULT_RESAMPLE_LENGTH, method=DEFAULT_LINKAGE,
                   max_roughness=DEFAULT_MAX_ROUGHNESS, field="detrended_mv"):
    """The whole clustering step in one call.

    Returns everything the figures and the summary need, computed once:
    the waveforms in their native units, the feature matrix, the linkage,
    the labels, the leaf order, the roughness report and the composition
    table. Computed once and passed around rather than recomputed per
    figure, so the dendrogram's leaf order and the overlay grid's cluster
    order provably describe the same clustering.
    """
    waveforms = [event_waveform(snippets, e, field=field) for e in events]
    features = feature_matrix(waveforms, n_samples)
    Z, cophenetic_r = build_linkage(features, method=method)

    if n_clusters is None and height is None:
        n_clusters = suggest_n_clusters(Z)
    labels = cut_tree(Z, n_clusters=n_clusters, height=height)

    return {
        "events": events,
        "waveforms": waveforms,
        "features": features,
        "linkage": Z,
        "cophenetic_r": cophenetic_r,
        "labels": labels,
        "n_clusters": int(len(set(labels.tolist()))),
        "leaves": leaf_order(Z),
        "roughness": roughness_report(features, labels, max_roughness),
        "composition": cluster_composition(events, labels),
        "method": method,
        "resample_length": int(n_samples),
    }


def condensed_from_matrix(D):
    """`squareform` with checks off - the same call `family_search.
    cluster_order` makes, kept here so the control path (average linkage
    on the scale-invariant matrix) is one line for a caller that wants to
    compare it against the Ward tree."""
    return squareform(np.asarray(D, dtype=float), checks=False)
