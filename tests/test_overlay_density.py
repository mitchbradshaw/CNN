"""
test_overlay_density.py
=========================
Tests for UI/plots.py's density-aware annotation ribbon pane content
(Part 4b, made viewport-reactive in Part B, moved into its own dedicated
pane in Part A, 2026-08): individual spans below `density_threshold` rows
*within the current viewport*, a bucketed ribbon above it — and
critically, that both branches return the exact same HoloViews element
type. A DynamicMap crashes (silently, from Panel's perspective — see
UI/plots.py's module docstring, bug 3) the moment its callback returns two
different element types across frames, which is exactly what would happen
if crossing the density threshold ever changed the returned type.

`build_annotation_ribbon` no longer takes a `y_range` -- ribbons are
separate panes with a FIXED (0, 1) y-range now (Part A), decoupled from
the main curve's axis entirely; the old "y-fraction never exceeded"/
"flush against the given y_range" tests are gone since there's no longer
a variable range to test against (see tests/test_ribbon_panes.py for the
Part A5 replacement: cross-pane x-sync, non-empty rendering, and bucket
alignment with the main plot).

Pure unit tests against synthetic rows — no real channel data or database
needed, since `build_annotation_ribbon` only touches plain dicts/rows.

Run from the project root:
    python tests/test_overlay_density.py
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
hv.extension("bokeh")

from UI.plots import build_annotation_ribbon
from Working.config import RIBBON_LANE_BACKGROUND_COLOR

FULL_VIEW = (0, 10_000_000)  # wide enough to contain every synthetic row below


def _row(rid, start, end, verdict="interesting", source="manual_ui"):
    return {"id": rid, "start_idx": start, "end_idx": end, "verdict": verdict, "source": source}


def _all_element_types(overlay):
    return {type(el) for el in overlay}


def _is_lane_background(el):
    return el.opts.get("style").kwargs.get("color") == RIBBON_LANE_BACKGROUND_COLOR


def _real_rect_count(overlay):
    """Total rows across every element EXCEPT the always-present lane
    background (Part B1) -- that background is a fixed +1 element/+1 row
    unrelated to how many actual annotations/buckets are present, so
    tests asserting an exact data-row count must not count it."""
    return sum(len(el.data) for el in overlay if not _is_lane_background(el))


# ── type consistency across the density threshold ───────────────────────────

def test_below_threshold_returns_overlay_of_rectangles():
    rows = [_row(i, i * 1000, i * 1000 + 500) for i in range(10)]
    overlay = build_annotation_ribbon(rows, 1.0, FULL_VIEW, density_threshold=300)
    assert isinstance(overlay, hv.Overlay)
    assert _all_element_types(overlay) == {hv.Rectangles}


def test_above_threshold_returns_overlay_of_rectangles():
    rows = [_row(i, i * 100, i * 100 + 50,
                  verdict=["interesting", "artifact", "not_interesting", "unsure"][i % 4])
            for i in range(500)]
    overlay = build_annotation_ribbon(rows, 1.0, FULL_VIEW, density_threshold=300)
    assert isinstance(overlay, hv.Overlay)
    assert _all_element_types(overlay) == {hv.Rectangles}


def test_empty_rows_returns_overlay_of_rectangles():
    overlay = build_annotation_ribbon([], 1.0, FULL_VIEW, density_threshold=300)
    assert isinstance(overlay, hv.Overlay)
    assert _all_element_types(overlay) == {hv.Rectangles}


def test_element_type_identical_on_both_sides_of_threshold():
    """The specific regression this exists to prevent: crossing the
    threshold must never change what TYPE gets returned, only how many
    rectangles and what they represent."""
    below = build_annotation_ribbon(
        [_row(i, i * 1000, i * 1000 + 500) for i in range(299)],
        1.0, FULL_VIEW, density_threshold=300,
    )
    above = build_annotation_ribbon(
        [_row(i, i * 1000, i * 1000 + 500) for i in range(301)],
        1.0, FULL_VIEW, density_threshold=300,
    )
    assert _all_element_types(below) == _all_element_types(above) == {hv.Rectangles}


def test_exactly_at_threshold_is_individual_not_ribbon():
    # density_threshold uses a strict > comparison -- exactly at the
    # threshold count still renders individually.
    rows = [_row(i, i * 10, i * 10 + 5) for i in range(300)]
    overlay = build_annotation_ribbon(rows, 1.0, FULL_VIEW, density_threshold=300)
    total_rects = _real_rect_count(overlay)
    assert total_rects == 300  # one rectangle per row, not bucketed


def test_rows_outside_viewport_are_excluded():
    rows = [_row(0, 0, 100), _row(1, 5_000_000, 5_000_100)]
    overlay = build_annotation_ribbon(rows, 1.0, (0, 1000), density_threshold=300)
    total_rects = _real_rect_count(overlay)
    assert total_rects == 1  # only the row overlapping [0, 1000)


# ── ribbon bucketing behavior ────────────────────────────────────────────────

def test_ribbon_bounds_rectangle_count_regardless_of_raw_row_count():
    # 5000 raw annotations must never produce anywhere near 5000 rectangles.
    rows = [_row(i, i * 10, i * 10 + 5,
                  verdict=["interesting", "artifact", "not_interesting", "unsure"][i % 4])
            for i in range(5000)]
    overlay = build_annotation_ribbon(rows, 1.0, FULL_VIEW, density_threshold=300)
    total_rects = _real_rect_count(overlay)
    # At most one rectangle per (verdict, bucket) pair -- 4 verdicts * 300 buckets.
    assert total_rects <= 4 * 300
    assert total_rects < 5000


def test_ribbon_preserves_verdict_color_grouping():
    rows = ([_row(i, i * 1000, i * 1000 + 500, verdict="artifact") for i in range(200)]
            + [_row(1000 + i, 500_000 + i * 1000, 500_000 + i * 1000 + 500, verdict="interesting")
               for i in range(200)])
    overlay = build_annotation_ribbon(rows, 1.0, FULL_VIEW, density_threshold=300)
    # Two verdicts present -> two separate Rectangles elements (one per
    # colour) + 1 always-present lane background (Part B1).
    assert len(overlay) == 3
    assert sum(1 for el in overlay if not _is_lane_background(el)) == 2


# ── fixed (0, 1) pane range (Part A, 2026-08) ───────────────────────────────

def test_all_rectangles_use_the_fixed_zero_to_one_range():
    """Ribbons are now separate panes with a FIXED (0, 1) y-range,
    completely decoupled from the main curve's axis (Part A) -- every
    rectangle, individual or bucketed, must use exactly this range
    regardless of annotation width, viewport, or count. (Compare to the
    pre-Part-A design, where this used to be a fraction of the curve's
    own y-range and could drift from what was actually on screen --
    see tests/test_ribbon_panes.py for the replacement coverage.)"""
    cases = [
        [_row(0, -1000, 1000, verdict="not_interesting", source="imported_10min")],  # wide single row
        [_row(i, i * 100, i * 100 + 50) for i in range(400)],  # bucketed ribbon
        [],  # empty
    ]
    for rows in cases:
        overlay = build_annotation_ribbon(rows, 1.0, (0, 100_000), density_threshold=300)
        for el in overlay:
            df = el.data
            if len(df):
                col_names = list(df.columns)
                y0_col, y1_col = col_names[1], col_names[3]
                assert (df[y0_col] == 0.0).all()
                assert (df[y1_col] == 1.0).all()


def test_viewport_reactive_bucketing_domain_changes_with_zoom():
    """Part B: the ribbon must bucket over the CURRENT VIEWPORT, not a
    fixed whole-channel/whole-annotation-set extent."""
    rows = [_row(i, i * 10_000, i * 10_000 + 50,
                  verdict=["interesting", "artifact", "not_interesting", "unsure"][i % 4])
            for i in range(1000)]  # spans 0 to ~10,000,000
    wide = build_annotation_ribbon(rows, 1.0, (0, 10_000_000), density_threshold=300)
    narrow = build_annotation_ribbon(rows, 1.0, (0, 100_000), density_threshold=300)
    wide_rects = sum(len(el.data) for el in wide)
    narrow_rects = sum(len(el.data) for el in narrow)
    # The narrow viewport only contains ~10 of the 1000 rows -- far fewer
    # occupied buckets than the wide (whole-set) viewport.
    assert narrow_rects < wide_rects


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
