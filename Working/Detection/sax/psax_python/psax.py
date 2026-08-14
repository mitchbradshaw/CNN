# pSAX representation, as introduced and studied in:
#
#   [1] K. Bountrogiannis, G. Tzagkarakis and P. Tsakalides,
#   "Data-driven Kernel-based Probabilistic SAX for Time Series Dimensionality Reduction,"
#   2020 28th European Signal Processing Conference (EUSIPCO), 2021.
#
#   [2] K. Bountrogiannis, G. Tzagkarakis and P. Tsakalides,
#   "Distribution Agnostic Symbolic Representations for Time Series Dimensionality
#    Reduction and Online Anomaly Detection,"
#   in IEEE Transactions on Knowledge and Data Engineering, 2022.
#
#   NOTE: scans with non-overlapping windows. For overlapping windows use psax_overlap.py.
#   pSAX treats the dataset as a whole; pSAX_overlap treats it as separate subsequences.
#
#   Author: Konstantinos Bountrogiannis
#   Contact: kbountrogiannis@gmail.com
#   Date: June 2022

import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Working.Detection.sax.csax_python.ts_paa          import ts_paa
from Working.Detection.sax.csax_python.timeseries2symbol import timeseries2symbol
from .kde      import epanechnikov_kde
from .kmeanspp import kmeanspp
from .lloydmax import lloydmax

_NORM_THRESH = 0.001  # matches timeseries2symbol's own normalisation threshold


def psax(data, training_len, dim_ratio, alphabet_size, normalize=True, return_details=False):
    """
    pSAX symbolic representation (non-overlapping windows).

    Parameters
    ----------
    data          : array-like — full time series
    training_len  : int        — samples used for density estimation
    dim_ratio     : float      — dimensionality reduction ratio
                                 (e.g. 1/3 → every 3 samples → 1 symbol)
    alphabet_size : int        — quantiser codebook size
    normalize     : bool       — z-normalise the dataset as a whole before processing
    return_details : bool      — if True, return `(str_out, details)` instead
        of just `str_out` (default False: byte-identical to every existing
        caller). See `Working.Detection.sax.csax_python.csax.csax`'s
        docstring for why `details["paa"]`/`["cutlines"]` are not simply
        `training_paa`/the raw `cutlines` from `lloydmax` — the identical
        "timeseries2symbol re-normalises its single window" mechanism
        applies here too, and is replicated the same way.

    Returns
    -------
    str_out : np.ndarray, shape (data_nseg,) — pSAX symbolic sequence (0-based)
    details : dict, only when return_details=True — same shape as cSAX's,
        with `representatives` = the Lloyd-Max codewords (`C`, sorted) and
        no `fallback_used` key (pSAX has no fallback path).
    """
    data = np.asarray(data, dtype=float).ravel()
    original_len = len(data)

    # Trim so data fits exactly into segments
    data_len  = len(data)
    data_nseg = int(np.floor(dim_ratio * data_len))
    data_len  = data_len - (data_len % data_nseg)
    data      = data[:data_len]

    # Trim training set similarly
    training_nseg = int(np.floor(dim_ratio * training_len))
    training_len  = training_len - (training_len % training_nseg)
    training_set  = data[:training_len]

    # Normalise entire dataset as a whole (not per-window)
    mu1, sigma1 = 0.0, 1.0
    if normalize:
        mu1 = data.mean()
        if np.std(training_set) < 0.001:
            data         = data         - data.mean()
            training_set = training_set - training_set.mean()
        else:
            sigma1       = data.std()
            data         = (data         - data.mean())         / data.std()
            training_set = (training_set - training_set.mean()) / training_set.std()

    # PAA of the training set
    training_paa = ts_paa(training_set, training_nseg)

    # Kernel density estimation (Epanechnikov, Silverman bandwidth).
    # Cap npoints at 1000 (MATLAB ksdensity default) — passing training_len
    # as the grid size creates an O(npoints × n_paa) matrix that exhausts
    # memory on long recordings (e.g. 162710 × 16271 ≈ 20 GB).
    f, x = epanechnikov_kde(training_paa, npoints=min(training_len, 1000))

    # Lloyd-Max quantisation: initialise codebook with k-means++
    _, init_codewords = kmeanspp(training_paa, alphabet_size)
    init_codewords    = np.sort(init_codewords)

    codewords, cutlines = lloydmax(f, x, alphabet_size, init=init_codewords)

    # Discretise with learned cutlines (NR_opt=1: record every window)
    sym, _ = timeseries2symbol(data, data_len, data_nseg, cutlines,
                               normalize=normalize, NR_opt=1)

    str_out = sym.ravel() - 1   # convert 1-based → 0-based

    if not return_details:
        return str_out

    # ── Replicate timeseries2symbol's single-window (N=data_len) inner
    # normalisation to recover the EXACT PAA it quantised.
    sub = data.copy()
    mu2, sigma2 = 0.0, 1.0
    if normalize:
        mu2 = sub.mean()
        sig = sub.std()
        if sig > _NORM_THRESH:
            sigma2 = sig
            sub = (sub - mu2) / sigma2
        else:
            sub = sub - mu2
    paa = ts_paa(sub, data_nseg)

    if normalize:
        norm_std = sigma1 * sigma2
        norm_mean = mu2 * sigma1 + mu1
    else:
        norm_std = None
        norm_mean = None

    paa_raw = paa if norm_std is None else paa * norm_std + norm_mean
    cutlines_raw = cutlines if norm_std is None else np.asarray(cutlines) * norm_std + norm_mean
    # See `csax.py`'s matching comment: `codewords` live in the
    # ONCE-normalised domain (KDE + Lloyd-Max ran on `training_paa`,
    # before `timeseries2symbol`'s inner renormalisation) — undo only the
    # first normalisation step, not the composed one.
    representatives = np.sort(np.asarray(codewords, dtype=float))
    representatives_raw = representatives if not normalize else representatives * sigma1 + mu1

    details = {
        "samples_per_symbol": data_len // data_nseg,
        "n_symbols": data_nseg,
        "data_len_trimmed": data_len,
        "n_trimmed": original_len - data_len,
        "paa": paa,
        "cutlines": np.asarray(cutlines, dtype=float),
        "representatives": representatives,
        "representatives_raw": representatives_raw,
        "alphabet_size": len(codewords),
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "paa_raw": paa_raw,
        "cutlines_raw": cutlines_raw,
    }
    return str_out, details
