# Epanechnikov kernel density estimation with Silverman's optimal bandwidth.
#
# Replaces MATLAB's ksdensity(...,'Kernel','epanechnikov') call used in pSAX.
# The bandwidth formula matches mvksdensity.m lines 325-366.
#
# Author: Konstantinos Bountrogiannis (original MATLAB)
# Python port: see psax_python

import numpy as np
from scipy.stats import iqr as scipy_iqr


def epanechnikov_kde(data, npoints):
    """
    Kernel density estimate using the Epanechnikov kernel with Silverman's bandwidth.

    Matches MATLAB: [f, x] = ksdensity(data, 'npoints', npoints, 'Kernel', 'epanechnikov')

    Parameters
    ----------
    data    : array-like — 1-D sample
    npoints : int        — number of evaluation points

    Returns
    -------
    f : np.ndarray, shape (npoints,) — density values
    x : np.ndarray, shape (npoints,) — evaluation points
    """
    data = np.asarray(data, dtype=float).ravel()
    n    = len(data)

    # ── Silverman's bandwidth for Epanechnikov (C = 2.3449) ──────────────────
    std_val = np.std(data, ddof=1)
    iqr_val = scipy_iqr(data) / 1.34
    sig     = min(std_val, iqr_val)
    if sig <= 0:
        sig = max(std_val, iqr_val)
    if sig <= 0:
        sig = 1.0

    C = 2.3449
    h = sig * C * n ** (-0.2)

    # ── Evaluation grid (foldwidth = sqrt(5) for Epanechnikov) ───────────────
    foldwidth = np.sqrt(5)
    x = np.linspace(data.min() - foldwidth * h,
                    data.max() + foldwidth * h,
                    npoints)

    # ── Epanechnikov kernel: K(u) = 3/4*(1-u^2), |u| <= 1 ───────────────────
    # Vectorised: u shape (npoints, n)
    u      = (x[:, None] - data[None, :]) / h           # (npoints, n)
    inside = np.abs(u) <= 1.0
    K      = np.where(inside, 0.75 * (1.0 - u ** 2), 0.0)
    f      = K.sum(axis=1) / (n * h)

    return f, x
