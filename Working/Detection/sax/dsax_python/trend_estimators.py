# Per-segment trend estimators for dSAX.
#
# Every estimator here answers the SAME question in the SAME unit:
#
#     "how much did the signal rise across this whole segment?"
#
# not "what is the slope per sample". That choice is the single most
# important constraint in this module, and it is worth spelling out why,
# because the natural implementation gets it wrong.
#
# An OLS fit naturally yields a slope in units of amplitude-per-SAMPLE.
# `endpoints` naturally yields amplitude-per-SEGMENT. If the two were left
# in their natural units, then swapping `trend_estimator="endpoints"` for
# `trend_estimator="ols_slope"` would silently rescale every delta by a
# factor of `sps - 1` — so an `absolute_threshold` tuned for one estimator
# would be off by two orders of magnitude for the other at sps=100, and a
# `learned` threshold would appear to "work" while quietly encoding a
# different physical quantity. Worse, `samples_per_symbol` would then leak
# into the delta scale, so the same recording at the same seconds-per-symbol
# but a different sampling rate would need a different threshold.
#
# So every estimator multiplies through to rise-across-segment:
#   - `endpoints` / `robust_endpoints` are already in that unit;
#   - `ols_slope` / `theil_sen` are slope-per-sample x (sps - 1), which is
#     the fitted line's rise from the first to the last sample index.
#
# `(sps - 1)` and not `sps`: the segment spans sample indices 0 .. sps-1, so
# the fitted line's rise between its own first and last sample is
# slope * (sps - 1). Using `sps` would make `ols_slope` disagree with
# `endpoints` on a noiseless ramp by a factor of sps/(sps-1) — small, but it
# would break the exact-string engineered tests and the "estimators are
# interchangeable" property this module exists to provide.
#
# Prior art for the estimators themselves is cited in `dsax.py`'s module
# docstring; nothing here is novel. `endpoints` is SAX-TD's trend factor
# (Sun et al. 2014); `ols_slope` is 1d-SAX's slope channel (Malinowski et
# al. 2013); `theil_sen` is the standard robust-regression substitute.

import numpy as np

TREND_ESTIMATORS = ("endpoints", "robust_endpoints", "ols_slope", "theil_sen")

# Above this segment length, `theil_sen` subsamples before fitting.
# theilslopes is O(sps^2) in pairwise comparisons; at sps=1000 that is 5e5
# pairs PER SEGMENT, which turns a 3000-segment encoding into minutes. 200
# points is 2e4 pairs, and the slope estimate of a 200-point even subsample
# of a smooth segment is indistinguishable from the full fit at the
# precision a 3-symbol quantiser cares about.
_THEIL_SEN_MAX_POINTS = 200


def _segment_matrix(data, n_seg, sps):
    """Reshape the (already trimmed) series into `(n_seg, sps)`.

    Segment `i` is `data[i*sps : (i+1)*sps]`, matching `ts_paa`'s
    contiguous blocking exactly — dSAX must segment identically to PAA or
    `details["paa"]` would describe different windows from
    `details["deltas"]`, and the TVA-style value+trend combination the
    `paa` key exists to enable would be silently misaligned.
    """
    data = np.asarray(data, dtype=float).ravel()
    return data[: n_seg * sps].reshape(n_seg, sps)


def _validate(n_seg, sps):
    """Both failure modes raise rather than degrade, because both mean the
    caller's segmentation is wrong in a way no sensible default can rescue:
    a one-sample segment has no slope at all (any value returned would be
    fabricated), and a one-segment string is not a string."""
    if sps < 2:
        raise ValueError(
            f"dSAX needs at least 2 samples per segment to define a trend, got sps={sps}. "
            "Increase seconds_per_symbol / samples_per_symbol, or lower dim_ratio."
        )
    if n_seg < 2:
        raise ValueError(
            f"dSAX needs at least 2 segments to produce a string, got n_seg={n_seg}. "
            "Decrease seconds_per_symbol / samples_per_symbol, or raise dim_ratio."
        )


def endpoints_delta(data, n_seg, sps):
    """`seg[-1] - seg[0]` — SAX-TD's trend factor (Sun et al. 2014).

    Cheapest and exactly faithful to the cited method, but it throws away
    every sample in between, so its variance under additive noise is
    2*sigma^2 regardless of how long the segment is. `ols_slope` is the
    default for precisely that reason; see test 13 in
    `tests/test_dsax_engineered.py`, which measures the difference.
    """
    _validate(n_seg, sps)
    seg = _segment_matrix(data, n_seg, sps)
    return seg[:, -1] - seg[:, 0]


def robust_endpoints_delta(data, n_seg, sps, endpoint_k=1):
    """`median(seg[-k:]) - median(seg[:k])`.

    `endpoint_k` is clipped to `sps // 2` so the head and tail windows can
    never overlap — an overlapping pair would make a pure ramp's delta
    shrink toward zero, which is a silent wrong answer rather than an
    error, so it is clipped rather than raised on.

    At `k == 1` this is bit-identical to `endpoints_delta` (the median of
    a single element is that element, exactly, with no arithmetic), which
    is asserted in the engineered tests so the two can never drift apart.
    """
    _validate(n_seg, sps)
    k = max(1, int(endpoint_k))
    k = min(k, sps // 2)
    seg = _segment_matrix(data, n_seg, sps)
    if k == 1:
        # Deliberately not `np.median(seg[:, :1], axis=1)`: median of one
        # element is a no-op mathematically, but it still routes through a
        # sort and a float division by 1, and "bit-identical to endpoints"
        # is a property this module promises. Take the element itself.
        return seg[:, -1] - seg[:, 0]
    return np.median(seg[:, -k:], axis=1) - np.median(seg[:, :k], axis=1)


def ols_slope_per_sample(data, n_seg, sps):
    """Least-squares slope of each segment against sample index, in
    amplitude-per-SAMPLE. `ols_slope_delta` is what dSAX consumes; this is
    exposed separately because `details["seg_slope"]` reports the raw
    per-sample slope (useful for drawing the fitted line in panel 1 of
    `plot_trend_encoding`, where the x axis is samples, not segments).

    Closed form, vectorised over all segments at once — the design regressor
    is the same `0..sps-1` for every segment, so `Sxx` is a scalar computed
    once and the whole fit collapses to one matrix-vector product. A Python
    loop over segments here would dominate the runtime of the entire
    encoder at the segment counts this repo uses (thousands).
    """
    _validate(n_seg, sps)
    seg = _segment_matrix(data, n_seg, sps)
    idx = np.arange(sps, dtype=float)
    idx_centred = idx - idx.mean()
    # Sxx = sum((i - ibar)^2), identical for every segment.
    sxx = float(idx_centred @ idx_centred)
    # sum((i - ibar) * y_i) needs no y-centring: sum(i - ibar) == 0, so the
    # y mean cancels out of the cross-product exactly.
    sxy = seg @ idx_centred
    return sxy / sxx


def ols_slope_delta(data, n_seg, sps):
    """OLS slope expressed as rise-across-segment. The dSAX default."""
    return ols_slope_per_sample(data, n_seg, sps) * (sps - 1)


def theil_sen_slope_per_sample(data, n_seg, sps):
    """Theil-Sen (median of pairwise slopes) per sample, via
    `scipy.stats.theilslopes`.

    Returns `(slopes, subsampled)`. `subsampled` is True when segments were
    thinned to `_THEIL_SEN_MAX_POINTS` evenly spaced samples before fitting
    — reported through `details["theil_sen_subsampled"]` so a result is
    never quietly an approximation of a different computation than the one
    named. The subsample keeps the first and last sample (`np.linspace`
    endpoints), so the fitted span still covers the full segment and the
    x (sps - 1) rescaling below stays correct.

    Unavoidably a Python loop: `theilslopes` is scalar-in, scalar-out. This
    is why it is not the default despite being the most robust of the four.
    """
    _validate(n_seg, sps)
    from scipy.stats import theilslopes

    seg = _segment_matrix(data, n_seg, sps)
    idx = np.arange(sps, dtype=float)

    subsampled = sps > _THEIL_SEN_MAX_POINTS
    if subsampled:
        take = np.unique(np.linspace(0, sps - 1, _THEIL_SEN_MAX_POINTS).round().astype(int))
        seg = seg[:, take]
        idx = idx[take]

    slopes = np.empty(n_seg, dtype=float)
    for i in range(n_seg):
        slopes[i] = theilslopes(seg[i], idx)[0]
    return slopes, subsampled


def theil_sen_delta(data, n_seg, sps):
    """Theil-Sen slope as rise-across-segment. Returns `(deltas, subsampled)`."""
    slopes, subsampled = theil_sen_slope_per_sample(data, n_seg, sps)
    return slopes * (sps - 1), subsampled


def compute_deltas(data, n_seg, sps, trend_estimator="ols_slope", endpoint_k=1):
    """Dispatch to one estimator and return `(deltas, seg_slope, subsampled)`.

    `deltas` is rise-across-segment (the quantised quantity);
    `seg_slope` is the same trend expressed per sample, so panel 1 of the
    plot can draw it against a sample axis without re-deriving it, and so
    `details["seg_slope"]` means the same thing whichever estimator ran.
    For the two endpoint estimators there is no fitted slope as such, so
    `seg_slope` is the secant slope `delta / (sps - 1)` — the line through
    the two points the estimator actually compared, which is the honest
    per-sample reading of what it measured.
    """
    if trend_estimator == "endpoints":
        deltas = endpoints_delta(data, n_seg, sps)
        return deltas, deltas / (sps - 1), False
    if trend_estimator == "robust_endpoints":
        deltas = robust_endpoints_delta(data, n_seg, sps, endpoint_k=endpoint_k)
        return deltas, deltas / (sps - 1), False
    if trend_estimator == "ols_slope":
        slope = ols_slope_per_sample(data, n_seg, sps)
        return slope * (sps - 1), slope, False
    if trend_estimator == "theil_sen":
        slope, subsampled = theil_sen_slope_per_sample(data, n_seg, sps)
        return slope * (sps - 1), slope, subsampled
    raise ValueError(
        f"Unknown trend_estimator {trend_estimator!r} — must be one of {TREND_ESTIMATORS}"
    )


def surrogate_same_halfwidth(data, samples_per_symbol, trend_estimator="ols_slope",
                             n_surrogates=50, alpha=0.95, random_state=None):
    """Half-width of the delta distribution under a no-trend null, from
    phase-randomised surrogates. Not called by dsax() — dsax() must stay
    deterministic; pass the result in as min_same_halfwidth if wanted.

    The question this answers is the one Lloyd-Max cannot: "how big a
    per-segment rise would this signal produce even if nothing were
    happening?". Lloyd-Max minimises squared quantisation error against the
    observed delta density, which is an entirely different objective — on a
    pure-noise signal it will happily split the noise into DOWN/SAME/UP
    thirds and report a perfectly balanced, perfectly meaningless encoding.
    A noise-floor threshold instead says "call it SAME unless it exceeds
    what noise alone does `alpha` of the time".

    Phase randomisation (Theiler et al.'s standard surrogate) preserves the
    magnitude spectrum — hence the autocorrelation, hence the noise colour,
    which matters a great deal here: 1/f drift produces far larger
    segment-scale deltas than white noise of the same variance, and a
    white-noise-derived threshold would badly under-estimate the floor on a
    fungal recording. It destroys the phase relationships that make a
    coherent trend, so any delta a surrogate produces is by construction
    "trend that isn't there".

    Note the null this tests is "no trend BEYOND the linear-Gaussian
    process with this spectrum". A signal whose slow drift IS the spectrum
    (test 9's noise-plus-ramp) will yield a large half-width, correctly
    reporting that its own drift makes segment-scale rises unremarkable.
    That is a real property of the null, not a defect, but it is why this
    is offered rather than imposed.

    Parameters
    ----------
    data               : array-like - the series to draw the null from
    samples_per_symbol : int        - segment length to measure deltas over
    trend_estimator    : str        - must match what dsax() will use, or
                                      the half-width is in a different unit
    n_surrogates       : int
    alpha              : float      - quantile of |delta| to return
    random_state       : int or np.random.Generator or None

    Returns
    -------
    float - the `alpha` quantile of |delta| pooled across all surrogates,
        in the units of `data` (so: raw units if you pass raw data,
        normalised units if you pass normalised data - pass whichever
        domain your `min_same_halfwidth` is meant to be in).
    """
    data = np.asarray(data, dtype=float).ravel()
    sps = int(samples_per_symbol)
    n_seg = len(data) // sps
    _validate(n_seg, sps)

    rng = (random_state if isinstance(random_state, np.random.Generator)
           else np.random.default_rng(random_state))

    # Trim to an even length so the rfft phase-randomisation below has a
    # clean Nyquist bin to leave alone.
    x = data[: n_seg * sps]
    x = x - x.mean()
    n = len(x)
    spectrum = np.fft.rfft(x)
    magnitude = np.abs(spectrum)

    pooled = []
    for _ in range(n_surrogates):
        # Randomise every phase except DC (index 0) and, for even n, the
        # Nyquist bin (last index) — both are real-valued in a real
        # signal's rfft, so giving them a phase would make the inverse
        # transform complex and force a lossy discard of the imaginary part.
        phases = rng.uniform(0.0, 2.0 * np.pi, size=len(spectrum))
        phases[0] = 0.0
        if n % 2 == 0:
            phases[-1] = 0.0
        surrogate = np.fft.irfft(magnitude * np.exp(1j * phases), n=n)
        deltas, _, _ = compute_deltas(surrogate, n_seg, sps, trend_estimator=trend_estimator)
        pooled.append(np.abs(deltas))

    return float(np.quantile(np.concatenate(pooled), alpha))
