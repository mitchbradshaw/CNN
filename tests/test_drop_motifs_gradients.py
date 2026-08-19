"""
test_drop_motifs_gradients.py
==============================
Tests for the fall-gradient measurements and the circular statistics
behind the rose diagram (`Working.Detection.drop_motifs.gradients`).

Why this needs tests at all: a rose diagram is very good at looking
convincing. Every one of the quantities under it - which gradient was
measured, what the angle was divided by to become dimensionless, whether
the bins wrap, whether the "mean direction" is a circular mean or an
arithmetic one - can be wrong while the picture stays beautiful. These
tests pin each of them on inputs whose answer is known by construction.

The two that matter most:

  - `slope_angle` is only meaningful relative to a STATED reference
    slope. arctan needs a dimensionless argument, and mV/s is not one.
    A test asserts that halving the reference moves the angle, so the
    reference can never quietly default to 1.0 and be forgotten.
  - the circular mean is not the arithmetic mean. On angles straddling a
    wrap point the two differ by 180 degrees, and only one of them is
    right.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.Detection.drop_motifs.gradients import (
    SLOPE_SCALES,
    circular_mean,
    fall_gradients,
    resultant_length,
    rose_histogram,
    slope_angle,
    uniformity_p,
)

FS = 1.0


# -- the gradients themselves ----------------------------------------------

def test_fall_gradients_on_a_linear_ramp_are_all_equal():
    """A perfectly linear fall has one gradient, so the steepest and the
    mean must both report it. If they disagree here, one of them is
    measuring something other than what it is named."""
    values = np.concatenate([np.zeros(20), np.linspace(0.0, -30.0, 31)])
    g = fall_gradients(values, FS, onset=20, trough=50)

    assert abs(g["max_slope_mv_s"] - (-1.0)) < 0.05
    assert abs(g["mean_slope_mv_s"] - (-1.0)) < 0.05
    assert abs(g["peakedness"] - 1.0) < 0.1


def test_onset_gradient_is_smeared_at_the_corner_which_is_why_it_is_not_the_default():
    """`np.gradient` is a CENTRAL difference, so at the corner where flat
    meets fall it averages the two and reports half the true steepness.

    This is not a defect to fix - a central difference is the right
    estimator - but it is the reason `max_slope_mv_s` and not
    `onset_slope_mv_s` is what the rose is built on by default. Pinned
    here so nobody 'fixes' the rose by switching the default back.
    """
    values = np.concatenate([np.zeros(20), np.linspace(0.0, -30.0, 31)])
    g = fall_gradients(values, FS, onset=20, trough=50)

    assert abs(g["onset_slope_mv_s"] - (-0.5)) < 0.05, (
        "the onset gradient at a corner should be half the fall's slope")
    assert g["max_slope_mv_s"] < g["onset_slope_mv_s"]


def test_peakedness_exceeds_one_when_the_fall_is_front_loaded():
    """A fall that is steep then shallow - which is what a spike's
    recovery actually looks like - must report a steepest gradient well
    above its own mean. This ratio is the dimensionless shape quantity the
    rose's second panel is built on, so it has to have the right sign of
    behaviour."""
    values = np.concatenate([
        np.zeros(10),
        np.linspace(0.0, -20.0, 11),      # steep: -2.0 per sample
        np.linspace(-20.0, -30.0, 40),    # shallow: -0.25 per sample
    ])
    g = fall_gradients(values, FS, onset=10, trough=60)

    assert g["peakedness"] > 3.0, (
        f"a front-loaded fall reported peakedness {g['peakedness']:.2f}")
    assert g["max_slope_mv_s"] < g["mean_slope_mv_s"] < 0.0


def test_fall_gradients_scale_correctly_with_sampling_rate():
    """The gradients are per SECOND, not per sample. Doubling fs over the
    same waveform must double every mV/s figure, or a 1 Hz recording and a
    2 Hz one cannot be put on the same rose."""
    values = np.concatenate([np.zeros(20), np.linspace(0.0, -30.0, 31)])
    slow = fall_gradients(values, 1.0, onset=20, trough=50)
    fast = fall_gradients(values, 2.0, onset=20, trough=50)

    assert abs(fast["max_slope_mv_s"] / slow["max_slope_mv_s"] - 2.0) < 0.01
    assert abs(fast["mean_slope_mv_s"] / slow["mean_slope_mv_s"] - 2.0) < 0.01
    # ... while the dimensionless ratio must NOT move.
    assert abs(fast["peakedness"] - slow["peakedness"]) < 1e-9


def test_a_degenerate_fall_does_not_raise_or_return_nonsense():
    flat = np.zeros(40)
    g = fall_gradients(flat, FS, onset=10, trough=30)
    assert g["max_slope_mv_s"] == 0.0
    assert g["peakedness"] == 0.0

    # trough at or before the onset: no fall to measure.
    g = fall_gradients(np.linspace(0, -10, 40), FS, onset=20, trough=20)
    assert np.isfinite(g["max_slope_mv_s"])
    assert np.isfinite(g["peakedness"])


# -- slope -> angle --------------------------------------------------------

def test_slope_angle_needs_a_reference_and_honours_it():
    """arctan takes a dimensionless argument. A slope in mV/s only has an
    angle once a reference slope fixes how many mV equal one second on the
    page - so the reference must visibly change the answer."""
    assert abs(slope_angle(-1.0, 1.0) - np.deg2rad(-45.0)) < 1e-9
    assert abs(slope_angle(-2.0, 2.0) - np.deg2rad(-45.0)) < 1e-9
    # Same slope, half the reference: steeper on the page.
    shallow = slope_angle(-1.0, 2.0)
    steep = slope_angle(-1.0, 0.5)
    assert steep < shallow < 0.0


def test_slope_angle_is_bounded_in_the_falling_quadrant():
    """Every drop angle lies in (-90, 0] degrees: a fall points down and
    to the right, and no finite slope reaches vertical. This is what lets
    the rose be drawn as a quadrant fan without clipping anything."""
    for slope in (-1e-6, -0.1, -1.0, -1e3, -1e9):
        theta = slope_angle(slope, 1.0)
        assert -np.pi / 2 < theta <= 0.0
    assert slope_angle(0.0, 1.0) == 0.0


def test_every_named_slope_scale_is_implemented():
    """`SLOCE_SCALES` is the CLI's choice list; a name in it with no
    implementation behind it is an argparse error at the worst moment."""
    from Working.Detection.drop_motifs.gradients import reference_slope
    gradients = [{"max_slope_mv_s": -2.0, "mean_slope_mv_s": -0.5,
                  "noise_sigma_mv_s": 0.01}] * 4
    for scale in SLOPE_SCALES:
        refs = reference_slope(gradients, scale, fixed=1.0)
        assert len(refs) == len(gradients)
        assert all(r > 0 for r in refs), f"{scale} produced a non-positive reference"


# -- circular statistics ---------------------------------------------------

def test_circular_mean_is_not_the_arithmetic_mean_across_a_wrap():
    """Two angles either side of the +/-180 boundary. Their circular mean
    is 180 degrees; their arithmetic mean is 0, which points the opposite
    way. Getting this wrong puts the mean-direction arrow on a rose
    exactly backwards."""
    angles = np.deg2rad([170.0, -170.0])
    assert abs(abs(circular_mean(angles)) - np.pi) < 1e-6
    assert abs(np.mean(angles)) < 1e-9        # ... which is the wrong answer


def test_circular_mean_matches_the_plain_mean_when_there_is_no_wrap():
    angles = np.deg2rad([-40.0, -45.0, -50.0])
    assert abs(np.rad2deg(circular_mean(angles)) - (-45.0)) < 0.5


def test_resultant_length_reads_as_concentration():
    """R = 1 for identical directions, ~0 for directions spread evenly
    round the circle. This is the number that says whether a rose's
    dominant lobe means anything."""
    identical = np.full(20, np.deg2rad(-30.0))
    assert abs(resultant_length(identical) - 1.0) < 1e-9

    spread = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    assert resultant_length(spread) < 0.01

    tight = np.deg2rad([-30.0, -32.0, -28.0, -31.0])
    assert resultant_length(tight) > 0.99


def test_uniformity_is_tested_against_the_achievable_range_not_the_circle():
    """Slope angles live in one quadrant, so a Rayleigh test against
    uniform-on-the-full-circle is trivially significant and says nothing.
    The test here is against uniform over the stated support.

    Calibration is checked over many draws rather than one: under the null
    a p-value is itself uniform on [0, 1], so any single uniform sample
    has a real 5% chance of landing under 0.05 and asserting on one draw
    would be asserting on a lucky seed. What must hold is that the rate is
    about right.
    """
    lo, hi = -np.pi / 2, 0.0
    flagged = 0
    for seed in range(40):
        rng = np.random.default_rng(seed)
        if uniformity_p(rng.uniform(lo, hi, 400), lo, hi) < 0.05:
            flagged += 1
    assert flagged <= 6, (
        f"{flagged}/40 genuinely uniform samples were called non-uniform; "
        "the test is not calibrated against its stated support")

    rng = np.random.default_rng(4)
    clustered = rng.normal(np.deg2rad(-45.0), np.deg2rad(2.0), 400)
    assert uniformity_p(clustered, lo, hi) < 0.001


# -- binning ---------------------------------------------------------------

def test_rose_histogram_counts_every_event_exactly_once():
    rng = np.random.default_rng(9)
    angles = rng.uniform(-np.pi / 2, 0.0, 137)
    centres, counts, width = rose_histogram(angles, n_bins=18,
                                            lo=-np.pi / 2, hi=0.0)
    assert len(centres) == len(counts) == 18
    assert counts.sum() == 137, "events were lost or double-counted in binning"
    assert abs(width - (np.pi / 2) / 18) < 1e-12


def test_rose_histogram_puts_a_known_angle_in_the_expected_bin():
    """One event at exactly -45 degrees, 18 bins over the quadrant: it
    belongs in the 9th, whose centre is -45 +/- half a bin."""
    centres, counts, width = rose_histogram(np.deg2rad([-45.0]), n_bins=18,
                                            lo=-np.pi / 2, hi=0.0)
    hit = int(np.argmax(counts))
    assert counts[hit] == 1
    assert abs(np.rad2deg(centres[hit]) - (-45.0)) <= np.rad2deg(width)


def test_rose_histogram_includes_both_endpoints():
    """An angle exactly on the upper edge must land in the last bin rather
    than falling off the end - otherwise a perfectly flat fall silently
    vanishes from the plot."""
    _, counts, _ = rose_histogram(np.array([0.0, -np.pi / 2]), n_bins=10,
                                  lo=-np.pi / 2, hi=0.0)
    assert counts.sum() == 2


def test_rose_histogram_on_no_events_returns_empty_bins_not_an_error():
    centres, counts, width = rose_histogram(np.array([]), n_bins=12,
                                            lo=-np.pi / 2, hi=0.0)
    assert len(counts) == 12
    assert counts.sum() == 0


def test_gradients_module_imports_no_plotting_library():
    import Working.Detection.drop_motifs.gradients as g
    forbidden = {"panel", "holoviews", "bokeh", "matplotlib"}
    names = {getattr(v, "__name__", "").split(".")[0] for v in vars(g).values()}
    assert not (forbidden & names)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
