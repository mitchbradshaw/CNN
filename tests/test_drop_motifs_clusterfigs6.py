"""
How many family panels the full-page dendrogram draws.

This is a layout decision, not a statistical one, and the distinction is
the whole point: `cluster.suggest_n_clusters` answers "how many clusters
does this data have", and answering that question was what produced a
figure with 24 of 31 motifs in one panel.
"""

import numpy as np
import pytest
from scipy.cluster.hierarchy import linkage

from Pipelines.drop_motifs import clusterfigs6 as cf6


def _linkage_of(points):
    return linkage(np.asarray(points, dtype=float).reshape(-1, 1),
                   method="ward")


def _blob(centre, n, spread=0.05, seed=0):
    rng = np.random.default_rng(seed)
    return centre + rng.normal(0, spread, n)


def test_no_family_holds_more_than_half_the_tree():
    """The catalogue ID 1 defect: 24 of 31 motifs in one panel.

    Four well-separated groups, one of them much larger than the rest. A
    cut that leaves the big one intact is the one being ruled out.
    """
    points = np.concatenate([_blob(0.0, 20, seed=1), _blob(10.0, 4, seed=2),
                             _blob(20.0, 4, seed=3), _blob(30.0, 4, seed=4)])
    Z = _linkage_of(points)

    from Working.Detection.drop_motifs import cluster as dc

    k = cf6.choose_family_count(Z, len(points))
    _, counts = np.unique(dc.cut_tree(Z, n_clusters=k), return_counts=True)

    assert counts.max() <= cf6.MAX_FAMILY_SHARE * len(points)


def test_balance_outranks_avoiding_a_singleton():
    """Ranking the two costs instead of weighing them chose k=3 here and
    left 62% of the motifs in one panel, because that cut had no
    singleton. An over-large family is the more serious fault."""
    from Working.Detection.drop_motifs import cluster as dc

    points = np.concatenate([_blob(0.0, 20, seed=1), _blob(10.0, 4, seed=2),
                             _blob(20.0, 4, seed=3), _blob(30.0, 4, seed=4)])
    Z = _linkage_of(points)

    k = cf6.choose_family_count(Z, len(points))
    _, counts = np.unique(dc.cut_tree(Z, n_clusters=k), return_counts=True)

    assert k >= 5
    assert counts.max() <= cf6.MAX_FAMILY_SHARE * len(points)


def test_a_balanced_tree_is_not_cut_deeper_than_it_needs():
    """Splitting a coherent set costs the comparison the panel is for."""
    points = np.concatenate([_blob(0.0, 8, seed=1), _blob(10.0, 8, seed=2),
                             _blob(20.0, 8, seed=3)])
    Z = _linkage_of(points)

    assert cf6.choose_family_count(Z, len(points)) == 3


def test_singletons_are_avoided_because_one_trace_is_not_a_family():
    """A panel holding one trace shows no family and still costs a row."""
    from Working.Detection.drop_motifs import cluster as dc

    points = np.concatenate([_blob(0.0, 9, seed=1), _blob(10.0, 9, seed=2),
                             _blob(20.0, 9, seed=3)])
    Z = _linkage_of(points)

    k = cf6.choose_family_count(Z, len(points))
    _, counts = np.unique(dc.cut_tree(Z, n_clusters=k), return_counts=True)

    assert (counts == 1).sum() == 0


def test_the_family_count_never_exceeds_what_a_page_holds():
    points = np.concatenate([_blob(10.0 * i, 3, seed=i) for i in range(20)])
    Z = _linkage_of(points)

    assert cf6.choose_family_count(Z, len(points)) <= cf6.MAX_FAMILIES


def test_a_tiny_tree_does_not_ask_for_more_families_than_it_has():
    points = np.array([0.0, 0.1, 5.0, 5.1])
    Z = _linkage_of(points)

    assert cf6.choose_family_count(Z, 4) <= 3


# -- the medoid is a real motif -----------------------------------------

def test_medoid_is_the_least_outlying_member():
    """A representative should be something that was recorded, not an
    average of things that were."""
    features = np.array([[0.0, 0.0], [0.1, 0.1], [0.2, 0.0], [9.0, 9.0]])
    assert cf6._medoid(features, [0, 1, 2]) == 1


def test_medoid_of_a_single_member_is_that_member():
    assert cf6._medoid(np.array([[1.0, 2.0]]), [0]) == 0


# -- contiguous blocks --------------------------------------------------

def test_contiguous_blocks_walks_runs_of_one_label():
    assert cf6._contiguous_blocks([1, 1, 2, 2, 2, 3]) == [
        (1, 0, 2), (2, 2, 5), (3, 5, 6)]


def test_contiguous_blocks_of_an_empty_sequence():
    assert cf6._contiguous_blocks([]) == []
