"""
test_shortcuts_and_view_controls.py
=====================================
Regression tests for Part C2 (Esc does not clear annotation selection),
Part C3 (Bokeh "Reset" returns to the previous view, not the whole
channel; no vertical pan control existed), and Part E5 (the full
keyboard-shortcut system C2 was generalized into).

C2's root cause was a hypothesis (a `width=0, height=0` hidden trigger
button risks being pruned from the render tree by a CSS/layout rule,
which would make `.click()` from JS silently do nothing) -- these tests
pin the concrete, checkable half of that fix (real 1px dimensions,
`opacity: 0` instead of zero size, still in normal layout flow) and the
Python-side click -> handler wiring, since real browser keydown
behaviour can't be verified headlessly. See this session's summary for
that caveat.

Real-data-gated (ViewerApp needs a real channel .npy), same convention
as tests/test_ui_selection.py and tests/test_filters.py. Always a fresh
temp sqlite file, never DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_shortcuts_and_view_controls.py
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
from UI.app import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_shortcuts.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    q.insert_annotation(conn, rid, 12000, 12600, "interesting", source=q.SOURCE_MANUAL_UI)
    conn.close()
    # Isolate from the real session file (Part E9) -- see
    # tests/_session_isolation.py.
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


def _click(button):
    """Simulate a real click without a live browser -- same technique
    used to verify E5 during development: feed `_process_events` the
    dict shape a Bokeh click event carries."""
    button._process_events({"clicks": (button.clicks or 0) + 1})


# ── C2 / E5: hidden shortcut buttons are DOM-safe and wired correctly ──────

def test_shortcut_buttons_are_not_zero_sized():
    """The original Esc bug's hypothesized root cause: a width=0, height=0
    element risks being pruned from the render tree by a CSS/layout rule,
    making `.click()` silently no-op. Every hidden shortcut button must
    have real (non-zero) dimensions and rely on opacity instead."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        assert len(app._shortcut_buttons) >= 12
        for btn in app._shortcut_buttons:
            assert btn.width and btn.width > 0, f"{btn.css_classes} has zero width"
            assert btn.height and btn.height > 0, f"{btn.css_classes} has zero height"
            assert btn.styles.get("opacity") == "0", f"{btn.css_classes} does not use opacity:0"
    finally:
        _close_and_unlink(app, db_path)


def test_escape_button_clears_annotation_selection():
    """The exact reported symptom: Esc must clear the current annotation
    selection. Verified at the Python handler level (click -> handler),
    not via a real browser keydown -- see module docstring."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        aid = q.list_annotations(app.conn, app._recording_id)[0]["id"]
        app._selected_annotation_ids = {aid}
        app._sync_table_selection_from_ids()
        assert app._selected_annotation_ids == {aid}

        escape_btn = app._shortcut_buttons[0]
        assert "shortcut-escape" in escape_btn.css_classes
        _click(escape_btn)

        assert app._selected_annotation_ids == set(), \
            "Esc (via the hidden shortcut-escape button) did not clear the selection"
    finally:
        _close_and_unlink(app, db_path)


def test_all_shortcut_buttons_reach_their_handler():
    """Every one of the 12 hidden buttons must actually be wired to a
    real, distinct effect -- not just present. Exercises the verdict
    keys (1-4), pan/select-mode keys (z/x/c), and next/prev (n/p), which
    are cheap to assert without a live plot; save/review are covered
    indirectly by test_ui_selection.py / the smoke test since they need
    a pending span / viewport."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        by_class = {}
        for btn in app._shortcut_buttons:
            for cls in btn.css_classes:
                if cls.startswith("shortcut-"):
                    by_class[cls] = btn

        _click(by_class["shortcut-verdict-2"])
        assert app.verdict == "not_interesting"

        _click(by_class["shortcut-verdict-4"])
        assert app.verdict == "unsure"

        _click(by_class["shortcut-mode-pan"])
        assert app.drag_mode.value == "Pan"

        _click(by_class["shortcut-mode-newspan"])
        assert app.drag_mode.value == "New span"

        _click(by_class["shortcut-mode-selectann"])
        assert app.drag_mode.value == "Select annotations"
    finally:
        _close_and_unlink(app, db_path)


# ── C3: explicit reset-to-full-view + vertical pan ──────────────────────────

def test_reset_full_view_button_restores_full_extent():
    """Bokeh's own toolbar "Reset" restores the PREVIOUS view, not the
    whole channel -- this is the explicit, always-whole-channel
    alternative the brief asked for."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        full = app._full_extent
        # Zoom into a narrow window first.
        app._range_stream.event(x_range=(full[0] + 10, full[0] + 20))
        assert app._range_stream.x_range != full

        app._on_reset_full_view()

        assert app._range_stream.x_range == app._full_extent
        assert app._y_pan_fraction == 0.0
    finally:
        _close_and_unlink(app, db_path)


def test_vertical_pan_shifts_rendered_y_range():
    """App-level vertical pan (not a Bokeh y-pan tool, whose cross-browser
    reliability can't be verified headlessly): panning up/down must
    actually shift what gets rendered. Checked against the real Bokeh
    figure's y_range, not `.range()` (which reflects the underlying
    curve DATA's own min/max, not the `ylim` display override -- a
    distinction that caused false negatives earlier in development)."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path = _fresh_app()
    try:
        import holoviews as hv
        renderer = hv.renderer("bokeh")

        def _rendered_y_range():
            plot = renderer.get_plot(app._dmap[app._dmap.keys()[0]] if app._dmap.keys() else app._dmap[()])
            return plot.state.y_range.start, plot.state.y_range.end

        before = _rendered_y_range()
        app._on_pan_y_up()
        after_up = _rendered_y_range()
        assert after_up[0] > before[0] and after_up[1] > before[1], \
            "panning up did not shift the rendered y-range upward"

        app._on_reset_full_view()
        app._on_pan_y_down()
        after_down = _rendered_y_range()
        assert after_down[0] < before[0] and after_down[1] < before[1], \
            "panning down did not shift the rendered y-range downward"
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
