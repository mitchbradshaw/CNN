"""
clusterk1.py
=============
Tasks 4 and 5. Two small, self-contained analyses over the refined store.

TASK 4 - A STATED RULE FOR THE NUMBER OF FAMILIES
--------------------------------------------------
k = 4 is currently a cut, not a decision. No cluster-derived number should
be quoted without a criterion, so the criterion is written down here, in
code, ABOVE the code that evaluates it, and the answer is read off
afterwards:

    SELECTION_RULE - maximise mean silhouette over k in 2..12; break ties
    toward the smaller k.

Silhouette rather than the gap statistic as the primary because the gap
statistic's uniform reference is a poor null for 200-dimensional
z-normalised vectors: a uniform box in that space is nothing like the thin
shell the normalisation constrains the data to, so the gap is measuring
"is this data on a sphere" as much as "how many clusters". It is computed
and reported anyway, because it is the conventional companion number and
its disagreement with silhouette is informative.

Cophenetic correlation is a property of the LINKAGE, not of k. It is
reported once, and the figure says so rather than plotting it against k as
though it varied.

The known tension from earlier work, carried here so the result is read
against it rather than in isolation: Ward over PCA gave silhouette 0.238
at k = 5 with cophenetic r 0.52, while average linkage gave cophenetic
r 0.91 but suggested k = 2. IF THE CRITERION SELECTS k = 2, k = 2 IS
REPORTED. A smaller repertoire is better for the argument, not worse.

TASK 5 - SEQUENCE STRUCTURE
----------------------------
Everything needed is already a column: `onset_idx`, `fs`, `channel`,
`drop_depth_mv`, `fall_duration_s`, `cluster_id`. Four statistics, and the
one that carries the weight is the last:

    CV of the ISI distribution, per channel. CV = 1 is Poisson; below 1 is
    more regular than Poisson, above 1 is bursting. It is the standard
    regularity statistic and it separates the draft's "shark-fin train"
    from its "icicle train" with one number each.

The archetype check is deliberately conservative. Twenty minutes at 10 Hz
is a short recording, and `archetype_verdict` is written to return "not
visible" unless a stated numeric condition is met, so that absence is
reported as absence rather than as a hedge.
"""

import numpy as np
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import pdist
from scipy.stats import linregress

from Pipelines.drop_motifs import nulls1 as n1

K_RANGE = tuple(range(2, 13))

SELECTION_RULE = ("maximise mean silhouette over k in 2..12; "
                  "break ties toward the smaller k")

GAP_REFERENCES = 20
GAP_SEED = 20260902

# Silhouette over 1058 points is a 1058x1058 distance matrix - fine. Over
# a larger store it would not be, so the subsample size is a constant
# rather than an assumption.
SILHOUETTE_MAX_N = 5000


def silhouette_and_gap(features, k_range=K_RANGE, *,
                       n_references=GAP_REFERENCES, seed=GAP_SEED):
    """Mean silhouette and the gap statistic for each k, plus the
    linkage's cophenetic r once.

    The gap reference is uniform over each feature DIMENSION's observed
    range, which is the standard construction (Tibshirani, Walther &
    Hastie 2001). Its weakness on z-normalised data is in the module
    docstring; it is reported with its standard error so the conventional
    "smallest k whose gap is within one SE of the next" rule can also be
    read off.
    """
    from sklearn.metrics import silhouette_score

    features = np.asarray(features, dtype=float)
    condensed = pdist(features, metric="euclidean")
    Z = linkage(condensed, method="ward")
    coph, _ = cophenet(Z, condensed)

    lo = features.min(axis=0)
    hi = features.max(axis=0)
    rng = np.random.default_rng(int(seed))
    references = [rng.uniform(lo, hi, size=features.shape)
                  for _ in range(int(n_references))]
    reference_linkages = [linkage(pdist(r, metric="euclidean"), method="ward")
                          for r in references]

    def dispersion(data, labels):
        """log of the pooled within-cluster sum of squared distances to
        the cluster centroid - the W_k the gap statistic compares."""
        total = 0.0
        for label in set(labels.tolist()):
            members = data[labels == label]
            if len(members) < 2:
                continue
            total += float(((members - members.mean(axis=0)) ** 2).sum())
        return np.log(total) if total > 0 else 0.0

    rows = []
    for k in k_range:
        labels = fcluster(Z, int(k), criterion="maxclust")
        if len(set(labels.tolist())) < 2:
            continue
        score = float(silhouette_score(features, labels, metric="euclidean"))
        observed = dispersion(features, labels)
        reference_values = np.array([
            dispersion(data, fcluster(rZ, int(k), criterion="maxclust"))
            for data, rZ in zip(references, reference_linkages)])
        gap = float(reference_values.mean() - observed)
        sk = float(reference_values.std() * np.sqrt(1.0 + 1.0 / n_references))
        sizes = np.bincount(labels)[1:]
        rows.append({"k": int(k), "silhouette": score, "gap": gap,
                     "gap_se": sk,
                     "log_within_dispersion": float(observed),
                     "reference_log_dispersion_mean":
                         float(reference_values.mean()),
                     "family_sizes": sizes.tolist(),
                     "smallest_family": int(sizes.min()),
                     "largest_family": int(sizes.max())})
    return rows, float(coph), Z


def apply_selection_rule(rows):
    """`SELECTION_RULE`, applied. Written after the rule and evaluated
    from it, so the criterion cannot be retrofitted to the answer."""
    if not rows:
        return None
    best = max(row["silhouette"] for row in rows)
    ties = [row for row in rows if row["silhouette"] == best]
    chosen = min(ties, key=lambda row: row["k"])

    # The conventional gap rule, reported alongside rather than instead:
    # the smallest k whose gap is at least the next k's gap minus that
    # next k's standard error.
    gap_k = None
    for index, row in enumerate(rows[:-1]):
        nxt = rows[index + 1]
        if row["gap"] >= nxt["gap"] - nxt["gap_se"]:
            gap_k = row["k"]
            break

    return {"rule": SELECTION_RULE,
            "selected_k": int(chosen["k"]),
            "selected_silhouette": float(chosen["silhouette"]),
            "n_ties": len(ties),
            "gap_rule": ("smallest k with gap(k) >= gap(k+1) - se(k+1) "
                         "(Tibshirani et al. 2001)"),
            "gap_selected_k": gap_k,
            "shipped_k": n1.COARSE_K,
            "agrees_with_shipped": int(chosen["k"]) == n1.COARSE_K}


# ---------------------------------------------------------------------------
# Task 5 - sequence
# ---------------------------------------------------------------------------

# CV within this of 1.0 is called Poisson rather than regular or bursting.
# A band rather than a point because CV is estimated from at most a few
# hundred intervals and its own sampling error is roughly 1/sqrt(2n).
POISSON_BAND = 0.15

# A monotone drift in ISI or depth across the recording is only called
# visible if a linear fit against event index clears BOTH of these. Two
# conditions because at n ~ 300 a slope can be significant while
# explaining nothing.
DRIFT_MIN_R2 = 0.05
DRIFT_MAX_P = 0.01

ARCHETYPES = ("shark-fin train", "icicle train", "stegosaurus (rising ISI)",
              "isolated spikes")


def isi_by_channel(rows):
    """`{channel: {onsets_s, isi_s, depths_mv, durations_s}}`.

    ISI is successive `onset_idx` differences WITHIN a channel, converted
    to seconds. Sorted first: the store is written channel-major and
    onset-ascending, but a sort costs nothing and an unsorted input would
    produce negative intervals rather than an error.
    """
    grouped = {}
    for row in rows:
        grouped.setdefault(int(row["channel"]), []).append(row)
    out = {}
    for channel, members in sorted(grouped.items()):
        members.sort(key=lambda r: int(r["onset_idx"]))
        fs = float(members[0]["fs"])
        onsets = np.asarray([int(r["onset_idx"]) for r in members],
                            dtype=float) / fs
        out[channel] = {
            "onsets_s": onsets,
            "isi_s": np.diff(onsets),
            "depths_mv": np.asarray([abs(float(r["drop_depth_mv"]))
                                     for r in members], dtype=float),
            "durations_s": np.asarray([float(r["fall_duration_s"])
                                       for r in members], dtype=float),
        }
    return out


# A monotone trend must also show up in the RANKS. Added after the first
# run called CH2 a "stegosaurus": its r2 of 0.27 came almost entirely from
# one 40 s gap in the middle of the recording, and a least-squares fit
# cannot tell one excursion from a trend. Spearman rho can - it is
# unmoved by how large the excursion is, only by whether the ordering
# rises - so "visible" now needs both, and the two numbers are reported
# side by side so a disagreement between them is legible rather than
# averaged away.
DRIFT_MIN_ABS_RHO = 0.20


def _drift(values):
    """Least-squares fit AND Spearman rho of `values` against event index.

    Three conditions for `visible`, and the third is the one that matters:
    a linear fit driven by a single gap or a single burst will have a
    respectable r2 and a tiny p while its rank correlation stays near
    zero. `rho_agrees` records whether the two tell the same story.
    """
    from scipy.stats import spearmanr

    values = np.asarray(values, dtype=float)
    if values.size < 8:
        return {"slope": None, "r2": None, "p": None, "spearman_rho": None,
                "rho_agrees": None, "visible": False}
    index = np.arange(values.size, dtype=float)
    fit = linregress(index, values)
    rho = spearmanr(index, values)
    r2 = float(fit.rvalue ** 2)
    p = float(fit.pvalue)
    strong_fit = bool(r2 >= DRIFT_MIN_R2 and p <= DRIFT_MAX_P)
    strong_rank = bool(abs(rho.statistic) >= DRIFT_MIN_ABS_RHO
                       and rho.pvalue <= DRIFT_MAX_P)
    return {"slope": float(fit.slope), "r2": r2, "p": p,
            "spearman_rho": float(rho.statistic),
            "spearman_p": float(rho.pvalue),
            "rho_agrees": bool(strong_fit == strong_rank),
            "least_squares_only": bool(strong_fit and not strong_rank),
            "visible": bool(strong_fit and strong_rank
                            and np.sign(fit.slope) == np.sign(rho.statistic))}


def sequence_stats(rows):
    """Per-channel ISI, CV, and the two drift fits panels B and C draw."""
    grouped = isi_by_channel(rows)
    per_channel = {}
    for channel, data in grouped.items():
        isi = data["isi_s"]
        cv = (float(isi.std() / isi.mean())
              if isi.size > 1 and isi.mean() > 0 else None)
        if cv is None:
            regularity = "too few intervals"
        elif cv < 1.0 - POISSON_BAND:
            regularity = "regular (CV < 1)"
        elif cv > 1.0 + POISSON_BAND:
            regularity = "bursting (CV > 1)"
        else:
            regularity = "Poisson-like (CV ~ 1)"
        per_channel["CH%d" % channel] = {
            "n_events": int(data["onsets_s"].size),
            "n_intervals": int(isi.size),
            "isi_median_s": float(np.median(isi)) if isi.size else None,
            "isi_mean_s": float(isi.mean()) if isi.size else None,
            "isi_q1_s": float(np.percentile(isi, 25)) if isi.size else None,
            "isi_q3_s": float(np.percentile(isi, 75)) if isi.size else None,
            "isi_min_s": float(isi.min()) if isi.size else None,
            "isi_max_s": float(isi.max()) if isi.size else None,
            "cv": cv,
            "regularity": regularity,
            "isi_drift": _drift(isi),
            "depth_drift": _drift(data["depths_mv"]),
            "median_depth_mv": float(np.median(data["depths_mv"])),
        }
    return per_channel


def archetype_verdict(per_channel):
    """Whether any of the draft's four sequence archetypes is VISIBLE.

    Deliberately conservative, and it returns "not visible" by default.
    Twenty minutes is a short recording, and "we looked and it is not
    there" is a reasonable finding that the report is better for stating
    plainly than for hedging around.
    """
    rising = [name for name, stats in per_channel.items()
              if stats["isi_drift"]["visible"]
              and (stats["isi_drift"]["slope"] or 0) > 0]
    bursting = [name for name, stats in per_channel.items()
                if stats["regularity"].startswith("bursting")]
    regular = [name for name, stats in per_channel.items()
               if stats["regularity"].startswith("regular")]
    drifting_depth = [name for name, stats in per_channel.items()
                      if stats["depth_drift"]["visible"]]

    # Channels where the least-squares fit alone would have said "trend"
    # but the ranks disagree. Reported explicitly, because this is exactly
    # the mistake the first version of this figure made.
    fit_only = [name for name, stats in per_channel.items()
                if stats["isi_drift"].get("least_squares_only")
                or stats["depth_drift"].get("least_squares_only")]

    findings = []
    if rising:
        findings.append(
            "stegosaurus (monotonically rising ISI) on " + ", ".join(rising))
    if drifting_depth:
        findings.append("amplitude drift across the recording on "
                        + ", ".join(drifting_depth))
    return {
        "archetypes_looked_for": list(ARCHETYPES),
        "criteria": {
            "rising_ISI": ("least-squares fit of ISI on event index with "
                           "r2 >= %.2f and p <= %g, AND |Spearman rho| >= "
                           "%.2f with p <= %g, AND the two agreeing in sign"
                           % (DRIFT_MIN_R2, DRIFT_MAX_P, DRIFT_MIN_ABS_RHO,
                              DRIFT_MAX_P)),
            "bursting": "CV > %.2f" % (1.0 + POISSON_BAND),
            "regular": "CV < %.2f" % (1.0 - POISSON_BAND),
        },
        "channels_with_rising_isi": rising,
        "channels_bursting": bursting,
        "channels_regular": regular,
        "channels_with_depth_drift": drifting_depth,
        "channels_where_only_the_least_squares_fit_agrees": fit_only,
        "rank_check_note": ("a channel listed under "
                            "channels_where_only_the_least_squares_fit_"
                            "agrees has a respectable r2 driven by one "
                            "excursion rather than by a trend - CH2's "
                            "single 40 s gap is the case this check was "
                            "added for"),
        "any_archetype_visible": bool(findings),
        "verdict": ("; ".join(findings) if findings else
                    "NONE of the four named sequence archetypes is visible "
                    "in these panels. Over 20 minutes at 10 Hz that is a "
                    "reasonable finding rather than a null result to "
                    "apologise for: the recording is too short for a slow "
                    "sequence structure to complete even one period."),
    }
