"""
test_window_matrix_coverage_ribbon.py
=======================================
Element-level tests for `UI.plots.build_window_matrix_ribbon`
(WINDOW_MATRIX_UI_PROMPT.md §4/§8.3) — no browser, no screenshots (that's
`Plots/window_matrix_stage3_*.png`, driven separately — see
WINDOW_MATRIX_STAGE3_SUMMARY.md). Asserts on the HoloViews object graph
directly: two disjoint stored matrices must produce two visibly separated
bands and not one continuous one, and a scale with no coverage must still
render a non-empty `Overlay` (the lane background), never a blank/None pane.

Run from the project root:
    python tests/test_window_matrix_coverage_ribbon.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import holoviews as hv

import UI.plots as plots

hv.extension("bokeh")


def _rectangles_in(overlay):
    """Every `hv.Rectangles` leaf in an Overlay, in draw order."""
    return [el for el in overlay if isinstance(el, hv.Rectangles)]


def test_no_coverage_still_renders_a_non_empty_overlay():
    """The lane background alone — never a blank pane, never `None`, never
    a bare (non-Overlay) element (module docstring's hard type-consistency
    requirement: a `DynamicMap`/pane that sometimes returns something other
    than an `Overlay` blanks with no visible error)."""
    result = plots.build_window_matrix_ribbon({}, fs=1.0, x_range_samples=(0, 10_000))
    assert isinstance(result, hv.Overlay)
    assert len(_rectangles_in(result)) >= 1  # the lane background, at minimum


def test_zero_width_viewport_still_renders_an_overlay():
    result = plots.build_window_matrix_ribbon(
        {"complete": [(0, 100)]}, fs=1.0, x_range_samples=(500, 500),
    )
    assert isinstance(result, hv.Overlay)


def test_two_disjoint_complete_runs_produce_two_separated_bands_not_one():
    """The failure mode this exists to catch: scattered coverage visually
    merging into apparent continuous coverage. Buckets strictly between the
    two covered spans must carry no 'fraction' data — i.e. only the lane
    background — the same way `build_reviewed_ribbon`'s gap tier is a real,
    checkable absence rather than an assumption."""
    coverage = {"complete": [(0, 1_000), (9_000, 10_000)]}
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    rects = _rectangles_in(result)
    # lane background + exactly one 'full' Rectangles element (both spans
    # are complete, so they collapse into a single vectorized element per
    # the "one Rectangles for all buckets" hard requirement).
    full_rects = [r for r in rects if "fraction" in r.vdims]
    assert len(full_rects) == 1
    data = full_rects[0].dframe()
    xs = sorted(data["x0"].tolist())
    # A visible gap in bucket x-starts between the two spans -- not one
    # contiguous run of buckets covering [0, 10000).
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    bucket_width = 10_000 / 300  # WM_COVERAGE_RIBBON_BUCKETS default
    assert max(gaps) > bucket_width * 2, "no visible gap between the two disjoint spans"
    assert min(xs) < 1_000
    assert max(xs) >= 9_000


def test_partial_and_complete_scales_render_in_different_colours():
    coverage = {"complete": [(0, 3_000)], "partial": [(6_000, 9_000)]}
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    rects = _rectangles_in(result)
    colours = {r.opts.get("plot").kwargs.get("color") if hasattr(r.opts.get("plot"), "kwargs")
               else None for r in rects}
    # At minimum, two distinct Rectangles elements exist for the two states
    # (plus the lane background) -- the actual colour values are asserted
    # against `Working.config`'s REVIEWED_FULL_COLOR/REVIEWED_PARTIAL_COLOR
    # constants directly below, which is the more meaningful check than
    # introspecting rendered Bokeh style dicts.
    assert len(rects) >= 3


def test_complete_and_partial_use_the_reviewed_ribbon_colours_verbatim():
    """§8.3: "the same distinction the reviewed ribbon already draws,
    reused rather than re-invented" -- checked by identity, not just by
    both being *some* two distinct colours."""
    coverage = {"complete": [(0, 3_000)], "partial": [(6_000, 9_000)]}
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    rects = _rectangles_in(result)
    fraction_rects = [r for r in rects if "fraction" in r.vdims]
    assert len(fraction_rects) == 2
    colours = {r.opts.get("style").kwargs["color"] for r in fraction_rects}
    assert colours == {plots.REVIEWED_FULL_COLOR, plots.REVIEWED_PARTIAL_COLOR}


def test_partial_only_coverage_is_never_promoted_to_full():
    coverage = {"partial": [(0, 10_000)]}
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    rects = _rectangles_in(result)
    fraction_rects = [r for r in rects if "fraction" in r.vdims]
    assert len(fraction_rects) == 1
    assert fraction_rects[0].opts.get("style").kwargs["color"] == plots.REVIEWED_PARTIAL_COLOR


def test_coverage_outside_the_viewport_is_clipped_out():
    coverage = {"complete": [(20_000, 30_000)]}  # entirely outside the viewport below
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    rects = _rectangles_in(result)
    fraction_rects = [r for r in rects if "fraction" in r.vdims]
    assert fraction_rects == []  # only the lane background remains


def test_every_leaf_element_has_axiswise_true():
    """UI/README.md: `axiswise=True` must be on every LEAF element, not
    just the enclosing Overlay -- this ribbon is instantiated once PER
    LADDER SCALE (up to 4 stacked panes sharing the same 'fraction' vdim in
    one session), exactly the multi-pane-same-vdim shape that caused a
    documented y-range-sharing bug elsewhere in this app. `axiswise`/
    `framewise` live in HoloViews' 'norm' options group, not 'plot'."""
    coverage = {"complete": [(0, 3_000)], "partial": [(6_000, 9_000)]}
    result = plots.build_window_matrix_ribbon(coverage, fs=1.0, x_range_samples=(0, 10_000))
    for el in result:
        norm = hv.Store.lookup_options("bokeh", el, "norm")
        assert norm.kwargs.get("axiswise") is True, el


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
