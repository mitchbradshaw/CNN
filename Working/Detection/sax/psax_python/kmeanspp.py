# k-means++ initialisation.
# Taken from the k-means file of Laurent S.:
# https://www.mathworks.com/matlabcentral/fileexchange/28804-k-means
#
# Python port: see psax_python

import numpy as np


def kmeanspp(X, k):
    """
    k-means++ initialisation for 1-D data.

    Parameters
    ----------
    X : array-like — 1-D data (or row vector)
    k : int        — number of cluster centres

    Returns
    -------
    L : np.ndarray, shape (n,) — cluster label per point (0-based)
    C : np.ndarray, shape (k,) — cluster centres (sorted ascending)
    """
    X = np.asarray(X, dtype=float).ravel()
    n = len(X)
    k = min(n, k)

    L  = np.zeros(n, dtype=int)
    L1 = np.full(n, -1, dtype=int)

    while not np.array_equal(np.unique(L), np.arange(k)):
        # Random initial centre
        C = [X[int(round(np.random.rand() * (n - 1)))]]
        L = np.zeros(n, dtype=int)

        for i in range(1, k):
            # Distance from each point to its current nearest centre
            D  = X - np.array(C)[L]              # signed distance (1-D)
            D  = np.cumsum(np.abs(D))             # cumulative distance

            if D[-1] == 0:
                # Degenerate: fill remaining centres with same point
                while len(C) < k:
                    C.append(X[0])
                break

            # Sample a new centre proportional to distance
            r       = np.random.rand()
            new_idx = int(np.where(r < D / D[-1])[0][0])
            C.append(X[new_idx])

            # Re-assign labels: argmax of 2*c*x - c^2  ≡  argmin of (x-c)^2
            C_arr = np.array(C)
            scores = 2.0 * C_arr[:, None] * X[None, :] - C_arr[:, None] ** 2
            L      = np.argmax(scores, axis=0)

        break   # mirrors MATLAB's iter<1 loop limit

    C_arr = np.sort(np.array(C))
    return L, C_arr
