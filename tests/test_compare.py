"""
test_compare.py
================
Ticket 33 — the two-run set-overlap comparison.

`Working.compare` is the headless half: given two completed runs, it computes
the intersection and each run's exclusive remainder using the named overlap
criterion `similarity.interval_iou`. `UI.workspaces.analyse.compare` renders
that result and routes an exclusive remainder into the Review queue.

These tests are deliberately headless: the core tests use an in-memory SQLite
database and synthetic detection rows; the UI tests use a fake app with only
the `.conn` attribute the surface reads.
"""

import inspect
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import panel as pn
pn.extension()

from Working.database import queries as q
from Working.database import runs as run_db
from Working.database.schema import init_db
from Working.database.similarity import interval_iou
from UI.workspaces.review.queue_state import ReviewQueue


def _make_db():
    """A fresh in-memory database with one recording and two completed runs."""
    conn = init_db(":memory:")
    recording_id = q.insert_recording(conn, "fake.mat", 0, 1.0, 10_000, 0, "fake.npy")
    config_id, _ = run_db.get_or_create_config(conn, {"steps": []})
    run_a = run_db.insert_run(conn, config_id, recording_id, 0, 10_000, status="completed")
    run_b = run_db.insert_run(conn, config_id, recording_id, 0, 10_000, status="completed")
    return conn, run_a, run_b


def _add_detections(conn, run_id, spans):
    """Insert detections for `spans` and return their ids in order."""
    return [run_db.insert_detection(conn, run_id, s, e) for s, e in spans]


def _close(conn):
    conn.close()


# ── headless core: Working.compare ─────────────────────────────────────────

def test_compare_reports_intersection_and_exclusive_remainders():
    from Working.compare import compare_run_sets

    conn, run_a, run_b = _make_db()
    try:
        a_ids = _add_detections(conn, run_a, [(0, 10), (20, 30), (40, 50)])
        b_ids = _add_detections(conn, run_b, [(0, 10), (25, 35), (60, 70)])

        result = compare_run_sets(conn, run_a, run_b, iou_threshold=0.5)

        assert result.overlap_criterion == "interval_iou"
        assert result.iou_threshold == 0.5

        # [0,10) is identical in both runs; the other spans do not clear a
        # 0.5 IoU threshold.
        assert [(p.a_detection_id, p.b_detection_id) for p in result.intersection] == [
            (a_ids[0], b_ids[0])
        ]
        assert {row["id"] for row in result.a_only} == {a_ids[1], a_ids[2]}
        assert {row["id"] for row in result.b_only} == {b_ids[1], b_ids[2]}

        assert result.counts == {
            "a_total": 3,
            "b_total": 3,
            "intersection": 1,
            "a_only": 2,
            "b_only": 2,
        }
    finally:
        _close(conn)


def test_compare_matches_by_interval_iou_not_duplicate_counting():
    from Working.compare import compare_run_sets

    conn, run_a, run_b = _make_db()
    try:
        a_ids = _add_detections(conn, run_a, [(0, 10), (20, 30)])
        b_ids = _add_detections(conn, run_b, [(0, 10), (2, 12)])

        result = compare_run_sets(conn, run_a, run_b, iou_threshold=0.5)

        # Both B spans overlap A[0,10), but one match consumes A[0,10) and
        # leaves B[2,12) as an exclusive B remainder.
        assert [(p.a_detection_id, p.b_detection_id) for p in result.intersection] == [
            (a_ids[0], b_ids[0])
        ]
        assert {row["id"] for row in result.a_only} == {a_ids[1]}
        assert {row["id"] for row in result.b_only} == {b_ids[1]}
        assert result.counts["intersection"] == 1
    finally:
        _close(conn)


def test_compare_uses_interval_iou_values_for_matches():
    from Working.compare import compare_run_sets

    conn, run_a, run_b = _make_db()
    try:
        a_id = _add_detections(conn, run_a, [(0, 10)])[0]
        b_id = _add_detections(conn, run_b, [(0, 10)])[0]

        result = compare_run_sets(conn, run_a, run_b, iou_threshold=0.5)

        assert len(result.intersection) == 1
        pair = result.intersection[0]
        assert pair.a_detection_id == a_id
        assert pair.b_detection_id == b_id
        assert pair.iou == interval_iou(0, 10, 0, 10) == 1.0
    finally:
        _close(conn)


def test_compare_refuses_incomplete_runs():
    from Working.compare import compare_run_sets

    conn, run_a, run_b = _make_db()
    try:
        run_db.update_run(conn, run_b, status="running")
        with pytest.raises(ValueError):
            compare_run_sets(conn, run_a, run_b)
    finally:
        _close(conn)


def test_compare_rejects_an_unknown_overlap_criterion():
    from Working.compare import compare_run_sets

    conn, run_a, run_b = _make_db()
    try:
        with pytest.raises(ValueError):
            compare_run_sets(conn, run_a, run_b, overlap_criterion="shape_distance")
    finally:
        _close(conn)


# ── UI surface: CompareSurface ─────────────────────────────────────────────

class _FakeApp:
    """The minimal app shape the surface reads: a live connection."""

    def __init__(self, conn):
        self.conn = conn


class _FakeReviewSurface:
    def __init__(self, conn):
        self.queue = ReviewQueue(conn)
        self.activated = []

    def on_tab_activated(self):
        self.activated.append(True)


class _RoutableFakeApp(_FakeApp):
    def __init__(self, conn, review_surface):
        super().__init__(conn)
        self.review_surface = review_surface
        self.activations = []

    def activate_workspace(self, workspace, section=None):
        self.activations.append((workspace, section))


def test_compare_surface_construction_returns_non_none_panes():
    from UI.workspaces.analyse.compare import CompareSurface

    conn, run_a, run_b = _make_db()
    try:
        _add_detections(conn, run_a, [(0, 10)])
        _add_detections(conn, run_b, [(20, 30)])

        surface = CompareSurface(_FakeApp(conn))
        layout = surface.layout()

        assert layout is not None
        for pane in (
            surface.run_a_select,
            surface.run_b_select,
            surface.compare_button,
            surface.review_a_button,
            surface.review_b_button,
            surface.summary_pane,
            surface.detail_pane,
        ):
            assert pane is not None, "a Compare pane must never be None"
    finally:
        _close(conn)


def test_compare_surface_shows_counts_after_compare():
    from UI.workspaces.analyse.compare import CompareSurface

    conn, run_a, run_b = _make_db()
    try:
        _add_detections(conn, run_a, [(0, 10)])
        _add_detections(conn, run_b, [(20, 30)])

        surface = CompareSurface(_FakeApp(conn))
        surface.run_a_select.value = run_a
        surface.run_b_select.value = run_b
        surface._on_compare()

        assert surface._comparison is not None
        assert "Intersection" in surface.summary_pane.object
        assert "A-only" in surface.summary_pane.object
        assert "B-only" in surface.summary_pane.object
    finally:
        _close(conn)


def test_compare_surface_routes_exclusive_remainder_to_review_queue():
    from UI.workspaces.analyse.compare import CompareSurface

    conn, run_a, run_b = _make_db()
    try:
        _add_detections(conn, run_a, [(0, 10)])
        _add_detections(conn, run_b, [(20, 30)])

        review = _FakeReviewSurface(conn)
        app = _RoutableFakeApp(conn, review)
        surface = CompareSurface(app)
        surface.run_a_select.value = run_a
        surface.run_b_select.value = run_b
        surface._on_compare()

        surface._route_to_review("a")

        assert app.activations[-1] == ("Review", "Candidate queue")
        assert review.activated, "routing into Review must re-render its queue"
        assert all(row["run_id"] == run_a for row in review.queue.candidates)

        surface._route_to_review("b")
        assert app.activations[-1] == ("Review", "Candidate queue")
        assert all(row["run_id"] == run_b for row in review.queue.candidates)
    finally:
        _close(conn)


def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
