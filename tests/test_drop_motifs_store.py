"""
test_drop_motifs_store.py
==========================
Round-trip tests for the drop-motif event store
(`Working.Detection.drop_motifs.store`).

The store is the actual deliverable of this pipeline, not a side effect of
it (work order 4): the figures are meant to be re-croppable, re-coloured
and re-clustered without ever re-running detection, and a data card is
meant to quote numbers that were measured once and written down rather
than re-derived each time somebody asks. Both of those claims are only
true if a reload is byte-faithful and if the reload path never touches the
original recording. These tests are what stop "in principle you could
replot from storage" from being the only evidence for that.

What each test pins:

  - the event table survives a CSV round trip with its integer indices
    still integers (a float `onset_idx` slices an array wrongly, quietly);
  - the snippet arrays come back bit-identical, raw and detrended alike;
  - `load_events` + `load_snippets` need no `npy_path` and no database -
    asserted by deleting the source array before reloading, so a store
    that secretly re-reads the channel fails loudly;
  - the manifest carries every parameter and every rejection count, since
    that file is what section 7 is transcribed from;
  - `cluster_id` starts at -1 and can be written back without disturbing
    anything else in the table.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.Detection.drop_motifs.detect import DetectionParams, detect_drops
from Working.Detection.drop_motifs.store import (
    EVENT_TABLE_COLUMNS,
    assign_clusters,
    load_events,
    load_manifest,
    load_snippets,
    write_run,
)

FS = 1.0


def _params(**kwargs):
    base = dict(
        detrend_window_s=2400.0, segment_seconds=20.0, same_fraction=0.5,
        slope_sigma=4.0, min_depth_frac=0.10, lookahead_mult=3.0,
        merge_gap_segments=0, min_separation_s=0.0,
        pre_context_mult=2.0, post_context_mult=4.0,
        trough_knee_frac=0.05,
    )
    base.update(kwargs)
    return DetectionParams(**base)


def _signal(n=2400):
    """Two engineered ramp-then-cliff events, so a run produces a store
    with more than one row to join against."""
    x = np.zeros(n, dtype=float)
    for peak in (700, 1900):
        x[peak - 400:peak] = np.linspace(0.0, 10.0, 400)
        x[peak:peak + 4] = np.linspace(10.0, 0.0, 4)
    return x


def _run(tmp_path, **kwargs):
    x = _signal()
    result = detect_drops(x, FS, _params(**kwargs))
    out_dir = os.path.join(str(tmp_path), "999")
    paths = write_run(
        out_dir, result, x, fs=FS, recording_id=999,
        source_file="engineered.mat", channel=0,
        span_start_idx=0, extra={"note": "engineered"},
    )
    return x, result, out_dir, paths


# -- the table -------------------------------------------------------------

def test_event_table_round_trips_with_integer_indices(tmp_path):
    x, result, out_dir, _ = _run(tmp_path)
    assert len(result.events) == 2

    rows = load_events(out_dir)
    assert len(rows) == 2
    for column in EVENT_TABLE_COLUMNS:
        assert column in rows[0], f"{column} missing from the reloaded table"

    for row, event in zip(rows, result.events):
        for key in ("onset_idx", "up_region_start_idx", "up_region_end_idx",
                    "snippet_start_idx", "snippet_end_idx"):
            assert isinstance(row[key], (int, np.integer)), (
                f"{key} came back as {type(row[key])}; a float index slices wrong")
            assert row[key] == getattr(event, key)


def test_span_identity_round_trips_and_is_not_the_recording_id(tmp_path):
    """`span_key` is what every per-group figure keys on, and it is NOT
    interchangeable with `recording_id`: three shipped spans share
    recording 1 at very different time scales, so grouping by recording
    would merge sets that were deliberately parameterised apart."""
    x = _signal()
    result = detect_drops(x, FS, _params())
    out_dir = os.path.join(str(tmp_path), "named")
    write_run(out_dir, result, x, fs=FS, recording_id=1,
              source_file="M2_aug_concat_fs1.mat", channel=0,
              span_start_idx=0, span_key="m2aug_ch00_am16",
              span_label="M2_aug CH00 AM sharkfin x16")

    rows = load_events(out_dir)
    assert all(r["span_key"] == "m2aug_ch00_am16" for r in rows)
    assert all(r["span_label"] == "M2_aug CH00 AM sharkfin x16" for r in rows)
    assert load_manifest(out_dir)["span_key"] == "m2aug_ch00_am16"


def test_a_run_without_a_span_key_still_gets_a_usable_one(tmp_path):
    """Older stores and ad-hoc runs have no span key; grouping must still
    work rather than raising or collapsing everything into one group."""
    _, _, out_dir, _ = _run(tmp_path)
    rows = load_events(out_dir)
    assert all(r["span_key"] for r in rows)


def test_hours_columns_agree_with_the_indices_they_describe(tmp_path):
    _, _, out_dir, _ = _run(tmp_path)
    for row in load_events(out_dir):
        assert abs(row["onset_h"] - row["onset_idx"] / FS / 3600.0) < 1e-9


def test_span_offset_is_added_so_indices_are_absolute_in_the_recording(tmp_path):
    """A run over a cropped span (the M2_aug case: 336-346 h of a 721 h
    channel) must still record indices that index the WHOLE channel, or
    the stored event cannot be found again in the source array."""
    x = _signal()
    result = detect_drops(x, FS, _params())
    out_dir = os.path.join(str(tmp_path), "1")
    write_run(out_dir, result, x, fs=FS, recording_id=1,
              source_file="M2_aug_concat_fs1.mat", channel=0,
              span_start_idx=1209600)

    rows = load_events(out_dir)
    assert rows[0]["onset_idx"] == result.events[0].onset_idx + 1209600
    # ... and the snippet key still resolves against the shifted table.
    snippets = load_snippets(out_dir)
    assert rows[0]["event_id"] in snippets


# -- the arrays ------------------------------------------------------------

def test_snippet_arrays_reload_bit_identical(tmp_path):
    x, result, out_dir, _ = _run(tmp_path)
    snippets = load_snippets(out_dir)
    rows = load_events(out_dir)

    for row, event in zip(rows, result.events):
        stored = snippets[row["event_id"]]
        expected_raw = x[event.snippet_start_idx:event.snippet_end_idx] * 1000.0
        np.testing.assert_array_equal(stored["raw_mv"], expected_raw)
        assert stored["detrended_mv"].shape == stored["raw_mv"].shape
        assert stored["t_s"].shape == stored["raw_mv"].shape
        assert np.all(np.diff(stored["t_s"]) > 0)


def test_replot_needs_no_access_to_the_recording(tmp_path):
    """The load path is checked by REMOVING the only copy of the source
    array from the process before reloading. A store that quietly re-reads
    the channel cannot pass this."""
    x, result, out_dir, _ = _run(tmp_path)
    first_sample = float(x[result.events[0].snippet_start_idx] * 1000.0)
    del x

    rows = load_events(out_dir)
    snippets = load_snippets(out_dir)
    assert len(rows) == len(snippets) == 2
    assert abs(snippets[rows[0]["event_id"]]["raw_mv"][0] - first_sample) < 1e-12


def test_every_row_has_a_snippet_and_every_snippet_has_a_row(tmp_path):
    _, _, out_dir, _ = _run(tmp_path)
    rows = load_events(out_dir)
    snippets = load_snippets(out_dir)
    assert {r["event_id"] for r in rows} == set(snippets)


# -- the manifest ----------------------------------------------------------

def test_manifest_records_every_parameter_and_every_rejection_reason(tmp_path):
    _, result, out_dir, _ = _run(tmp_path)
    manifest = load_manifest(out_dir)

    for key in ("detrend_window_s", "segment_seconds", "same_fraction",
                "slope_sigma", "min_depth_frac", "lookahead_mult",
                "merge_gap_segments", "min_separation_s",
                "pre_context_mult", "post_context_mult"):
        assert key in manifest["params"], f"{key} absent from the manifest"

    for key in ("up_regions", "drops_confirmed", "rejected_no_slope",
                "rejected_shallow", "rejected_duplicate"):
        assert key in manifest["counts"], f"{key} absent from the manifest"

    assert manifest["counts"]["drops_confirmed"] == len(result.events)
    assert manifest["recording"]["id"] == 999
    assert "distributions" in manifest
    assert "drop_depth_mv" in manifest["distributions"]
    assert "fall_duration_s" in manifest["distributions"]
    # An empty run must be self-evidently empty, not indistinguishable
    # from a run that never happened.
    assert manifest["counts"]["drops_confirmed"] > 0
    assert manifest["empty"] is False


def test_a_run_that_finds_nothing_says_so_loudly(tmp_path):
    x = np.zeros(1000)
    result = detect_drops(x, FS, _params())
    out_dir = os.path.join(str(tmp_path), "empty")
    write_run(out_dir, result, x, fs=FS, recording_id=7,
              source_file="flat.mat", channel=0, span_start_idx=0)

    manifest = load_manifest(out_dir)
    assert manifest["empty"] is True
    assert manifest["counts"]["drops_confirmed"] == 0
    assert load_events(out_dir) == []
    # The files must still exist. "Zero events" and "not yet run" have to
    # be distinguishable on disk, which is the whole point.
    assert os.path.exists(os.path.join(out_dir, "manifest.json"))
    assert os.path.exists(os.path.join(out_dir, "events.csv"))


def test_manifest_is_valid_json_on_disk(tmp_path):
    _, _, out_dir, _ = _run(tmp_path)
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as fh:
        json.load(fh)


# -- cluster ids -----------------------------------------------------------

def test_cluster_id_starts_unassigned_and_can_be_written_back(tmp_path):
    _, _, out_dir, _ = _run(tmp_path)
    rows = load_events(out_dir)
    assert all(r["cluster_id"] == -1 for r in rows)

    assign_clusters(out_dir, {rows[0]["event_id"]: 3, rows[1]["event_id"]: 3})

    after = load_events(out_dir)
    assert [r["cluster_id"] for r in after] == [3, 3]
    # Nothing else moved.
    assert [r["onset_idx"] for r in after] == [r["onset_idx"] for r in rows]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
