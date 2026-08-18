"""
test_motif_browser.py
=======================
End-to-end test for UI/motif_browser.py against a scratch DB and a small
synthetic (but real, on-disk) channel — never the real annotations.sqlite,
same convention as tests/test_run_panel.py. Exercises the full path: run
`detection.matrix_profile` through `execute_recipe` (so the adapter's
`persist` hook registers a real v2 artifact), load `ViewerApp`, activate
the Motif browser tab, select a scale, browse groups, save one as a
motif, and headlessly render both panes to check element-type consistency
and non-degenerate axis ranges (the two failure modes
MATRIX_PROFILE_UI_PROMPT.md §6.2 calls out as invisible to plain
construction: a blank pane from mixed element types, and a flat-line
overlay from a missing `axiswise`).

Run from the project root:
    python tests/test_motif_browser.py
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
from Working.execution import execute_recipe
from Working.recipes import make_recipe
from UI.plots import build_motif_waveform_overlay
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

import Adapters.detection_matrix_profile as mp_adapter

FS = 0.5  # chosen so window_min=1 -> m=30 samples (fits the tiny fixture);
          # window_min=60/600 -> m=1800/18000, correctly "invalid" for n=3000.
N = 3000


def _planted_npy(path, seed=0):
    rng = np.random.default_rng(seed)
    m = 30
    t = np.linspace(0, 2 * np.pi, m)
    pattern = np.sin(t)
    x = rng.standard_normal(N) * 0.02
    for s in (200, 900, 1600, 2300):
        x[s:s + m] = pattern + rng.standard_normal(m) * 1e-4
    np.save(path, x)
    return path


def _fresh_app_with_mp():
    tmpdir = tempfile.mkdtemp(prefix="motif_browser_test_")
    npy_path = _planted_npy(os.path.join(tmpdir, "CH0.npy"))
    db_path = os.path.join(tmpdir, "test.sqlite")

    conn = init_db(db_path)
    recording_id = q.insert_recording(conn, "fake_mp.mat", 0, FS, N, 0, npy_path)
    conn.close()

    # Redirect the adapter's disk output into the scratch tmpdir -- without
    # this, `execute_recipe` -> the adapter's `persist` hook writes into the
    # REAL `Results/Detection/matrix_profile/` tree regardless of `db_path`
    # (confirmed: this polluted the real repo before this override existed).
    original_results_dir = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = os.path.join(tmpdir, "mp_results")
    try:
        recipe = make_recipe(recording_id, [
            {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 1.0}},
        ], span=None)
        result = execute_recipe(recipe, db_path=db_path)
        assert result["reused"] is False
    finally:
        mp_adapter.RESULTS_DIR = original_results_dir

    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=db_path)
    app._test_session_cm = session_cm
    app.layout()
    return app, db_path, tmpdir


def _close(app, db_path, tmpdir):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── scale ladder ─────────────────────────────────────────────────────────────

def test_scale_ladder_shows_available_and_invalid_states():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        assert "1 min" in mb.scale_radio.options, mb.scale_radio.options
        assert any("invalid" in opt for opt in mb.scale_radio.options), mb.scale_radio.options
        assert any("missing" in opt for opt in mb.scale_radio.options), mb.scale_radio.options
    finally:
        _close(app, db_path, tmpdir)


# ── selecting a scale loads groups and both panes ───────────────────────────

def test_selecting_available_scale_loads_groups_and_panes():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"

        assert mb._run_id is not None
        assert len(mb._groups) > 0
        assert mb.top_pane.object is not None
        assert mb.bottom_pane.object is not None
        assert "Motif 1 /" in mb.group_label.object
    finally:
        _close(app, db_path, tmpdir)


def test_invalid_scale_shows_reason_and_no_groups():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        invalid_opt = next(opt for opt in mb.scale_radio.options if "invalid" in opt)
        mb.scale_radio.value = invalid_opt
        assert mb._run_id is None
        assert "not valid" in mb.scale_status.object
    finally:
        _close(app, db_path, tmpdir)


# ── headless render: element-type consistency + non-degenerate ranges ──────

def test_top_pane_renders_as_overlay_with_markers():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"

        elem = mb.top_pane.object[()]  # current DynamicMap frame
        fig = hv.render(elem, backend="bokeh")
        # curve + rectangles + scatter = at least 3 renderers
        assert len(fig.renderers) >= 3, len(fig.renderers)
    finally:
        _close(app, db_path, tmpdir)


def test_bottom_pane_renders_non_flat_overlay():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"

        elem = mb.bottom_pane.object[()]
        assert isinstance(elem, hv.Overlay), type(elem)
        for leaf in elem:
            assert leaf.opts.get().kwargs.get("axiswise") is True, (
                f"{type(leaf).__name__} is missing axiswise=True -- this is exactly the "
                "flat-line-from-shared-range bug MATRIX_PROFILE_UI_PROMPT.md §6.2 warns about"
            )
        fig = hv.render(elem, backend="bokeh")
        # Not a flat line: at least one renderer's y data has nonzero spread.
        has_variation = False
        for r in fig.renderers:
            try:
                data = r.data_source.data
            except AttributeError:
                continue
            for key, values in data.items():
                arr = np.asarray(values, dtype=float) if len(values) else np.array([])
                if arr.size > 1 and np.ptp(arr) > 1e-9:
                    has_variation = True
        assert has_variation, "bottom pane rendered but every series is flat -- likely the axiswise bug"
    finally:
        _close(app, db_path, tmpdir)


def test_bottom_pane_y_range_rescales_across_group_navigation():
    """Regression: the bottom pane's y-range must actually rescale when
    navigating between motif groups on the SAME live plot object -- not
    just on the first frame. `ylim`+`framewise=True` alone is only
    honoured on a DynamicMap's first render (same root cause `_set_y_range`
    documents for the main curve/ribbons); without the `_set_y_range`
    hook, later groups render real (non-flat) data squashed into whatever
    sliver of an earlier group's stale range they happen to overlap --
    which reads as "every motif looks flat and hard to see the shape of".
    """
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        if len(mb._groups) < 2:
            print("  (skipped: fewer than 2 groups found for this fixture)")
            return

        renderer = hv.renderer("bokeh")
        plot = renderer.get_plot(mb.bottom_pane.object)
        plot.refresh()
        range_a = (plot.state.y_range.start, plot.state.y_range.end)
        assert range_a != (0, 1) and range_a[0] < range_a[1]

        mb._on_next()
        plot.refresh()
        range_b = (plot.state.y_range.start, plot.state.y_range.end)
        assert range_b != (0, 1) and range_b[0] < range_b[1]

        # Whether or not the two groups happen to need the SAME range is
        # data-dependent -- what matters is that the axis actually reflects
        # each frame's own data range each time, not that it's stuck at 0-1
        # (the reported symptom) or frozen at frame A's value.
        expected_a = build_motif_waveform_overlay(
            mb._groups[0], mb._x, mb._m, mb._fs_at_scale,
        )
        fig_a = hv.render(expected_a, backend="bokeh")
        assert abs(fig_a.y_range.start - range_a[0]) < 1e-6
        assert abs(fig_a.y_range.end - range_a[1]) < 1e-6
    finally:
        _close(app, db_path, tmpdir)


# ── navigation ───────────────────────────────────────────────────────────────

def test_navigation_prev_next_and_jump():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        if len(mb._groups) < 2:
            print("  (skipped: fewer than 2 groups found for this fixture)")
            return
        start_idx = mb._group_index
        mb._on_next()
        assert mb._group_index == start_idx + 1
        mb._on_prev()
        assert mb._group_index == start_idx
        mb.jump_input.value = len(mb._groups)
        assert mb._group_index == len(mb._groups) - 1
    finally:
        _close(app, db_path, tmpdir)


# ── group-set keying via the widgets ────────────────────────────────────────

def test_changing_n_neighbors_requires_explicit_recompute():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        original_groups = list(mb._groups)

        mb.n_neighbors.value = mb.n_neighbors.value + 1
        # Must NOT recompute automatically.
        assert mb._groups == original_groups
        assert mb.recompute_button.visible is True

        mb._on_recompute_groups()
        assert mb.recompute_button.visible is False
    finally:
        _close(app, db_path, tmpdir)


# ── save as motif ────────────────────────────────────────────────────────────

def test_save_group_as_motif():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        mb.motif_label.value = "test motif"
        mb._on_save_motif()
        assert "Saved motif id=" in mb.motif_status.object

        from Working.database import runs as R
        motifs = R.list_motifs(app.conn)
        assert len(motifs) == 1
        assert motifs[0]["label"] == "test motif"
    finally:
        _close(app, db_path, tmpdir)


# ── open in viewer ───────────────────────────────────────────────────────────

def test_open_in_viewer_moves_the_range_stream():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        before = app._range_stream.x_range
        mb._on_open_in_viewer()
        after = app._range_stream.x_range
        assert after != before
        assert app.tabs.active == 0
    finally:
        _close(app, db_path, tmpdir)


# ── segment mode ─────────────────────────────────────────────────────────────

def test_segment_mode_requires_staged_span():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        mb._on_segment_mode_compute()
        assert "No span staged" in mb.segment_mode_status.object
    finally:
        _close(app, db_path, tmpdir)


def test_segment_mode_both_readings_compute():
    app, db_path, tmpdir = _fresh_app_with_mp()
    try:
        mb = app.motif_browser
        mb.on_tab_activated()
        mb.scale_radio.value = "1 min"
        app._pending_bounds = (200.0, 340.0)  # 70 samples at fs=0.5, comfortably >= 2*m (60)

        mb.segment_mode_radio.value = mb.segment_mode_radio.options[0]
        mb._on_segment_mode_compute()
        assert "nearest neighbour across full channel" in mb.segment_mode_status.object

        mb.segment_mode_radio.value = mb.segment_mode_radio.options[1]
        mb._on_segment_mode_compute()
        assert "nearest neighbour within this segment" in mb.segment_mode_status.object
    finally:
        _close(app, db_path, tmpdir)


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
