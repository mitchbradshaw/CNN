# Author: Konstantinos Bountrogiannis
# Contact: kbountrogiannis@gmail.com
# Date: July 2022

import numpy as np


def epanechfun(x, d, bandwidth):
    """
    Epanechnikov kernel weighted mean.

    Parameters
    ----------
    x         : np.ndarray, shape (numDim, inN) — data points within bandwidth
    d         : np.ndarray, shape (inN,)         — squared distances to current mean
    bandwidth : float

    Returns
    -------
    out : np.ndarray, shape (numDim,) — kernel-weighted mean
    """
    a    = 2
    ns   = 1000
    xs   = np.linspace(0, a * bandwidth ** 2, ns + 1)
    kfun = np.maximum(0.0, 1.0 - xs / bandwidth ** 2)

    idx = np.round(d / (a * bandwidth ** 2) * ns).astype(int)
    idx = np.clip(idx, 0, ns)
    w   = kfun[idx]                          # (inN,)

    return np.sum(x * w, axis=1) / np.sum(w)  # (numDim,)
