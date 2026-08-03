# Lloyd-Max quantizer.
#
# Author: Konstantinos Bountrogiannis
# Contact: kbountrogiannis@gmail.com
# Date: June 2022
#
# Python port: see psax_python

import numpy as np
from .kmeanspp import kmeanspp


def lloydmax(f, x, ncodewords, data=None, init=None, lock_bounds=False):
    """
    Lloyd-Max optimal scalar quantizer.

    Iteratively finds codewords C and decision boundaries b that minimise
    the mean-squared quantisation error under the density (f, x).

    Parameters
    ----------
    f           : array-like — PDF values evaluated on x
    x           : array-like — evaluation grid (same length as f)
    ncodewords  : int        — codebook size (number of quantisation levels)
    data        : array-like or None — raw data used for k-means++ init when
                                       init is None
    init        : array-like or None — initial codewords (length ncodewords) or
                                       initial boundaries (length ncodewords-1),
                                       or a shorter codebook to be padded
    lock_bounds : bool       — if True, fix boundaries and only update codewords

    Returns
    -------
    C : np.ndarray, shape (ncodewords,)   — codeword values (sorted)
    b : np.ndarray, shape (ncodewords-1,) — decision boundaries (cutlines)
    """
    f = np.asarray(f, dtype=float).ravel()
    x = np.asarray(x, dtype=float).ravel()

    tol  = 1e-7
    tol2 = np.finfo(float).eps * (x.max() - x.min())

    # ── Initialisation ───────────────────────────────────────────────────────
    C           = None
    b           = None
    init_bounds  = False
    init_codebook = False

    if init is not None:
        init = np.asarray(init, dtype=float).ravel()
        if len(init) == ncodewords:
            C             = init.copy()
            init_codebook = True
        elif len(init) == ncodewords - 1:
            b            = init.copy()
            init_bounds  = True
        elif len(init) < ncodewords:
            idx   = int(np.argmin(np.abs(init - init.mean())))
            v     = init[idx]
            space = ncodewords - len(init)
            C     = np.concatenate([init[:idx + 1],
                                    np.full(space, v),
                                    init[idx + 1:]])
            init_codebook = True

    if not init_codebook and data is not None:
        _, C = kmeanspp(data, ncodewords)
        C    = np.sort(C)

    if C is None:
        # Fallback random initialisation
        C = np.sort((x[0] + (x[-1] - x[0]) * np.random.rand(2)) % x[-1])

    prev_C = np.zeros(ncodewords)
    prev_b = np.zeros(max(ncodewords - 1, 1))

    # ── Main loop ────────────────────────────────────────────────────────────
    stop = False
    itr  = 0

    while not stop and itr < 100:

        # Step 1: update boundaries
        if (itr > 1 or not init_bounds) and not lock_bounds:
            b = (C[:-1] + C[1:]) / 2.0

        # Step 2: update codewords as PDF-weighted centroids
        for i in range(ncodewords):
            if i == 0:
                b1 = 0
                b2 = int(np.argmin(np.abs(b[i] - x)))
                if b2 == b1:
                    b2 = b1 + 1
            elif i == ncodewords - 1:
                b1 = int(np.argmin(np.abs(b[i - 1] - x)))
                b2 = len(x) - 1
                if b2 == b1:
                    b1 = b2 - 1
            else:
                b1 = int(np.argmin(np.abs(b[i - 1] - x)))
                b2 = int(np.argmin(np.abs(b[i]     - x)))
                if b2 <= b1:
                    if b1 > 0:
                        b1 = b2 - 1
                    elif b2 < len(x) - 1:
                        b2 = b1 + 1

            b2   = min(len(x) - 1, b2)
            xs   = x[b1: b2 + 1]
            fs   = f[b1: b2 + 1]
            I1   = np.trapz(xs * fs, xs)
            I2   = np.trapz(fs,      xs)

            if I2 == 0.0 or not np.isfinite(I1 / I2 if I2 != 0 else np.inf):
                f[b1: b2 + 1] += np.finfo(float).tiny
                f /= np.trapz(f, x)
                xs  = x[b1: b2 + 1]
                fs  = f[b1: b2 + 1]
                I1  = np.trapz(xs * fs, xs)
                I2  = np.trapz(fs,      xs)
                val = I1 / I2 if I2 != 0 else np.nan
                if not np.isfinite(val):
                    raise ValueError("lloydmax: codeword became NaN or Inf")
                C[i] = val
            else:
                C[i] = I1 / I2

        # Convergence check
        move = np.mean(np.abs(prev_C - C))
        rel_dist = move / np.mean(np.abs(C)) if move > tol2 else move
        stop = (rel_dist < tol) and (rel_dist < tol2)

        prev_b = b.copy()
        prev_C = C.copy()
        itr   += 1

    return C, b
