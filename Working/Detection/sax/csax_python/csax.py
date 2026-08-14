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
from scipy.stats import norm

from .ts_paa                        import ts_paa
from .normal_cutlines               import normal_cutlines
from .timeseries2symbol             import timeseries2symbol
from .meanshift.hg_meanshift_cluster import hg_meanshift_cluster

_NORM_THRESH = 0.001  # matches timeseries2symbol's own normalisation threshold


def csax(data, training_len, dim_ratio, normalize=True, return_details=False):
    """
    cSAX symbolic representation (non-overlapping windows).

    Parameters
    ----------
    data         : array-like — full time series
    training_len : int        — number of samples used for density estimation
    dim_ratio    : float      — dimensionality reduction ratio (e.g. 1/3 → every 3 samples → 1 symbol)
    normalize    : bool       — z-normalise the dataset as a whole before processing
    return_details : bool     — if True, return `(str_out, details)` instead of
        just `str_out` (default False: byte-identical to every existing caller).
        See the module-level note below for what `details` contains and why.

    Returns
    -------
    str_out : np.ndarray, shape (data_nseg,) — cSAX symbolic sequence (0-based symbol indices)
    details : dict, only when return_details=True — see below.

    Notes on `return_details` (2026-08, UI encoding-inspection view)
    ------------------------------------------------------------------
    `timeseries2symbol` is called here with `N=data_len` — a single window
    spanning the entire (already once-normalised) `data` — so internally it
    re-derives `mu, sigma = sub.mean(), sub.std()` on that single window and
    normalises AGAIN before computing the PAA it actually quantises
    (`_map_to_string`). That second, internal normalisation is a real,
    distinct affine transform (not a no-op — the once-normalised data's mean
    isn't exactly 0 nor its std exactly 1 after trimming), so the PAA that
    determined every symbol is NOT exactly `training_paa` above (which is
    only used to learn the cutlines, from the training set's PAA under the
    FIRST normalisation only). `details["paa"]` replicates that inner
    normalisation explicitly, matching `timeseries2symbol`'s single-window
    path exactly, so it is provably the same array `_map_to_string` used —
    verified in tests/test_sax_details.py by re-quantising it against
    `details["cutlines"]` by hand and reproducing `str_out` exactly.
    `details["norm_mean"]`/`["norm_std"]` are the COMPOSED constants of both
    normalisation steps, so `raw = value * norm_std + norm_mean` undoes the
    full chain in one step for `paa`/`cutlines` alike.
    """
    data = np.asarray(data, dtype=float).ravel()
    original_len = len(data)

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
    mu1, sigma1 = 0.0, 1.0
    if normalize:
        mu1 = data.mean()
        if np.std(training_set) < 0.001:
            data         = data         - data.mean()
            training_set = training_set - training_set.mean()
        else:
            sigma1       = data.std()
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

    fallback_used = clust_cent.shape[1] <= 1
    if not fallback_used:
        centres  = np.sort(clust_cent[0])           # ensure sorted
        cutlines = centres[:-1] + np.diff(centres) / 2
        representatives = centres
    else:
        # Fallback to standard SAX
        cutlines = normal_cutlines(10)
        # No cluster centres exist in this branch — the natural stand-in
        # per equiprobable Gaussian bin is its median under N(0,1), the
        # same distribution `normal_cutlines` assumes.
        representatives = norm.ppf((np.arange(10) + 0.5) / 10.0)

    # Discretise with learned cutlines (NR_opt=1: no numerosity reduction)
    sym, _ = timeseries2symbol(data, data_len, data_nseg, cutlines,
                               normalize=normalize, NR_opt=1)

    # sym is (1, data_nseg) with 1-based indices; convert to 0-based 1-D array
    str_out = sym.ravel() - 1

    if not return_details:
        return str_out

    # ── Replicate timeseries2symbol's single-window (N=data_len) inner
    # normalisation to recover the EXACT PAA it quantised — see docstring.
    sub = data.copy()
    mu2, sigma2 = 0.0, 1.0
    if normalize:
        mu2 = sub.mean()
        sig = sub.std()
        if sig > _NORM_THRESH:
            sigma2 = sig
            sub = (sub - mu2) / sigma2
        else:
            sub = sub - mu2
    paa = ts_paa(sub, data_nseg)

    # Composed normalisation constants: raw = value*norm_std + norm_mean
    # undoes BOTH steps (outer z-normalisation, then timeseries2symbol's
    # inner single-window renormalisation) in one shot.
    if normalize:
        norm_std = sigma1 * sigma2
        norm_mean = mu2 * sigma1 + mu1
    else:
        norm_std = None
        norm_mean = None

    paa_raw = paa if norm_std is None else paa * norm_std + norm_mean
    cutlines_raw = cutlines if norm_std is None else np.asarray(cutlines) * norm_std + norm_mean
    # `representatives` live in the ONCE-normalised domain (Mean-Shift ran
    # on `training_paa`, computed before `timeseries2symbol`'s inner
    # renormalisation) -- a DIFFERENT intermediate domain from `paa`/
    # `cutlines` above, so undoing only the first normalisation step
    # (mu1, sigma1), not the composed one, is what maps them back to raw
    # amplitude units correctly.
    representatives_raw = (
        np.asarray(representatives, dtype=float) if not normalize
        else np.asarray(representatives, dtype=float) * sigma1 + mu1
    )

    details = {
        "samples_per_symbol": data_len // data_nseg,
        "n_symbols": data_nseg,
        "data_len_trimmed": data_len,
        "n_trimmed": original_len - data_len,
        "paa": paa,
        "cutlines": np.asarray(cutlines, dtype=float),
        "representatives": np.asarray(representatives, dtype=float),
        "representatives_raw": representatives_raw,
        "alphabet_size": len(representatives),
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "fallback_used": fallback_used,
        "paa_raw": paa_raw,
        "cutlines_raw": cutlines_raw,
    }
    return str_out, details
