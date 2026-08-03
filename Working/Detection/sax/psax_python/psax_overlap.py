# pSAX representation (overlapping windows), as introduced and studied in:
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
#   NOTE: scans with overlapping windows (for discord detection).
#   For non-overlapping windows use psax.py.
#
#   Author: Konstantinos Bountrogiannis
#   Contact: kbountrogiannis@gmail.com
#   Date: June 2022

import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Working.Detection.sax.csax_python.ts_paa           import ts_paa
from Working.Detection.sax.csax_python.timeseries2symbol import timeseries2symbol
from .kde      import epanechnikov_kde
from .kmeanspp import kmeanspp
from .lloydmax import lloydmax


def psax_overlap(data, training_len, win_size, paa_size, alphabet_size, normalize=True):
    """
    pSAX symbolic representation with overlapping sliding windows.

    Parameters
    ----------
    data          : array-like — full time series
    training_len  : int        — samples used for training
    win_size      : int        — sliding window length
    paa_size      : int        — PAA segments per window
    alphabet_size : int        — quantiser codebook size
    normalize     : bool       — z-normalise each subsequence independently

    Returns
    -------
    str_out : np.ndarray, shape (num_windows, paa_size)
                  pSAX symbol matrix (0-based), one row per window.
    """
    data = np.asarray(data, dtype=float).ravel()

    # Build training PAA from all subsequences in the training region
    num_train_windows = training_len - win_size + 1
    training_paa_rows = np.zeros((num_train_windows, paa_size))

    for i in range(num_train_windows):
        sub = data[i: i + win_size].copy()
        if normalize:
            sigma = np.std(sub)
            if sigma < 0.001:
                sub = sub - sub.mean()
            else:
                sub = (sub - sub.mean()) / sigma
        training_paa_rows[i, :] = ts_paa(sub, paa_size)

    # Concatenate all PAA rows into one flat training vector
    training_paa = training_paa_rows.ravel()

    # Kernel density estimation (Epanechnikov, Silverman bandwidth)
    f, x = epanechnikov_kde(training_paa, npoints=training_len)

    # Lloyd-Max quantisation: initialise codebook with k-means++
    _, init_codewords = kmeanspp(training_paa, alphabet_size)
    init_codewords    = np.sort(init_codewords)

    _, cutlines = lloydmax(f, x, alphabet_size, init=init_codewords)

    # Discretise all overlapping windows (NR_opt=1: record every window)
    sym, _ = timeseries2symbol(data, win_size, paa_size, cutlines,
                               normalize=normalize, NR_opt=1)

    str_out = sym - 1   # convert 1-based → 0-based
    return str_out
