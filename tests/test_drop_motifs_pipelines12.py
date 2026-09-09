"""drop_motifs12a's Task 3 machinery: what STEP 4 shades, and how it is chosen.

Two things are being pinned here.

`casestudy9.plot_pipeline` gained a `store_rows` argument, and `casestudy9`
is shared with `run_drop10_casestudies` and the three `run_casestudy9*`
scripts. The test that matters is therefore as much "the default path did
not move" as "the new path works".

`pipelines12.choose_sequences` has to be reproducible from a seed and a
species alone. Its draw is over the SORTED remaining keys precisely so that
it does not depend on the order `sequences.csv` happens to be in, and that
is the property worth a test - a seeded choice that silently depends on
input order is not seeded at all.
"""

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest

from Pipelines.drop_motifs import casestudy9, pipelines12


def _channel(fs=10.0, n=1200, period=120, depth=1.0):
    """A sawtooth: slow ramp up, one-sample-per-step fall. Drops on purpose."""
    x = np.zeros(n)
    for start in range(0, n, period):
        rise = min(period - 20, n - start)
        x[start:start + rise] = np.linspace(0.0, depth, rise)
        fall_at = start + rise
        fall = min(20, n - fall_at)
        if fall > 0:
            x[fall_at:fall_at + fall] = np.linspace(depth, 0.0, fall)
    return x / 1000.0          # volts, as everything below Working/ expects


def _replay(x, fs=10.0, start=0, stop=None):
    stop = len(x) if stop is None else stop
    return casestudy9.replay_window(
        x, fs, start, stop, catalogue_id=1, recording_id=1,
        source_file="synthetic.npy", channel=0, span_key="id001",
        span_label="synthetic")


def test_store_rows_replaces_the_replayed_detections(tmp_path):
    """STEP 4 shades exactly the rows handed in, and says it did."""
    x = _channel()
    replay = _replay(x)
    store_rows = [
        {"event_id": "e0", "onset_idx": 100, "trough_idx": 118,
         "pass_key": "base", "drop_depth_mv": 1.0},
        {"event_id": "e1", "onset_idx": 220, "trough_idx": 238,
         "pass_key": "fine", "drop_depth_mv": 0.9},
    ]
    _path, info = casestudy9.plot_pipeline(
        replay, x, tmp_path / "with_store.png", title="t",
        store_rows=store_rows)

    assert info["rows_from_store"] is True
    assert info["n_detected"] == len(store_rows)


def test_the_default_path_is_unchanged(tmp_path):
    """No `store_rows`: the replay's own detections, as every caller had."""
    x = _channel()
    replay = _replay(x)
    _path, info = casestudy9.plot_pipeline(
        replay, x, tmp_path / "default.png", title="t")

    assert info["rows_from_store"] is False
    assert info["n_detected"] == len(replay["rows"])


def test_the_panel_states_its_millivolts_per_second(tmp_path):
    """Drawing rule 3: the scale is stated, in `style7`'s own words."""
    x = _channel()
    replay = _replay(x)
    store_rows = [{"event_id": "e0", "onset_idx": 100, "trough_idx": 118,
                   "pass_key": "base", "drop_depth_mv": 1.0}]
    _path, info = casestudy9.plot_pipeline(
        replay, x, tmp_path / "shape.png", title="t", store_rows=store_rows)

    shape = info["panel_event_shape"]
    assert shape["mv_as_seconds"] > 0
    assert shape["median_height_to_width"] > 0
    assert "1 mV drawn as" in shape["caption"]


def _sequences():
    return [
        {"sequence_key": "reishi_id903_ch3_606s", "species": "reishi"},
        {"sequence_key": "reishi_id901_ch1_461s", "species": "reishi"},
        {"sequence_key": "reishi_zz_1", "species": "reishi"},
        {"sequence_key": "reishi_aa_2", "species": "reishi"},
        {"sequence_key": "oyster_id10_ch3_1362824s", "species": "oyster"},
    ]


def test_preferred_sequences_are_taken_first():
    chosen = pipelines12.choose_sequences(_sequences(), "reishi", n=3)
    keys = [s["sequence_key"] for s in chosen]
    assert keys[:2] == ["reishi_id901_ch1_461s", "reishi_id903_ch3_606s"]
    assert len(keys) == 3


def test_the_draw_does_not_depend_on_input_order():
    """The seeded part is a permutation of the SORTED remainder.

    Otherwise "seed 20260904" means a different three sequences every time
    `sequences.csv` is regenerated in a different order, which is the whole
    failure a seed is there to prevent.
    """
    forward = pipelines12.choose_sequences(_sequences(), "reishi", n=3)
    backward = pipelines12.choose_sequences(
        list(reversed(_sequences())), "reishi", n=3)
    assert ([s["sequence_key"] for s in forward]
            == [s["sequence_key"] for s in backward])


@pytest.mark.parametrize("duration_s, expected_at_least", [(400.0, 400.0),
                                                           (4.0, 60.0)])
def test_a_short_sequence_still_gets_a_usable_window(duration_s,
                                                     expected_at_least):
    """A five-event Reishi run 2 s wide cannot derive a scale from 2 s."""
    sequence = {"start_onset_s": 1000.0,
                "end_onset_s": 1000.0 + duration_s}
    start, stop = pipelines12.window_for(sequence, 10.0)
    assert (stop - start) / 10.0 >= expected_at_least
    # and the sequence sits strictly inside it
    assert start < 1000.0 * 10
    assert stop > (1000.0 + duration_s) * 10


def test_the_replay_window_is_capped_near_the_detection_window():
    """A pipeline figure must illustrate the parameterisation that ran.

    `casestudy9.replay_window` re-derives the detector's parameters from the
    window it is handed. A Lion's mane sequence spans hours where the
    detection window was 120 s, and replaying the whole span does not
    illustrate that detection - on the measured case it does not run at all,
    because the base pass derives a two-sample segment and dSAX refuses it.
    """
    sequence = {"start_onset_s": 1_670_000.0, "end_onset_s": 1_673_000.0}
    uncapped = pipelines12.window_for(sequence, 10.0)
    capped = pipelines12.window_for(sequence, 10.0, max_window_s=480.0)

    assert (uncapped[1] - uncapped[0]) / 10.0 > 3000
    assert (capped[1] - capped[0]) / 10.0 == pytest.approx(480.0, abs=1.0)
    # ...and it is centred on the run, not clipped off its front.
    centre = (capped[0] + capped[1]) / 2.0 / 10.0
    assert centre == pytest.approx(1_671_500.0, abs=1.0)


def test_a_short_sequence_is_not_stretched_by_the_cap():
    sequence = {"start_onset_s": 100.0, "end_onset_s": 200.0}
    lo, hi = pipelines12.window_for(sequence, 10.0, max_window_s=480.0)
    assert (hi - lo) / 10.0 == pytest.approx(150.0, abs=1.0)


def test_a_capped_window_lands_where_the_events_are():
    """On a sparse corpus the midpoint is the wrong place to put the window.

    Lion's mane region B averages one event per 400 s. Dropping a 480 s
    window on the midpoint of a multi-hour run held ONE event, which is not
    enough for the figure to show anything about the detector.
    """
    sequence = {"start_onset_s": 0.0, "end_onset_s": 3600.0}
    # Nine events bunched near the end, one stray at the start.
    onsets = [0.0] + [3000.0 + 40.0 * i for i in range(9)]
    lo, hi = pipelines12.window_for(sequence, 10.0, max_window_s=480.0,
                                    onsets_s=onsets)
    inside = [o for o in onsets if lo / 10.0 <= o <= hi / 10.0]
    assert len(inside) == 9

    midpoint_only = pipelines12.window_for(sequence, 10.0, max_window_s=480.0)
    inside_mid = [o for o in onsets
                  if midpoint_only[0] / 10.0 <= o <= midpoint_only[1] / 10.0]
    assert len(inside_mid) < len(inside)
