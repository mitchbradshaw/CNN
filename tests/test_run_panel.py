"""
test_run_panel.py
===================
Tests for Part 5 (2026-08): the Run algorithm tab's pre-run preview
(Section A) and the Before/After comparison's y-axis handling (Section B).

Real-data-gated (ViewerApp needs a real channel .npy), same convention as
tests/test_ribbon_panes.py. Always a fresh temp sqlite file, never
DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_run_panel.py
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
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from UI.app import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600
CENTER = 12_300


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_run_panel.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name, rid


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _curve_x_extent(curve):
    """(t_min, t_max) of a single hv.Curve's underlying data — used to
    check WHICH span a preview curve actually shows without depending on
    exact opt internals."""
    t = curve.dimension_values(0)
    return float(t.min()), float(t.max())


# ── A1/A2: preview renders on arrival, single-plot vs. Before/After ────────

def test_preview_renders_on_arrival_with_a_staged_span():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._stage_span(1000, 1600, annotation_id=None)
        rp.span_mode.value = "Selected span"
        assert isinstance(rp.result_pane.object, hv.Curve), (
            "arriving with a staged span should show a single unprocessed-signal curve, "
            f"got {type(rp.result_pane.object)}"
        )
        assert "not yet processed" in rp.result_pane.object.opts.get("plot").kwargs.get("title", "").lower()
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        # end_idx is exclusive, so the last plotted sample is at 1599, not 1600.
        assert abs(t0 - 1000.0) < 1.0 and abs(t1 - 1599.0) < 1.0, (
            f"preview should span the staged sample range (1000-1600), got ({t0}, {t1})"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_result_pane_never_shows_stale_single_plot_alongside_before_after():
    """A2: after `_show_before_after` runs, the pane holds the Layout pair
    (not the earlier single Curve); switching span context afterwards
    reverts it to a fresh single-plot preview, never leaving both."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)
        rp._show_before_after(recording, result_x, result_t)
        assert isinstance(rp.result_pane.object, hv.Layout), "after a run, expected the Before/After Layout"

        rp.span_mode.value = "Whole channel"
        assert isinstance(rp.result_pane.object, hv.Curve), (
            "changing span context after a run should replace the stale Before/After "
            f"pair with a fresh single-plot preview, got {type(rp.result_pane.object)}"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── A4: span mode changes the preview ───────────────────────────────────────

def test_preview_updates_on_span_mode_change():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        # span_mode already defaults to "Current viewport" -- assigning the
        # SAME value wouldn't fire its param.watch, so simulate the real
        # trigger (arriving/re-arriving on the tab) explicitly instead.
        app._range_stream.event(x_range=(5000.0, 5100.0))
        app._refresh_view()
        rp._on_span_context_changed()
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 5000.0) < 1.0 and abs(t1 - 5099.0) < 1.0, (
            f"'Current viewport' preview should match the viewer's x_range, got ({t0}, {t1})"
        )

        rp.span_mode.value = "Whole channel"
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert t1 > 100000, f"'Whole channel' preview should span the full channel, got ({t0}, {t1})"
    finally:
        _close_and_unlink(app, db_path)


# ── A3: staged-row selection changes the preview ────────────────────────────

def test_preview_updates_on_staged_row_selection():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._stage_span(1000, 1600, annotation_id=None)
        app._stage_span(9000, 9600, annotation_id=None)
        rp.span_mode.value = "Selected span"

        # Nothing explicitly selected -> first row (1000-1600).
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 1000.0) < 1.0, f"expected first staged row by default, got ({t0}, {t1})"

        # Select the second row -> preview follows it.
        rp.staged_table.selection = [1]
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 9000.0) < 1.0 and abs(t1 - 9599.0) < 1.0, (
            f"selecting staged row 1 should preview 9000-9600, got ({t0}, {t1})"
        )
        assert "2/2" in rp.preview_info.object, (
            f"preview_info should make clear which staged row is shown, got {rp.preview_info.object!r}"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── B2/B3: independent vs. shared y-axis ────────────────────────────────────

def test_independent_yaxis_gives_each_panel_its_own_tight_range():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        # Tiny-amplitude "after" against the raw channel's much larger
        # DC-offset range as "before" -- the exact bandpass-filter scenario
        # from the bug report.
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)

        assert rp.yaxis_mode.value == "Independent y-axis", "default must be independent (B2)"
        rp._show_before_after(recording, result_x, result_t)
        before_curve, after_curve = list(rp.result_pane.object.values())
        before_ylim = before_curve.opts.get("plot").kwargs["ylim"]
        after_ylim = after_curve.opts.get("plot").kwargs["ylim"]
        after_span = after_ylim[1] - after_ylim[0]
        before_span = before_ylim[1] - before_ylim[0]
        assert after_span < before_span / 100, (
            f"independent mode should give the tiny 'after' signal its own tight range, "
            f"got before={before_ylim} after={after_ylim}"
        )
        # B3: the numeric range is visible in each title.
        assert "y:" in before_curve.opts.get("plot").kwargs["title"]
        assert "y:" in after_curve.opts.get("plot").kwargs["title"]
        # B4: the scale-change note is populated.
        assert rp.scale_note.object != ""
    finally:
        _close_and_unlink(app, db_path)


def test_shared_yaxis_gives_both_panels_the_identical_combined_range():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)

        rp.yaxis_mode.value = "Shared y-axis"
        rp._show_before_after(recording, result_x, result_t)
        before_curve, after_curve = list(rp.result_pane.object.values())
        before_ylim = before_curve.opts.get("plot").kwargs["ylim"]
        after_ylim = after_curve.opts.get("plot").kwargs["ylim"]
        assert before_ylim == after_ylim, (
            f"shared mode should give both panels the identical combined range, "
            f"got before={before_ylim} after={after_ylim}"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_yaxis_toggle_rerenders_last_result_without_rerunning():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)
        rp._show_before_after(recording, result_x, result_t)

        rp.yaxis_mode.value = "Shared y-axis"
        before_curve, after_curve = list(rp.result_pane.object.values())
        assert before_curve.opts.get("plot").kwargs["ylim"] == after_curve.opts.get("plot").kwargs["ylim"]

        rp.yaxis_mode.value = "Independent y-axis"
        before_curve, after_curve = list(rp.result_pane.object.values())
        assert before_curve.opts.get("plot").kwargs["ylim"] != after_curve.opts.get("plot").kwargs["ylim"]
    finally:
        _close_and_unlink(app, db_path)


# ── C3/C4: placeholders and motif-button gating ─────────────────────────────

def test_detections_placeholder_shown_before_first_run():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        assert rp.detections_table.visible is False
        assert rp.detections_placeholder.visible is True
        rp._show_detections([{"id": 1, "start_idx": 0, "end_idx": 10, "score": 0.5}])
        assert rp.detections_table.visible is True
        assert rp.detections_placeholder.visible is False
    finally:
        _close_and_unlink(app, db_path)


def test_motif_buttons_disabled_until_run_or_valid_span():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        assert rp.save_motif_button.disabled is True, "no detections yet -> disabled"

        rp.span_mode.value = "Whole channel"
        assert rp.save_viewport_motif_button.disabled is True, "'Whole channel' has no manual span"

        rp.span_mode.value = "Current viewport"
        assert rp.save_viewport_motif_button.disabled is False, "a real viewport is a valid manual span"

        rp._show_detections([{"id": 1, "start_idx": 0, "end_idx": 10, "score": 0.5}])
        rp._update_motif_button_states()  # real trigger is `_on_run_finished`; called directly here
        assert rp.save_motif_button.disabled is False, "detections now exist -> enabled"
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
