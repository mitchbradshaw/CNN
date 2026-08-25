"""
test_library_edges.py
======================
Contract tests for `Working.library` (ticket 36) — matching a candidate span
to an exemplar entry writes a `motif_member` (the candidate span, in whatever
recording/channel it came from) and a `motif_edge` carrying everything needed
to reproduce the match: distance function name, threshold, distance value and
recipe hash. A motif family is therefore an object, not a screenshot.

The acceptance criteria under test:

1. Matching a candidate span to an exemplar writes a `motif_member` and a
   `motif_edge`.
2. Every edge carries distance function name, threshold, distance value and
   recipe hash.
3. A member may reference any recording and any channel, including one the
   exemplar did not come from.
4. Re-running the same match with the same recipe does not duplicate the edge.
5. An edge written today can be recomputed from its recorded fields to the
   same distance value.

Headless: uses a temporary directory for the npy files the recordings point
at and an in-memory sqlite database.
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.distances import (
    DISTANCE_REGISTRY, DISTANCE_SCALE_INVARIANT, DISTANCE_NATIVE_LENGTH,
    resample_to_length,
)
from Working.library import match_span_to_entry


# ── fixture helpers ─────────────────────────────────────────────────────────

def _write_recording(conn, npy_dir, source_file, channel, data):
    """Write `data` to a scratch .npy file and insert a recording row that
    points at it. Returns the recording id."""
    npy_path = os.path.join(npy_dir, f"{source_file}_ch{channel}.npy")
    np.save(npy_path, np.asarray(data, dtype=float))
    return q.insert_recording(conn, source_file, channel, 1.0, len(data), 0, npy_path)


def _make_library(npy_dir):
    """A scratch in-memory library:
    - recording A (source A.mat, channel 0) is a sine; its span [10, 50) is
      the exemplar entry.
    - recording B (source B.mat, channel 3) is the same sine — a *different*
      source file and channel than the exemplar.
    - recording C (source C.mat, channel 1) is independent noise, for the
      no-match case.

    Returns (conn, entry_id, rec_a, rec_b, rec_c).
    """
    conn = init_db(":memory:")
    sine = np.sin(2 * np.pi * np.arange(200) / 200)
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sine)
    rec_b = _write_recording(conn, npy_dir, "B.mat", 3, sine)
    rng = np.random.default_rng(0)
    rec_c = _write_recording(conn, npy_dir, "C.mat", 1, rng.standard_normal(200))
    entry_id = R.insert_motif_entry(conn, rec_a, 10, 50)
    return conn, entry_id, rec_a, rec_b, rec_c


# ── criterion 1: a match writes a member and an edge ────────────────────────

def test_match_writes_member_and_edge():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        result = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        assert result is not None

        # The family now has two members: the exemplar's own span and the
        # candidate span.
        members = R.list_motif_members(conn, entry_id)
        assert len(members) == 2, [dict(m) for m in members]
        member_ids = {m["id"] for m in members}
        assert result["exemplar_member_id"] in member_ids
        assert result["candidate_member_id"] in member_ids

        # One edge joins them.
        edges = R.list_motif_edges(conn, entry_id)
        assert len(edges) == 1
        edge = edges[0]
        assert {edge["member_a_id"], edge["member_b_id"]} == member_ids


# ── criterion 2: every edge carries the reproducing fields ──────────────────

def test_edge_carries_distance_function_threshold_value_and_recipe_hash():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        result = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        edge = R.get_motif_edge(
            conn, result["exemplar_member_id"], result["candidate_member_id"],
            DISTANCE_SCALE_INVARIANT, 0.1, "h1",
        )
        assert edge is not None
        assert edge["distance_function"] == DISTANCE_SCALE_INVARIANT
        assert abs(edge["threshold"] - 0.1) < 1e-12
        assert abs(edge["distance_value"]) < 1e-6
        assert edge["recipe_hash"] == "h1"


# ── criterion 3: a member may live in any recording/channel ─────────────────

def test_member_may_reference_a_different_recording_and_channel():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        result = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        entry = R.get_motif_entry(conn, entry_id)
        # The exemplar lives on recording A, the candidate on recording B —
        # a different source file AND a different channel.
        assert rec_b != entry["recording_id"]
        member = R.get_motif_member(conn, result["candidate_member_id"])
        assert member["recording_id"] == rec_b
        assert member["entry_id"] == entry_id
        assert member["start_idx"] == 10
        assert member["end_idx"] == 50


# ── criterion 4: re-running the same match is idempotent ────────────────────

def test_rerunning_same_match_does_not_duplicate_the_edge():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        r1 = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        r2 = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        assert r2["edge_id"] == r1["edge_id"]
        assert len(R.list_motif_edges(conn, entry_id)) == 1
        assert len(R.list_motif_members(conn, entry_id)) == 2


# ── criterion 5: an edge is recomputable from its recorded fields ───────────

def test_edge_can_be_recomputed_from_recorded_fields():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        result = match_span_to_entry(
            conn, entry_id, rec_b, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h1",
        )
        edge = R.get_motif_edge(
            conn, result["exemplar_member_id"], result["candidate_member_id"],
            DISTANCE_SCALE_INVARIANT, 0.1, "h1",
        )
        ma = R.get_motif_member(conn, edge["member_a_id"])
        mb = R.get_motif_member(conn, edge["member_b_id"])
        rec_a_row = q.get_recording_by_id(conn, ma["recording_id"])
        rec_b_row = q.get_recording_by_id(conn, mb["recording_id"])
        # `np.array` copies the slice out of the memmap so the scratch .npy
        # files aren't held open when the temp dir is cleaned up on Windows.
        xa = np.array(np.load(rec_a_row["npy_path"], mmap_mode="r")[ma["start_idx"]:ma["end_idx"]])
        xb = np.array(np.load(rec_b_row["npy_path"], mmap_mode="r")[mb["start_idx"]:mb["end_idx"]])
        func = DISTANCE_REGISTRY[edge["distance_function"]]
        recomputed = func(xa, xb)
        assert np.isclose(recomputed, edge["distance_value"], atol=1e-9)


# ── beyond threshold: no match, nothing persisted ───────────────────────────

def test_distance_above_threshold_writes_no_member_or_edge():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, rec_c = _make_library(npy_dir)
        result = match_span_to_entry(
            conn, entry_id, rec_c, 10, 50,
            distance_function=DISTANCE_SCALE_INVARIANT,
            threshold=0.1, recipe_hash="h2",
        )
        assert result is None
        assert R.list_motif_edges(conn, entry_id) == []
        assert R.list_motif_members(conn, entry_id) == []


# ── T40: search at other scales ─────────────────────────────────────────────

def _make_scale_library(npy_dir):
    """A scratch library for the search-at-other-scales tests:
    - recording A holds a single full sine cycle over 100 samples; that span
      is the exemplar entry.
    - recording B is 800 samples of zeros with the same sine planted at three
      durations (50, 150, 200) at non-overlapping spans. Each planted instance
      is the exemplar *resampled* to that duration, so under the
      scale-invariant distance it is the same shape at a different scale.

    Returns (conn, entry_id, rec_a, rec_b, planted) where `planted` is a list
    of (duration, start_idx, end_idx).
    """
    conn = init_db(":memory:")
    m = 100
    sine = np.sin(2 * np.pi * np.arange(m) / m)
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sine)
    entry_id = R.insert_motif_entry(conn, rec_a, 0, m, label="sine")

    n = 800
    x = np.zeros(n)
    planted = [(50, 10, 60), (150, 300, 450), (200, 550, 750)]
    for dur, start, end in planted:
        x[start:end] = resample_to_length(sine, dur)
    rec_b = _write_recording(conn, npy_dir, "B.mat", 0, x)
    return conn, entry_id, rec_a, rec_b, planted


def test_search_across_durations_recovers_motif_at_three_scales():
    import Working.library as lib
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, planted = _make_scale_library(npy_dir)
        try:
            durations = list(range(50, 201, 50))  # [50, 100, 150, 200]
            result = lib.search_entry_across_durations(
                conn, entry_id, rec_b,
                durations=durations,
                threshold=0.1, recipe_hash="h_scale",
                distance_function=DISTANCE_SCALE_INVARIANT,
            )
            matched = set(result["matched_spans"])
            for dur, start, end in planted:
                assert (start, end) in matched, (
                    f"scale-invariant search missed planted span {(start, end)}"
                )
            assert len(result["matches"]) >= len(planted)

            # Every written edge records the distance function used.
            edges = R.list_motif_edges(conn, entry_id)
            assert edges
            assert all(
                e["distance_function"] == DISTANCE_SCALE_INVARIANT for e in edges
            )
        finally:
            conn.close()


def test_search_across_durations_native_length_control_recovers_fewer():
    import Working.library as lib
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, planted = _make_scale_library(npy_dir)
        try:
            durations = list(range(50, 201, 50))
            result = lib.search_entry_across_durations(
                conn, entry_id, rec_b,
                durations=durations,
                threshold=0.1, recipe_hash="h_native",
                distance_function=DISTANCE_NATIVE_LENGTH,
            )
            # The native-length control does not reconcile duration away:
            # the same shape at a different duration is a large distance, so
            # fewer than all three planted spans are recovered.
            assert len(result["matched_spans"]) < len(planted), (
                f"native-length control recovered {len(result['matched_spans'])} "
                f"of {len(planted)} planted spans; expected fewer"
            )
        finally:
            conn.close()


def test_entry_detail_search_action_constructs_and_runs():
    import panel as pn
    import holoviews as hv
    pn.extension("tabulator")
    hv.extension("bokeh")
    from UI.workspaces.library.detail import EntryDetail

    class _FakeApp:
        def __init__(self, conn):
            self.conn = conn

    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, rec_a, rec_b, planted = _make_scale_library(npy_dir)
        try:
            detail = EntryDetail(_FakeApp(conn))
            # The search action's panes are present and non-None.
            assert detail.search_recording is not None
            assert detail.search_min_duration is not None
            assert detail.search_max_duration is not None
            assert detail.search_step is not None
            assert detail.search_threshold is not None
            assert detail.search_run_button is not None
            assert detail.search_results_pane is not None
            assert detail.layout() is not None

            # Drive the action: select the exemplar, point the search at
            # recording B, run it.
            detail.select_entry(entry_id)
            detail.search_recording.value = rec_b
            detail.search_min_duration.value = 50
            detail.search_max_duration.value = 200
            detail.search_step.value = 50
            detail.search_threshold.value = 0.1
            detail._on_search_run(None)

            text = detail.search_results_pane.object
            assert "scale_invariant" in text
            assert "native_length" in text

            # The action ran both distances side by side; the scale-invariant
            # arm recovered the planted spans, the native-length arm did not.
            results = detail.last_search_results
            assert results[DISTANCE_SCALE_INVARIANT]["recall"] >= len(planted)
            assert results[DISTANCE_NATIVE_LENGTH]["recall"] < len(planted)

            # The search wrote members and edges recording the distance used.
            edges = R.list_motif_edges(conn, entry_id)
            assert edges
            assert all(
                e["distance_function"] == DISTANCE_SCALE_INVARIANT for e in edges
            )
        finally:
            conn.close()


# ── runner ──────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
