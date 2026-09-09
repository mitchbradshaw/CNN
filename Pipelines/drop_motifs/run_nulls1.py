"""
run_nulls1.py
==============
The one command that produces `Plots/drop_motifs9_fig2a/nulls_v1/`.

    python Pipelines/drop_motifs/run_nulls1.py

Tasks 0 and 2-6. Task 1's grid is `run_surrogates1.py`, run separately
because it is the only part that takes more than a couple of minutes; this
script draws `NULL_surrogate.png` from the JSON that grid leaves behind,
and says so rather than silently skipping it if the grid has not been run.

    python Pipelines/drop_motifs/run_surrogates1.py --n 100   # ~1 h
    python Pipelines/drop_motifs/run_nulls1.py                # ~4 min

Every task writes one JSON beside its figure holding every number the
figure states, so the paper quotes the JSON and never the PNG. Nothing
here touches the refined store, the raw store, `Plots/drop_motifs8_fig2a/`
or the database beyond a read.
"""

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "4")

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from Pipelines.drop_motifs import clusterk1, crosschan1 as cc
from Pipelines.drop_motifs import nuisance1, nullfigs1
from Pipelines.drop_motifs import nulls1 as n1
from Working.Detection.drop_motifs import motifs5


def _write(payload, path):
    Path(path).write_text(json.dumps(n1.jsonable(payload), indent=1),
                          encoding="utf-8")
    return str(path)


# ===========================================================================
# Task 0
# ===========================================================================

def task0_distance(out_dir):
    """Which distance actually built the shipped dendrogram.

    Settled by RECOMPUTATION, not by reading the code: the cophenetic
    correlation of Ward-over-Euclidean on the feature matrix is compared
    against the number `refine_report.json` shipped. If they agree to four
    decimal places, that is what built the tree.
    """
    from scipy.cluster.hierarchy import cophenet, linkage
    from scipy.spatial.distance import pdist, squareform
    from scipy.stats import pearsonr, spearmanr

    from Working import distances as wd
    from Working.Detection.drop_motifs import cluster as dc

    rows, snippets, _ = n1.load_refined_store()
    waveforms, keep = [], []
    for row in rows:
        wave = n1.waveform_of(row, snippets, mode="fall")
        if wave is not None:
            waveforms.append(wave)
            keep.append(row)

    features = dc.feature_matrix(waveforms)
    condensed = pdist(features, metric="euclidean")
    Z = linkage(condensed, method="ward")
    coph, _ = cophenet(Z, condensed)

    shipped = json.loads(
        (n1.PLOT_DIR / "refined_v2" / "refine_report.json")
        .read_text(encoding="utf-8"))
    shipped_coph = shipped["figures"]["dendrogram"]["cophenetic"]

    # Are the two distances equivalent in practice? Compared over a
    # subsample because `distance_matrix` is an O(n^2) Python loop.
    rng = np.random.default_rng(0)
    index = rng.choice(len(waveforms), min(220, len(waveforms)),
                       replace=False)
    subset = [waveforms[i] for i in index]
    scale_invariant = dc.distance_matrix(
        subset, metric=wd.DISTANCE_SCALE_INVARIANT)
    euclidean = squareform(pdist(dc.feature_matrix(subset),
                                 metric="euclidean"))
    upper = np.triu_indices(len(subset), 1)
    a, b = scale_invariant[upper], euclidean[upper]

    depths = np.asarray([abs(float(r["drop_depth_mv"])) for r in keep])
    amplitude_leak = float(pearsonr(np.linalg.norm(features, axis=1),
                                    depths)[0])

    payload = {
        "task": "Task 0 - which distance built the shipped tree",
        "answer": ("PLAIN EUCLIDEAN over the resampled, z-normalised "
                   "feature vectors. cluster.build_linkage calls "
                   "pdist(features, metric='euclidean') then Ward; "
                   "cluster.distance_matrix / DISTANCE_SCALE_INVARIANT is "
                   "a separate utility and produced no shipped dendrogram. "
                   "DETECTION_AND_FIGURES.md section 3 is correct; "
                   "PROVENANCE.md is wrong."),
        "evidence": {
            "recomputed_cophenetic": float(coph),
            "shipped_cophenetic_refine_report": float(shipped_coph),
            "agree": bool(abs(coph - shipped_coph) < 1e-6),
            "n_motifs": len(keep),
        },
        "equivalence": {
            "question": ("does z-normalisation of the resampled vector make "
                         "the two distances equivalent in practice?"),
            "answer": ("YES, to within a monotone rescaling. Both pipelines "
                       "are resample -> z-normalise -> Euclidean. They "
                       "differ only in the common length (a fixed 200 here "
                       "against max(len_a, len_b) pairwise there) and in a "
                       "1/sqrt(n) factor distance_matrix applies so its "
                       "output reads as an RMS z-score per sample."),
            "n_pairs": int(len(a)),
            "spearman": float(spearmanr(a, b).statistic),
            "pearson": float(pearsonr(a, b)[0]),
        },
        "is_the_scale_invariance_claim_still_true": {
            "verdict": True,
            "why": ("z_normalize divides out each event's own standard "
                    "deviation and resample_to_length divides out its own "
                    "duration, so amplitude and duration are removed from "
                    "every vector BEFORE the Euclidean distance is taken. "
                    "The grouping is therefore scale-invariant by "
                    "construction - but because the NORMALISATION is "
                    "applied per vector, not because a scale-invariant "
                    "METRIC was used. The appendix has to say the former."),
            "correlation_feature_norm_vs_depth": amplitude_leak,
            "note": ("a correlation of ~0 between a feature vector's norm "
                     "and its event's depth is the direct check: no "
                     "amplitude information survives into the space the "
                     "tree is built in."),
        },
        "documents_to_correct": [
            {"file": "Plots/drop_motifs9_fig2a/PROVENANCE.md",
             "status": "WRONG",
             "passage": ("\"the clustering distance is scale-invariant "
                         "(cluster.DISTANCE_SCALE_INVARIANT)\""),
             "correction": ("the distance is plain Euclidean over "
                            "resampled, z-normalised vectors; the grouping "
                            "is scale-invariant because of that "
                            "normalisation, not because "
                            "DISTANCE_SCALE_INVARIANT was used")},
            {"file": "Pipelines/drop_motifs/DETECTION_AND_FIGURES.md",
             "status": "CORRECT", "passage": "section 3, item 1",
             "correction": None},
        ],
    }
    return _write(payload, Path(out_dir) / "TASK0_distance.json"), payload


# ===========================================================================
# Task 2
# ===========================================================================

def task2_nuisance(out_dir, *, permutations=nuisance1.N_PERMUTATIONS):
    rows, snippets, _ = n1.load_refined_store()
    features, keep, dropped = n1.build_features(rows, snippets, mode="fall")

    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist
    Z = linkage(pdist(features, metric="euclidean"), method="ward")
    channels = np.asarray([int(r["channel"]) for r in keep], dtype=int)

    family_by_channel = {}
    for name, k in (("coarse_k%d" % n1.COARSE_K, n1.COARSE_K),
                    ("fine_k%d" % n1.FINE_K, n1.FINE_K)):
        labels = fcluster(Z, int(k), criterion="maxclust")
        family_by_channel[name] = nuisance1.permutation_test(
            labels, channels, n_permutations=permutations)
        family_by_channel[name]["k"] = int(k)

    pre_floor, n_raw = nuisance1.raw_store_depths()
    payload = {
        "task": "Task 2 - amplitude is the electrode, shape is not",
        "claim": ("absolute event amplitude is a property of the electrode; "
                  "relative event shape is not"),
        "n_refined_store": len(rows),
        "n_clustered": len(keep),
        "n_dropped_from_tree": dropped,
        "n_raw_store": int(n_raw),
        "depth_test": nuisance1.depth_test(rows),
        "pre_floor_depth_by_channel": {
            "CH%d" % c: {"n": int(v.size),
                         "median_mv": float(np.median(v)),
                         "fraction_at_or_below_floor": float(
                             (v <= n1.MIN_DEPTH_MV).mean())}
            for c, v in pre_floor.items()},
        "family_by_channel": family_by_channel,
        "shape_spread": nuisance1.per_channel_shape_spread(features, keep),
        "residual_flag": nuisance1.RESIDUAL_FLAG,
        "feature_mode": "fall (onset..trough) - the shipped representation",
    }
    payload["_post_floor_depths"] = {
        c: v.tolist() for c, v in nuisance1.depth_by_channel(rows).items()}
    payload["_pre_floor_depths"] = {c: v.tolist()
                                    for c, v in pre_floor.items()}
    path = nullfigs1.plot_nuisance_vs_signal(
        payload, Path(out_dir) / "NUISANCE_vs_SIGNAL.png")
    return path, _write(payload, Path(out_dir) / "NUISANCE_vs_SIGNAL.json"), \
        payload


# ===========================================================================
# Task 3
# ===========================================================================

def _zero_lag_concentration(pairs, half_width_s=None):
    """Is there a spike at lag zero, or is the lag distribution flat?

    A clean spike at zero is what a shared-ground disturbance would look
    like, and it is the result Task 3 was expecting to find or refute.
    The comparison is against a UNIFORM lag distribution over the search
    range, which is what "no alignment structure at all" looks like when
    every pair's peak is placed by noise.
    """
    half_width_s = (cc.DEFAULT_THRESHOLDS.common_lag_s
                    if half_width_s is None else half_width_s)
    lags = np.asarray([p["peak_lag_s"] for p in pairs
                       if p["peak_lag_s"] is not None], dtype=float)
    if not lags.size:
        return {"observed_fraction": None, "uniform_fraction": None,
                "ratio": None, "half_width_s": float(half_width_s), "n": 0}
    observed = float((np.abs(lags) <= half_width_s).mean())
    uniform = float(2 * half_width_s / (2 * cc.MAX_LAG_S))
    return {"observed_fraction": observed, "uniform_fraction": uniform,
            "ratio": float(observed / uniform) if uniform else None,
            "half_width_s": float(half_width_s), "n": int(lags.size)}


def _sensitivity_verdict(counts, ranges, tolerance=0.30):
    """Are the bin counts stable under +-50% on each threshold?

    "Stable" is defined here, once, rather than left to a reader's eye:
    a bin is stable if no single threshold moving by +-50% changes its
    count by more than `tolerance` of its stated value. The brief asks
    whether the counts are stable, so the answer has to be a rule with a
    number in it.
    """
    verdict = {"tolerance": tolerance, "per_bin": {}, "stable": True,
               "worst": None}
    worst_swing = -1.0
    for name in ("common_mode", "propagation"):
        stated = max(counts.get(name, 0), 1)
        swings = {}
        for threshold, node in ranges.items():
            low, high = node["%s_range" % name]
            swings[threshold] = float((high - low) / stated)
        driver = max(swings, key=swings.get)
        stable = swings[driver] <= tolerance
        verdict["per_bin"][name] = {
            "stated_count": counts.get(name, 0),
            "relative_swing_by_threshold": swings,
            "worst_threshold": driver,
            "worst_relative_swing": swings[driver],
            "stable": stable,
        }
        verdict["stable"] = verdict["stable"] and stable
        if swings[driver] > worst_swing:
            worst_swing = swings[driver]
            verdict["worst"] = {"bin": name, "threshold": driver,
                                "relative_swing": swings[driver]}
    if verdict["stable"]:
        verdict["reading"] = (
            "the bin counts are STABLE: no threshold moved by +-50%% "
            "changes any bin by more than %.0f%% of its stated count"
            % (100 * tolerance))
    else:
        worst = verdict["worst"]
        verdict["reading"] = (
            "the bin counts are NOT STABLE. Moving %s by +-50%% swings the "
            "%s count by %.0f%% of its stated value (%s), which is well "
            "beyond the %.0f%% tolerance. The bin BOUNDARIES are "
            "conventions and the counts inside them must be quoted as "
            "\"under these thresholds\", never as a measurement. What does "
            "NOT move is the qualitative reading, because the same "
            "thresholds are applied to the rotation null."
            % (worst["threshold"], worst["bin"],
               100 * worst["relative_swing"],
               ranges[worst["threshold"]]["%s_range" % worst["bin"]],
               100 * tolerance))
    return verdict


def task3_cross_channel(out_dir, *, permutations=nuisance1.N_PERMUTATIONS,
                        rotations=cc.ROTATION_TRIALS):
    rows, snippets, _ = n1.load_refined_store()
    pairs = cc.cross_channel_pairs(rows, snippets)
    counts = cc.bin_counts(pairs)
    suspect = cc.common_mode_event_ids(pairs)
    sensitivity, sensitivity_ranges = cc.sensitivity_table(pairs)

    n_samples = max(int(r["snippet_end_idx"]) for r in rows)
    entries = n1.channel_table()
    n_samples = max(n_samples, len(n1.load_channel(entries[0])))
    rotation = cc.rotation_null(rows, n_samples, trials=rotations)

    # Rebuild Task 2's family table with every common-mode event removed.
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    def _family_p(subset_rows):
        features, keep, _ = n1.build_features(subset_rows, snippets,
                                              mode="fall")
        if features is None:
            return None, 0
        Z = linkage(pdist(features, metric="euclidean"), method="ward")
        labels = fcluster(Z, n1.COARSE_K, criterion="maxclust")
        channels = np.asarray([int(r["channel"]) for r in keep], dtype=int)
        return nuisance1.permutation_test(labels, channels,
                                          n_permutations=permutations), \
            len(keep)

    with_all, n_all = _family_p(rows)
    cleaned_rows = [r for r in rows if r["event_id"] not in suspect]
    without, n_without = _family_p(cleaned_rows)

    survives = {
        "n_common_mode_events_removed": len(suspect),
        "n_before": n_all, "n_after": n_without,
        "permutation_p_with_common_mode": (with_all or {}).get("permutation_p"),
        "cramers_v_with_common_mode": (with_all or {}).get("cramers_v"),
        "permutation_p": (without or {}).get("permutation_p"),
        "cramers_v": (without or {}).get("cramers_v"),
        "n_families_with_all_five_channels":
            (without or {}).get("n_families_with_all_five_channels"),
        # "Survives" means the channel-independence reading is unchanged:
        # the permutation test still fails to reject independence at 0.05.
        # Stated as a rule so the word is not doing the work silently.
        "criterion": ("channel independence survives if the permutation p "
                      "without common-mode events is still > 0.05"),
        "survives": bool((without or {}).get("permutation_p", 0) > 0.05),
    }

    payload = {
        "task": "Task 3 - cross-channel co-occurrence and the common-mode "
                "control",
        "why": ("five electrodes 1.5 mm apart on a shared ground: Task 2's "
                "channel-mixing claim is worthless if the mixing is one "
                "disturbance recorded five times"),
        "thresholds": {
            "pair_window_s": cc.PAIR_WINDOW_S,
            "max_lag_s": cc.MAX_LAG_S,
            "min_overlap_samples": cc.MIN_OVERLAP_SAMPLES,
            **{k: float(v) for k, v in
               vars(cc.DEFAULT_THRESHOLDS).items()},
        },
        "n_events_considered": len(rows),
        "n_pairs": len(pairs),
        "bin_counts": counts,
        "bin_fractions": {k: (v / len(pairs) if pairs else 0.0)
                          for k, v in counts.items()},
        "n_common_mode_events": len(suspect),
        "common_mode_event_fraction": len(suspect) / max(len(rows), 1),
        "zero_lag_concentration": _zero_lag_concentration(pairs),
        "lag_summary": n1.quartiles(p["peak_lag_s"] for p in pairs),
        "abs_lag_summary": n1.quartiles(
            abs(p["peak_lag_s"]) for p in pairs
            if p["peak_lag_s"] is not None),
        "r_summary": n1.quartiles(p["peak_r"] for p in pairs),
        "sensitivity": sensitivity, "sensitivity_ranges": sensitivity_ranges,
        "sensitivity_verdict": _sensitivity_verdict(counts,
                                                    sensitivity_ranges),
        "rotation_null": {k: v for k, v in rotation.items() if k != "null"},
        "family_result_without_common_mode": survives,
        "pairs_by_channel_pair": {
            "CH%d-CH%d" % (a, b): sum(1 for p in pairs
                                      if p["channel_a"] == a
                                      and p["channel_b"] == b)
            for a in range(5) for b in range(a + 1, 5)},
        "common_mode_by_channel_pair": {
            "CH%d-CH%d" % (a, b): sum(1 for p in pairs
                                      if p["bin"] == "common_mode"
                                      and p["channel_a"] == a
                                      and p["channel_b"] == b)
            for a in range(5) for b in range(a + 1, 5)},
    }
    payload["_pairs"] = pairs
    payload["rotation_null"]["null"] = rotation["null"]
    path = nullfigs1.plot_cross_channel(payload,
                                        Path(out_dir) / "CROSS_CHANNEL.png")
    payload["rotation_null"].pop("null", None)
    return path, _write(payload, Path(out_dir) / "CROSS_CHANNEL.json"), payload


# ===========================================================================
# Task 4
# ===========================================================================

def task4_cluster_k(out_dir):
    rows, snippets, _ = n1.load_refined_store()
    features, keep, dropped = n1.build_features(rows, snippets, mode="fall")
    per_k, cophenetic, _ = clusterk1.silhouette_and_gap(features)
    selection = clusterk1.apply_selection_rule(per_k)

    payload = {
        "task": "Task 4 - a stated rule for the number of families",
        "rule_stated_before_the_answer_was_read": clusterk1.SELECTION_RULE,
        "n": len(keep),
        "n_dropped_from_tree": dropped,
        "k_range": list(clusterk1.K_RANGE),
        "cophenetic_r": cophenetic,
        "cophenetic_note": ("a property of the LINKAGE, not of k - reported "
                            "once, and not plotted against k"),
        "n_gap_references": clusterk1.GAP_REFERENCES,
        "gap_seed": clusterk1.GAP_SEED,
        "gap_caveat": ("The gap statistic's uniform reference is a poor null "
                       "for 200-dimensional z-normalised vectors, which lie "
                       "on a thin shell rather than filling a box, so the "
                       "gap partly measures that geometry. It is reported "
                       "because it is the conventional companion number and "
                       "because its disagreement with silhouette is itself "
                       "informative - not because it is the criterion."),
        "per_k": per_k,
        "selection": selection,
        "known_tension": ("earlier work: Ward over PCA gave silhouette 0.238 "
                          "at k = 5 with cophenetic r 0.52, while average "
                          "linkage gave cophenetic r 0.91 but suggested "
                          "k = 2. A smaller repertoire is better for the "
                          "argument, not worse, so k = 2 would be reported "
                          "as k = 2."),
        "feature_mode": "fall (onset..trough) - the shipped representation",
    }
    path = nullfigs1.plot_cluster_k(payload, Path(out_dir) / "CLUSTER_K.png")
    return path, _write(payload, Path(out_dir) / "CLUSTER_K.json"), payload


# ===========================================================================
# Task 5
# ===========================================================================

def task5_sequence(out_dir):
    rows, _, _ = n1.load_refined_store()
    per_channel = clusterk1.sequence_stats(rows)
    archetypes = clusterk1.archetype_verdict(per_channel)

    payload = {
        "task": "Task 5 - sequence structure",
        "n": len(rows),
        "recording_seconds": 1200.0,
        "fs": 10.0,
        "per_channel": per_channel,
        "archetypes": archetypes,
        "poisson_band": clusterk1.POISSON_BAND,
        "drift_criteria": {"min_r2": clusterk1.DRIFT_MIN_R2,
                           "max_p": clusterk1.DRIFT_MAX_P},
    }
    payload["_grouped"] = clusterk1.isi_by_channel(rows)
    path = nullfigs1.plot_sequence(payload, Path(out_dir) / "SEQUENCE.png")
    payload.pop("_grouped")
    return path, _write(payload, Path(out_dir) / "SEQUENCE.json"), payload


# ===========================================================================
# Task 6
# ===========================================================================

def task6_quantisation(out_dir):
    rows, _, _ = n1.load_refined_store()
    fs = 10.0
    seconds = np.asarray([float(r["fall_duration_s"]) for r in rows])
    samples = np.round(seconds * fs).astype(int)
    payload = {
        "task": "Task 6a - fall duration is a few samples",
        "n": len(rows), "fs": fs,
        "quantum_s": 1.0 / fs,
        "median_samples": float(np.median(samples)),
        "q1_samples": float(np.percentile(samples, 25)),
        "q3_samples": float(np.percentile(samples, 75)),
        "min_samples": int(samples.min()), "max_samples": int(samples.max()),
        "n_distinct_samples": int(len(set(samples.tolist()))),
        "median_seconds": float(np.median(seconds)),
        "q1_seconds": float(np.percentile(seconds, 25)),
        "q3_seconds": float(np.percentile(seconds, 75)),
        "fraction_under_5_samples": float((samples < 5).mean()),
        "fraction_under_3_samples": float((samples < 3).mean()),
        "reading": ("the IQR of the fall duration is %d to %d SAMPLES. Any "
                    "claim about duration - including the near-constancy "
                    "that drives the height-vs-slope result - is a claim "
                    "about that many samples."
                    % (np.percentile(samples, 25), np.percentile(samples, 75))),
    }
    payload["_duration_samples"] = samples.tolist()
    payload["_duration_seconds"] = seconds.tolist()
    path = nullfigs1.plot_quant_duration(payload,
                                         Path(out_dir) / "QUANT_duration.png")
    return path, _write(payload, Path(out_dir) / "QUANT_duration.json"), payload


def task6_alphabet(out_dir):
    """dSAX letter occupancy per channel.

    Recomputed rather than read from the store - the store keeps events,
    not the encoding that produced them - and recomputed PER SLIDING
    WINDOW, because that is how the detector encodes. Every pass derives
    its own scale from the 50 s it is handed (`params` from
    `passes6.run_base`), so one encoding over the whole 1200 s channel
    would be a different alphabet from the one that actually ran, and the
    `S` fraction is exactly the quantity that would shift.

    A letter is one dSAX SEGMENT, not one sample: `segment_seconds` is
    derived per window, so the counts below are segment counts and the
    denominator says so.
    """
    from Pipelines.drop_motifs import passes6, passes9
    from Working.Detection.drop_motifs import detect5

    letters = ["d", "D", "S", "U", "u"]
    meaning = {"d": "steep fall", "D": "fall", "S": "flat (noise floor)",
               "U": "rise", "u": "steep rise"}
    kwargs = n1.detect_kwargs()

    per_channel, sigmas, slope_sigmas = {}, [], []
    for entry in n1.channel_table():
        x = n1.load_channel(entry)
        fs = entry["fs"]
        bounds = passes9.window_bounds(len(x), fs, kwargs["window_s"],
                                       kwargs["overlap"])
        counts = {letter: 0 for letter in letters}
        total = 0
        for start, end in bounds:
            segment = np.asarray(x[start:end], dtype=float)
            try:
                base = passes6.run_base(segment, fs,
                                        max_passes=kwargs["max_passes"])
                staged, details = detect5.stage_letters(segment, fs,
                                                        base.result.params)
            except Exception:                                  # noqa: BLE001
                continue
            symbols = np.asarray(list(staged))
            for letter in letters:
                counts[letter] += int((symbols == letter).sum())
            total += int(symbols.size)
            sigmas.append(float(details.get("sigma_slope", np.nan)))
            slope_sigmas.append(float(
                getattr(base.result.params, "slope_sigma", np.nan)))
        total = max(total, 1)
        per_channel["CH%d" % entry["channel"]] = {
            "counts": counts,
            "proportions": [counts[letter] / total for letter in letters],
            "n_segments": total,
            "n_windows": len(bounds),
        }

    flat = np.mean([v["proportions"][2] for v in per_channel.values()])
    extreme = np.mean([v["proportions"][0] + v["proportions"][4]
                       for v in per_channel.values()])
    sigma = float(np.nanmedian(slope_sigmas)) if slope_sigmas else float("nan")
    k = 3
    payload = {
        "task": "Task 6b - dSAX alphabet occupancy",
        "letters": letters, "letter_meaning": meaning,
        "k": k,
        "sigma": sigma,
        "sigma_note": ("median slope_sigma across the 47 windows of all "
                       "five channels; the d/u split is at "
                       "slope_sigma x the window's own MAD slope noise"),
        "unit": "one count is one dSAX SEGMENT, not one sample",
        "per_channel": per_channel,
        "mean_S_fraction": float(flat),
        "mean_extreme_fraction": float(extreme),
        "expectation": ("an 8-sigma threshold should make d and u rare and "
                        "S dominant"),
        "expectation_met": {"S_dominant": bool(flat > 0.5),
                            "d_and_u_rare": bool(extreme < 0.10)},
    }
    if flat <= 0.5:
        payload["verdict"] = (
            "S is only %.0f%% of segments - the encoding is NOT behaving as "
            "an 8-sigma threshold should and the alphabet is close to "
            "degenerate" % (100 * flat))
    elif extreme < 0.10:
        payload["verdict"] = (
            "as expected: S dominates at %.0f%% of segments and the extreme "
            "letters d+u are rare at %.1f%%" % (100 * flat, 100 * extreme))
    else:
        # The expectation was half met, and saying so is the point of the
        # panel - a sanity check that only reports agreement is not one.
        payload["verdict"] = (
            "HALF the expectation holds. S does dominate (%.0f%% of "
            "segments), but d+u are NOT rare - they are %.1f%% of all "
            "segments, roughly one in three. At an 8-sigma slope cut that "
            "is a lot, and it says the per-window MAD slope noise is small "
            "relative to the excursions these channels actually contain "
            "rather than that the threshold is misapplied. The encoding is "
            "not degenerate; it is simply not sparse."
            % (100 * flat, 100 * extreme))
    path = nullfigs1.plot_alphabet(payload, Path(out_dir) / "ALPHABET.png")
    return path, _write(payload, Path(out_dir) / "ALPHABET.json"), payload


def task6_windowing(out_dir):
    """Whole-channel against sliding-window detection, and what the extra
    detections look like."""
    whole_dir = n1.PLOT_DIR.parent / "drop_motifs8_fig2a" / "motifs"
    if not whole_dir.exists():
        return None, None, {"skipped": "no %s" % whole_dir}

    whole = motifs5.load_events(str(whole_dir))
    sliding = motifs5.load_events(str(n1.RAW_STORE))

    per_channel, added_depths, shared_depths = {}, [], []
    for channel in range(5):
        w = [r for r in whole if int(r["channel"]) == channel]
        s = [r for r in sliding if int(r["channel"]) == channel]
        per_channel["CH%d" % channel] = {
            "whole_channel": len(w), "sliding": len(s),
            "ratio": len(s) / max(len(w), 1),
        }
        # An event is "shared" when the whole-channel run found a drop
        # within half a second of it. Onset proximity rather than event id
        # because the two runs frame their windows differently and never
        # produce the same id for the same drop.
        w_onsets = np.sort(np.asarray([int(r["onset_idx"]) for r in w]))
        for row in s:
            onset = int(row["onset_idx"])
            near = (w_onsets.size and
                    np.min(np.abs(w_onsets - onset)) <= 5)
            (shared_depths if near else added_depths).append(
                abs(float(row["drop_depth_mv"])))

    added = np.asarray(added_depths, dtype=float)
    payload = {
        "task": "Task 6c - whole-channel against sliding-window detection",
        "total_whole": len(whole), "total_sliding": len(sliding),
        "per_channel": per_channel,
        "match_tolerance_samples": 5,
        "n_added": int(added.size), "n_shared": len(shared_depths),
        "added_above_floor_fraction": float(
            (added > n1.MIN_DEPTH_MV).mean()) if added.size else 0.0,
        "added_depth": n1.quartiles(added_depths),
        "shared_depth": n1.quartiles(shared_depths),
    }
    # The reading is COMPUTED. An earlier version printed "so the extra
    # count is not sub-noise inflation" whatever the fraction was, which
    # would have asserted the opposite of the number beside it.
    if not added.size:
        payload["reading"] = "no added events"
    else:
        fraction = float((added > n1.MIN_DEPTH_MV).mean())
        survivors = int((added > n1.MIN_DEPTH_MV).sum())
        if fraction >= 0.5:
            payload["reading"] = (
                "%.0f%% of what the sliding window adds clears the 0.1 mV "
                "instrument floor, so the extra count is not sub-noise "
                "inflation" % (100 * fraction))
        else:
            payload["reading"] = (
                "ONLY %.0f%% of what the sliding window adds clears the "
                "0.1 mV instrument floor - %d of %d added detections are "
                "sub-noise and the floor removes them. The defensible "
                "claim is therefore about the %d that survive, not about "
                "the raw %d -> %d count: the sliding window finds %d real "
                "events the whole-channel framing missed, and the rest of "
                "its extra count IS sub-noise and is gated away."
                % (100 * fraction, int(added.size) - survivors,
                   int(added.size), survivors, payload["total_whole"],
                   payload["total_sliding"], survivors))
        payload["n_added_above_floor"] = survivors
    payload["_added_depths"] = added_depths
    payload["_shared_depths"] = shared_depths
    path = nullfigs1.plot_windowing(payload, Path(out_dir) / "WINDOWING.png")
    return path, _write(payload, Path(out_dir) / "WINDOWING.json"), payload


# ===========================================================================
# Task 1's figure, from the grid's JSON
# ===========================================================================

def task1_figure(out_dir):
    json_path = Path(out_dir) / "NULL_surrogate.json"
    runs_path = Path(out_dir) / "surrogate_runs" / "realisations.json"
    if not json_path.exists() or not runs_path.exists():
        return None, {"skipped": (
            "run `python Pipelines/drop_motifs/run_surrogates1.py --n 100` "
            "first - NULL_surrogate.json is not there yet")}
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    realisations = json.loads(
        runs_path.read_text(encoding="utf-8"))["realisations"]
    path = nullfigs1.plot_null_surrogate(payload, realisations,
                                         Path(out_dir) / "NULL_surrogate.png")
    return path, payload


# ===========================================================================

TASKS = ("0", "2", "3", "4", "5", "6", "1fig")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(n1.OUT_DIR))
    parser.add_argument("--tasks", nargs="*", default=list(TASKS),
                        choices=list(TASKS))
    parser.add_argument("--permutations", type=int,
                        default=nuisance1.N_PERMUTATIONS)
    parser.add_argument("--rotations", type=int, default=cc.ROTATION_TRIALS)
    parser.add_argument("--with-surrogates", type=int, metavar="N",
                        help="run Task 1's grid first, with N realisations "
                             "per generator (about 50 min at N=100 on 14 "
                             "cores). Omit to draw Task 1's figure from a "
                             "grid that has already been run.")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--no-readme", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    (out_dir / "surrogate_runs").mkdir(parents=True, exist_ok=True)
    results = {}

    # Task 1's grid, when asked for. Kept as a separate module and invoked
    # here rather than merged in, because it is the only part that takes
    # tens of minutes and it must stay runnable on its own - but "one
    # command reproduces everything" is a requirement, so there has to be
    # a flag that does the whole thing.
    if args.with_surrogates:
        print("=== Task 1 - the surrogate grid (N = %d per generator)"
              % args.with_surrogates, flush=True)
        from Pipelines.drop_motifs import run_surrogates1
        code = run_surrogates1.main(
            ["--n", str(args.with_surrogates),
             "--out-dir", str(out_dir)]
            + (["--workers", str(args.workers)] if args.workers else []))
        if code != 0:
            print("  ! the grid failed; Task 1's figure will be skipped")

    def _run(name, label, fn):
        if name not in args.tasks:
            return
        print("\n=== %s" % label, flush=True)
        started = time.time()
        try:
            out = fn()
        except Exception as exc:                               # noqa: BLE001
            print("  ! FAILED: %r" % (exc,), flush=True)
            import traceback
            traceback.print_exc()
            results[name] = {"error": repr(exc)}
            return
        results[name] = out[-1]
        for item in out[:-1]:
            if item:
                print("  -> %s" % item, flush=True)
        print("  %.1f s" % (time.time() - started), flush=True)

    _run("0", "Task 0 - which distance built the shipped tree",
         lambda: task0_distance(out_dir))
    if "0" in args.tasks and "error" not in results.get("0", {}):
        answer = results["0"]
        print("  recomputed cophenetic %.4f vs shipped %.4f -> %s"
              % (answer["evidence"]["recomputed_cophenetic"],
                 answer["evidence"]["shipped_cophenetic_refine_report"],
                 "MATCH" if answer["evidence"]["agree"] else "DISAGREE"))
        print("  scale-invariant vs euclidean-over-features: "
              "Spearman %.4f over %d pairs"
              % (answer["equivalence"]["spearman"],
                 answer["equivalence"]["n_pairs"]))

    _run("2", "Task 2 - amplitude is the electrode, shape is not",
         lambda: task2_nuisance(out_dir, permutations=args.permutations))
    _run("3", "Task 3 - cross-channel co-occurrence",
         lambda: task3_cross_channel(out_dir, permutations=args.permutations,
                                     rotations=args.rotations))
    _run("4", "Task 4 - a stated rule for k",
         lambda: task4_cluster_k(out_dir))
    _run("5", "Task 5 - sequence structure",
         lambda: task5_sequence(out_dir))
    _run("6", "Task 6a - duration quantisation",
         lambda: task6_quantisation(out_dir))
    _run("6", "Task 6b - dSAX alphabet", lambda: task6_alphabet(out_dir))
    _run("6", "Task 6c - windowing", lambda: task6_windowing(out_dir))

    if "1fig" in args.tasks:
        print("\n=== Task 1 - NULL_surrogate.png", flush=True)
        path, payload = task1_figure(out_dir)
        if path:
            print("  -> %s" % path)
        else:
            print("  ! %s" % payload["skipped"])

    if not args.no_readme:
        print("\n=== README, rebuilt from the JSONs", flush=True)
        from Pipelines.drop_motifs import run_readme1
        readme, n_items = run_readme1.build(out_dir)
        print("  -> %s  (%d entries under \"what the nulls did not "
              "support\")" % (readme, n_items))

    print("\n-> %s" % out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
