"""
drop_motifs7.3: the page is fitted to the panels, not the panels to the page.

Three separate faults, three groups of tests.

1. A panel whose height-to-width ratio is locked shrinks inside a fixed
   gridspec cell, so ID 22's overlay page came out as five slivers adrift
   in white space and the bottom row sat hard against the left margin.
   The geometry has to be solved BEFORE the figure is made, so the figure
   can be sized to it and the rows centred.

2. The dendrogram's merge-distance axis was linear, so on ID 22 the single
   root merge occupied the top third of an A4 page on its own.

3. The rose's mean direction was a legend key drawn as a horizontal swatch
   in the bottom-left corner, which says nothing about an angle.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import style73


# ---------------------------------------------------------------------------
# 1. panel geometry
# ---------------------------------------------------------------------------

def test_an_unconstrained_panel_gets_the_box_its_shape_asks_for():
    """height/width = aspect * y range / x range, and nothing is distorted."""
    aspect, x_range, y_range = 24.4, 300.0, 5.0
    w, h, fill, distortion = style73.panel_box(aspect, x_range, y_range)

    assert h / w == pytest.approx(aspect * y_range / x_range, rel=1e-9)
    assert distortion == pytest.approx(1.0, rel=1e-9)
    # `fill` is what set_aspect must be given to fill exactly this box.
    assert fill == pytest.approx(aspect, rel=1e-9)


def aspect_fill(w, h, x_range, y_range):
    return (h / w) * (x_range / y_range)


def test_a_sliver_reaches_the_lower_bound_by_growing_not_by_stretching():
    """ID 22's purple family, measured: about an inch wide at 7.2's fixed
    panel height. It must reach the readable width, and the first way to
    get there is a BIGGER panel, not a stretched one."""
    aspect, x_range, y_range = 24.38, 302.0, 32.0
    w, h, fill, distortion = style73.panel_box(aspect, x_range, y_range)

    assert w >= style73.PANEL_MIN_WIDTH_IN - 1e-9
    assert h > style73.PANEL_HEIGHT_IN          # grew, rather than stretched
    # Growth is what buys the readable width here: stretching alone would
    # have spent the whole allowance and still fallen short of the floor.
    assert max(distortion, 1.0 / distortion) < style73.MAX_DISTORTION
    assert fill == pytest.approx(aspect_fill(w, h, x_range, y_range), rel=1e-9)


def test_the_stretch_is_capped_rather_than_unbounded():
    """The bounds are goals; the cap is the rule. Widening without a
    ceiling would make a 60:1 motif a square and call it the recording."""
    for aspect, x_range, y_range in ((1e5, 10.0, 10.0),      # absurdly tall
                                     (0.01, 1000.0, 2.0)):   # absurdly flat
        _, _, _, distortion = style73.panel_box(aspect, x_range, y_range)
        assert max(distortion, 1.0 / distortion) == pytest.approx(
            style73.MAX_DISTORTION, rel=1e-6)


def test_a_wide_flat_panel_is_capped_in_width_not_run_off_the_page():
    w, _, _, _ = style73.panel_box(aspect=0.01, x_range=1000.0, y_range=2.0)
    assert w <= style73.PANEL_MAX_WIDTH_IN + 1e-9


def test_nothing_measurable_falls_back_to_a_default_box():
    w, h, fill, distortion = style73.panel_box(0.0, 0.0, 0.0)
    assert w > 0 and h > 0
    assert distortion == 1.0


def test_a_row_of_boxes_is_centred_and_never_overlaps():
    lefts = style73.centred_row([3.0, 5.0, 2.0], gap=0.5, total=14.0)

    assert len(lefts) == 3
    for i, (left, width) in enumerate(zip(lefts, [3.0, 5.0, 2.0])):
        if i:
            assert left >= lefts[i - 1] + [3.0, 5.0, 2.0][i - 1] - 1e-9
    span_lo = lefts[0]
    span_hi = lefts[-1] + 2.0
    assert span_lo == pytest.approx(14.0 - span_hi, abs=1e-9)


def test_a_row_wider_than_the_page_starts_at_the_left_margin():
    lefts = style73.centred_row([9.0, 9.0], gap=0.5, total=10.0)
    assert lefts[0] == pytest.approx(0.0, abs=1e-9)


def test_the_caption_names_the_direction_of_any_extra_stretch():
    # distortion = fill aspect / true aspect: above 1 the panel is
    # drawn taller than the recording, below 1 wider.
    assert "taller" in style73.distortion_caption(1.6).lower()
    assert "wider" in style73.distortion_caption(1 / 1.6).lower()
    assert style73.distortion_caption(1.0) == ""


# ---------------------------------------------------------------------------
# 2. the merge-distance axis
# ---------------------------------------------------------------------------

def _id022_merges():
    """Ward heights with the shape that caused the white space: a long tail
    of small merges and one root merge far above everything."""
    return np.concatenate([np.linspace(0.1, 3.0, 40), [22.0]])


def test_the_scale_is_monotone_and_invertible():
    forward, inverse = style73.rank_scale_functions(_id022_merges())
    probe = np.linspace(0.0, 25.0, 200)
    mapped = forward(probe)

    assert np.all(np.diff(mapped) > 0)
    assert inverse(mapped) == pytest.approx(probe, abs=1e-6)


def test_the_root_merge_stops_owning_a_third_of_the_page():
    """The whole point: on a linear axis the top merge takes 86% of the
    height. Ranked, it takes a single interval like any other merge."""
    heights = _id022_merges()
    forward, _ = style73.rank_scale_functions(heights)

    top = float(heights.max())
    second = float(np.sort(heights)[-2])
    linear_share = (top - second) / top
    ranked_share = ((forward(np.array([top]))[0]
                     - forward(np.array([second]))[0])
                    / forward(np.array([top]))[0])

    assert linear_share > 0.8
    assert ranked_share < 0.35
    assert ranked_share < linear_share / 2


def test_the_small_merges_gain_the_room_the_root_gave_up():
    heights = _id022_merges()
    forward, _ = style73.rank_scale_functions(heights)
    low = np.sort(heights)[:10]

    linear = (low[-1] - low[0]) / heights.max()
    ranked = ((forward(low[-1:])[0] - forward(low[:1])[0])
              / forward(np.array([heights.max()]))[0])
    assert ranked > linear * 2


def test_a_degenerate_set_of_merges_falls_back_to_identity():
    forward, inverse = style73.rank_scale_functions([2.0])
    probe = np.array([0.0, 1.0, 5.0])
    assert forward(probe) == pytest.approx(probe)
    assert inverse(probe) == pytest.approx(probe)


def test_values_outside_the_merge_range_are_extrapolated_not_clipped():
    """The axis needs headroom above the root merge for the title and the
    padding, and clipping would pile every padded value on one line."""
    forward, _ = style73.rank_scale_functions(_id022_merges())
    assert forward(np.array([30.0]))[0] > forward(np.array([22.0]))[0]
    assert forward(np.array([-1.0]))[0] < forward(np.array([0.0]))[0]


# ---------------------------------------------------------------------------
# 3. the rose's mean
# ---------------------------------------------------------------------------

def test_the_mean_label_sits_at_the_mean_angle_not_in_a_corner():
    """`mean_marker` returns where to draw the marker and its label, in the
    rose's own polar coordinates - so both are on the ray by construction
    and cannot drift into a legend box."""
    theta, radius, label_theta, label_radius, rotation = style73.mean_marker(
        mean_deg=-31.0, peak_radius=14.0)

    assert theta == pytest.approx(np.deg2rad(-31.0))
    assert label_theta == pytest.approx(theta)
    assert radius > 0
    assert label_radius > radius
    assert -90.0 <= rotation <= 90.0


def test_the_label_is_readable_rather_than_upside_down():
    """A ray at -80 degrees would carry text rotated to -80, which is read
    bottom-to-top. Rotations are folded into the readable half turn."""
    for mean_deg in (-89.0, -80.0, -45.0, -5.0, 0.0):
        *_, rotation = style73.mean_marker(mean_deg, peak_radius=10.0)
        assert -90.0 <= rotation <= 90.0


def test_an_empty_rose_still_places_the_marker_somewhere_drawable():
    _, radius, _, label_radius, _ = style73.mean_marker(-45.0, peak_radius=0.0)
    assert radius > 0
    assert label_radius > radius


def test_the_shape_caption_states_one_thing_not_two_contradictory_ones():
    """ID 3's overlay said "shape as in the recording (3.8:1)" on one line
    and "drawn 1.47x wider" on the next. Both were true and referred to
    different steps, which reads as a contradiction."""
    caption = style73.shape_caption(true_ratio=3.83, compression=1.0,
                                    distortion=0.68)

    assert "3.83" not in caption or "as in the recording" not in caption
    assert "2.6:1" in caption          # what the panel shows
    assert "3.83:1" in caption         # what the recording holds


def test_an_undistorted_panel_is_still_reported_as_exact():
    caption = style73.shape_caption(3.83, 1.0, 1.0)
    assert "as in the recording" in caption
    assert "3.83:1" in caption


def test_compression_and_panel_distortion_compose_rather_than_stack_up():
    """ID 22: 10.1:1 compressed 1.7x by the aspect cap, then the panel box
    departs again. The reader is told the single number that results."""
    caption = style73.shape_caption(10.1, 1.6878, 0.625)
    drawn = 10.1 * 0.625 / 1.6878
    assert f"{drawn:.3g}:1" in caption
    assert "10.1:1" in caption
