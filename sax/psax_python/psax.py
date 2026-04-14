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

from sax.csax_python.ts_paa          import ts_paa
from sax.csax_python.timeseries2symbol import timeseries2symbol
from .kde      import epanechnikov_kde
from .kmeanspp import kmeanspp
from .lloydmax import lloydmax


def psax(data, training_len, dim_ratio, alphabet_size, normalize=True):
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

    Returns
    -------
    str_out : np.ndarray, shape (data_nseg,) — pSAX symbolic sequence (0-based)
    """
    data = np.asarray(data, dtype=float).ravel()

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
    if normalize:
        if np.std(training_set) < 0.001:
            data         = data         - data.mean()
            training_set = training_set - training_set.mean()
        else:
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

    _, cutlines = lloydmax(f, x, alphabet_size, init=init_codewords)

    # Discretise with learned cutlines (NR_opt=1: record every window)
    sym, _ = timeseries2symbol(data, data_len, data_nseg, cutlines,
                               normalize=normalize, NR_opt=1)

    str_out = sym.ravel() - 1   # convert 1-based → 0-based
    return str_out
