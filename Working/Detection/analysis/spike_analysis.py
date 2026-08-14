import numpy as np
import matplotlib.pyplot as plt

def spike_detection_v1(x, width=20, delta=0.01, d=30):
    """
    Spike detection algorithm (Adamatzky 2023).

    For each sample x_i the neighbourhood average is computed as:
        a_i = (4·w)^{-1} · Σ_{i−2w ≤ j ≤ i+2w} x_j

    Index i is a candidate spike if  |x_i| − |a_i| > δ.
    Candidates are then filtered: any spike within d samples of a
    preceding confirmed spike is discarded (refractory-period filter).

    Default parameters for S. commune: w=20, δ=0.01, d=30.

    Parameters
    ----------
    x     : array-like   Raw signal.
    width : int          Neighbourhood half-width w.  Default 20.
    delta : float        Detection threshold δ.  Default 0.01.
    d     : int          Minimum inter-spike distance in samples.  Default 30.

    Returns
    -------
    spike_indices : np.ndarray   Sorted array of spike sample indices.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)

    # ── Step 1: candidate detection ───────────────────────────────────────────
    candidates = []
    for i in range(n):
        j_min = max(0,     i - 2 * width)
        j_max = min(n - 1, i + 2 * width)           # inclusive upper bound
        a_i = x[j_min : j_max + 1].sum() / (4 * width)

        if abs(x[i]) - abs(a_i) > delta:
            candidates.append(i)

    # ── Step 2: refractory-period filter (remove spikes within d of a prior spike)
    if not candidates:
        return np.array([], dtype=int)

    filtered = [candidates[0]]
    for idx in candidates[1:]:
        if idx - filtered[-1] >= d:
            filtered.append(idx)

    return np.array(filtered, dtype=int)

def compute_spike_statistics(x,spikelocs):
    """
    Function to compute some statistics about the spikes inside a sequence x

    """

    # -- Average duration of spike (median, std)

    # -- Average amplitude of spike (median, std)

    # -- Average distance between spikes (median, std)
    
