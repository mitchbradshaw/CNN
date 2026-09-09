"""
run_round2_taskA.py
====================
Task A steps 3-4: re-report every descriptive clustering number on the
CORRECTED store, and decide the linkage by the rule `tree2` states above
its own code.

    python Pipelines/drop_motifs/run_round2_taskA.py

Reads `round2_v1/motifs` (written by `run_round2_store.py`). Writes

    round2_v1/TASK_A_tree.json
    round2_v1/ALL_dendrogram.png
    round2_v1/ALL_families.png
    round2_v1/LINKAGE_selection.png

TWO family tables are reported, and the difference between them matters.

  THE SELECTED CUT is whatever `tree2`'s rule picks. It is the one the
  paper should quote, and it comes with its own degeneracy diagnostic.

  THE LEGACY CUT is Ward on Euclidean at k = 4 - what every drop_motifs
  figure from 6 onward used, and what `nulls_v1` computed its tightness and
  Cramer's V against. It is reported so the round-1 numbers stay comparable
  and so the change is visible as a difference rather than as a silence. It
  is NOT a recommendation.
"""

import json
import os
import sys
from pathlib import Path as _Path

import numpy as np
from scipy.cluster.hierarchy import fcluster
from scipy.spatial.distance import pdist
from scipy.stats import chi2_contingency

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# THE PIN GOES FIRST, and `round2` must not be imported above it.
#
# `Working/Detection/drop_motifs/cluster.py` is shared and drop_motifs10 has
# modified it. `cluster.feature_matrix` and `cluster.build_linkage` are what
# produce every number in this file - the feature matrix, the cophenetic
# correlation, the whole linkage grid - so importing the working tree's copy
# would make Task A a measurement of drop_motifs10's clustering rather than
# of the corrected drop_motifs9 store. `round2` imports both `cluster` and
# `clusterfigs7` at module scope, so it has to come after `activate()`.
#
# `activate()` evicts anything already imported from those packages, so
# importing `pinned9` by its normal name above is safe: the package object
# it creates is thrown away and rebuilt against the snapshot.
from Pipelines.drop_motifs import pinned9

_SNAPSHOT_PATH, PROVENANCE = pinned9.activate()

from Pipelines.drop_motifs import round2, round2figs1, tree2
from Working.Detection.drop_motifs import cluster as dc

LEGACY_K = 4
FINE_K = 10


def cramers_v(labels, channel):
    """Family x channel association, the same statistic `nulls_v1` used."""
    families = sorted(set(np.asarray(labels).tolist()))
    channels = sorted(set(np.asarray(channel).tolist()))
    table = np.array([[int(np.sum((labels == f) & (channel == c)))
                       for c in channels] for f in families], dtype=float)
    keep = table.sum(axis=1) > 0
    table = table[keep]
    if table.shape[0] < 2 or table.shape[1] < 2:
        return float("nan"), table
    chi2 = chi2_contingency(table)[0]
    n = table.sum()
    return float(np.sqrt(chi2 / (n * (min(table.shape) - 1)))), table


def main():
    print(f"pinned detector/clustering: {_SNAPSHOT_PATH}")
    print(f"  cluster.py from commit {PROVENANCE['commit']}: "
          f"{'Working/Detection/drop_motifs/cluster.py' in PROVENANCE['pinned_to_commit']}")

    rows, features, amplitude, channel, waveforms, info = round2.load()
    print(f"corrected store: n = {info['n_clustered']} "
          f"({info['n_zero_variance_dropped']} zero-variance dropped)")
    print(f"  per channel: {info['n_per_channel']}")

    # -- the grid, then the rule -------------------------------------------
    cells = tree2.linkage_grid(features)
    print("\nlinkage grid (rule stated in tree2's docstring, fixed first):")
    for cell in sorted(cells, key=lambda c: -c["cophenetic_r"]):
        shape = cell["cut_shape_at_selected_k"]
        print(f"  {cell['method']:9s} {cell['metric']:12s} "
              f"coph r = {cell['cophenetic_r']:.4f}  "
              f"k = {cell['selected_k']:2d}  "
              f"sil = {cell['silhouette_at_selected_k']:.4f}  "
              f"sizes = {shape['sizes'][:5]}"
              f"{'  [INVALID]' if cell['method_invalid'] else ''}"
              f"{'  [DEGENERATE]' if shape['degenerate'] else ''}")

    winner, verdict = tree2.choose(cells)
    print(f"\nSELECTED: {verdict['selected']['method']} / "
          f"{verdict['selected']['metric']}, k = {verdict['selected']['k']}, "
          f"cophenetic r = {verdict['selected']['cophenetic_r']:.4f}")
    print(f"  clears the {verdict['cophenetic_floor']} floor: "
          f"{verdict['clears_floor']}")
    if verdict.get("degeneracy_warning"):
        print(f"  ! {verdict['degeneracy_warning']}")
    if verdict.get("finding"):
        print(f"  ! {verdict['finding']}")

    selected_labels = fcluster(winner["_Z"], verdict["selected"]["k"],
                               criterion="maxclust")

    # -- the legacy cut, for comparability with round one ------------------
    legacy = next(c for c in cells
                  if c["method"] == "ward" and c["metric"] == "euclidean")
    legacy_labels = fcluster(legacy["_Z"], LEGACY_K, criterion="maxclust")
    fine_labels = fcluster(legacy["_Z"], FINE_K, criterion="maxclust")

    tables = {
        "selected": round2.family_table(rows, selected_labels, features),
        "legacy_ward_k4": round2.family_table(rows, legacy_labels, features),
        "legacy_ward_k10": round2.family_table(rows, fine_labels, features),
    }

    print(f"\nlegacy cut (Ward / Euclidean, k = {LEGACY_K}) — for "
          f"comparability with nulls_v1, not a recommendation:")
    for entry in tables["legacy_ward_k4"]:
        print(f"  F{entry['family']}  n = {entry['n']:4d}  "
              f"median {entry['median_depth_mv']:.3f} mV, "
              f"{entry['median_fall_s']:.2f} s  "
              f"channels {entry['channels']}  "
              f"({entry['n_channels_held']} of 5)")

    v4, _ = cramers_v(legacy_labels, channel)
    v10, _ = cramers_v(fine_labels, channel)
    vsel, _ = cramers_v(selected_labels, channel)
    tight4 = round2.within_family_distance(features, legacy_labels)
    tight_sel = round2.within_family_distance(features, selected_labels)

    print(f"\n  Cramer's V, legacy k=4:  {v4:.4f}  (nulls_v1: 0.1145)")
    print(f"  Cramer's V, legacy k=10: {v10:.4f}  (nulls_v1: 0.1459)")
    print(f"  mean within-family distance, legacy k=4: {tight4:.4f}  "
          f"(nulls_v1 real: 2.3424, AAFT null median 2.7273)")

    # -- does Task A move the tightness statistic past the null's IQR? -----
    # The brief's gate on re-running the 50-minute surrogate grid: only if
    # the corrected real-side statistic moves by more than the null's
    # interquartile range. Answered here, in the run, rather than by eye.
    null_iqr = _aaft_tightness_iqr()
    delta = abs(tight4 - 2.3424)
    rerun = bool(null_iqr is not None and delta > null_iqr)
    print(f"\n  surrogate-grid re-run gate: |{tight4:.4f} - 2.3424| = "
          f"{delta:.4f} vs AAFT null IQR = "
          f"{'n/a' if null_iqr is None else f'{null_iqr:.4f}'}"
          f"  ->  {'RE-RUN NEEDED' if rerun else 'no re-run needed'}")

    # -- figures -----------------------------------------------------------
    out = _Path(round2.OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)

    paths = {}
    paths["linkage"] = round2figs1.plot_linkage_selection(
        cells, verdict, out / "LINKAGE_selection.png")
    print(f"\n-> {paths['linkage']}")

    # The dendrogram and the atlas are drawn on the LEGACY Ward tree at the
    # selected k where that is meaningful, and on the selected tree
    # otherwise. Here the selected cut is drawn on the selected tree, which
    # is what the rule chose; the legacy k=4 atlas is drawn as well because
    # it is the picture every earlier figure showed and the paper needs to
    # see what changed.
    paths["dendrogram"] = round2figs1.plot_dendrogram(
        winner["_Z"], selected_labels, rows, out / "ALL_dendrogram.png",
        title=(f"round2 corrected store — {verdict['selected']['method']} "
               f"linkage, {verdict['selected']['metric']} distance"),
        cophenetic=verdict["selected"]["cophenetic_r"],
        k=verdict["selected"]["k"])
    print(f"-> {paths['dendrogram']}")

    paths["families"] = round2figs1.plot_family_atlas(
        features, legacy_labels, rows, out / "ALL_families.png",
        title=(f"round2 corrected store — Ward / Euclidean at k = {LEGACY_K} "
               "(the legacy cut, kept for comparability with nulls_v1)"),
        cophenetic=legacy["cophenetic_r"])
    print(f"-> {paths['families']}")

    paths["families_selected"] = round2figs1.plot_family_atlas(
        features, selected_labels, rows,
        out / "ALL_families_selected.png",
        title=(f"round2 corrected store — the SELECTED cut: "
               f"{verdict['selected']['method']} / "
               f"{verdict['selected']['metric']}, k = "
               f"{verdict['selected']['k']}"),
        cophenetic=verdict["selected"]["cophenetic_r"])
    print(f"-> {paths['families_selected']}")

    payload = {
        "detector_provenance": PROVENANCE,
        "store": info,
        "shipped_for_comparison": {
            "cophenetic_r_shipped_with_defect": 0.6814,
            "cophenetic_r_after_deleting_the_22": 0.4080,
            "n_shipped_refined": 1058,
            "n_after_deleting_zero_variance": 1036,
            "source": "nulls_v1/README.md section 4b",
        },
        "linkage_grid": tree2.public(cells),
        "verdict": verdict,
        "selected_cut": {
            "method": verdict["selected"]["method"],
            "metric": verdict["selected"]["metric"],
            "k": verdict["selected"]["k"],
            "cophenetic_r": verdict["selected"]["cophenetic_r"],
            "silhouette": verdict["selected"]["silhouette"],
            "cramers_v_vs_channel": vsel,
            "mean_within_family_distance": tight_sel,
            "families": tables["selected"],
            "labels": [int(v) for v in selected_labels],
        },
        "legacy_cut": {
            "method": "ward", "metric": "euclidean",
            "k": LEGACY_K, "fine_k": FINE_K,
            "cophenetic_r": legacy["cophenetic_r"],
            "silhouette_by_k": legacy["silhouette_by_k"],
            "cut_shape_by_k": legacy["cut_shape_by_k"],
            "cramers_v_vs_channel_k4": v4,
            "cramers_v_vs_channel_k10": v10,
            "mean_within_family_distance_k4": tight4,
            "families_k4": tables["legacy_ward_k4"],
            "families_k10": tables["legacy_ward_k10"],
            "labels_k4": [int(v) for v in legacy_labels],
            "labels_k10": [int(v) for v in fine_labels],
            "note": ("Ward at k=4 is what drop_motifs6-9 and nulls_v1 used. "
                     "Reported so the round-1 numbers stay comparable; not "
                     "selected by the rule."),
        },
        "surrogate_grid_rerun_gate": {
            "rule": ("re-run the 50-minute grid only if the corrected "
                     "real-side tightness statistic moves by more than the "
                     "AAFT null's interquartile range"),
            "round1_real": 2.3424,
            "round2_real": tight4,
            "delta": delta,
            "aaft_null_iqr": null_iqr,
            "rerun_needed": rerun,
        },
        "figures": paths,
        "event_ids": [r["event_id"] for r in rows],
        "channels": [int(c) for c in channel],
    }
    (out / "TASK_A_tree.json").write_text(
        json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\n-> {out / 'TASK_A_tree.json'}")
    return 0


def _aaft_tightness_iqr():
    """The AAFT null's IQR for mean within-family distance, from nulls_v1.

    Read out of the round-1 JSON rather than recomputed: the grid is
    read-only input to this round and the brief forbids re-running it
    without cause. `null_q1` / `null_q3` are the quartiles the grid already
    wrote, in the FALL representation, which is the one round one quoted
    (2.3424 real against a 2.7273 AAFT median).
    """
    path = _Path(round2.NULLS_V1, "NULL_surrogate.json")
    if not path.is_file():
        return None
    data = json.loads(path.read_text("utf-8"))
    try:
        cell = data["tests"]["family"]["fall"]["within_family_dispersion"][
            "aaft"]
    except (KeyError, TypeError):
        return None
    q1, q3 = cell.get("null_q1"), cell.get("null_q3")
    if q1 is None or q3 is None:
        return None
    return float(q3) - float(q1)


if __name__ == "__main__":
    raise SystemExit(main())
