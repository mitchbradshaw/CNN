"""
test_similarity.py
====================
Tests for Working/database/similarity.py: interval IoU arithmetic, and
near-duplicate detection both for a single candidate span (Part 2c, the
save-time warning) and across a whole channel (Part 2d, the audit).

Run from the project root:
    python tests/test_similarity.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database.similarity import (
    find_near_duplicate_pairs,
    find_similar_annotations,
    interval_iou,
    is_near_duplicate,
    width_ratio,
)


def _fresh_conn_with_recording():
    conn = init_db(":memory:")
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 100_000, 0, "a/CH0.npy")
    return conn, rid


# ── interval_iou / width_ratio ──────────────────────────────────────────────

def test_iou_identical_intervals_is_one():
    assert interval_iou(100, 200, 100, 200) == 1.0


def test_iou_no_overlap_is_zero():
    assert interval_iou(100, 200, 300, 400) == 0.0


def test_iou_touching_but_not_overlapping_is_zero():
    assert interval_iou(100, 200, 200, 300) == 0.0


def test_iou_partial_overlap():
    # [100,200) and [110,210): intersection=90, union=100+100-90=110
    assert abs(interval_iou(100, 200, 110, 210) - 90 / 110) < 1e-9


def test_iou_exactly_at_conventional_threshold():
    # [0,100) vs [0,80): intersection=80, union=100+80-80=100 -> IoU=0.8
    assert interval_iou(0, 100, 0, 80) == 0.8


def test_width_ratio_equal_widths_is_one():
    assert width_ratio(0, 100, 500, 600) == 1.0


def test_width_ratio_order_independent():
    assert width_ratio(0, 100, 0, 50) == width_ratio(0, 50, 0, 100) == 2.0


def test_width_ratio_zero_width_is_none():
    assert width_ratio(0, 0, 0, 100) is None


# ── is_near_duplicate ────────────────────────────────────────────────────────

def test_is_near_duplicate_identical_spans():
    assert is_near_duplicate(100, 200, 100, 200) is True


def test_is_near_duplicate_below_iou_threshold():
    assert is_near_duplicate(0, 100, 50, 200) is False  # IoU well under 0.8


def test_is_near_duplicate_high_iou_but_bad_width_ratio_still_rejected():
    # A short span fully inside a much longer one can have low true IoU,
    # but this checks the width-ratio guard specifically: construct a case
    # with default thresholds where width ratio alone would fail even if
    # some hypothetical IoU formulation passed.
    assert is_near_duplicate(100, 1100, 500, 520) is False  # widths 1000 vs 20


def test_is_near_duplicate_custom_thresholds():
    # Equal-width (ratio=1.0, well under the default width-ratio gate)
    # intervals offset by a quarter-width: IoU = 75/125 = 0.6 — fails the
    # default 0.8 IoU threshold but passes a relaxed one.
    assert is_near_duplicate(0, 100, 25, 125, iou_threshold=0.8) is False
    assert is_near_duplicate(0, 100, 25, 125, iou_threshold=0.5) is True


# ── find_similar_annotations (Part 2c) ──────────────────────────────────────

def test_find_similar_annotations_finds_overlapping_match():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    matches = find_similar_annotations(conn, rid, 1005, 1095)
    assert len(matches) == 1
    assert matches[0]["start_idx"] == 1000
    assert "iou" in matches[0]


def test_find_similar_annotations_ignores_unrelated_spans():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 50000, 50100, "artifact", source=q.SOURCE_MANUAL_UI)
    matches = find_similar_annotations(conn, rid, 1005, 1095)
    assert len(matches) == 1
    assert matches[0]["start_idx"] == 1000


def test_find_similar_annotations_excludes_self():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    matches = find_similar_annotations(conn, rid, 1000, 1100, exclude_annotation_id=aid)
    assert matches == []


def test_find_similar_annotations_no_match_returns_empty():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    matches = find_similar_annotations(conn, rid, 90000, 90100)
    assert matches == []


def test_find_similar_annotations_sorted_by_iou_descending():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1101, "interesting", source=q.SOURCE_MANUAL_UI)  # closer match
    q.insert_annotation(conn, rid, 1000, 1300, "artifact", source=q.SOURCE_MANUAL_UI)      # looser match
    # Widen both thresholds explicitly so the looser match (width ratio 3x)
    # isn't rejected by the width-ratio gate before IoU ordering matters.
    matches = find_similar_annotations(conn, rid, 1000, 1100,
                                        iou_threshold=0.3, width_ratio_threshold=5.0)
    assert len(matches) == 2
    assert matches[0]["iou"] >= matches[1]["iou"]


# ── find_near_duplicate_pairs (Part 2d audit) ───────────────────────────────

def test_find_near_duplicate_pairs_report_only_finds_pair():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 1005, 1095, "interesting", source=q.SOURCE_MANUAL_UI)
    pairs = find_near_duplicate_pairs(conn, rid)
    assert len(pairs) == 1
    assert {pairs[0]["a"]["start_idx"], pairs[0]["b"]["start_idx"]} == {1000, 1005}
    # Report-only: nothing was deleted.
    assert len(q.list_annotations(conn, rid)) == 2


def test_find_near_duplicate_pairs_no_duplicates():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 5000, 5100, "artifact", source=q.SOURCE_MANUAL_UI)
    assert find_near_duplicate_pairs(conn, rid) == []


def test_find_near_duplicate_pairs_multiple_pairs_sorted():
    conn, rid = _fresh_conn_with_recording()
    q.insert_annotation(conn, rid, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)  # group A
    q.insert_annotation(conn, rid, 1001, 1099, "interesting", source=q.SOURCE_MANUAL_UI)  # group A, near-identical
    q.insert_annotation(conn, rid, 5000, 5100, "artifact", source=q.SOURCE_MANUAL_UI)     # group B
    q.insert_annotation(conn, rid, 5010, 5090, "artifact", source=q.SOURCE_MANUAL_UI)     # group B, looser
    pairs = find_near_duplicate_pairs(conn, rid)
    assert len(pairs) == 2
    assert pairs[0]["iou"] >= pairs[1]["iou"]


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
