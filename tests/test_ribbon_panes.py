"""
test_ribbon_panes.py
======================
Tests for Part A (2026-08): the reviewed-coverage and annotation-density
ribbons moved OUT of the main plot (where they were overlays positioned
as a fraction of the curve's own y-range) into their own separate, thin
Bokeh panes stacked above/below it, linked only by x-range. This replaces
tests/test_ribbon_y_range_tracking.py, which tested the retired "pin to
the curve's visible y-range" mechanism.

Root cause notes (see UI/README.md for the full writeup): the reported
symptom was a ribbon going missing entirely at some zoom levels. The
user's hypothesis -- a circular dependency between ribbon position and
the curve's y-auto-ranging -- was tested directly (rendered y-range with
and without the ribbon renderers present) and REFUTED: `apply_ranges=
False` was already correctly excluding every overlay from the curve's
range computation. The exact vanishing was not reproduced by direct
inspection either. Regardless of the inconclusive root cause, sharing an
axis with the trace at all was the wrong design -- a ribbon's position
should never depend on what the signal happens to be doing -- so the
fix is architectural: fixed (0, 1) y-range panes with no coupling to the
curve's axis, which makes this whole class of bug structurally
impossible rather than merely rare.

Real-data-gated (ViewerApp needs a real channel .npy), same convention
as tests/test_ui_selection.py. Always a fresh temp sqlite file, never
DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_ribbon_panes.py
"""

import inspect
import os
import sys
import tempfile

import pytest

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
from Working.config import RIBBON_FRAME_MIN_BORDER_LEFT, RIBBON_PANE_HEIGHT
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600
CENTER = 12_300  # inside the channel, near a real annotation


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_ribbon_panes.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    # A handful of real-shaped annotations/reviewed spans near CENTER.
    for i in range(5):
        s = CENTER + i * 100
        q.insert_annotation(conn, rid, s, s + 50, "interesting", source=q.SOURCE_MANUAL_UI)
        q.insert_reviewed_span(conn, rid, s, s + 50, source=q.SOURCE_MANUAL_UI)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _rendered_x_range(plot):
    plot.refresh()
    return (plot.state.x_range.start, plot.state.x_range.end)


def _rendered_renderer_row_count(plot):
    total = 0
    for r in plot.state.renderers:
        cds = getattr(r, "data_source", None)
        if cds is not None:
            total += len(cds.data.get("left", cds.data.get("x", [])))
    return total


# ── (a) x-ranges stay synchronised across all three panes through pan/zoom ──

def test_x_ranges_stay_synchronised_across_pan_and_zoom():
    """The invariant that broke TWICE (2026-08): once when the ribbons
    were still overlays coupled to the curve's y-axis, and again after
    the Part A restructure, when `xlim`+`framewise=True` alone turned out
    to only be honoured by HoloViews on a DynamicMap's FIRST rendered
    frame -- every SUBSEQUENT stream-triggered refresh left each ribbon
    pane's axis pinned to whatever it was at construction, even though
    the bucket DATA underneath was correctly recomputed for the new
    viewport (see `UI.plots._set_x_range`'s docstring for the full
    mechanism).

    The plot objects are created ONCE, outside the loop, and refreshed
    repeatedly -- exactly how the real live app works (Panel builds one
    Bokeh model per pane and patches it in place on every stream event;
    it never reconstructs the plot from scratch on every pan/zoom). An
    earlier version of this test fetched a FRESH `get_plot()` after each
    `.event()`, which only ever exercises a plot's "first frame" and
    silently missed this exact bug -- fetching fresh every time is not
    representative of the live app and must not be reintroduced here.
    """
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        p_curve = renderer.get_plot(app.plot_pane.object)
        p_rev = renderer.get_plot(app.reviewed_ribbon_pane.object)
        p_ann = renderer.get_plot(app.annotation_ribbon_pane.object)

        # Simulated ZOOM sequence: full extent, then progressively narrower.
        for width in [None, 21600, 3600, 585, 60]:
            x_range = app._full_extent if width is None else (
                max(0, CENTER - width / 2), CENTER + width / 2
            )
            app._range_stream.event(x_range=x_range)
            app._refresh_view()
            curve_x = _rendered_x_range(p_curve)
            rev_x = _rendered_x_range(p_rev)
            ann_x = _rendered_x_range(p_ann)
            assert abs(curve_x[0] - rev_x[0]) < 1e-6 and abs(curve_x[1] - rev_x[1]) < 1e-6, (
                f"zoom width={width}: curve_x={curve_x} reviewed_x={rev_x} (SAME persistent plot object)"
            )
            assert abs(curve_x[0] - ann_x[0]) < 1e-6 and abs(curve_x[1] - ann_x[1]) < 1e-6, (
                f"zoom width={width}: curve_x={curve_x} annotation_x={ann_x} (SAME persistent plot object)"
            )

        # Simulated PAN sequence: same width, sliding center -- the exact
        # user-reported scenario (288-298h, then 292.05-292.68h).
        for center in [CENTER, CENTER + 200, CENTER - 150, CENTER + 50]:
            x_range = (center - 5, center + 5)
            app._range_stream.event(x_range=x_range)
            app._refresh_view()
            curve_x = _rendered_x_range(p_curve)
            rev_x = _rendered_x_range(p_rev)
            ann_x = _rendered_x_range(p_ann)
            assert curve_x == rev_x == ann_x, (
                f"pan center={center}: curve_x={curve_x} reviewed_x={rev_x} annotation_x={ann_x}"
            )
    finally:
        _close_and_unlink(app, db_path)


# ── (b) each ribbon pane renders non-empty whenever there is data in view ───

def test_ribbon_panes_render_non_empty_when_data_in_view():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        # A 1000s window centered on the 5 fabricated annotations/spans.
        x_range = (CENTER - 200, CENTER + 700)
        app._range_stream.event(x_range=x_range)
        app._refresh_view()
        p_rev = renderer.get_plot(app.reviewed_ribbon_pane.object)
        p_ann = renderer.get_plot(app.annotation_ribbon_pane.object)
        p_rev.refresh()
        p_ann.refresh()
        assert _rendered_renderer_row_count(p_rev) > 0, "reviewed ribbon rendered nothing with data in view"
        assert _rendered_renderer_row_count(p_ann) > 0, "annotation ribbon rendered nothing with data in view"
    finally:
        _close_and_unlink(app, db_path)


def test_ribbon_panes_render_something_even_with_no_data_in_view():
    """The lane background (Part B1) means a pane is never actually
    empty -- a genuinely data-free stretch must still show the neutral
    tint, not zero renderers, so "no data" and "broken pane" can never
    look identical."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        # Far from every fabricated annotation/reviewed span.
        x_range = (CENTER + 100_000, CENTER + 100_060)
        app._range_stream.event(x_range=x_range)
        app._refresh_view()
        p_rev = renderer.get_plot(app.reviewed_ribbon_pane.object)
        p_ann = renderer.get_plot(app.annotation_ribbon_pane.object)
        p_rev.refresh()
        p_ann.refresh()
        assert _rendered_renderer_row_count(p_rev) > 0, "reviewed pane has no renderers at all (not even background)"
        assert _rendered_renderer_row_count(p_ann) > 0, "annotation pane has no renderers at all (not even background)"
    finally:
        _close_and_unlink(app, db_path)


# ── (c) bucket boundaries align with the main plot's x-coordinates ─────────

def test_ribbon_bucket_coordinates_fall_within_curve_x_range():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        x_range = (CENTER - 200, CENTER + 700)
        app._range_stream.event(x_range=x_range)
        app._refresh_view()
        p_curve = renderer.get_plot(app.plot_pane.object)
        p_ann = renderer.get_plot(app.annotation_ribbon_pane.object)
        p_curve.refresh()
        p_ann.refresh()
        curve_x0, curve_x1 = p_curve.state.x_range.start, p_curve.state.x_range.end
        found_bucket = False
        for r in p_ann.state.renderers:
            cds = getattr(r, "data_source", None)
            if cds is None:
                continue
            for left, right in zip(cds.data.get("left", []), cds.data.get("right", [])):
                found_bucket = True
                assert left >= curve_x0 - 1e-6, f"bucket left={left} is before curve x_range start={curve_x0}"
                assert right <= curve_x1 + 1e-6, f"bucket right={right} is past curve x_range end={curve_x1}"
        assert found_bucket, "no annotation-ribbon bucket rectangles found to check"
    finally:
        _close_and_unlink(app, db_path)


# ── pane styling: fixed height, hidden axes, no toolbar, matching border ────

def test_ribbon_panes_have_fixed_height_and_hidden_axes_and_no_toolbar():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        for pane_obj in (app.reviewed_ribbon_pane.object, app.annotation_ribbon_pane.object):
            plot = renderer.get_plot(pane_obj)
            fig = plot.state
            assert fig.height == RIBBON_PANE_HEIGHT
            assert fig.toolbar_location is None
            assert fig.xaxis[0].visible is False
            assert fig.yaxis[0].visible is False
    finally:
        _close_and_unlink(app, db_path)


def test_ribbon_panes_share_left_border_with_the_curve():
    """The main risk with separate panes (Part A3): a ribbon pane's frame
    starting at a different pixel x-position than the curve's, which
    would visibly offset every bucket from the region it annotates."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        renderer = hv.renderer("bokeh")
        p_curve = renderer.get_plot(app.plot_pane.object)
        p_rev = renderer.get_plot(app.reviewed_ribbon_pane.object)
        p_ann = renderer.get_plot(app.annotation_ribbon_pane.object)
        assert p_curve.state.min_border_left == RIBBON_FRAME_MIN_BORDER_LEFT
        assert p_rev.state.min_border_left == RIBBON_FRAME_MIN_BORDER_LEFT
        assert p_ann.state.min_border_left == RIBBON_FRAME_MIN_BORDER_LEFT
    finally:
        _close_and_unlink(app, db_path)


# ── toggling a ribbon off collapses its pane (Part A4) ──────────────────────

def test_toggling_annotations_off_collapses_the_annotation_pane():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert app.annotation_ribbon_pane.visible is True
        app.show_annotations_toggle.value = False
        assert app.annotation_ribbon_pane.visible is False
        app.show_annotations_toggle.value = True
        assert app.annotation_ribbon_pane.visible is True
    finally:
        _close_and_unlink(app, db_path)


def test_toggling_reviewed_ribbon_off_collapses_its_pane():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert app.reviewed_ribbon_pane.visible is True
        app.show_reviewed_ribbon_toggle.value = False
        assert app.reviewed_ribbon_pane.visible is False
        app.show_reviewed_ribbon_toggle.value = True
        assert app.reviewed_ribbon_pane.visible is True
    finally:
        _close_and_unlink(app, db_path)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except pytest.skip.Exception as e:
            # `Skipped` derives from BaseException, not Exception, so it would
            # sail past the handler below and abort the whole standalone run on
            # the first guarded test. Absent data is a skip here too, not a pass.
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        # Never fold skips into the pass count: "all green" and "the data
        # was not there" are the two readings this file exists to keep
        # apart.
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
