# Copyright and terms of use (DO NOT REMOVE):
# The code is made freely available for non-commercial uses only, provided that the copyright
# header in each file not be removed, and suitable citation(s) (see below) be made for papers
# published based on the code.
#
#   Lin, J., Keogh, E., Lonardi, S. & Chiu, B.
#   "A Symbolic Representation of Time Series, with Implications for Streaming Algorithms."
#   In proceedings of the 8th ACM SIGMOD Workshop on Research Issues in Data Mining and
#   Knowledge Discovery. San Diego, CA. June 13, 2003.
#
#   Lin, J., Keogh, E., Patel, P. & Lonardi, S.
#   "Finding Motifs in Time Series". In proceedings of the 2nd Workshop on Temporal Data Mining,
#   at the 8th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining.
#   Edmonton, Alberta, Canada. July 23-26, 2002
#
# Copyright (c) 2003, Eamonn Keogh, Jessica Lin, Stefano Lonardi, Pranav Patel, Li Wei.
# All rights reserved.

import numpy as np


def ts_paa(data, n):
    """
    Compute the Piecewise Aggregate Approximation (PAA) of a time series.

    Parameters
    ----------
    data : array-like  — 1-D time series
    n    : int         — number of PAA segments

    Returns
    -------
    paa : np.ndarray, shape (n,)
    """
    data = np.asarray(data, dtype=float).ravel()
    N = len(data)

    if N == n:
        return data.copy()

    if N % n != 0:
        # Fractional PAA: replicate rows (column-major reshape, matching MATLAB)
        temp = np.tile(data, (n, 1))               # (n, N)
        expanded = temp.ravel(order='F')            # (N*n,) column-major unravel
        paa = expanded.reshape(N, n, order='F').mean(axis=0)
    else:
        win_size = N // n
        # MATLAB: reshape(data, win_size, n) fills column-by-column → groups of win_size
        paa = data.reshape(n, win_size).mean(axis=1)

    return paa
