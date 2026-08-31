"""
test_plots_perf.py
==================
The performance work of 2026-08-31, pinned by behaviour rather than by
timing. A wall-clock assertion is a flaky test on a shared machine, so
each of these asserts the *mechanism* that makes the app fast, and the
one timing check that is here is a ratio with an order-of-magnitude
margin, not a millisecond budget.

What was slow, and why:

- `_minmax_decimate` ran a Python `for` loop over up to 20,000 buckets,
  doing two `np.argmin`/`np.argmax` calls each, on **every range event**.
  Panning the whole-channel view re-ran it over 2.6M samples per frame.
  It is now vectorised. The first test here is the one that matters: the
  vectorised version must produce byte-identical output to the loop, or
  the decimation is no longer the same picture.
- `load_channel_mmap` re-opened the `.npy` on every call, and
  `build_channel_dmap` scanned the **entire** channel for its min/max on
  every plot rebuild — which happens on every view-transform toggle and
  every tool re-arm, not just on load. Both are now cached against the
  file's identity (path, mtime, size), so a re-materialised channel still
  invalidates.
"""

import os
import sys
import tempfile
import time

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import holoviews as hv
hv.extension("bokeh")

from UI import plots as P


def _reference_minmax_decimate(x_slice, t_slice, max_points):
    """The original loop, kept verbatim as the oracle.

    This is deliberately a copy rather than an import: the point of the
    first test is that the fast implementation agrees with THIS, so it
    has to survive the fast one replacing it in `UI/plots.py`.
    """
    n = len(x_slice)
    if n <= max_points:
        return x_slice, t_slice
    n_buckets = max(1, max_points // 2)
    edges = np.unique(np.linspace(0, n, n_buckets + 1).astype(np.int64))
    starts = edges[:-1]
    xs_out = np.empty(2 * len(starts), dtype=x_slice.dtype)
    ts_out = np.empty(2 * len(starts), dtype=t_slice.dtype)
    ends = np.append(starts[1:], n)
    for i, (lo, hi) in enumerate(zip(starts, ends)):
        seg = x_slice[lo:hi]
        i_min = lo + int(np.argmin(seg))
        i_max = lo + int(np.argmax(seg))
        if i_min <= i_max:
            xs_out[2 * i], xs_out[2 * i + 1] = x_slice[i_min], x_slice[i_max]
            ts_out[2 * i], ts_out[2 * i + 1] = t_slice[i_min], t_slice[i_max]
        else:
            xs_out[2 * i], xs_out[2 * i + 1] = x_slice[i_max], x_slice[i_min]
            ts_out[2 * i], ts_out[2 * i + 1] = t_slice[i_max], t_slice[i_min]
    return xs_out, ts_out


# ── (a) the vectorised decimation draws exactly the same picture ────────

@pytest.mark.parametrize("n,max_points", [
    (10, 40_000),          # below the cap: passthrough
    (40_000, 40_000),      # exactly at the cap: passthrough
    (40_001, 40_000),      # one over: buckets of 1-2 samples, the ragged case
    (100_000, 40_000),
    (2_595_600, 40_000),   # a real full channel
    (123_457, 1_000),      # bucket count that does not divide evenly
    (5_000, 3),            # pathological: fewer buckets than 2
])
def test_vectorised_decimation_matches_the_loop(n, max_points):
    rng = np.random.default_rng(20260831)
    x = rng.standard_normal(n).astype(np.float64)
    t = np.arange(n, dtype=np.float64) / 3.0

    got_x, got_t = P._minmax_decimate(x, t, max_points)
    want_x, want_t = _reference_minmax_decimate(x, t, max_points)

    np.testing.assert_array_equal(got_x, want_x)
    np.testing.assert_array_equal(got_t, want_t)


def test_decimation_matches_the_loop_with_ties_and_plateaus():
    """Ties matter. `np.argmin` returns the FIRST occurrence, and the
    output ordering (min-then-max or max-then-min) is decided by which
    index comes first — so a signal full of repeated values, which a
    flat-lining electrode produces constantly, is exactly where a
    vectorised rewrite silently diverges."""
    x = np.repeat([0.0, 0.0, 1.0, 1.0, -1.0, -1.0, 0.0], 3_000).astype(np.float64)
    t = np.arange(len(x), dtype=np.float64)
    got_x, got_t = P._minmax_decimate(x, t, 1_000)
    want_x, want_t = _reference_minmax_decimate(x, t, 1_000)
    np.testing.assert_array_equal(got_x, want_x)
    np.testing.assert_array_equal(got_t, want_t)


def test_decimation_preserves_a_spike_a_stride_would_lose():
    """The property the whole min/max scheme exists for: a single-sample
    spike survives decimation. Simple striding would alias it away, and
    finding spikes is what this application is for."""
    x = np.zeros(500_000)
    x[123_456] = 42.0
    t = np.arange(len(x), dtype=np.float64)
    out_x, _out_t = P._minmax_decimate(x, t, 4_000)
    assert out_x.max() == 42.0


def test_decimation_is_not_quadratically_slow():
    """A ratio, not a budget. Ten times the input must not cost anywhere
    near ten times the work per sample — the old Python loop scaled with
    bucket count and dominated every pan of a wide viewport."""
    rng = np.random.default_rng(1)
    t0 = time.perf_counter()
    P._minmax_decimate(rng.standard_normal(200_000), np.arange(200_000.0), 40_000)
    small = time.perf_counter() - t0
    t0 = time.perf_counter()
    P._minmax_decimate(rng.standard_normal(2_000_000), np.arange(2_000_000.0), 40_000)
    large = time.perf_counter() - t0
    assert large < max(small * 40, 2.0), (
        f"decimation scaled badly: {small:.3f}s for 200k, {large:.3f}s for 2M")


# ── (b) the channel file is opened once, and re-opened when it changes ──

def _tmp_npy(values):
    fd, path = tempfile.mkstemp(suffix=".npy")
    os.close(fd)
    np.save(path, np.asarray(values, dtype=np.float64))
    return path


def test_channel_mmap_is_reused_for_the_same_file():
    path = _tmp_npy(np.arange(100.0))
    try:
        a = P.load_channel_mmap(path)
        b = P.load_channel_mmap(path)
        assert a is b, "the same channel file was memory-mapped twice"
    finally:
        os.unlink(path)


def test_channel_mmap_is_invalidated_when_the_file_changes():
    """A re-materialised channel must not keep serving the old array.

    `Working/` can rewrite a channel `.npy` (re-import, re-materialise).
    A cache keyed on the path alone would hand the viewer stale data
    with no way to notice, which is a far worse bug than the slowness
    the cache is fixing.
    """
    path = _tmp_npy(np.arange(100.0))
    try:
        first = P.load_channel_mmap(path)
        assert float(first[0]) == 0.0
        time.sleep(0.01)
        np.save(path, np.arange(100.0) + 1000.0)
        second = P.load_channel_mmap(path)
        assert float(second[0]) == 1000.0, "stale mmap served after the file was rewritten"
    finally:
        os.unlink(path)


def test_channel_extent_matches_a_full_scan_and_is_cached():
    path = _tmp_npy(np.array([-3.0, 0.0, 7.5, 2.0]))
    try:
        lo, hi = P.channel_extent(path)
        assert (lo, hi) == (-3.0, 7.5)
        assert P.channel_extent(path) == (lo, hi)
    finally:
        os.unlink(path)


def test_channel_extent_is_invalidated_when_the_file_changes():
    path = _tmp_npy(np.array([0.0, 1.0]))
    try:
        assert P.channel_extent(path) == (0.0, 1.0)
        time.sleep(0.01)
        np.save(path, np.array([0.0, 99.0]))
        assert P.channel_extent(path) == (0.0, 99.0)
    finally:
        os.unlink(path)
