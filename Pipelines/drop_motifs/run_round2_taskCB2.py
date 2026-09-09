"""
run_round2_taskCB2.py
======================
Task C (is the partition real?) and Task B2 (does shape transfer across
electrodes?). Both read the corrected store and neither needs a surrogate,
so they run together.

    python Pipelines/drop_motifs/run_round2_taskCB2.py
    python Pipelines/drop_motifs/run_round2_taskCB2.py --bootstrap 50

Writes

    round2_v1/TASK_C_partition.json   round2_v1/PARTITION_validity.png
    round2_v1/TASK_B2_transfer.json   round2_v1/TRANSFER_matrix.png

WHICH CUT THESE ARE COMPUTED ON, AND WHY
-----------------------------------------
Ward / Euclidean at k = 4. NOT the cut Task A's rule selected.

Task A's rule selected average linkage at k = 2, and what that cut
actually is is 1092 events against 5 - one family plus five outliers.
Asking "is that partition stable?" of a 1092/5 split answers a question
nobody has: of course the 1092 stay together. Both tasks here are about
whether a MULTI-FAMILY partition of this store has any substance, so they
are computed on the four-family cut that every drop_motifs figure and all
of `nulls_v1` used.

That is a choice and it cuts against this round's own selection rule, so
it is stated in the JSON and in both figure captions rather than left for
a reader to infer. Task A's answer stands: no faithful tree of this store
resolves it into several populated families.
"""

import argparse
import json
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import pinned9

_SNAPSHOT_PATH, PROVENANCE = pinned9.activate()

from scipy.cluster.hierarchy import fcluster
from scipy.spatial.distance import pdist
from scipy.cluster.hierarchy import linkage

from Pipelines.drop_motifs import round2, round2figs1, validity2

CUT_METHOD = "ward"
CUT_METRIC = "euclidean"
CUT_K = 4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=round2.STORE)
    parser.add_argument("--out-dir", default=round2.OUT_DIR)
    parser.add_argument("--k", type=int, default=CUT_K)
    parser.add_argument("--random-partitions", type=int,
                        default=validity2.N_RANDOM_PARTITIONS)
    parser.add_argument("--bootstrap", type=int,
                        default=validity2.N_BOOTSTRAP)
    parser.add_argument("--transfer-permutations", type=int,
                        default=validity2.N_TRANSFER_PERMUTATIONS)
    args = parser.parse_args(argv)

    rows, features, amplitude, channel, waveforms, info = round2.load(
        args.store)
    print(f"store: {args.store}   n = {info['n_clustered']}")
    print(f"cut: {CUT_METHOD} / {CUT_METRIC}, k = {args.k}  "
          f"(NOT Task A's selected cut - see this module's docstring)\n")

    Z = linkage(pdist(features, metric=CUT_METRIC), method=CUT_METHOD)
    labels = fcluster(Z, args.k, criterion="maxclust")

    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- C --
    print("Task C")
    random_null = validity2.random_partition_null(
        features, labels, n=args.random_partitions)
    p = max(random_null["p"], random_null["p_floor"])
    print(f"  random-partition null: real "
          f"{random_null['observed']:.4f} vs null median "
          f"{random_null['null_median']:.4f}  "
          f"p {'<=' if random_null['at_p_floor'] else '='} {p:.4f}")
    print(f"    -> the tree "
          f"{'DID' if random_null['p'] < 0.05 else 'did NOT'} find "
          f"structure a random grouping of the same sizes does not have")

    coassociation, stability = validity2.bootstrap_coassociation(
        features, args.k, method=CUT_METHOD, metric=CUT_METRIC,
        n=args.bootstrap, reference_labels=labels)
    print(f"  bootstrap co-association ({args.bootstrap} resamples): "
          f"within {stability['mean_within_family_coassociation']:.3f}, "
          f"between {stability['mean_between_family_coassociation']:.3f}, "
          f"separation {stability['separation']:.3f}")
    for family, entry in sorted(stability["per_family_stability"].items()):
        print(f"    F{family}  n = {entry['n']:4d}  "
              f"stability {entry['stability']:.3f}")

    figure_c = round2figs1.plot_partition_validity(
        random_null, coassociation, stability, labels,
        out / "PARTITION_validity.png")
    print(f"  -> {figure_c}")

    payload_c = {
        "task": "Task C - is the partition real, or is it just a cut?",
        "detector_provenance": PROVENANCE,
        "store": info,
        "cut": {"method": CUT_METHOD, "metric": CUT_METRIC, "k": args.k,
                "why_not_task_A_selected_cut": (
                    "Task A's rule selected average/euclidean at k=2, whose "
                    "cut is 1092 events against 5 - one family plus five "
                    "outliers. Stability and transfer are questions about a "
                    "multi-family partition, so both are computed on the "
                    "Ward k=4 cut every earlier figure and all of nulls_v1 "
                    "used. Task A's verdict is unchanged.")},
        "random_partition_null": random_null,
        "bootstrap": stability,
        "the_50s_block_shuffle_reframed": {
            "round1_result": ("real families are NOT tighter than a 50 s "
                              "block shuffle's: 2.3424 vs 2.3461, p = 0.475"),
            "why_that_is_a_bound_and_not_a_refutation": (
                "A 50 s block shuffle preserves every waveform inside a "
                "block; it moves blocks in time and leaves their contents "
                "alone. The set of shapes it produces is therefore very "
                "nearly the set of shapes in the recording, so it cannot "
                "be a null for 'is there a shape repertoire' - it contains "
                "the repertoire by construction. It is a null for 'does "
                "the ORDER of events matter', and its answer is that it "
                "does not. That is consistent with shape being the "
                "invariant rather than evidence against it. The bound this "
                "leaves is real and should be stated: these data cannot "
                "distinguish a repertoire from a waveform-preserving "
                "reshuffling of one."),
        },
        "figure": figure_c,
    }
    (out / "TASK_C_partition.json").write_text(
        json.dumps(payload_c, indent=2, default=float), encoding="utf-8")

    # --------------------------------------------------------------- B2 --
    print("\nTask B2")
    channels = sorted(set(channel.tolist()))
    matrix, adjusted, detail, own = validity2.transfer(
        features, channel, args.k, method=CUT_METHOD, metric=CUT_METRIC,
        n_permutations=args.transfer_permutations, channels=channels)

    print("  ARI transfer matrix (rows = shapes learned on, "
          "columns = applied to):")
    header = "        " + "".join(f"   ->CH{c}  " for c in channels)
    print(header)
    for i, a in enumerate(channels):
        cells = "".join(
            "     -    " if i == j or not np.isfinite(matrix[i, j])
            else f"  {matrix[i, j]:+.3f}  " for j in range(len(channels)))
        print(f"  CH{a}  {cells}")

    medoid_waveforms = {
        c: [features[i] for i in own[c]["medoid_indices"]]
        for c in channels if own[c]["medoid_indices"] is not None}

    figure_b2 = round2figs1.plot_transfer(
        matrix, adjusted, detail, medoid_waveforms,
        out / "TRANSFER_matrix.png", channels=channels, k=args.k)
    print(f"  -> {figure_b2}")

    # CH2 gets its own paragraph because it is the channel a reviewer will
    # ask about: it failed the AAFT detection null, it is the only one with
    # ISI CV > 1, and the floor removed 77% of it.
    ch2 = {"as_source": {}, "as_target": {}}
    for key, entry in detail.items():
        if entry["source_channel"] == 2:
            ch2["as_source"][key] = entry["ari"]
        if entry["target_channel"] == 2:
            ch2["as_target"][key] = entry["ari"]
    others = [e["ari"] for e in detail.values()
              if 2 not in (e["source_channel"], e["target_channel"])]
    ch2_note = {
        "mean_ari_as_source": float(np.mean(list(ch2["as_source"].values())))
        if ch2["as_source"] else float("nan"),
        "mean_ari_as_target": float(np.mean(list(ch2["as_target"].values())))
        if ch2["as_target"] else float("nan"),
        "mean_ari_pairs_not_involving_CH2": float(np.mean(others))
        if others else float("nan"),
        "n_events": int(info["n_per_channel"].get(2, 0)),
    }
    ch2_note["behaves_differently"] = bool(
        np.isfinite(ch2_note["mean_ari_as_target"])
        and np.isfinite(ch2_note["mean_ari_pairs_not_involving_CH2"])
        and abs(ch2_note["mean_ari_as_target"]
                - ch2_note["mean_ari_pairs_not_involving_CH2"]) > 0.05)
    print(f"\n  CH2: mean ARI as source "
          f"{ch2_note['mean_ari_as_source']:.3f}, as target "
          f"{ch2_note['mean_ari_as_target']:.3f}, "
          f"pairs without CH2 "
          f"{ch2_note['mean_ari_pairs_not_involving_CH2']:.3f}  "
          f"-> {'DIFFERENT' if ch2_note['behaves_differently'] else 'in line'}")

    payload_b2 = {
        "task": "Task B2 - cross-electrode family transfer",
        "detector_provenance": PROVENANCE,
        "store": info,
        "cut": payload_c["cut"],
        "channels": channels,
        "ari_matrix": matrix.tolist(),
        "ari_minus_null_median_matrix": adjusted.tolist(),
        "pairs": detail,
        "ch2": ch2_note,
        "n_permutations": args.transfer_permutations,
        "seed_rule": ("SEED_BASE + 100*target_channel + source_channel, so "
                      "no two ordered pairs share a stream"),
        "figure": figure_b2,
    }
    (out / "TASK_B2_transfer.json").write_text(
        json.dumps(payload_b2, indent=2, default=float), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
