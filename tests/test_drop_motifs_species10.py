"""drop_motifs10 - the machinery every Task 5 claim rests on.

One test per property a number in `CLAIMS.md` depends on. The rule this
run works to is that a claim without a test is a claim that will be
re-derived by hand next time and got wrong.
"""

import numpy as np
import pytest
from scipy.stats import chi2_contingency

from Pipelines.drop_motifs import corpora10, floor10, species10, tree10


# ---------------------------------------------------------------------------
# the confound the whole run is built around
# ---------------------------------------------------------------------------

def test_decimation_low_pass_filters_rather_than_taking_every_tenth_sample():
    """The rate control has to BE a control.

    At 10 Hz a 0.3 s fall is three samples. Taking every tenth sample
    folds it into the 1 Hz band as a single-sample step, which the
    detector would read as the sharpest drop in the recording - so naive
    decimation would manufacture exactly the short, sharp events the
    control exists to test for.

    The test: a signal that is pure high-frequency content must come back
    ATTENUATED, where a stride would alias it through at full amplitude.
    """
    fs = 10.0
    t = np.arange(0, 400, 1.0 / fs)
    # 4.2 Hz - far above the 0.5 Hz Nyquist of the decimated series, and
    # chosen so a stride ALIASES it to 0.2 Hz at full amplitude rather
    # than landing on a phase that happens to cancel.
    high = np.sin(2 * np.pi * 4.2 * t)

    decimated, new_fs = corpora10.decimate_to(high, fs, target_fs=1.0)
    strided = high[::10]

    assert new_fs == 1.0
    assert len(decimated) == pytest.approx(len(high) / 10, abs=2)
    # the stride passes it through essentially undiminished...
    assert np.ptp(strided) > 0.9 * np.ptp(high)
    # ...and the filter removes it
    assert np.ptp(decimated) < 0.25 * np.ptp(high), (
        "the anti-alias filter must remove the 4.2 Hz component; a stride "
        f"aliases it through (decimated ptp {np.ptp(decimated):.3f} vs "
        f"strided {np.ptp(strided):.3f} vs source {np.ptp(high):.3f})")


def test_decimation_is_zero_phase_so_events_do_not_move():
    """`RATE_COMPARISON.png` draws the same physical events on two axes,
    which is only honest if a decimated onset lands at `onset / factor`.
    """
    fs = 10.0
    # ONE event, not a train. With a train of identical drops `argmin` is
    # picking arbitrarily between equal minima and the test measures
    # nothing.
    x = np.zeros(4000)
    x[2000:2040] -= np.linspace(0, 1, 40)
    x[2040:2120] += np.linspace(-1, 0, 80)
    y, _ = corpora10.decimate_to(x, fs, target_fs=1.0)
    assert abs(int(np.argmin(y)) - int(np.argmin(x)) // 10) <= 1, (
        f"the decimated trough landed at {int(np.argmin(y))}, the native "
        f"one at {int(np.argmin(x))} (= {int(np.argmin(x)) // 10} "
        "decimated); a filter with group delay would move it")


def test_n_samples_in_fall_is_stamped_on_every_row():
    """The confound control's primary variable. Nothing in 5b works
    without it, so it is computed rather than trusted to arrive."""
    row = corpora10.label_row(
        {"onset_idx": 100, "trough_idx": 137},
        corpus="reishi_10hz", species="reishi", framing="sliding", fs=10.0)
    assert row["n_samples_in_fall"] == 37
    assert row["species"] == "reishi" and row["fs"] == 10.0
    # never zero, or a quantile bin edge lands on an impossible value
    assert corpora10.label_row(
        {"onset_idx": 5, "trough_idx": 5}, corpus="c", species="s",
        framing="span", fs=1.0)["n_samples_in_fall"] == 1


def test_reishi_arms_share_a_species_and_the_matched_subset_is_1hz():
    """The design, asserted rather than assumed by every later table."""
    assert (corpora10.species_of(corpora10.CORPUS_REISHI_10HZ)
            == corpora10.species_of(corpora10.CORPUS_REISHI_1HZ)
            == corpora10.SPECIES_REISHI)
    assert corpora10.CORPUS_REISHI_10HZ not in corpora10.MATCHED_RATE_SUBSET
    assert set(corpora10.MATCHED_RATE_CLEAN_PAIR) == {
        corpora10.CORPUS_OYSTER, corpora10.CORPUS_385}


# ---------------------------------------------------------------------------
# the depth floor
# ---------------------------------------------------------------------------

def test_derived_floor_scales_with_the_recording_s_own_noise():
    """A floor that does not move with the noise is a per-corpus tuning
    decision made by accident - which is what the global 0.1 mV is."""
    rng = np.random.default_rng(20260903)
    quiet = rng.normal(0.0, 0.001, 20000)
    loud = rng.normal(0.0, 0.010, 20000)
    assert (floor10.derived_floor_mv(loud)
            > 5 * floor10.derived_floor_mv(quiet))
    # ...and it is 3 sigma, not some other multiple
    assert floor10.derived_floor_mv(quiet) == pytest.approx(
        3.0 * floor10.amplitude_sigma_mv(quiet))


def test_the_floor_is_stamped_on_every_row_it_passed():
    """A pooled store built from four corpora, each with its own floor,
    must still say per event which number it was measured against."""
    rows = [{"drop_depth_mv": 0.5}, {"drop_depth_mv": 0.05}]
    kept, rejected = floor10.apply_floor(rows, 0.1, rule="test")
    assert len(kept) == 1 and len(rejected) == 1
    assert kept[0]["depth_floor_mv"] == 0.1
    assert kept[0]["floor_rule"] == "test"


# ---------------------------------------------------------------------------
# the permutation machinery
# ---------------------------------------------------------------------------

def test_fast_cramers_v_agrees_with_scipy():
    """The permutation loop uses a hand-rolled chi-square for speed. If it
    disagreed with scipy the observed value and the null would be on
    different scales and every p would be meaningless."""
    rng = np.random.default_rng(3)
    table = rng.integers(5, 90, (4, 3)).astype(float)
    chi2, _, _, _ = chi2_contingency(table)
    expected = np.sqrt(chi2 / (table.sum() * (min(table.shape) - 1)))
    assert species10._v_from_table(table) == pytest.approx(expected)
    assert species10.cramers_v(table)[0] == pytest.approx(expected)


def test_permutation_p_is_never_zero():
    """A p of zero claims more resolution than the shuffles bought."""
    families = ["A"] * 60 + ["B"] * 60
    labels = ["x"] * 60 + ["y"] * 60          # perfectly associated
    result = species10.permutation_v(families, labels, n=200)
    # Exactly 1.0, which it only is with Yates' correction OFF. See
    # `cramers_v`: scipy corrects 2x2 tables by default and the
    # permutation null does not, so the default would put the observed
    # value and its own null on different formulae.
    assert result["cramers_v"] == pytest.approx(1.0)
    assert result["permutation_p"] == pytest.approx(1 / 201)
    assert result["permutation_p"] > 0


def test_permutation_null_recovers_independence():
    """Shuffling the label must destroy the association and nothing else -
    both marginals are preserved exactly, so an independent table has to
    sit inside its own null."""
    rng = np.random.default_rng(11)
    families = rng.integers(0, 4, 800)
    labels = rng.choice(["a", "b", "c"], 800)
    result = species10.permutation_v(families, labels, n=500)
    assert result["permutation_p"] > 0.05
    assert result["cramers_v"] == pytest.approx(
        result["null_median_v"], abs=0.06)


def test_sample_bins_are_quantiles_not_fixed_width():
    """Fixed-width bins over corpora two orders of magnitude apart would
    put every reishi event in one bin and every oyster event in another,
    which makes the confound control a test of the binning."""
    values = [1, 2, 3, 4] * 25 + [300, 400] * 25
    bins = species10.sample_bins(values, n_bins=4)
    assert len(set(bins)) >= 3
    biggest = max(set(bins), key=lambda b: bins.count(b))
    assert bins.count(biggest) < len(values) * 0.75


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------

def _separable(n_per_class=60, seed=7):
    rng = np.random.default_rng(seed)
    X = np.vstack([rng.normal(loc, 1.0, (n_per_class, 4)) for loc in (0, 6)])
    y = np.array(["a"] * n_per_class + ["b"] * n_per_class)
    return X, y


def test_decode_beats_its_own_null_on_separable_classes():
    X, y = _separable()
    result = species10.decode(X, y, n_permutations=100, group=90)
    assert result["balanced_accuracy"] > 0.9
    assert result["permutation_p"] <= 0.05
    assert result["chance"] == pytest.approx(0.5)


def test_decode_does_not_beat_its_null_on_random_labels():
    """The test that matters most: the procedure must not manufacture
    accuracy. Balanced subsampling and stratified folds can both do that,
    which is why the null re-runs the WHOLE cross-validation rather than
    being an analytic chance level."""
    rng = np.random.default_rng(5)
    X = rng.normal(0, 1, (160, 4))
    y = rng.choice(["a", "b"], 160)
    result = species10.decode(X, y, n_permutations=100, group=91)
    assert result["permutation_p"] > 0.05
    assert result["balanced_accuracy"] < 0.70


def test_decode_is_class_balanced_by_subsampling():
    """Every class comes back at the size of the smallest, so chance is
    1/n_classes and the drawn chance line is the real one."""
    rng = np.random.default_rng(2)
    X = rng.normal(0, 1, (300, 3))
    y = np.array(["a"] * 250 + ["b"] * 50)
    result = species10.decode(X, y, n_permutations=20, group=92)
    assert result["n"] == 100
    assert result["n_per_class"] == 50


def test_resolution_alone_is_available_as_a_control_representation():
    """If `n_samples_in_fall` alone decodes species well, so will anything
    correlated with it - which is the point of carrying it."""
    rows = [{"drop_depth_mv": 1.0, "fall_duration_s": 2.0,
             "max_slope_raw": -0.5, "n_samples_in_fall": 7}]
    reps = species10.representations(np.zeros((1, 200)), rows)
    assert set(reps) == {"absolute scale", "normalised shape", "both",
                         "resolution alone"}
    assert reps["resolution alone"].shape == (1, 1)
    assert reps["resolution alone"][0, 0] == 7
    assert reps["both"].shape == (1, 203)


# ---------------------------------------------------------------------------
# transfer
# ---------------------------------------------------------------------------

def test_transfer_scores_high_when_b_is_a_s_own_shapes():
    """The sanity end of 5d: A's medoids describing events drawn from A's
    own families must score well above a permuted partition."""
    rng = np.random.default_rng(13)
    t = np.linspace(0, 1, 200)
    shapes = [np.sin(2 * np.pi * t), -t, np.exp(-4 * t), t ** 2]
    def draw(n):
        rows = []
        for i in range(n):
            base = shapes[i % len(shapes)]
            rows.append(base + rng.normal(0, 0.05, t.size))
        return np.vstack(rows)
    A, B = draw(120), draw(120)
    result = species10.transfer(A, B, k=4, n=100, group=93)
    assert result["ari"] > 0.5
    assert result["permutation_p"] <= 0.05


def test_phase_randomised_surrogate_preserves_the_power_spectrum():
    """The partition-free check compares a real event against a surrogate
    with its OWN spectrum, so the surrogate must actually have it."""
    rng = np.random.default_rng(17)
    x = np.cumsum(rng.normal(0, 1, 256))
    y = species10.phase_randomised(x, rng)
    assert np.allclose(np.abs(np.fft.rfft(x)), np.abs(np.fft.rfft(y)),
                       rtol=1e-8, atol=1e-8)
    assert not np.allclose(x, y)


# ---------------------------------------------------------------------------
# the tree
# ---------------------------------------------------------------------------

def test_tree_reports_why_a_row_was_dropped_rather_than_dropping_it_quietly():
    """A count of zero here is a claim, so the counts are carried into
    every figure's JSON. 22 all-zero vectors reached a shipped tree in
    drop_motifs9 because nothing counted them."""
    rows = [{"event_id": "a", "onset_idx": 0, "trough_idx": 5,
             "snippet_start_idx": 0, "snippet_end_idx": 10,
             "signal_sign": 1},
            {"event_id": "missing", "onset_idx": 0, "trough_idx": 5,
             "snippet_start_idx": 0, "snippet_end_idx": 10,
             "signal_sign": 1},
            {"event_id": "flat", "onset_idx": 0, "trough_idx": 5,
             "snippet_start_idx": 0, "snippet_end_idx": 10,
             "signal_sign": 1}]
    snippets = {
        "a": {"detrended_mv": np.linspace(1.0, 0.0, 10)},
        "flat": {"detrended_mv": np.full(10, 0.4)},
    }
    waveforms, kept, dropped = tree10.waveforms_of(rows, snippets)
    assert [r["event_id"] for r in kept] == ["a"]
    assert dropped == {"no_array": 1, "store_mismatch": 0, "constant": 1}


def test_medoid_is_a_real_member_not_a_mean():
    """A mean of z-normalised vectors is not a waveform any event has and
    must never be drawn as one."""
    features = np.array([[0.0, 1.0], [0.1, 1.1], [5.0, 5.0]])
    labels = np.array([1, 1, 2])
    index = tree10.medoids(features, labels)
    assert set(index) == {1, 2}
    assert index[1] in (0, 1)
    assert index[2] == 2
