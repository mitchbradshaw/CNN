"""
detrend.py
===========
Plain numpy/scipy detrending — headless, no Panel/HoloViews/Bokeh imports
(the standing rule for everything under `Working/`).

Added (2026-08) because Stage 3's benchmark found preprocessing dominated
every matcher choice for the SAX encoding view (recall 0.22 raw vs 0.85
detrended) — reachable from the UI's Run algorithm tab via
`Adapters/preprocessing_detrend.py`, which wraps `make_detrend_filter`
exactly like `Working.Detection.analysis.freq_analysis.make_bandpass_filter`
wraps its own scipy call.
"""

import numpy as np


def _rolling_mean(w, window_samples):
    """Centred rolling mean via a cumulative-sum trick — O(n), edges use
    whatever window actually fits (no NaN padding, no shrinking the
    output length)."""
    n = len(w)
    half = max(1, window_samples // 2)
    csum = np.concatenate([[0.0], np.cumsum(w, dtype=np.float64)])
    out = np.empty(n, dtype=np.float64)
    idx = np.arange(n)
    lo = np.clip(idx - half, 0, n)
    hi = np.clip(idx + half + 1, 0, n)
    out = (csum[hi] - csum[lo]) / (hi - lo)
    return out


def make_detrend_filter(fs, mode="rolling_mean", window_s=600.0):
    """
    Factory: returns fn(w) that removes a slow trend from a window.

    Parameters
    ----------
    fs        : float  Sampling frequency (Hz) — converts `window_s` to samples.
    mode      : str    "rolling_mean" (subtract a centred rolling mean),
                        "rolling_z" (rolling_mean subtracted, then divided
                        by a matching centred rolling std), or "linear"
                        (subtract a single least-squares line over the
                        whole span — ignores `window_s`).
    window_s  : float  Rolling-window width in seconds (ignored for "linear").
    """
    if mode not in ("rolling_mean", "rolling_z", "linear"):
        raise ValueError(f"Unknown detrend mode {mode!r} — must be 'rolling_mean', 'rolling_z', or 'linear'")

    def _detrend(w):
        w = np.asarray(w, dtype=np.float64)
        if mode == "linear":
            idx = np.arange(len(w))
            coeffs = np.polyfit(idx, w, 1)
            return w - np.polyval(coeffs, idx)

        window_samples = max(1, int(round(window_s * fs)))
        trend = _rolling_mean(w, window_samples)
        out = w - trend
        if mode == "rolling_z":
            rolling_var = _rolling_mean((w - trend) ** 2, window_samples)
            rolling_std = np.sqrt(np.maximum(rolling_var, 0.0))
            out = np.divide(out, rolling_std, out=np.zeros_like(out), where=rolling_std > 1e-12)
        return out

    return _detrend
