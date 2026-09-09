"""
validity2.py
=============
Round 2, Tasks C and B2: is the partition real, and do shapes learned on
one electrode describe events on another?

TASK C - IS THE PARTITION REAL, OR IS IT JUST A CUT?
-----------------------------------------------------
Round one asked whether the families were TIGHTER than surrogates and got
a mixed answer. What it never asked is whether the clustering found
anything at all. Two cheap tests answer that, and neither needs a
surrogate.

  THE RANDOM-PARTITION NULL. Split the same events into groups of the same
  observed sizes, uniformly at random, and measure the same within-family
  distance. This is the test the family-COUNT comparison was reaching for
  and failing to make: counting families at a fixed cut height cannot
  distinguish a tree that found structure from one that did not, because
  both produce k groups. Comparing the tightness of the real grouping to
  the tightness of a random grouping of identical sizes can.

  BOOTSTRAP CO-ASSOCIATION. Resample the events with replacement,
  recluster, and record how often each pair of events lands in the same
  family. A family that survives resampling is a far stronger object than
  one that merely exists at one cut, and the mean within-family
  co-association is the number to quote in place of the family count the
  nulls rejected.

WHY 50 s BLOCK SHUFFLE IS NOT THE DAMNING RESULT IT LOOKS LIKE
---------------------------------------------------------------
Round one reported that the real families are not tighter than a 50 s
block shuffle's (2.342 against 2.346, p = 0.475) and filed it under what
the nulls did not support. That reading is too harsh, and the correction
belongs in the output rather than in a footnote.

A 50 s block shuffle preserves every waveform inside a block. It moves
blocks around in time and leaves their contents alone, so the SET OF
SHAPES it produces is very nearly the set of shapes in the recording. It
therefore cannot be a null for "is there a shape repertoire" - it contains
the repertoire by construction. What it IS a null for is "does the ORDER
of events matter", and its answer is that it does not.

That is consistent with shape being the invariant, not evidence against
it: if the repertoire is a property of the preparation rather than of the
sequence, shuffling the sequence should leave it alone, which is exactly
what was observed. The loss is a BOUND, and the bound is that these data
cannot distinguish a repertoire from a waveform-preserving reshuffling of
one - which is a statement about what a block shuffle can test, not about
the mycelium.

TASK B2 - CROSS-ELECTRODE FAMILY TRANSFER
------------------------------------------
The foundation-model-facing question. Cluster channel A's events on their
own, take each family's MEDOID, assign every channel B event to its
nearest A-medoid, and ask how well that agrees with B's own independent
clustering. High agreement means the shapes are the same objects on both
electrodes - that a model trained on one site transfers to another.

A medoid rather than a centroid because a centroid is an average of
z-normalised vectors and is not itself a waveform; a medoid is a real
event, so "the shapes CH0 learned" is a set of traces a reader can be
shown, which is what the figure's second panel does.
"""

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import cdist, pdist
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score

from Pipelines.drop_motifs.round2 import (SEED_BASE, medoid_index,
                                          within_family_distance)

N_RANDOM_PARTITIONS = 1000
N_BOOTSTRAP = 200
N_TRANSFER_PERMUTATIONS = 1000


# ---------------------------------------------------------------------------
# Task C
# ---------------------------------------------------------------------------

def random_partition_null(features, labels, *, n=N_RANDOM_PARTITIONS,
                          seed=SEED_BASE):
    """Within-family distance under random groupings of the observed sizes.

    The sizes are held fixed on purpose. Within-family distance falls as a
    group gets smaller, so a null that drew sizes at random would compare
    the real partition against groupings of a different shape and the
    result would be about size rather than about structure.
    """
    features = np.asarray(features, dtype=float)
    labels = np.asarray(labels)
    sizes = [int(np.sum(labels == v)) for v in sorted(set(labels.tolist()))]
    observed = within_family_distance(features, labels)

    rng = np.random.default_rng(seed)
    draws = np.empty(n, dtype=float)
    index = np.arange(features.shape[0])
    for i in range(n):
        shuffled = rng.permutation(index)
        random_labels = np.empty(features.shape[0], dtype=int)
        cursor = 0
        for family, size in enumerate(sizes, start=1):
            random_labels[shuffled[cursor:cursor + size]] = family
            cursor += size
        draws[i] = within_family_distance(features, random_labels)

    p = float((1 + int(np.sum(draws <= observed))) / (1 + n))
    return {
        "statistic": "mean within-family distance to centroid",
        "direction": "less (a real partition should be TIGHTER)",
        "observed": float(observed),
        "n_null": int(n),
        "null_median": float(np.median(draws)),
        "null_q1": float(np.percentile(draws, 25)),
        "null_q3": float(np.percentile(draws, 75)),
        "null_min": float(np.min(draws)),
        "null_max": float(np.max(draws)),
        "null_values": [float(v) for v in draws],
        "p": p,
        "p_floor": float(1.0 / (1 + n)),
        "at_p_floor": bool(p <= 1.0 / (1 + n)),
        "family_sizes_held_fixed": sizes,
        "seed": int(seed),
    }


def bootstrap_coassociation(features, k, *, method="ward",
                            metric="euclidean", n=N_BOOTSTRAP,
                            seed=SEED_BASE, reference_labels=None):
    """How often two events land in the same family across resamples.

    Returns the co-association matrix, the per-family stability, and the
    mean within- and between-family co-association.

    Only pairs where BOTH events were drawn are counted, and the divisor
    is the number of resamples in which that happened - not `n`. A
    bootstrap draws about 63% of the events each time, so dividing by `n`
    would report every pair at roughly 0.4x its real co-association and
    the whole matrix would read as instability that is an artefact of the
    resampling.
    """
    features = np.asarray(features, dtype=float)
    size = features.shape[0]
    together = np.zeros((size, size), dtype=float)
    both_drawn = np.zeros((size, size), dtype=float)

    rng = np.random.default_rng(seed)
    for _ in range(n):
        sample = np.unique(rng.integers(0, size, size))
        if sample.size < k + 1:
            continue
        block = features[sample]
        Z = linkage(pdist(block, metric=metric), method=method)
        labels = fcluster(Z, k, criterion="maxclust")

        both_drawn[np.ix_(sample, sample)] += 1.0
        for family in set(labels.tolist()):
            members = sample[labels == family]
            together[np.ix_(members, members)] += 1.0

    with np.errstate(invalid="ignore", divide="ignore"):
        coassociation = np.where(both_drawn > 0, together / both_drawn,
                                 np.nan)

    result = {
        "n_resamples": int(n), "k": int(k), "method": method,
        "metric": metric, "seed": int(seed),
        "mean_pairs_evaluated": float(np.nanmean(both_drawn)),
    }

    if reference_labels is not None:
        reference_labels = np.asarray(reference_labels)
        within, between, per_family = [], [], {}
        for family in sorted(set(reference_labels.tolist())):
            members = np.flatnonzero(reference_labels == family)
            others = np.flatnonzero(reference_labels != family)
            if members.size > 1:
                block = coassociation[np.ix_(members, members)]
                values = block[np.triu_indices(members.size, k=1)]
                values = values[np.isfinite(values)]
                per_family[int(family)] = {
                    "n": int(members.size),
                    "stability": float(np.mean(values)) if values.size
                    else float("nan"),
                }
                within.append(values)
            if members.size and others.size:
                block = coassociation[np.ix_(members, others)]
                between.append(block[np.isfinite(block)].ravel())

        result["per_family_stability"] = per_family
        result["mean_within_family_coassociation"] = float(
            np.mean(np.concatenate(within))) if within else float("nan")
        result["mean_between_family_coassociation"] = float(
            np.mean(np.concatenate(between))) if between else float("nan")
        result["separation"] = (
            result["mean_within_family_coassociation"]
            - result["mean_between_family_coassociation"])

    return coassociation, result


# ---------------------------------------------------------------------------
# Task B2
# ---------------------------------------------------------------------------

def channel_medoids(features, indices, k, *, method="ward",
                    metric="euclidean"):
    """Cluster one channel's events alone; return its family medoids.

    Returns `(medoid_features, labels, medoid_indices)`, all in the
    caller's index space, so a medoid can be drawn as the real event it is.
    """
    indices = np.asarray(indices, dtype=int)
    block = features[indices]
    if block.shape[0] <= k:
        return None, None, None
    Z = linkage(pdist(block, metric=metric), method=method)
    labels = fcluster(Z, k, criterion="maxclust")

    medoids = []
    for family in sorted(set(labels.tolist())):
        members = indices[labels == family]
        medoids.append(medoid_index(features, members))
    medoids = np.asarray(medoids, dtype=int)
    return features[medoids], labels, medoids


def transfer(features, channel, k, *, method="ward", metric="euclidean",
             n_permutations=N_TRANSFER_PERMUTATIONS, seed_base=SEED_BASE,
             channels=None):
    """The ordered-pair transfer matrix. Returns `(matrix, detail)`.

    For every ordered pair (A, B): cluster A alone, assign each B event to
    its nearest A-medoid, cluster B independently, and score the agreement
    between the two labellings of B with ARI and AMI.

    The null permutes B'S OWN labels, not the A-derived assignment,
    because the question is whether the A-derived grouping of B agrees
    with B's structure more than an arbitrary relabelling of that
    structure would.
    """
    features = np.asarray(features, dtype=float)
    channel = np.asarray(channel, dtype=int)
    channels = sorted(set(channel.tolist())) if channels is None \
        else list(channels)

    own = {}
    for c in channels:
        indices = np.flatnonzero(channel == c)
        medoid_features, labels, medoid_indices = channel_medoids(
            features, indices, k, method=method, metric=metric)
        own[c] = {"indices": indices, "medoids": medoid_features,
                  "labels": labels, "medoid_indices": medoid_indices}

    size = len(channels)
    matrix = np.full((size, size), np.nan)
    adjusted = np.full((size, size), np.nan)
    detail = {}

    for i, a in enumerate(channels):
        if own[a]["medoids"] is None:
            continue
        for j, b in enumerate(channels):
            if a == b or own[b]["labels"] is None:
                continue
            b_indices = own[b]["indices"]
            distances = cdist(features[b_indices], own[a]["medoids"],
                              metric=("euclidean" if metric == "euclidean"
                                      else "correlation"))
            assigned = np.argmin(distances, axis=1)
            b_own = own[b]["labels"]

            ari = float(adjusted_rand_score(b_own, assigned))
            ami = float(adjusted_mutual_info_score(b_own, assigned))

            # The seed formula, per (A, B) pair: the realisation slot
            # carries the SOURCE channel so no two pairs share a stream.
            rng = np.random.default_rng(seed_base + 100 * int(b) + int(a))
            draws = np.empty(n_permutations, dtype=float)
            shuffled = np.array(b_own, copy=True)
            for step in range(n_permutations):
                rng.shuffle(shuffled)
                draws[step] = adjusted_rand_score(shuffled, assigned)
            p = float((1 + int(np.sum(draws >= ari))) / (1 + n_permutations))

            matrix[i, j] = ari
            adjusted[i, j] = ari - float(np.median(draws))
            detail[f"{a}->{b}"] = {
                "source_channel": int(a), "target_channel": int(b),
                "n_target_events": int(b_indices.size),
                "ari": ari, "ami": ami,
                "null_median_ari": float(np.median(draws)),
                "null_q3_ari": float(np.percentile(draws, 75)),
                "ari_minus_null_median": float(ari - np.median(draws)),
                "p": p, "p_floor": float(1.0 / (1 + n_permutations)),
                "at_p_floor": bool(p <= 1.0 / (1 + n_permutations)),
                "seed": int(seed_base + 100 * int(b) + int(a)),
                "median_distance_to_nearest_A_medoid": float(
                    np.median(distances.min(axis=1))),
            }

    return matrix, adjusted, detail, own
