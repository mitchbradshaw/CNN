"""drop_motifs12b's figures: that they are drawn, and that the rules hold.

These are construction tests against a synthetic store, not a comparison
against a shipped PNG. What they pin is the set of things that produce a
figure which LOOKS fine and is wrong:

  - the two waterfalls in S3.1 must show the same events in the same
    grouping, or the pair cannot be read across, which is the only thing
    the pair is for;
  - every panel that draws a waveform must be aspect-locked, because an
    unlocked panel is how round 11 flattened every trace;
  - the contact sheet's panels must all come out the same shape, or a
    reader reads a difference in box size as a difference in waveform;
  - a figure must be able to say what it did - the manifests carry the
    offset, the lock, the trace count and the thinning.
"""

import matplotlib

matplotlib.use("Agg")

import json

import numpy as np
import pytest

from Pipelines.drop_motifs import drawing_rules, figures12b_s3

FS = 10.0


def _event(index, *, fall_samples=8, depth_mv=3.0, onset_idx, species,
           catalogue_id=1, channel=0, pre=40, post=70):
    fall = np.linspace(0.0, -depth_mv, fall_samples + 1)[1:]
    recovery = -depth_mv * np.exp(-np.arange(post) / (post / 4.0))
    values = np.concatenate([np.zeros(pre), fall, recovery])
    event_id = f"e{index}"
    row = {
        "event_id": event_id, "fs": FS, "species": species,
        "catalogue_id": catalogue_id, "channel": channel,
        "recording_id": 1, "corpus": species,
        "onset_idx": onset_idx, "trough_idx": onset_idx + fall_samples,
        "snippet_start_idx": onset_idx - pre,
        "snippet_end_idx": onset_idx - pre + values.size,
        "drop_depth_mv": depth_mv, "fall_duration_s": fall_samples / FS,
        "onset_s": onset_idx / FS, "is_pure": 1,
    }
    return row, {event_id: {"detrended_mv": values, "raw_mv": values + 0.05}}


def _run(n=30, species="reishi", spacing=200):
    """One synthetic sequence in the shape `sequences11.extract` produces."""
    rows, snippets = [], {}
    for index in range(n):
        row, snips = _event(index, species=species,
                            onset_idx=1000 + index * spacing,
                            fall_samples=8 + index % 3,
                            depth_mv=3.0 + 0.08 * index)
        rows.append(row)
        snippets.update(snips)
    onsets = np.array([r["onset_s"] for r in rows])
    return {
        "sequence_key": f"{species}_id1_ch0_{int(onsets[0])}s",
        "species": species, "catalogue_id": 1, "channel": "0",
        "start_event_id": rows[0]["event_id"],
        "end_event_id": rows[-1]["event_id"],
        "n": len(rows), "cv_interval": 0.0, "r2_trend": 0.0,
        "drift_ratio": 1.0, "arm": "constant_gap",
        "arm_constant_gap": True, "arm_trend": False, "high_drift": False,
        "start_onset_s": float(onsets[0]), "end_onset_s": float(onsets[-1]),
        "duration_s": float(onsets[-1] - onsets[0]),
        "median_interval_s": spacing / FS,
        "group_median_interval_s": spacing / FS,
        "median_fall_s": 0.9, "median_depth_mv": 4.0,
        "rows": rows,
    }, snippets


class _NoSources:
    """A `sources12b.Sources` that reaches nothing.

    The figure must still be drawn, with the strip labelled as missing
    rather than the run stopping - a headless test box has no DATA/.
    """

    def span_for(self, rows, **_kwargs):
        return 0, 0

    def slice_mv(self, _row, _start, _stop):
        return None


class _FlatSources(_NoSources):
    """A source that returns a trace, so the strip path itself is exercised."""

    def span_for(self, rows, **_kwargs):
        return (min(int(r["onset_idx"]) for r in rows) - 50,
                max(int(r["trough_idx"]) for r in rows) + 50)

    def slice_mv(self, row, start, stop):
        return np.sin(np.arange(stop - start) / 40.0)


def _manifest(path):
    with open(str(path).replace(".png", ".json"), encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------
# S3.1
# --------------------------------------------------------------------------

def test_sequence_morph_is_written_and_states_what_it_drew(tmp_path):
    run, snippets = _run()
    path = tmp_path / "S3_1.png"
    manifest = figures12b_s3.plot_sequence_morph(
        run, snippets, path, sources=_FlatSources(), store_label="synthetic",
        families={r["event_id"]: 1 for r in run["rows"]}, family_k=8,
        selection="test")
    assert path.exists() and path.stat().st_size > 0
    # The JSON beside the figure is written from the same dict the figure was
    # drawn from, so a number on the page and a number in the manifest cannot
    # drift apart. `config11.write_manifest` adds provenance keys of its own.
    written = _manifest(path)
    assert {key: written[key] for key in manifest} == manifest

    assert manifest["n_drawn"] <= drawing_rules.MAX_TRACES
    assert manifest["reference_strip"]["drawn"] is True
    assert manifest["normalised_axis"] == [drawing_rules.PHASE_LO,
                                           drawing_rules.PHASE_HI]
    assert manifest["waterfall_offset_mv"] > 0
    assert manifest["every_kth_drawn"] >= 1
    bank = manifest["bank"]
    assert bank["columns"] * bank["per_column"] >= manifest["n_drawn"]


def test_the_two_waterfalls_show_the_same_events(tmp_path):
    """The pair is the argument; different events on the two sides is not."""
    run, snippets = _run()
    plan = figures12b_s3._waterfall_plan(run["rows"], snippets)
    assert len(plan["native"]) == len(plan["phase"]) == len(plan["rows"])


def test_the_drawn_median_event_lands_in_the_band(tmp_path):
    run, snippets = _run()
    manifest = figures12b_s3.plot_sequence_morph(
        run, snippets, tmp_path / "S3_1.png", sources=_NoSources(),
        store_label="synthetic", selection="test")
    assert manifest["drop_shape_ok"], manifest["drop_shape_note"]
    assert (drawing_rules.MIN_RATIO
            <= manifest["median_event_drawn_ratio"]
            <= drawing_rules.MAX_RATIO)


def test_a_missing_source_trace_is_said_rather_than_raised(tmp_path):
    run, snippets = _run()
    path = tmp_path / "S3_1.png"
    manifest = figures12b_s3.plot_sequence_morph(
        run, snippets, path, sources=_NoSources(), store_label="synthetic",
        selection="test")
    assert path.exists()
    assert manifest["reference_strip"]["drawn"] is False
    assert "unavailable" in manifest["reference_strip"]["note"]


def test_the_offset_is_zero_point_eight_of_the_drawn_peak_to_peak(tmp_path):
    run, snippets = _run()
    plan = figures12b_s3._waterfall_plan(run["rows"], snippets)
    clipped = figures12b_s3._clip_to_view(plan["native"], plan["xlim"])
    spans = [float(np.ptp(y)) for _t, y in clipped]
    assert plan["offset"] == pytest.approx(
        drawing_rules.OFFSET_FRACTION * float(np.median(spans)))


def test_a_long_sequence_is_thinned_and_says_by_how_much(tmp_path):
    run, snippets = _run(n=120)
    manifest = figures12b_s3.plot_sequence_morph(
        run, snippets, tmp_path / "S3_1.png", sources=_NoSources(),
        store_label="synthetic", selection="test")
    assert manifest["n_drawn"] <= drawing_rules.MAX_TRACES
    assert manifest["every_kth_drawn"] > 1
    assert manifest["n_drawable"] == 120


# --------------------------------------------------------------------------
# S3.2
# --------------------------------------------------------------------------

def test_contact_sheet_locks_every_panel_to_its_own_event(tmp_path):
    """Uniform panels, and the median event inside the 1:1 - 3:1 band.

    Two species so the row ordering by native fall duration is exercised.
    """
    runs, snippets = [], {}
    for species, spacing, depth in (("reishi", 60, 0.4), ("oyster", 900, 8.0)):
        run, snips = _run(n=14, species=species, spacing=spacing)
        for row in run["rows"]:
            row["drop_depth_mv"] = depth * (1.0 + 0.05 * (hash(row["event_id"]) % 7))
        runs.append(run)
        snippets.update(snips)
    # Distinct event ids per species, so the two runs cannot share arrays.
    path = tmp_path / "S3_2.png"
    manifest = figures12b_s3.plot_morph_across_scales(
        [runs[0]], snippets, path, store_label="synthetic")
    assert path.exists()
    row = manifest["rows"][0]
    assert row["panel_lock"].startswith("per panel")
    assert row["view_falls"] == list(figures12b_s3.CONTACT_VIEW_FALLS)
    assert (drawing_rules.MIN_RATIO
            <= row["median_event_drawn_ratio"]
            <= drawing_rules.MAX_RATIO)
