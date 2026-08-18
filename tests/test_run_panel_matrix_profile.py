"""
test_run_panel_matrix_profile.py
==================================
Regression test for a real crash: running `detection.matrix_profile` from
the Run algorithm tab raised `KeyError: 'details'` inside
`RunPanel._gather_encoding_display_data`, which assumes every
`output_kind='encoding'` adapter is SAX-shaped (a `details` dict + `x`/`t`
+ a discrete symbol array in `result.meta`/`result`). Matrix profile is
also `output_kind='encoding'` but is a continuous distance profile with
none of that — it needs its own path (`_gather_generic_encoding_display_data`),
routed via the same `algorithm_short.startswith("sax_")` convention the
SAX persistence code already uses.

Drives `RunPanel._gather_display_data` directly (synchronously) with a
real `execute_recipe` result — this is exactly what `RunPanel._on_run`'s
background thread does, just without the thread, since threading and a
live Bokeh document aren't needed to exercise this code path.

Real-data-gated (needs a real channel .npy), same convention as
tests/test_run_panel.py.

Run from the project root:
    python tests/test_run_panel_matrix_profile.py
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
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from Working.execution import execute_recipe
from Working.recipes import make_recipe
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

import Adapters.detection_matrix_profile as mp_adapter

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app_and_recipe(window_min=10.0, span=(100_000, 110_000)):
    tmpdir = tempfile.mkdtemp(prefix="rp_mp_test_")
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    recording_id = q.insert_recording(conn, "UNITTEST_rp_mp.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()

    original_results_dir = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = os.path.join(tmpdir, "mp_results")

    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()

    recipe = make_recipe(recording_id, [
        {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": window_min}},
    ], span=span)
    return app, tf.name, tmpdir, original_results_dir, recipe


def _close(app, db_path, tmpdir, original_results_dir):
    mp_adapter.RESULTS_DIR = original_results_dir
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_gather_display_data_does_not_raise_for_fresh_run():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, tmpdir, original_results_dir, recipe = _fresh_app_and_recipe()
    try:
        out = execute_recipe(recipe, db_path=db_path)
        assert out["reused"] is False
        conn_w = init_db(db_path)
        try:
            display_data = app.run_panel._gather_display_data(conn_w, out, recipe)
        finally:
            conn_w.close()

        assert display_data["kind"] == "generic_encoding"
        assert display_data["reused"] is False
        assert display_data["artifact_path"] is not None
        assert os.path.isfile(display_data["artifact_path"])
        summary = display_data["summary"]
        assert summary is not None
        assert summary["n"] > 0
        assert summary["m"] == 600  # window_min=10 at fs=1
        assert summary["min"] is not None and summary["max"] is not None
    finally:
        _close(app, db_path, tmpdir, original_results_dir)


def test_gather_display_data_reused_run_does_not_recompute():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, tmpdir, original_results_dir, recipe = _fresh_app_and_recipe()
    try:
        execute_recipe(recipe, db_path=db_path)
        out2 = execute_recipe(recipe, db_path=db_path)
        assert out2["reused"] is True
        assert out2["result"] is None  # nothing recomputed

        conn_w = init_db(db_path)
        try:
            display_data = app.run_panel._gather_display_data(conn_w, out2, recipe)
        finally:
            conn_w.close()

        assert display_data["kind"] == "generic_encoding"
        assert display_data["reused"] is True
        # Still resolves a real artifact/summary from the FIRST run's
        # registered artifact, without recomputing anything.
        assert display_data["artifact_path"] is not None
        assert display_data["summary"] is not None
    finally:
        _close(app, db_path, tmpdir, original_results_dir)


def test_on_run_finished_does_not_raise(monkeypatch=None):
    """The full UI-thread path: _on_run_finished must handle the
    'generic_encoding' kind without touching the SAX-only encoding_section
    rendering."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, tmpdir, original_results_dir, recipe = _fresh_app_and_recipe()
    try:
        out = execute_recipe(recipe, db_path=db_path)
        conn_w = init_db(db_path)
        try:
            display_data = app.run_panel._gather_display_data(conn_w, out, recipe)
        finally:
            conn_w.close()

        rp = app.run_panel
        rp._last_recipe = recipe
        rp._on_run_finished(out, display_data)  # must not raise
        assert rp.encoding_section.visible is False  # not SAX-shaped -- stays hidden
        assert "Motif browser" in rp.status.object
    finally:
        _close(app, db_path, tmpdir, original_results_dir)


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
