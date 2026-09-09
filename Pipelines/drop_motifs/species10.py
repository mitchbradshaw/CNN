"""
species10.py
=============
Task 5. Do shape families cross species, or do they only look like they do?

Every statistic here is paired with the null that bounds it, because round
one established what happens otherwise: the depth-angle correlation of
rho = -0.866 survived review for a whole run before a waveform-preserving
surrogate reproduced it at -0.860, and it turned out to be detector
geometry. Nothing in this module reports an effect without reporting what
the same measurement gives when the label it depends on is destroyed.

Seeding
-------
`base + 100 * group + index`, never `10 * channel + realisation`. Round
one's formula is not injective past index 9: 500 channel-realisations drew
from 140 distinct seeds and the effective N behind every pooled p was
below its nominal one. 100 is above any index used here.

The order the sub-tasks run in
------------------------------
5b BEFORE 5a. Whether family membership tracks species is not worth
reading until it is known whether it tracks SAMPLES PER EVENT, because
species is perfectly confounded with sampling rate between reishi and the
other two and a 200-point resample of 7 samples is 96% interpolation. If
samples-per-event associates more strongly than species does, the tree is
separating measurement resolution and every cross-species number in 5a is
unsafe.

No plotting library.
"""

import numpy as np
from scipy.stats import chi2_contingency
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, adjusted_rand_score,
                             balanced_accuracy_score, confusion_matrix)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils import resample

from Pipelines.drop_motifs import tree10

SEED_BASE = 20260903
N_PERMUTATIONS = 10000
N_DECODE_PERMUTATIONS = 1000
# A decoding null re-runs the WHOLE cross-validation per shuffle, so
# 1000 of them is 5000 model fits. That is affordable because every
# decode here is class-balanced down to the smallest species (76
# events, so 228 in total) - see `_balanced_indices`.
N_TRANSFER_PERMUTATIONS = 1000

# The samples-per-event control in 5b is the one decode NOT balanced down
# to 228 events - its classes are quantile bins of the whole subset, so
# pooled_all runs it on 3511 events and 200 features. 1000 permutations
# there is 5000 fits of a 4-class problem at that size, which measured out
# at tens of minutes per subset for a number that only has to answer "is
# it above chance". 200 shuffles resolve p to 1/201 = 0.005, which is
# ample for that question, and the count is reported on the figure.
N_CONTROL_PERMUTATIONS = 200

N_FOLDS = 5

# Solver budget for a permutation draw. The observed value always uses the
# full 2000; see `_cv_balanced_accuracy`.
NULL_MAX_ITER = 300


def seed_for(group, index):
    """`base + 100*group + index`. See the module docstring."""
    return int(SEED_BASE + 100 * int(group) + int(index))


# ---------------------------------------------------------------------------
# contingency and permutation - shared by 5a and 5b
# ---------------------------------------------------------------------------

def _codes(values):
    """`(codes, levels)` - integer codes and their sorted level names."""
    levels = sorted({str(v) for v in values})
    index = {v: i for i, v in enumerate(levels)}
    return np.asarray([index[str(v)] for v in values], dtype=np.intp), levels


def _table_from_codes(a, b, n_a, n_b):
    """Contingency table by bincount. The permutation loop's inner step.

    `np.bincount` over the flattened pair index, not a Python loop over
    events. The pooled store is 3511 events and the null is 10000
    shuffles; at 3511 Python-level increments per shuffle that is 35
    million operations for ONE test, and there are twelve. Vectorised it
    is a bincount per shuffle, which is milliseconds.
    """
    return np.bincount(a * n_b + b,
                       minlength=n_a * n_b).reshape(n_a, n_b).astype(float)


def _v_from_table(table):
    """Cramer's V without scipy's p-value machinery.

    chi-square is computed directly here because the permutation loop
    needs V ten thousand times and never needs the analytic p. The
    observed value is still reported through `cramers_v`, which does use
    `chi2_contingency`, so the two are checked against each other by
    construction on the observed table.
    """
    total = table.sum()
    if total <= 0:
        return float("nan")
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row @ col / total
    nonzero = expected > 0
    chi2 = float(((table[nonzero] - expected[nonzero]) ** 2
                  / expected[nonzero]).sum())
    k = min(table.shape) - 1
    if k <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / (total * k)))


def cramers_v(table):
    """Cramer's V for a contingency table, and the chi-square behind it.

    `correction=False`, and it is not optional. `chi2_contingency` applies
    Yates' continuity correction to 2x2 tables BY DEFAULT and to nothing
    else, so with the default the observed V for a two-species, two-family
    comparison would be computed under a different formula from every draw
    of its own permutation null - which computes chi-square directly. On a
    perfectly associated 2x2 table of 120 events that is V = 0.983 against
    a true 1.000, and it would make the observed value systematically
    smaller than the null it is being compared against for exactly the
    matched-rate two-species contrasts this run cares most about. Caught
    by `test_permutation_p_is_never_zero`.
    """
    table = np.asarray(table, dtype=float)
    if table.size == 0 or table.shape[0] < 2 or table.shape[1] < 2:
        return float("nan"), float("nan"), float("nan")
    if not table.sum():
        return float("nan"), float("nan"), float("nan")
    chi2, p, _, _ = chi2_contingency(table, correction=False)
    n = table.sum()
    k = min(table.shape) - 1
    return float(np.sqrt(chi2 / (n * k))), float(chi2), float(p)


def contingency(labels_a, labels_b):
    """`(table, levels_a, levels_b)` from two aligned label sequences."""
    a, levels_a = _codes(labels_a)
    b, levels_b = _codes(labels_b)
    return _table_from_codes(a, b, len(levels_a), len(levels_b)), levels_a, levels_b


def standardised_residuals(table):
    """(observed - expected) / sqrt(expected), the per-cell enrichment.

    |z| > 2 is the conventional flag. Reported per cell rather than
    summarised, because "which family is enriched for which species" is
    the actual question and a single V cannot answer it.
    """
    table = np.asarray(table, dtype=float)
    total = table.sum()
    if total <= 0:
        return np.zeros_like(table)
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (table - expected) / np.sqrt(expected)
    return np.nan_to_num(z)


def permutation_v(families, labels, *, n=N_PERMUTATIONS, group=0):
    """V against a null that shuffles `labels` and keeps `families` fixed.

    Shuffling the LABEL and not the family is deliberate: it destroys the
    association while preserving both marginals exactly, so the null
    answers "how much V does a tree of this shape produce against labels
    of these proportions by chance", which is the question.
    """
    fam_codes, levels_f = _codes([str(f) for f in families])
    lab_codes, levels_l = _codes([str(v) for v in labels])
    n_f, n_l = len(levels_f), len(levels_l)

    table = _table_from_codes(fam_codes, lab_codes, n_f, n_l)
    observed, chi2, chi2_p = cramers_v(table)

    rng = np.random.default_rng(seed_for(group, 0))
    null = np.empty(int(n), dtype=float)
    shuffled = lab_codes.copy()
    for i in range(int(n)):
        rng.shuffle(shuffled)
        null[i] = _v_from_table(
            _table_from_codes(fam_codes, shuffled, n_f, n_l))

    # (1 + #{null >= observed}) / (1 + n) - never zero, because a p of
    # zero claims more resolution than the number of shuffles bought.
    p = float((1 + int(np.sum(null >= observed))) / (1 + int(n)))
    residuals = standardised_residuals(table)
    return {
        "cramers_v": observed,
        "chi2": chi2,
        "chi2_p": chi2_p,
        "null_median_v": float(np.median(null)),
        "null_p95_v": float(np.percentile(null, 95)),
        "permutation_p": p,
        "n_permutations": int(n),
        "n": int(table.sum()),
        "table": table.astype(int).tolist(),
        "families": levels_f,
        "levels": levels_l,
        "residuals": residuals.tolist(),
        "enriched": [
            {"family": levels_f[i], "level": levels_l[j],
             "z": float(residuals[i, j]), "observed": int(table[i, j])}
            for i in range(n_f) for j in range(n_l)
            if abs(residuals[i, j]) > 2.0
        ],
    }


# ---------------------------------------------------------------------------
# 5b - the confound control
# ---------------------------------------------------------------------------

def sample_bins(values, n_bins=4):
    """Quantile bins of `n_samples_in_fall`, labelled by their range.

    Quantile rather than fixed-width: the corpora differ by two orders of
    magnitude in samples per event, and fixed-width bins would put every
    reishi event in one bin and every oyster event in another, which would
    make the test a test of the binning.
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return []
    edges = np.unique(np.quantile(values, np.linspace(0, 1, int(n_bins) + 1)))
    if edges.size < 2:
        return [f"{int(values[0])}"] * values.size
    index = np.clip(np.digitize(values, edges[1:-1], right=False),
                    0, len(edges) - 2)
    labels = [f"{edges[i]:.0f}-{edges[i + 1]:.0f}" for i in range(len(edges) - 1)]
    return [labels[i] for i in index]


def resolution_vs_species(rows, labels, *, n=N_PERMUTATIONS, n_bins=4,
                          group=1):
    """Family x species against family x samples-per-event, side by side.

    The comparison the cross-species reading is conditional on. If
    samples-per-event associates more strongly, the tree is separating
    measurement resolution.
    """
    species = [r["species"] for r in rows]
    bins = sample_bins([r["n_samples_in_fall"] for r in rows], n_bins=n_bins)
    return {
        "species": permutation_v(labels, species, n=n, group=group),
        "samples_per_event": permutation_v(labels, bins, n=n, group=group + 1),
        "n_bins": int(n_bins),
        "bin_labels": sorted(set(bins)),
    }


def decode_samples_from_shape(features, rows, *, n_bins=4, folds=N_FOLDS,
                              group=2, n_permutations=N_CONTROL_PERMUTATIONS):
    """Can a 200-point z-normalised vector say how many samples built it?

    If it can, the representation carries measurement resolution and not
    only shape, and a family that separates species may be separating the
    rate they were recorded at. This is the direct test of that, and it is
    the one number in 5b that does not depend on the tree at all.
    """
    y = np.asarray(sample_bins([r["n_samples_in_fall"] for r in rows],
                               n_bins=n_bins))
    return decode(features, y, folds=folds, group=group,
                  n_permutations=n_permutations)


# ---------------------------------------------------------------------------
# 5c - decoding, and the null that bounds it
# ---------------------------------------------------------------------------

def absolute_scale_features(rows):
    """Depth, fall duration in seconds, tangent slope. The scale axis."""
    return np.column_stack([
        [abs(float(r["drop_depth_mv"])) for r in rows],
        [float(r["fall_duration_s"]) for r in rows],
        [abs(float(r.get("max_slope_raw", 0.0))) for r in rows],
    ])


def resolution_features(rows):
    """`n_samples_in_fall` alone - the control representation.

    If this decodes species well then so will anything correlated with it,
    which includes any representation that has not had resolution removed.
    """
    return np.asarray([[int(r["n_samples_in_fall"])] for r in rows],
                      dtype=float)


def representations(features, rows):
    """The four representations Task 5c compares, in reporting order."""
    scale = absolute_scale_features(rows)
    return {
        "absolute scale": scale,
        "normalised shape": np.asarray(features, dtype=float),
        "both": np.column_stack([scale, np.asarray(features, dtype=float)]),
        "resolution alone": resolution_features(rows),
    }


def _balanced_indices(y, rng):
    """Indices giving every class the size of the smallest class.

    Class-balanced by SUBSAMPLING rather than by class weights, so the
    permutation null and the observation are computed on identically
    shaped problems. With weights, chance depends on the weighting and the
    drawn chance line would not be 1/n_classes.
    """
    classes, counts = np.unique(y, return_counts=True)
    smallest = int(counts.min())
    picks = []
    for label in classes:
        members = np.flatnonzero(y == label)
        picks.append(resample(members, replace=False, n_samples=smallest,
                              random_state=int(rng.integers(0, 2 ** 31 - 1))))
    return np.concatenate(picks)


def _cv_balanced_accuracy(X, y, folds, seed, max_iter=2000):
    """Stratified k-fold balanced accuracy, plus the pooled confusion.

    `max_iter` is lowered for the permutation loop only. The OBSERVED
    value is always computed at the full budget; a null fitted at a
    smaller budget can only be pessimistic about the null, which would
    make the p optimistic, so the two are checked against each other in
    `decode` by recomputing one null draw at the full budget.
    """
    skf = StratifiedKFold(n_splits=int(folds), shuffle=True,
                          random_state=int(seed))
    truth, predicted = [], []
    for train, test in skf.split(X, y):
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=int(max_iter),
                               class_weight="balanced"))
        model.fit(X[train], y[train])
        truth.extend(y[test])
        predicted.extend(model.predict(X[test]))
    return (float(balanced_accuracy_score(truth, predicted)),
            float(accuracy_score(truth, predicted)),
            np.asarray(truth), np.asarray(predicted))


def decode(X, y, *, folds=N_FOLDS, group=3,
           n_permutations=N_DECODE_PERMUTATIONS):
    """Balanced accuracy with a label-permutation null.

    The null shuffles y and re-runs the WHOLE cross-validation, so it
    absorbs any optimism the fold structure or the balancing introduces
    rather than being compared against an analytic chance level that the
    procedure may not actually obey. Chance is still drawn, as
    1 / n_classes, so the two can be seen to agree or not.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    classes = np.unique(y)
    if classes.size < 2 or X.shape[0] < folds * classes.size:
        return {"error": f"too few samples: n={X.shape[0]}, "
                         f"{classes.size} classes"}

    rng = np.random.default_rng(seed_for(group, 0))
    keep = _balanced_indices(y, rng)
    Xb, yb = X[keep], y[keep]

    observed, plain, truth, predicted = _cv_balanced_accuracy(
        Xb, yb, folds, seed_for(group, 1))

    null = np.empty(int(n_permutations), dtype=float)
    shuffled = yb.copy()
    check = None
    for i in range(int(n_permutations)):
        rng.shuffle(shuffled)
        null[i], _, _, _ = _cv_balanced_accuracy(
            Xb, shuffled, folds, seed_for(group, 2 + i % 97),
            max_iter=NULL_MAX_ITER)
        if i == 0:
            check, _, _, _ = _cv_balanced_accuracy(
                Xb, shuffled, folds, seed_for(group, 2), max_iter=2000)

    p = float((1 + int(np.sum(null >= observed))) / (1 + int(n_permutations)))
    matrix = confusion_matrix(truth, predicted, labels=list(classes))
    return {
        "balanced_accuracy": observed,
        "accuracy": plain,
        "chance": float(1.0 / classes.size),
        "null_median": float(np.median(null)),
        "null_p95": float(np.percentile(null, 95)),
        "permutation_p": p,
        "n_permutations": int(n_permutations),
        "n": int(Xb.shape[0]),
        "n_per_class": int(Xb.shape[0] // classes.size),
        "classes": [str(c) for c in classes],
        "confusion": matrix.tolist(),
        "n_features": int(Xb.shape[1]),
        # One null draw recomputed at the full solver budget, so the
        # cheaper budget used for the other draws is checked rather than
        # assumed harmless.
        "null_draw0_cheap": float(null[0]),
        "null_draw0_full_budget": (float(check) if check is not None
                                   else None),
    }


def decode_species(features, rows, *, folds=N_FOLDS, group=3,
                   n_permutations=N_DECODE_PERMUTATIONS):
    """5c: every representation against the same species labels."""
    y = np.asarray([r["species"] for r in rows])
    out = {}
    for offset, (name, X) in enumerate(representations(features, rows).items()):
        out[name] = decode(X, y, folds=folds, group=group + offset,
                           n_permutations=n_permutations)
    return out


# ---------------------------------------------------------------------------
# 5d - leave-one-species-out family transfer
# ---------------------------------------------------------------------------

def _own_clustering(features, k):
    from scipy.cluster.hierarchy import fcluster
    Z, _ = tree10.cluster.build_linkage(features)
    k = max(2, min(int(k), len(features) - 1))
    return np.asarray(fcluster(Z, k, criterion="maxclust"))


def transfer(features_a, features_b, *, k=tree10.COARSE_K,
             n=N_TRANSFER_PERMUTATIONS, group=8):
    """Do A's shapes describe B's events?

    Cluster A alone, take its medoids, assign every B event to its nearest
    A-medoid, and score that assignment against B's OWN independent
    clustering with the adjusted Rand index. ARI is chance-corrected, so
    zero is "no better than a random partition of the same shape" and the
    permutation null is a check on that rather than the whole test.

    The secondary check has no partition dependence at all: the median
    distance from a B event to its nearest A-medoid. A partition can score
    badly because B genuinely has more families than A while every B event
    still sits close to some A shape, and that distinction matters.
    """
    features_a = np.asarray(features_a, dtype=float)
    features_b = np.asarray(features_b, dtype=float)
    if len(features_a) < k + 1 or len(features_b) < k + 1:
        return {"error": f"too few events: A={len(features_a)}, "
                         f"B={len(features_b)}"}

    labels_a = _own_clustering(features_a, k)
    medoid_index = tree10.medoids(features_a, labels_a)
    medoids = np.vstack([features_a[i] for i in
                         sorted(medoid_index, key=lambda key: key)])

    d = np.linalg.norm(features_b[:, None, :] - medoids[None, :, :], axis=2)
    assigned = np.argmin(d, axis=1)
    nearest = d.min(axis=1)

    labels_b = _own_clustering(features_b, k)
    observed = float(adjusted_rand_score(labels_b, assigned))

    rng = np.random.default_rng(seed_for(group, 0))
    null = np.empty(int(n), dtype=float)
    shuffled = labels_b.copy()
    for i in range(int(n)):
        rng.shuffle(shuffled)
        null[i] = adjusted_rand_score(shuffled, assigned)
    p = float((1 + int(np.sum(null >= observed))) / (1 + int(n)))

    return {
        "ari": observed,
        "null_median_ari": float(np.median(null)),
        "permutation_p": p,
        "n_permutations": int(n),
        "n_a": int(len(features_a)),
        "n_b": int(len(features_b)),
        "k": int(k),
        "median_nearest_distance": float(np.median(nearest)),
        "mean_nearest_distance": float(np.mean(nearest)),
        "n_medoids": int(len(medoids)),
    }


def phase_randomised(waveform, rng):
    """An FFT surrogate of one waveform: same spectrum, random phases.

    The reference for "how close would a B event be to an A-medoid if its
    shape carried no information beyond its power spectrum". Amplitudes
    are preserved exactly, so the surrogate has the same roughness and the
    same dominant scale as the event it replaces.
    """
    x = np.asarray(waveform, dtype=float)
    if x.size < 4:
        return x.copy()
    spectrum = np.fft.rfft(x)
    phases = rng.uniform(0, 2 * np.pi, spectrum.size)
    phases[0] = 0.0
    if x.size % 2 == 0:
        phases[-1] = 0.0
    return np.fft.irfft(np.abs(spectrum) * np.exp(1j * phases), n=x.size)


def transfer_against_surrogate(features_a, waveforms_b, *,
                               k=tree10.COARSE_K, group=9, n_surrogates=100):
    """Median nearest-medoid distance, real B against phase-randomised B.

    The partition-free half of 5d. A real B event should sit closer to
    some A shape than a surrogate with B's own spectrum does, or "A's
    shapes describe B" is a statement about power spectra.
    """
    features_a = np.asarray(features_a, dtype=float)
    if len(features_a) < k + 1 or len(waveforms_b) < 2:
        return {"error": "too few events"}

    labels_a = _own_clustering(features_a, k)
    medoid_index = tree10.medoids(features_a, labels_a)
    medoids = np.vstack([features_a[i] for i in sorted(medoid_index)])

    real = tree10.cluster.feature_matrix(list(waveforms_b))
    observed = float(np.median(
        np.linalg.norm(real[:, None, :] - medoids[None, :, :],
                       axis=2).min(axis=1)))

    rng = np.random.default_rng(seed_for(group, 0))
    null = []
    for i in range(int(n_surrogates)):
        draws = []
        for wave in waveforms_b:
            surrogate = phase_randomised(wave, rng)
            if float(np.ptp(surrogate)) == 0.0:
                surrogate = np.asarray(wave, dtype=float)
            draws.append(surrogate)
        block = tree10.cluster.feature_matrix(draws)
        null.append(float(np.median(
            np.linalg.norm(block[:, None, :] - medoids[None, :, :],
                           axis=2).min(axis=1))))
    null = np.asarray(null)
    # Lower is better here, so the tail is the LEFT one.
    p = float((1 + int(np.sum(null <= observed))) / (1 + len(null)))
    return {
        "median_nearest_distance": observed,
        "surrogate_median": float(np.median(null)),
        "p_closer_than_surrogate": p,
        "n_surrogates": int(n_surrogates),
        "n_b": int(len(waveforms_b)),
    }


def species_matrix(by_species, *, k=tree10.COARSE_K,
                   n=N_TRANSFER_PERMUTATIONS):
    """The ordered-pair ARI matrix. `by_species` is `{species: features}`."""
    names = sorted(by_species)
    out = {}
    for i, a in enumerate(names):
        out[a] = {}
        for j, b in enumerate(names):
            if a == b:
                out[a][b] = {"ari": 1.0, "self": True}
                continue
            out[a][b] = transfer(by_species[a], by_species[b], k=k, n=n,
                                 group=10 + i * len(names) + j)
    return {"species": names, "matrix": out}
