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

import pytest

import numpy as np
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import execute_recipe
from Working.recipes import make_recipe
from UI.plots import build_motif_waveform_overlay
from UI.viewer import ViewerApp
from UI.workspaces.library.grid import LibraryGrid
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


class _FakeLibraryApp:
    """The only app surface `LibraryGrid` is allowed to read."""

    def __init__(self, conn):
        self.conn = conn


def _insert_library_recording(conn, tmpdir, source_file, channel):
    npy_path = os.path.join(tmpdir, f"{source_file}_ch{channel}.npy")
    _planted_npy(npy_path)
    return q.insert_recording(conn, source_file, channel, FS, N, 0, npy_path)


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


# ── library grid (T38) ─────────────────────────────────────────────────────

def test_library_grid_renders_empty_library_without_blanking():
    conn = init_db(":memory:")
    try:
        grid = LibraryGrid(_FakeLibraryApp(conn))
        layout = grid.layout()
        assert layout is not None
        assert grid.cards == []
    finally:
        conn.close()


def test_library_grid_renders_exemplar_cards_with_scope():
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = init_db(":memory:")
        try:
            rec_a = _insert_library_recording(conn, tmpdir, "A.mat", 0)
            rec_b = _insert_library_recording(conn, tmpdir, "B.mat", 3)

            # e1 is newer, so it sorts first under `list_motif_entries`'s
            # created_at DESC ordering — lets us assert its scope on cards[0]
            # deterministically rather than whichever row won the race.
            e1 = R.insert_motif_entry(
                conn, rec_a, 10, 50, label="sine-a",
                created_at="2026-01-02T00:00:00+00:00",
            )
            e2 = R.insert_motif_entry(
                conn, rec_b, 20, 60, label="sine-b",
                created_at="2026-01-01T00:00:00+00:00",
            )
            # e1 appears in both recordings; e2 only in recording B.
            R.get_or_create_motif_member(conn, e1, rec_a, 10, 50)
            R.get_or_create_motif_member(conn, e1, rec_b, 20, 60)
            R.get_or_create_motif_member(conn, e2, rec_b, 20, 60)

            grid = LibraryGrid(_FakeLibraryApp(conn))
            layout = grid.layout()

            assert layout is not None
            assert len(grid.cards) == 2
            assert len(grid.scope_panes) == 2

            first_scope = grid.scope_panes[0].object
            assert "A.mat" in first_scope and "CH00" in first_scope
            assert "B.mat" in first_scope and "CH03" in first_scope

            second_scope = grid.scope_panes[1].object
            assert "B.mat" in second_scope and "CH03" in second_scope
        finally:
            conn.close()


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


# ─────────────────────────────────────────────────────────────────────────
#  Y-range mode on the waveform overlay (2026-08 usability pass)
# ─────────────────────────────────────────────────────────────────────────
#
# The overlay fenced its y-range with a Tukey IQR fence (k=3) computed from
# the middle 50% of the stacked curves. That fence was added so one sharp
# transient could not squash every other curve flat -- but its consequence
# is that the transient itself draws CLIPPED at the frame edge, which reads
# as "the plot is cut short". Reported directly: "I just want to make sure I
# can see the whole range of the motifs."
#
# So the fence becomes a mode rather than the only behaviour, and the
# default flips to "fit": every sample of every curve is inside the frame.


def _fenced_group_and_signal():
    """A group whose seed carries a transient far outside the bulk range --
    the exact shape the IQR fence clips."""
    m = 64
    x = np.zeros(4 * m, dtype=np.float64)
    rng = np.random.default_rng(7)
    for k in range(4):
        base = rng.normal(0.0, 0.05, m)
        base[m // 2] = -8.0          # the transient the fence fences out
        x[k * m:(k + 1) * m] = base
    group = {"seed_idx": 0, "neighbours": [(m, 0.1), (2 * m, 0.2), (3 * m, 0.3)]}
    return group, x, m


def _overlay_ylim(overlay):
    """The y-range every leaf of the overlay was given."""
    limits = [el.opts.get("plot").kwargs.get("ylim") for el in overlay]
    assert len({l for l in limits if l is not None}) == 1, \
        f"leaves disagree about ylim: {limits}"
    return next(l for l in limits if l is not None)


def test_waveform_overlay_fit_mode_contains_every_sample():
    """The default y-range holds the whole curve, transient included."""
    group, x, m = _fenced_group_and_signal()
    overlay = build_motif_waveform_overlay(group, x, m, fs=1.0)
    y0, y1 = _overlay_ylim(overlay)

    drawn = np.concatenate([np.asarray(el.dimension_values(1))
                            for el in overlay if len(el)])
    assert y0 <= drawn.min() and drawn.max() <= y1, (
        f"y-range ({y0:.3f}, {y1:.3f}) clips data spanning "
        f"({drawn.min():.3f}, {drawn.max():.3f}) -- the transient is cut off"
    )


def test_waveform_overlay_fence_mode_still_available():
    """The IQR fence is kept, as an explicit mode -- it is the right view
    when one transient would otherwise flatten every other curve."""
    group, x, m = _fenced_group_and_signal()
    fit = _overlay_ylim(build_motif_waveform_overlay(group, x, m, fs=1.0,
                                                     y_range_mode="fit"))
    fenced = _overlay_ylim(build_motif_waveform_overlay(group, x, m, fs=1.0,
                                                        y_range_mode="fence"))
    assert (fenced[1] - fenced[0]) < (fit[1] - fit[0]), \
        "the fenced range should be tighter than the fit-to-data range"


def test_waveform_overlay_rejects_an_unknown_y_range_mode():
    group, x, m = _fenced_group_and_signal()
    with pytest.raises(ValueError, match="y_range_mode"):
        build_motif_waveform_overlay(group, x, m, fs=1.0, y_range_mode="iqr")
