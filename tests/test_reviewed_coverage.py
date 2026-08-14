"""
test_reviewed_coverage.py
============================
Tests for UI/plots.py's reviewed-coverage ribbon (Part 4c): type
consistency across the empty/sparse/full-coverage branches, the core
"sparse islands must not render as full coverage at coarse zoom" guarantee
(the whole reason this ribbon exists — a naive per-pixel merge would make
scattered ~600s reviewed islands look like continuous coverage once
zoomed out far enough), and that the ribbon and the numeric "reviewed: X%"
summary figure are provably computed from the same merge logic.

Run from the project root:
    python tests/test_reviewed_coverage.py
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

from Working.database.schema import init_db
from Working.database import queries as q
from Working.config import REVIEWED_FULL_COVERAGE_THRESHOLD
from UI.plots import build_reviewed_ribbon, _bucket_coverage_fractions


def _row(s, e):
    return {"start_idx": s, "end_idx": e}


# ── type consistency ─────────────────────────────────────────────────────────

def test_no_reviewed_spans_returns_overlay_of_rectangles():
    overlay = build_reviewed_ribbon([], 1.0, (0, 1000))
    assert isinstance(overlay, hv.Overlay)
    assert all(isinstance(el, hv.Rectangles) for el in overlay)


def test_sparse_reviewed_spans_returns_overlay_of_rectangles():
    overlay = build_reviewed_ribbon([_row(100, 200)], 1.0, (0, 1_000_000), n_buckets=10)
    assert isinstance(overlay, hv.Overlay)
    assert all(isinstance(el, hv.Rectangles) for el in overlay)


def test_fully_reviewed_returns_overlay_of_rectangles():
    overlay = build_reviewed_ribbon([_row(0, 1000)], 1.0, (0, 1000), n_buckets=10)
    assert isinstance(overlay, hv.Overlay)
    assert all(isinstance(el, hv.Rectangles) for el in overlay)


def test_zero_span_viewport_returns_overlay_of_rectangles():
    overlay = build_reviewed_ribbon([_row(0, 100)], 1.0, (500, 500))
    assert isinstance(overlay, hv.Overlay)
    assert all(isinstance(el, hv.Rectangles) for el in overlay)


# ── the core guarantee: sparse islands don't look like full coverage ───────────

def test_sparse_islands_never_show_full_coverage_at_coarse_zoom():
    """The exact scenario described: ~600-sample reviewed islands
    scattered across a multi-million-sample channel. At coarse zoom (few
    buckets spanning the whole channel), true coverage is under 1%, and no
    bucket may report >= REVIEWED_FULL_COVERAGE_THRESHOLD."""
    n_samples = 2_200_000
    islands = [(i * 200_000, i * 200_000 + 600) for i in range(11)]
    merged = q.merge_intervals(islands)
    fractions = _bucket_coverage_fractions(merged, 0, n_samples, 10)
    assert max(fractions) < REVIEWED_FULL_COVERAGE_THRESHOLD
    assert max(fractions) < 0.01  # true per-bucket density is ~0.3%


def test_ribbon_is_viewport_reactive_not_just_full_channel():
    """Part B: the ribbon must bucket over the CURRENT VIEWPORT, not a
    fixed whole-channel range. Zooming into a region containing exactly
    one ~600-sample island (out of an otherwise-huge unreviewed channel)
    must show fine-grained partial/gap detail within that narrow view —
    not the same coarse whole-channel picture regardless of zoom."""
    n_samples = 2_200_000
    island = (1_000_000, 1_000_600)

    # Full-channel (coarse) viewport: the island is a negligible sliver.
    coarse_fractions = _bucket_coverage_fractions(
        q.merge_intervals([island]), 0, n_samples, 10,
    )
    assert max(coarse_fractions) < 0.01

    # Zoomed into a narrow window tightly around the island: the SAME
    # island now dominates a much smaller viewport, so at least one
    # bucket must show meaningfully higher coverage than at coarse zoom --
    # proving the bucketing domain actually changed with the viewport.
    zoomed_fractions = _bucket_coverage_fractions(
        q.merge_intervals([island]), 999_000, 1_001_000, 10,
    )
    assert max(zoomed_fractions) > max(coarse_fractions) * 10


def test_sparse_islands_still_not_full_when_viewport_itself_is_coarse():
    """Same guarantee as the full-channel case, phrased explicitly as 'the
    viewport IS the whole channel' -- the coarse-zoom case is just one
    particular viewport, not a special code path."""
    n_samples = 2_200_000
    islands = [(i * 200_000, i * 200_000 + 600) for i in range(11)]
    rows = [_row(s, e) for s, e in islands]
    overlay = build_reviewed_ribbon(rows, 1.0, (0, n_samples), n_buckets=10)
    from UI.plots import REVIEWED_FULL_COLOR
    for el in overlay:
        if el.opts.get("style").kwargs.get("color") == REVIEWED_FULL_COLOR:
            assert len(el.data) == 0, "a sparse island rendered as FULL coverage"


def test_sparse_islands_produce_partial_not_full_rectangles():
    # 3 islands over 10 buckets -- guarantees both occupied (partial) and
    # empty (gap) buckets exist, unlike one-island-per-bucket layouts.
    n_samples = 2_200_000
    islands = [(0, 600), (600_000, 600_600), (1_800_000, 1_800_600)]
    rows = [_row(s, e) for s, e in islands]
    overlay = build_reviewed_ribbon(rows, 1.0, (0, n_samples), n_buckets=10)
    from UI.plots import REVIEWED_FULL_COLOR, REVIEWED_PARTIAL_COLOR, REVIEWED_GAP_COLOR
    colors_by_rowcount = {
        el.opts.get("style").kwargs.get("color"): len(el.data) for el in overlay
    }
    assert colors_by_rowcount.get(REVIEWED_FULL_COLOR, 0) == 0
    assert colors_by_rowcount.get(REVIEWED_PARTIAL_COLOR, 0) == 3
    assert colors_by_rowcount.get(REVIEWED_GAP_COLOR, 0) == 7


def test_all_rectangles_use_the_fixed_zero_to_one_range():
    """The reviewed-coverage ribbon is now a separate pane with a FIXED
    (0, 1) y-range, completely decoupled from the main curve's axis
    (Part A, 2026-08) -- every bucket, in every coverage tier, must use
    exactly this range regardless of viewport or span count. (Compare to
    the pre-Part-A design, where this used to be a fraction of the
    curve's own y-range and could drift from what was actually on
    screen -- see tests/test_ribbon_panes.py for the replacement
    cross-pane alignment coverage.)"""
    cases = [
        [_row(i * 100, i * 100 + 50) for i in range(20)],  # mixed tiers
        [_row(0, 2000)],  # fully covered
        [],  # empty
    ]
    for rows in cases:
        overlay = build_reviewed_ribbon(rows, 1.0, (0, 2000))
        for el in overlay:
            df = el.data
            if len(df):
                col_names = list(df.columns)
                y0_col, y1_col = col_names[1], col_names[3]
                assert (df[y0_col] == 0.0).all()
                assert (df[y1_col] == 1.0).all()


def test_fully_covered_bucket_reports_near_one():
    fractions = _bucket_coverage_fractions([(0, 1000)], 0, 1000, 1)
    assert fractions[0] >= REVIEWED_FULL_COVERAGE_THRESHOLD


def test_uncovered_bucket_reports_exactly_zero():
    fractions = _bucket_coverage_fractions([(500, 600)], 0, 1000, 10)
    # Bucket 0 covers samples 0-100, bucket 5 covers 500-600 (fully
    # covered), all others must be exactly 0 -- not some tiny epsilon from
    # a boundary rounding error.
    for i, f in enumerate(fractions):
        if i == 5:
            continue
        assert f == 0.0, f"bucket {i} unexpectedly non-zero: {f}"


def test_overlapping_reviewed_spans_do_not_double_count():
    # Two spans covering the SAME 0-500 range in a 0-1000 bucket -- true
    # coverage is 50%, not 100% (which naive independent-overlap summing,
    # without merging first, would report).
    merged = q.merge_intervals([(0, 500), (0, 500)])
    fractions = _bucket_coverage_fractions(merged, 0, 1000, 1)
    assert abs(fractions[0] - 0.5) < 1e-9


# ── ribbon and summary must agree (same source function) ───────────────────────

def test_ribbon_and_summary_percentage_agree():
    """Bucket-width-weighted average of the ribbon's per-bucket fractions
    must equal Working.database.queries.reviewed_fraction exactly (within
    floating tolerance) -- both are built from merge_intervals, not two
    independently-written computations that could silently drift apart."""
    conn = init_db(":memory:")
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 100_000, 0, "a/CH0.npy")
    # Deliberately scattered, some overlapping.
    for s, e in [(0, 500), (400, 900), (10_000, 10_600), (50_000, 50_050), (99_000, 100_000)]:
        q.insert_reviewed_span(conn, rid, s, e, source=q.SOURCE_MANUAL_UI)

    reviewed_rows = q.list_reviewed_spans(conn, rid)
    n_buckets = 500
    merged = q.merge_intervals((r["start_idx"], r["end_idx"]) for r in reviewed_rows)
    fractions = _bucket_coverage_fractions(merged, 0, 100_000, n_buckets)
    bucket_width = 100_000 / n_buckets
    ribbon_weighted_avg = sum(f * bucket_width for f in fractions) / 100_000

    summary_fraction = q.reviewed_fraction(conn, rid)
    assert abs(ribbon_weighted_avg - summary_fraction) < 1e-6


def test_ribbon_and_summary_agree_with_no_reviewed_spans():
    conn = init_db(":memory:")
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 10_000, 0, "a/CH0.npy")
    fractions = _bucket_coverage_fractions([], 0, 10_000, 100)
    assert sum(fractions) == 0.0
    assert q.reviewed_fraction(conn, rid) == 0.0


def test_ribbon_and_summary_agree_when_fully_reviewed():
    conn = init_db(":memory:")
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 10_000, 0, "a/CH0.npy")
    q.insert_reviewed_span(conn, rid, 0, 10_000, source=q.SOURCE_MANUAL_UI)
    merged = q.merge_intervals([(0, 10_000)])
    fractions = _bucket_coverage_fractions(merged, 0, 10_000, 100)
    assert all(f >= REVIEWED_FULL_COVERAGE_THRESHOLD for f in fractions)
    assert q.reviewed_fraction(conn, rid) == 1.0


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
