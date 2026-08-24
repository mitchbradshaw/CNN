"""
autoparams.py
==============
Detection parameters derived from the span's own dominant period, instead
of hand-tuned per recording.

Why this exists
---------------
The three-stage detector ships six spans and every one of them carries a
hand-measured parameter set with its own justification. That is honest
work and it does not scale: the sixteen spans this module was written for
range 450x in duration (720 samples to 324,000) and hand-tuning each is
sixteen parameter sweeps.

The observation that makes derivation possible is that the shipped tuning
notes are ALREADY period-derived reasoning, written in prose:

    "the segment length is bounded above by the RISE, not the fall"
    "long enough not to eat a ~50-100 s icicle, short enough to flatten
     the slow wander"

Both are statements about the event period. `derive_params` makes them
executable, so the parameters become something the signal said rather
than something an operator remembered.

Why the period is measured TWICE
--------------------------------
Autocorrelation of the detrended trace recovers the period well when the
train is regular, and the ACF peak height is a free confidence score.
Measured against the annotated cycle counts on the real spans:

    span            ACF period   implied n   annotated n   ACF peak
    sharkfin x14        509 s        14.0         14         0.91
    crested->shark      517 s        16.6         16         0.83
    sharkfin x4         959 s         4.0          4         0.62
    growing            5435 s        39.7        ~38         0.58
    ---------------------------------------------------------------
    am16 (336-346 h)   2950 s        12.2         16         0.22
    clean sharkfin      394 s          -           -         0.11
    triangle ridges   46788 s          -           -         0.04

Everything at >=0.58 is right and everything at <=0.36 is suspect, so the
peak height is a usable gate. But the failure at the top of the second
block is the one that matters: `am16` is the reference span, the one with
the only external check (16 detections against an annotation that
independently records "16 cycles"), and its ACF is wrong by four cycles.

It is wrong for a stated reason. Annotation 11266 reads "frequency
modulation fm DECREASING" - the span has no single period, so no
autocorrelation can return the right number and neither can any other
stationary estimator. A wavelet Omega(tau) energy sum was tried as an
alternative and reproduces the ACF almost exactly where the ACF is good
(14.1 vs 14.0, 16.9 vs 16.6, 4.1 vs 4.0) and fails identically on am16
(12.7 vs 16), with uniformly lower confidence. The problem is
non-stationarity, not the transform.

So the ACF is only a SEED. `autotune` runs detection with it, takes the
median inter-onset interval of what came back, re-derives from that and
re-runs. A median interval is well defined on a modulated train where a
period is not. The fixed point of "the parameters imply the events, the
events imply the parameters" is a stronger claim than either endpoint,
and it needs no human number - which keeps the 16-from-16 check honest,
because a period derived from "16" would make finding 16 events circular.

The annotated counts are therefore a CHECK in the report and never an
input here.
"""

from dataclasses import dataclass, field

import numpy as np

# The ACF peak height above which the measured period is trusted without
# qualification. Set from the table above: every real span at or above
# this reads a period consistent with its annotated cycle count, and every
# span below it does not. Spans under the gate still get a period - the
# refinement pass usually rescues them - but the report flags them.
CONFIDENCE_GATE = 0.50

# Segments per period. The binding constraint is the RISE, which must span
# several segments for a rise-then-fall rule to see it as a rise at all;
# eight puts ~6 segments across a sharkfin's rise and ~2 across its fall.
SEGMENTS_PER_PERIOD = 8.0

# Detrend window as a multiple of the period. Below ~1 period the rolling
# mean tracks the event and removes it; far above it the slow drift
# survives into the trend alphabet. Two and a half is the middle of the
# range the shipped hand-tuned spans actually occupy when their windows
# are re-expressed in periods (am16: 1800/2250 = 0.8; sharkfin14:
# 1013/509 = 2.0; furrycaterpillar: 120/102 = 1.2; troughtrain and
# growing both near 1.3), rounded up because the failure at the short end
# (the event is deleted) is silent and the failure at the long end (some
# drift survives) is visible in the figure.
DETREND_PERIODS = 2.5

# Bounds on the search for a period, as fractions of the span. Below the
# lower bound a "period" is a few samples of noise; above the upper the
# ACF is estimated from too few repeats to mean anything.
MIN_PERIOD_SAMPLES = 20
MAX_PERIOD_FRAC = 0.25

# Relative change in the period below which the refinement has converged.
CONVERGENCE_TOL = 0.15


def _rolling_mean(x, window):
    window = max(3, int(window)) | 1
    padded = np.pad(x, window // 2, mode="edge")
    cumulative = np.cumsum(np.insert(padded, 0, 0.0))
    return ((cumulative[window:] - cumulative[:-window]) / window)[:len(x)]


def dominant_period(x, fs, min_period_s=None, max_frac=MAX_PERIOD_FRAC):
    """`(period_s, confidence)` from the autocorrelation's tallest peak.

    The confidence IS the peak height, in [0, 1] where 1 is a perfectly
    periodic signal. It is returned rather than thresholded here because
    the caller decides what to do about a weak one, and because the number
    belongs in the report either way - a derived parameter with no stated
    confidence is a magic number with extra steps.

    The high-pass before the transform is deliberately crude (a rolling
    mean a tenth of the span) and is NOT the detection detrend: its only
    job is to stop a slow baseline drift dominating the ACF at every lag,
    and using the real detrend window here would need the period, which is
    what is being measured.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    n = len(x)
    if n < 16:
        return float("nan"), 0.0

    x = x - _rolling_mean(x, max(3, n // 10))
    x = x - x.mean()

    # FFT autocorrelation: the direct O(n^2) form is unusable at 324,000
    # samples, which is one real span.
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(x, size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    if acf[0] <= 0:
        return float("nan"), 0.0
    acf = acf / acf[0]

    lo = int(MIN_PERIOD_SAMPLES if min_period_s is None
             else round(min_period_s * fs))
    hi = int(n * max_frac)
    if hi <= lo + 3:
        return float("nan"), 0.0

    segment = acf[lo:hi]
    slope = np.diff(segment)
    peaks = np.flatnonzero((slope[:-1] > 0) & (slope[1:] <= 0)) + 1
    if peaks.size == 0:
        return float("nan"), 0.0

    best = int(peaks[int(np.argmax(segment[peaks]))])
    return float((lo + best) / fs), float(segment[best])


def derive_params(period_s, fs, n_samples, **overrides):
    """The parameter dict implied by one period.

    Only the two parameters that are genuinely time-scaled are derived.
    Everything else in `Detect5Params` is dimensionless by construction -
    `slope_sigma` is a multiple of the noise, `min_depth_frac` a fraction
    of the deepest fall, the window multipliers fractions of the fall -
    which is precisely why those did NOT need per-recording tuning in the
    shipped detector and these two did.
    """
    fs = float(fs)
    span_s = n_samples / fs

    if not np.isfinite(period_s) or period_s <= 0:
        # No period was measurable. Fall back on the span itself, which is
        # the only length scale left, and let the caller's confidence
        # reading say why the answer is weak.
        period_s = span_s / 10.0

    segment_seconds = max(1.0 / fs, period_s / SEGMENTS_PER_PERIOD)

    # At least eight segments over the span or the trend string is too
    # short for a run-length rule to find anything in.
    segment_seconds = min(segment_seconds, span_s / 8.0)

    detrend_window_s = DETREND_PERIODS * period_s
    # A detrend window at or beyond half the span stops being a high pass
    # and becomes a mean subtraction.
    detrend_window_s = min(detrend_window_s, span_s / 2.0)
    detrend_window_s = max(detrend_window_s, 3.0 / fs)

    derived = dict(segment_seconds=float(segment_seconds),
                   detrend_window_s=float(detrend_window_s))
    derived.update(overrides)
    return derived


@dataclass
class AutotuneResult:
    """The converged parameters and the whole road to them.

    `trace` carries one entry per pass so the fixed point is inspectable:
    a period that stopped moving is only evidence if you can see it stop.
    """
    period_s: float
    confidence: float
    params: object = None
    events: list = field(default_factory=list)
    morphology: str = None
    result: object = None
    trace: list = field(default_factory=list)
    converged: bool = False
    seed_period_s: float = float("nan")

    @property
    def confident(self):
        return self.confidence >= CONFIDENCE_GATE


def autotune(x, fs, max_passes=3, tol=CONVERGENCE_TOL, params_factory=None,
             **overrides):
    """Seed the period from the ACF, then refine it from the detections.

    Each pass: derive parameters from the current period, detect, and
    replace the period with the median interval between consecutive
    onsets. Stop when the period moves by less than `tol` relatively, or
    when a pass finds fewer than two events (one interval is not a median
    and iterating on it would be superstition).

    Imported late because `detect5` imports nothing from here and the
    dependency would otherwise be circular; keeping the arrow one-way
    means `detect5` stays usable with hand-set parameters, which is what
    the tests assert against.
    """
    from .detect5 import Detect5Params, detect_drops5

    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)

    seed_period, confidence = dominant_period(x, fs)
    period = seed_period
    factory = params_factory or (lambda **kw: Detect5Params(**kw))

    trace = []
    passes = []
    converged = False

    for index in range(max(1, int(max_passes))):
        params = factory(**derive_params(period, fs, len(x), **overrides))
        result = detect_drops5(x, fs, params)

        onsets = np.array([e.onset_idx for e in result.events], dtype=float)
        if onsets.size >= 2:
            measured = float(np.median(np.diff(onsets)) / fs)
        else:
            measured = float("nan")

        entry = dict(
            pass_index=index,
            period_s=float(period),
            segment_seconds=params.segment_seconds,
            detrend_window_s=params.detrend_window_s,
            n_events=len(result.events),
            measured_interval_s=measured,
            morphology=result.morphology,
        )
        trace.append(entry)
        passes.append((entry, params, result))

        if not np.isfinite(measured) or measured <= 0:
            # Fewer than two events. The period cannot be refined and
            # re-running the same parameters would only repeat this, so
            # stop rather than burn the remaining passes.
            break

        relative_change = abs(measured - period) / max(period, 1e-12)
        period = measured
        if relative_change < tol:
            converged = True
            break

    # The BEST pass wins, not the last one.
    #
    # The iteration is not guaranteed to have a fixed point and on a
    # strongly modulated train it demonstrably does not: on an eight-cycle
    # train ramped 700 s -> 350 s the event count goes 2, 7, 3, 7, 6 as the
    # period ping-pongs between two basins. Taking the last pass there
    # returns whichever half of the oscillation the budget happened to end
    # on, which is arbitrary in the worst way - it looks like an answer.
    #
    # Event count is the right score because the gates do not move between
    # passes: the same slope threshold, the same rise gate and the same
    # dominance gate reject the same junk whatever the segment length, so
    # a pass that returns MORE events past identical gates has found more
    # real events rather than been more permissive.
    best_entry, best_params, best_result = max(
        passes, key=lambda item: (item[0]["n_events"], -item[0]["pass_index"]))

    refined = best_entry["measured_interval_s"]
    if not np.isfinite(refined) or refined <= 0:
        refined = best_entry["period_s"]
    best_entry["selected"] = True

    return AutotuneResult(
        period_s=float(refined),
        confidence=float(confidence),
        params=best_params,
        events=list(best_result.events),
        morphology=best_result.morphology,
        result=best_result,
        trace=trace,
        converged=converged,
        seed_period_s=float(seed_period),
    )
