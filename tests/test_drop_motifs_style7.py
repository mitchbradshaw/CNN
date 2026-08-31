"""
What drop_motifs7 adds: one hue per family, and a locked height-to-width
ratio. Both were reported as figure faults and both are pinned here as
numbers, because both reached a saved PNG without raising.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import passes7, style7


# -- one hue per family -------------------------------------------------

def test_no_family_ramp_reaches_red_yellow_black_or_white():
    """The four colours excluded from this report, as one assertion.

    Tested on HUE, not on the raw red channel. A red-channel threshold
    fails orange, which is high in red by construction and is one of the
    two hues the operator asked FOR on the inverted pass - the first
    version of this test rejected the palette it was meant to protect.
    """
    from matplotlib.colors import rgb_to_hsv

    for index in range(len(style7.FAMILY_RAMPS) + len(style7.INVERTED_RAMPS)):
        for inverted in (False, True):
            name, cmap = style7.family_ramp(index, inverted=inverted)
            rgb = cmap(np.linspace(0, 1, 48))[:, :3]
            hue, sat, val = rgb_to_hsv(rgb).T

            coloured = (sat > 0.35) & (val > 0.25)
            # Red sits within ~15 degrees of hue 0; orange (~30 deg) does not.
            is_red = coloured & ((hue < 0.042) | (hue > 0.958))
            # Yellow is a bright, saturated hue around 60 degrees.
            is_yellow = (sat > 0.35) & (val > 0.65) & (hue > 0.11) & (hue < 0.20)

            assert not is_red.any(), f"{name} reaches red"
            assert not is_yellow.any(), f"{name} reaches yellow"

            luminance = (0.299 * rgb[:, 0] + 0.587 * rgb[:, 1]
                         + 0.114 * rgb[:, 2])
            assert luminance.min() > 0.06, f"{name} reaches black"
            assert luminance.max() < 0.88, f"{name} reaches white"


def test_enough_hues_that_a_five_family_span_never_repeats_one():
    """ID 26 has five drop families; a four-ramp pool captioned two of
    them "green", which is worse than no colour coding."""
    assert len(style7.FAMILY_RAMPS) >= 6
    names = [style7.family_ramp(i)[0] for i in range(5)]
    assert len(set(names)) == 5


def test_drops_and_rises_never_share_a_hue():
    drops = {style7.family_ramp(i)[0] for i in range(len(style7.FAMILY_RAMPS))}
    rises = {style7.family_ramp(i, inverted=True)[0]
             for i in range(len(style7.INVERTED_RAMPS))}
    assert drops.isdisjoint(rises)


def test_a_family_ramp_runs_light_to_dark_so_time_is_readable():
    _, cmap = style7.family_ramp(0)
    s = cmap(np.linspace(0, 1, 32))
    luminance = 0.299 * s[:, 0] + 0.587 * s[:, 1] + 0.114 * s[:, 2]
    assert luminance[0] > luminance[-1] + 0.2


# -- the locked height-to-width ratio -----------------------------------

def test_a_steeper_motif_is_drawn_steeper():
    """The property the whole change exists for.

    Under the old fit-to-axes behaviour both of these filled their panel
    and looked identical. Under one shared scale the 20 mV / 3 s event
    must come out far steeper than the 3 mV / 200 s one.
    """
    aspect = style7.seconds_per_mv([20.0, 3.0], [3.0, 200.0])

    steep = aspect * 20.0 / 3.0
    shallow = aspect * 3.0 / 200.0
    assert steep > shallow * 100


def test_the_median_event_lands_at_the_target_proportion():
    aspect = style7.seconds_per_mv([10.0] * 5, [50.0] * 5)
    assert aspect * 10.0 / 50.0 == pytest.approx(style7.TARGET_MEDIAN_RATIO)


def test_the_scale_is_clamped_so_a_panel_cannot_become_a_hairline():
    assert style7.seconds_per_mv([1e-9], [1e9]) <= style7.MAX_SECONDS_PER_MV
    assert style7.seconds_per_mv([1e9], [1e-9]) >= style7.MIN_SECONDS_PER_MV


def test_seconds_per_mv_survives_a_set_with_nothing_measurable():
    assert style7.seconds_per_mv([], []) == 1.0
    assert style7.seconds_per_mv([0.0, np.nan], [0.0, np.inf]) == 1.0


def test_aspect_caption_states_the_scale_both_ways_round():
    assert "mV of height" in style7.aspect_caption(0.5)
    assert "s of width" in style7.aspect_caption(4.0)
    assert "not locked" in style7.aspect_caption(0.0)


# -- the micro pass and the lone inverted rule --------------------------

def test_micro_relaxes_exactly_the_three_gates_that_were_rejecting_events():
    """ID 26 at 8 sigma: 67 candidates, 21 shallow, 18 no-rise, 12 not
    dominant. All three gates are relative to the biggest thing in view,
    which is what deletes a population of small events."""
    assert passes7.MICRO_MIN_DEPTH_FRAC < 0.10
    assert passes7.MICRO_MIN_FALL_DOMINANCE < 0.50
    assert passes7.MICRO_MIN_RISE_FRAC < 0.50


def test_micro_still_refuses_to_buy_events_with_dirty_windows():
    """Sensitivity that reintroduces burst windows is the defect the
    purity metric exists to catch."""
    assert 0.5 < passes7.MICRO_MIN_PURITY < 1.0


def test_micro_segments_are_a_fraction_of_the_span_not_fixed_seconds():
    """The winning segment is 100 s on ID 26, 200 s on ID 28 and 30 s on
    ID 385; a fixed ladder would be three different wrong answers."""
    assert all(0 < f < 1 for f in passes7.MICRO_SEGMENT_FRACTIONS)
    assert len(passes7.MICRO_SEGMENT_FRACTIONS) >= 4


def test_a_lone_inverted_detection_is_not_a_family():
    assert passes7.MIN_INVERTED_FAMILY == 2


def test_the_micro_pass_has_its_own_key_so_it_cannot_overwrite_another():
    keys = {passes7.motif_key(26, 7, p, 1000) for p in passes7.PASS_ORDER}
    assert len(keys) == len(passes7.PASS_ORDER)
    assert passes7.PASS_MICRO in passes7.PASS_ORDER
