"""
tree2.py
=========
Round 2, Task A step 4: which linkage, decided by a rule stated before the
answers were read.

THE RULE, IN FULL, WRITTEN DOWN FIRST
--------------------------------------
1. The GRID is fixed in advance: {Ward, average, complete} x {Euclidean,
   correlation}. Ward is only defined for Euclidean distance - its update
   formula minimises a variance, which presumes squared Euclidean geometry
   - so Ward x correlation is computed for completeness and reported as
   METHOD-INVALID, never selected.
2. The number of families k is chosen, per linkage, by round one's rule:
   maximise mean silhouette over k in 2..12 in the same distance the tree
   was built in, breaking ties toward the SMALLER k.
3. The linkage is chosen by COPHENETIC CORRELATION, highest wins. Not by
   silhouette, and not by how many families it produces. Cophenetic r is
   the only one of the two numbers that measures what a dendrogram is FOR:
   how faithfully the tree's merge heights reproduce the pairwise distances
   it was built from. Silhouette measures how separated a CUT is, which is
   a different question and one a tree can score well on while being a poor
   summary of the distance matrix.
4. `COPHENETIC_FLOOR` = 0.70 is the floor these figures already warn at.
   If the winner clears it, its (linkage, k) carries the family table. If
   NO cell clears it, that is reported as the finding: no tree over this
   feature matrix is a faithful summary of it, the family table is a cut
   rather than a discovered structure, and it must be captioned as one.
5. Ties in cophenetic r within 0.005 break toward the linkage with the
   higher silhouette, then toward Ward, because Ward is what every earlier
   figure in this pipeline used and a change of default should have to earn
   itself.

The rule is here, above the code, so the order it was fixed in is a
property of the file rather than a claim in a report.

WHY THIS IS BEING ASKED AT ALL
-------------------------------
Round one found the shipped Ward tree's cophenetic r was 0.681 only because
22 all-zero feature vectors sat on top of each other at distance zero; with
them removed the same store gives 0.408. A tree that weakly supported
should not carry a paper's family table without comment. Task A's store fix
removes the zero vectors at source rather than by deletion, so this module
runs on a store where the question can be asked cleanly.
"""

import numpy as np
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import pdist
from sklearn.metrics import silhouette_score

COPHENETIC_FLOOR = 0.70
K_RANGE = tuple(range(2, 13))
METHODS = ("ward", "average", "complete")
METRICS = ("euclidean", "correlation")
TIE_TOLERANCE = 0.005

# A family this small is not a family. `nulls_v1` counted families at
# ">= 5 members" for exactly this reason, and the same threshold is used
# here so the two rounds count the same object.
MIN_FAMILY = 5

# A cut this lopsided is one family plus some outliers, whatever k says.
# Reported, never selected on - see `cut_shape`.
DEGENERATE_SHARE = 0.90


def select_k(Z, condensed, features, metric, k_range=K_RANGE):
    """Round one's rule: max mean silhouette over `k_range`, ties to smaller.

    The silhouette is computed in the SAME distance the tree was built in,
    passed as a precomputed square matrix, so a correlation tree is not
    scored on Euclidean separation it never optimised.
    """
    from scipy.spatial.distance import squareform

    square = squareform(condensed)
    scores = {}
    n = features.shape[0]
    for k in k_range:
        if k >= n:
            continue
        labels = fcluster(Z, k, criterion="maxclust")
        if len(set(labels.tolist())) < 2:
            continue
        scores[int(k)] = float(silhouette_score(square, labels,
                                                metric="precomputed"))
    if not scores:
        return None, {}
    best = max(scores, key=lambda k: (scores[k], -k))
    return int(best), scores


def cut_shape(labels, min_family=MIN_FAMILY,
              degenerate_share=DEGENERATE_SHARE):
    """What a cut actually looks like, as numbers rather than as a k.

    This exists because the silhouette rule can be satisfied by shaving a
    handful of outliers off one blob: average linkage on this store scores
    its best silhouette at k = 2 with sizes 1092 and 5, which is not two
    families, it is one family and five outliers. A silhouette cannot tell
    those apart - separating five far points from a thousand near ones is
    genuinely a well-separated partition by that measure.

    So the shape of the cut is REPORTED alongside every silhouette, and it
    is deliberately NOT part of the selection rule in `choose`. Adding a
    criterion after seeing which cells it would disqualify is how a rule
    stops being a rule. A reader gets the rule's answer and the diagnostic
    that qualifies it, in the same row.
    """
    labels = np.asarray(labels)
    n = labels.size
    sizes = sorted((int(np.sum(labels == v)) for v in set(labels.tolist())),
                   reverse=True)
    largest = sizes[0] / n if n else 0.0
    return {
        "sizes": sizes,
        "n_families_at_least_min": int(sum(1 for s in sizes
                                           if s >= min_family)),
        "largest_family_share": float(largest),
        "degenerate": bool(largest >= degenerate_share),
    }


def linkage_grid(features, methods=METHODS, metrics=METRICS,
                 k_range=K_RANGE):
    """Every cell of the grid. Returns a list of dicts, one per cell.

    Nothing is selected here. `choose` applies the rule; keeping the two
    apart is what makes it checkable that the rule did not move once the
    numbers were on the table.
    """
    features = np.asarray(features, dtype=float)
    cells = []
    for metric in metrics:
        condensed = pdist(features, metric=metric)
        for method in methods:
            invalid = (method == "ward" and metric != "euclidean")
            Z = linkage(condensed, method=method)
            coph, _ = cophenet(Z, condensed)
            k, scores = select_k(Z, condensed, features, metric,
                                 k_range=k_range)
            labels = fcluster(Z, k, criterion="maxclust") if k else None
            shapes = {}
            for kk in k_range:
                if kk >= features.shape[0]:
                    continue
                shapes[int(kk)] = cut_shape(
                    fcluster(Z, kk, criterion="maxclust"))
            cells.append({
                "method": method,
                "metric": metric,
                "cophenetic_r": float(coph),
                "selected_k": k,
                "silhouette_at_selected_k": (float(scores[k]) if k else None),
                "silhouette_by_k": scores,
                "cut_shape_at_selected_k": (shapes.get(k) if k else None),
                "cut_shape_by_k": shapes,
                "method_invalid": bool(invalid),
                "invalid_reason": (
                    "Ward minimises a variance and presumes squared "
                    "Euclidean geometry; it is not defined for a "
                    "correlation distance" if invalid else None),
                "_Z": Z,
                "_labels": labels,
                "_condensed": condensed,
            })
    return cells


def choose(cells, floor=COPHENETIC_FLOOR, tie=TIE_TOLERANCE):
    """Apply the rule at the top of this module. Returns `(cell, verdict)`.

    `verdict["clears_floor"]` is the one a caption has to carry.
    """
    eligible = [c for c in cells if not c["method_invalid"]
                and c["selected_k"] is not None]
    if not eligible:
        return None, {"clears_floor": False,
                      "reason": "no valid linkage produced a cut"}

    best_r = max(c["cophenetic_r"] for c in eligible)
    contenders = [c for c in eligible
                  if c["cophenetic_r"] >= best_r - tie]
    winner = max(contenders, key=lambda c: (
        c["silhouette_at_selected_k"] or 0.0, c["method"] == "ward"))

    verdict = {
        "rule": ("highest cophenetic r among valid linkages; ties within "
                 f"{tie} to the higher silhouette, then to Ward; k by max "
                 "mean silhouette over 2..12 with ties to the smaller k"),
        "cophenetic_floor": float(floor),
        "best_cophenetic_r": float(best_r),
        "n_contenders_within_tie": len(contenders),
        "selected": {"method": winner["method"], "metric": winner["metric"],
                     "k": winner["selected_k"],
                     "cophenetic_r": winner["cophenetic_r"],
                     "silhouette": winner["silhouette_at_selected_k"]},
        "clears_floor": bool(best_r >= floor),
        "any_cell_clears_floor": bool(
            max(c["cophenetic_r"] for c in cells) >= floor),
    }
    shape = winner.get("cut_shape_at_selected_k") or {}
    verdict["selected"]["cut_sizes"] = shape.get("sizes")
    verdict["selected"]["n_families_at_least_5"] = shape.get(
        "n_families_at_least_min")
    verdict["selected"]["degenerate_cut"] = shape.get("degenerate")
    if shape.get("degenerate"):
        verdict["degeneracy_warning"] = (
            f"The selected cut is {shape['sizes']}: "
            f"{shape['largest_family_share'] * 100:.1f}% of the events are "
            f"in one family, and {shape['n_families_at_least_min']} of "
            f"{len(shape['sizes'])} groups reach {MIN_FAMILY} members. "
            "The rule was followed, and what "
            "it selected is one family plus a handful of outliers, not a "
            "repertoire of two shapes. Read as a statement about the data "
            "rather than about the method, this says the shape distribution "
            "has no gap in it: no cut of this tree separates two populated "
            "groups better than shaving off its extremes.")
    if not verdict["clears_floor"]:
        verdict["finding"] = (
            f"No linkage over this feature matrix reaches cophenetic "
            f"r = {floor:.2f}. The best is {winner['method']} linkage on "
            f"{winner['metric']} distance at r = {best_r:.3f}. The family "
            "table is therefore a CUT, not a discovered structure, and "
            "every figure carrying it must say so. The tightness result is "
            "unaffected: it is a statement about distances between events, "
            "and does not require the tree to be a faithful summary of "
            "them.")
    return winner, verdict


def public(cells):
    """The grid with the scipy objects stripped, ready for JSON."""
    return [{k: v for k, v in cell.items() if not k.startswith("_")}
            for cell in cells]
