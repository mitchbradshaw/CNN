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

# Both time-scaled parameters key off the FEATURE WIDTH, not the period.
#
# This was measured against the six hand-tuned presets and the period lost
# badly. Segment length as a fraction of each quantity:
#
#     span                  width  seg_hand  seg/width   seg/period
#     mushroom_icicles         10         2       0.20       0.0014
#     m2aug am16              235       120       0.51       0.041
#     m2aug sharkfin14         81        20       0.25       0.039
#     m2aug furrycaterpillar  159        20       0.13       0.020
#     m2aug growing           759       120       0.16       0.022
#     m2aug troughtrain       378        60       0.16       0.072
#
# Against the period the ratio spreads 51x and is not a rule; against the
# width it spreads 4x and clusters at ~0.2. The reason is structural: a
# period is the spacing BETWEEN events and a segment has to resolve the
# INSIDE of one. The two coincide only at a high duty cycle. Mushroom is
# the counter-example that makes it obvious - ~50 s icicles spaced ~1400 s
# apart, where period/8 gives a 175 s segment, the icicle is smaller than
# one segment, and the detector returns zero events on a recording with
# twenty-six of them.
SEGMENTS_PER_FEATURE = 5.0          # width / 5; reproduces Mushroom's 2.0 s

# Detrend window as a multiple of the same width. The constraint is
# one-sided and asymmetric in cost: too short and the rolling mean tracks
# the event and deletes it, which is SILENT; too long and some drift
# survives into the trend alphabet, which is visible in the figure. The
# hand-tuned spans sit at 4.7x to 19x the width (median 12.5), excluding
# furrycaterpillar at 0.75x, whose width is inflated by the rolling hill
# it rides on rather than measuring its own 0.3 mV tooth.
DETREND_FEATURES = 10.0

# Where the autocorrelation is judged to have left its central lobe. Half
# height is the standard reading of a lobe width and needs no tuning.
FEATURE_LEVEL = 0.5

# A segment must also be small against the SPACING, or a whole cycle lands
# in one symbol. Only binds where the width estimate is inflated by
# structure slower than the event.
SEGMENTS_PER_INTERVAL = 8.0

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


def feature_width(x, fs, level=FEATURE_LEVEL):
    """Width of the autocorrelation's central lobe, in seconds.

    How wide the typical FEATURE is, as distinct from how far apart
    features are. The lag at which the ACF has fallen to half height is
    the standard reading of a lobe width and takes no parameter beyond
    the level itself.

    This is the quantity both derived parameters key off; see the
    `SEGMENTS_PER_FEATURE` comment for the measurement that chose it over
    the period.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    n = len(x)
    if n < 16:
        return float("nan")

    x = x - _rolling_mean(x, max(3, n // 10))
    x = x - x.mean()
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(x, size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    if acf[0] <= 0:
        return float("nan")
    acf = acf / acf[0]

    below = np.flatnonzero(acf <= level)
    return float(below[0] / fs) if below.size else float(n / fs)


def derive_params(feature_width_s, fs, n_samples, interval_s=None,
                  **overrides):
    """The parameter dict implied by one feature width.

    Only the two genuinely time-scaled parameters are derived. Everything
    else in `Detect5Params` is dimensionless by construction -
    `slope_sigma` is a multiple of the noise, `min_depth_frac` a fraction
    of the deepest fall, the window multipliers fractions of the fall -
    which is precisely why those did NOT need per-recording tuning in the
    shipped detector and these two did.

    `interval_s`, when known, caps the segment from the other side: a
    segment must be small against the spacing as well as against the
    event, and on a span whose width estimate is inflated by slow
    structure the spacing is the binding constraint.
    """
    fs = float(fs)
    span_s = n_samples / fs

    if not np.isfinite(feature_width_s) or feature_width_s <= 0:
        # Nothing measurable. The span is the only length scale left; the
        # caller's confidence reading is what says the answer is weak.
        feature_width_s = span_s / 50.0

    segment_seconds = feature_width_s / SEGMENTS_PER_FEATURE
    if interval_s and np.isfinite(interval_s) and interval_s > 0:
        segment_seconds = min(segment_seconds,
                              interval_s / SEGMENTS_PER_INTERVAL)

    # Never below TWO samples - a trend estimator needs two points to fit
    # a slope through and dSAX raises rather than guessing. Never so large
    # that the trend string is too short for a run-length rule to find
    # anything in.
    segment_seconds = max(2.0 / fs, segment_seconds)
    segment_seconds = min(segment_seconds, span_s / 8.0)

    detrend_window_s = DETREND_FEATURES * feature_width_s
    # At or beyond half the span a detrend window stops being a high pass
    # and becomes a mean subtraction.
    detrend_window_s = min(detrend_window_s, span_s / 2.0)
    # And it must stay well above the segment, or the trend it removes is
    # the trend the encoder is trying to read.
    detrend_window_s = max(detrend_window_s, 4.0 * segment_seconds, 3.0 / fs)

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
    feature_width_s: float = float("nan")
    seed_width_s: float = float("nan")
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
    """Choose a scale by trying several and measuring, then refine it.

    Two phases, because they answer different questions.

    PHASE 1 - which scale. The ACF lobe width and the ACF period are two
    independent readings of the signal's scale and the ratio between them
    is not a constant: measured across the shipped spans it runs 2.2x
    (troughtrain) to 140x (mushroom, whose icicles are tiny against their
    spacing). A single seed is therefore a bet, and on catalogue ID 20 the
    width bet loses outright - four sharkfins in the span, an ACF high
    pass that is a large fraction of one period, a lobe width of 61 s
    against a real event of several hundred, and zero events found on a
    recording annotated "4x sharkfin sequence". So all three candidates
    are tried and the scorer picks.

    PHASE 2 - refine it. From the best seed's own measured event extent,
    iterating until the width stops moving. This is what handles a
    frequency-modulated train, where no stationary estimator can be right
    and a median measured extent still can.

    Keeping them separate matters: an earlier version ran the seeds and
    the refinement out of one budget, so three seeds consumed all three
    passes and NO refinement ever ran. Two spans that had been exact
    (16/16 and 14/14) dropped to 11 and 13.

    Scoring is by event count among ADMISSIBLE passes only - see the
    admissibility note below. Imported late because `detect5` imports
    nothing from here and the dependency would otherwise be circular.
    """
    from .detect5 import Detect5Params, detect_drops5

    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)

    seed_period, confidence = dominant_period(x, fs)
    seed_width = feature_width(x, fs)
    factory = params_factory or (lambda **kw: Detect5Params(**kw))

    trace = []
    passes = []

    def run(width, interval, phase, index):
        params = factory(**derive_params(width, fs, len(x),
                                         interval_s=interval, **overrides))
        result = detect_drops5(x, fs, params)

        onsets = np.array([e.onset_idx for e in result.events], dtype=float)
        measured_interval = (float(np.median(np.diff(onsets)) / fs)
                             if onsets.size >= 2 else float("nan"))
        # The event's own core extent - the same kind of quantity the ACF
        # lobe width estimates, measured directly instead of inferred from
        # the shape of a correlogram.
        extents = [(e.trough_idx - e.up_region_start_idx)
                   if e.up_region_start_idx >= 0
                   else 2 * (e.trough_idx - e.onset_idx)
                   for e in result.events]
        measured_width = (float(np.median(extents) / fs)
                          if extents else float("nan"))

        # Events must not overlap each other. If the typical spacing is
        # shorter than the typical event, the "events" are fragments of
        # one thing and the pass is describing its own segmentation rather
        # than the signal - which is what a too-fine segment produces, and
        # which would otherwise WIN the scoring by returning the most of
        # them. Measured on the modulated fixture, an inadmissible pass
        # reported a 3 s median spacing against a 122 s event.
        admissible = bool(result.events) and (
            len(result.events) < 2
            or not np.isfinite(measured_interval)
            or measured_interval >= measured_width)

        entry = dict(phase=phase, pass_index=index,
                     feature_width_s=float(width),
                     segment_seconds=params.segment_seconds,
                     detrend_window_s=params.detrend_window_s,
                     n_events=len(result.events),
                     measured_width_s=measured_width,
                     measured_interval_s=measured_interval,
                     morphology=result.morphology,
                     admissible=admissible)
        trace.append(entry)
        passes.append((entry, params, result))
        return entry

    def best_of(items):
        """Most events, among admissible passes; earliest breaks a tie.

        Count is a sound score because the gates do not move between
        passes: the same slope threshold, rise gate and dominance gate
        reject the same junk whatever the segmentation, so more events
        past identical gates means more found rather than more admitted.
        """
        usable = [i for i in items if i[0]["admissible"]] or items
        return max(usable, key=lambda i: (i[0]["n_events"],
                                          -i[0]["pass_index"]))

    # -- phase 1: the candidate scales ------------------------------------
    seeds = []
    for value in [seed_width, seed_period / 6.0 if seed_period > 0 else None,
                  seed_period / 12.0 if seed_period > 0 else None]:
        if (value is not None and np.isfinite(value) and value > 0
                and not any(abs(value - kept) < 1e-9 for kept in seeds)):
            seeds.append(float(value))
    if not seeds:
        seeds = [len(x) / fs / 50.0]

    for index, width in enumerate(seeds):
        run(width, None, "seed", index)

    # -- phase 2: refine from the best seed --------------------------------
    entry = best_of(passes)[0]
    width = entry["measured_width_s"]
    interval = entry["measured_interval_s"]
    converged = False

    for step in range(max(0, int(max_passes) - 1)):
        if not np.isfinite(width) or width <= 0:
            break
        entry = run(width, interval, "refine", len(seeds) + step)
        nxt = entry["measured_width_s"]
        if not np.isfinite(nxt) or nxt <= 0:
            break
        relative_change = abs(nxt - width) / max(width, 1e-12)
        width, interval = nxt, entry["measured_interval_s"]
        if relative_change < tol:
            converged = True
            break

    best_entry, best_params, best_result = best_of(passes)
    best_entry["selected"] = True

    refined_interval = best_entry["measured_interval_s"]
    if not np.isfinite(refined_interval) or refined_interval <= 0:
        refined_interval = seed_period
    refined_width = best_entry["measured_width_s"]
    if not np.isfinite(refined_width) or refined_width <= 0:
        refined_width = best_entry["feature_width_s"]

    return AutotuneResult(
        period_s=float(refined_interval),
        feature_width_s=float(refined_width),
        seed_width_s=float(seed_width),
        confidence=float(confidence),
        params=best_params,
        events=list(best_result.events),
        morphology=best_result.morphology,
        result=best_result,
        trace=trace,
        converged=converged,
        seed_period_s=float(seed_period),
    )
