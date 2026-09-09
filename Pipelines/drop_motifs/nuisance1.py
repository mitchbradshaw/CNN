"""
nuisance1.py
=============
Task 2. Two measurements that point opposite ways, and drawing them side
by side is the whole argument:

    ABSOLUTE AMPLITUDE IS A PROPERTY OF THE ELECTRODE.
    RELATIVE SHAPE IS NOT.

Measurement 1 is a Kruskal-Wallis over per-channel drop depth, reported
WITH AN EFFECT SIZE. At n = 1058 every test is significant and a p-value
carries no information; epsilon-squared says how much of the rank variance
the channel label actually explains, and that is the number the sentence
rests on.

Measurement 2 is a permutation test on the family x channel contingency
table. The null is NOT uniform. Channels contribute unequally to the store
- CH2 has 93 events, CH1 has 346 - so a family can look channel-mixed
purely because CH1 is everywhere. Shuffling the channel LABELS across
events preserves both margins by construction, which is exactly the null
that "shape is independent of electrode" needs, and standardised residuals
against the marginal-proportion expectation say which family, if any, is
enriched for which channel and by how much.

WHY CRAMER'S V AND NOT ONLY CHI-SQUARED. chi-squared scales with n, so its
value cannot be compared against anything or quoted in a sentence. V is
chi-squared normalised to [0, 1] by n and the table's smaller dimension,
so "V = 0.08" is a statement about association strength that survives
being read on its own. Both are reported; the permutation p is identical
for the two because V is a monotone function of chi-squared at fixed n and
fixed table shape.

Panel C is the argument compressed into one scatter: per-channel median
depth on x against per-channel median normalised-shape distance to the
GLOBAL medoid on y. If amplitude separates the electrodes and shape does
not, the five points spread horizontally and not vertically. The y axis
is measured in the same z-normalised 200-point feature space every family
statistic uses, so it is the same notion of "shape" throughout.
"""

import numpy as np
from scipy.stats import chi2_contingency, kruskal

from Pipelines.drop_motifs import nulls1 as n1

N_PERMUTATIONS = 10_000
PERMUTATION_SEED = 20260902

# |z| above this is annotated on panel B. 2 is the conventional reading of
# "this cell is further from its expectation than sampling noise explains";
# it is a display threshold, and every residual is in the JSON regardless.
RESIDUAL_FLAG = 2.0


def epsilon_squared(h_statistic, n, k):
    """Kruskal-Wallis effect size: the fraction of rank variance the group
    label explains.

    `(H - k + 1) / (n - k)`. Bounded to [0, 1] because the correction can
    go slightly negative when H is below its expectation under the null,
    and a negative "fraction of variance" is not a number to print.
    Conventional reading: 0.01 small, 0.06 moderate, 0.14 large.
    """
    if n <= k:
        return None
    return float(np.clip((float(h_statistic) - k + 1) / (n - k), 0.0, 1.0))


def depth_by_channel(rows):
    """`{channel: array of |drop_depth_mv|}`, channels in order."""
    out = {}
    for row in rows:
        out.setdefault(int(row["channel"]), []).append(
            abs(float(row["drop_depth_mv"])))
    return {c: np.asarray(v, dtype=float) for c, v in sorted(out.items())}


def depth_test(rows):
    """Kruskal-Wallis across channels, with the effect size that makes the
    p readable."""
    groups = depth_by_channel(rows)
    arrays = [v for v in groups.values() if v.size]
    if len(arrays) < 2:
        return None
    result = kruskal(*arrays)
    n = int(sum(a.size for a in arrays))
    return {
        "test": "Kruskal-Wallis H, |drop_depth_mv| by channel",
        "H": float(result.statistic),
        "p": float(result.pvalue),
        "n": n,
        "k_groups": len(arrays),
        "epsilon_squared": epsilon_squared(result.statistic, n, len(arrays)),
        "per_channel": {
            "CH%d" % c: {"n": int(v.size),
                         "median_mv": float(np.median(v)),
                         "q1_mv": float(np.percentile(v, 25)),
                         "q3_mv": float(np.percentile(v, 75)),
                         "min_mv": float(v.min()), "max_mv": float(v.max())}
            for c, v in groups.items()},
        "median_ratio_max_over_min": float(
            max(np.median(v) for v in groups.values())
            / min(np.median(v) for v in groups.values())),
    }


# ---------------------------------------------------------------------------
# family x channel
# ---------------------------------------------------------------------------

def contingency(labels, channels, n_channels=5):
    """`(table, family_ids)` with families as rows and channels as
    columns."""
    labels = np.asarray(labels)
    channels = np.asarray(channels, dtype=int)
    families = sorted(set(labels.tolist()))
    table = np.zeros((len(families), n_channels), dtype=float)
    for i, family in enumerate(families):
        mask = labels == family
        for channel in range(n_channels):
            table[i, channel] = int((channels[mask] == channel).sum())
    return table, families


def cramers_v(chi2, table):
    n = float(table.sum())
    if n <= 0:
        return None
    smaller = min(table.shape) - 1
    if smaller <= 0:
        return None
    return float(np.sqrt(chi2 / (n * smaller)))


def standardised_residuals(table):
    """Adjusted standardised (Haberman) residuals, which are the ones that
    are approximately standard normal and therefore the ones |z| > 2 means
    something about.

    Pearson residuals `(O - E)/sqrt(E)` are NOT standard normal - their
    variance is `(1 - row_prop)(1 - col_prop)` - so a Pearson residual of
    2.0 is not a two-sigma cell. Dividing by that variance is the
    correction, and it is why an enrichment claim in the report is made
    from these and not from the raw difference.
    """
    table = np.asarray(table, dtype=float)
    n = table.sum()
    if n <= 0:
        return np.zeros_like(table)
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row @ col / n
    with np.errstate(divide="ignore", invalid="ignore"):
        variance = expected * (1 - row / n) * (1 - col / n)
        residual = np.where(variance > 0,
                            (table - expected) / np.sqrt(variance), 0.0)
    return residual


def permutation_test(labels, channels, *, n_permutations=N_PERMUTATIONS,
                     seed=PERMUTATION_SEED, n_channels=5):
    """Shuffle the CHANNEL LABELS across events and rebuild the table.

    Both margins are preserved exactly - the family sizes because the
    labels array is untouched, the channel totals because a permutation of
    the channel vector is a rearrangement of the same multiset. The only
    thing destroyed is the pairing, which is precisely the hypothesis. A
    uniform-expectation chi-squared would instead be testing "are the
    channels equally represented", which is false for a reason that has
    nothing to do with shape.
    """
    labels = np.asarray(labels)
    channels = np.asarray(channels, dtype=int)
    table, families = contingency(labels, channels, n_channels)
    chi2, chi2_p, dof, expected = chi2_contingency(
        table[:, table.sum(axis=0) > 0])
    observed_v = cramers_v(chi2, table)

    rng = np.random.default_rng(int(seed))
    null_chi2 = np.empty(int(n_permutations), dtype=float)
    shuffled = channels.copy()
    for i in range(int(n_permutations)):
        rng.shuffle(shuffled)
        permuted, _ = contingency(labels, shuffled, n_channels)
        used = permuted[:, permuted.sum(axis=0) > 0]
        null_chi2[i] = chi2_contingency(used)[0] if used.shape[1] > 1 else 0.0

    n_ge = int((null_chi2 >= chi2).sum())
    return {
        "families": [int(f) for f in families],
        "table": table.astype(int).tolist(),
        "expected_under_marginals": expected.tolist(),
        "standardised_residuals": standardised_residuals(table).tolist(),
        "chi2": float(chi2),
        "chi2_dof": int(dof),
        "chi2_asymptotic_p": float(chi2_p),
        "cramers_v": observed_v,
        "n_permutations": int(n_permutations),
        "permutation_seed": int(seed),
        "permutation_p": float((1 + n_ge) / (1 + int(n_permutations))),
        "null_chi2_median": float(np.median(null_chi2)),
        "null_chi2_q95": float(np.percentile(null_chi2, 95)),
        "null_cramers_v_median": cramers_v(float(np.median(null_chi2)), table),
        "channel_marginal_proportion": (
            table.sum(axis=0) / table.sum()).tolist(),
        "n_families_with_all_five_channels": int(
            (table > 0).all(axis=1).sum()),
        "n_families": int(table.shape[0]),
        "flagged_cells": [
            {"family": int(families[i]), "channel": "CH%d" % j,
             "observed": int(table[i, j]),
             "expected": float(expected[i, j]) if j < expected.shape[1] else None,
             "z": float(z)}
            for (i, j), z in np.ndenumerate(standardised_residuals(table))
            if abs(z) > RESIDUAL_FLAG],
    }


# ---------------------------------------------------------------------------
# panel C - shape distance to the global medoid
# ---------------------------------------------------------------------------

def shape_distance_to_global_medoid(features):
    """Distance from each event to the ONE medoid of the whole store, in
    the z-normalised feature space.

    The medoid rather than the centroid: a centroid of z-normalised
    vectors is not itself a plausible waveform (averaging cancels the
    features that distinguish shapes), whereas the medoid is an actual
    event. Computed by minimising the summed distance to every other
    event, which is O(n^2) in memory at n ~ 1000 - fine here, and the
    reason this is not offered for the surrogate grid.
    """
    features = np.asarray(features, dtype=float)
    from scipy.spatial.distance import pdist, squareform
    distances = squareform(pdist(features, metric="euclidean"))
    medoid = int(np.argmin(distances.sum(axis=1)))
    return distances[medoid], medoid


def per_channel_shape_spread(features, rows):
    """`{channel: {median_shape_distance, median_depth}}` - panel C's five
    points."""
    distances, medoid = shape_distance_to_global_medoid(features)
    channels = np.asarray([int(r["channel"]) for r in rows], dtype=int)
    depths = np.asarray([abs(float(r["drop_depth_mv"])) for r in rows],
                        dtype=float)
    out = {}
    for channel in sorted(set(channels.tolist())):
        mask = channels == channel
        out["CH%d" % channel] = {
            "n": int(mask.sum()),
            "median_depth_mv": float(np.median(depths[mask])),
            "median_shape_distance": float(np.median(distances[mask])),
            "iqr_depth_mv": float(np.subtract(
                *np.percentile(depths[mask], [75, 25]))),
            "iqr_shape_distance": float(np.subtract(
                *np.percentile(distances[mask], [75, 25]))),
        }
    spread = {
        "medoid_event_id": rows[medoid]["event_id"],
        "medoid_channel": int(rows[medoid]["channel"]),
        "per_channel": out,
    }
    depth_values = [v["median_depth_mv"] for v in out.values()]
    shape_values = [v["median_shape_distance"] for v in out.values()]
    # The one number panel C exists to produce: how far apart the five
    # electrodes sit on each axis, each expressed as a fraction of that
    # axis's own median, so the two are comparable despite different units.
    spread["depth_spread_ratio"] = float(
        (max(depth_values) - min(depth_values)) / np.median(depth_values))
    spread["shape_spread_ratio"] = float(
        (max(shape_values) - min(shape_values)) / np.median(shape_values))
    spread["separation_ratio_depth_over_shape"] = float(
        spread["depth_spread_ratio"] / spread["shape_spread_ratio"])
    return spread


def raw_store_depths(store=n1.RAW_STORE):
    """Pre-floor per-channel depths, for the faint distributions drawn
    behind panel A. The truncation the 0.1 mV floor applies is the single
    most important caveat on measurement 1 and it is drawn rather than
    described."""
    from Working.Detection.drop_motifs import motifs5
    rows = motifs5.load_events(str(store))
    return depth_by_channel(rows), len(rows)
