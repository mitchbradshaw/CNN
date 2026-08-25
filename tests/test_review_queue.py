"""
test_review_queue.py
====================
Tests for T20 — the headless half of the Review candidate queue
(`UI/workspaces/review/queue_state.py`).

The queue state object is deliberately free of any Panel import so it stays
headlessly testable; ticket 21 renders what this holds. It builds on the
candidate-queue query (`Working.database.queries.queue_candidates`, T19) and
the adjudication store (`Working.database.adjudications`, T19) rather than
reimplementing either.

The Review invariant asserted throughout: adjudicating writes an
`adjudications` row and never an `annotations` row. Undo reverses the last
adjudication write, so an accidental verdict is not permanent (PRD story 28).

Run from the project root:
    python tests/test_review_queue.py
"""

import inspect
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
from UI.workspaces.review.queue_state import ReviewQueue


def _fresh_conn():
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    return conn


def _insert_recording(conn, source_file="a.mat", channel=0):
    return q.insert_recording(conn, source_file, channel, 1.0, 1000, 0,
                              f"data/{source_file}/CH{channel}.npy")


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


# ── construction and the no-UI-import boundary ──────────────────────────────

def test_module_imports_no_ui_library():
    src_path = os.path.join(PROJECT_ROOT, "UI", "workspaces", "review",
                            "queue_state.py")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    for banned in ("panel", "holoviews", "bokeh", "matplotlib"):
        assert banned not in src.lower(), \
            f"queue_state.py must not mention {banned}"


def test_new_queue_holds_candidates_index_and_empty_history():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.5)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.6)
    d3 = _insert_detection(conn, rid, start_idx=400, end_idx=500, score=0.7)
    queue = ReviewQueue(conn)
    assert [c["id"] for c in queue.candidates] == [d1, d2, d3]
    assert queue.index == 0
    assert queue.current["id"] == d1
    assert queue.history == []


def test_default_filter_is_unadjudicated_only():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    adj.insert_adjudication(conn, d1, "interesting")
    queue = ReviewQueue(conn)  # default adjudication_status="unadjudicated"
    assert [c["id"] for c in queue.candidates] == [d2]


# ── filters compose ─────────────────────────────────────────────────────────

def test_filters_include_run_and_run_group():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    g1 = _insert_run_group(conn)
    g2 = _insert_run_group(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.5,
                           run_group_id=g1)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.6,
                           run_group_id=g2)
    run1 = conn.execute(
        "SELECT run_id FROM detections WHERE id = ?", (d1,)
    ).fetchone()["run_id"]
    queue_by_run = ReviewQueue(conn, run_id=run1)
    assert [c["id"] for c in queue_by_run.candidates] == [d1]
    queue_by_group = ReviewQueue(conn, run_group_id=g1)
    assert [c["id"] for c in queue_by_group.candidates] == [d1]


def test_filters_include_method_and_score_range():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d_rupture = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.3,
                                  method="rupture")
    _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.6,
                      method="peak_finder")
    queue = ReviewQueue(conn, method="rupture", score_min=0.2, score_max=0.4)
    assert [c["id"] for c in queue.candidates] == [d_rupture]


def test_filters_include_channel():
    conn = _fresh_conn()
    rid0 = _insert_recording(conn, source_file="a.mat", channel=0)
    rid1 = _insert_recording(conn, source_file="a.mat", channel=1)
    d0 = _insert_detection(conn, rid0, start_idx=0, end_idx=100, score=0.5)
    d1 = _insert_detection(conn, rid1, start_idx=200, end_idx=300, score=0.6)
    queue = ReviewQueue(conn, channel=1)
    assert [c["id"] for c in queue.candidates] == [d1]
    assert d0 not in [c["id"] for c in queue.candidates]


def test_filters_compose():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    g = _insert_run_group(conn)
    d_match = _insert_detection(conn, rid, start_idx=0, end_idx=100, score=0.6,
                                method="rupture", run_group_id=g)
    _insert_detection(conn, rid, start_idx=200, end_idx=300, score=0.9,
                      method="peak_finder", run_group_id=g)
    queue = ReviewQueue(conn, run_group_id=g, method="rupture",
                        score_min=0.5, score_max=0.7,
                        adjudication_status="unadjudicated")
    assert [c["id"] for c in queue.candidates] == [d_match]


def test_set_filters_reloads_the_candidate_list():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d_rupture = _insert_detection(conn, rid, start_idx=0, end_idx=100,
                                  method="rupture")
    _insert_detection(conn, rid, start_idx=200, end_idx=300, method="peak_finder")
    queue = ReviewQueue(conn)
    assert len(queue.candidates) == 2
    queue.set_filters(method="rupture")
    assert [c["id"] for c in queue.candidates] == [d_rupture]
    assert queue.index == 0


# ── advancing ───────────────────────────────────────────────────────────────

def test_advance_moves_to_the_next_unadjudicated_candidate():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    d3 = _insert_detection(conn, rid, start_idx=400, end_idx=500)
    queue = ReviewQueue(conn)
    assert queue.current["id"] == d1
    queue.advance()
    assert queue.current["id"] == d2
    queue.advance()
    assert queue.current["id"] == d3
    queue.advance()
    assert queue.current is None


def test_advance_skips_a_candidate_already_adjudicated():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    d3 = _insert_detection(conn, rid, start_idx=400, end_idx=500)
    adj.insert_adjudication(conn, d2, "interesting")
    # No adjudication-status filter: the list holds all three, but advancing
    # must skip the already-adjudicated middle candidate and land on the next
    # unadjudicated one.
    queue = ReviewQueue(conn, adjudication_status=None)
    assert [c["id"] for c in queue.candidates] == [d1, d2, d3]
    assert queue.current["id"] == d1
    queue.advance()
    assert queue.current["id"] == d3


# ── adjudicating and the verdict history ────────────────────────────────────

def test_adjudicate_current_writes_and_auto_advances():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    queue = ReviewQueue(conn)
    adj_id = queue.adjudicate_current("interesting")
    row = adj.get_adjudication(conn, d1)
    assert row is not None and row["verdict"] == "interesting"
    assert row["id"] == adj_id
    assert queue.history[-1]["detection_id"] == d1
    assert queue.history[-1]["verdict"] == "interesting"
    assert queue.current["id"] == d2  # auto-advanced


def test_adjudicating_writes_no_annotation_row():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    _insert_detection(conn, rid, start_idx=0, end_idx=100)
    queue = ReviewQueue(conn)
    queue.adjudicate_current("not_interesting")
    n = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
    assert n == 0


def test_history_records_each_verdict_in_order():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    d3 = _insert_detection(conn, rid, start_idx=400, end_idx=500)
    queue = ReviewQueue(conn)
    queue.adjudicate_current("interesting")
    queue.adjudicate_current("not_interesting")
    queue.adjudicate_current("artifact")
    assert len(queue.history) == 3
    assert [h["verdict"] for h in queue.history] == \
        ["interesting", "not_interesting", "artifact"]
    assert [h["detection_id"] for h in queue.history] == [d1, d2, d3]
    assert queue.current is None  # every candidate adjudicated


def test_adjudicate_current_with_no_candidate_raises():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    _insert_detection(conn, rid, start_idx=0, end_idx=100)
    queue = ReviewQueue(conn)
    queue.adjudicate_current("interesting")  # only candidate -> auto-advance to end
    assert queue.current is None
    try:
        queue.adjudicate_current("interesting")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


# ── undo ────────────────────────────────────────────────────────────────────

def test_undo_restores_the_previous_index_and_reverses_a_new_adjudication():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    queue = ReviewQueue(conn)
    queue.adjudicate_current("interesting")  # at d1, auto-advance to d2
    assert queue.current["id"] == d2
    assert adj.get_adjudication(conn, d1) is not None
    ok = queue.undo()
    assert ok is True
    assert queue.index == 0
    assert queue.current["id"] == d1
    assert adj.get_adjudication(conn, d1) is None  # row deleted
    assert queue.history == []


def test_undo_restores_the_previous_verdict_when_readjudicating():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    adj.insert_adjudication(conn, d1, "interesting", note="first")
    queue = ReviewQueue(conn, adjudication_status=None)
    queue.adjudicate_current("not_interesting", note="second")
    assert adj.get_adjudication(conn, d1)["verdict"] == "not_interesting"
    assert adj.get_adjudication(conn, d1)["note"] == "second"
    ok = queue.undo()
    assert ok is True
    row = adj.get_adjudication(conn, d1)
    assert row["verdict"] == "interesting"
    assert row["note"] == "first"
    assert queue.current["id"] == d1


def test_undo_steps_back_through_multiple_adjudications():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    d1 = _insert_detection(conn, rid, start_idx=0, end_idx=100)
    d2 = _insert_detection(conn, rid, start_idx=200, end_idx=300)
    d3 = _insert_detection(conn, rid, start_idx=400, end_idx=500)
    queue = ReviewQueue(conn)
    queue.adjudicate_current("interesting")        # d1 -> index 1
    queue.adjudicate_current("not_interesting")    # d2 -> index 2
    assert queue.current["id"] == d3
    queue.undo()  # reverse d2 -> back to index 1
    assert queue.current["id"] == d2
    assert adj.get_adjudication(conn, d2) is None
    queue.undo()  # reverse d1 -> back to index 0
    assert queue.current["id"] == d1
    assert adj.get_adjudication(conn, d1) is None


def test_undo_returns_false_when_there_is_no_history():
    conn = _fresh_conn()
    rid = _insert_recording(conn)
    _insert_detection(conn, rid, start_idx=0, end_idx=100)
    queue = ReviewQueue(conn)
    assert queue.undo() is False
    assert queue.current is not None


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
