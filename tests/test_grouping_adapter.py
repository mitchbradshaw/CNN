"""
test_grouping_adapter.py
=========================
Ticket 11 — new adapter: clustering to a Grouping.

The block takes a `WindowSet` and produces a `Grouping` — the missing link
between the window matrix and a label set. These tests assert the external
behaviour the ticket's acceptance criteria name: the adapter declares
`WindowSet -> Grouping`, exposes linkage and cluster count as tunable
parameters, offers a `derive` readout that reports the resulting cluster
sizes for the current parameters, recovers three obvious synthetic clusters
(asserted by group membership rather than by silhouette score), and the
produced `Grouping` round-trips to disk and back unchanged.

Run from the project root:
    python -m pytest tests/test_grouping_adapter.py -q
"""

import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.registry import discover_adapters, get_adapter
from Working.types import Grouping, WindowSet

discover_adapters()

CLUSTER_NAME = "catalogue.cluster"


def _synthetic_window_set(n_per_cluster=12, seed=0):
    """Three well-separated Gaussian blobs, as a `WindowSet` with an attached
    two-feature matrix. The separation (6 units) is far larger than the blob
    spread (0.2), so any sane hierarchical clustering must recover three
    groups by membership."""
    rng = np.random.RandomState(seed)
    centers = [np.array([0.0, 0.0]), np.array([6.0, 0.0]), np.array([0.0, 6.0])]
    rows = []
    group_ids = []
    for group_id, center in enumerate(centers):
        rows.append(center + rng.normal(0.0, 0.2, size=(n_per_cluster, 2)))
        group_ids.extend([group_id] * n_per_cluster)

    features = pd.DataFrame(np.vstack(rows), columns=["x", "y"])
    starts = np.arange(len(features))
    window_set = WindowSet(starts=starts, length=128, fs=1.0, features=features)
    return window_set, np.array(group_ids)


def test_cluster_adapter_declares_windowset_to_grouping():
    spec = get_adapter(CLUSTER_NAME)
    assert spec.input_kind == "windowset"
    assert spec.output_kind == "grouping"


def test_linkage_and_cluster_count_are_params():
    spec = get_adapter(CLUSTER_NAME)
    param_names = {p.name for p in spec.params}
    assert {"linkage", "k"} <= param_names

    linkage = next(p for p in spec.params if p.name == "linkage")
    assert linkage.type is str
    assert set(linkage.choices) == {"ward", "average", "complete", "single"}

    k = next(p for p in spec.params if p.name == "k")
    assert k.type is int
    assert k.min is not None and k.min >= 2


def test_derive_reports_resulting_cluster_sizes():
    spec = get_adapter(CLUSTER_NAME)
    window_set, _ = _synthetic_window_set()
    params = spec.validate_params({"linkage": "ward", "k": 3})

    rows = spec.derive(np.zeros(3), np.arange(3), 1.0, params, value=window_set)

    values = {label: value for label, value, _severity in rows}
    assert "Cluster sizes" in values
    sizes = sorted(int(part) for part in values["Cluster sizes"].split(","))
    assert sizes == [12, 12, 12]


def test_three_obvious_clusters_recovered_by_membership():
    spec = get_adapter(CLUSTER_NAME)
    window_set, group_ids = _synthetic_window_set()
    params = spec.validate_params({"linkage": "ward", "k": 3})

    result = spec.run(np.zeros(3), np.arange(3), 1.0, value=window_set, **params)

    assert result.output_kind == "grouping"
    labels = result.value.labels
    assert len(labels) == len(window_set.starts)

    # Assert by membership: each synthetic blob maps to exactly one cluster,
    # and no two blobs share a cluster label.
    for group_id in range(3):
        blob_labels = labels[group_ids == group_id]
        assert len(np.unique(blob_labels)) == 1, group_id
    assert len(np.unique(labels)) == 3


def test_grouping_round_trips_to_disk_and_back(tmp_path):
    spec = get_adapter(CLUSTER_NAME)
    window_set, _ = _synthetic_window_set(n_per_cluster=8)
    params = spec.validate_params({"linkage": "ward", "k": 3})

    grouping = spec.run(np.zeros(3), np.arange(3), 1.0, value=window_set, **params).value

    grouping.to_path(str(tmp_path))
    restored = Grouping.from_path(str(tmp_path))
    assert restored == grouping
