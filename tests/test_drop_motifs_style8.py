"""
drop_motifs8: how tall a panel is allowed to be depends on how much of
the shape claim survives being drawn at all.

drop_motifs7.2 capped every panel at 6:1. That is right for a span whose
motifs are 10:1 - the panel is nearly the recording's shape. It is wrong
for catalogue ID 385, whose motifs occupy 202:1: capping at 6:1 draws the
tallest, narrowest panel the rules allow while being 34x from the truth
anyway, so the reader gets neither fidelity nor legibility.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import style7, style8


# Measured with `overlays72.span_aspect` over the drop_motifs7 library.
MEASURED_TRUE_RATIOS = {3: 3.83, 35: 3.58, 20: 4.48, 34: 6.29, 22: 10.13,
                        33: 13.59, 29: 14.37, 26: 15.73, 1: 16.35, 8: 17.30,
                        28: 18.03, 10: 28.02, 25: 68.48, 24: 69.60,
                        385: 202.56}


def test_a_ratio_inside_the_cap_is_untouched():
    for span in (3, 35, 20):
        ratio = MEASURED_TRUE_RATIOS[span]
        assert style8.readable_max_ratio(ratio) == style7.MAX_PANEL_RATIO


def test_a_nearly_faithful_panel_keeps_the_tall_cap():
    """ID 22 is 10.1:1, drawn at 6:1 - a compression of 1.7. That panel is
    still making a shape claim, so it keeps the height."""
    assert style8.readable_max_ratio(MEASURED_TRUE_RATIOS[22]) == \
        pytest.approx(style7.MAX_PANEL_RATIO)


def test_id385_is_drawn_wide_because_its_shape_claim_is_already_gone():
    """The operator's point: at 202:1 the motifs would be too tall and
    narrow to read, and 6:1 buys no fidelity when the truth is 34x away."""
    allowed = style8.readable_max_ratio(MEASURED_TRUE_RATIOS[385])

    assert allowed == pytest.approx(style8.READABLE_RATIO, rel=1e-6)
    assert allowed < style7.MAX_PANEL_RATIO / 2


def test_the_backing_off_is_gradual_not_a_cliff():
    """Two spans a hair apart in true ratio must not be drawn at wildly
    different proportions."""
    for ratio in (11.9, 12.1, 23.9, 24.1):
        near = style8.readable_max_ratio(ratio)
        far = style8.readable_max_ratio(ratio * 1.02)
        assert abs(np.log(near / far)) < 0.02


def test_more_distortion_never_buys_a_taller_panel():
    """Monotone: as the truth gets further away, the panel gets wider, not
    taller. Anything else means an unreadable span is drawn tallest."""
    ratios = sorted(MEASURED_TRUE_RATIOS.values())
    allowed = [style8.readable_max_ratio(r) for r in ratios]
    assert all(b <= a + 1e-9 for a, b in zip(allowed, allowed[1:]))


def test_the_floor_is_a_readable_proportion_not_a_square():
    """Backing off entirely to 1:1 would say the motifs are as wide as
    they are tall, which is its own false claim."""
    assert 1.0 < style8.READABLE_RATIO < style7.MAX_PANEL_RATIO
    for ratio in (500.0, 5000.0):
        assert style8.readable_max_ratio(ratio) == \
            pytest.approx(style8.READABLE_RATIO, rel=1e-6)


def test_a_ratio_that_cannot_be_measured_falls_back_to_the_cap():
    assert style8.readable_max_ratio(float("nan")) == style7.MAX_PANEL_RATIO
    assert style8.readable_max_ratio(0.0) == style7.MAX_PANEL_RATIO


# ---------------------------------------------------------------------------
# the pooled figures need one colour per span
# ---------------------------------------------------------------------------

def test_every_span_gets_its_own_colour():
    spans = [1, 3, 8, 10, 20, 21, 22, 24, 25, 26, 28, 29, 33, 34, 35, 385]
    colours = style8.span_colours(spans)

    assert set(colours) == set(spans)
    assert len({tuple(np.round(c, 4)) for c in colours.values()}) == len(spans)


def test_the_span_colours_avoid_the_excluded_hues():
    """Red, yellow, black and white, same rule as the family ramps."""
    import matplotlib.colors as mcolors

    for colour in style8.span_colours(list(range(16))).values():
        h, s, v = mcolors.rgb_to_hsv(mcolors.to_rgb(colour))
        assert 0.12 < v < 0.95                      # not black, not white
        near_red = min(h, 1.0 - h) < 15.0 / 360.0
        assert not (near_red and s > 0.35)
        assert not (0.12 < h < 0.20 and s > 0.35)   # not yellow


def test_the_colour_for_a_span_does_not_move_when_another_is_added():
    """A pooled figure and a per-span figure have to agree, and a rerun
    over a subset must not recolour everything."""
    full = style8.span_colours([1, 3, 10, 385])
    subset = style8.span_colours([1, 3, 10, 385, 22, 25])
    assert full[3] == subset[3]
    assert full[385] == subset[385]
