# cSAX representation, as introduced and studied in:
#
#   [1] K. Bountrogiannis, G. Tzagkarakis and P. Tsakalides,
#   "Distribution Agnostic Symbolic Representations for Time Series Dimensionality Reduction
#    and Online Anomaly Detection,"
#   in IEEE Transactions on Knowledge and Data Engineering, 2022.
#
#   NOTE: scans with non-overlapping windows. For overlapping windows use csax_overlap.py.
#   cSAX treats the dataset as a whole; cSAX_overlap treats it as separate subsequences.
#
#   Author: Konstantinos Bountrogiannis
#   Contact: kbountrogiannis@gmail.com
#   Date: July 2022

import numpy as np

from .ts_paa                        import ts_paa
from .normal_cutlines               import normal_cutlines
from .timeseries2symbol             import timeseries2symbol
from .meanshift.hg_meanshift_cluster import hg_meanshift_cluster


def csax(data, training_len, dim_ratio, normalize=True):
    """
    cSAX symbolic representation (non-overlapping windows).

    Parameters
    ----------
    data         : array-like — full time series
    training_len : int        — number of samples used for density estimation
    dim_ratio    : float      — dimensionality reduction ratio (e.g. 1/3 → every 3 samples → 1 symbol)
    normalize    : bool       — z-normalise the dataset as a whole before processing

    Returns
    -------
    str_out : np.ndarray, shape (data_nseg,) — cSAX symbolic sequence (0-based symbol indices)
    """
    data = np.asarray(data, dtype=float).ravel()

    # Trim data so it fits exactly into segments
    data_len  = len(data)
    data_nseg = int(np.floor(dim_ratio * data_len))
    data_len  = data_len - (data_len % data_nseg)
    data      = data[:data_len]

    # Trim training set similarly
    training_nseg = int(np.floor(dim_ratio * training_len))
    training_len  = training_len - (training_len % training_nseg)
    training_set  = data[:training_len]

    # Normalise entire dataset (not per-window)
    if normalize:
        if np.std(training_set) < 0.001:
            data         = data         - data.mean()
            training_set = training_set - training_set.mean()
        else:
            data         = (data         - data.mean())         / data.std()
            training_set = (training_set - training_set.mean()) / training_set.std()

    # PAA of the training set
    training_paa = ts_paa(training_set, training_nseg)   # (training_nseg,)

    # Mean-Shift clustering to learn data-adaptive cutlines
    multi_factor = 1.0
    clust_cent, _, _ = hg_meanshift_cluster(training_paa, 'gaussian', multi_factor)

    while clust_cent.shape[1] < 2 and multi_factor > 0.5:
        multi_factor /= 2
        clust_cent, _, _ = hg_meanshift_cluster(training_paa, 'gaussian', multi_factor)

    if clust_cent.shape[1] > 1:
        centres  = np.sort(clust_cent[0])           # ensure sorted
        cutlines = centres[:-1] + np.diff(centres) / 2
    else:
        # Fallback to standard SAX
        cutlines = normal_cutlines(10)

    # Discretise with learned cutlines (NR_opt=1: no numerosity reduction)
    sym, _ = timeseries2symbol(data, data_len, data_nseg, cutlines,
                               normalize=normalize, NR_opt=1)

    # sym is (1, data_nseg) with 1-based indices; convert to 0-based 1-D array
    str_out = sym.ravel() - 1

    return str_out
