"""
catalogue_cluster.py
=====================
Adapter for the dendrogram clustering stage in
`Working.Catalogue.dendrogram.dendrogram_cluster` — the missing typed link
from a `WindowSet` (a per-window feature matrix) to a `Grouping` (one
integer cluster label per window).

`dendrogram_cluster` exposes two stages — `preprocess_window_matrix` and
`cluster_window_matrix` — and a long tail of visualisation helpers. This
adapter exposes exactly the two calls the typed chain needs, and surfaces
only `linkage` and `k` as parameters because the thesis plan records both
as unresolved research decisions: they must stay tunable from the block
inspector rather than be baked into the adapter.

The underlying module imports matplotlib at module scope for its plotting
half, so it is imported lazily inside `_cluster_window_set` rather than at
adapter-import time — registering this adapter must not drag a plotting
backend into every `discover_adapters()` call.
"""

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec
from Adapters.registry import register
from Working.types import Grouping


def _cluster_window_set(window_set, linkage, k):
    """Run the two dendrogram stages and return the `ClusterResult`."""
    if window_set is None:
        raise ValueError(
            "catalogue.cluster requires a WindowSet input from a prior step "
            "(input_kind='windowset')."
        )
    features = window_set.features
    if features is None or features.shape[0] == 0 or features.shape[1] == 0:
        raise ValueError(
            "catalogue.cluster requires a WindowSet with an attached feature "
            "matrix, one row per window."
        )
    if k > len(features):
        raise ValueError(
            f"k={k} exceeds the number of windows ({len(features)}) — cannot "
            "cut more clusters than there are leaves."
        )

    from Working.Catalogue.dendrogram.dendrogram_cluster import (
        cluster_window_matrix,
        preprocess_window_matrix,
    )

    preprocessed = preprocess_window_matrix(features)
    return cluster_window_matrix(preprocessed, method=linkage, n_clusters=k)


def _run(x, t, fs, linkage="ward", k=3, value=None):
    cluster = _cluster_window_set(value, linkage, k)
    return AdapterResult(
        output_kind="grouping",
        value=Grouping(labels=cluster.labels),
        meta={
            "linkage": linkage,
            "k": k,
            "cluster_counts": cluster.cluster_counts,
            "n_windows": cluster.n_windows,
            "n_features": cluster.n_features,
        },
    )


def _derive(x, t, fs, params, value=None):
    """Pre-run readout: cluster sizes for the current linkage and k.

    `derive` is normally called with `(x, t, fs, params)`. Because this
    block's primary input is a typed `WindowSet` rather than the root
    signal, the window set can be supplied as the optional `value` keyword
    (the same way `_run` receives it from `execute_recipe`). Without it
    there is no matrix to cluster, so the readout says so instead of
    inventing a number.
    """
    if value is None:
        return [("Cluster sizes", "run the window-matrix step first", "warn")]

    cluster = _cluster_window_set(value, params["linkage"], params["k"])
    sizes = ", ".join(
        str(cluster.cluster_counts[label])
        for label in sorted(cluster.cluster_counts)
    )
    return [
        ("Clusters requested", str(params["k"]), ""),
        ("Windows clustered", str(cluster.n_windows), ""),
        ("Cluster sizes", sizes, ""),
    ]


SPEC = register(AdapterSpec(
    name="catalogue.cluster",
    display_name="Dendrogram clustering (WindowSet -> Grouping)",
    stage="catalogue",
    params=[
        ParamSpec(
            "linkage", str, "ward",
            "Hierarchical linkage method. Ward is the recommended default for "
            "electrophysiological windows; average/complete/single remain "
            "available because the linkage choice is an open research decision.",
            choices=["ward", "average", "complete", "single"],
        ),
        ParamSpec(
            "k", int, 3,
            "Number of flat clusters to cut the dendrogram into.",
            min=2,
        ),
    ],
    run=_run,
    input_kind="windowset",
    output_kind="grouping",
    derive=_derive,
    description=(
        "Hierarchical clustering of a window set's attached feature matrix, "
        "returning one integer cluster label per window as a Grouping. "
        "Linkage and cluster count are exposed as parameters — the selection "
        "criterion is an open research decision and must stay tunable."
    ),
))
