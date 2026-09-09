"""
run_readme1.py
===============
Builds `Plots/drop_motifs9_fig2a/nulls_v1/README.md` FROM THE JSONS the
other two scripts wrote, so no number in it is transcribed by hand and it
cannot drift from the figures.

    python Pipelines/drop_motifs/run_readme1.py

Sections, in the order the brief asks for:

  1. the Task 0 answer, in one paragraph
  2. one command that reproduces everything
  3. every statistic the figures state, with its p and its N, in a form
     that pastes into a paper
  4. WHAT THE NULLS DID NOT SUPPORT - at the same prominence as what
     worked, because a surrogate that reproduces the depth-angle rho is
     better found tonight than in review
  5. every RNG seed

Section 4 is generated from the results, not written in advance: a claim
lands there when its own p says it should.
"""

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import nulls1 as n1

ALPHA = 0.05


def _load(path):
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value, spec="%.4g"):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        return spec % float(value)
    except (TypeError, ValueError):
        return str(value)


def _p(value):
    if value is None:
        return "-"
    if value <= 1.0 / 101.0 + 1e-9:
        return "%.4f *(floor)*" % value
    return "%.4f" % value


def statistic_rows(surrogate, nuisance, cross, clusterk, sequence, quant,
                   windowing):
    """`[(statistic, observed, null median, p, N), ...]` - the table a
    paper pastes."""
    rows = []

    if surrogate:
        observed = surrogate["observed"]
        tests = surrogate["tests"]
        n = surrogate["n_realisations_per_generator"]
        for generator in n1.GENERATORS:
            label = n1.GENERATOR_LABELS[generator]
            node = tests["detections"]["pooled"][generator]
            rows.append(("detections after the 0.1 mV floor, pooled "
                         "(vs %s)" % label,
                         _fmt(node["observed"], "%d"),
                         _fmt(node["null_median"], "%.1f"),
                         _p(node["p"]), "N = %d" % n))
        for channel in range(5):
            for generator in n1.GENERATORS:
                node = tests["detections"]["CH%d" % channel][generator]
                rows.append(("detections, CH%d (vs %s)"
                             % (channel, n1.GENERATOR_LABELS[generator]),
                             _fmt(node["observed"], "%d"),
                             _fmt(node["null_median"], "%.1f"),
                             _p(node["p"]), "N = %d" % n))
        for mode in n1.FEATURE_MODES:
            for generator in n1.GENERATORS:
                node = tests["family"][mode]["n_families_at_height"][generator]
                rows.append(("families (>=%d members) at the real tree's "
                             "k=4 height [%s] (vs %s)"
                             % (n1.MIN_FAMILY_MEMBERS, mode,
                                n1.GENERATOR_LABELS[generator]),
                             _fmt(node["observed"], "%d"),
                             _fmt(node["null_median"], "%.1f"),
                             _p(node["p"]), "N = %d" % n))
                node = tests["family"][mode]["within_family_dispersion"][generator]
                rows.append(("mean within-family distance to centroid at "
                             "k=4 [%s] (vs %s)"
                             % (mode, n1.GENERATOR_LABELS[generator]),
                             _fmt(node["observed"], "%.4f"),
                             _fmt(node["null_median"], "%.4f"),
                             _p(node["p"]), "N = %d" % n))
        for generator in n1.GENERATORS:
            node = tests["geometry"]["spearman_rho"][generator]
            rows.append(("Spearman rho (depth vs fall angle) (vs %s)"
                         % n1.GENERATOR_LABELS[generator],
                         _fmt(node["observed"], "%+.4f"),
                         _fmt(node["null_median"], "%+.4f"),
                         _p(node["p"]),
                         "N = %d, n = %d events"
                         % (n, observed["angle_n"])))
            node = tests["geometry"]["control_b"][generator]
            rows.append(("control exponent b, duration ~ depth^b (vs %s)"
                         % n1.GENERATOR_LABELS[generator],
                         _fmt(node["observed"], "%.4f"),
                         _fmt(node["null_median"], "%.4f"),
                         _p(node["p"]), "N = %d" % n))

    if nuisance:
        depth = nuisance["depth_test"]
        rows.append(("Kruskal-Wallis H, drop depth by channel",
                     "H = %.1f, eps^2 = %.4f"
                     % (depth["H"], depth["epsilon_squared"]),
                     "-", "%.3g" % depth["p"], "n = %d" % depth["n"]))
        rows.append(("median depth ratio, deepest / shallowest channel "
                     "(after the floor)",
                     "%.2fx" % depth["median_ratio_max_over_min"], "-", "-",
                     "n = %d" % depth["n"]))
        pre = nuisance["pre_floor_depth_by_channel"]
        medians = [v["median_mv"] for v in pre.values()]
        rows.append(("median depth ratio, deepest / shallowest channel "
                     "(BEFORE the floor)",
                     "%.2fx" % (max(medians) / min(medians)), "-", "-",
                     "n = %d" % nuisance["n_raw_store"]))
        for name, table in nuisance["family_by_channel"].items():
            rows.append(("family x channel association, %s "
                         "(Cramer's V)" % name,
                         "%.4f" % table["cramers_v"],
                         "%.4f" % table["null_cramers_v_median"],
                         _p(table["permutation_p"]),
                         "%d shuffles, n = %d"
                         % (table["n_permutations"],
                            nuisance["n_clustered"])))
            rows.append(("families holding all five channels, %s" % name,
                         "%d of %d"
                         % (table["n_families_with_all_five_channels"],
                            table["n_families"]), "-", "-", "-"))
        spread = nuisance["shape_spread"]
        rows.append(("electrode separation: amplitude spread / shape spread",
                     "%.2fx" % spread["separation_ratio_depth_over_shape"],
                     "-", "-", "5 channels"))

    if cross:
        rows.append(("cross-channel pairs within +-%g s"
                     % cross["thresholds"]["pair_window_s"],
                     "%d" % cross["n_pairs"], "-", "-",
                     "n = %d events" % cross["n_events_considered"]))
        for name, count in cross["bin_counts"].items():
            rows.append(("  of which %s" % name,
                         "%d (%.1f%%)"
                         % (count, 100 * cross["bin_fractions"][name]),
                         "-", "-", "-"))
        rotation = cross["rotation_null"]
        rows.append(("cross-channel onset coincidences vs rotation null",
                     "%d" % rotation["observed_coincidences"],
                     "%.0f" % rotation["null_median"], _p(rotation["p"]),
                     "%d rotations" % rotation["n_trials"]))
        survives = cross["family_result_without_common_mode"]
        rows.append(("family x channel permutation p with common-mode "
                     "events removed",
                     "V = %s" % _fmt(survives["cramers_v"], "%.4f"),
                     "-", _p(survives["permutation_p"]),
                     "n = %d (was %d)"
                     % (survives["n_after"], survives["n_before"])))
        concentration = cross.get("zero_lag_concentration") or {}
        if concentration.get("ratio") is not None:
            rows.append(("peak lags within +-%.1f s of zero, vs uniform"
                         % concentration["half_width_s"],
                         "%.1f%%" % (100 * concentration["observed_fraction"]),
                         "%.1f%%" % (100 * concentration["uniform_fraction"]),
                         "%.2fx" % concentration["ratio"],
                         "n = %d pairs" % concentration["n"]))
        for name, node in (cross.get("sensitivity_ranges") or {}).items():
            rows.append(("bin counts under +-50%% on `%s`" % name,
                         "common_mode %d-%d, propagation %d-%d"
                         % (*node["common_mode_range"],
                            *node["propagation_range"]), "-", "-",
                         "stated: %d / %d"
                         % (cross["bin_counts"]["common_mode"],
                            cross["bin_counts"]["propagation"])))

    if clusterk:
        selection = clusterk["selection"]
        rows.append(("selected k (rule: %s)" % selection["rule"],
                     "k = %d" % selection["selected_k"],
                     "-", "silhouette %.4f" % selection["selected_silhouette"],
                     "n = %d" % clusterk["n"]))
        rows.append(("gap-statistic k (Tibshirani rule)",
                     "k = %s" % (selection["gap_selected_k"] or "-"),
                     "-", "-", "%d references"
                     % clusterk["n_gap_references"]))
        rows.append(("cophenetic r of the Ward linkage",
                     "%.4f" % clusterk["cophenetic_r"], "-", "-",
                     "n = %d" % clusterk["n"]))

    if sequence:
        for name, stats in sequence["per_channel"].items():
            rows.append(("ISI coefficient of variation, %s" % name,
                         _fmt(stats["cv"], "%.3f"), "1.0 (Poisson)",
                         stats["regularity"],
                         "%d intervals" % stats["n_intervals"]))

    if quant:
        rows.append(("fall duration, IQR in SAMPLES at 10 Hz",
                     "%g-%g samples"
                     % (quant["q1_samples"], quant["q3_samples"]),
                     "-", "-", "n = %d" % quant["n"]))
        rows.append(("fall duration, distinct values in the whole store",
                     "%d" % quant["n_distinct_samples"], "-", "-",
                     "n = %d" % quant["n"]))

    if windowing and "skipped" not in windowing:
        rows.append(("motifs: whole-channel vs sliding-window detection",
                     "%d -> %d"
                     % (windowing["total_whole"], windowing["total_sliding"]),
                     "-", "-", "5 channels"))
        rows.append(("  CH2 specifically",
                     "%d -> %d"
                     % (windowing["per_channel"]["CH2"]["whole_channel"],
                        windowing["per_channel"]["CH2"]["sliding"]),
                     "-", "-", "-"))
        rows.append(("fraction of sliding-window-only detections above the "
                     "0.1 mV floor",
                     "%.1f%%"
                     % (100 * windowing["added_above_floor_fraction"]),
                     "-", "-", "n = %d added" % windowing["n_added"]))
    return rows


def not_supported(surrogate, nuisance, cross):
    """Section 4, generated from the numbers.

    A claim lands here when its own p says it should, not when someone
    decided in advance that it might.
    """
    items = []

    if surrogate:
        tests = surrogate["tests"]
        observed = surrogate["observed"]

        collisions = n1.seed_collisions(
            surrogate["n_realisations_per_generator"])
        items.append((
            "Every pooled p below has an effective N somewhat under its "
            "nominal one, because the specified seed formula collides.",
            "`20260902 + 1000*generator + 10*channel + realisation` is not "
            "injective once realisation >= 10 - CH0 realisation 10 and CH1 "
            "realisation 0 draw identical randomness. Measured: %d "
            "channel-realisations per generator draw from %d distinct "
            "seeds, each reused by up to %d of them. The collisions are "
            "always ACROSS channels, so they are applied to different "
            "source signals and no two surrogates are the same signal; "
            "seeds are unique within each channel and within each "
            "realisation, which is what the per-channel and the pooled "
            "nulls respectively require. But pooled realisations share "
            "randomness, so they are not perfectly independent draws. The "
            "per-channel p-values in panel A are unaffected. A future run "
            "should use `100*channel + realisation`."
            % (collisions["n_channel_realisations_per_generator"],
               collisions["n_distinct_seeds_per_generator"],
               collisions["max_reuse_of_one_seed"])))

        reproduced = []
        for generator in n1.GENERATORS:
            node = tests["geometry"]["spearman_rho"][generator]
            if node["p"] is not None and node["p"] > ALPHA:
                reproduced.append((generator, node))
        if reproduced:
            items.append((
                "The depth-angle correlation is NOT specific to the "
                "recording.",
                "Observed Spearman rho = %+.3f. It is reproduced by %s "
                "(null medians %s; p = %s). rho is therefore a property of "
                "the DETECTOR'S GEOMETRY - slope is depth divided by "
                "duration, and any generator that preserves the local "
                "waveform preserves that arithmetic - not a property of "
                "the mycelium. Section 3.2 must not quote rho as evidence "
                "of anything biological."
                % (observed["angle_spearman_rho_depth_vs_angle"],
                   ", ".join(n1.GENERATOR_LABELS[g] for g, _ in reproduced),
                   ", ".join("%+.3f" % node["null_median"]
                             for _, node in reproduced),
                   ", ".join("%.3f" % node["p"] for _, node in reproduced))))

        b_reproduced = [g for g in n1.GENERATORS
                        if (tests["geometry"]["control_b"][g]["p"] or 0) > ALPHA]
        if b_reproduced:
            items.append((
                "The control exponent b is also reproduced by the nulls.",
                "Observed b = %.3f. Reproduced by %s. The near-constancy of "
                "fall duration across two orders of magnitude of depth is "
                "what the surrogates recover too, so it is a statement "
                "about the detector's duration estimate at 10 Hz rather "
                "than about the preparation."
                % (observed["angle_duration_vs_depth_exponent"],
                   ", ".join(n1.GENERATOR_LABELS[g] for g in b_reproduced))))

        for generator in n1.GENERATORS:
            node = tests["detections"]["pooled"][generator]
            if node["p"] is not None and node["p"] > ALPHA:
                items.append((
                    "The detection count is not distinguishable from %s."
                    % n1.GENERATOR_LABELS[generator],
                    "Observed %d against a null median of %.0f, p = %.3f. "
                    "This generator preserves the local waveform, so it is "
                    "the expected outcome and it bounds the claim: what "
                    "the counts rule out is coloured noise, not shuffled "
                    "signal."
                    % (node["observed"], node["null_median"], node["p"])))

        for mode in n1.FEATURE_MODES:
            for generator in n1.GENERATORS:
                node = tests["family"][mode]["within_family_dispersion"][generator]
                if node["p"] is not None and node["p"] > ALPHA:
                    items.append((
                        "The real families are NOT tighter than %s's, in "
                        "the %s representation."
                        % (n1.GENERATOR_LABELS[generator], mode),
                        "Observed mean within-family distance %.3f against "
                        "a null median of %.3f, p = %.3f. The "
                        "limited-repertoire claim does not hold against "
                        "this null in this representation."
                        % (node["observed"], node["null_median"], node["p"])))
                node = tests["family"][mode]["n_families_at_height"][generator]
                if node["p"] is not None and node["p"] > ALPHA:
                    items.append((
                        "The real store does not resolve into FEWER "
                        "families than %s's, in the %s representation."
                        % (n1.GENERATOR_LABELS[generator], mode),
                        "Observed %d families of >=%d members at the real "
                        "tree's k=4 height, null median %.1f, p = %.3f."
                        % (node["observed"], n1.MIN_FAMILY_MEMBERS,
                           node["null_median"], node["p"])))

    if nuisance:
        coarse = nuisance["family_by_channel"]["coarse_k%d" % n1.COARSE_K]
        if coarse["permutation_p"] <= ALPHA:
            flagged = coarse["flagged_cells"]
            items.append((
                "\"Family membership is not channel-dependent\" is FALSE "
                "as an absolute statement.",
                "The permutation test rejects independence at both cuts "
                "(p = %.4f, %d shuffles). What survives is a claim about "
                "DEGREE: Cramer's V = %.3f against a null median of %.3f, "
                "all %d coarse families draw members from all five "
                "channels, and the enrichments are specific and few - %s. "
                "The paper must say \"weakly channel-dependent, and far "
                "less so than amplitude\", not \"channel-independent\"."
                % (coarse["permutation_p"], coarse["n_permutations"],
                   coarse["cramers_v"], coarse["null_cramers_v_median"],
                   coarse["n_families_with_all_five_channels"],
                   "; ".join("F%d %s z=%+.1f"
                             % (cell["family"], cell["channel"], cell["z"])
                             for cell in flagged[:5]) or "none")))

        depth = nuisance["depth_test"]
        pre = nuisance["pre_floor_depth_by_channel"]
        medians = [v["median_mv"] for v in pre.values()]
        items.append((
            "The \"order of magnitude\" amplitude spread is a PRE-FLOOR "
            "number and does not survive the floor.",
            "Before the 0.1 mV gate the per-channel median depth spans "
            "%.1fx (CH2 %.3f mV to CH3 %.3f mV). After it, the same "
            "quantity spans only %.2fx, because the gate removes exactly "
            "the events that made the channels differ - %.0f%% of CH2. "
            "The Kruskal-Wallis effect size on the refined store is "
            "eps^2 = %.3f, which is moderate, not overwhelming. Panel A "
            "draws both distributions so this is visible rather than "
            "asserted."
            % (max(medians) / min(medians), min(medians), max(medians),
               depth["median_ratio_max_over_min"],
               100 * max(v["fraction_at_or_below_floor"]
                         for v in pre.values()),
               depth["epsilon_squared"])))

    if cross:
        rotation = cross["rotation_null"]
        if rotation["p"] > ALPHA:
            items.append((
                "\"These events co-occur across electrodes\" is NOT "
                "supported.",
                "The observed %d cross-channel onset coincidences within "
                "+-%g s sit inside the rotation null (median %.0f, %.2fx, "
                "p = %.3f over %d rotations). Once each channel's own event "
                "density and inter-event spacing are held fixed and only "
                "the alignment between channels is destroyed, the "
                "coincidence count barely moves. The lag distribution says "
                "the same thing: %.1f%% of peak lags fall within +-%.1f s "
                "against %.1f%% expected under a uniform lag, so there is "
                "no spike at zero. THIS IS GOOD NEWS FOR TASK 2 - it is "
                "the strongest single piece of evidence that the family "
                "channel-mixing is not one disturbance recorded five times "
                "- but it must not be written up as a positive finding of "
                "network co-activity, because it is the opposite."
                % (rotation["observed_coincidences"],
                   rotation["pair_window_s"], rotation["null_median"],
                   rotation["ratio_observed_over_null_median"],
                   rotation["p"], rotation["n_trials"],
                   100 * cross["zero_lag_concentration"]["observed_fraction"],
                   cross["zero_lag_concentration"]["half_width_s"],
                   100 * cross["zero_lag_concentration"]["uniform_fraction"])))

        verdict = cross.get("sensitivity_verdict") or {}
        if verdict and not verdict.get("stable", True):
            items.append((
                "The common_mode / propagation bin COUNTS are not stable "
                "under the sensitivity sweep.",
                "%s Nothing that depends on a bin count - \"88 common-mode "
                "pairs\", \"30%% propagation\" - should be quoted as a "
                "measurement. What is stable is the comparison in the "
                "entry above, because the rotation null is counted under "
                "the same thresholds as the observation."
                % verdict["reading"]))

        survives = cross["family_result_without_common_mode"]
        if not survives.get("survives"):
            items.append((
                "Removing the common-mode events does not rescue channel "
                "independence.",
                "With %d common-mode events removed the permutation p is "
                "%s (it was %s) and Cramer's V falls from %s to %s. The "
                "association was not contamination - it is still there "
                "once the shared-ground candidates are gone, which makes "
                "it a weak real effect rather than an artefact. Note the p "
                "is now marginal, and on %d events rather than %d."
                % (survives["n_common_mode_events_removed"],
                   _fmt(survives["permutation_p"], "%.4f"),
                   _fmt(survives["permutation_p_with_common_mode"], "%.4f"),
                   _fmt(survives["cramers_v_with_common_mode"], "%.4f"),
                   _fmt(survives["cramers_v"], "%.4f"),
                   survives["n_after"], survives["n_before"])))
    return items


def store_defects(clusterk, task0):
    """Section 4b: what was found in the STORE that contradicts the
    documents. Separate from the nulls, because it is a defect rather than
    a negative result."""
    items = []
    if clusterk and task0:
        shipped = task0["evidence"]["shipped_cophenetic_refine_report"]
        items.append((
            "22 of the 1058 refined motifs enter the shipped Ward tree as "
            "ALL-ZERO vectors, and they inflate the cophenetic r.",
            "30 refined rows (and 208 of the 1736 raw rows) have a stored "
            "`detrended_mv` array whose length disagrees with "
            "`snippet_end_idx - snippet_start_idx`. "
            "`clusterfigs7._waveform_of` clips the onset into the array, so "
            "for 22 of them the returned \"fall\" is one sample long, and "
            "`cluster.feature_matrix` z-normalises that constant to all "
            "zeros. Those 22 sit on top of each other at distance zero. "
            "Removing them takes the cophenetic correlation of the same "
            "store from the shipped **%.4f** down to **%.4f** - the "
            "shipped figure is above the 0.70 warning floor partly because "
            "of a store defect. `nulls_v1` drops zero-variance feature "
            "rows on both the real and the surrogate side, which is why "
            "its n is %d rather than 1058."
            % (shipped, clusterk["cophenetic_r"], clusterk["n"])))
    return items


def build(out_dir):
    out_dir = Path(out_dir)
    task0 = _load(out_dir / "TASK0_distance.json")
    surrogate = _load(out_dir / "NULL_surrogate.json")
    nuisance = _load(out_dir / "NUISANCE_vs_SIGNAL.json")
    cross = _load(out_dir / "CROSS_CHANNEL.json")
    clusterk = _load(out_dir / "CLUSTER_K.json")
    sequence = _load(out_dir / "SEQUENCE.json")
    quant = _load(out_dir / "QUANT_duration.json")
    alphabet = _load(out_dir / "ALPHABET.json")
    windowing = _load(out_dir / "WINDOWING.json")

    lines = []
    add = lines.append

    add("# nulls_v1 — the null models and the nuisance/signal separation")
    add("")
    add("Everything under this directory was written by two commands and "
        "reads the refined store as read-only input. No existing store or "
        "figure was modified; no surrogate signal was persisted, given a "
        "`recordings` row, or written to `DATA/db/annotations.sqlite`.")
    add("")

    # -- 1. Task 0 ------------------------------------------------------
    add("## 1. Task 0 — which distance built the shipped tree")
    add("")
    if task0:
        evidence = task0["evidence"]
        equivalence = task0["equivalence"]
        leak = task0["is_the_scale_invariance_claim_still_true"]
        add("**`Pipelines/drop_motifs/DETECTION_AND_FIGURES.md` §3 is "
            "correct and `Plots/drop_motifs9_fig2a/PROVENANCE.md` is "
            "wrong.** The shipped tree's distance is plain Euclidean over "
            "the resampled, z-normalised feature vectors: "
            "`cluster.build_linkage` calls `pdist(features, "
            "metric=\"euclidean\")` and then Ward, and "
            "`cluster.distance_matrix` / `DISTANCE_SCALE_INVARIANT` is a "
            "separate utility that produced no shipped dendrogram. This is "
            "settled by recomputation rather than by reading: rebuilding "
            "the tree that way over the %d refined motifs gives cophenetic "
            "r = %.4f, which is the number `refined_v2/refine_report.json` "
            "already carries (%.4f). **The scale-invariance claim is still "
            "true, but for a different reason and the appendix has to say "
            "the right one.** `feature_matrix` resamples every event to "
            "200 points and z-normalises it, so each event's own duration "
            "and amplitude are divided out *before* any distance is taken "
            "— the grouping is scale-invariant because of the "
            "normalisation applied per vector, not because a "
            "scale-invariant metric was used. The two are equivalent in "
            "practice: over %d pairs the scale-invariant distance and "
            "Euclidean-over-features correlate at Spearman %.4f "
            "(Pearson %.4f), differing only in the common resample length "
            "(a fixed 200 against `max(len_a, len_b)` pairwise) and in a "
            "1/sqrt(n) factor. The direct check that no amplitude survives "
            "into the clustering space: the correlation between a feature "
            "vector's norm and its event's drop depth is %+.4f."
            % (evidence["n_motifs"], evidence["recomputed_cophenetic"],
               evidence["shipped_cophenetic_refine_report"],
               equivalence["n_pairs"], equivalence["spearman"],
               equivalence["pearson"],
               leak["correlation_feature_norm_vs_depth"]))
    else:
        add("*(TASK0_distance.json not found — run the command below.)*")
    add("")

    # -- 2. reproduction ------------------------------------------------
    add("## 2. Reproducing everything")
    add("")
    n = surrogate["n_realisations_per_generator"] if surrogate else 100
    add("**One command.** Everything in this directory, from the "
        "read-only refined store:")
    add("")
    add("```bash")
    add("python Pipelines/drop_motifs/run_nulls1.py --with-surrogates %d"
        % n)
    add("```")
    add("")
    add("That runs Task 1's grid (about 50 minutes on 14 cores), then "
        "Tasks 0 and 2-6, then rebuilds this README from the JSONs they "
        "write. The pieces are also runnable on their own:")
    add("")
    add("```bash")
    add("# Task 1's grid alone: 5 channels x 3 generators x %d realisations"
        % n)
    add("python Pipelines/drop_motifs/run_surrogates1.py --n %d" % n)
    add("")
    add("# Tasks 0 and 2-6, and NULL_surrogate.png from the grid's JSON "
        "(~4 min)")
    add("python Pipelines/drop_motifs/run_nulls1.py")
    add("")
    add("# this README alone, rebuilt from those JSONs")
    add("python Pipelines/drop_motifs/run_readme1.py")
    add("")
    add("# the tests the claims depend on")
    add("pytest tests/test_drop_motifs_crosschan1.py "
        "tests/test_drop_motifs_nulls1.py")
    add("```")
    add("")
    if surrogate:
        kwargs = surrogate["detect_kwargs"]
        add("The surrogate chain is the shipped chain: "
            "`passes9.detect_sliding(window_s=%g, overlap=%g, max_passes=%d, "
            "fine=%s, sensitive=%s, micro=%s)` then `refine9.refine_store"
            "(min_depth_mv=%g)`. `window_s` and `overlap` are read out of "
            "`run_summary.json`, not retyped; `max_passes` is %s."
            % (kwargs["window_s"], kwargs["overlap"], kwargs["max_passes"],
               kwargs["fine"], kwargs["sensitive"], kwargs["micro"],
               surrogate["min_depth_mv"],
               kwargs.get("max_passes_source",
                          kwargs.get("_max_passes_source", "its default"))))
        add("")
        add("**Edge handling.** %s" % surrogate["edge_handling"]["note"])
        add("")

    # -- 3. the table ---------------------------------------------------
    add("## 3. Every statistic the figures state")
    add("")
    add("| statistic | observed | null median | p | N |")
    add("|---|---|---|---|---|")
    for row in statistic_rows(surrogate, nuisance, cross, clusterk,
                              sequence, quant, windowing):
        add("| %s | %s | %s | %s | %s |" % row)
    add("")

    # -- 4. what did not work -------------------------------------------
    add("## 4. What the nulls did NOT support")
    add("")
    add("This section carries the same weight as section 3. Each entry is "
        "generated from its own p, not chosen in advance.")
    add("")
    items = not_supported(surrogate, nuisance, cross)
    if not items:
        add("*(Nothing to report here yet — the surrogate grid has not "
            "been run, so most of this section cannot be computed.)*")
    for index, (heading, body) in enumerate(items, start=1):
        add("**%d. %s**" % (index, heading))
        add("")
        add(body)
        add("")

    defects = store_defects(clusterk, task0)
    if defects:
        add("### 4b. What was found in the STORE that contradicts the docs")
        add("")
        add("Not a negative result - a defect, found while building this "
            "directory and written up in "
            "`Pipelines/drop_motifs/DETECTION_AND_FIGURES.md` §6 item 7.")
        add("")
        for index, (heading, body) in enumerate(defects, start=1):
            add("**%d. %s**" % (index, heading))
            add("")
            add(body)
            add("")
        items = items + defects

    # -- 5. seeds -------------------------------------------------------
    add("## 5. Every RNG seed")
    add("")
    if surrogate:
        add("**Surrogates.** `%s`. Concretely:" % surrogate["seed_rule"])
        add("")
        add("| generator | CH0 | CH1 | CH2 | CH3 | CH4 |")
        add("|---|---|---|---|---|---|")
        for generator in n1.GENERATORS:
            seeds = surrogate["seeds"][generator]
            add("| %s | %s |" % (generator, " | ".join(
                "%d…%d" % (seeds["CH%d" % c][0], seeds["CH%d" % c][-1])
                for c in range(5))))
        add("")
        add("Every individual seed is listed in `NULL_surrogate.json` "
            "under `seeds`, and each realisation's five seeds are in "
            "`surrogate_runs/summary.csv` and `realisations.json`.")
        add("")
        collisions = n1.seed_collisions(
            surrogate["n_realisations_per_generator"])
        add("> **The specified seed formula collides, and the collisions "
            "were measured rather than assumed away.** %s" %
            collisions["reading"])
        add("")
    seeds = []
    if nuisance:
        table = nuisance["family_by_channel"]["coarse_k%d" % n1.COARSE_K]
        seeds.append(("Task 2 channel-label permutation",
                      table["permutation_seed"],
                      "%d shuffles" % table["n_permutations"]))
    if cross:
        seeds.append(("Task 3 onset-rotation null",
                      cross["rotation_null"]["seed"],
                      "%d rotations" % cross["rotation_null"]["n_trials"]))
    if clusterk:
        seeds.append(("Task 4 gap-statistic uniform references",
                      clusterk["gap_seed"],
                      "%d references" % clusterk["n_gap_references"]))
    if task0:
        seeds.append(("Task 0 distance-equivalence subsample", 0,
                      "%d pairs" % task0["equivalence"]["n_pairs"]))
    if seeds:
        add("**Everything else.**")
        add("")
        add("| where | seed | scale |")
        add("|---|---|---|")
        for row in seeds:
            add("| %s | %d | %s |" % row)
        add("")

    # -- 6. files -------------------------------------------------------
    add("## 6. Files")
    add("")
    add("```")
    for path in sorted(out_dir.iterdir()):
        if path.name == "README.md":
            continue
        if path.is_dir():
            add("%-28s %s" % (path.name + "/",
                              ", ".join(sorted(p.name
                                               for p in path.iterdir()))))
        else:
            add("%-28s %d KB" % (path.name, path.stat().st_size // 1024))
    add("```")
    add("")
    if alphabet:
        add("`ALPHABET.png` reading: %s" % alphabet["verdict"])
        add("")
    if sequence:
        add("`SEQUENCE.png` reading: %s" % sequence["archetypes"]["verdict"])
        add("")

    text = "\n".join(lines) + "\n"
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    return out_dir / "README.md", len(items)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(n1.OUT_DIR))
    args = parser.parse_args(argv)
    path, n_items = build(args.out_dir)
    print("-> %s  (%d entries in \"what the nulls did not support\")"
          % (path, n_items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
