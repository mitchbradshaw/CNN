# cSAX representation (overlapping windows), as introduced and studied in:
#
#   [1] K. Bountrogiannis, G. Tzagkarakis and P. Tsakalides,
#   "Distribution Agnostic Symbolic Representations for Time Series Dimensionality Reduction
#    and Online Anomaly Detection,"
#   in IEEE Transactions on Knowledge and Data Engineering, 2022.
#
#   NOTE: scans with overlapping windows (used for discord detection).
#   For non-overlapping windows use csax.py.
#
#   Author: Konstantinos Bountrogiannis
#   Contact: kbountrogiannis@gmail.com
#   Date: July 2022

import numpy as np

from .ts_paa                        import ts_paa
from .normal_cutlines               import normal_cutlines
from .timeseries2symbol             import timeseries2symbol
from .meanshift.hg_meanshift_cluster import hg_meanshift_cluster


def csax_overlap(data, training_len, win_size, paa_size, normalize=True):
    """
    cSAX symbolic representation with overlapping sliding windows.

    Parameters
    ----------
    data         : array-like — full time series
    training_len : int        — number of samples used for training
    win_size     : int        — length of each sliding window
    paa_size     : int        — number of PAA segments per window
    normalize    : bool       — z-normalise each subsequence independently

    Returns
    -------
    str_out : np.ndarray, shape (num_windows, paa_size)
                  cSAX symbol matrix (0-based), one row per recorded window.
    """
    data = np.asarray(data, dtype=float).ravel()

    # Build training PAA by scanning all subsequences in the training region
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

    # Concatenate PAA rows into one flat training vector
    training_paa = training_paa_rows.ravel()   # (num_train_windows * paa_size,)

    # Mean-Shift clustering with multi_factor=4 (better for HOT-SAX discord detection)
    multi_factor = 4.0
    clust_cent, _, _ = hg_meanshift_cluster(training_paa, 'gaussian', multi_factor)

    while clust_cent.shape[1] < 2 and multi_factor > 0.5:
        multi_factor /= 2
        clust_cent, _, _ = hg_meanshift_cluster(training_paa, 'gaussian', multi_factor)

    if clust_cent.shape[1] > 1:
        centres  = np.sort(clust_cent[0])
        cutlines = centres[:-1] + np.diff(centres) / 2
    else:
        cutlines = normal_cutlines(3)

    # Discretise all overlapping windows (NR_opt=1: record every window)
    sym, _ = timeseries2symbol(data, win_size, paa_size, cutlines,
                               normalize=normalize, NR_opt=1)

    # Convert from 1-based to 0-based
    str_out = sym - 1

    return str_out
