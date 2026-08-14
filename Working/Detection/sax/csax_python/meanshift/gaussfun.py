# Copyright 2015 Han Gong, University of East Anglia
# Modified by Konstantinos Bountrogiannis, July 2022

import numpy as np


def gaussfun(x, d, bandwidth):
    """
    Approximate Gaussian kernel weighted mean.

    Parameters
    ----------
    x         : np.ndarray, shape (numDim, inN) — data points within bandwidth
    d         : np.ndarray, shape (inN,)         — squared distances to current mean
    bandwidth : float

    Returns
    -------
    out : np.ndarray, shape (numDim,) — kernel-weighted mean
    """
    ns   = 1000
    xs   = np.linspace(0, bandwidth ** 2, ns + 1)
    kfun = np.exp(-xs / (2 * bandwidth ** 2))

    idx = np.round(d / bandwidth ** 2 * ns).astype(int)
    idx = np.clip(idx, 0, ns)
    w   = kfun[idx]                          # (inN,)

    return np.sum(x * w, axis=1) / np.sum(w)  # (numDim,)
