"""
test_ui_responsiveness.py
=========================
The interaction-latency work of 2026-08-31.

Two mechanisms, both invisible in a screenshot and both easy to
regress by deleting one keyword:

**Throttled range sliders.** Panel fires `value` on every intermediate
position of a drag. Each one here re-filters the whole library and
rebuilds every card, so dragging a range slider across its track used to
queue dozens of full rebuilds and the UI went away for several seconds.
`value_throttled` fires once, when the handle is released.

**Loading feedback.** A rebuild that takes a second with no visual
acknowledgement reads as a broken control, and the usual response is to
click again, which queues another rebuild. Panel's `loading_indicator`
covers panes it knows are updating; the surfaces that swap
`Column.objects` wholesale have to say so themselves.

Neither is asserted by timing. The mechanism is what is pinned.
"""

import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from UI.workspaces.library.grid import LibraryGrid


def _empty_grid():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    return LibraryGrid(conn), conn, tf.name


def _callbacks_on(widget, param_name):
    """The functions registered as watchers of one parameter.

    Not `widget.param.watchers.keys()`: Panel registers its OWN internal
    watcher on essentially every parameter for browser sync, so "is
    anything watching `value`?" is always true and asserts nothing. What
    distinguishes a throttled control from an unthrottled one is *which*
    callback sits on which parameter, so that is what these tests check.
    """
    out = []
    for group in widget.param.watchers.get(param_name, {}).values():
        for watcher in group:
            out.append(watcher.fn)
    return out


# ── (a) range sliders fire on release, not on every drag frame ──────────

@pytest.mark.parametrize("slider_name", ["depth_range", "fall_duration_range"])
def test_range_sliders_filter_on_release_not_on_every_drag_frame(slider_name):
    """A `value` watcher here means every intermediate drag position
    triggers a full re-filter and a rebuild of every card. That is the
    difference between one rebuild per gesture and dozens."""
    grid, conn, path = _empty_grid()
    try:
        slider = getattr(grid, slider_name)
        handler = grid._on_filter_change
        assert handler in _callbacks_on(slider, "value_throttled"), (
            f"{slider_name} does not filter on release: _on_filter_change is "
            f"not watching value_throttled.")
        assert handler not in _callbacks_on(slider, "value"), (
            f"{slider_name} watches BOTH value and value_throttled — the "
            f"throttled watcher buys nothing while the unthrottled one still "
            f"fires on every drag frame.")
    finally:
        conn.close()
        os.unlink(path)


def test_the_other_filter_widgets_are_not_throttled():
    """Throttling a discrete control would make it feel broken.

    `value_throttled` exists for continuous drags. A `MultiSelect` change
    is a single discrete event and should take effect at once; moving it
    to the throttled parameter would be a latency "fix" that adds
    latency.
    """
    grid, conn, path = _empty_grid()
    try:
        handler = grid._on_filter_change
        for name in ("morphology", "purity", "spike_train", "recording", "channel"):
            widget = getattr(grid, name)
            assert handler in _callbacks_on(widget, "value"), (
                f"{name} no longer applies its filter at all")
    finally:
        conn.close()
        os.unlink(path)


# ── (b) the app asks Panel to show a spinner while it rebuilds ──────────

def test_loading_indicator_is_enabled_app_wide():
    """`UI.viewer.constants` is the one place the Panel extension is
    activated. Without `loading_indicator=True` Panel renders nothing at
    all while a pane recomputes, and a slow control is indistinguishable
    from a dead one — which is what makes a user click it again and queue
    a second rebuild."""
    import UI.viewer.constants  # noqa: F401  (activates the extension)
    assert pn.config.loading_indicator is True


def test_library_grid_clears_its_loading_flag_after_rebuilding():
    grid, conn, path = _empty_grid()
    try:
        grid._render_sections()
        assert grid._sections.loading is False, (
            "the grid stayed in the loading state after rebuilding — the flag "
            "is set but never cleared, so the surface is permanently greyed out")
    finally:
        conn.close()
        os.unlink(path)


def test_library_grid_clears_its_loading_flag_even_when_rebuilding_raises():
    """The failure mode a naive `loading = True ... loading = False` has.

    If a rebuild raises between the two assignments the grid is left
    greyed out forever with no error on screen, which looks exactly like
    a hang. The flag must be cleared in a `finally`.
    """
    grid, conn, path = _empty_grid()
    try:
        grid.groups = [("boom", ["missing-entry-id"])]
        with pytest.raises(Exception):
            grid._render_sections()
        assert grid._sections.loading is False, (
            "a failed rebuild left the grid permanently in the loading state")
    finally:
        conn.close()
        os.unlink(path)
