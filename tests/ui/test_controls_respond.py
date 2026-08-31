"""
test_controls_respond.py
========================
The controls a user actually touches, exercised through the browser.

Scope is deliberately narrow: the display-only view transforms and the
cross-channel peek. Both drive a plot rebuild through a widget watcher,
which is the code path where a blank pane appears, and both are cheap to
assert on. Adding a case here should mean "this control rebuilt a plot
and the console stayed clean", not "this control produced exactly these
pixels" — the latter is a screenshot's job, and screenshots are for
humans to look at, not for CI to diff.
"""

import pytest

from tests.ui.browser import assert_not_blank, checkbox


def _checkbox(page, label):
    """`browser.checkbox` plus an explicit skip, so a renamed control
    reads as "that control is gone" rather than as a click timeout."""
    box = checkbox(page, label)
    if box.count() == 0:
        pytest.skip(f"no checkbox labelled {label!r} in this build")
    return box.first


def test_dc_offset_toggle_rebuilds_the_plot(ui_app, snap):
    """Part E3's display-only DC-offset transform.

    It rebuilds the `DynamicMap` from scratch (the transform is baked in
    at construction, not streamed), so a mistake here is precisely the
    "plot object replaced, new one never renders" case.
    """
    page, _url, _app = ui_app
    assert_not_blank(page, "the plot before toggling DC offset")
    _checkbox(page, "Remove DC offset (display only)").click()
    page.wait_for_timeout(1500)
    assert_not_blank(page, "the plot after toggling DC offset")
    snap("dc-offset-on")


def test_y_autoscale_toggle_rebuilds_the_plot(ui_app, snap):
    page, _url, _app = ui_app
    _checkbox(page, "Y-autoscale to viewport").click()
    page.wait_for_timeout(1500)
    assert_not_blank(page, "the plot with y-autoscale off")
    snap("y-autoscale-off")


def test_cross_channel_peek_renders_a_second_trace(ui_app, snap):
    """Selecting a comparison channel adds a second painted canvas.

    The scratch database is seeded with two real channels precisely so
    this dropdown has something to select; with one channel the control
    exists but exercises nothing.
    """
    page, _url, _app = ui_app
    from tests.ui.browser import deep_count

    before = deep_count(page, "canvas")
    select = page.get_by_role("combobox", name="Compare with channel")
    if select.count() == 0:
        pytest.skip("no cross-channel peek select in this build")
    options = select.first.locator("option")
    labels = [options.nth(i).inner_text().strip() for i in range(options.count())]
    real = [label for label in labels if label and label != "(none)"]
    if not real:
        pytest.skip("cross-channel peek has no comparison channel to select")

    select.first.select_option(label=real[0])
    page.wait_for_timeout(2000)
    snap("cross-channel-peek")
    after = deep_count(page, "canvas")
    assert after > before, (
        f"selecting comparison channel {real[0]!r} did not add a canvas "
        f"({before} before, {after} after) — the peek pane is empty"
    )
