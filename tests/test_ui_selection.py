"""
test_ui_selection.py
======================
Tests for UI/app.py's shared table<->plot selection model, sample-boundary
snapping on the pending-span steppers, and the cross-tab staging basket.

The first UI-level test in this repo — ViewerApp requires a real channel
.npy (build_channel_dmap memory-maps it), so this follows the same
real-data-gated convention as tests/test_execution.py: skip if the data
isn't present locally, never touch DATA/db/annotations.sqlite (a fresh
temp sqlite file per test, with one fabricated `recordings` row pointing
at the real channel), and always close the connection before unlinking
(Windows/Drive-synced folders hold a file lock otherwise).

Run from the project root:
    python tests/test_ui_selection.py
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
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_selection.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    # A few fabricated annotations with different verdicts, far apart, so
    # selection/filter tests below have real rows to work with — a fresh
    # temp DB otherwise starts with none.
    q.insert_annotation(conn, rid, 12000, 12600, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 50000, 50600, "artifact", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 90000, 90300, "not_interesting", source=q.SOURCE_MANUAL_UI)
    conn.close()
    # Isolate from the real session file (Part E9) -- see
    # tests/_session_isolation.py. Kept open for the app's whole
    # lifetime, closed in `_close_and_unlink`.
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()  # populates app.tabs, needed by staging's tab-switch
    return app, tf.name


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


# ── sample-boundary snapping (Part 2a) ──────────────────────────────────────

def test_subsample_drag_snaps_to_exact_sample_boundary():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        app._set_pending_bounds(100.37, 250.91)  # fs=1.0Hz -> not sample-aligned
        assert app._pending_bounds == (100.0, 251.0), app._pending_bounds
    finally:
        _close_and_unlink(app, db_path)


def test_snapped_bounds_produce_integer_sample_indices_in_saved_annotation():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        app._set_pending_bounds(1000.2, 1100.8)
        aid = app._save_annotation()
        assert aid is not None
        row = q.get_annotation(app.conn, aid)
        # No sub-sample time reached the database -- both indices are the
        # nearest whole sample, matching what round(x * fs) would give.
        assert row["start_idx"] == 1000
        assert row["end_idx"] == 1101
    finally:
        _close_and_unlink(app, db_path)


def test_saved_indices_identical_regardless_of_display_unit():
    """Regression test: a since-fixed bug made the annotation/reviewed/
    detection *overlays* render ~3600x misaligned in hours mode (see
    UI/plots.py module docstring, bug 4). That was confirmed rendering-only
    by an explicit code audit (every write-adjacent conversion — save,
    mark-reviewed, stage, select-in-range — already multiplied by
    `_unit_scale()`), but this pins the actual end-to-end behavior: the
    SAME real-world span, dragged once in seconds mode and once in hours
    mode (Bokeh reports drag coordinates in whatever the curve's current
    axis unit is), must produce byte-identical stored sample indices.
    """
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        app.drag_mode.value = "New span"
        app._bounds_stream.event(boundsx=(100000.0, 100600.0))
        aid_seconds = app._save_annotation()
        row_seconds = q.get_annotation(app.conn, aid_seconds)

        app.time_unit_toggle.value = "hours"
        # The same real-world span (100000s-100600s), expressed in hours --
        # exactly what a live drag on the now-hours-scaled curve would report.
        app._bounds_stream.event(boundsx=(100000.0 / 3600.0, 100600.0 / 3600.0))
        aid_hours = app._save_annotation()
        row_hours = q.get_annotation(app.conn, aid_hours)

        assert row_seconds["start_idx"] == row_hours["start_idx"] == 100000
        assert row_seconds["end_idx"] == row_hours["end_idx"] == 100600
    finally:
        _close_and_unlink(app, db_path)


def test_stepper_step_size_matches_one_sample_period():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        assert app.start_time_input.step == 1.0 / app._fs  # fs=1.0Hz here -> 1.0s
        app.time_unit_toggle.value = "hours"
        assert abs(app.start_time_input.step - 1.0 / app._fs / 3600.0) < 1e-12
    finally:
        _close_and_unlink(app, db_path)


def test_zero_or_negative_width_after_snapping_clears_pending_bounds():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        # Both ends round to the same sample -> zero-width, must not be saved as a span.
        app._set_pending_bounds(100.01, 100.02)
        assert app._pending_bounds is None
    finally:
        _close_and_unlink(app, db_path)


# ── selection re-entrancy guard ─────────────────────────────────────────────

def test_table_to_model_sync_does_not_reenter_infinitely():
    """The watcher is bound (`self.annotations_table.param.watch(self.
    _on_table_selection_changed, ...)`) at __init__ time, so it must be
    patched on the CLASS before construction — patching it on an
    already-built instance's class afterward doesn't reach an already-bound
    Param watcher reference."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    calls = {"n": 0}
    orig = ViewerApp._on_table_selection_changed

    def counting(self, event):
        calls["n"] += 1
        if calls["n"] > 20:
            raise RuntimeError("reentrancy loop")
        return orig(self, event)

    ViewerApp._on_table_selection_changed = counting
    try:
        app, db_path = _fresh_app()
        try:
            calls["n"] = 0  # ignore any watcher firings during construction/layout
            app.annotations_table.selection = [0]
            first_count = calls["n"]
            assert first_count >= 1

            app._selected_annotation_ids = set()
            app._sync_table_selection_from_ids()  # sets .selection under the guard flag
            # The watcher fires again (Param always calls watchers on
            # assignment) but the guard makes it a no-op immediately —
            # bounded, not runaway.
            assert calls["n"] <= first_count + 2

            assert app._updating_annotation_selection is False
            assert app.annotations_table.selection == []
            assert app._selected_annotation_ids == set()
        finally:
            _close_and_unlink(app, db_path)
    finally:
        ViewerApp._on_table_selection_changed = orig


def test_selection_persists_across_filter_change_with_hidden_count():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        rows = app._filtered_annotation_rows()
        if len(rows) < 2:
            print("  (skipped: fewer than 2 annotations on this test channel)")
            return
        target = rows[0]
        other_verdicts = sorted({r["verdict"] for r in rows if r["verdict"] != target["verdict"]})
        if not other_verdicts:
            print("  (skipped: only one verdict present on this channel)")
            return

        app._selected_annotation_ids = {target["id"]}
        app._refresh_table()
        assert app.annotation_selection_info.object == "**1 selected, pinned to top**"

        app.filter_verdict.value = other_verdicts  # excludes target's verdict
        assert target["id"] in app._selected_annotation_ids  # not dropped
        assert "hidden by filters" in app.annotation_selection_info.object
        assert app.annotations_table.selection == []  # not visible -> not checked

        app.filter_verdict.value = []  # clear filter
        assert app.annotation_selection_info.object == "**1 selected, pinned to top**"
        assert app.annotations_table.selection == [0]
    finally:
        _close_and_unlink(app, db_path)


def test_annotation_toggle_selection_via_box_select():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        rows = app._filtered_annotation_rows()
        if not rows:
            print("  (skipped: no annotations on this test channel)")
            return
        first = rows[0]
        app.drag_mode.value = "Select annotations"
        app._bounds_stream.event(boundsx=(first["start_idx"] + 1, first["end_idx"] - 1))
        assert first["id"] in app._selected_annotation_ids
        # Same drag again -> toggles off.
        app._bounds_stream.event(boundsx=(first["start_idx"] + 1, first["end_idx"] - 1))
        assert first["id"] not in app._selected_annotation_ids
    finally:
        _close_and_unlink(app, db_path)


def _fresh_app_many_annotations(n=30):
    """More rows than `page_size` (12), spread far enough apart that a
    box-select drag can target exactly one without touching its
    neighbours -- needed to test that a plot-driven selection reaches
    page 1 even when the selected row started out on a later page."""
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_many.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    ids = []
    for i in range(n):
        aid = q.insert_annotation(conn, rid, i * 10_000, i * 10_000 + 500,
                                   "interesting", source=q.SOURCE_MANUAL_UI)
        ids.append(aid)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name, ids


def test_plot_selection_repins_table_not_just_checkbox():
    """E1/E2 regression: the reported bug -- a plot-drag selection updated
    the checkbox/info-panel count but left the table's pin markers and
    sort order stale, so a newly-selected row (especially one from a
    LATER page) never actually reached page 1 and didn't show a pin icon
    even where it was already visible."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, ids = _fresh_app_many_annotations(30)
    try:
        # Annotation index 25 -- with 30 rows sorted by start_idx and a
        # page size of 12, this starts on page 3, nowhere near page 1.
        target_row = q.get_annotation(app.conn, ids[25])
        app.drag_mode.value = "Select annotations"
        app._bounds_stream.event(
            boundsx=(target_row["start_idx"] + 1, target_row["end_idx"] - 1)
        )
        assert target_row["id"] in app._selected_annotation_ids

        df = app.annotations_table.value
        page_size = app.annotations_table.page_size
        first_page_ids = df["id"].iloc[:page_size].tolist()
        assert target_row["id"] in first_page_ids, (
            "a plot-selected row from a later page did not reach page 1 "
            "of the table"
        )
        pinned_col = df.set_index("id")["pinned"]
        assert pinned_col.loc[target_row["id"]] != "", (
            "the plot-selected row has no pin marker"
        )
        # Every OTHER row on page 1 must be unpinned -- pin marker is
        # exact, not "everything near the top looks pinned".
        for rid in first_page_ids:
            if rid != target_row["id"]:
                assert pinned_col.loc[rid] == ""
    finally:
        _close_and_unlink(app, db_path)


def test_plot_selection_of_two_annotations_both_reach_page_one():
    """The exact reported symptom: 2 selected via the plot, but only one
    pin marker visible. Both must be pinned and both must be on page 1."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, ids = _fresh_app_many_annotations(30)
    try:
        row_a = q.get_annotation(app.conn, ids[10])
        row_b = q.get_annotation(app.conn, ids[20])
        app.drag_mode.value = "Select annotations"
        app._bounds_stream.event(boundsx=(row_a["start_idx"] + 1, row_a["end_idx"] - 1))
        app._bounds_stream.event(boundsx=(row_b["start_idx"] + 1, row_b["end_idx"] - 1))
        assert app._selected_annotation_ids == {row_a["id"], row_b["id"]}
        assert "2 selected" in app.annotation_selection_info.object

        df = app.annotations_table.value
        page_size = app.annotations_table.page_size
        first_page_ids = set(df["id"].iloc[:page_size].tolist())
        assert row_a["id"] in first_page_ids and row_b["id"] in first_page_ids

        pinned_col = df.set_index("id")["pinned"]
        assert pinned_col.loc[row_a["id"]] != "" and pinned_col.loc[row_b["id"]] != "", (
            "both plot-selected annotations must show a pin marker, not just one"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── staged spans survive a tab switch (Part 3) ──────────────────────────────

def test_staged_spans_survive_tab_switch():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        app.drag_mode.value = "New span"
        app._bounds_stream.event(boundsx=(1000.0, 1100.0))
        app._on_stage_pending()
        assert len(app._staged_spans) == 1
        assert app.tabs.active == 1  # switched to "Run algorithm"

        app.tabs.active = 0  # switch back to Viewer
        app.tabs.active = 2  # and to Run history
        app.tabs.active = 1  # back to Run algorithm

        assert len(app._staged_spans) == 1, "staged span was lost across tab switches"
        staged = app._staged_spans[0]
        assert staged["start_idx"] == 1000 and staged["end_idx"] == 1100
        assert staged["annotation_id"] is None
        assert len(app.run_panel.staged_table.value) == 1
    finally:
        _close_and_unlink(app, db_path)


def test_stage_from_selected_annotations():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        rows = app._filtered_annotation_rows()
        if len(rows) < 2:
            print("  (skipped: fewer than 2 annotations on this test channel)")
            return
        app._selected_annotation_ids = {rows[0]["id"], rows[1]["id"]}
        app._on_run_selected()
        assert len(app._staged_spans) == 2
        staged_ids = {s["annotation_id"] for s in app._staged_spans}
        assert staged_ids == {rows[0]["id"], rows[1]["id"]}
        assert app.tabs.active == 1
    finally:
        _close_and_unlink(app, db_path)


def test_remove_and_clear_staged_spans():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        app._stage_span(100, 200, annotation_id=None)
        app._stage_span(300, 400, annotation_id=None)
        assert len(app._staged_spans) == 2

        app.run_panel.staged_table.selection = [0]
        app.run_panel._on_remove_staged()
        assert len(app._staged_spans) == 1
        assert app._staged_spans[0]["start_idx"] == 300

        app.run_panel._on_clear_staged()
        assert app._staged_spans == []
        assert len(app.run_panel.staged_table.value) == 0
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
