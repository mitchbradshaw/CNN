"""
test_cross_channel.py
======================
Contract tests for `Working.cross_channel` and the `Working.library` action
that persists its classifications (ticket 41).

A shared-ground recording artifact must be separated from a real network
event *before* anything is counted. These tests use synthetic pairs with a
known injected lag and a known waveform relationship, so a bug here cannot
look like a research finding:

- one case per classification bin, asserted against the cross-correlation
  peak and the waveform correlation at that lag;
- the classification is persisted on the existing motif edge; and
- recurrence counts exclude the `artifact` bin.

Headless: uses a temporary directory for the npy files the recordings point
at and an in-memory sqlite database.
"""

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
from Working.distances import DISTANCE_SCALE_INVARIANT
from Working.cross_channel import (
    ARTIFACT,
    INDEPENDENT_RECURRENCE,
    PROPAGATION,
    CROSS_CHANNEL_ARTIFACT_MAX_ABS_LAG,
    CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION,
    CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG,
    classify_waveforms,
)
from Working.library import classify_cross_channel_edges, recurrence_count


# ── fixture helpers ─────────────────────────────────────────────────────────

def _write_recording(conn, npy_dir, source_file, channel, data):
    """Write `data` to a scratch .npy file and insert a recording row that
    points at it. Returns the recording id."""
    npy_path = os.path.join(npy_dir, f"{source_file}_ch{channel}.npy")
    np.save(npy_path, np.asarray(data, dtype=float))
    return q.insert_recording(conn, source_file, channel, 1.0, len(data), 0, npy_path)


def _make_base(n=400, seed=0):
    return np.random.default_rng(seed).standard_normal(n)


# ── criterion 1: one synthetic case per bin ────────────────────────────────

def test_artifact_pair_classifies_artifact():
    x = _make_base()
    y = x.copy()  # known relationship: identical, known injected lag: 0
    lag, correlation, classification = classify_waveforms(x, y)

    assert classification == ARTIFACT
    assert abs(lag) <= CROSS_CHANNEL_ARTIFACT_MAX_ABS_LAG
    assert correlation >= CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION


def test_propagation_pair_classifies_propagation():
    rng = np.random.default_rng(1)
    x = _make_base()
    y = np.roll(x, 5) + 0.5 * rng.standard_normal(len(x))

    lag, correlation, classification = classify_waveforms(x, y)

    assert classification == PROPAGATION
    assert abs(lag) == 5
    assert abs(lag) <= CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG
    assert correlation < CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION


def test_independent_recurrence_pair_classifies_independent_recurrence():
    x = _make_base()
    y = np.roll(x, 80)  # known injected lag: long, scattered interval

    lag, correlation, classification = classify_waveforms(x, y)

    assert classification == INDEPENDENT_RECURRENCE
    assert abs(lag) > CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG


# ── criterion 2: classification is persisted on the edge ───────────────────

def test_cross_channel_edges_are_classified_and_artifacts_excluded_from_count():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn = init_db(":memory:")
        try:
            base = _make_base()
            rng = np.random.default_rng(2)
            rec_a = _write_recording(conn, npy_dir, "shared.mat", 0, base)
            rec_b = _write_recording(
                conn, npy_dir, "shared.mat", 1,
                np.roll(base, 5) + 0.5 * rng.standard_normal(len(base)),
            )
            rec_c = _write_recording(conn, npy_dir, "shared.mat", 2, base.copy())

            entry_id = R.insert_motif_entry(conn, rec_a, 0, 200)
            ma = R.get_or_create_motif_member(conn, entry_id, rec_a, 0, 200)
            mb = R.get_or_create_motif_member(conn, entry_id, rec_b, 0, 200)
            mc = R.get_or_create_motif_member(conn, entry_id, rec_c, 0, 200)

            R.insert_motif_edge(
                conn, ma, mb, DISTANCE_SCALE_INVARIANT, 0.1, 0.0, "recipe-a",
            )
            R.insert_motif_edge(
                conn, ma, mc, DISTANCE_SCALE_INVARIANT, 0.1, 0.0, "recipe-b",
            )

            results = classify_cross_channel_edges(conn, entry_id)

            assert len(results) == 2
            by_pair = {(r["member_a_id"], r["member_b_id"]): r for r in results}
            propagation = by_pair[(ma, mb)]
            artifact = by_pair[(ma, mc)]

            assert propagation["classification_bin"] == PROPAGATION
            assert abs(propagation["lag"]) == 5
            assert propagation["waveform_correlation"] is not None

            assert artifact["classification_bin"] == ARTIFACT
            assert abs(artifact["lag"]) <= CROSS_CHANNEL_ARTIFACT_MAX_ABS_LAG
            assert artifact["waveform_correlation"] >= CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION

            assert recurrence_count(conn, entry_id) == 1
        finally:
            conn.close()


# ── criterion 3: the action's UI surface constructs headlessly ─────────────

class _FakeApp:
    """The only app surface the detail action is allowed to read."""

    def __init__(self, conn):
        self.conn = conn


def test_cross_channel_action_renders_and_runs():
    from UI.workspaces.library.cross_channel import CrossChannelClassifier

    with tempfile.TemporaryDirectory() as npy_dir:
        conn = init_db(":memory:")
        try:
            base = _make_base()
            rec_a = _write_recording(conn, npy_dir, "shared.mat", 0, base)
            rec_b = _write_recording(conn, npy_dir, "shared.mat", 1, np.roll(base, 5))
            entry_id = R.insert_motif_entry(conn, rec_a, 0, 200)
            ma = R.get_or_create_motif_member(conn, entry_id, rec_a, 0, 200)
            mb = R.get_or_create_motif_member(conn, entry_id, rec_b, 0, 200)
            R.insert_motif_edge(
                conn, ma, mb, DISTANCE_SCALE_INVARIANT, 0.1, 0.0, "recipe-a",
            )

            action = CrossChannelClassifier(_FakeApp(conn), entry_id)
            layout = action.layout()

            assert layout is not None
            assert action.button is not None
            assert action.status is not None

            action._on_click()
            assert "1" in action.status.object
        finally:
            conn.close()
