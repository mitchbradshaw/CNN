"""
distances.py
==============
Three named ways to say two spans are the same shape (T35), each a named
constant rather than an anonymous callable so it can be recorded verbatim
on the `motif_edge` it produces (PIPELINE_PRD.md, "Distances"):

  DISTANCE_SCALE_INVARIANT  Resample both spans to a common length,
                            z-normalise, Euclidean. The primary distance —
                            shape independent of duration.
  DISTANCE_SYMBOLIC         SAX minimum-distance (MINDIST) at a fixed word
                            length. Scale-invariant by construction through
                            piecewise aggregation: reuses the existing SAX
                            ports (`normal_cutlines` for breakpoints,
                            `timeseries2symbol` for the PAA + z-normalise +
                            quantise pipeline it already implements) rather
                            than reimplementing PAA.
  DISTANCE_NATIVE_LENGTH    z-normalised Euclidean at native length (no
                            resampling) — the unnormalised control. Spans
                            of unequal length are compared over their
                            shorter's length, unresampled, so a duration
                            mismatch shows up as a large distance rather
                            than being reconciled away.

`DISTANCE_REGISTRY` maps each name to its function, so a caller (ticket 41)
can look a distance up by the name recorded on an edge rather than storing
a callable.

Elastic distances (e.g. dynamic time warping) are explicitly out of scope
— see PIPELINE_PRD.md's "Distances" paragraph.
"""

import numpy as np

from Working.Detection.sax.csax_python.normal_cutlines import normal_cutlines
from Working.Detection.sax.csax_python.timeseries2symbol import timeseries2symbol

DISTANCE_SCALE_INVARIANT = "scale_invariant"
DISTANCE_SYMBOLIC = "symbolic_sax"
DISTANCE_NATIVE_LENGTH = "native_length"


def z_normalize(x):
    """z-normalise `x` to zero mean, unit variance. A constant span
    (std == 0) returns an all-zero array rather than dividing by zero."""
    x = np.asarray(x, dtype=float).ravel()
    mu, sigma = x.mean(), x.std()
    if sigma == 0:
        return np.zeros_like(x)
    return (x - mu) / sigma


def resample_to_length(x, n):
    """Linearly resample `x` to `n` points spanning its original extent —
    the step that makes two spans of different sample count comparable
    before a scale-invariant distance."""
    x = np.asarray(x, dtype=float).ravel()
    if len(x) == n:
        return x.copy()
    old_idx = np.linspace(0.0, 1.0, len(x))
    new_idx = np.linspace(0.0, 1.0, n)
    return np.interp(new_idx, old_idx, x)


def scale_invariant_distance(x1, x2, n_samples=None):
    """Resample both spans to a common length, z-normalise, Euclidean.

    `n_samples` defaults to the longer of the two spans' native lengths,
    so no information is thrown away by downsampling the longer span.
    """
    x1 = np.asarray(x1, dtype=float).ravel()
    x2 = np.asarray(x2, dtype=float).ravel()
    if n_samples is None:
        n_samples = max(len(x1), len(x2))
    r1 = z_normalize(resample_to_length(x1, n_samples))
    r2 = z_normalize(resample_to_length(x2, n_samples))
    return float(np.linalg.norm(r1 - r2))


def native_length_distance(x1, x2):
    """z-normalised Euclidean at native length — the unnormalised control.

    No resampling: the two spans are compared sample-for-sample from their
    start, truncated to the shorter span's length. A pair identical in
    shape but differing in duration is therefore large under this
    distance, unlike `scale_invariant_distance`.
    """
    x1 = np.asarray(x1, dtype=float).ravel()
    x2 = np.asarray(x2, dtype=float).ravel()
    n = min(len(x1), len(x2))
    r1 = z_normalize(x1[:n])
    r2 = z_normalize(x2[:n])
    return float(np.linalg.norm(r1 - r2))


def _sax_symbols(x, word_length, cutlines):
    """One span's 0-based SAX symbol string at a fixed word length, via
    the existing SAX ports: `timeseries2symbol` z-normalises and
    PAA-reduces the whole span to `word_length` symbols in one call
    (N=len(x): a single window spanning the whole span; NR_opt=1: no
    numerosity reduction, so the one window is always recorded)."""
    x = np.asarray(x, dtype=float).ravel()
    symbols, _ = timeseries2symbol(x, len(x), word_length, cutlines,
                                    normalize=True, NR_opt=1)
    return symbols[0] - 1  # 1-based -> 0-based


def _mindist_cell_table(cutlines, alphabet_size):
    """Symbol-to-symbol MINDIST lookup: 0 for adjacent-or-equal symbols
    (|r-c|<=1), otherwise the gap between the breakpoints separating
    them — the classic SAX distance table (Lin, Keogh, Lonardi & Chiu,
    2003), built from the same `cutlines` used to quantise both spans."""
    table = np.zeros((alphabet_size, alphabet_size))
    for r in range(alphabet_size):
        for c in range(alphabet_size):
            if abs(r - c) <= 1:
                continue
            lo, hi = (r, c) if r < c else (c, r)
            table[r, c] = cutlines[hi - 1] - cutlines[lo]
    return table


def symbolic_distance(x1, x2, word_length, alphabet_size=10):
    """SAX minimum-distance (MINDIST) between two spans' symbol strings at
    a fixed word length. Scale-invariant by construction: piecewise
    aggregation folds each span's own duration into the same word length
    before comparison, so no separate resampling step is needed.
    """
    cutlines = normal_cutlines(alphabet_size)
    s1 = _sax_symbols(x1, word_length, cutlines)
    s2 = _sax_symbols(x2, word_length, cutlines)
    table = _mindist_cell_table(cutlines, alphabet_size)
    cell_dists = table[s1, s2]
    return float(np.sqrt(np.sum(cell_dists ** 2)))


DISTANCE_REGISTRY = {
    DISTANCE_SCALE_INVARIANT: scale_invariant_distance,
    DISTANCE_SYMBOLIC: symbolic_distance,
    DISTANCE_NATIVE_LENGTH: native_length_distance,
}
