"""
test_filters.py
=================
Tests for UI/app.py's ViewerApp._filtered_annotation_rows: single-value
filters, multi-value filters WITHIN one category (must be OR — a reported
bug claimed this was incorrectly AND-ing, making multi-select return
nothing), and combinations ACROSS categories (must be AND). Also pins that
the table, the plot overlay, and the live filter counts all route through
this one function, not independently-written copies.

Real-data-gated (ViewerApp needs a real channel .npy), same convention as
tests/test_ui_selection.py. Always a fresh temp sqlite file, never
DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_filters.py
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

import panel as pn
pn.extension()

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import vocabulary as v
from UI.app import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app_with_disjoint_annotations():
    """4 annotations, one per verdict, at well-separated, non-overlapping
    positions, plus 2 with distinct sources and 2 with distinct element
    tags -- disjoint enough that OR/AND behavior is unambiguous from
    counts alone."""
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_filters.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    v.seed_vocabulary(conn)

    verdicts = ["interesting", "not_interesting", "artifact", "unsure"]
    aids = {}
    for i, verdict in enumerate(verdicts):
        aid = q.insert_annotation(conn, rid, i * 10_000, i * 10_000 + 100, verdict,
                                   source=q.SOURCE_MANUAL_UI)
        aids[verdict] = aid

    # Distinct sources for the source-filter test.
    q.insert_annotation(conn, rid, 100_000, 100_100, "interesting", source="excel_catalog")

    # Distinct element tags for the tag-filter test.
    v.set_annotation_tags(conn, aids["interesting"], "element", ["sharkfin"])
    v.set_annotation_tags(conn, aids["artifact"], "element", ["ridge"])

    conn.close()
    # Every test in this file must be isolated from the real session file
    # (Part E9) -- a fresh app here restoring leftover filter/tag state
    # from an unrelated database is exactly the kind of cross-test
    # contamination that silently reduced a filtered-row count once
    # already; see tests/_session_isolation.py. Kept open for the app's
    # whole lifetime (not just construction) and closed in
    # `_close_and_unlink`, since a test may itself set filters mid-run.
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    return app, tf.name, aids


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


# ── verdict: single vs multi-value (the exact reported symptom) ────────────

def test_single_verdict_filter():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_verdict.value = ["interesting"]
        rows = app._filtered_annotation_rows()
        assert {r["verdict"] for r in rows} == {"interesting"}
        assert len(rows) == 2  # the manual_ui one + the excel_catalog one
    finally:
        _close_and_unlink(app, db_path)


def test_multi_value_verdict_filter_is_or_not_and():
    """The exact reported bug: selecting two verdicts must return the
    UNION (both), never an empty result."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_verdict.value = ["interesting", "not_interesting"]
        rows = app._filtered_annotation_rows()
        assert len(rows) > 0, "multi-value verdict filter returned NOTHING -- reproduces the reported bug"
        assert {r["verdict"] for r in rows} == {"interesting", "not_interesting"}
        assert len(rows) == 3  # 2 interesting (manual_ui + excel_catalog) + 1 not_interesting
    finally:
        _close_and_unlink(app, db_path)


def test_all_four_verdicts_selected_returns_everything():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_verdict.value = ["interesting", "not_interesting", "artifact", "unsure"]
        rows = app._filtered_annotation_rows()
        assert len(rows) == 5  # all annotations
    finally:
        _close_and_unlink(app, db_path)


# ── source: multi-value OR ──────────────────────────────────────────────────

def test_multi_value_source_filter_is_or():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_source.value = ["manual_ui"]
        manual_only = len(app._filtered_annotation_rows())
        app.filter_source.value = ["excel_catalog"]
        excel_only = len(app._filtered_annotation_rows())
        app.filter_source.value = ["manual_ui", "excel_catalog"]
        both = len(app._filtered_annotation_rows())
        assert both == manual_only + excel_only  # disjoint union, not empty/AND
    finally:
        _close_and_unlink(app, db_path)


# ── tags: multi-value OR within category ────────────────────────────────────

def test_multi_value_element_tag_filter_is_or():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_tag_widgets["element"].value = ["sharkfin"]
        sharkfin_only = len(app._filtered_annotation_rows())
        app.filter_tag_widgets["element"].value = ["ridge"]
        ridge_only = len(app._filtered_annotation_rows())
        app.filter_tag_widgets["element"].value = ["sharkfin", "ridge"]
        both = len(app._filtered_annotation_rows())
        assert sharkfin_only == 1 and ridge_only == 1
        assert both == 2, "multi-value tag filter did not union -- looks AND-ed, not OR-ed"
    finally:
        _close_and_unlink(app, db_path)


# ── cross-category: AND ─────────────────────────────────────────────────────

def test_cross_category_filters_are_anded():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        # interesting (2 rows) AND source=excel_catalog (1 of those 2) -> 1
        app.filter_verdict.value = ["interesting"]
        app.filter_source.value = ["excel_catalog"]
        rows = app._filtered_annotation_rows()
        assert len(rows) == 1
        assert rows[0]["verdict"] == "interesting" and rows[0]["source"] == "excel_catalog"
    finally:
        _close_and_unlink(app, db_path)


def test_cross_category_filters_can_produce_empty_result_correctly():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        # artifact AND source=excel_catalog -> genuinely no such row (correct AND,
        # not the multi-value-within-one-category bug).
        app.filter_verdict.value = ["artifact"]
        app.filter_source.value = ["excel_catalog"]
        rows = app._filtered_annotation_rows()
        assert rows == []
    finally:
        _close_and_unlink(app, db_path)


# ── table / plot / counts all use the same function ─────────────────────────

def test_table_and_filtered_rows_agree():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.filter_verdict.value = ["interesting", "not_interesting"]
        app._refresh_table()
        assert len(app.annotations_table.value) == len(app._filtered_annotation_rows())
    finally:
        _close_and_unlink(app, db_path)


def test_plot_overlay_reflects_same_filtered_count():
    """Part A (2026-08): individual annotation rectangles now render in
    `app.annotation_ribbon_pane` (a separate pane), not overlaid on
    `app.plot_pane` -- see UI/plots.py's module docstring."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, aids = _fresh_app_with_disjoint_annotations()
    try:
        app.channel = 0
        app.filter_verdict.value = ["interesting", "not_interesting"]
        app._refresh_view()
        overlay = app.annotation_ribbon_pane.object[()]
        import holoviews as hv
        total_rects = sum(
            len(el.data) for el in overlay
            if isinstance(el, hv.Rectangles) and "annotation_id" in [str(d) for d in el.vdims]
        )
        assert total_rects == len(app._filtered_annotation_rows())
    finally:
        _close_and_unlink(app, db_path)


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
