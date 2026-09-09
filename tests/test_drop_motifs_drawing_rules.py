"""drop_motifs12b's shared drawing rules.

Round 11's figures failed review for three drawing faults and each of them
is pinned here, because each is invisible in a passing figure script: a
resample, a crop and an offset all produce a picture, just not the right
one.

  - `phase_trace` must return the event's OWN samples. A six-sample fall
    that comes back as 200 points is the round-11 Reishi curve - five
    straight segments dressed up as a waveform.
  - `phase_trace` must carry the approach and the recovery. Cropping to
    onset->trough is what made three species look identical.
  - `waterfall_offset` must be under one drawn peak-to-peak. Round 11's was
    about four, which flattens every trace whatever the panel's shape.

Plus rule 9 itself, as an assertion: the median event of a locked panel is
drawn between 1:1 and 3:1 height-to-width.
"""

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
from matplotlib import pyplot as plt

from Pipelines.drop_motifs import drawing_rules


FS = 10.0


def _event(event_id, *, fall_samples=6, depth_mv=3.0, pre=40, post=60,
           fs=FS, onset_idx=1000):
    """One synthetic drop: flat shoulder, linear fall, exponential recovery.

    Returned in the store's own shape - a row plus the `{field: array}`
    entry `motifs5.load_store` yields - so the functions under test are
    exercised through exactly the interface the figures use.
    """
    fall = np.linspace(0.0, -depth_mv, fall_samples + 1)[1:]
    recovery = -depth_mv * np.exp(-np.arange(post) / (post / 4.0))
    values = np.concatenate([np.zeros(pre), fall, recovery])
    row = {
        "event_id": event_id,
        "fs": fs,
        "onset_idx": onset_idx,
        "trough_idx": onset_idx + fall_samples,
        "snippet_start_idx": onset_idx - pre,
        "snippet_end_idx": onset_idx - pre + values.size,
        "drop_depth_mv": depth_mv,
        "fall_duration_s": fall_samples / fs,
        "onset_s": onset_idx / fs,
        "channel": 0,
        "species": "test",
    }
    return row, {event_id: {"detrended_mv": values, "raw_mv": values}}


# --------------------------------------------------------------------------
# rule 1 - nothing is resampled
# --------------------------------------------------------------------------

def test_phase_trace_keeps_the_events_own_samples():
    """A six-sample fall is drawn with six samples in the fall, not 200."""
    row, snippets = _event("e", fall_samples=6)
    phase, z = drawing_rules.phase_trace(row, snippets)
    in_fall = (phase >= 0.0) & (phase <= 1.0)
    assert 5 <= int(in_fall.sum()) <= 8, (
        "the fall must be drawn at its own resolution; "
        f"got {int(in_fall.sum())} points")
    # And the spacing is uniform, which a resample onto a fixed grid of a
    # different length would not be.
    steps = np.diff(phase)
    assert np.allclose(steps, steps[0])


def test_a_long_and_a_short_event_are_drawn_at_their_own_lengths():
    """Two events of different sample count come back different lengths.

    The round-11 feature vector made both exactly 200 points, which is the
    property that made them indistinguishable on the page.
    """
    short_row, short_snips = _event("short", fall_samples=6)
    long_row, long_snips = _event("long", fall_samples=90, pre=200, post=300)
    short_phase, _ = drawing_rules.phase_trace(short_row, short_snips)
    long_phase, _ = drawing_rules.phase_trace(long_row, long_snips)
    assert long_phase.size > 5 * short_phase.size


# --------------------------------------------------------------------------
# rules 2 and 5 - the approach and the recovery are in frame
# --------------------------------------------------------------------------

def test_phase_trace_spans_minus_half_to_one_and_a_half():
    row, snippets = _event("e")
    phase, _z = drawing_rules.phase_trace(row, snippets)
    assert phase.min() <= -0.4, "the approach was cropped out"
    assert phase.max() >= 1.4, "the recovery was cropped out"
    assert phase.min() >= drawing_rules.PHASE_LO - 1e-9
    assert phase.max() <= drawing_rules.PHASE_HI + 1e-9


def test_framed_trace_is_never_cropped_to_onset_trough():
    row, snippets = _event("e")
    t, _y, complete = drawing_rules.framed_trace(row, snippets)
    fall = drawing_rules.fall_duration_s(row)
    assert t.min() < 0.0
    assert t.max() > fall
    assert complete is True


def test_framed_trace_reports_an_incomplete_frame():
    """A stored window shorter than the frame says so rather than pretending."""
    row, snippets = _event("e", pre=2, post=3)
    _t, _y, complete = drawing_rules.framed_trace(row, snippets)
    assert complete is False


def test_normalisation_uses_the_falls_own_statistics():
    """z is standardised on the fall, not on however much quiet is included.

    Two copies of one event framed in windows of very different length must
    give the same drawn shape; a frame-wide sd would rescale one of them by
    the length of its own window.
    """
    tight_row, tight = _event("tight", pre=30, post=45)
    loose_row, loose = _event("loose", pre=300, post=45)
    _p1, z1 = drawing_rules.phase_trace(tight_row, tight)
    _p2, z2 = drawing_rules.phase_trace(loose_row, loose)
    assert np.isclose(z1.min(), z2.min(), rtol=1e-6)


# --------------------------------------------------------------------------
# rule 6 - the offset
# --------------------------------------------------------------------------

def test_waterfall_offset_is_below_one_drawn_peak_to_peak():
    rows, snippets = [], {}
    for index in range(6):
        row, snips = _event(f"e{index}", depth_mv=3.0 + 0.1 * index)
        rows.append(row)
        snippets.update(snips)
    traces = [drawing_rules.framed_trace(r, snippets)[:2] for r in rows]
    offset = drawing_rules.waterfall_offset(traces)
    spans = [float(np.ptp(y)) for _t, y in traces]
    assert offset < float(np.median(spans)), (
        "successive traces must overlap; round 11's offset was ~4x this")
    assert offset == pytest.approx(0.8 * float(np.median(spans)))


def test_thin_keeps_the_ends_and_states_k():
    members = list(range(103))
    drawn, k = drawing_rules.thin(members)
    assert len(drawn) <= drawing_rules.MAX_TRACES
    assert drawn[0] == 0 and drawn[-1] == 102, (
        "a sequence's ends are the finding; a prefix throws one away")
    assert k > 1


def test_thin_leaves_a_short_sequence_alone():
    drawn, k = drawing_rules.thin(list(range(9)))
    assert len(drawn) == 9 and k == 1


# --------------------------------------------------------------------------
# rules 3, 4 and 9 - the aspect, and the smoke test the work order asks for
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth_mv,fall_samples", [
    (0.3, 7),        # Reishi-scale: shallow and fast
    (13.0, 60),      # oyster-scale: deep and slow
    (1.9, 11),       # Lion's mane region B: narrow and sharp
])
def test_median_event_is_drawn_between_one_and_three_to_one(depth_mv,
                                                            fall_samples):
    """Rule 9. Three scales three orders of magnitude apart, one rule."""
    rows, snippets = [], {}
    for index in range(5):
        row, snips = _event(f"e{index}", depth_mv=depth_mv * (1.0 + 0.05 * index),
                            fall_samples=fall_samples,
                            pre=4 * fall_samples, post=6 * fall_samples)
        rows.append(row)
        snippets.update(snips)

    aspect, drawn, _capped = drawing_rules.figure_aspect(rows)
    ok, why = drawing_rules.check_drop_shape(drawn)
    assert ok, why
    assert drawing_rules.MIN_RATIO <= drawn <= drawing_rules.MAX_RATIO

    # And the aspect actually reaches an axes and survives being drawn.
    fig, ax = plt.subplots(figsize=(3.0, 4.0))
    for row in rows:
        t, y, _ = drawing_rules.framed_trace(row, snippets)
        ax.plot(t, y)
    drawing_rules.apply_aspect(ax, aspect)
    assert ax.get_aspect() == pytest.approx(aspect)
    plt.close(fig)


def test_drawn_ratio_follows_the_aspect():
    rows, snippets = [], {}
    for index in range(4):
        row, snips = _event(f"e{index}")
        rows.append(row)
        snippets.update(snips)
    aspect, drawn, _capped = drawing_rules.figure_aspect(rows)
    assert drawing_rules.drawn_ratio(aspect, rows) == pytest.approx(drawn)
    assert drawing_rules.drawn_ratio(2 * aspect, rows) == pytest.approx(2 * drawn)


def test_check_drop_shape_rejects_a_flat_panel():
    ok, why = drawing_rules.check_drop_shape(0.2)
    assert not ok and "flatter" in why


# --------------------------------------------------------------------------
# rule 7 - colour is graded by time and keyed by species name
# --------------------------------------------------------------------------

def test_time_colours_grade_from_light_to_dark_in_order():
    rows = [dict(onset_s=float(t)) for t in (0.0, 10.0, 20.0, 30.0)]
    colours, norm, _cmap = drawing_rules.time_colours(rows, "reishi")
    assert len(colours) == 4
    brightness = [sum(c[:3]) for c in colours]
    assert brightness == sorted(brightness, reverse=True)
    assert norm.vmin == 0.0 and norm.vmax == pytest.approx(30.0)


def test_species_ramp_is_keyed_by_name_not_position():
    """A species keeps its hue whatever else is in the store."""
    one = drawing_rules.species_ramp("oyster")(0.5)
    two = drawing_rules.species_ramp("oyster")(0.5)
    assert one == two
    assert drawing_rules.species_ramp("reishi")(0.5) != one
