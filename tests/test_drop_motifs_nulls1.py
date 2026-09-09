"""
The surrogate generators and the rank statistic, tested against the
properties the write-up claims for them.

Task 1's entire argument is "the detector finds things in the recording
that it does not find in a signal with the same spectrum / the same
waveforms". That argument is only as good as the surrogates being what
they are said to be, and a surrogate that quietly failed to destroy what
it claims to destroy - or quietly destroyed something it claims to
preserve - would produce a confident, wrong p-value with nothing on the
figure to give it away.

Run: pytest tests/test_drop_motifs_nulls1.py
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import nulls1 as n1

FS = 10.0
N = 4000


def _skewed_signal(seed=3):
    """Something with the awkward properties the real channels have: a
    strongly non-Gaussian, one-sided marginal on top of coloured noise.
    A Gaussian test signal would let plain phase randomisation pass as
    AAFT."""
    rng = np.random.default_rng(seed)
    noise = np.cumsum(rng.normal(0, 1, N))
    noise = noise - np.convolve(noise, np.ones(101) / 101, mode="same")
    spikes = np.zeros(N)
    for onset in rng.choice(N - 40, 60, replace=False):
        spikes[onset:onset + 8] -= np.linspace(0, 3.0, 8)
    return noise * 0.2 + spikes


# ---------------------------------------------------------------------------
# AAFT
# ---------------------------------------------------------------------------

def test_aaft_preserves_the_marginal_distribution_exactly():
    """The 'amplitude-adjusted' half of AAFT. The output must be a
    PERMUTATION of the input's own sample values - not merely similarly
    distributed. This is the property that makes it the right null for a
    non-Gaussian channel, and plain phase randomisation fails it."""
    x = _skewed_signal()
    y = n1.aaft_surrogate(x, np.random.default_rng(0))
    assert np.allclose(np.sort(x), np.sort(y)), (
        "AAFT output is not a permutation of the input's values")


def test_aaft_preserves_the_power_spectrum_approximately():
    """The 'Fourier transform' half. Approximately, not exactly - the
    rank remapping distorts it slightly, which is stated in the module
    docstring and is why IAAFT exists. The threshold is loose on purpose:
    it is here to catch a surrogate that has lost the spectrum entirely,
    not to pin a number."""
    from scipy.signal import welch
    x = _skewed_signal()
    y = n1.aaft_surrogate(x, np.random.default_rng(0))
    _, px = welch(x, FS, nperseg=512)
    _, py = welch(y, FS, nperseg=512)
    correlation = float(np.corrcoef(np.log(px), np.log(py))[0, 1])
    assert correlation > 0.75, (
        "AAFT lost the power spectrum: log-periodogram correlation %.3f"
        % correlation)


def test_aaft_destroys_the_waveform_asymmetry_it_is_meant_to_destroy():
    """The whole point of the null. These events are asymmetric - a fast
    fall and a slow recovery - and the skew of the first difference is
    what measures that. A surrogate that preserved it would not be
    nulling anything."""
    from scipy.stats import skew
    x = _skewed_signal()
    y = n1.aaft_surrogate(x, np.random.default_rng(0))
    assert abs(skew(np.diff(x))) > 0.5, "test signal is not asymmetric"
    assert abs(skew(np.diff(y))) < abs(skew(np.diff(x))) / 2.0, (
        "AAFT kept the derivative skew (%.3f -> %.3f); it is supposed to "
        "destroy waveform asymmetry"
        % (skew(np.diff(x)), skew(np.diff(y))))


def test_aaft_is_real_valued_and_the_same_length():
    x = _skewed_signal()
    y = n1.aaft_surrogate(x, np.random.default_rng(0))
    assert y.shape == x.shape
    assert np.all(np.isfinite(y))
    assert not np.iscomplexobj(y)


# ---------------------------------------------------------------------------
# block shuffle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("block_s", [50.0, 5.0])
def test_block_shuffle_preserves_length_and_every_sample(block_s):
    """The sliding window derives its window count from the signal length,
    so a surrogate one sample short would silently be a different
    experiment."""
    x = _skewed_signal()
    y = n1.block_shuffle_surrogate(x, np.random.default_rng(1), block_s, FS)
    assert y.shape == x.shape
    assert np.allclose(np.sort(x), np.sort(y))


@pytest.mark.parametrize("block_s", [50.0, 5.0])
def test_block_shuffle_actually_reorders(block_s):
    """A permutation that happened to be the identity would be a null
    that nulls nothing, and it would look exactly like a strong positive
    result."""
    x = _skewed_signal()
    y = n1.block_shuffle_surrogate(x, np.random.default_rng(1), block_s, FS)
    assert not np.allclose(x, y), (
        "block shuffle at %g s returned the signal unchanged" % block_s)


def test_block_shuffle_keeps_local_waveform_intact():
    """The claim that separates this generator from AAFT: everything
    INSIDE a block survives. Checked by finding where a block landed and
    comparing it sample for sample."""
    x = _skewed_signal()
    block = int(round(5.0 * FS))
    y = n1.block_shuffle_surrogate(x, np.random.default_rng(1), 5.0, FS)
    source = x[block * 3:block * 4]
    n_blocks = len(x) // block
    found = any(np.allclose(y[i * block:(i + 1) * block], source)
                for i in range(n_blocks))
    assert found, "a whole 5 s block of the original is not present intact"


# ---------------------------------------------------------------------------
# seeds and the rank statistic
# ---------------------------------------------------------------------------

def test_seed_formula_matches_the_documented_one():
    assert n1.seed_for("aaft", 0, 0) == 20260902
    assert n1.seed_for("block50", 0, 0) == 20260902 + 1000
    assert n1.seed_for("block5", 4, 99) == 20260902 + 2000 + 40 + 99


def test_seeds_are_unique_within_a_channel():
    """The property panel A's per-channel nulls depend on: a channel's 100
    realisations must be 100 genuinely different surrogates."""
    for generator in n1.GENERATORS:
        for channel in range(5):
            seeds = [n1.seed_for(generator, channel, r) for r in range(100)]
            assert len(set(seeds)) == 100, (generator, channel)


def test_seeds_are_unique_within_a_realisation():
    """The property the pooled tree depends on: one realisation must not
    draw the same randomness for two of its five channels."""
    for generator in n1.GENERATORS:
        for realisation in range(100):
            seeds = [n1.seed_for(generator, c, realisation) for c in range(5)]
            assert len(set(seeds)) == 5, (generator, realisation)


def test_the_specified_seed_formula_collides_across_channels():
    """A REGRESSION LOCK ON A KNOWN DEFECT, not an endorsement of it.

    `10*channel + realisation` is not injective once realisation >= 10:
    CH0 realisation 10 and CH1 realisation 0 draw identical randomness.
    The formula is the one the specification fixed and the one every
    recorded seed came from, so it was kept and documented rather than
    changed mid-grid. This test exists so that if someone later switches
    to `100*channel + realisation` - which is the right fix - they are
    told, here, that the recorded seeds no longer reproduce the shipped
    nulls.
    """
    assert n1.seed_for("aaft", 0, 10) == n1.seed_for("aaft", 1, 0)
    report = n1.seed_collisions(100)
    assert report["n_channel_realisations_per_generator"] == 500
    assert report["n_distinct_seeds_per_generator"] == 140
    assert report["max_reuse_of_one_seed"] == 5
    assert report["unique_within_each_channel"]
    assert report["unique_within_each_realisation"]


def test_generators_never_share_a_seed():
    """The 1000x generator stride is what keeps the three nulls
    independent of each other; at the grid's size it does."""
    by_generator = {g: {n1.seed_for(g, c, r)
                        for c in range(5) for r in range(100)}
                    for g in n1.GENERATORS}
    for a, b in ((0, 1), (0, 2), (1, 2)):
        first, second = n1.GENERATORS[a], n1.GENERATORS[b]
        assert not (by_generator[first] & by_generator[second]), (first, second)


def test_the_same_seed_reproduces_the_same_surrogate():
    """The reproducibility claim the README makes in section 5."""
    x = _skewed_signal()
    for generator in n1.GENERATORS:
        seed = n1.seed_for(generator, 2, 7)
        first = n1.make_surrogate(x, FS, generator, seed)
        second = n1.make_surrogate(x, FS, generator, seed)
        assert np.array_equal(first, second), generator


def test_rank_p_hits_its_floor_and_its_ceiling():
    null = np.arange(100, dtype=float)
    assert n1.rank_p(1000.0, null, greater=True)["p"] == pytest.approx(1 / 101)
    assert n1.rank_p(-1.0, null, greater=True)["p"] == pytest.approx(1.0)
    assert n1.rank_p(-1.0, null, greater=False)["p"] == pytest.approx(1 / 101)


def test_rank_p_never_returns_zero():
    """(1 + #{...}) / (1 + N) - the +1 is what stops a p of 0 being
    reported from 100 samples, and a p of 0 in a paper is a claim no
    finite null can support."""
    null = np.zeros(100)
    assert n1.rank_p(999.0, null, greater=True)["p"] > 0


def test_rank_p_ignores_non_finite_nulls_and_says_how_many_it_used():
    null = [1.0, 2.0, np.nan, None, 3.0]
    result = n1.rank_p(2.5, null, greater=True)
    assert result["n_null"] == 3
    assert result["p"] == pytest.approx(2 / 4)


# ---------------------------------------------------------------------------
# the edge trim
# ---------------------------------------------------------------------------

def test_trim_edges_keeps_only_the_interior_and_is_symmetric():
    """The FFT wrap-around defence. Both ends must go, and by the same
    amount, or the real store and its surrogates are counted over
    different spans."""
    n_samples = 12001
    rows = [{"onset_idx": idx, "channel": 0}
            for idx in (0, 499, 500, 6000, 11500, 11501, 12000)]
    kept = [r["onset_idx"]
            for r in n1.trim_edges(rows, FS, n_samples, trim_s=50.0)]
    assert kept == [500, 6000, 11500]


def test_trim_edges_with_zero_trim_keeps_everything():
    rows = [{"onset_idx": i, "channel": 0} for i in range(0, 12000, 1000)]
    assert len(n1.trim_edges(rows, FS, 12001, trim_s=0.0)) == len(rows)


# ---------------------------------------------------------------------------
# the detector's arguments
# ---------------------------------------------------------------------------

def test_detect_kwargs_are_read_from_the_shipped_run_not_retyped():
    """If run_summary.json ever changes, this must change with it - the
    surrogates are only a null of the shipped detector if they use the
    shipped detector's arguments."""
    kwargs = n1.detect_kwargs()
    assert kwargs["window_s"] == 50.0
    assert kwargs["overlap"] == 0.5
    assert kwargs["fine"] and kwargs["sensitive"] and kwargs["micro"]
    assert set(kwargs["_passes_fired_in_shipped_run"]) == {
        "base", "fine", "sens", "micro"}


def test_channel_entry_survives_the_json_round_trip():
    """int keys in memory, string keys after json.dump. Both callers must
    resolve - this is the bug that would otherwise have surfaced only
    after the fifty-minute grid finished."""
    per_channel = {0: "a", 1: "b"}
    assert n1.channel_entry(per_channel, 0) == "a"
    assert n1.channel_entry({"0": "a"}, 0) == "a"
    assert n1.channel_entry({"CH3": "d"}, 3) == "d"
    with pytest.raises(KeyError):
        n1.channel_entry({"CH3": "d"}, 4)
