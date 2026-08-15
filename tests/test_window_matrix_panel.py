"""
test_window_matrix_panel.py
=============================
Headless tests for UI.window_matrix_panel.WindowMatrixPanel
(WINDOW_MATRIX_UI_PROMPT.md §8.2/§3.1-3.4) — no browser, follows
tests/test_run_panel.py's approach of instantiating the real UI objects
against a temp DB, never a live server.

Always a fresh temp sqlite file and a synthetic channel .npy (not the real
channel data, and never DATA/db/annotations.sqlite), and the session file is
redirected via tests._session_isolation.scratch_session_file so a
test-created ViewerApp can't read or write real UI session state.

Calibration is pre-seeded into an isolated temp calibration file (same
pattern as tests/test_wm_cost.py) so tests run fast and deterministically
instead of racing a background auto-calibration thread.

Run from the project root:
    python tests/test_window_matrix_panel.py
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

from Working.config import WM_SCALE_LADDER_MIN
from Working.database.schema import init_db
from Working.database import queries as q
import Working.Preprocessing.window_matrix.cost as cost
from UI.app import ViewerApp
from tests._session_isolation import scratch_session_file
from tests._calibration_isolation import scratch_calibration

N_SAMPLES = 24_000  # fs=1 -> long enough for 1/10/60 min, too short for 600 min


def _IsolatedCalibration():
    """Same as tests/test_wm_cost.py's helper — redirects
    `cost.CALIBRATION_PATH` so nothing here touches the real
    DATA/db/wm_calibration.json. Shared implementation in
    `tests/_calibration_isolation.py`; the previous local copy leaked its temp
    file on exit."""
    return scratch_calibration(cost)


def _fresh_app_with_recording():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    npy_dir = tempfile.mkdtemp(prefix="wm_panel_test_")
    npy_path = os.path.join(npy_dir, "CH0.npy")
    np.save(npy_path, np.random.default_rng(0).standard_normal(N_SAMPLES))

    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_wm_panel.mat", 0, 1.0, N_SAMPLES, 0, npy_path)
    conn.close()

    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    app.source_file, app.channel = "UNITTEST_wm_panel.mat", 0
    app._load_recording()
    return app, tf.name, npy_dir


def _close(app, db_path, npy_dir):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)
    import shutil
    shutil.rmtree(npy_dir, ignore_errors=True)


def _select_window_matrix(app):
    rp = app.run_panel
    rp.stage_select.value = "preprocessing"
    rp._on_stage_changed(None)
    rp.algorithm_select.value = "preprocessing.window_matrix"
    rp._on_algorithm_changed(None)
    return rp


# ── Visibility (§3.1) ────────────────────────────────────────────────────────

def test_hidden_for_a_non_window_matrix_algorithm():
    app, db_path, npy_dir = _fresh_app_with_recording()
    try:
        rp = app.run_panel
        rp.stage_select.value = "preprocessing"
        rp._on_stage_changed(None)
        # Whatever the first preprocessing algorithm alphabetically is,
        # explicitly force something that is NOT window_matrix.
        rp.algorithm_select.value = "preprocessing.detrend"
        rp._on_algorithm_changed(None)
        assert rp.window_matrix_panel.visible is False
        assert rp.window_matrix_panel.card.visible is False
    finally:
        _close(app, db_path, npy_dir)


def test_visible_for_window_matrix_algorithm():
    app, db_path, npy_dir = _fresh_app_with_recording()
    try:
        rp = _select_window_matrix(app)
        assert rp.window_matrix_panel.visible is True
    finally:
        _close(app, db_path, npy_dir)


def test_auto_preview_does_not_crash_for_window_matrix():
    """Regression test: `preprocessing.window_matrix` is `output_kind ==
    "encoding"` (like SAX), but its `result.meta` has none of SAX's
    `x`/`t`/`details` shape — `_run_auto_preview` used to call
    `_show_encoding(..., result.meta["details"], ...)` unconditionally for
    any 'encoding'-kind adapter, which raised `KeyError('details')` live
    the moment auto-preview fired for window_matrix (real traceback landed
    in Working.execution._execute_recipe_with_conn via
    UI/run_panel.py's `_run_auto_preview`). Fixed by gating both
    `_schedule_auto_preview` and `_run_auto_preview` on
    `_is_sax_shaped_encoding`, since matrix profile and the window matrix
    are both 'encoding'-kind but neither is SAX-shaped."""
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            rp.auto_preview_checkbox.value = True
            rp._run_auto_preview()  # must not raise
            assert rp.encoding_section.visible is False
        finally:
            _close(app, db_path, npy_dir)


def test_schedule_auto_preview_is_a_noop_for_window_matrix():
    app, db_path, npy_dir = _fresh_app_with_recording()
    try:
        rp = _select_window_matrix(app)
        rp.auto_preview_checkbox.value = True
        rp._schedule_auto_preview()
        assert rp._auto_preview_timer is None
    finally:
        _close(app, db_path, npy_dir)


def test_switching_away_hides_it_again():
    app, db_path, npy_dir = _fresh_app_with_recording()
    try:
        rp = _select_window_matrix(app)
        assert rp.window_matrix_panel.visible is True
        rp.algorithm_select.value = "preprocessing.detrend"
        rp._on_algorithm_changed(None)
        assert rp.window_matrix_panel.visible is False
    finally:
        _close(app, db_path, npy_dir)


# ── The ladder (§3.2) ────────────────────────────────────────────────────────

def test_ladder_renders_one_entry_per_scale():
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            assert len(wp.scale_radio.options) == len(WM_SCALE_LADDER_MIN)
            assert set(wp._ladder_rows.keys()) == set(WM_SCALE_LADDER_MIN)
        finally:
            _close(app, db_path, npy_dir)


def test_invalid_entry_has_no_compute_button():
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            # 24,000 samples at fs=1 admits at most one 600-minute (36,000
            # sample) window -- actually zero, since 36000 > 24000 -- so the
            # 600-min entry must be "invalid", not "missing".
            row_600 = wp._ladder_rows[600]
            assert row_600["state"] == "invalid"

            label_600 = next(opt for opt, wm in wp._label_to_window_min.items() if wm == 600)
            wp.scale_radio.value = label_600
            assert wp.action_button.visible is False
            assert "not valid" in wp.scale_status.object.lower()
        finally:
            _close(app, db_path, npy_dir)


def test_missing_entry_has_a_compute_button():
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            row_10 = wp._ladder_rows[10]
            assert row_10["state"] == "missing"

            label_10 = next(opt for opt, wm in wp._label_to_window_min.items() if wm == 10)
            wp.scale_radio.value = label_10
            assert wp.action_button.visible is True
            assert "Compute" in wp.action_button.name
        finally:
            _close(app, db_path, npy_dir)


def test_selecting_a_scale_writes_window_min_into_the_param_form():
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            label_60 = next(opt for opt, wm in wp._label_to_window_min.items() if wm == 60)
            wp.scale_radio.value = label_60
            assert rp._param_widgets["window_min"].value == 60.0
            assert wp._selected_window_min == 60
        finally:
            _close(app, db_path, npy_dir)


def test_measure_count_shown_when_a_stage_is_unavailable_at_scale():
    """WINDOW_MATRIX_UI_PROMPT.md §3.3: an `available` scale whose slow-entropy
    or CNN stage can't run there must say "N/33 measures", never silently
    imply every measure is present."""
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            row_60 = wp._ladder_rows[60]
            # 60 min at fs=1 -> m=3600, well within slow_entropy/cnn limits,
            # so this scale should have ALL 33 measures available (a
            # negative-case check that the label logic doesn't over-report).
            avail, total = wp._measure_counts(row_60)
            assert avail == total == 33
        finally:
            _close(app, db_path, npy_dir)


# ── refresh(recording, span) ─────────────────────────────────────────────────

def test_refresh_with_no_recording_clears_the_ladder():
    with _IsolatedCalibration():
        cost.calibrate()
        app, db_path, npy_dir = _fresh_app_with_recording()
        try:
            rp = _select_window_matrix(app)
            wp = rp.window_matrix_panel
            assert wp.scale_radio.options  # populated first
            wp.refresh(None, None)
            assert wp.scale_radio.options == []
            assert wp.action_button.visible is False
        finally:
            _close(app, db_path, npy_dir)


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
