"""
drop_motifs7.2: a motif is drawn the shape it is in the recording.

drop_motifs7 locked the height-to-width ratio to a fixed target, which
made every motif the same proportion regardless of what it looked like.
On catalogue ID 3 that drew a spike nearly four times taller than wide as
nearly twice as wide as tall. These tests pin the measurement that
replaces the target.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import style7


def _id003():
    """Catalogue ID 3, measured: 8579 s and 21.1 mV in a 13.5 x 2.6 in box,
    median motif 7.1 mV over 145 s."""
    return dict(span_seconds=8579.0, span_mv=21.1, width_in=13.5,
                height_in=2.6, depths_mv=[7.1], falls_s=[145.0])


def test_the_drawn_ratio_matches_the_span_panels_own_ratio():
    """The whole point: what the reader sees in the recording is what the
    overlay reproduces."""
    p = _id003()
    aspect, true_ratio, compression = style7.span_locked_aspect(**p)

    # Worked independently of the implementation: seconds per inch over
    # millivolts per inch, times depth over duration.
    expected = ((p["span_seconds"] / p["width_in"])
                / (p["span_mv"] / p["height_in"])) * 7.1 / 145.0

    assert true_ratio == pytest.approx(expected, rel=1e-9)
    assert true_ratio == pytest.approx(3.83, abs=0.05)
    assert compression == 1.0
    assert aspect * 7.1 / 145.0 == pytest.approx(true_ratio, rel=1e-9)


def test_id003_is_drawn_taller_than_wide_not_wider_than_tall():
    """The operator's own description of the defect, as an assertion."""
    aspect, true_ratio, _ = style7.span_locked_aspect(**_id003())

    assert true_ratio > 2.0
    # The drop_motifs7 target it replaces drew everything at 0.55 : 1.
    assert style7.TARGET_MEDIAN_RATIO < 1.0
    assert true_ratio > style7.TARGET_MEDIAN_RATIO * 5


def test_an_extreme_ratio_is_compressed_and_the_compression_is_reported():
    """ID 22's motifs genuinely occupy about 10:1; a 10:1 panel shows
    nothing, so it is compressed - and the caller is told, so the figure
    can say so instead of presenting it as exact."""
    aspect, true_ratio, compression = style7.span_locked_aspect(
        span_seconds=9317.0, span_mv=43.6, width_in=13.5, height_in=2.6,
        depths_mv=[22.7], falls_s=[54.0])

    assert true_ratio > style7.MAX_PANEL_RATIO
    assert compression > 1.0
    assert aspect * 22.7 / 54.0 == pytest.approx(style7.MAX_PANEL_RATIO,
                                                 rel=1e-9)


def test_the_adjustment_is_always_a_magnitude_never_below_one():
    """Returning ratio/min_ratio for the expanded case gave a number below
    1, which prints as "compressed by less than nothing"."""
    for depth in (0.01, 0.04, 22.7, 7.1):
        _, _, adjustment = style7.span_locked_aspect(
            span_seconds=9317.0, span_mv=43.6, width_in=13.5, height_in=2.6,
            depths_mv=[depth], falls_s=[54.0])
        assert adjustment >= 1.0


def test_an_expanded_panel_is_not_described_as_compressed():
    assert "expanded" in style7.fidelity_caption(0.05, 8.0)
    assert "compressed" in style7.fidelity_caption(10.1, 1.7)


def test_a_very_flat_motif_is_expanded_rather_than_drawn_as_a_line():
    aspect, true_ratio, compression = style7.span_locked_aspect(
        span_seconds=100000.0, span_mv=5.0, width_in=13.5, height_in=2.6,
        depths_mv=[0.04], falls_s=[900.0])

    assert true_ratio < style7.MIN_PANEL_RATIO
    assert compression > 1.0
    assert aspect * 0.04 / 900.0 == pytest.approx(style7.MIN_PANEL_RATIO,
                                                  rel=1e-9)


def test_a_ratio_inside_the_bounds_is_reproduced_exactly():
    for depth, fall in ((7.1, 145.0), (10.0, 200.0), (4.0, 90.0)):
        aspect, true_ratio, compression = style7.span_locked_aspect(
            span_seconds=8579.0, span_mv=21.1, width_in=13.5, height_in=2.6,
            depths_mv=[depth], falls_s=[fall])
        if style7.MIN_PANEL_RATIO <= true_ratio <= style7.MAX_PANEL_RATIO:
            assert compression == 1.0
            assert aspect * depth / fall == pytest.approx(true_ratio)


def test_nothing_measurable_falls_back_rather_than_dividing_by_zero():
    aspect, true_ratio, compression = style7.span_locked_aspect(
        span_seconds=0.0, span_mv=0.0, width_in=0.0, height_in=0.0,
        depths_mv=[], falls_s=[])
    assert aspect == 1.0
    assert np.isnan(true_ratio)
    assert compression == 1.0


def test_the_caption_distinguishes_an_exact_panel_from_a_compressed_one():
    assert "as in the recording" in style7.fidelity_caption(3.8, 1.0)
    assert "compressed" in style7.fidelity_caption(10.1, 1.7)
    assert "10.1:1" in style7.fidelity_caption(10.1, 1.7)
    assert "not locked" in style7.fidelity_caption(float("nan"), 1.0)


def test_uniform_boxes_and_true_shape_use_datalim_not_box():
    """A row of family panels must be the same size AND keep the shape.
    Box-adjustment gives up the first; datalim gives up only margin."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    style7.apply_aspect(ax, 4.0, adjustable="datalim")
    assert ax.get_aspect() == 4.0
    assert ax.get_adjustable() == "datalim"
    plt.close(fig)
