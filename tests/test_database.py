"""
test_database.py
==================
Tests for Working/database/: schema init, the global<->local
index conversion (including the channel-boundary-straddle case), and the
plain CRUD functions.

Run from the project root:
    python tests/test_database.py
"""

import inspect
import os
import sys

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q


def _fresh_conn():
    return init_db(":memory:")


# ── global_to_local / boundary-straddle ────────────────────────────────────────

def test_global_to_local_within_first_channel():
    assert q.global_to_local(50, 1000) == (0, 50)


def test_global_to_local_second_channel():
    assert q.global_to_local(1050, 1000) == (1, 50)


def test_global_to_local_exact_boundary():
    # start exactly on a channel boundary belongs to the *next* channel
    assert q.global_to_local(1000, 1000) == (1, 0)


def test_window_straddles_boundary_true():
    # L=1000, window=600, local=700 -> 700+600=1300 > 1000
    assert q.window_straddles_boundary(700, 600, 1000) is True


def test_window_straddles_boundary_false():
    # local=300 -> 300+600=900 <= 1000
    assert q.window_straddles_boundary(300, 600, 1000) is False


def test_window_straddles_boundary_exact_fit():
    # local=400 -> 400+600=1000 == L, not a straddle
    assert q.window_straddles_boundary(400, 600, 1000) is False


# ── schema / recordings ─────────────────────────────────────────────────────────

def test_init_db_is_idempotent():
    conn = _fresh_conn()
    init_db(":memory:")  # separate in-memory db, just checking no error
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {"recordings", "reviewed_spans", "annotations", "configs",
                "runs", "detections", "encodings", "motifs"}
    assert expected.issubset(tables), tables


def test_insert_recording_idempotent():
    conn = _fresh_conn()
    id1 = q.insert_recording(conn, "rec.mat", 0, 1.0, 1000, 0, "path/CH0.npy")
    id2 = q.insert_recording(conn, "rec.mat", 0, 1.0, 1000, 0, "path/CH0.npy")
    assert id1 == id2
    rows = conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()
    assert rows["n"] == 1


def test_list_recordings_filters_by_source_file():
    conn = _fresh_conn()
    q.insert_recording(conn, "a.mat", 0, 1.0, 100, 0, "a/CH0.npy")
    q.insert_recording(conn, "b.mat", 0, 1.0, 100, 0, "b/CH0.npy")
    rows = q.list_recordings(conn, source_file="a.mat")
    assert len(rows) == 1
    assert rows[0]["source_file"] == "a.mat"


# ── annotations ──────────────────────────────────────────────────────────────

def test_insert_and_list_annotation():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_annotation(conn, rid, 10, 610, "interesting", source=q.SOURCE_MANUAL_UI)
    rows = q.list_annotations(conn, rid)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "interesting"


def test_insert_annotation_rejects_bad_verdict():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    try:
        q.insert_annotation(conn, rid, 0, 600, "bogus", source=q.SOURCE_MANUAL_UI)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_annotation_exists():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    assert not q.annotation_exists(conn, rid, 0, 600, q.SOURCE_IMPORTED_10MIN)
    q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    assert q.annotation_exists(conn, rid, 0, 600, q.SOURCE_IMPORTED_10MIN)


def test_update_annotation_protects_imported():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    try:
        q.update_annotation(conn, aid, verdict="unsure")
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    # force=True is an explicit override
    q.update_annotation(conn, aid, force=True, verdict="unsure")
    assert q.get_annotation(conn, aid)["verdict"] == "unsure"


def test_update_annotation_allows_manual():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "unsure", source=q.SOURCE_MANUAL_UI)
    q.update_annotation(conn, aid, verdict="interesting", note="edited")
    row = q.get_annotation(conn, aid)
    assert row["verdict"] == "interesting"
    assert row["note"] == "edited"


def test_delete_annotation_protects_imported():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    try:
        q.delete_annotation(conn, aid)
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    assert q.get_annotation(conn, aid) is not None


# ── reviewed_spans / summary ─────────────────────────────────────────────────

def test_reviewed_fraction_merges_overlaps():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_reviewed_span(conn, rid, 0, 200, source=q.SOURCE_MANUAL_UI)
    q.insert_reviewed_span(conn, rid, 100, 300, source=q.SOURCE_MANUAL_UI)  # overlaps
    q.insert_reviewed_span(conn, rid, 500, 600, source=q.SOURCE_MANUAL_UI)
    # covered = [0,300) + [500,600) = 300 + 100 = 400 out of 1000
    assert q.reviewed_fraction(conn, rid) == 400 / 1000


def test_reviewed_fraction_zero_when_unreviewed():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    assert q.reviewed_fraction(conn, rid) == 0.0


def test_recording_summary_counts():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 100, 700, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    q.insert_annotation(conn, rid, 200, 800, "interesting", source=q.SOURCE_MANUAL_UI)
    summary = q.recording_summary(conn, rid)
    assert summary["interesting"] == 2
    assert summary["artifact"] == 1
    assert summary["not_interesting"] == 0
    assert summary["total"] == 3


# ── runner ───────────────────────────────────────────────────────────────────

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
