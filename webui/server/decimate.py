"""Peak-preserving decimation for the prototype service layer.

``_minmax_kernel`` and ``_minmax_decimate`` are copied **verbatim** from
``UI/plots.py`` (lines 277-368, 2026-08-31 vectorised version) with
attribution, because importing ``UI.plots`` pulls in HoloViews and this
server must stay UI-library free. Nothing is changed in those two functions;
the additions below them are the prototype's own.
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# BEGIN verbatim copy of UI/plots.py (lines 277-368)
# ---------------------------------------------------------------------------

# How many samples one vectorised decimation pass handles at a time. The
# kernel below allocates a handful of temporaries the size of its input,
# so running it over a whole 2.6M-sample channel in one go is bounded by
# memory bandwidth and gives back most of what vectorising won. Chunking
# keeps those temporaries inside cache. Measured on a full channel:
# unchunked ~48 ms (no better than the old Python loop), chunked ~12 ms.
# The value is not critical — anything from ~64k to ~512k behaves the
# same; it is a cache-size knob, not a correctness one.
_DECIMATE_CHUNK_SAMPLES = 262_144


def _minmax_kernel(x, t, starts, stop):
    """Bucketed min/max over `starts` (absolute indices into `x`), where
    the last bucket ends at `stop`. Returns interleaved (values, times).

    Indices are recovered without a per-bucket `argmin`:
    `np.minimum.reduceat` gives each bucket's minimum *value* in one C
    pass; marking every position equal to its own bucket's minimum and
    reducing those positions' indices by `minimum` gives the *first* such
    index per bucket, which is exactly what `np.argmin` returns, ties
    included. Non-matching positions are set to `stop`, a value no real
    index in range can take, so they never win the reduction.
    """
    counts = np.diff(np.append(starts, stop))
    bucket_min = np.minimum.reduceat(x, starts)
    bucket_max = np.maximum.reduceat(x, starts)

    idx = np.arange(len(x), dtype=np.int64)
    never = np.int64(len(x))
    i_min = np.minimum.reduceat(
        np.where(x == np.repeat(bucket_min, counts), idx, never), starts)
    i_max = np.minimum.reduceat(
        np.where(x == np.repeat(bucket_max, counts), idx, never), starts)

    # Emit in the order the extremes actually occur, so the polyline
    # traces the signal's own up/down shape rather than a sawtooth.
    min_first = i_min <= i_max
    first = np.where(min_first, i_min, i_max)
    second = np.where(min_first, i_max, i_min)
    return first, second


def _minmax_decimate(x_slice, t_slice, max_points):
    """Reduce a slice to roughly `max_points` samples while preserving its
    peaks and troughs, using bucketed min/max (not simple striding, which
    would alias away exactly the spikes this app exists to find).

    Each bucket contributes its min and max value, in that order if the min
    occurs first in the bucket, else max-then-min — so the result traces
    the same up/down envelope a human would see in the full-resolution
    data, just with the flat-ish stretches between extremes omitted.

    **Vectorised and chunked (2026-08-31).** This was a Python `for` loop
    over up to 20,000 buckets, each doing an `np.argmin` and an
    `np.argmax`. It runs on every range event, so panning a whole-channel
    view re-entered that loop for every frame, and it was the single
    largest cost on the viewer's interaction path. Measured before/after
    on random data with the production 40,000-point cap:

        200k samples    46 ms  ->   3.5 ms   (13x)
        1M samples      48 ms  ->   8.8 ms   (5.4x)
        2.6M samples    50 ms  ->  12.1 ms   (4.1x)

    The rewrite is output-identical. `tests/test_plots_perf.py` pins that
    against a verbatim copy of the old loop — including the tie and
    plateau cases, where "first occurrence" ordering decides whether a
    bucket emits min-then-max or max-then-min, and where a vectorised
    rewrite silently diverges if it gets ties wrong.
    """
    n = len(x_slice)
    if n <= max_points:
        return x_slice, t_slice

    n_buckets = max(1, max_points // 2)
    edges = np.unique(np.linspace(0, n, n_buckets + 1).astype(np.int64))
    starts = edges[:-1]

    x = np.asarray(x_slice)
    t = np.asarray(t_slice)
    xs_out = np.empty(2 * len(starts), dtype=x_slice.dtype)
    ts_out = np.empty(2 * len(starts), dtype=t_slice.dtype)

    # Walk whole buckets, never splitting one across chunks — a split
    # bucket would report two local extremes instead of one and change
    # the output.
    b = 0
    while b < len(starts):
        lo = int(starts[b])
        b_end = int(np.searchsorted(starts, lo + _DECIMATE_CHUNK_SAMPLES, side="right"))
        b_end = max(b_end, b + 1)
        stop = int(starts[b_end]) if b_end < len(starts) else n

        first, second = _minmax_kernel(x[lo:stop], t[lo:stop], starts[b:b_end] - lo, stop - lo)
        xs_out[2 * b:2 * b_end:2] = x[lo + first]
        xs_out[2 * b + 1:2 * b_end:2] = x[lo + second]
        ts_out[2 * b:2 * b_end:2] = t[lo + first]
        ts_out[2 * b + 1:2 * b_end:2] = t[lo + second]
        b = b_end

    return xs_out, ts_out

# ---------------------------------------------------------------------------
# END verbatim copy
# ---------------------------------------------------------------------------


def _fast_minmax(seg: np.ndarray, n_buckets: int):
    """Equal-width bucketed min/max with first-occurrence ordering, via
    reshape + argmin/argmax. Same semantics as ``_minmax_kernel`` (each bucket
    emits its min and max in the order they occur) but ~3x faster on this
    machine for a 2.6M-sample channel (14 ms vs 35 ms measured 2026-09-14),
    because it avoids the ``np.where(x == repeat(...))`` temporaries. The tail
    that does not fill a whole bucket becomes one extra bucket. Returns
    (indices, values) as interleaved polyline arrays of length 2 * buckets.
    NaN-free input only."""
    n = len(seg)
    b = max(1, int(np.ceil(n / n_buckets)))
    m = (n // b) * b
    y = seg[:m].reshape(-1, b)
    rows = np.arange(len(y))
    imin = y.argmin(axis=1); imax = y.argmax(axis=1)
    lo = y[rows, imin]; hi = y[rows, imax]
    base = rows * b
    min_first = imin <= imax
    idx = np.empty(2 * len(y), dtype=np.int64); vals = np.empty(2 * len(y), dtype=seg.dtype)
    idx[0::2] = np.where(min_first, imin, imax) + base
    idx[1::2] = np.where(min_first, imax, imin) + base
    vals[0::2] = np.where(min_first, lo, hi)
    vals[1::2] = np.where(min_first, hi, lo)
    if m < n:                                   # tail bucket
        tail = seg[m:]
        ti, ta = int(tail.argmin()), int(tail.argmax())
        first, second = (ti, ta) if ti <= ta else (ta, ti)
        idx = np.concatenate([idx, [m + first, m + second]])
        vals = np.concatenate([vals, [tail[first], tail[second]]])
    return idx, vals


def envelope(x: np.ndarray, fs: float, start_idx: int, end_idx: int, px: int) -> dict:
    """Peak-preserving polyline for the sample window ``[start_idx, end_idx)``
    of ``x`` (a memmap or array), sized for ``px`` device pixels.

    Returns interleaved ``t`` (absolute seconds from recording start) and
    ``v`` lists of length about ``2 * px`` — each bucket contributes its min and
    max in the order they occur, exactly like the old viewer. NaN-safe: a
    bucket that is entirely NaN emits ``None`` (JSON null), a bucket that is
    partly NaN ignores the NaNs.
    """
    n = int(len(x))
    start_idx = max(0, min(n, int(start_idx)))
    end_idx = max(start_idx, min(n, int(end_idx)))
    px = max(8, int(px))
    seg = np.asarray(x[start_idx:end_idx])
    m = len(seg)
    if m == 0:
        return {"t": [], "v": [], "n_source": 0, "n_points": 0, "decimated": False}

    has_nan = bool(np.isnan(seg).any()) if seg.dtype.kind == "f" else False
    max_points = 2 * px
    if m <= max_points:
        t = (np.arange(start_idx, end_idx) / fs)
        v = seg.astype(float)
        vv = [None if (has_nan and np.isnan(a)) else float(a) for a in v]
        return {"t": t.tolist(), "v": vv, "n_source": m, "n_points": m, "decimated": False}

    if not has_nan:
        idx, vals = _fast_minmax(seg, max(1, max_points // 2))
        t = (idx + start_idx) / fs
        return {"t": t.tolist(), "v": vals.astype(float).tolist(),
                "n_source": m, "n_points": int(len(vals)), "decimated": True}

    # NaN-aware fallback (Scores from matrix_profile carry a NaN tail).
    n_buckets = max(1, max_points // 2)
    edges = np.unique(np.linspace(0, m, n_buckets + 1).astype(np.int64))
    t_out, v_out = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        chunk = seg[a:b]
        finite = chunk[~np.isnan(chunk)]
        tc0 = (start_idx + a) / fs
        tc1 = (start_idx + max(a, b - 1)) / fs
        if finite.size == 0:
            t_out.extend([tc0, tc1]); v_out.extend([None, None])
            continue
        lo, hi = float(finite.min()), float(finite.max())
        i_lo = int(np.nanargmin(chunk)); i_hi = int(np.nanargmax(chunk))
        if i_lo <= i_hi:
            t_out.extend([(start_idx + a + i_lo) / fs, (start_idx + a + i_hi) / fs]); v_out.extend([lo, hi])
        else:
            t_out.extend([(start_idx + a + i_hi) / fs, (start_idx + a + i_lo) / fs]); v_out.extend([hi, lo])
    return {"t": t_out, "v": v_out, "n_source": m, "n_points": len(v_out), "decimated": True}
