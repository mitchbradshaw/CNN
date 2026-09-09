"""
tree10.py
==========
One tree over one store, and the feature matrix underneath it. Everything
in Tasks 4 and 5 reads its grouping from here so that no two figures can
be describing different trees.

The representation, and what it does and does not carry
-------------------------------------------------------
An event's waveform is its own samples from `onset_idx` to `trough_idx` -
the fall, not the snippet. `cluster.feature_matrix` resamples that to 200
points and z-normalises it, so BOTH the event's duration and its amplitude
are divided out before any distance is taken. The tree is Ward over plain
Euclidean distance between those vectors; `cluster.distance_matrix` is a
different utility and has produced no shipped dendrogram
(`nulls_v1/README.md` sec 1 settles this by recomputation).

That normalisation is what makes "the same shape at different scales" a
meaningful question. It is ALSO the thing Task 5b exists to test, because
resampling 7 samples to 200 points and resampling 150 samples to 200
points are not the same operation, and what survives of the difference is
the confound this whole run is built around.

Zero-variance rows
------------------
`feature_matrix` now raises on a constant waveform rather than returning
an all-zero vector, so this module filters them out FIRST and reports how
many there were. 22 of the 1058 shipped drop_motifs9 motifs were constants
that reached the tree as coincident points and inflated its cophenetic r
from 0.408 to 0.681. A count of zero here is a claim, so it is written
into every figure's JSON rather than assumed.

No plotting library.
"""

import numpy as np
from scipy.cluster.hierarchy import fcluster
from scipy.spatial.distance import pdist, squareform

from Pipelines.drop_motifs.clusterfigs7 import _waveform_of
from Working.Detection.drop_motifs import cluster

# The two cuts every figure reports, as drop_motifs9 reported them.
COARSE_K = 4
FINE_K = 10


def waveforms_of(rows, snippets, *, field="detrended_mv"):
    """`(waveforms, kept_rows, dropped)` - the falls, ready to featurise.

    A row is dropped if it has no stored array, if `_waveform_of` refuses
    it (the store disagreeing with itself), or if the fall it returns is
    constant. Each reason is counted separately, because they are three
    different faults and only the last is ever benign.
    """
    waveforms, kept = [], []
    dropped = {"no_array": 0, "store_mismatch": 0, "constant": 0}
    for row in rows:
        try:
            wave = _waveform_of(row, snippets, field=field,
                                orient_rises_as_drops=False)
        except ValueError:
            dropped["store_mismatch"] += 1
            continue
        if wave is None:
            dropped["no_array"] += 1
            continue
        wave = np.asarray(wave, dtype=float)
        if wave.size < 2 or float(np.ptp(wave)) == 0.0:
            dropped["constant"] += 1
            continue
        waveforms.append(wave)
        kept.append(row)
    return waveforms, kept, dropped


def build(rows, snippets, *, coarse_k=COARSE_K, fine_k=FINE_K,
          field="detrended_mv"):
    """The pooled tree. `None` if fewer than three motifs survive."""
    waveforms, kept, dropped = waveforms_of(rows, snippets, field=field)
    if len(kept) < 3:
        return None

    features = cluster.feature_matrix(waveforms)
    Z, cophenetic = cluster.build_linkage(features)

    n = len(kept)
    coarse_k = max(2, min(int(coarse_k), n - 1))
    fine_k = max(coarse_k, min(int(fine_k), n - 1))
    return {
        "rows": kept,
        "waveforms": waveforms,
        "features": features,
        "Z": Z,
        "cophenetic": float(cophenetic),
        "coarse_k": coarse_k,
        "fine_k": fine_k,
        "coarse": np.asarray(fcluster(Z, coarse_k, criterion="maxclust")),
        "fine": np.asarray(fcluster(Z, fine_k, criterion="maxclust")),
        "n": n,
        "dropped": dropped,
        "n_input": len(rows),
    }


def medoids(features, labels):
    """`{label: index_into_features}` - the member nearest its own centroid.

    A medoid rather than a mean, because a mean of z-normalised vectors is
    not itself a waveform any event has and cannot be drawn as one.
    """
    out = {}
    for label in np.unique(labels):
        members = np.flatnonzero(labels == label)
        if members.size == 1:
            out[int(label)] = int(members[0])
            continue
        block = features[members]
        centroid = block.mean(axis=0)
        distances = np.linalg.norm(block - centroid, axis=1)
        out[int(label)] = int(members[int(np.argmin(distances))])
    return out


def distances(features):
    """Condensed and square Euclidean distance over the feature vectors."""
    condensed = pdist(features, metric="euclidean")
    return condensed, squareform(condensed)


def family_table(rows, labels, field):
    """`{family: {value: count}}` - the raw contingency, before any test."""
    table = {}
    for row, label in zip(rows, labels):
        table.setdefault(int(label), {})
        key = row.get(field)
        table[int(label)][key] = table[int(label)].get(key, 0) + 1
    return table


def summarise_family(rows, labels, label_value):
    """Median depth, fall, and fall-in-samples for one family."""
    members = [r for r, lab in zip(rows, labels) if int(lab) == int(label_value)]
    if not members:
        return {}
    depth = np.asarray([abs(float(r["drop_depth_mv"])) for r in members])
    fall = np.asarray([float(r["fall_duration_s"]) for r in members])
    samples = np.asarray([int(r["n_samples_in_fall"]) for r in members])
    species = {}
    for r in members:
        species[r["species"]] = species.get(r["species"], 0) + 1
    return {
        "family": int(label_value),
        "n": len(members),
        "median_depth_mv": float(np.median(depth)),
        "median_fall_s": float(np.median(fall)),
        "median_fall_samples": float(np.median(samples)),
        "species": species,
    }
