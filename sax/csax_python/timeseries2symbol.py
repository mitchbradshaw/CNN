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
# Copyright (c) 2003, Eamonn Keogh, Jessica Lin, Stefano Lonardi, Pranav Patel, Li Wei.
# All rights reserved.

import numpy as np
from .ts_paa import ts_paa


def timeseries2symbol(data, N, n, cutlines, normalize=True, NR_opt=2):
    """
    Convert a time series to a sequence of SAX symbols.

    Parameters
    ----------
    data      : array-like  — raw time series
    N         : int         — sliding window length (use len(data) for no sliding)
    n         : int         — number of PAA segments (symbols per window)
    cutlines  : array-like  — breakpoint boundaries between symbols
    normalize : bool        — z-normalise each subsequence before symbolising
    NR_opt    : int         — numerosity reduction option:
                              1 = none (record every window)
                              2 = skip if identical to previous (default)
                              3 = skip if mindist to previous == 0
                              other = skip if non-monotone AND mindist > 0

    Returns
    -------
    symbolic_data : np.ndarray, shape (num_recorded, n) — integer symbol arrays
    pointers      : np.ndarray, shape (num_recorded,)   — start index of each recorded window
    """
    data     = np.asarray(data, dtype=float).ravel()
    cutlines = np.asarray(cutlines, dtype=float).ravel()

    norm_thresh  = 0.001
    data_len     = len(data)
    num_windows  = data_len - (N - 1)

    symbolic_rows = []
    pointer_list  = []

    # Sentinel: initialise "last recorded" to something that won't match a real string
    last_string = np.full(n, -1, dtype=int)

    for i in range(num_windows):
        sub = data[i: i + N].copy()

        if normalize:
            mu, sigma = sub.mean(), sub.std()
            if sigma > norm_thresh:
                sub = (sub - mu) / sigma
            else:
                sub = sub - mu

        paa            = ts_paa(sub, n)
        current_string = _map_to_string(paa, cutlines)

        if NR_opt == 1:
            # No numerosity reduction
            symbolic_rows.append(current_string)
            pointer_list.append(i)

        elif NR_opt == 2:
            # Record only if different from previous
            if not np.array_equal(current_string, last_string):
                symbolic_rows.append(current_string)
                pointer_list.append(i)
                last_string = current_string

        elif NR_opt == 3:
            # Record only if mindist to previous > 0
            if not np.array_equal(current_string, last_string):
                if np.any(np.abs(last_string - current_string) > 1):
                    symbolic_rows.append(current_string)
                    pointer_list.append(i)
                    last_string = current_string
            # Always record the very first window
            if i == 0 and not pointer_list:
                symbolic_rows.append(current_string)
                pointer_list.append(i)
                last_string = current_string

        else:
            # Advanced: non-monotone AND mindist > 0
            if not np.array_equal(current_string, last_string):
                diffs = np.diff(current_string)
                is_monotone = np.all(diffs >= 0) or np.all(diffs <= 0)
                if np.any(np.abs(last_string - current_string) > 1) and not is_monotone:
                    symbolic_rows.append(current_string)
                    pointer_list.append(i)
                    last_string = current_string

    if not symbolic_rows:
        return np.empty((0, n), dtype=int), np.empty(0, dtype=int)

    return np.array(symbolic_rows, dtype=int), np.array(pointer_list, dtype=int)


# ── Private helper ────────────────────────────────────────────────────────────

def _map_to_string(paa, cutlines):
    """Map each PAA value to a symbol index (1-based, matching MATLAB)."""
    cut_points = np.concatenate([[-np.inf], cutlines])
    # Count how many cut_points are <= each PAA value
    return np.sum(cut_points[:, None] <= paa[None, :], axis=0).astype(int)
