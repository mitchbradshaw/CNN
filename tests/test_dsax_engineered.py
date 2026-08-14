"""
test_dsax_engineered.py
========================
Engineered-dataset tests for dSAX: thirteen synthetic signals whose correct
encoding is known in advance, so a regression shows up as a wrong STRING
rather than as a plausible-looking array nobody can check.

Where an exact string is asserted the call uses
`normalize=False, threshold_mode="absolute"`. That combination is
deliberately the least clever configuration available: no z-normalisation
to reason about, no density estimate, no RNG, and a threshold stated
directly in the same raw units as the signal. The expectation is then
unambiguous - if `"UUUUUUUUUU"` does not come out of a monotonic ramp,
something is wrong with dSAX and not with the test's setup.

The later tests (8-13) are statistical rather than exact, and each one
targets a specific claim the design rests on:
  - 8  the zero anchor holds under noise (no drift in the SAME band);
  - 9  the KNOWN failure mode - untreated drift swamps the encoding;
  - 10 amplitude invariance under normalisation;
  - 11 sampling-rate invariance at matched seconds-per-symbol, which is
       the whole reason every estimator is expressed as rise-per-SEGMENT;
  - 12 the four estimators are genuinely interchangeable when there is no
       noise for them to disagree about;
  - 13 and that they are NOT interchangeable when there is, in the
       direction the choice of `ols_slope` as the default assumes.

`ENGINEERED` at the bottom is the shared dataset registry, imported by
`Experimentation/Detection experiments/run_dsax_validation.py` so the
figures and the metrics describe exactly the signals asserted on here.

Pure-numpy, ASCII-only output (see BASELINE.md). Runnable standalone:
    python tests/test_dsax_engineered.py
"""

import inspect
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.Detection.sax.dsax_python.dsax import dsax, dsax_letters
from Working.Detection.sax.dsax_python.trend_estimators import TREND_ESTIMATORS

SEED = 20260809
DOWN, SAME, UP = 0, 1, 2


def _dim_ratio(n, sps):
    """The `segment_plan` convention: `(n_symbols + 0.5) / n` reproduces
    `n_symbols` exactly through dSAX's own `floor(dim_ratio * n)`."""
    return (n // sps + 0.5) / n


def encode(x, sps, seed=SEED, **kwargs):
    """One seeded call, returning `(symbols, details)`. Seeding
    unconditionally costs nothing in the RNG-free modes and removes any
    chance of a `learned`-mode test being flaky."""
    np.random.seed(seed)
    return dsax(x, len(x), _dim_ratio(len(x), sps), return_details=True, **kwargs)


def letters(x, sps, **kwargs):
    symbols, details = encode(x, sps, **kwargs)
    return dsax_letters(symbols, details["alphabet_size"])


# -- the signals -----------------------------------------------------------
# Built once at import so the tests and the validation script provably
# encode the identical arrays.

RAMP_UP = np.linspace(0.0, 10.0, 1000)
RAMP_DOWN = -RAMP_UP
CONSTANT = np.full(1000, 5.0)
TRIANGLE = np.concatenate(
    [np.linspace(0.0, 1.0, 100) if i % 2 == 0 else np.linspace(1.0, 0.0, 100)
     for i in range(10)]
)

# Flat, then a unit step in the MIDDLE of segment 5, then flat.
STEP = np.zeros(1000)
STEP[550:] = 1.0
STEP_SEGMENT = 5

# Five segments whose rises are exactly -2, -1, 0, +1, +2.
_stair_pieces, _stair_level = [], 0.0
for _rise in (-2.0, -1.0, 0.0, 1.0, 2.0):
    _stair_pieces.append(np.linspace(_stair_level, _stair_level + _rise, 100))
    _stair_level += _rise
STAIRCASE = np.concatenate(_stair_pieces)

# Sharkfin: one segment of fast rise, then five segments of exponential
# decay with a 200-sample time constant (so each segment loses a factor
# exp(-0.5) and every one of the five is a clear DOWN).
SHARKFIN = np.concatenate([
    np.linspace(0.0, 10.0, 100),
    10.0 * np.exp(-np.arange(500) / 200.0),
])

# 3000 segments, not a few hundred. The UP/DOWN balance assertions below
# are bounded at 0.1, and the sampling error on that statistic is set by
# the segment count: even with a perfectly centred delta distribution,
# UP - DOWN is multinomial with sd = sqrt(n_seg * 0.5), so the imbalance
# has sd = sqrt(0.5 / n_seg). At 300 segments that is 0.041 and a 0.1 bound
# is a 2.4-sigma test - which duly failed on the first seed tried, at 0.113,
# with `delta_mean` sitting a perfectly ordinary +2.4 standard errors from
# zero. At 3000 segments the sd is 0.013 and the same bound is a 7-sigma
# test. The expectation was right; the sample was too small to support it.
NOISE_SPS = 40
NOISE_N = 120_000
_noise_rng = np.random.default_rng(SEED)
NOISE = _noise_rng.normal(0.0, 1.0, NOISE_N)
# Per-segment drift of +3.0 at sps=40 - roughly 6x the standard deviation
# of an OLS delta on this noise, so the drift is overwhelming by design.
DRIFT_PER_SEGMENT = 3.0
NOISE_PLUS_DRIFT = NOISE + np.arange(NOISE_N) * (DRIFT_PER_SEGMENT / NOISE_SPS)

_mixed_rng = np.random.default_rng(SEED + 1)
MIXED = (2.0 * np.sin(2 * np.pi * np.arange(6000) / 700.0)
         + _mixed_rng.normal(0.0, 0.5, 6000))


def _smooth(t_seconds):
    """A deterministic band-limited function, used for the sampling-rate
    invariance test. Two incommensurate components so the encoding is not
    trivially periodic at the segment scale."""
    return (np.sin(2 * np.pi * t_seconds / 37.0)
            + 0.6 * np.sin(2 * np.pi * t_seconds / 11.3))


def _detrend_linear(x):
    idx = np.arange(len(x), dtype=float)
    slope, intercept = np.polyfit(idx, x, 1)
    return x - (slope * idx + intercept)


# -- 1-2. monotonic ramps --------------------------------------------------

def test_01_linear_ramp_up_is_all_up():
    got = letters(RAMP_UP, 100, threshold_mode="absolute",
                  absolute_threshold=0.1, normalize=False)
    assert got == "UUUUUUUUUU", got


def test_02_linear_ramp_down_is_all_down():
    got = letters(RAMP_DOWN, 100, threshold_mode="absolute",
                  absolute_threshold=0.1, normalize=False)
    assert got == "DDDDDDDDDD", got


# -- 3. constant -----------------------------------------------------------

def test_03_constant_signal_is_all_same_in_every_mode():
    """A dead channel must encode, not explode. Asserted for the learned
    mode too, because that is the path that would otherwise hand a
    zero-variance sample to the KDE."""
    for kwargs in (dict(threshold_mode="absolute", absolute_threshold=0.5, normalize=False),
                   dict(threshold_mode="absolute", absolute_threshold=0.5, normalize=True),
                   dict(threshold_mode="learned", normalize=False),
                   dict(threshold_mode="learned", normalize=True),
                   dict(threshold_mode="quantile", normalize=True)):
        symbols, details = encode(CONSTANT, 100, **kwargs)
        assert np.all(symbols == SAME), f"{kwargs}: got {dsax_letters(symbols)}"
        assert details["cutlines_degenerate"] is True, \
            f"{kwargs}: a flat delta distribution must be flagged"
        assert np.all(np.diff(details["cutlines"]) > 0), \
            f"{kwargs}: cutlines must still be strictly ascending"
        assert details["same_fraction_observed"] == 1.0


def test_03c_a_noiseless_ramp_is_not_reported_as_degenerate_under_absolute():
    """A pure ramp has zero SPREAD in its deltas, which is a different
    condition from having zero deltas. Under `absolute` the cutlines are
    the caller's stated physical thresholds and are perfectly meaningful,
    so the flag must stay off; under a LEARNING mode there is genuinely
    nothing to learn from a point mass and the bin widths come from the
    zero anchor instead, so the flag must come on."""
    _, absolute = encode(RAMP_UP, 100, threshold_mode="absolute",
                         absolute_threshold=0.1, normalize=False)
    assert np.ptp(absolute["deltas"]) < 1e-9, "the ramp must have spread-free deltas"
    assert absolute["cutlines_degenerate"] is False
    assert np.allclose(absolute["cutlines"], [-0.1, 0.1])

    symbols, learned = encode(RAMP_UP, 100, threshold_mode="learned", normalize=False)
    assert learned["cutlines_degenerate"] is True
    assert np.all(symbols == UP), "a monotonic ramp must never encode as SAME"


def test_03b_constant_signal_still_requantises_exactly():
    """Mirrors `test_csax_fallback_path_is_flagged_and_still_reproducible`:
    the degenerate path must report cutlines that genuinely produced the
    string, not placeholder values."""
    symbols, details = encode(CONSTANT, 100, threshold_mode="learned")
    by_hand = np.searchsorted(details["cutlines"], details["deltas"], side="right")
    assert np.array_equal(by_hand, symbols)


# -- 4. triangle -----------------------------------------------------------

def test_04_triangle_wave_alternates():
    got = letters(TRIANGLE, 100, threshold_mode="absolute",
                  absolute_threshold=0.2, normalize=False)
    assert got == "UDUDUDUDUD", got


# -- 5. isolated step ------------------------------------------------------

def test_05_step_inside_one_segment_marks_exactly_that_segment():
    symbols, _ = encode(STEP, 100, threshold_mode="absolute",
                        absolute_threshold=0.2, normalize=False)
    non_same = np.flatnonzero(symbols != SAME)
    assert len(non_same) == 1, f"expected one non-SAME symbol, got {dsax_letters(symbols)}"
    assert non_same[0] == STEP_SEGMENT, f"marked segment {non_same[0]}"
    assert symbols[non_same[0]] == UP


# -- 6. five-symbol staircase ---------------------------------------------

def test_06_staircase_fills_a_five_symbol_alphabet_in_order():
    """`absolute` mode is a 3-symbol construction by definition, and
    `learned` mode cannot be trusted to resolve five clusters from five
    training points, so this uses `quantile` - which at k>3 places
    equiprobable cutlines and is fully deterministic. With exactly one
    segment per intended symbol, equiprobable IS the right answer."""
    symbols, details = encode(STAIRCASE, 100, alphabet_size=5,
                              threshold_mode="quantile", normalize=False)
    assert np.array_equal(symbols, np.arange(5)), \
        f"got {symbols.tolist()} from deltas {np.round(details['deltas'], 6).tolist()}"
    assert np.allclose(details["deltas"], [-2.0, -1.0, 0.0, 1.0, 2.0]), \
        "the staircase's per-segment rises must be exactly what was built"
    assert details["zero_symbol"] == 2


# -- 7. sharkfin -----------------------------------------------------------

def test_07_sharkfin_matches_the_morphology_regex():
    """The point of the whole representation: a named morphology becomes a
    regular expression over the string. Stripping SAME first is how a
    vocabulary pattern is meant to be applied - quiescent padding should
    not break a match."""
    got = letters(SHARKFIN, 100, threshold_mode="absolute",
                  absolute_threshold=0.25, normalize=False)
    stripped = got.replace("S", "")
    assert re.fullmatch(r"UD{3,}", stripped), f"got {got!r} -> stripped {stripped!r}"


# -- 8. white noise --------------------------------------------------------

def test_08_white_noise_stays_balanced_around_zero():
    symbols, details = encode(NOISE, NOISE_SPS, threshold_mode="learned",
                              force_symmetric=True)
    n = len(symbols)
    up = int(np.sum(symbols == UP))
    down = int(np.sum(symbols == DOWN))
    imbalance = abs(up - down) / n
    assert imbalance < 0.1, f"UP={up} DOWN={down} imbalance={imbalance:.4f}"

    # Delta mean: an OLS delta on unit-variance noise at sps=40 has
    # sd ~ 0.53, so 3000 of them have a sample-mean standard error of
    # ~0.0097 - 0.05 is a 5-sigma bound.
    assert abs(details["delta_mean"]) < 0.05, details["delta_mean"]

    cutlines = details["cutlines"]
    assert np.allclose(cutlines, -cutlines[::-1]), cutlines
    assert int(np.searchsorted(cutlines, 0.0)) == 1, \
        "delta = 0 must land in the middle (SAME) bin"
    assert details["zero_symbol"] == SAME


# -- 9. the known failure mode: drift ------------------------------------

def test_09_untreated_drift_swamps_the_encoding_and_detrending_fixes_it():
    """This test asserts a WEAKNESS, on purpose. dSAX quantises a rise, so
    a monotonic drift makes every segment rise, and the encoding collapses
    to all-UP while carrying no morphology at all. Anyone using dSAX on
    real electrode data needs to know that detrending is not optional -
    hence a test that fails loudly if the failure mode ever silently
    stops being reproducible (which would mean the encoder had started
    detrending on its own, which it must not)."""
    symbols, _ = encode(NOISE_PLUS_DRIFT, NOISE_SPS, threshold_mode="learned")
    up_fraction = float(np.mean(symbols == UP))
    assert up_fraction > 0.8, f"expected drift dominance, got UP fraction {up_fraction:.3f}"

    detrended = _detrend_linear(NOISE_PLUS_DRIFT)
    symbols2, _ = encode(detrended, NOISE_SPS, threshold_mode="learned")
    n = len(symbols2)
    imbalance = abs(int(np.sum(symbols2 == UP)) - int(np.sum(symbols2 == DOWN))) / n
    assert imbalance < 0.1, f"detrending did not restore balance: {imbalance:.4f}"


# -- 10. scale invariance -------------------------------------------------

def test_10_encoding_is_invariant_to_amplitude_scaling():
    a, _ = encode(MIXED, 40, threshold_mode="learned", normalize=True)
    b, _ = encode(1000.0 * MIXED, 40, threshold_mode="learned", normalize=True)
    assert np.array_equal(a, b), \
        f"{int(np.sum(a != b))} of {len(a)} symbols differ under a 1000x rescale"


# -- 11. sampling-rate invariance -----------------------------------------

def test_11_encoding_is_invariant_to_sampling_rate_at_matched_seconds():
    """Matched SECONDS per symbol, not samples - this is what the
    rise-per-segment normalisation in `trend_estimators` buys. If the
    estimators returned slope-per-sample instead, the two encodings here
    would differ by a factor of two in delta scale."""
    duration = 600.0
    fs_lo, fs_hi = 10.0, 20.0
    seconds_per_symbol = 4.0

    x_lo = _smooth(np.arange(int(duration * fs_lo)) / fs_lo)
    x_hi = _smooth(np.arange(int(duration * fs_hi)) / fs_hi)
    sym_lo, det_lo = encode(x_lo, int(seconds_per_symbol * fs_lo), threshold_mode="learned")
    sym_hi, det_hi = encode(x_hi, int(seconds_per_symbol * fs_hi), threshold_mode="learned")

    assert det_lo["n_symbols"] == det_hi["n_symbols"] == 150
    agreement = float(np.mean(sym_lo == sym_hi))
    assert agreement >= 0.95, f"symbol agreement across sampling rates was {agreement:.3f}"


# -- 12. the estimators agree when there is nothing to disagree about -----

def test_12_all_estimators_agree_on_noiseless_signals():
    for name, signal, threshold in (("ramp_up", RAMP_UP, 0.1),
                                    ("ramp_down", RAMP_DOWN, 0.1),
                                    ("triangle", TRIANGLE, 0.2)):
        strings = {}
        for estimator in TREND_ESTIMATORS:
            strings[estimator] = letters(signal, 100, trend_estimator=estimator,
                                         threshold_mode="absolute",
                                         absolute_threshold=threshold, normalize=False)
        distinct = set(strings.values())
        assert len(distinct) == 1, f"{name}: estimators disagreed -> {strings}"


def test_12b_robust_endpoints_at_k1_is_bit_identical_to_endpoints():
    """Not merely equal to tolerance - the same bits. `robust_endpoints`
    special-cases k=1 to avoid routing a single element through a median,
    and this is what keeps that special case honest."""
    for signal in (RAMP_UP, TRIANGLE, SHARKFIN, NOISE[:4000], MIXED):
        sps = 100 if len(signal) % 100 == 0 else 40
        _, a = encode(signal, sps, trend_estimator="endpoints",
                      threshold_mode="quantile", normalize=False)
        _, b = encode(signal, sps, trend_estimator="robust_endpoints", endpoint_k=1,
                      threshold_mode="quantile", normalize=False)
        assert np.array_equal(a["deltas"], b["deltas"]), \
            "robust_endpoints(k=1) must be bit-identical to endpoints"


def test_12c_robust_endpoints_at_k_above_one_actually_differs():
    """Sanity guard on the test above: if `endpoint_k` were being ignored
    entirely, `test_12b` would still pass. This makes sure it is not."""
    _, a = encode(NOISE[:4000], 40, trend_estimator="robust_endpoints", endpoint_k=1,
                  threshold_mode="quantile", normalize=False)
    _, b = encode(NOISE[:4000], 40, trend_estimator="robust_endpoints", endpoint_k=5,
                  threshold_mode="quantile", normalize=False)
    assert not np.array_equal(a["deltas"], b["deltas"])


# -- 13. the estimators do NOT agree when there is ------------------------

# A slow sinusoid whose per-segment rise sweeps smoothly through +/-1.0, so
# a threshold at 0.5 sits in the middle of the range and segments near the
# crossings are genuinely borderline - which is where estimator variance
# turns into symbol flips.
ROBUSTNESS_SPS = 50
ROBUSTNESS_N = 2000
ROBUSTNESS_THRESHOLD = 0.5
ROBUSTNESS_NOISE_SD = 0.2
ROBUSTNESS_REPEATS = 200
_rob_t = np.arange(ROBUSTNESS_N, dtype=float)
ROBUSTNESS_BASE = (1.0 / (ROBUSTNESS_SPS - 1)) * (1000.0 / (2 * np.pi)) * \
    np.sin(2 * np.pi * _rob_t / 1000.0)


def _flip_rates(repeats=ROBUSTNESS_REPEATS, estimators=TREND_ESTIMATORS):
    """Symbol-flip rate per estimator against the noiseless ground truth.
    Shared with `run_dsax_validation.py` so the reported numbers and the
    asserted ones are the same computation."""
    common = dict(threshold_mode="absolute", absolute_threshold=ROBUSTNESS_THRESHOLD,
                  normalize=False)
    truth = {e: encode(ROBUSTNESS_BASE, ROBUSTNESS_SPS, trend_estimator=e, **common)[0]
             for e in estimators}
    flips = {e: 0 for e in estimators}
    total = {e: 0 for e in estimators}
    for seed in range(repeats):
        rng = np.random.default_rng(10_000 + seed)
        noisy = ROBUSTNESS_BASE + rng.normal(0.0, ROBUSTNESS_NOISE_SD, ROBUSTNESS_N)
        for e in estimators:
            got, _ = encode(noisy, ROBUSTNESS_SPS, trend_estimator=e, **common)
            flips[e] += int(np.sum(got != truth[e]))
            total[e] += len(got)
    return {e: flips[e] / total[e] for e in estimators}


def test_13_fitted_estimators_flip_less_than_endpoints_under_noise():
    """The measurement behind the choice of `ols_slope` as the default.

    `endpoints` uses two samples, so its delta has variance 2*sigma^2
    however long the segment is. An OLS slope over sps samples has delta
    variance about 12*sigma^2/sps - at sps=50 that is a factor of ~25 less,
    which should show up directly as fewer symbol flips near a threshold.

    If this ever fails, do NOT weaken it: the finding would contradict the
    design rationale and belongs in IMPLEMENTATION_NOTES.md.
    """
    rates = _flip_rates()
    assert rates["ols_slope"] < rates["endpoints"], rates
    assert rates["theil_sen"] < rates["endpoints"], rates
    # And the noise really is producing flips - otherwise the comparison
    # above would be 0 < 0 and would have failed anyway, but a positive
    # assertion says so explicitly.
    assert rates["endpoints"] > 0.01, f"the test signal produced almost no flips: {rates}"


# -- shared registry for the validation script ----------------------------

ENGINEERED = [
    {"id": 1, "name": "ramp_up", "x": RAMP_UP, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=0.1, normalize=False),
     "expectation": "UUUUUUUUUU"},
    {"id": 2, "name": "ramp_down", "x": RAMP_DOWN, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=0.1, normalize=False),
     "expectation": "DDDDDDDDDD"},
    {"id": 3, "name": "constant", "x": CONSTANT, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="learned", normalize=True),
     "expectation": "all SAME, cutlines_degenerate=True"},
    {"id": 4, "name": "triangle", "x": TRIANGLE, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=0.2, normalize=False),
     "expectation": "UDUDUDUDUD"},
    {"id": 5, "name": "step", "x": STEP, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=0.2, normalize=False),
     "expectation": "one UP at segment 5, rest SAME"},
    {"id": 6, "name": "staircase_k5", "x": STAIRCASE, "fs": 1.0, "sps": 100,
     "kwargs": dict(alphabet_size=5, threshold_mode="quantile", normalize=False),
     "expectation": "symbols [0, 1, 2, 3, 4]"},
    {"id": 7, "name": "sharkfin", "x": SHARKFIN, "fs": 1.0, "sps": 100,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=0.25, normalize=False),
     "expectation": "U then D+ after stripping S"},
    {"id": 8, "name": "white_noise", "x": NOISE, "fs": 1.0, "sps": NOISE_SPS,
     "kwargs": dict(threshold_mode="learned", force_symmetric=True),
     "expectation": "UP/DOWN balanced, cutlines symmetric"},
    {"id": 9, "name": "noise_plus_drift", "x": NOISE_PLUS_DRIFT, "fs": 1.0, "sps": NOISE_SPS,
     "kwargs": dict(threshold_mode="learned"),
     "expectation": "UP fraction > 0.8 (drift dominance)"},
    {"id": 10, "name": "mixed_sine_noise", "x": MIXED, "fs": 1.0, "sps": 40,
     "kwargs": dict(threshold_mode="learned", normalize=True),
     "expectation": "identical under a 1000x rescale"},
    {"id": 11, "name": "smooth_fs10", "x": _smooth(np.arange(6000) / 10.0), "fs": 10.0,
     "sps": 40, "kwargs": dict(threshold_mode="learned"),
     "expectation": ">= 95% agreement with the same function at 2x fs"},
    {"id": 12, "name": "noisy_sine_borderline", "x": ROBUSTNESS_BASE, "fs": 1.0,
     "sps": ROBUSTNESS_SPS,
     "kwargs": dict(threshold_mode="absolute", absolute_threshold=ROBUSTNESS_THRESHOLD,
                    normalize=False),
     "expectation": "noiseless ground truth for the estimator comparison"},
]


# -- runner ----------------------------------------------------------------

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
