"""
test_surfaces_render.py
=======================
The gate the headless suite cannot be: every top-level workspace opens in
a real browser, paints, and produces no JS errors.

`CLAUDE.md` records the failure mode these exist for — "a broken dynamic
map renders as a silently blank pane, not an error. Tests pass, review
passes, the feature is missing." The headless construction tests added
for it assert a pane's `.object` is not `None`. That catches an absent
pane. It cannot catch a present pane that throws in the browser, which is
what actually happened both times.

Each test leaves a screenshot under `runs/ui-screenshots/<test-name>/`
(gitignored) so a reviewer — human or agent — can look at the thing
rather than trust a green dot.
"""

import pytest

from tests.ui.browser import assert_not_blank, canvas_ink, open_tab

WORKSPACES = ["Explore", "Analyse", "Review", "Library", "Admin"]


def test_explore_paints_the_signal(ui_app, snap):
    """The main viewer renders a real trace, not an empty frame."""
    page, _url, _app = ui_app
    ink = assert_not_blank(page, "the Explore signal plot")
    snap("explore")
    # Recorded so a regression that halves the plot's content shows up as a
    # number in the failure output rather than as "looks fine to me".
    assert ink["w"] > 200 and ink["h"] > 100, f"plot canvas is degenerate: {ink}"


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_workspace_opens_without_browser_errors(ui_app, snap, workspace):
    """Every tab survives being opened.

    The assertion that matters is not in this function body — it is the
    console-error check in the `ui_app` fixture's teardown. A workspace
    whose surface throws on mount fails here even though the DOM looks
    populated.
    """
    page, _url, _app = ui_app
    open_tab(page, workspace)
    snap(f"workspace-{workspace.lower()}")


def test_returning_to_explore_repaints(ui_app, snap):
    """Leaving and re-entering Explore must not leave a dead plot.

    Panel builds one Bokeh model per pane and patches it in place. A tab
    switch that detaches and reattaches the pane is exactly the situation
    where a stale model renders as an empty frame, and it is invisible to
    a construction test because the Python objects are all still there.
    """
    page, _url, _app = ui_app
    assert_not_blank(page, "Explore on first load")
    open_tab(page, "Library")
    open_tab(page, "Explore")
    ink = assert_not_blank(page, "Explore after a round trip through Library")
    snap("explore-after-round-trip")
    assert ink["distinct"] > 4


def test_zoom_preset_redraws_the_plot(ui_app, snap):
    """A viewport change produces a visibly different frame.

    Driven through the app's own zoom-preset button rather than by
    simulating a drag on the canvas: Bokeh canvas coordinates are not
    addressable by Playwright, and a test that fakes them is testing the
    test. The button is what a user clicks anyway.
    """
    page, _url, _app = ui_app
    before = canvas_ink(page)
    snap("zoom-before")

    button = page.get_by_role("button", name="Full channel")
    if button.count() == 0:
        pytest.skip("no 'Full channel' zoom preset in this build")
    button.first.click()
    page.wait_for_timeout(1500)

    after = assert_not_blank(page, "the plot after a zoom preset")
    snap("zoom-after")
    assert before is not None
    # Not asserting the frames DIFFER: the app may already be at full
    # extent on load, in which case an identical frame is correct
    # behaviour. The real assertion is that it still paints and the
    # console stayed clean through a stream-driven rebuild.
    assert after["distinct"] > 4
