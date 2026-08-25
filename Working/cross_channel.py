"""
cross_channel.py
=================
The UI-free core of cross-channel classification (ticket 41): given two
waveforms, compute the inter-channel lag from the cross-correlation peak and
the waveform identity from the correlation at that lag, then assign exactly
one of the three classification bins.

The classification is a statement about a motif *family*, not about a single
univariate `Signal`, so this is not an adapter and it imports no UI library.
It can be imported from a bare script, or run directly with
``python Working/cross_channel.py ENTRY_ID`` to classify a library entry's
cross-channel edges.

The bin boundaries are judgement calls that the recurrence claim rests on, so
they are named constants below rather than literals buried in the function.
"""

import numpy as np

from Working.distances import resample_to_length, z_normalize

# The three bins, in the exact spelling persisted on `motif_edge`.
ARTIFACT = "artifact"
PROPAGATION = "propagation"
INDEPENDENT_RECURRENCE = "independent_recurrence"
BINS = (ARTIFACT, PROPAGATION, INDEPENDENT_RECURRENCE)

# ── Bin boundaries ─────────────────────────────────────────────────────────
#
# `artifact` is near-zero lag AND near-identical waveform: the same event seen
# on two channels through a shared ground, not two biological events.
CROSS_CHANNEL_ARTIFACT_MAX_ABS_LAG = 1      # samples; |lag| <= this is near-zero
CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION = 0.99

# `propagation` is a small consistent lag with waveform variation: close
# enough in time to be a propagated event, but no longer identical.
CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG = 50  # samples; |lag| <= this is "small"

# Anything beyond `CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG` is an independent
# recurrence: the same shape reappearing on a different channel at an
# interval too long to be one travelling event.


def cross_correlate(x, y):
    """Normalised cross-correlation between two waveforms.

    The two inputs are resampled to their common (longer) length and
    z-normalised before correlation, so the returned correlations are Pearson
    correlations at each integer sample lag and are directly comparable
    across pairs of unequal native length.

    Returns
    -------
    (lags, correlations) : (numpy.ndarray, numpy.ndarray)
        `lags` are the raw ``numpy.correlate(..., mode="full")`` lags in
        samples; `correlations` are the corresponding correlation values.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.size == 0 or y.size == 0:
        raise ValueError("cross-correlation requires two non-empty waveforms")
    n = max(x.size, y.size)
    x = resample_to_length(x, n)
    y = resample_to_length(y, n)

    zx = z_normalize(x)
    zy = z_normalize(y)

    correlations = np.correlate(zx, zy, mode="full") / n
    lags = np.arange(-(n - 1), n)
    return lags, correlations


def cross_correlation_peak(x, y):
    """The inter-channel lag and waveform identity of two waveforms.

    The peak is the largest absolute correlation (the same shape may be
    inverted on another channel). The returned lag is signed: it is the lag
    of `y` relative to `x`, positive meaning `y` occurs later than `x`.

    Returns
    -------
    (lag, correlation) : (int, float)
    """
    lags, correlations = cross_correlate(x, y)
    peak = int(np.argmax(np.abs(correlations)))
    # `np.correlate(x, y)`'s positive lags mean `x` occurs later than `y`;
    # invert so the public lag reads as `y` relative to `x`.
    return int(-lags[peak]), float(correlations[peak])


def classify_waveforms(x, y):
    """Classify a pair of waveforms into exactly one cross-channel bin.

    Returns
    -------
    (lag, waveform_correlation, classification) : (int, float, str)
        `classification` is one of `ARTIFACT`, `PROPAGATION` or
        `INDEPENDENT_RECURRENCE`.
    """
    lag, waveform_correlation = cross_correlation_peak(x, y)
    abs_lag = abs(lag)

    if (abs_lag <= CROSS_CHANNEL_ARTIFACT_MAX_ABS_LAG
            and waveform_correlation >= CROSS_CHANNEL_ARTIFACT_MIN_CORRELATION):
        classification = ARTIFACT
    elif abs_lag <= CROSS_CHANNEL_PROPAGATION_MAX_ABS_LAG:
        classification = PROPAGATION
    else:
        classification = INDEPENDENT_RECURRENCE

    return lag, waveform_correlation, classification


if __name__ == "__main__":
    import argparse

    from Working.database.schema import init_db
    from Working.library import classify_cross_channel_edges

    parser = argparse.ArgumentParser(
        description="Classify one motif family's cross-channel edges.",
    )
    parser.add_argument("entry_id", type=int, help="motif_entry id to classify")
    parser.add_argument("--db", default=None,
                        help="database path (default: DATA/db/annotations.sqlite)")
    args = parser.parse_args()

    conn = init_db(args.db)
    try:
        results = classify_cross_channel_edges(conn, args.entry_id)
        print(f"classified {len(results)} cross-channel edge(s) for entry {args.entry_id}")
    finally:
        conn.close()
