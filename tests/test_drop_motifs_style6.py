"""
The four numeric fixes behind the drop_motifs6 figure set.

Each test here pins a defect that was visible in the drop_motifs5 plots
and states it as the behaviour that must not come back. They are numeric
rather than visual on purpose: every one of these faults reached a saved
PNG without raising, so an assertion on a drawn figure would have passed
too.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import style6


# -- fix 1: baseline is the flat run, not one sample --------------------

def test_baseline_ignores_a_noise_spike_at_the_onset_sample():
    """The catalogue ID 8 defect.

    A single anomalous sample AT the onset index moved the whole trace by
    its own error under `values[onset]`. Four traces in one panel then sat
    at four different pre-drop heights in a figure whose caption claimed
    they all start at zero.
    """
    values = np.concatenate([np.full(50, 10.0), np.full(50, -40.0)])
    values[49] = 25.0                      # the bad sample, at the onset
    assert style6.baseline_level(values, 49) == pytest.approx(10.0)


def test_baseline_of_a_flat_run_is_that_level():
    values = np.concatenate([np.full(40, -3.5), np.linspace(-3.5, -60, 40)])
    assert style6.baseline_level(values, 40) == pytest.approx(-3.5)


def test_aligned_traces_start_from_a_common_height():
    """The property the left overlay panel claims and did not have."""
    starts = []
    for level in (-455.0, -442.0, -430.0):
        values = np.concatenate([np.full(40, level),
                                 np.linspace(level, level - 50.0, 40)])
        values[39] = level + np.random.default_rng(0).normal(0, 4)
        _, aligned = style6.aligned_trace(values, 40, fs=1.0)
        starts.append(float(np.median(aligned[:40])))
    assert np.allclose(starts, 0.0, atol=1e-9)


def test_baseline_falls_back_when_there_is_no_pre_onset_region():
    values = np.array([5.0, 4.0, -30.0, -35.0])
    assert style6.baseline_level(values, 0) == pytest.approx(5.0)


# -- fix 2: one window length for the whole set -------------------------

def test_common_window_is_the_smallest_each_side():
    pre, post = style6.common_window([40, 12, 25], [90, 60, 70])
    assert (pre, post) == (12, 60)


def test_uniform_set_puts_every_onset_at_the_same_index():
    """Ragged in, rectangular out, and the onsets line up.

    The detector brackets each event on its own UP runs, so windows are
    different lengths by construction. An overlay of them is traces that
    stop at different places for reasons unrelated to the motif.
    """
    traces, onsets = [], []
    for pre, post in ((30, 80), (12, 60), (45, 95)):
        traces.append(np.concatenate([np.zeros(pre),
                                      np.linspace(0, -40, post)]))
        onsets.append(pre)

    stacked, onset = style6.uniform_set(traces, onsets)

    assert stacked.shape == (3, 12 + 60)
    assert onset == 12
    assert np.isfinite(stacked).all()
    # Every row falls from the same column, which is the whole point.
    assert np.allclose(stacked[:, onset], 0.0)


def test_cut_to_common_pads_short_motifs_with_nan_not_with_an_edge_value():
    """A trace with no data there must show as absent, not as flat."""
    values = np.concatenate([np.zeros(5), np.linspace(0, -20, 10)])
    cut, onset = style6.cut_to_common(values, 5, pre=20, post=10)

    assert onset == 20
    assert np.isnan(cut[:15]).all()          # nothing recorded that early
    assert np.isfinite(cut[20:]).all()


# -- fix 3: outliers are drawn but do not set the scale -----------------

def test_outlier_mask_catches_the_id10_pair():
    """Two events an order of magnitude deeper than the family.

    A standard-deviation screen fails this: the two outliers inflate the
    deviation far enough to stop being outliers by their own test.
    """
    depths = np.array([2.1, 2.4, 2.0, 2.6, 2.2, 2.5, 2.3, 24.0, 27.0])
    mask = style6.outlier_mask(depths)

    assert mask.tolist() == [False] * 7 + [True, True]


def test_outlier_mask_is_empty_when_the_family_is_tight():
    assert not style6.outlier_mask(np.array([2.0, 2.1, 2.2, 2.05, 2.15])).any()


def test_family_ylim_is_set_by_the_inliers_not_by_the_outliers():
    """The operator's instruction, as an assertion.

    An outlier may be drawn and may leave the frame; it may not squash the
    family it is an outlier of.
    """
    family = np.vstack([np.linspace(0, -3, 50) for _ in range(7)])
    outliers = np.vstack([np.linspace(0, -27, 50) for _ in range(2)])
    stacked = np.vstack([family, outliers])
    inliers = np.array([True] * 7 + [False] * 2)

    low, high = style6.family_ylim(stacked, inliers)

    assert low > -4.0        # scaled to the family
    assert low < -3.0        # and still contains it


def test_family_ylim_without_a_mask_uses_everything():
    stacked = np.vstack([np.linspace(0, -3, 20), np.linspace(0, -27, 20)])
    low, _ = style6.family_ylim(stacked)
    assert low < -27.0


# -- fix 4: the ramp reaches no yellow ----------------------------------

def test_time_ramp_is_blue_green_and_never_yellow():
    """Yellow is excluded from the report this feeds.

    Yellow is high red AND high green with low blue. Asserting on that
    combination tests the property that was asked for, rather than
    asserting the name of a colormap.
    """
    samples = style6.TIME_CMAP(np.linspace(0, 1, 64))
    red, green, blue = samples[:, 0], samples[:, 1], samples[:, 2]

    yellowish = (red > 0.65) & (green > 0.65) & (blue < 0.45)
    assert not yellowish.any()

    # Blue-dominant at the start, green-dominant at the end. This is what
    # "a blue to green gradient" means, and it is the assertion to make
    # rather than one on the blue channel's absolute value: a ramp that
    # starts at a dark navy has a modest blue number and is still blue.
    assert blue[0] > green[0] + 0.2
    assert green[-1] > blue[-1] + 0.2


def test_time_ramp_stays_legible_on_white_and_orders_in_greyscale():
    """Two failure modes measured on the rejected candidates.

    `GnBu_r` truncated to its green end reached luminance 0.77 - a trace
    in it is invisible on the page. And a ramp whose luminance is not
    monotone stops being an ordering the moment the figure is printed in
    greyscale, which is how a thesis appendix is usually read.
    """
    samples = style6.TIME_CMAP(np.linspace(0, 1, 64))
    luminance = (0.299 * samples[:, 0] + 0.587 * samples[:, 1]
                 + 0.114 * samples[:, 2])

    assert luminance.max() < 0.70
    assert np.all(np.diff(luminance) > -0.005)


def test_time_colours_map_earliest_and_latest_to_the_ramp_ends():
    colours, norm = style6.time_colours([100.0, 104.0, 108.0])

    assert len(colours) == 3
    assert norm.vmin == 100.0 and norm.vmax == 108.0
    assert colours[0] == style6.TIME_CMAP(0.0)
    assert colours[-1] == style6.TIME_CMAP(1.0)


def test_time_colours_of_a_single_event_do_not_divide_by_zero():
    colours, _ = style6.time_colours([7.0])
    assert len(colours) == 1


# -- the line weights are actually heavier ------------------------------

def test_line_weights_are_30_to_50_percent_above_the_previous_set():
    """Every width is its drop_motifs5 base times one shared multiplier."""
    assert 1.30 <= style6.LW <= 1.50

    pairs = [
        (style6.LW_TRACE, style6.BASE_TRACE),
        (style6.LW_SIGNAL, style6.BASE_SIGNAL),
        (style6.LW_MEDOID, style6.BASE_MEDOID),
        (style6.LW_FAMILY, style6.BASE_FAMILY),
        (style6.LW_OUTLIER, style6.BASE_OUTLIER),
        (style6.LW_TREE, style6.BASE_TREE),
        (style6.LW_RULE, style6.BASE_RULE),
    ]
    for width, base in pairs:
        assert 1.30 <= width / base <= 1.50

    # The two bases that are pinned to a real drop_motifs5 line, so the
    # comparison is against what was actually drawn rather than a guess.
    assert style6.BASE_TRACE == 0.9
    assert style6.BASE_SIGNAL == 0.5
