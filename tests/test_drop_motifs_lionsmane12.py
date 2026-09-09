"""Lion's mane corpus (drop_motifs12a) — the facts that had to be measured.

Three things about `L_LM_Jul_26_J_raw_fs10` are not derivable from the
recordings table, because the recording is not IN the recordings table, and
each one silently corrupts every number downstream if it is assumed instead:

  1. THE CHANNELS ARE IN MILLIVOLTS. Every other `.npy` under
     `DATA/derived/channels/` is in volts and `motifs5.rows_and_arrays`
     multiplies by 1000 on that basis. Feeding these arrays in raw makes
     every depth, every floor and every slope 1000x too large.

  2. fs IS 10.0 Hz, and this is the check that establishes it rather than
     the inferred sample-count-over-plotted-duration argument in the
     channel manifest.

  3. CATALOGUE ID 385 IS A 1 Hz EXCERPT OF CH2, and its position is
     measurable rather than believed.

All three are one measurement: id385 block-mean-decimated 10:1 out of CH2
reproduces the 1 Hz export almost exactly. The gain of that fit is the unit
check, the sharpness of the correlation peak is the rate check, and its
location is the excerpt's position.
"""

import os

import numpy as np
import pytest

from Pipelines.drop_motifs import lionsmane12

DATA = os.path.join("DATA", "derived", "channels", lionsmane12.STEM)
pytestmark = pytest.mark.skipif(
    not os.path.isdir(DATA),
    reason=f"{DATA} is not provisioned in this worktree")


def test_channels_load_in_volts_not_millivolts():
    """The stored array is millivolts; `load_channel` must hand back volts.

    The guard is the recording's own peak-to-peak. CH3 swings about 450 mV
    over the whole recording, so a correct load is order 0.1-1.0 V and an
    uncorrected one is order 100-1000 "volts" - three orders apart, which
    no threshold can straddle by accident.
    """
    x = lionsmane12.load_channel(3, start=7_400_000, stop=7_600_000)
    assert np.max(np.abs(x)) < 1.0, "channel did not come back in volts"

    raw = lionsmane12.load_channel_native(3, start=7_400_000, stop=7_600_000)
    assert np.allclose(raw / lionsmane12.NATIVE_UNITS_PER_VOLT, x)
    assert np.max(np.abs(raw)) > 1.0, "the stored array is not millivolts"


def test_id385_is_an_excerpt_of_ch2_and_that_fixes_the_sample_rate():
    """`locate_id385` finds the excerpt, and the fit is a unit/rate check.

    A 10:1 block mean of CH2 against the 1 Hz export is a near-perfect
    match ONLY if the rate really is 10.0 Hz: over four hours a rate error
    of even 0.1% would walk the two traces 14 samples apart and smear the
    peak. The gain of the same fit is 1.000 only if both are millivolts.
    """
    found = lionsmane12.locate_id385()

    assert found["r"] > 0.99
    assert abs(found["gain"] - 1.0) < 0.01, "the unit fit is not 1:1 in mV"
    assert found["channel"] == 2
    # Region B is 1.376e7 - 1.71e7; the excerpt must lie inside it.
    lo, hi = lionsmane12.REGIONS["B"].start, lionsmane12.REGIONS["B"].stop
    assert lo <= found["start_idx"] < found["stop_idx"] <= hi


def test_regions_are_inside_the_recording_and_name_their_channel():
    for key, region in lionsmane12.REGIONS.items():
        assert region.key == key
        assert 0 <= region.start < region.stop <= lionsmane12.N_SAMPLES
        assert region.channel in range(lionsmane12.N_CHANNELS)


# ---------------------------------------------------------------------------
# detecting over a REGION rather than a whole channel
# ---------------------------------------------------------------------------

def _sawtooth(n=6000, period=300, depth=1.0):
    """Slow ramp, sharp fall. Volts, as everything below Working/ expects."""
    x = np.zeros(n)
    for start in range(0, n, period):
        rise = min(period - 20, n - start)
        x[start:start + rise] = np.linspace(0.0, depth, rise)
        at = start + rise
        fall = min(20, n - at)
        if fall > 0:
            x[at:at + fall] = np.linspace(depth, 0.0, fall)
    return x / 1000.0


def test_detect_sliding_can_report_indices_absolute_in_the_channel():
    """A region is a SLICE, and the store's indices must not be slice-relative.

    `passes9.detect_sliding` offsets every index by the window's start
    within the array it was handed. On Fig2A that array is the whole
    channel, so slice-relative and absolute coincide and the distinction has
    never mattered. A Lion's mane region starts 13.76 million samples into
    its channel, and a store whose `onset_idx` is 13.76 million short would
    point every figure, every sequence and every ID 385 comparison at the
    wrong part of the recording - while looking entirely well-formed.

    `base_offset` is added on top of the window start, so the rows come back
    in channel coordinates. The event ids carry the same absolute onset, or
    the id and the row would disagree about where the event is.
    """
    from Pipelines.drop_motifs import passes9

    x = _sawtooth()
    common = dict(catalogue_id=910, recording_id=lionsmane12.RECORDING_ID,
                  source_file="synthetic.npy", channel=2, window_s=120.0,
                  span_label="region", span_key="region_B_CH2")

    at_zero, _arrays, _info = passes9.detect_sliding(x, 10.0, **common)
    offset = 13_760_000
    shifted, _arrays2, _info2 = passes9.detect_sliding(
        x, 10.0, base_offset=offset, **common)

    assert at_zero, "the fixture produced no detections to compare"
    assert len(shifted) == len(at_zero)

    for before, after in zip(at_zero, shifted):
        for field in ("onset_idx", "trough_idx", "snippet_start_idx",
                      "snippet_end_idx", "window_start_idx", "window_end_idx"):
            assert int(after[field]) == int(before[field]) + offset, field
        # The id embeds the onset; it has to move with it.
        assert str(int(after["onset_idx"])) in after["event_id"]
        # ...and the framing tie-break must be computed in one frame, not
        # against a window whose bounds moved and an onset that did not.
        assert after["window_centre_frac"] == pytest.approx(
            before["window_centre_frac"])


def test_base_offset_defaults_to_zero_so_fig2a_is_unchanged():
    from Pipelines.drop_motifs import passes9

    x = _sawtooth()
    common = dict(catalogue_id=900, recording_id=466,
                  source_file="Fig2A_dt0p1.csv", channel=1, window_s=120.0,
                  span_label="CH1", span_key="id900")
    plain, _a, _i = passes9.detect_sliding(x, 10.0, **common)
    explicit, _a2, _i2 = passes9.detect_sliding(x, 10.0, base_offset=0,
                                                **common)
    assert [r["event_id"] for r in plain] == [r["event_id"] for r in explicit]
