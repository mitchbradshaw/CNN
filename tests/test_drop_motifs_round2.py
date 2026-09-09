"""round2: the seams the claims table rests on.

Each test here guards a sentence that ends up in `CLAIMS.md`. They are
cheap and headless, and none of them touches a store - the point is the
LOGIC that turns numbers into verdicts, because that is what a reader
cannot check by re-running the pipeline.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import decode2, floors2, round2, tree2, validity2


# ---------------------------------------------------------------------------
# the seed formula round one got wrong
# ---------------------------------------------------------------------------

def test_the_seed_formula_is_injective_where_round_one_collided():
    """Round one used `base + 1000*generator + 10*channel + realisation`,
    which is not injective once realisation >= 10: CH0 realisation 10 and
    CH1 realisation 0 drew identical randomness, and 500 channel-
    realisations shared 140 seeds. 100 separates them."""
    seeds = [round2.seed(channel, realisation)
             for channel in range(5) for realisation in range(100)]

    assert len(set(seeds)) == len(seeds)


def test_the_round_one_multiplier_would_have_collided_on_this_grid():
    """The regression the formula change exists to prevent, stated as a
    test rather than as a comment, so nobody reinstates 10."""
    collided = [round2.SEED_BASE + 10 * channel + realisation
                for channel in range(5) for realisation in range(100)]

    assert len(set(collided)) < len(collided)


# ---------------------------------------------------------------------------
# a cut that is one family plus outliers must be reported as one
# ---------------------------------------------------------------------------

def test_a_1092_to_5_split_is_flagged_degenerate():
    """The measured case. Average linkage scores its best silhouette at
    k = 2 by shaving five outliers off a thousand events, and a silhouette
    cannot tell that from a real two-family structure - separating five far
    points from a thousand near ones IS a well-separated partition by that
    measure. The diagnostic has to catch it because the rule cannot."""
    labels = np.array([1] * 1092 + [2] * 5)

    shape = tree2.cut_shape(labels)

    assert shape["degenerate"] is True
    assert shape["sizes"] == [1092, 5]
    assert shape["largest_family_share"] > 0.99


def test_a_balanced_four_way_cut_is_not_flagged_degenerate():
    labels = np.array([1] * 163 + [2] * 680 + [3] * 202 + [4] * 52)

    shape = tree2.cut_shape(labels)

    assert shape["degenerate"] is False
    assert shape["n_families_at_least_min"] == 4


def test_the_degeneracy_diagnostic_does_not_change_what_the_rule_selects():
    """The diagnostic is REPORTED, never selected on. Adding a criterion
    after seeing which cells it would disqualify is how a rule stops being
    a rule, so this pins that `choose` ignores it."""
    degenerate = {
        "method": "average", "metric": "euclidean", "cophenetic_r": 0.84,
        "selected_k": 2, "silhouette_at_selected_k": 0.72,
        "method_invalid": False,
        "cut_shape_at_selected_k": tree2.cut_shape(
            np.array([1] * 1092 + [2] * 5)),
    }
    healthy = {
        "method": "ward", "metric": "euclidean", "cophenetic_r": 0.64,
        "selected_k": 4, "silhouette_at_selected_k": 0.29,
        "method_invalid": False,
        "cut_shape_at_selected_k": tree2.cut_shape(
            np.array([1] * 400 + [2] * 400 + [3] * 200 + [4] * 97)),
    }

    winner, verdict = tree2.choose([degenerate, healthy])

    assert winner is degenerate
    assert verdict["selected"]["method"] == "average"
    assert verdict["degeneracy_warning"]


def test_ward_on_a_correlation_distance_is_never_selected():
    """Ward minimises a variance and presumes squared Euclidean geometry.
    It is computed for completeness and must not win, even when it has the
    best cophenetic r."""
    invalid = {
        "method": "ward", "metric": "correlation", "cophenetic_r": 0.99,
        "selected_k": 2, "silhouette_at_selected_k": 0.9,
        "method_invalid": True,
        "cut_shape_at_selected_k": tree2.cut_shape(np.array([1] * 50 +
                                                            [2] * 50)),
    }
    valid = {
        "method": "average", "metric": "euclidean", "cophenetic_r": 0.50,
        "selected_k": 3, "silhouette_at_selected_k": 0.4,
        "method_invalid": False,
        "cut_shape_at_selected_k": tree2.cut_shape(
            np.array([1] * 40 + [2] * 30 + [3] * 30)),
    }

    winner, verdict = tree2.choose([invalid, valid])

    assert winner is valid
    assert verdict["clears_floor"] is False
    assert "0.70" in verdict["finding"] or "0.7" in verdict["finding"]


# ---------------------------------------------------------------------------
# Task B's verdict must be able to say the claim is false
# ---------------------------------------------------------------------------

def _entry(accuracy, p=0.001):
    return {"balanced_accuracy": accuracy, "p_permutation": p,
            "chance": 0.2, "at_p_floor": False, "p_floor": 0.000999}


def test_shape_decoding_as_well_as_amplitude_falsifies_the_claim():
    """The outcome the paper must not be allowed to soften. If normalised
    shape recovers the electrode as well as amplitude does, the central
    claim is wrong and the verdict has to say so without being asked."""
    results = {
        "amplitude": {"random_forest": _entry(0.35)},
        "shape": {"random_forest": _entry(0.34)},
    }

    _, verdict = decode2.headline(results)

    assert verdict["verdict"] == "falsified"


def test_shape_at_chance_supports_the_strong_form():
    results = {
        "amplitude": {"random_forest": _entry(0.35)},
        "shape": {"random_forest": _entry(0.21, p=0.42)},
    }

    _, verdict = decode2.headline(results)

    assert verdict["verdict"] == "supported"


def test_shape_between_the_two_is_supported_only_as_a_matter_of_degree():
    """The measured case: shape carries some site information but far less
    than amplitude. The claim survives as a statement about degree and must
    not be written as an absolute."""
    results = {
        "amplitude": {"random_forest": _entry(0.346)},
        "shape": {"random_forest": _entry(0.262)},
    }

    sentence, verdict = decode2.headline(results)

    assert verdict["verdict"] == "supported with a caveat"
    assert "20%" in sentence
    assert 0.0 < verdict["shape_margin_as_fraction_of_amplitude_margin"] < 0.9


def test_amplitude_failing_its_own_null_is_reported_not_ignored():
    results = {
        "amplitude": {"random_forest": _entry(0.22, p=0.31)},
        "shape": {"random_forest": _entry(0.21, p=0.44)},
    }

    _, verdict = decode2.headline(results)

    assert verdict["verdict"] == "not supported"


def test_the_both_representation_standardises_before_stacking():
    """Three raw millivolt columns beside two hundred z-scored ones would
    be invisible to a regularised model, so the concatenation has to put
    them on one scale first."""
    shape = np.random.default_rng(0).normal(0, 1, (40, 200))
    amplitude = np.column_stack([
        np.full(40, 1000.0) + np.arange(40),
        np.linspace(0.5, 2.0, 40),
        np.linspace(-30, -5, 40)])

    both = decode2.build("both", shape, amplitude)

    assert both.shape == (40, 203)
    assert abs(both[:, :3].mean()) < 1e-9
    assert abs(both[:, :3].std() - 1.0) < 0.05


# ---------------------------------------------------------------------------
# Task C's null has to hold the family sizes fixed
# ---------------------------------------------------------------------------

def test_the_random_partition_null_preserves_the_observed_family_sizes():
    """Within-family distance falls as a group gets smaller, so a null that
    drew sizes at random would compare the real partition against groupings
    of a different SHAPE and the result would be about size rather than
    about structure."""
    rng = np.random.default_rng(7)
    features = rng.normal(0, 1, (60, 8))
    labels = np.array([1] * 30 + [2] * 20 + [3] * 10)

    result = validity2.random_partition_null(features, labels, n=25)

    assert result["family_sizes_held_fixed"] == [30, 20, 10]
    assert result["n_null"] == 25


def test_a_real_grouping_beats_the_random_partition_null():
    """Three well-separated blobs must come out tighter than any random
    grouping of the same sizes; if this ever fails the statistic is not
    measuring what Task C claims it measures."""
    rng = np.random.default_rng(11)
    features = np.vstack([
        rng.normal(centre, 0.25, (30, 6))
        for centre in (-8.0, 0.0, 8.0)])
    labels = np.array([1] * 30 + [2] * 30 + [3] * 30)

    result = validity2.random_partition_null(features, labels, n=100)

    assert result["observed"] < result["null_min"]
    assert result["p"] <= result["p_floor"]


def test_co_association_divides_by_the_resamples_a_pair_was_drawn_in():
    """A bootstrap draws about 63% of the events each time, so dividing by
    the number of RESAMPLES rather than by the number in which both members
    appeared would report every pair at roughly 0.4x its real
    co-association and the whole matrix would read as instability that is
    an artefact of the resampling."""
    rng = np.random.default_rng(3)
    features = np.vstack([rng.normal(centre, 0.2, (25, 4))
                          for centre in (-6.0, 6.0)])
    labels = np.array([1] * 25 + [2] * 25)

    matrix, stability = validity2.bootstrap_coassociation(
        features, 2, n=40, reference_labels=labels)

    assert stability["mean_within_family_coassociation"] > 0.9
    assert stability["mean_between_family_coassociation"] < 0.1
    finite = matrix[np.isfinite(matrix)]
    assert finite.max() <= 1.0


# ---------------------------------------------------------------------------
# Task D's floor is derived, not chosen
# ---------------------------------------------------------------------------

def test_a_quieter_channel_gets_a_lower_floor():
    """The whole point of Task D. A global floor's severity is set by how
    quiet an electrode happens to be; a derived floor scales with it."""
    noise = {
        0: {"median_slope_sigma_mv_per_s": 0.30},
        2: {"median_slope_sigma_mv_per_s": 0.09},
    }

    floors = floors2.per_channel_floors(noise, fs=10.0, multiplier=3.0)

    assert floors[2] < floors[0]
    assert floors[0] == pytest.approx(0.09)
    assert floors[2] == pytest.approx(0.027)


def test_the_floor_is_applied_per_channel_not_globally():
    rows = [
        {"channel": 0, "drop_depth_mv": 0.05},   # under CH0's 0.09
        {"channel": 2, "drop_depth_mv": 0.05},   # over  CH2's 0.027
    ]
    floors = {0: 0.09, 2: 0.027}

    kept = floors2.apply_floor(rows, floors)

    assert [r["channel"] for r in kept] == [2]


def test_the_global_floor_is_what_removes_most_of_the_quiet_channel():
    """The measured asymmetry, as a test: a 0.1 mV gate keeps a loud
    channel's events and removes a quiet one's, which is what makes it a
    channel-dependent filter rather than a noise floor."""
    rows = ([{"channel": 3, "drop_depth_mv": 0.30}] * 10
            + [{"channel": 2, "drop_depth_mv": 0.04}] * 10)

    kept = floors2.apply_floor(rows, None, global_floor=0.1)

    assert {r["channel"] for r in kept} == {3}


# ---------------------------------------------------------------------------
# Task E has to distinguish two different failures
# ---------------------------------------------------------------------------

def test_a_count_below_the_null_median_is_not_an_underpowered_test():
    """CH2 and CH4's measured situation. The detector finds FEWER events
    than in surrogates built from their own spectra, so more events would
    not help - and calling that 'too few events to tell' would be the
    wrong sentence in the paper."""
    summary = {"observed": 80.0, "p": 0.95, "null_median": 95.5,
               "null_q1": 88.0, "null_q3": 106.0, "null_min": 66.0,
               "null_max": 117.0, "n_null": 100}

    note = floors2.power_note(2, summary, noise_sigma=0.09,
                              median_depth=0.195, n_events=97)

    assert note["verdict"] == "indistinguishable from coloured noise"
    assert "FEWER" in note["gloss"]


def test_a_count_just_short_of_the_threshold_is_underpowered():
    summary = {"observed": 205.0, "p": 0.09, "null_median": 190.0,
               "null_q1": 182.0, "null_q3": 200.0, "null_min": 160.0,
               "null_max": 230.0, "n_null": 100}

    note = floors2.power_note(3, summary, noise_sigma=0.24,
                              median_depth=0.355, n_events=250)

    assert note["verdict"] == "too few events to tell"


def test_a_channel_that_clears_the_null_is_not_given_a_failure_verdict():
    summary = {"observed": 318.0, "p": 0.0099, "null_median": 212.0,
               "null_q1": 206.0, "null_q3": 221.0, "null_min": 190.0,
               "null_max": 240.0, "n_null": 100}

    note = floors2.power_note(1, summary, noise_sigma=0.27,
                              median_depth=0.259, n_events=350)

    assert note["verdict"] == "exceeds the null"
