# dSAX (delta-SAX): a trend-symbolic representation.
#
# dSAX segments a series EXACTLY as PAA does, but encodes each segment by
# how much it rose or fell across the segment rather than by its mean,
# into an ordered alphabet whose middle symbol means "no meaningful
# change". For the default 3-symbol alphabet: 0 = DOWN, 1 = SAME, 2 = UP,
# 0-based and ascending, so `np.searchsorted(cutlines, delta, side="right")`
# produces the symbol directly — the same convention as csax/psax.
#
# ── This is not a novel method. What it reuses, and what differs ─────────
#
# Trend-symbolic time-series representations are a well-established family.
# The prior art this stands on:
#
#   [1] H. Esmael, A. Arnaout, R. K. Fruhwirth, G. Thonhauser,
#       "Multivariate Time Series Classification by Combining Trend-Based
#        and Value-Based Approximations" (TVA), ICCSA 2012.
#       Per-segment U/D/S trend symbols concatenated with SAX value
#       symbols. This is the closest antecedent to dSAX's alphabet — dSAX
#       is TVA's trend channel taken alone.
#
#   [2] Y. Sun, J. Li, J. Wang, X. Xia, "An improvement of symbolic
#       aggregate approximation distance measure for time series"
#       (SAX-TD), Neurocomputing 2014. Defines a trend factor from the
#       STARTING AND ENDING POINTS of each segment — that is exactly the
#       `endpoints` estimator in `trend_estimators.py`.
#
#   [3] S. Malinowski, T. Guyet, R. Quiniou, R. Tavenard, "1d-SAX: A Novel
#       Symbolic Representation for Time Series", IDA 2013. Quantises both
#       the per-segment mean AND the OLS slope. 1d-SAX is strictly more
#       informative than dSAX; dSAX is its slope channel alone, with a
#       learned zero-anchored alphabet instead of a Gaussian-prior one.
#       (`details["paa"]` is populated here precisely so that recovering
#       the full 1d-SAX/TVA value+trend pairing later costs nothing.)
#
#   [4] R. Agrawal, G. Psaila, E. L. Wimmers, M. Zait, "Querying Shapes of
#       Histories" (Shape Definition Language), VLDB 1995. The original
#       up/down/stable shape alphabet.
#
#   [5] K. Bountrogiannis, G. Tzagkarakis, P. Tsakalides, EUSIPCO 2020 and
#       IEEE TKDE 2022 — the cSAX/pSAX work already vendored in this repo.
#       dSAX reuses pSAX's Epanechnikov KDE + k-means++ + Lloyd-Max
#       machinery UNCHANGED (imported, not copied), applied to the DELTA
#       distribution instead of the PAA distribution.
#
# The contribution claimed here is narrow and should not be overstated
# anywhere: applying a data-adaptively quantised, ZERO-ANCHORED trend
# alphabet to fungal bio-electric recordings, so that a shared morphology
# vocabulary (sharkfin, rollinghill, ...) becomes regex-searchable over the
# symbol string. Nothing more.
#
# ── Why Lloyd-Max and not cSAX's Mean-Shift ──────────────────────────────
#
# cSAX learns its cutlines by Mean-Shift clustering the PAA and cutting
# midway between cluster centres. That works when the level distribution is
# multi-modal (two resting potentials, say). The DELTA distribution of a
# roughly stationary signal is not: it is one unimodal lump centred near
# zero. Mean-Shift would routinely return a single cluster, and cSAX's
# `while clust_cent.shape[1] < 2` loop would exhaust its multi_factor
# halving and take the fallback path — silently producing classic 10-symbol
# Gaussian SAX, which is not a trend encoding at all. Lloyd-Max has no such
# failure mode: it always yields exactly `alphabet_size` codewords, however
# unimodal the density. So `learned` mode is pSAX's machinery, deliberately,
# and Mean-Shift is not offered.
#
# ── Why dSAX does not call timeseries2symbol ─────────────────────────────
#
# csax/psax normalise TWICE — once here, then again inside
# `timeseries2symbol`'s single-window path — and their `details` code has to
# compose both affine transforms to report honest raw-unit values.
# dSAX computes its deltas and quantises them itself with one
# `np.searchsorted`, so there is exactly ONE normalisation step and no
# composition to get wrong. Do not "restore" the double-normalisation dance
# by routing dSAX through `timeseries2symbol`: it quantises segment MEANS,
# which is the wrong quantity.
#
# ── The delta conversion rule, which is NOT the PAA conversion rule ──────
#
# A delta is a DIFFERENCE, so an additive offset cancels out of it. If the
# normalisation was `x_norm = (x - mu) / sigma`, then:
#
#     delta_raw = delta_norm * sigma            # scale ONLY — no + mu
#     paa_raw   = paa_norm   * sigma + mu       # offset applies to LEVELS
#
# Getting this wrong produces deltas offset by the recording's DC level,
# which on a fungal electrode (tens of mV of standing potential against
# sub-mV excursions) is a factor-of-100 error that still looks plausible.
# `details["delta_scale"]` is the sigma-only constant and is the ONLY thing
# any delta-domain -> raw conversion may use, cutlines included.
# `tests/test_dsax.py` asserts the mean does not appear.

import os

import numpy as np

from Working.Detection.sax.csax_python.ts_paa import ts_paa
from Working.Detection.sax.psax_python.kde import epanechnikov_kde
from Working.Detection.sax.psax_python.kmeanspp import kmeanspp
from Working.Detection.sax.psax_python.lloydmax import lloydmax

from .trend_estimators import TREND_ESTIMATORS, compute_deltas

_NORM_THRESH = 0.001  # matches psax/csax's own normalisation threshold

THRESHOLD_MODES = ("learned", "absolute", "quantile")

SYMBOL_NAMES = {
    3: ("DOWN", "SAME", "UP"),
    5: ("DOWN2", "DOWN1", "SAME", "UP1", "UP2"),
}

# Single-character display letters per alphabet size. SEPARATE from
# `SYMBOL_NAMES` rather than derived from it, because the obvious
# derivation (first character of each name) works at k=3 and COLLIDES at
# k=5: DOWN2/DOWN1 both start "D" and UP1/UP2 both start "U", which would
# silently make the string ambiguous and every regex written against it
# wrong. Defined once here and consumed by `dsax_letters` and by the UI's
# `symbol_letters` resolver, so the string in the run panel, the string in
# the cached `.txt`, the strip's cell labels and the legend can never drift
# apart.
#
# k=5 scheme: lower case for the OUTER (stronger) bins, upper for the
# inner. Case therefore encodes magnitude and the letter encodes
# direction, so `[Dd]` matches any fall and `[Uu]` any rise, and a
# case-insensitive k=3 vocabulary pattern (`UD{3,}`) still matches at k=5
# without being rewritten.
#
# Only sizes with a genuinely meaningful mnemonic appear here. Everything
# else falls back to the repo-wide a/b/c convention rather than inventing
# a scheme nobody agreed: an even alphabet has no SAME bin at all (see
# `_symmetrise`), so a D/S/U-shaped mnemonic would be actively misleading
# there.
SYMBOL_LETTERS = {
    3: ("D", "S", "U"),
    5: ("d", "D", "S", "U", "u"),
}

# Relative tolerance below which the delta distribution counts as constant
# (a flat signal, or one whose only variation is float noise). Chosen at
# 1e-9 of the signal's amplitude scale: comfortably above float64 round-off
# accumulated by an OLS dot product over a few thousand samples (~1e-13
# relative at worst), and comfortably below any delta a real recording
# produces. See `_degenerate_cutlines`.
_DEGENERATE_REL = 1e-9

# Relative nudge used to restore strict ascent when symmetrisation or a
# degenerate density collapses two cutlines onto each other. Same reasoning
# as above: large enough to survive float64 comparison, small enough that it
# cannot move a symbol boundary past any real delta.
_ASCENT_EPS_REL = 1e-9


def _letter(i):
    """Duplicated from `Adapters._sax_common._letter` deliberately, not
    imported. `Working/` must not depend on `Adapters/` — the dependency
    runs the other way (adapters wrap Working functions), and importing
    upward would make this module unimportable from a bare `Working/`
    checkout on a compute node. `_sax_common._letter` itself carries the
    identical note about not importing `UI.plots.symbol_to_letter`. Keep
    all three in sync if either changes; each is 4 lines."""
    i = int(i)
    if i < 26:
        return chr(ord("a") + i)
    i -= 26
    return chr(ord("a") + i // 26) + chr(ord("a") + i % 26)


def dsax_letters(symbols, alphabet_size=3):
    """Render a symbol array as a searchable string.

    This is the payoff of the whole representation: once an encoding is a
    string, a morphology in the tag vocabulary becomes a regular
    expression. "sharkfin" — one sharp rise then a sustained decay — is
    `U D{3,}` once the SAME padding is stripped; "rollinghill" is
    `U{2,} S{1,} D{2,}`. That is a detector, written in one line, over an
    encoding that took no training data to build.

    For `alphabet_size == 3` the letters are D / S / U, which is what makes
    those patterns readable. For any other alphabet size there is no
    agreed mnemonic, so it falls back to the repo-wide a, b, c, ...
    convention (`_letter`) rather than inventing one per alphabet size —
    a regex written against `D2`/`D1` two-character symbols would not be a
    character-class regex at all, which defeats the purpose.
    """
    symbols = np.asarray(symbols, dtype=int).ravel()
    table = SYMBOL_LETTERS.get(int(alphabet_size))
    if table is not None:
        return "".join(table[s] if 0 <= s < len(table) else "?" for s in symbols)
    return "".join(_letter(s) for s in symbols)


# ── cutline construction ─────────────────────────────────────────────────

def _symmetrise(cutlines):
    """Fold the ascending cutlines onto their own mirror image:

        c'_j = (c_j - c_{m-1-j}) / 2        (m = len(cutlines) = k - 1)

    Delta space has a privileged origin that the PAA space of pSAX does
    not — zero means "no change", and it is the only value in the whole
    domain with an interpretation independent of the data. Unconstrained
    Lloyd-Max minimises squared error against the observed density and has
    no reason whatsoever to respect that origin; on a signal with a faint
    net drift it will happily shift the whole codebook off zero, so
    "SAME" would come to mean "rising at the average rate", and the
    encoding would silently stop being a trend encoding.

    Folding fixes that with no extra parameter and no extra assumption:
      - it is idempotent (folding an already-symmetric set changes nothing);
      - it preserves ascent, because `c_j` ascends and `-c_{m-1-j}` ascends;
      - for odd alphabet sizes (m even) it gives k=3 exactly `[-s, +s]`
        with `s = (c_1 - c_0)/2`;
      - for even alphabet sizes (m odd) the self-paired middle cutline
        j = (m-1)/2 lands EXACTLY on 0, which is the correct behaviour:
        an even alphabet has no SAME bin, only a boundary at zero.

    It does cost the MSE-optimality that Lloyd-Max was solving for. That
    trade is taken deliberately and is reported: `force_symmetric=False`
    keeps the raw cutlines, and `details["zero_symbol"]` then makes the
    asymmetry visible rather than silent. Asymmetric cutlines are
    scientifically interesting here — a fast-rise/slow-decay morphology
    SHOULD produce a skewed delta distribution — the requirement is only
    that the skew be measured, not accidental.
    """
    c = np.asarray(cutlines, dtype=float)
    return (c - c[::-1]) / 2.0


def _learned_cutlines(training_deltas, alphabet_size, npoints):
    """pSAX's quantiser, unchanged, run on deltas instead of PAA.

    The `npoints=min(training_len, 1000)` cap is inherited from `psax()`
    and kept for the same reason stated there: `epanechnikov_kde` builds an
    (npoints x n_samples) matrix, so passing the raw training length
    exhausts memory on long recordings (162710 x 16271 ~ 20 GB). It is not
    a tuning knob.
    """
    f, x = epanechnikov_kde(training_deltas, npoints=npoints)
    _, init_codewords = kmeanspp(training_deltas, alphabet_size)
    init_codewords = np.sort(init_codewords)
    codewords, cutlines = lloydmax(f, x, alphabet_size, init=init_codewords)
    return np.sort(np.asarray(codewords, dtype=float)), np.asarray(cutlines, dtype=float)


def _quantile_cutlines(training_deltas, alphabet_size, same_fraction):
    """Distribution-free cutlines straight off the empirical delta quantiles.

    Two different rules, because the k=3 case has a target that the general
    case does not:

      - k == 3: the caller states what fraction of segments should be
        called SAME, and the cutlines are placed to deliver exactly that.
        This is the mode to use when you know a priori how much of a
        recording is quiescent.
      - k  > 3: equiprobable bins — classic SAX's own idea (Gaussian
        equiprobable cutlines), applied to the delta distribution rather
        than assuming it is Gaussian. `same_fraction` has no meaning here
        and is ignored; forcing it into an even split would make the two
        branches disagree about what the parameter does.
    """
    d = np.asarray(training_deltas, dtype=float)
    if alphabet_size == 3:
        lo = float(np.quantile(d, (1.0 - same_fraction) / 2.0))
        hi = float(np.quantile(d, (1.0 + same_fraction) / 2.0))
        return np.array([lo, hi], dtype=float)
    qs = np.arange(1, alphabet_size) / float(alphabet_size)
    return np.quantile(d, qs).astype(float)


def _all_same_cutlines(deltas, alphabet_size, tol):
    """Cutlines for a delta distribution that is entirely AT zero.

    A constant input must not raise — it is a completely legitimate thing
    to encode (a dead electrode, a saturated channel, a quiescent hour),
    and the honest answer is "nothing changed anywhere", i.e. all-SAME.
    `csax` has an analogous fallback for Mean-Shift finding fewer than two
    clusters; the spirit is mirrored, including flagging it loudly rather
    than letting a caller mistake the result for a real quantisation.

    The band is placed at twice the largest observed |delta| (floored at
    `tol`) so that every delta provably lands strictly inside it, rather
    than at some arbitrary epsilon that float round-off could straddle.

    Note this can only guarantee all-SAME for ODD alphabet sizes. An even
    alphabet has a cutline AT zero and therefore no SAME bin at all, so
    round-off deltas of either sign land either side of it. That is
    inherent to even alphabets, not a defect here.
    """
    half = 2.0 * max(float(np.max(np.abs(deltas))) if deltas.size else 0.0, tol)
    m = alphabet_size - 1
    if m == 1:
        return np.array([0.0], dtype=float)
    return np.linspace(-half, half, m).astype(float)


def _flat_nonzero_cutlines(deltas, alphabet_size):
    """Cutlines for deltas that have no spread but are not zero — a
    perfectly noiseless ramp or triangle wave, where every segment rises by
    exactly the same amount.

    This case is separated from `_all_same_cutlines` because the two want
    OPPOSITE answers, and conflating them was an actual bug during
    development: a clean +1-per-segment ramp has `ptp(deltas) == 0`, hits
    the no-spread branch, and — if that branch always builds a band around
    zero wide enough to swallow every delta — gets encoded as all-SAME.
    A monotonic ramp reported as "no change" is the worst possible output
    of a trend encoder.

    The learning modes genuinely have nothing to learn from a point mass:
    Lloyd-Max cannot separate identical samples and the empirical quantiles
    all coincide. But the zero anchor supplies the missing information for
    free — the deltas sit a known distance from the origin, on a known
    side — so the cutlines are placed to span [-|v|, +|v|] with the point
    mass landing in the extreme bin on its own side. Equal-width, exactly
    symmetric, strictly ascending, and it makes a ramp read as all-UP and
    a decay as all-DOWN, which is the only defensible reading.

    Still flagged `cutlines_degenerate=True`: the bin widths here are an
    artefact of the anchor, not of any density the data supports.
    """
    v = abs(float(np.mean(deltas)))
    m = alphabet_size - 1
    # Interior points of an (m+2)-point grid across [-v, +v]: gives m
    # ascending cutlines strictly inside the range, so +v lands in bin m
    # and -v in bin 0.
    return np.linspace(-v, v, m + 2)[1:-1].astype(float)


def _enforce_ascending(cutlines, deltas):
    """`np.searchsorted` requires a sorted array and gives nonsense bins for
    repeated values, so strict ascent is a hard precondition, not a nicety.

    Returns `(cutlines, degenerate)`. `degenerate` is True whenever a nudge
    was needed, and is surfaced as `details["cutlines_degenerate"]` — a
    caller must be able to tell "the quantiser resolved k distinct levels"
    from "two levels were forced apart by an epsilon and one of these bins
    is empty by construction".
    """
    c = np.asarray(cutlines, dtype=float).copy()
    if c.size < 2:
        return c, False
    scale = max(float(np.max(np.abs(c))), float(np.std(deltas)), 1.0)
    eps = _ASCENT_EPS_REL * scale
    degenerate = False
    for j in range(1, len(c)):
        if c[j] <= c[j - 1]:
            c[j] = c[j - 1] + eps
            degenerate = True
    return c, degenerate


def _apply_min_same_halfwidth(cutlines, halfwidth, alphabet_size):
    """Widen the zero-containing bin so it spans at least [-w, +w].

    This is the injection point for a noise-floor estimate: Lloyd-Max
    answers "where do the cutlines minimise squared quantisation error",
    which is a completely different question from "how big a rise could
    noise alone have produced". On a pure-noise segment the MSE-optimal
    answer is to split the noise into three roughly equal bins and report a
    beautifully balanced, entirely meaningless encoding.
    `trend_estimators.surrogate_same_halfwidth` computes the noise-floor
    answer; passing it in here is how the two get reconciled.

    Deliberately a floor and not an override — if the learned SAME band is
    already wider than the noise floor, the data is saying the quiescent
    range is genuinely wider than noise, and overriding that downward would
    throw information away. `run_dsax_validation.py` measures how far apart
    the two answers actually sit.

    Even alphabet sizes have no zero-containing bin to widen (there is a
    cutline AT zero), so this is a no-op there and reports so.
    Returns `(cutlines, applied)`.
    """
    c = np.asarray(cutlines, dtype=float).copy()
    if halfwidth is None or alphabet_size % 2 == 0 or c.size < 2:
        return c, False
    w = abs(float(halfwidth))
    mid_hi = c.size // 2          # index of the SAME bin's upper cutline
    mid_lo = mid_hi - 1           # ... and its lower one
    if c[mid_lo] > -w:
        c[mid_lo] = -w
    if c[mid_hi] < w:
        c[mid_hi] = w
    # Widening the middle can now collide with its neighbours. Push them
    # out rather than clipping the middle back: the caller asked for a
    # minimum SAME width and that request wins over the outer boundaries,
    # which have no comparable justification behind them.
    for j in range(mid_lo - 1, -1, -1):
        if c[j] >= c[j + 1]:
            c[j] = c[j + 1] - abs(c[j + 1]) * _ASCENT_EPS_REL - _ASCENT_EPS_REL
    for j in range(mid_hi + 1, c.size):
        if c[j] <= c[j - 1]:
            c[j] = c[j - 1] + abs(c[j - 1]) * _ASCENT_EPS_REL + _ASCENT_EPS_REL
    return c, True


def _bin_representatives(deltas, cutlines, alphabet_size):
    """A stand-in codeword per bin for the modes that do not produce one.

    `learned` mode gets real Lloyd-Max codewords. `absolute`/`quantile`
    have no codebook, but `details["representatives"]` is part of the
    shared contract that consumers (the encoding view's legend, any future
    reconstruction) rely on, so something honest has to fill it. The
    per-bin MEDIAN of the observed deltas is the right stand-in: it is the
    value that actually typifies segments given that symbol, and unlike the
    bin midpoint it is defined for the two unbounded outer bins.

    An empty bin has no median, so it falls back to the bin midpoint where
    both edges are finite, and to the finite edge offset by half a typical
    bin width where it is not.
    """
    d = np.asarray(deltas, dtype=float)
    c = np.asarray(cutlines, dtype=float)
    assign = np.searchsorted(c, d, side="right")
    widths = np.diff(c)
    typical = float(np.mean(widths)) if widths.size else max(float(np.max(np.abs(c))) * 2.0, 1.0)
    reps = np.empty(alphabet_size, dtype=float)
    for s in range(alphabet_size):
        members = d[assign == s]
        if members.size:
            reps[s] = float(np.median(members))
        elif s == 0:
            reps[s] = c[0] - typical / 2.0
        elif s == alphabet_size - 1:
            reps[s] = c[-1] + typical / 2.0
        else:
            reps[s] = (c[s - 1] + c[s]) / 2.0
    return reps


# ── the encoder ──────────────────────────────────────────────────────────

def dsax(data, training_len, dim_ratio, alphabet_size=3,
         trend_estimator="ols_slope", threshold_mode="learned",
         endpoint_k=1, absolute_threshold=None, same_fraction=0.5,
         min_same_halfwidth=None, force_symmetric=True,
         normalize=True, return_details=False):
    """
    dSAX symbolic representation (non-overlapping windows).

    Segments identically to `psax()`/`csax()` — same `data_nseg =
    floor(dim_ratio * data_len)`, same trim to an exact multiple — so
    `Adapters._sax_common.segment_plan()` round-trips against dSAX exactly
    as it does against pSAX (asserted in `tests/test_dsax.py`). What
    differs is what each segment is reduced to: its rise, not its mean.

    Parameters
    ----------
    data          : array-like — full time series
    training_len  : int        — samples used to learn the cutlines
    dim_ratio     : float      — dimensionality reduction ratio
                                 (e.g. 1/3 -> every 3 samples -> 1 symbol)
    alphabet_size : int        — number of symbols; 3 (DOWN/SAME/UP) is the
                                 designed case, odd sizes keep a SAME bin
    trend_estimator : str      — one of `trend_estimators.TREND_ESTIMATORS`;
                                 all are normalised to rise-across-segment,
                                 so switching does not require re-tuning a
                                 threshold (see that module's header)
    threshold_mode : str       — "learned" (KDE + Lloyd-Max, the default),
                                 "absolute" (a stated raw-unit threshold),
                                 or "quantile"
    endpoint_k    : int        — window length for "robust_endpoints"
    absolute_threshold : float — raw signal units of RISE PER SEGMENT;
                                 required by, and only valid for,
                                 threshold_mode="absolute" at
                                 alphabet_size=3
    same_fraction : float      — target SAME occupancy for
                                 threshold_mode="quantile" at
                                 alphabet_size=3
    min_same_halfwidth : float — floor on the SAME band half-width, in the
                                 WORKING delta domain (normalised units
                                 when normalize=True, raw otherwise). The
                                 hook for a noise-floor estimate; see
                                 `trend_estimators.surrogate_same_halfwidth`
    force_symmetric : bool     — fold cutlines about zero (default True);
                                 see `_symmetrise` for why zero is
                                 privileged in delta space
    normalize     : bool       — z-normalise the dataset as a whole first
    return_details : bool      — if True return `(str_out, details)`

    Returns
    -------
    str_out : np.ndarray, shape (data_nseg,) — 0-based symbol indices,
        ascending in trend: 0 is the steepest fall, k-1 the steepest rise.
    details : dict, only when return_details=True — see the module
        docstring for the delta-vs-level raw-conversion rule, and §3.6 of
        `DSAX_IMPLEMENTATION_PROMPT.md` for the full key list.

    Determinism
    -----------
    `threshold_mode="learned"` consumes `np.random` via `kmeanspp`, exactly
    as `psax()` does. Seed `np.random` before the call if you need
    reproducibility, and reseed identically before any pair of calls being
    compared — the existing SAX tests follow the same discipline.
    `"absolute"` and `"quantile"` touch no RNG at all, which is why the
    engineered exact-string tests use `"absolute"`.
    """
    # ── validate the enums BEFORE doing any work, so a typo fails fast and
    # cheaply rather than after a KDE on a 160k-sample recording.
    if trend_estimator not in TREND_ESTIMATORS:
        raise ValueError(
            f"Unknown trend_estimator {trend_estimator!r} — must be one of {TREND_ESTIMATORS}"
        )
    if threshold_mode not in THRESHOLD_MODES:
        raise ValueError(
            f"Unknown threshold_mode {threshold_mode!r} — must be one of {THRESHOLD_MODES}"
        )
    alphabet_size = int(alphabet_size)
    if alphabet_size < 2:
        raise ValueError(f"alphabet_size must be at least 2, got {alphabet_size}")
    if threshold_mode == "absolute":
        if alphabet_size != 3:
            raise ValueError(
                "threshold_mode='absolute' is defined for alphabet_size=3 only "
                f"(a single +/- threshold gives exactly 3 bins), got {alphabet_size}. "
                "Use 'learned' or 'quantile' for larger alphabets."
            )
        if absolute_threshold is None:
            raise ValueError("threshold_mode='absolute' requires absolute_threshold")
        if float(absolute_threshold) <= 0:
            raise ValueError(
                f"absolute_threshold must be positive, got {absolute_threshold} — "
                "it is a half-width, and the cutlines are +/- it"
            )
    if threshold_mode == "quantile" and not 0.0 < same_fraction < 1.0:
        raise ValueError(f"same_fraction must lie strictly in (0, 1), got {same_fraction}")

    data = np.asarray(data, dtype=float).ravel()
    original_len = len(data)

    # ── Segmentation arithmetic, copied verbatim from psax() so that
    # `segment_plan`'s dim_ratio round-trip behaves identically for both.
    data_len = len(data)
    data_nseg = int(np.floor(dim_ratio * data_len))
    if data_nseg < 2:
        # psax reaches `data_len % data_nseg` with data_nseg=0 and dies with
        # a bare ZeroDivisionError. dSAX needs >= 2 segments anyway (a
        # one-symbol string is not a string), so it checks first and says
        # what is actually wrong.
        raise ValueError(
            f"dim_ratio={dim_ratio!r} over {data_len} samples yields {data_nseg} segment(s); "
            "dSAX needs at least 2. Raise dim_ratio or use a longer span."
        )
    data_len = data_len - (data_len % data_nseg)
    data = data[:data_len]
    sps = data_len // data_nseg
    if sps < 2:
        raise ValueError(
            f"dim_ratio={dim_ratio!r} yields {sps} sample(s) per segment; a trend needs at "
            "least 2. Lower dim_ratio, or raise seconds_per_symbol."
        )

    # Trim the training span the same way psax does.
    training_len = int(training_len)
    training_nseg = max(int(np.floor(dim_ratio * training_len)), 1)
    training_len = training_len - (training_len % training_nseg)

    # ── Normalisation. ONE step, unlike psax/csax (see module docstring).
    mu1, sigma1 = 0.0, 1.0
    if normalize:
        mu1 = float(data.mean())
        sd = float(data.std())
        if sd < _NORM_THRESH:
            # Degenerate-variance guard, matching psax: mean-subtract only,
            # so delta_scale stays exactly 1.0 and no division by ~0 blows
            # the deltas up to nonsense.
            data = data - mu1
        else:
            sigma1 = sd
            data = (data - mu1) / sigma1

    # ── Deltas over every segment.
    deltas, seg_slope, theil_sen_subsampled = compute_deltas(
        data, data_nseg, sps, trend_estimator=trend_estimator, endpoint_k=endpoint_k
    )

    # The training deltas are exactly the leading `n_train_seg` entries of
    # `deltas`, because segment i of `data[:n*sps]` IS segment i of `data`.
    # Recomputing them from a separately re-normalised training slice (as
    # psax does for its PAA) would put them in a slightly DIFFERENT scale
    # from the deltas being quantised — harmless for a mean, but a delta's
    # magnitude is the whole signal, so the cutlines would be learned in
    # one unit and applied in another. Slicing makes that class of bug
    # impossible. It also fixes the segment length at `sps` for training,
    # which matters because rise-per-segment scales with segment length:
    # psax's `training_nseg` can imply a slightly different segment length
    # from `sps`, which is invisible for PAA and a systematic bias here.
    n_train_seg = int(np.clip(training_len // sps, 2, data_nseg))
    training_deltas = deltas[:n_train_seg]

    # ── Cutlines, in the working (possibly normalised) delta domain.
    delta_scale = sigma1 if normalize else None
    degenerate_tol = _DEGENERATE_REL * max(float(np.max(np.abs(data))) if data.size else 0.0, 1.0)
    deltas_are_flat = float(np.ptp(deltas)) <= degenerate_tol

    deltas_are_zero = deltas_are_flat and (
        (float(np.max(np.abs(deltas))) if deltas.size else 0.0) <= degenerate_tol
    )
    # `absolute` mode is fully specified by the caller: its cutlines came
    # from a stated physical threshold, not from the data, so a degenerate
    # delta distribution gives it nothing to fall back FROM. Only the two
    # learning modes get short-circuited.
    learning_mode = threshold_mode in ("learned", "quantile")

    codewords = None
    if deltas_are_zero and learning_mode:
        # Short-circuit before the KDE: `epanechnikov_kde` on a
        # zero-variance sample falls back to a bandwidth of 1.0 in the
        # signal's units, which would place cutlines at O(1) around a
        # distribution of exact zeros — all-SAME by luck rather than by
        # construction, and unflagged. Handle it explicitly instead.
        cutlines = _all_same_cutlines(deltas, alphabet_size, degenerate_tol)
    elif deltas_are_flat and learning_mode:
        cutlines = _flat_nonzero_cutlines(deltas, alphabet_size)
    elif threshold_mode == "learned":
        codewords, cutlines = _learned_cutlines(
            training_deltas, alphabet_size, npoints=min(training_len, 1000)
        )
        if force_symmetric:
            cutlines = _symmetrise(cutlines)
    elif threshold_mode == "absolute":
        thr = float(absolute_threshold)
        # `absolute_threshold` is stated in RAW units of rise per segment,
        # so it has to be divided into the working domain — and by
        # delta_scale (sigma), never by norm_std composed with an offset.
        # Already symmetric by construction, so `force_symmetric` has
        # nothing to do here and is not applied (folding it would be an
        # exact no-op, but running it would suggest otherwise).
        cutlines = np.array([-thr, thr], dtype=float)
        if normalize:
            cutlines = cutlines / delta_scale
    else:  # "quantile"
        cutlines = _quantile_cutlines(training_deltas, alphabet_size, float(same_fraction))
        if force_symmetric:
            cutlines = _symmetrise(cutlines)

    cutlines, min_same_applied = _apply_min_same_halfwidth(
        cutlines, min_same_halfwidth, alphabet_size
    )
    cutlines, nudged = _enforce_ascending(cutlines, deltas)
    # The flag means "these cutlines are not a real quantisation of this
    # data" and is true in exactly three situations:
    #   - two cutlines had to be forced apart by an epsilon;
    #   - the deltas are all zero, so there was nothing to quantise at all
    #     (the brief's constant-signal case — true in EVERY mode, because
    #     it is a statement about the data, not about the cutlines);
    #   - a learning mode was handed a spread-free delta distribution and
    #     had to fall back on the zero anchor for its bin widths.
    # It is deliberately NOT set for `absolute` mode on a noiseless ramp:
    # the deltas have no spread there, but the cutlines are the caller's
    # stated physical thresholds, un-nudged and entirely meaningful.
    cutlines_degenerate = bool(
        nudged or deltas_are_zero or (deltas_are_flat and learning_mode)
    )

    # ── Quantise. One line — this IS the algorithm.
    str_out = np.searchsorted(cutlines, deltas, side="right")

    if not return_details:
        return str_out

    # ── details ──────────────────────────────────────────────────────────
    paa = ts_paa(data, data_nseg)

    if normalize:
        norm_mean = mu1
        norm_std = sigma1
    else:
        norm_mean = None
        norm_std = None

    # THE conversion rule. Levels take the offset; differences do not.
    paa_raw = paa if norm_std is None else paa * norm_std + norm_mean
    deltas_raw = deltas if delta_scale is None else deltas * delta_scale
    cutlines_raw = cutlines if delta_scale is None else cutlines * delta_scale
    seg_slope_raw = seg_slope if delta_scale is None else seg_slope * delta_scale

    if codewords is not None:
        representatives = np.asarray(codewords, dtype=float)
    else:
        representatives = _bin_representatives(deltas, cutlines, alphabet_size)
    representatives_raw = (representatives if delta_scale is None
                           else representatives * delta_scale)

    zero_symbol = int(np.searchsorted(cutlines, 0.0, side="right"))
    same_fraction_observed = float(np.mean(str_out == zero_symbol)) if len(str_out) else 0.0

    segment_starts = np.arange(data_nseg, dtype=int) * sps
    segment_ends = segment_starts + sps

    details = {
        # ── identical semantics to psax's keys, so shared consumers
        # (`_sax_common.diagnostic_rows`, the encoding cache) keep working.
        "samples_per_symbol": sps,
        "n_symbols": data_nseg,
        "data_len_trimmed": data_len,
        "n_trimmed": original_len - data_len,
        "alphabet_size": alphabet_size,
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "paa": paa,
        "paa_raw": paa_raw,
        "representatives": representatives,
        "representatives_raw": representatives_raw,
        "cutlines": np.asarray(cutlines, dtype=float),
        "cutlines_raw": np.asarray(cutlines_raw, dtype=float),
        # ── dSAX-specific. `cutlines`/`cutlines_raw` above live in DELTA
        # space, not amplitude space — which is why the shared
        # `plot_encoding_matplotlib` must not be pointed at this dict; see
        # `plot_trend_encoding`.
        # Declares, rather than leaves to be guessed, which quantity
        # `cutlines`/`cutlines_raw` are a threshold ON. The shared encoding
        # view (`UI.plots.build_encoding_panels`) draws cutlines against
        # the quantised quantity, and drawing a rise-per-segment threshold
        # against an amplitude level is dimensionally meaningless — see
        # `UI.plots.cutline_domain`, which reads this key and falls back to
        # duck-typing for cSAX/pSAX (whose details dicts predate it and
        # which are not edited here).
        "cutline_domain": "delta",
        "deltas": deltas,
        "deltas_raw": deltas_raw,
        "delta_scale": delta_scale,
        "delta_mean": float(np.mean(deltas)) if deltas.size else 0.0,
        "delta_mean_raw": (float(np.mean(deltas_raw)) if deltas_raw.size else 0.0),
        "seg_slope": seg_slope,
        "seg_slope_raw": seg_slope_raw,
        "segment_starts": segment_starts,
        "segment_ends": segment_ends,
        "trend_estimator": trend_estimator,
        "threshold_mode": threshold_mode,
        "force_symmetric": bool(force_symmetric),
        "zero_symbol": zero_symbol,
        "same_fraction_observed": same_fraction_observed,
        "cutlines_degenerate": cutlines_degenerate,
        "theil_sen_subsampled": bool(theil_sen_subsampled),
        "min_same_halfwidth_applied": bool(min_same_applied),
    }
    return str_out, details


# ── post-hoc analysis of a finished encoding ─────────────────────────────
#
# Everything below reads a `details` dict and never re-runs the encoder.
# That is deliberate: `learned` mode consumes `np.random` via `kmeanspp`,
# so a "what if" recomputation would not be comparing like with like
# unless the caller reseeded identically — which a UI button cannot be
# trusted to do. Working from `details["deltas"]` and `details["cutlines"]`
# instead makes every answer here EXACT with respect to the run being
# inspected, not an approximation of a different run.


def same_band_halfwidth(details):
    """Half-width of the SAME band, in the WORKING delta domain, or None
    when the alphabet has no SAME bin.

    An even alphabet has a cutline exactly AT zero (see `_symmetrise`) and
    therefore no middle bin — returning 0.0 there would read as "an
    infinitely narrow quiescent band", which is a different and wrong
    statement from "this alphabet does not have one".
    """
    cutlines = np.asarray(details["cutlines"], dtype=float)
    if int(details["alphabet_size"]) % 2 == 0 or cutlines.size < 2:
        return None
    mid_hi = cutlines.size // 2
    return float((cutlines[mid_hi] - cutlines[mid_hi - 1]) / 2.0)


def same_fraction_under_halfwidth(details, halfwidth):
    """What fraction of segments would be SAME if the SAME band were
    widened to at least +/- `halfwidth` (working delta units).

    Answers the noise-floor button's "what would imposing this floor
    actually do?" without re-encoding anything: it applies the SAME
    widening rule `dsax()` itself applies (`_apply_min_same_halfwidth`,
    then `_enforce_ascending`) to the cutlines already in `details`, and
    re-quantises the deltas already in `details`. Exact, deterministic,
    and provably the same arithmetic the real run would perform if
    `min_same_halfwidth` were passed in.

    Returns (same_fraction, widened_cutlines), or (None, None) when the
    alphabet has no SAME bin.
    """
    if same_band_halfwidth(details) is None:
        return None, None
    cutlines, _ = _apply_min_same_halfwidth(
        np.asarray(details["cutlines"], dtype=float), halfwidth,
        int(details["alphabet_size"]),
    )
    deltas = np.asarray(details["deltas"], dtype=float)
    cutlines, _ = _enforce_ascending(cutlines, deltas)
    symbols = np.searchsorted(cutlines, deltas, side="right")
    zero_symbol = int(np.searchsorted(cutlines, 0.0, side="right"))
    return float(np.mean(symbols == zero_symbol)), cutlines


def working_domain_array(x, details):
    """Re-derive the array `dsax()` actually measured deltas on, from the
    raw input and the normalisation constants it recorded.

    `min_same_halfwidth` is specified in the WORKING delta domain, so any
    externally-estimated half-width (e.g. from
    `surrogate_same_halfwidth`) has to be estimated on THIS array, not on
    the raw one — otherwise the two numbers being compared differ by a
    factor of `norm_std`, which on a fungal channel is easily two orders
    of magnitude. This is the same class of error `delta_scale` exists to
    prevent inside the encoder; the button that consumes it needs the
    same discipline.

    Also trims to `data_len_trimmed`, so the surrogate's spectrum is
    estimated over exactly the samples that were encoded.
    """
    x = np.asarray(x, dtype=float).ravel()[: int(details["data_len_trimmed"])]
    if details.get("norm_std") is None:
        return x
    return (x - float(details["norm_mean"])) / float(details["norm_std"])


# Occupancy band within which a 3-symbol trend encoding is indistinguishable
# from MSE-optimally quantised noise. IMPLEMENTATION_NOTES.md 6.3 measured
# 46.5% SAME on 3000 segments of pure Gaussian noise; the band is set
# generously around it because the exact figure depends on the noise colour,
# and the point of the warning is to prompt a check, not to accuse.
SAME_FRACTION_SUSPECT_RANGE = (0.40, 0.60)

# Above this fraction of the SAME half-width, a non-zero mean delta is
# reporting net drift rather than sampling noise. At 0.25 the mean sits a
# quarter of the way to the UP boundary, which is already enough to skew
# the UP/DOWN balance visibly.
DELTA_MEAN_DRIFT_FRACTION = 0.25


def trend_diagnostic_rows(symbols, details):
    """dSAX-specific diagnostic rows, to be APPENDED to
    `Adapters._sax_common.diagnostic_rows`'s domain-agnostic ones
    (occupancy entropy, self-transition rate, realised alphabet size) —
    not a replacement for them.

    Kept separate rather than folded into the shared function because the
    shared one serves cSAX and pSAX too, and every row below is a
    statement about a TREND encoding specifically: none of them has a
    meaning for an amplitude-quantised one. Returns the same
    `(label, value, severity)` shape the shared function returns, with
    severity in {"", "warn", "error"}, so the caller can concatenate the
    two lists and render them through one formatter.

    Lives here rather than in `Adapters/` so a headless SLURM job can print
    the same warnings the UI shows, without importing the adapter layer.
    """
    symbols = np.asarray(symbols, dtype=int)
    alphabet_size = int(details["alphabet_size"])
    rows = []

    halfwidth = same_band_halfwidth(details)
    scale = details.get("delta_scale") or 1.0

    # ── SAME fraction ────────────────────────────────────────────────────
    if halfwidth is None:
        rows.append((
            "SAME band",
            f"none — alphabet_size={alphabet_size} is EVEN, so the cutlines "
            "include one exactly at zero and there is no 'no meaningful change' "
            "bin at all. Use an odd alphabet size for trend work.",
            "warn",
        ))
    else:
        same_fraction = float(details.get("same_fraction_observed", 0.0))
        lo, hi = SAME_FRACTION_SUSPECT_RANGE
        suspect = lo <= same_fraction <= hi
        note = (
            " — roughly half of segments are labelled UP or DOWN. Pure noise "
            "produces 53% by MSE-optimal quantisation alone (see "
            "IMPLEMENTATION_NOTES.md 6.3). Check against a noise-floor estimate "
            "before reading this as structure." if suspect else ""
        )
        rows.append(("SAME fraction", f"{same_fraction * 100:.1f}%{note}",
                     "warn" if suspect else ""))

        applied = bool(details.get("min_same_halfwidth_applied"))
        rows.append((
            "SAME band half-width",
            f"{halfwidth * scale:.4g} (raw units, rise per segment)"
            + (" — widened to a supplied min_same_halfwidth floor" if applied
               else " — learned from the data, NOT a noise floor"),
            "",
        ))

    # ── mean delta / residual drift ──────────────────────────────────────
    delta_mean_raw = float(details.get("delta_mean_raw", 0.0))
    drifting = (
        halfwidth is not None and halfwidth > 0
        and abs(float(details.get("delta_mean", 0.0)))
        > DELTA_MEAN_DRIFT_FRACTION * halfwidth
    )
    drift_note = (
        " — the average segment is not flat, which means residual DRIFT is "
        "being encoded as morphology. dSAX quantises a rise, so a monotonic "
        "trend pushes every segment toward UP (or DOWN) and the string stops "
        "carrying shape. Detrending is not optional on electrode data — see "
        "IMPLEMENTATION_NOTES.md 7.3." if drifting else ""
    )
    rows.append(("Mean delta", f"{delta_mean_raw:.4g} (raw units){drift_note}",
                 "warn" if drifting else ""))

    # ── degeneracy ───────────────────────────────────────────────────────
    if details.get("cutlines_degenerate"):
        rows.append(("Cutlines degenerate", degeneracy_explanation(symbols, details), "error"))

    return rows


def degeneracy_explanation(symbols, details):
    """Plain-language account of WHICH degenerate case fired.

    `cutlines_degenerate` is one flag covering three distinct situations
    that want three different readings (IMPLEMENTATION_NOTES.md 2.4/2.5),
    and collapsing them into "something was degenerate" throws away the
    only information a reader can act on: a constant channel is a data
    problem, a straight ramp is a preprocessing problem, and nudged
    cutlines are a quantiser problem.

    Discriminated by observable facts rather than by re-deriving the
    encoder's internal tolerances, so this can never disagree with the
    flag it is explaining:
      - all symbols in the zero bin  -> the deltas were all zero;
      - otherwise no spread in the deltas -> a perfectly straight ramp;
      - otherwise -> two cutlines collided and were forced apart.
    """
    symbols = np.asarray(symbols, dtype=int)
    deltas = np.asarray(details["deltas"], dtype=float)
    zero_symbol = int(details.get("zero_symbol", 0))
    spread = float(np.ptp(deltas)) if deltas.size else 0.0
    biggest = float(np.max(np.abs(deltas))) if deltas.size else 0.0

    if symbols.size and np.all(symbols == zero_symbol):
        return (
            "every segment's rise is ZERO — the signal is constant over this span "
            "(a dead or saturated channel, or a fully quiescent stretch). The "
            "encoding is all-SAME by construction, not by measurement, and carries "
            "no information about this span beyond 'nothing happened'."
        )
    if spread <= biggest * 1e-6:
        return (
            "every segment rises by exactly the SAME amount — the signal is a "
            "perfectly straight ramp over this span, so the quantiser had no spread "
            "to learn from and the bin widths come from the zero anchor rather than "
            "from any density the data supports. The DIRECTION of each symbol is "
            "meaningful; the magnitudes are not."
        )
    return (
        "two cutlines collided and were forced apart by an epsilon — at least one "
        "symbol bin is empty by construction. The alphabet is effectively smaller "
        "than the requested size; reduce alphabet_size, or use a span whose delta "
        "distribution actually supports this many levels."
    )


# ── plotting ─────────────────────────────────────────────────────────────

def plot_trend_encoding(x, t, symbols, details, path=None, letter_threshold=120):
    """dSAX's own four-panel figure. NOT `plot_encoding_matplotlib`.

    The shared SAX renderer draws `cutlines_raw` as horizontal amplitude
    bands behind `paa_raw`. dSAX's cutlines are thresholds on a RISE, in
    units of amplitude-per-segment, and its `paa_raw` is a level. Drawing
    one against the other would produce a figure that is not merely
    unhelpful but physically meaningless — two quantities of different
    dimension sharing an axis, with the bands appearing to explain symbols
    they had no part in choosing. Hence a separate renderer, and hence the
    matching warning in `_sax_common`'s docstring is echoed here.

    The four panels answer four different questions:
      1. did the fitted trend actually track the signal?
      2. what were the per-segment deltas, and where did the cutlines fall?
      3. is the threshold SENSIBLE — i.e. does the SAME band sit over the
         bulk of the delta distribution or slice through it? This is the
         panel worth looking at first.
      4. what string came out?

    `Agg` is forced before pyplot is imported: this must render inside a
    SLURM job with no display, and matplotlib picks its backend at first
    pyplot import, so setting it afterwards is too late.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.asarray(x, dtype=float).ravel()
    t = np.asarray(t, dtype=float).ravel()
    symbols = np.asarray(symbols, dtype=int).ravel()

    sps = int(details["samples_per_symbol"])
    n_symbols = int(details["n_symbols"])
    alphabet_size = int(details["alphabet_size"])
    deltas_raw = np.asarray(details["deltas_raw"], dtype=float)
    cutlines_raw = np.asarray(details["cutlines_raw"], dtype=float)
    paa_raw = np.asarray(details["paa_raw"], dtype=float)
    seg_slope_raw = np.asarray(details["seg_slope_raw"], dtype=float)

    idx = np.minimum(np.arange(n_symbols + 1) * sps, len(t) - 1)
    seg_t = t[idx]
    seg_mid = (seg_t[:-1] + seg_t[1:]) / 2.0

    cmap = matplotlib.colormaps["coolwarm"].resampled(max(alphabet_size, 2))
    colors = [cmap(i) for i in range(alphabet_size)]

    fig, axes = plt.subplots(4, 1, figsize=(14, 12),
                             gridspec_kw={"height_ratios": [2.2, 2.0, 2.0, 0.6]})

    # 1 ── signal with each segment's fitted trend drawn over it.
    ax = axes[0]
    # Grey, not the usual signal blue: the fitted trend lines drawn on top
    # are coloured BY SYMBOL, and on a `coolwarm` scale DOWN is blue — a
    # blue trend line over a blue signal is invisible, which defeats the
    # only purpose of this panel.
    ax.plot(t, x, linewidth=0.6, color="#aaaaaa")
    for i in range(n_symbols):
        # The OLS line passes through (segment centre, segment mean); for
        # the endpoint estimators `seg_slope` is the secant slope and the
        # segment mean is still the natural anchor, so one formula serves
        # every estimator and the drawn line always has the slope that was
        # actually quantised.
        half_rise = seg_slope_raw[i] * (sps - 1) / 2.0
        ax.plot([seg_t[i], seg_t[i + 1]],
                [paa_raw[i] - half_rise, paa_raw[i] + half_rise],
                color=colors[symbols[i] % len(colors)], linewidth=2.0,
                solid_capstyle="butt")
    ax.set_ylabel("amplitude")
    # Panels 1, 2 and 4 are all against time and must be readable as one
    # vertical stack, so their x limits are pinned to the same span rather
    # than left to matplotlib's per-axes autoscale margins. `sharex` is not
    # used because panel 3's x axis is a delta axis, not time.
    ax.set_xlim(t[0], t[-1])
    ax.set_title(
        f"Signal with per-segment fitted trend  "
        f"(estimator={details['trend_estimator']}, sps={sps})"
    )

    # 2 ── the quantised quantity itself, against the cutlines.
    ax = axes[1]
    ax.axhline(0.0, color="#999999", linewidth=0.8)
    ax.vlines(seg_mid, 0.0, deltas_raw, color="#555555", linewidth=0.8)
    ax.scatter(seg_mid, deltas_raw, s=14,
               c=[colors[s % len(colors)] for s in symbols], zorder=3)
    for c in cutlines_raw:
        ax.axhline(c, color="#333333", linewidth=1.0, linestyle="--")
    ax.set_ylabel("delta (rise per segment,\nraw units)")
    ax.set_title("Per-segment delta vs. cutlines (dashed)")
    ax.set_xlim(t[0], t[-1])

    # 3 ── the diagnostic panel: is this threshold defensible?
    ax = axes[2]
    bins = int(np.clip(np.sqrt(max(n_symbols, 1)) * 3, 10, 80))
    ax.hist(deltas_raw, bins=bins, color="#bcbcbc", edgecolor="#888888")
    zero_symbol = int(details["zero_symbol"])
    if alphabet_size % 2 == 1 and cutlines_raw.size >= 2:
        mid_hi = cutlines_raw.size // 2
        ax.axvspan(cutlines_raw[mid_hi - 1], cutlines_raw[mid_hi],
                   color=colors[zero_symbol % len(colors)], alpha=0.30,
                   label="SAME band")
        ax.legend(loc="upper right", fontsize=8)
    for c in cutlines_raw:
        ax.axvline(c, color="#333333", linewidth=1.0, linestyle="--")
    ax.axvline(0.0, color="#000000", linewidth=1.2)
    ax.set_xlabel("delta (rise per segment, raw units)")
    ax.set_ylabel("segments")
    ax.set_title(
        f"Delta distribution vs. cutlines  "
        f"(mode={details['threshold_mode']}, symmetric={details['force_symmetric']}, "
        f"SAME={details['same_fraction_observed'] * 100:.1f}%)"
    )

    # 4 ── the string.
    ax = axes[3]
    show_letters = n_symbols <= letter_threshold
    for i in range(n_symbols):
        ax.axvspan(seg_t[i], seg_t[i + 1], color=colors[symbols[i] % len(colors)])
        if show_letters:
            ax.text(seg_mid[i], 0.5, dsax_letters([symbols[i]], alphabet_size),
                    ha="center", va="center", fontsize=7, color="black")
    ax.set_yticks([])
    ax.set_xlim(t[0], t[-1])
    ax.set_xlabel("time (s)")
    ax.set_title("Symbol strip")

    fig.tight_layout()
    if path is not None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        fig.savefig(path, dpi=110)
    return fig
