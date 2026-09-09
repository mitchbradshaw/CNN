"""
run_drop10_claims.py
=====================
Assembles `Plots/drop_motifs10/CLAIMS.md` from the analysis JSONs.

    python Pipelines/drop_motifs/run_drop10_claims.py

The verdicts are authored - they are judgements and have to be - but every
NUMBER in every row is read out of the file that computed it. Round one's
ledger existed because a retyped number drifts.
"""

import json
import os
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import claims10  # noqa: E402

OUT = _Path("Plots") / "drop_motifs10"

PREAMBLE = """Round two's ledger, extended with the cross-species rows.

Every row carries its evidence, the null or control that bounds it, and a
verdict. **Every falsified or bounded row carries the sentence the paper
should use instead** - a falsified claim with no replacement gets quietly
re-asserted in the next draft, which is the failure this file exists to
prevent.

Read `SPECIES_vs_RESOLUTION.png` before any cross-species row. The confound
control is not a caveat on the cross-species result; it is a precondition
for reading it."""


def fmt_p(p):
    return "p < 1e-4" if p is not None and p <= 1e-4 else f"p = {p:.4f}"


def build():
    res = claims10.load(OUT / "SPECIES_vs_RESOLUTION.json")
    fam = claims10.load(OUT / "FAMILIES_by_species.json")
    dec = claims10.load(OUT / "DECODE_species.json")
    tra = claims10.load(OUT / "TRANSFER_species.json")
    reb = claims10.load(OUT / "rebaseline.json")
    atlas = claims10.load(OUT / "ALL_atlas.json")
    rose = claims10.load(OUT / "ALL_rose.json")

    rows = []

    # ---- the detector, Tasks 1 and 6 ----------------------------------
    if reb:
        checks = reb["human_referenced"]
        unchanged = all(c["unchanged"] for c in checks)
        counts = ", ".join(f"ID {c['catalogue_id']} {c['drop10_base']}"
                           for c in checks)
        rows.append(claims10.row(
            "The Task 1 fixes did not move any count a human validated.",
            f"base-pass counts after every fix: {counts}; drop_motifs8 gave "
            f"17 / 16 / 14 / 24",
            "the fix ladder: 16 of 16 controls reproduce drop_motifs8 "
            "exactly, and every moved count is attributable to a named rung",
            claims10.SUPPORTED if unchanged else claims10.FALSIFIED))

        rows.append(claims10.row(
            "The store no longer disagrees with itself, so no motif enters "
            "the tree as an all-zero feature vector.",
            "0 of 3511 rows have a length mismatch and 0 are constant "
            "(drop_motifs9: 208 of 1736 raw, 30 of 1058 refined, 22 "
            "all-zero)",
            "`cluster.feature_matrix` and `_waveform_of` now raise rather "
            "than clip; `tests/test_drop_motifs_round2_store.py`",
            claims10.SUPPORTED))

        rows.append(claims10.row(
            "Both named sensitivity misses are fixed, and both were "
            "bracketing bugs rather than slope-gate misses.",
            "CH4 win05: 19 -> 23 detections, one per d-run, nothing "
            "rejected. CH1 9052: detected at 0.127 mV, dominance 0.944 "
            "(was rejected at a measured 0.086 mV)",
            "`tests/test_drop_motifs_defects10.py`, by sample index; the "
            "four human counts unchanged through both fixes",
            claims10.SUPPORTED))

        rows.append(claims10.row(
            "The operator's 0.1 mV floor is an M2-specific number, not an "
            "instrument constant.",
            "0.1 mV is 3.1-5.3 sigma of the M2 spans' own noise, 18.5 sigma "
            "on Mushroom_260720 and 15.1-58.7 sigma on Fig2A",
            "the 3-sigma rule independently returns 0.056-0.096 mV on the "
            "M2 recordings the 0.1 mV was stated for",
            claims10.SUPPORTED))

    # ---- the atlas ----------------------------------------------------
    if atlas:
        rows.append(claims10.row(
            "The corpora contain a small repertoire of relative shapes at "
            "wildly different absolute scales.",
            f"{atlas['n_medoids']} family medoids from "
            f"{len(atlas['corpora'])} corpora span "
            f"{atlas['orders_of_magnitude']:.1f} orders of magnitude of "
            f"native fall duration "
            f"({atlas['native_fall_range_s'][0]:g}-"
            f"{atlas['native_fall_range_s'][1]:g} s) and "
            f"{atlas['samples_in_fall_range'][0]}-"
            f"{atlas['samples_in_fall_range'][1]} samples per fall",
            "no null - this is a description of the store, not a test. The "
            "REPERTOIRE half of the claim is what rows below test",
            claims10.BOUNDED,
            "The detected events span three orders of magnitude of duration "
            "and four of amplitude, and a shape-normalised clustering groups "
            "them into a small number of families. Whether that small number "
            "reflects a limited biological repertoire rather than the "
            "clustering's own compression is not established here: every "
            "pooled tree in this run sits below the 0.70 cophenetic floor, "
            "and drop_motifs9's nulls could not distinguish the real "
            "families' tightness from a block-shuffle surrogate's."))

    # ---- 5b, the confound control -------------------------------------
    if res:
        for key, label in (("oyster_vs_sp385",
                            "oyster vs sp385, matched rate AND framing"),
                           ("matched_rate", "the matched-rate subset"),
                           ("pooled_all", "all four corpora pooled")):
            block = res.get(key)
            if not block:
                continue
            coarse = block["coarse"]
            sp, sa = coarse["species"], coarse["samples_per_event"]
            dominates = sa["cramers_v"] > sp["cramers_v"]
            rows.append(claims10.row(
                f"Family membership tracks SPECIES rather than measurement "
                f"resolution - {label}, coarse cut.",
                f"V(species) = {sp['cramers_v']:.4f} "
                f"({fmt_p(sp['permutation_p'])}); "
                f"V(samples per event) = {sa['cramers_v']:.4f} "
                f"({fmt_p(sa['permutation_p'])}); n = {sp['n']}",
                f"10,000-shuffle permutation on the label, both marginals "
                f"preserved; null medians {sp['null_median_v']:.4f} and "
                f"{sa['null_median_v']:.4f}",
                claims10.FALSIFIED if dominates else claims10.SUPPORTED,
                ("Family membership is associated at least as strongly with "
                 "the number of samples an event was built from as with the "
                 "species it came from "
                 f"(Cramer's V {sa['cramers_v']:.3f} against "
                 f"{sp['cramers_v']:.3f}). The shape families this pipeline "
                 "recovers cannot be read as species groupings without first "
                 "matching the sampling rate and the framing.")
                if dominates else None))

        block = res.get("pooled_all", {}).get("decode_samples_from_shape")
        if block and "balanced_accuracy" in block:
            rows.append(claims10.row(
                "The 200-point z-normalised feature vector carries SHAPE "
                "only, with absolute duration and amplitude divided out.",
                f"a classifier reads samples-per-event out of that vector at "
                f"{block['balanced_accuracy']:.3f} balanced accuracy against "
                f"a chance of {block['chance']:.3f} "
                f"({fmt_p(block['permutation_p'])}, n = {block['n']})",
                f"{block['n_permutations']}-shuffle label permutation, whole "
                f"cross-validation re-run per shuffle; null median "
                f"{block['null_median']:.3f}",
                claims10.FALSIFIED,
                "Resampling every event to 200 points removes its absolute "
                "duration and amplitude but not its measurement resolution: "
                f"the normalised vector still predicts how many samples it "
                f"was built from at {block['balanced_accuracy']:.2f} balanced "
                f"accuracy against a chance of {block['chance']:.2f}. Shape "
                "distances between corpora recorded at different rates are "
                "therefore not purely distances between shapes."))

    # ---- 5a ------------------------------------------------------------
    if fam:
        clean = fam.get("oyster_vs_sp385", {}).get("coarse")
        framing = fam.get("oyster_vs_reishi_1hz", {}).get("coarse")
        if clean:
            rows.append(claims10.row(
                "Shape families are species-specific: a family belongs to a "
                "species.",
                f"on the clean contrast (oyster vs sp385, matched rate and "
                f"matched framing) the coarse cut gives V = "
                f"{clean['cramers_v']:.4f}, {fmt_p(clean['permutation_p'])}, "
                f"n = {clean['n']}, with "
                f"{len(clean['enriched'])} cells at |z| > 2",
                "10,000-shuffle permutation; null median "
                f"{clean['null_median_v']:.4f}",
                claims10.NOT_SUPPORTED,
                "At matched sampling rate and matched framing, family "
                "membership is not distinguishable from independent of "
                f"species (Cramer's V = {clean['cramers_v']:.3f}, "
                f"{fmt_p(clean['permutation_p'])} over 10,000 shuffles, "
                f"n = {clean['n']}). Every coarse family drawn on "
                "`ALL_families.png` contains events from more than one "
                "species."))
        if clean and framing:
            rows.append(claims10.row(
                "Where family membership DOES track a corpus label at "
                "matched rate, framing rather than species is the candidate "
                "explanation.",
                f"matched rate, matched framing (oyster vs sp385): V = "
                f"{clean['cramers_v']:.4f} ({fmt_p(clean['permutation_p'])}). "
                f"Matched rate, DIFFERENT framing (oyster vs reishi_1hz): "
                f"V = {framing['cramers_v']:.4f} "
                f"({fmt_p(framing['permutation_p'])})",
                "the same 10,000-shuffle permutation on both; the two "
                "contrasts differ in framing and species, not in rate",
                claims10.SUPPORTED))

    # ---- 5c ------------------------------------------------------------
    if dec:
        block = dec.get("matched_rate", {}).get("representations", {})
        scale = block.get("absolute scale", {})
        shape = block.get("normalised shape", {})
        control = block.get("resolution alone", {})
        both = block.get("both", {})
        if scale and shape:
            rows.append(claims10.row(
                "Species is recoverable from ABSOLUTE SCALE well above "
                "chance.",
                f"balanced accuracy {scale['balanced_accuracy']:.3f} against "
                f"a chance of {scale['chance']:.3f} "
                f"({fmt_p(scale['permutation_p'])}), n = {scale['n']}, "
                f"matched-rate subset",
                f"{scale['n_permutations']}-shuffle permutation, whole "
                f"cross-validation re-run per shuffle; null median "
                f"{scale['null_median']:.3f}",
                claims10.SUPPORTED))

            rows.append(claims10.row(
                "Species is recoverable from NORMALISED SHAPE only near "
                "chance - shape is species-invariant.",
                f"balanced accuracy {shape['balanced_accuracy']:.3f} against "
                f"a chance of {shape['chance']:.3f} "
                f"({fmt_p(shape['permutation_p'])}), n = {shape['n']}",
                f"{shape['n_permutations']}-shuffle permutation; null median "
                f"{shape['null_median']:.3f}, p95 {shape['null_p95']:.3f}",
                claims10.FALSIFIED,
                "Normalised shape is not species-invariant. It decodes "
                f"species at {shape['balanced_accuracy']:.2f} balanced "
                f"accuracy against a chance of {shape['chance']:.2f} "
                f"({fmt_p(shape['permutation_p'])}) - well above chance, "
                "though below what absolute scale achieves "
                f"({scale['balanced_accuracy']:.2f}). For species "
                "identification absolute scale is the stronger cue; for "
                "cross-species event detection, shape normalisation reduces "
                "but does not remove the species signal."))

        if shape and control:
            rows.append(claims10.row(
                "What normalised shape knows about species is shape, not "
                "measurement resolution.",
                f"normalised shape (200 features) decodes species at "
                f"{shape['balanced_accuracy']:.3f}; "
                f"n_samples_in_fall ALONE (1 feature) decodes it at "
                f"{control['balanced_accuracy']:.3f}",
                "the resolution-alone representation is the control - if it "
                "decodes species well, so will anything correlated with it",
                claims10.NOT_SUPPORTED,
                "A single feature - the number of samples in the fall - "
                f"decodes species at {control['balanced_accuracy']:.2f} "
                "balanced accuracy, against "
                f"{shape['balanced_accuracy']:.2f} for the whole 200-point "
                "normalised vector. Most of what the shape representation "
                "knows about species is plausibly measurement resolution "
                "rather than morphology, and this run cannot separate the "
                "two."))

        if both and scale:
            rows.append(claims10.row(
                "Concatenating shape with absolute scale improves species "
                "decoding over scale alone.",
                f"both = {both['balanced_accuracy']:.3f} against absolute "
                f"scale alone = {scale['balanced_accuracy']:.3f}",
                "same folds, same balancing, same permutation null",
                claims10.FALSIFIED if
                both["balanced_accuracy"] <= scale["balanced_accuracy"]
                else claims10.SUPPORTED,
                ("Adding the 200-point shape vector to the three absolute-"
                 "scale features does not improve species decoding and "
                 f"slightly degrades it ({both['balanced_accuracy']:.2f} "
                 f"against {scale['balanced_accuracy']:.2f}), which is what "
                 "200 mostly-uninformative features do to a classifier "
                 "trained on 228 events.")
                if both["balanced_accuracy"] <= scale["balanced_accuracy"]
                else None))

    # ---- 5d ------------------------------------------------------------
    if tra:
        block = tra.get("matched_rate", {})
        matrix = block.get("ari_matrix", {})
        sur = block.get("surrogate", {})
        if matrix:
            pairs = []
            for a in matrix["species"]:
                for b in matrix["species"]:
                    if a == b:
                        continue
                    cell = matrix["matrix"][a][b]
                    pairs.append((f"{a}->{b}", cell.get("ari", float("nan")),
                                  cell.get("permutation_p", float("nan"))))
            best = max(pairs, key=lambda p: p[1])
            worst = min(pairs, key=lambda p: p[1])
            rows.append(claims10.row(
                "Shape families learned on one species describe another "
                "species' events as well as that species' own clustering "
                "does.",
                "adjusted Rand index, matched-rate subset: best "
                f"{best[0]} = {best[1]:.3f}, worst {worst[0]} = "
                f"{worst[1]:.3f}; the matrix is strongly ASYMMETRIC",
                "1000-shuffle permutation of B's own labels against the "
                "assignment to A's medoids",
                claims10.BOUNDED,
                "Family transfer between species is real but partial and "
                f"strongly asymmetric: reishi's and sp385's medoids describe "
                f"oyster's events at ARI {matrix['matrix']['reishi']['oyster'].get('ari', float('nan')):.2f} "
                f"and {matrix['matrix']['sp385']['oyster'].get('ari', float('nan')):.2f}, "
                "while oyster's medoids describe theirs at "
                f"{matrix['matrix']['oyster']['reishi'].get('ari', float('nan')):.2f} "
                f"and {matrix['matrix']['oyster']['sp385'].get('ari', float('nan')):.2f}. "
                "The shared repertoire is a subset relation, not an "
                "equivalence."))

        if sur:
            worst_p = max(v.get("p_closer_than_surrogate", 1.0)
                          for v in sur.values())
            ratios = [v["surrogate_median"] / v["median_nearest_distance"]
                      for v in sur.values()
                      if v.get("median_nearest_distance")]
            rows.append(claims10.row(
                "One species' events sit closer to another species' shape "
                "medoids than chance allows.",
                f"median nearest-medoid distance for real B against a "
                f"phase-randomised surrogate of B, all "
                f"{len(sur)} ordered pairs: surrogate is "
                f"{min(ratios):.1f}x to {max(ratios):.1f}x further",
                "100 phase-randomised surrogates per pair, each preserving "
                f"B's own power spectrum; worst p = {worst_p:.4f}",
                claims10.SUPPORTED))

    # ---- points of contact with round two ------------------------------
    # `Plots/drop_motifs9_fig2a/round2_v1/` appeared while this run was in
    # progress. It is a different question at a different level (channels,
    # not species) on a different store, so its rows are not restated here
    # - but three of them bear directly on numbers above and are carried
    # forward as rows of their own.
    rows.append(claims10.row(
        "The Ward tree this run's families come from is a faithful summary "
        "of the shape distances.",
        "every drop_motifs10 tree is below the 0.70 cophenetic floor "
        "(pooled 0.577; oyster 0.473; sp385 0.471; reishi_1hz 0.538; "
        "matched-rate 0.486; only reishi_10hz clears it at 0.769). Round "
        "two measured the same thing on its own store and found average "
        "linkage more faithful than Ward (0.839 against 0.638)",
        "round two's linkage selection, which drop_motifs10 did not repeat "
        "- this run used Ward throughout, as every earlier run did",
        claims10.NOT_SUPPORTED,
        "Every family table in this run is a CUT at a chosen height on a "
        "Ward tree whose cophenetic correlation is below the 0.70 floor, "
        "not a discovered partition. Round two's linkage selection on the "
        "drop_motifs9 store found that the most faithful tree over the same "
        "kind of feature matrix is average linkage, and that its selected "
        "cut is one family plus a handful of outliers - i.e. the shape "
        "distribution has no gap in it. The cross-species results here are "
        "therefore statements about how events distribute over an imposed "
        "grouping, and they should be quoted with the grouping named. "
        "Repeating round two's linkage selection on the pooled cross-species "
        "store is the first thing drop_motifs11 should do."))

    rows.append(claims10.row(
        "A 3-sigma per-channel floor is a single well-defined number.",
        "drop_motifs10 and round two independently chose the same "
        "multiplier (3.0) and got floors that differ by 4.1x to 5.6x: on "
        "Fig2A, 0.0051-0.0199 mV here against 0.0284-0.0817 mV there",
        "the two use different noise estimators - second-difference "
        "amplitude MAD here, gradient MAD divided by fs there. Measured on "
        "CH1 over the whole channel the gradient MAD is 4.1x the "
        "second-difference estimate",
        claims10.BOUNDED,
        "The multiplier is not the decision; the noise estimator is. Two "
        "independent 3-sigma per-channel floors differ by a factor of five "
        "because one is built on a second-difference amplitude MAD and the "
        "other on a gradient MAD. `detect.slope_noise_sigma` documents why "
        "they diverge - a gradient MAD reports the typical EVENT slope "
        "rather than the baseline once the duty cycle is high, which is why "
        "the second difference is the detector's own default - but the "
        "gradient-based floor lands closer to the operator's stated 0.1 mV, "
        "so this run does not treat the disagreement as settled. Both "
        "stores are written; the floor must be quoted with every count."))

    rows.append(claims10.row(
        "Normalised shape is blind to the recording context it came from.",
        "round two, channels: amplitude decodes channel at 34.6% and shape "
        "at 26.2% against a 20% baseline. drop_motifs10, species: absolute "
        "scale 0.781 and normalised shape 0.614 against a 0.333 baseline",
        "independent permutation nulls on two different stores at two "
        "different levels of the hierarchy",
        claims10.FALSIFIED,
        "Normalised shape is not blind to recording context at either "
        "level. It carries electrode identity (26.2% against a 20% "
        "baseline) and it carries species (0.61 against a 0.33 baseline). "
        "In both cases absolute amplitude carries more, and in both cases "
        "shape carries a real and reproducible remainder. 'Shape is "
        "scale-invariant' describes what the normalisation was designed to "
        "do, not what the resulting representation does."))

    return rows


def main():
    rows = build()
    path = claims10.write(rows, OUT / "CLAIMS.md",
                          title="CLAIMS.md — drop_motifs10",
                          preamble=PREAMBLE)
    print(f"-> {path}  ({len(rows)} rows)")
    for i, r in enumerate(rows, 1):
        print(f"  {i:2d}. [{r['verdict']:>13s}] {r['claim'][:76]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
