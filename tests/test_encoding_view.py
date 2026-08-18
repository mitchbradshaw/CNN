"""
test_encoding_view.py
========================
Tests for Part 6 (2026-08): the Run algorithm tab's encoding inspection
view — running cSAX/pSAX populates the four panels, string/RLE display,
diagnostics, and alphabet legend; a non-encoding run keeps the section
hidden; preprocessing prepends a real recipe step; auto-preview recomputes
without creating `runs`/`configs` rows; and saving an encoding as a motif
seed captures the symbol string.

Real-data-gated (ViewerApp needs a real channel .npy), same convention as
tests/test_run_panel.py. Always a fresh temp sqlite file, never
DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_encoding_view.py
"""

import inspect
import os
import sys
import tempfile
import threading
import time

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
from Working.database import runs as R
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
    rid = q.insert_recording(conn, "UNITTEST_encoding_view.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
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


def _select_algorithm(rp, full_name):
    rp.stage_select.value = full_name.split(".")[0]
    rp.algorithm_select.value = full_name


def _run_and_wait(rp, timeout_s=15):
    rp._on_run()
    deadline = time.time() + timeout_s
    while rp._thread is not None and rp._thread.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    # `_on_run_finished` is scheduled via `doc.add_next_tick_callback`, which
    # only fires inside a live Bokeh event loop -- there is none here (no
    # `pn.state.curdoc`), so `_run_on_ui_thread` calls it directly and
    # synchronously the moment the worker thread finishes. A short grace
    # sleep covers the rare case the worker is still tearing down.
    time.sleep(0.05)


def _db_counts(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("configs", "runs", "detections", "encodings")}
    conn.close()
    return counts


# ── running an encoding algorithm populates the section ─────────────────

def test_running_csax_populates_encoding_section():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        rp.span_mode.value = "Current viewport"
        _select_algorithm(rp, "detection.sax_csax")
        rp._param_widgets["segment_mode"].value = "samples_per_symbol"
        rp._param_widgets["samples_per_symbol"].value = 20

        _run_and_wait(rp)

        assert rp.encoding_section.visible is True
        assert rp.enc_signal_pane.object is not None
        assert rp.enc_strip_pane.object is not None
        assert rp.enc_string_pane.value != ""
        assert "Length:" in rp.enc_string_info.object
        assert rp.enc_diagnostics_pane.object != ""
        assert "Realised alphabet size" in rp.enc_diagnostics_pane.object
        assert rp.enc_legend_pane.object != ""
    finally:
        _close_and_unlink(app, db_path)


def test_switching_to_non_encoding_algorithm_hides_stale_section_immediately():
    """The section must not linger from a PREVIOUS algorithm's run/preview
    once a non-encoding algorithm is selected -- even before that new
    algorithm has been run at all (the same "no stale state" rule as the
    pre-run preview, Part 5 A2)."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        _run_and_wait(rp)
        assert rp.encoding_section.visible is True

        _select_algorithm(rp, "preprocessing.bandpass")
        assert rp.encoding_section.visible is False, (
            "stale encoding section must hide the moment a non-encoding algorithm is selected"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_running_non_encoding_algorithm_hides_section():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "preprocessing.bandpass")

        _run_and_wait(rp)

        assert rp.encoding_section.visible is False
    finally:
        _close_and_unlink(app, db_path)


# ── preprocessing prepends a real recipe step ────────────────────────────

def test_preprocessing_prepends_a_real_recipe_step():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        rp.preprocess_select.value = "rolling_mean"
        rp.preprocess_window.value = 100.0

        _run_and_wait(rp)

        steps = rp._last_recipe["steps"]
        assert len(steps) == 2, steps
        assert steps[0]["stage"] == "preprocessing" and steps[0]["algorithm"] == "detrend"
        assert steps[0]["params"]["mode"] == "rolling_mean"
        assert steps[1]["algorithm"] == "sax_csax"
    finally:
        _close_and_unlink(app, db_path)


def test_no_preprocessing_means_single_step_recipe():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        assert rp.preprocess_select.value == "none"

        _run_and_wait(rp)

        assert len(rp._last_recipe["steps"]) == 1
    finally:
        _close_and_unlink(app, db_path)


# ── derive() readout populates without running ──────────────────────────

def test_derived_table_populates_without_running():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_psax")
        assert rp.derived_pane.object != ""
        assert "Symbols produced" in rp.derived_pane.object
        counts_before = _db_counts(db_path)
        assert counts_before["runs"] == 0, "derive() must never run/record anything"
    finally:
        _close_and_unlink(app, db_path)


def test_switching_to_algorithm_without_derive_clears_stale_table():
    """`_apply_recommended_defaults` only reaches `_refresh_derived()` when
    `spec.recommend` is set -- an algorithm with neither (e.g. bandpass)
    must still clear a PREVIOUS algorithm's stale derive() table, not
    leave it showing indefinitely."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_psax")
        assert "Symbols produced" in rp.derived_pane.object

        _select_algorithm(rp, "preprocessing.bandpass")
        assert rp.derived_pane.object == "", (
            f"stale derive() table must clear, got: {rp.derived_pane.object!r}"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── auto-preview: no DB writes ───────────────────────────────────────────

def test_auto_preview_shows_encoding_without_recording_a_run():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        rp.auto_preview_checkbox.value = True

        before = _db_counts(db_path)
        rp._run_auto_preview()  # bypass the debounce timer directly

        after = _db_counts(db_path)
        assert after == before, f"auto-preview must not write to the database: {before} -> {after}"
        assert rp.encoding_section.visible is True
        assert rp.enc_string_pane.value != ""
    finally:
        _close_and_unlink(app, db_path)


# ── motif seeding ─────────────────────────────────────────────────────────

def test_save_encoding_as_motif_seed():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        _run_and_wait(rp)
        assert rp._last_encoding is not None

        rp.motif_label.value = "test seed"
        rp._on_save_encoding_as_motif()

        assert "Saved motif" in rp.enc_seed_motif_status.object
        motifs = R.list_motifs(app.conn)
        assert len(motifs) == 1
        assert motifs[0]["sax_string"]
        assert motifs[0]["label"] == "test seed"
    finally:
        _close_and_unlink(app, db_path)


# ── reused run still shows a full encoding under the recompute threshold ──

def test_reused_run_recomputes_encoding_for_display():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        _select_algorithm(rp, "detection.sax_csax")
        rp._param_widgets["segment_mode"].value = "samples_per_symbol"
        rp._param_widgets["samples_per_symbol"].value = 20

        _run_and_wait(rp)
        assert "Done" in rp.status.object
        first_run_id = rp._last_run_result["run_id"]

        _run_and_wait(rp)  # identical params -> reused
        assert rp._last_run_result["reused"] is True
        assert rp._last_run_result["run_id"] == first_run_id
        assert rp.encoding_section.visible is True
        assert rp.enc_string_pane.value != ""
    finally:
        _close_and_unlink(app, db_path)


# ── runner ───────────────────────────────────────────────────────────────

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
