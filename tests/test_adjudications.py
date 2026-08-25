"""
test_adjudications.py
=====================
Tests for T19 — the adjudication store (`Working/database/adjudications.py`)
and the divergence / candidate-queue queries (`Working/database/queries.py`).

The adjudication invariant asserted throughout: a human verdict against a
machine detection writes an `adjudications` row and never an `annotations`
row (coding standard 2.5). Both divergence directions — machine-yes/human-no
and human-yes/machine-said-nothing — are queryable as first-class reads.

Run from the project root:
    pytest tests/test_adjudications.py
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

from Working.database.schema import init_db
from Working.database import adjudications as adj
from Working.database import queries as q
from Working.database import vocabulary as v


def _fresh_conn():
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    return conn


def _insert_run_group(conn):
    cur = conn.execute(
        "INSERT INTO run_groups (created_at) VALUES (?)", ("2026-01-01T00:00:00",)
    )
    conn.commit()
    return cur.lastrowid


def _insert_detection(conn, rid, start_idx=0, end_idx=100, score=None,
                      method="rupture", run_group_id=None):
    """Configs -> runs -> detections boilerplate, with an optional method in
    the recipe JSON and an optional run-group link."""
    cid = conn.execute(
        "INSERT INTO configs (config_hash, config_json, created_at) VALUES (?, ?, ?)",
        (f"hash-{rid}-{start_idx}-{end_idx}-{method}",
         json.dumps({"steps": [{"stage": "detection", "algorithm": method}]}),
         "2026-01-01T00:00:00"),
    ).lastrowid
    run_id = conn.execute(
        """INSERT INTO runs
               (config_id, recording_id, span_start, span_end, started_at, status, run_group_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cid, rid, 0, 1000, "2026-01-01T00:00:00", "done", run_group_id),
    ).lastrowid
    det_id = conn.execute(
        "INSERT INTO detections (run_id, start_idx, end_idx, score) VALUES (?, ?, ?, ?)",
        (run_id, start_idx, end_idx, score),
    ).lastrowid
    conn.commit()
    return det_id


# ── Adjudication store ────────────────────────────────────────────────────────

def test_insert_adjudication_creates_row_with_verdict_note_and_tags():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    det_id = _insert_detection(conn, rid)
    adj_id = adj.insert_adjudication(
        conn, det_id, "interesting", note="clear spike",
        tags={"element": ["sharkfin"]},
    )
    row = conn.execute(
        "SELECT * FROM adjudications WHERE detection_id = ?", (det_id,)
    ).fetchone()
    assert row is not None
    assert row["verdict"] == "interesting"
    assert row["note"] == "clear spike"
    assert row["id"] == adj_id
    assert adj.get_adjudication_tags(conn, adj_id).get("element") == ["sharkfin"]


def test_readjudicating_updates_existing_row_not_inserts_second():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    det_id = _insert_detection(conn, rid)
    adj.insert_adjudication(conn, det_id, "interesting", note="first")
    adj.insert_adjudication(conn, det_id, "not_interesting", note="second")
    rows = conn.execute(
        "SELECT * FROM adjudications WHERE detection_id = ?", (det_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["verdict"] == "not_interesting"
    assert rows[0]["note"] == "second"


def test_insert_adjudication_rejects_non_vocabulary_verdict():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    det_id = _insert_detection(conn, rid)
    try:
        adj.insert_adjudication(conn, det_id, "bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_adjudicating_a_detection_writes_no_annotation_row():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    det_id = _insert_detection(conn, rid)
    adj.insert_adjudication(conn, det_id, "not_interesting", note="no")
    n = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
    assert n == 0


def test_adjudications_module_never_inserts_into_annotations():
    """Structural guard for the invariant: no code path in the adjudication
    module writes a human verdict into the human-annotation store."""
    module_path = os.path.join(PROJECT_ROOT, "Working", "database", "adjudications.py")
    with open(module_path, "r", encoding="utf-8") as f:
        source = f.read()
    assert "INTO annotations" not in source, (
        "adjudications.py must never write into the annotations table"
    )


# ── Divergence queries ────────────────────────────────────────────────────────

def test_divergence_rejected_detections_returns_machine_yes_human_no():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    rejected = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    accepted = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    unjudged = _insert_detection(conn, rid, start_idx=400, end_idx=500)
    adj.insert_adjudication(conn, rejected, "not_interesting")
    adj.insert_adjudication(conn, accepted, "interesting")
    rows = q.divergence_rejected_detections(conn)
    assert [r["id"] for r in rows] == [rejected]
    # the unjudged detection has no adjudication, so it is not "rejected"
    assert unjudged not in [r["id"] for r in rows]


def test_divergence_annotations_without_detection_returns_human_yes_machine_silent():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    orphan = q.insert_annotation(conn, rid, 0, 50, "interesting", source=q.SOURCE_MANUAL_UI)
    covered = q.insert_annotation(conn, rid, 300, 400, "interesting", source=q.SOURCE_MANUAL_UI)
    _insert_detection(conn, rid, start_idx=310, end_idx=390)  # overlaps covered
    rows = q.divergence_annotations_without_detection(conn)
    assert [r["id"] for r in rows] == [orphan]
    assert covered not in [r["id"] for r in rows]


def test_both_divergence_directions_queryable_over_one_recording():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    orphan = q.insert_annotation(conn, rid, 0, 50, "interesting", source=q.SOURCE_MANUAL_UI)
    rejected = _insert_detection(conn, rid, start_idx=100, end_idx=200, score=0.8)
    adj.insert_adjudication(conn, rejected, "not_interesting")
    rejected_rows = q.divergence_rejected_detections(conn, recording_id=rid)
    orphan_rows = q.divergence_annotations_without_detection(conn, recording_id=rid)
    assert [r["id"] for r in rejected_rows] == [rejected]
    assert [r["id"] for r in orphan_rows] == [orphan]


# ── Candidate queue query ─────────────────────────────────────────────────────

def test_queue_filters_by_run_and_run_group():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    g1 = _insert_run_group(conn)
    g2 = _insert_run_group(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.5, run_group_id=g1)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.7, run_group_id=g2)
    run1 = conn.execute("SELECT run_id FROM detections WHERE id = ?", (d1,)).fetchone()["run_id"]
    assert [r["id"] for r in q.queue_candidates(conn, run_id=run1)] == [d1]
    assert [r["id"] for r in q.queue_candidates(conn, run_group_id=g1)] == [d1]


def test_queue_filters_by_method():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    d_rupture = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.5, method="rupture")
    d_peak = _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.7, method="peak_finder")
    rows = q.queue_candidates(conn, method="rupture")
    assert [r["id"] for r in rows] == [d_rupture]
    assert d_peak not in [r["id"] for r in rows]


def test_queue_filters_by_score_range_and_channel():
    conn = _fresh_conn()
    rid0 = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    rid1 = q.insert_recording(conn, "a.mat", 1, 1.0, 1000, 0, "a/CH1.npy")
    d_low = _insert_detection(conn, rid0, start_idx=0, end_idx=100, score=0.3)
    d_mid = _insert_detection(conn, rid0, start_idx=200, end_idx=300, score=0.6)
    d_hi = _insert_detection(conn, rid1, start_idx=400, end_idx=500, score=0.9)
    assert [r["id"] for r in q.queue_candidates(conn, score_min=0.5, score_max=0.8)] == [d_mid]
    assert [r["id"] for r in q.queue_candidates(conn, channel=1)] == [d_hi]
    assert d_low not in [r["id"] for r in q.queue_candidates(conn, score_min=0.5)]


def test_queue_filters_by_adjudication_status():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    d_un = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.5)
    d_acc = _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.6)
    d_rej = _insert_detection(conn, rid, start_idx=400, end_idx=500, score=0.7)
    adj.insert_adjudication(conn, d_acc, "interesting")
    adj.insert_adjudication(conn, d_rej, "not_interesting")
    assert [r["id"] for r in q.queue_candidates(conn, adjudication_status="unadjudicated")] == [d_un]
    assert [r["id"] for r in q.queue_candidates(conn, adjudication_status="adjudicated")] == [d_acc, d_rej]
    assert [r["id"] for r in q.queue_candidates(conn, adjudication_status="accepted")] == [d_acc]
    assert [r["id"] for r in q.queue_candidates(conn, adjudication_status="rejected")] == [d_rej]


def test_queue_composes_filters():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    g = _insert_run_group(conn)
    d = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.6,
                          method="rupture", run_group_id=g)
    _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.9,
                      method="peak_finder", run_group_id=g)
    rows = q.queue_candidates(
        conn, run_group_id=g, method="rupture", score_min=0.5, score_max=0.7,
        adjudication_status="unadjudicated",
    )
    assert [r["id"] for r in rows] == [d]


def test_queue_pages_with_limit_and_offset():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    ids = [_insert_detection(conn, rid, start_idx=i * 100, end_idx=i * 100 + 100,
                             score=0.5)
           for i in range(5)]
    page1 = q.queue_candidates(conn, limit=2, offset=0)
    page2 = q.queue_candidates(conn, limit=2, offset=2)
    assert [r["id"] for r in page1] == ids[:2]
    assert [r["id"] for r in page2] == ids[2:4]
