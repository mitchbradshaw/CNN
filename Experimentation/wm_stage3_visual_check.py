"""
wm_stage3_visual_check.py
===========================
One-off visual verification script for the window-matrix Stage 3 UI
(WINDOW_MATRIX_UI_PROMPT.md §8, this work order's §8). NOT a test — a
scratch driver that builds a real synthetic DB with real computed window
matrices, renders the actual Run-panel widgets (result_pane preview +
window_matrix_panel.ribbon_column) to static HTML, and screenshots them
with Playwright, per UI/README.md's "Visual verification during
development" pattern.

Never touches the real database or the real DATA/db/wm_calibration.json.

Run from the repo root:
    python Experimentation/wm_stage3_visual_check.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import panel as pn
import holoviews as hv
hv.extension("bokeh")

_TMPDIR = tempfile.mkdtemp(prefix="wm_stage3_visual_")
_SESSION_PATH = os.path.join(_TMPDIR, "session.json")

import Working.config as config
config.SESSION_STATE_PATH = _SESSION_PATH  # BEFORE importing UI.app, per UI/README.md

import Working.Preprocessing.window_matrix.cost as cost
cost.CALIBRATION_PATH = os.path.join(_TMPDIR, "wm_calibration.json")

from Working.database.schema import init_db
from Working.database import queries as q
from Working.recipes import make_recipe
from Working.execution import execute_recipe
import Adapters.preprocessing_window_matrix as wm_adapter
from Adapters.preprocessing_window_matrix import default_artifact_path
import UI.app as appmod

# `execute_recipe`'s persist hook writes through this module-level default
# (see its docstring: "Overridable so a test can redirect a real
# execute_recipe run's disk output without touching the real Results/
# tree") -- MUST be redirected before any `_compute()` call, or a run here
# writes a real .npz into the actual repo's Results/Preprocessing/window_matrix/.
wm_adapter.RESULTS_DIR = os.path.join(_TMPDIR, "wm_results")

from bokeh.io import save as bokeh_save
from bokeh.resources import INLINE
from playwright.sync_api import sync_playwright

OUT_DIR = os.path.join("Plots", "Preprocessing", "window_matrix")
os.makedirs(OUT_DIR, exist_ok=True)

N_SAMPLES = 50_000  # fs=1 -> ~13.9 hours; long enough for 1/10/60 min, too short for 600 min


def _build_data():
    db_path = os.path.join(_TMPDIR, "test.sqlite")
    npy_path = os.path.join(_TMPDIR, "CH0.npy")
    np.save(npy_path, np.random.default_rng(0).standard_normal(N_SAMPLES))
    conn = init_db(db_path)
    rid = q.insert_recording(conn, "wm_visual_check.mat", 0, 1.0, N_SAMPLES, 0, npy_path)
    conn.close()
    return db_path, rid


def _compute(db_path, recording_id, window_min, span, stages=("catch22", "fast_entropy")):
    conn = init_db(db_path)
    recording = q.get_recording_by_id(conn, recording_id)
    conn.close()
    resume_path = default_artifact_path(recording, window_min, 1.0)
    recipe = make_recipe(recording_id, [
        {"stage": "preprocessing", "algorithm": "window_matrix",
         "params": {
             "window_min": float(window_min), "step_frac": 1.0,
             "catch22": "catch22" in stages, "fast_entropy": "fast_entropy" in stages,
             "slow_entropy": False, "cnn": False, "rf": False,
             "timeout_s": 0.0, "resume_path": resume_path,
         }},
    ], span=list(span))
    execute_recipe(recipe, db_path=db_path)
    print(f"  computed WIN{window_min}min over span={span}")


def _screenshot(pane_column, out_path, viewport=(1100, 420)):
    html_path = out_path.replace(".png", ".html")
    doc_column = pn.Column(pane_column, sizing_mode="fixed", width=viewport[0])
    doc_column.save(html_path, resources=INLINE, embed=False)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        page.goto(f"file:///{os.path.abspath(html_path).replace(os.sep, '/')}")
        page.wait_for_timeout(400)
        page.screenshot(path=out_path)
        browser.close()
    print(f"  saved {out_path}")


def main():
    print("Building synthetic DB + channel...")
    db_path, recording_id = _build_data()

    print("Calibrating (isolated wm_calibration.json)...")
    cost.calibrate()

    print("Computing real window matrices...")
    # 10-min coverage over two DISJOINT spans, leaving a real gap [15000, 30000).
    _compute(db_path, recording_id, 10.0, (0, 15_000))
    _compute(db_path, recording_id, 10.0, (30_000, 50_000))
    # 60-min coverage over a region that does NOT include [2000, 8000) --
    # so that viewport shows this scale's pane as lane-background-only
    # (WM_MIN_WINDOWS=3 means this span must be wide enough for at least
    # 3 non-overlapping 3600-sample windows).
    _compute(db_path, recording_id, 60.0, (20_000, 50_000))

    app = appmod.ViewerApp(db_path=db_path)
    app.source_file, app.channel = "wm_visual_check.mat", 0
    app._load_recording()
    rp = app.run_panel
    rp.stage_select.value = "preprocessing"
    rp._on_stage_changed(None)
    rp.algorithm_select.value = "preprocessing.window_matrix"
    rp._on_algorithm_changed(None)
    wp = rp.window_matrix_panel

    layout = pn.Column(rp.result_pane, wp.ribbon_column)

    # ── Screenshot 1: full-channel zoom, disjoint 10-min spans -> visible gap.
    rp.span_mode.value = "Whole channel"
    rp._on_span_context_changed()
    print(f"ribbon panes (whole channel): {len(wp.ribbon_column.objects)} objects, visible={wp.ribbon_column.visible}")
    _screenshot(layout, os.path.join(OUT_DIR, "window_matrix_stage3_01_full_channel_gap.png"))

    # ── Screenshot 2: zoomed into ONE region fully covered at 10-min, and
    # fully OUTSIDE the 60-min coverage -- both the "band lines up with the
    # region" check and the "scale with no coverage -> lane background, not
    # blank" check in the same frame.
    app._stage_span(2_000, 8_000, annotation_id=None)
    rp.span_mode.value = "Selected span"
    rp._on_span_context_changed()
    print(f"ribbon panes (zoomed, covered+uncovered): {len(wp.ribbon_column.objects)} objects")
    _screenshot(layout, os.path.join(OUT_DIR, "window_matrix_stage3_02_zoomed_covered_and_empty.png"))

    # ── Screenshot 3: zoomed into the 60-min matrix's own covered region,
    # confirming that scale's band is drawn (not just the 10-min one).
    app._staged_spans.clear()
    app._stage_span(42_000, 48_000, annotation_id=None)
    rp.refresh_staged_list()
    rp.span_mode.value = "Selected span"
    rp._on_span_context_changed()
    print(f"ribbon panes (zoomed into 60-min coverage): {len(wp.ribbon_column.objects)} objects")
    _screenshot(layout, os.path.join(OUT_DIR, "window_matrix_stage3_03_zoomed_60min_covered.png"))

    app.conn.close()
    shutil.rmtree(_TMPDIR, ignore_errors=True)
    print("Done.")


if __name__ == "__main__":
    main()
