"""
detect.py
==========
Find every spike-drop in one span of one channel.

The shape being detected
------------------------
A spike here is a slow rise followed by a fast fall and a slower recovery
- the Izhikevich-style "perturbation from a trajectory and gradual reset
to the original trajectory". This module locates the FALL: the first
strongly negative-going sample after a rise. It does not locate the spike;
it locates the sub-shape, so that the sub-shape can be asked the question
the whole spike has already been asked elsewhere in this repo - does it
recur, and is its vocabulary small?

The pipeline, and why each step is there
----------------------------------------
    1. rolling-mean detrend        remove slow baseline drift
    2. dSAX trend encoding (k=3)   D / S / U per segment
    3. regex over the letters      every maximal run of U is a rise
    4. derivative scan after each  the first steep fall is the drop onset
    5. depth + separation filters  one event per real event, no noise

Step 2 uses `threshold_mode="quantile"`, NOT the `learned` default, and
that is the single most consequential choice in this module. dSAX's
learned cutlines are Lloyd-Max optimal against the observed delta
distribution. On a spiking recording that distribution is dominated by the
rare, enormous drop deltas, and the MSE-optimal answer is a SAME band wide
enough to swallow 99% of segments - INCLUDING the entire rise. Measured on
Mushroom_260720 the learned SAME fraction is 0.98-0.99 and the letters
around a real icicle read `SSSSSSSSDSSSSSS`: the fall is classified, the
rise never is, and "the first fall after a rise" therefore matches
nothing. Quantile mode sets the band by OCCUPANCY instead, which is
scale-free with respect to how big the drops are, and the same icicle
reads `SSSUDDUDDU` - a rise, then the fall. See
`Pipelines/drop_motifs/README.md` for the measured comparison.

A second, free benefit: quantile mode touches no RNG at all (dSAX's own
"Determinism" note), so detection is reproducible without depending on
anybody remembering to seed. The random seed is still recorded in the
manifest, because the clustering step downstream does consume one.

The negative-slope threshold
-----------------------------
"Within a negative slope threshold" needs a number, and the number has to
mean the same thing on a 4-hour recording whose drops are 12 mV over 4
seconds and on a 721-hour one whose drops are 45 mV over 7 minutes. It is
built here as a NOISE-FLOOR criterion:

    slope_threshold = -slope_sigma * robust_sigma(d/dt x_detrended)

with `robust_sigma` a MAD estimate. The MAD rather than the standard
deviation is essential and not a stylistic preference: on this data the
rare huge drops ARE the outliers, so an sd-based scale is set by the very
events being looked for and the threshold walks away from the noise it is
supposed to describe. `tests/test_drop_motifs_detect.py` pins that
property directly.

The work order suggested deriving the threshold from dSAX's own learned
DOWN cutline instead, to avoid a second free parameter. That reasoning
holds for `learned` mode, where the cutline is a magnitude. Under
`quantile` mode the cutline is an occupancy quantile and carries no
information about how steep "steep" is, so it cannot serve. The MAD
estimate is the replacement, and `slope_sigma` reads directly as a claim:
"the fall is at least this many times steeper than noise alone produces".

Every rejected candidate is counted. A span that produces no events must
be distinguishable from a span nobody ran (work order 1.8), so `counts`
is part of the result rather than a log line.

No matplotlib, Panel, HoloViews or Bokeh - CLAUDE.md rule 1.
"""

import re
import time
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d

from Working.Detection.sax.dsax_python.dsax import dsax, dsax_letters

# dSAX's 3-symbol alphabet is DOWN / SAME / UP; `dsax_letters` renders it
# as D / S / U, which is what makes a rise a regex rather than a loop.
ALPHABET_SIZE = 3
TREND_ESTIMATOR = "ols_slope"
THRESHOLD_MODE = "quantile"

# Consumed only by the clustering step downstream, but recorded here so
# one manifest describes the whole run.
DEFAULT_SEED = 20260819

# MAD -> sigma for a Gaussian. Standard constant, spelled out rather than
# hidden so the estimator is auditable.
_MAD_TO_SIGMA = 1.4826

# How the noise floor behind the slope threshold is estimated. See
# `slope_noise_sigma` - the choice matters most on dense spike trains,
# where the naive one measures the events instead of the noise.
NOISE_SECOND_DIFFERENCE = "second_difference"
NOISE_GRADIENT = "gradient"
NOISE_ESTIMATORS = (NOISE_SECOND_DIFFERENCE, NOISE_GRADIENT)

# Fallback noise floor for a signal with no measurable noise at all, as a
# fraction of its amplitude range per sample. Only ever reached on
# synthetic or heavily-smoothed input; see `_floor_noise`.
_NOISELESS_FLOOR_FRAC = 1e-3

# The second-difference noise estimate is floored at this fraction of the
# gradient estimate. Across the six shipped spans the two sit within 0.6x
# to 1.25x of each other, so at 1/100 this binds only on a signal with no
# broadband noise at all. See `slope_noise_sigma`.
_SMOOTH_SIGNAL_FLOOR_RATIO = 0.01


@dataclass(frozen=True)
class DetectionParams:
    """Every knob, in physical units, in one object.

    Physical units rather than samples throughout: the two recordings this
    was built for share fs=1 Hz today, but a parameter set expressed in
    samples silently means something different the moment one does not,
    and these values are quoted in a data card.
    """

    # -- preprocessing ----------------------------------------------------
    detrend_window_s: float
    # Rolling-mean window. Long relative to noise, comparable to one spike:
    # too short and the spike is treated as drift and removed, too long and
    # the drift survives into the trend alphabet. Validated by eye per
    # recording; the chosen values and the reasoning are in
    # Pipelines/drop_motifs/README.md.

    segment_seconds: float
    # dSAX segment duration. Must be short enough that the rise spans
    # several segments and the fall lands in its own.

    # -- trend alphabet ---------------------------------------------------
    same_fraction: float = 0.6
    # Target SAME occupancy for quantile mode: the fraction of segments
    # called "no meaningful change". Reads directly as an assumption about
    # how much of the recording is quiescent.

    merge_gap_segments: int = 0
    # Bridge runs of up to this many S between two U runs into one rise.
    # 0 (the default) treats `UUSUU` as two rises, which is what the bare
    # regex does. Raise it when a rise has a genuine plateau part-way up.

    # -- the drop ---------------------------------------------------------
    slope_sigma: float = 8.0
    # Onset threshold in robust sigmas of the per-sample derivative's
    # NOISE. 8 rather than the 6 this started at: the noise estimate is
    # now correctly de-scaled for a central difference (see
    # `slope_noise_sigma`), which lowered it by sqrt(2), so 8 here lands
    # on much the same physical threshold as 6 did before while the
    # number now means what it says.

    noise_estimator: str = NOISE_SECOND_DIFFERENCE
    # Which noise floor the threshold is built on. The default measures
    # noise; `"gradient"` measures the typical slope and silently
    # collapses on dense spike trains. See `slope_noise_sigma`.

    lookahead_mult: float = 3.0
    # How far past an UP region the onset scan may run, in multiples of
    # that region's own duration. Bounded rather than unbounded so a rise
    # at the very end of a span cannot walk off the data or hang.

    trough_knee_frac: float = 0.05
    # The fall is over once its slope has recovered to this fraction of
    # its own steepest. See `find_trough` - this is what stops the trough
    # search running on into the next cycle's deeper minimum, and it is
    # what makes "the most vertical drop" a measurable quantity rather
    # than a description.

    min_depth_frac: float = 0.10
    # A candidate is kept when its fall depth is at least this fraction of
    # the DEEPEST fall found in the same span. Relative rather than
    # absolute so one number works on a 12 mV recording and a 45 mV one;
    # self-calibrating, and the rejected depths are reported so the cut is
    # arguable rather than silent.

    min_separation_s: float = 0.0
    # Two onsets closer than this are the same event seen from several UP
    # regions; the deeper survives. 0 disables dedup, which is correct
    # where the rise-to-drop mapping is already 1:1 (M2_aug's sharkfins).

    # -- the stored window ------------------------------------------------
    pre_context_mult: float = 2.0
    post_context_mult: float = 4.0
    # Snippet extent, in multiples of the fall's own duration, before the
    # onset and after the trough. Anchored on the FALL rather than on the
    # rise because the fall is the motif; a rise-anchored window is 15
    # minutes wide on M2_aug and 4 seconds wide on Mushroom, which stores
    # the recovery on one recording and truncates it on the other.

    random_seed: int = DEFAULT_SEED


@dataclass(frozen=True)
class DropEvent:
    """One drop, self-describing.

    Indices are relative to the array passed to `detect_drops`;
    `store.write_run` shifts them by the span offset so what lands on disk
    indexes the whole channel. Carrying the parameters on the event as
    well as in the manifest is deliberate: the event table is the data
    card's raw material, and a row whose provenance lives only in a
    separate file is a row that will eventually be quoted without it.
    """

    up_region_start_idx: int
    up_region_end_idx: int
    onset_idx: int
    trough_idx: int
    onset_slope_raw: float
    drop_depth_mv: float
    fall_duration_s: float
    peak_to_peak_mv: float
    snippet_start_idx: int
    snippet_end_idx: int
    detrend_window_s: float
    segment_seconds: float
    same_fraction: float
    slope_sigma: float
    dsax_threshold_mode: str = THRESHOLD_MODE
    dsax_trend_estimator: str = TREND_ESTIMATOR


@dataclass
class DetectionResult:
    events: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    x_detrended: np.ndarray = None
    params: DetectionParams = None

    @property
    def empty(self):
        return not self.events


# -- primitives ------------------------------------------------------------

def robust_sigma(values):
    """MAD-based standard deviation estimate.

    Used for the noise floor rather than `np.std` because on a spiking
    recording the events are the outliers, and an sd-based noise estimate
    is therefore set by the very thing it is meant to be a floor beneath.
    Measured on 5000 Gaussian samples with 1% replaced by a huge constant,
    the sd triples and this moves by under 5%.
    """
    values = np.asarray(values, dtype=float).ravel()
    if values.size == 0:
        return 0.0
    mad = float(np.median(np.abs(values - np.median(values))))
    return _MAD_TO_SIGMA * mad


def slope_noise_sigma(x, fs, estimator=NOISE_SECOND_DIFFERENCE):
    """Robust sd of the per-sample derivative UNDER NOISE ALONE.

    `slope_sigma` claims to mean "this many times steeper than noise
    alone produces", and that claim is only true if the estimate here
    measures noise rather than signal. Which estimator delivers that
    depends on the recording's duty cycle, and the difference is not
    small:

      "gradient"          MAD of `np.gradient(x)` directly. Correct while
                          events are RARE, because then most samples sit
                          on quiet baseline and the MAD sees baseline.
                          It fails as the duty cycle rises: on the 14x
                          sharkfin span (14 events filling 1.97 h) more
                          than half of all samples lie on an event slope,
                          so the MAD reports the typical EVENT slope,
                          0.0387 mV/s. Six of those is -0.232 mV/s -
                          steeper than the steepest sample anywhere in
                          the span (-0.186), so the detector found 14
                          rises and zero drops. Nothing raised; the span
                          simply came back empty.

      "second_difference" MAD of `np.diff(x, 2)`, the default. A second
                          difference annihilates any locally linear
                          trend, so a smooth event slope contributes
                          nothing and only broadband noise survives. On
                          the same span it returns 0.0221 mV/s and the
                          drops are found. On the already-validated spans
                          it changes almost nothing: Mushroom_260720 goes
                          26 events to 27, and M2_aug's 16-from-16 match
                          against annotation 11266 is unchanged.

    Scaling, both factors of which matter:
      - `/ sqrt(6)` because Var(x[i+1] - 2x[i] + x[i-1]) = 6*sigma^2 for
        white noise, so the raw second-difference MAD overstates the
        amplitude noise by sqrt(6);
      - `/ sqrt(2)` because the quantity actually thresholded is
        `np.gradient`, a central difference, whose noise sd is
        sigma_amplitude / sqrt(2), not sigma_amplitude.
    Dropping either would leave `slope_sigma` meaning some other number
    of sigmas than the one written on it.
    """
    x = np.asarray(x, dtype=float).ravel()
    if x.size < 3:
        return 0.0
    if estimator not in NOISE_ESTIMATORS:
        raise ValueError(
            f"unknown noise estimator {estimator!r} - must be one of "
            f"{NOISE_ESTIMATORS}")

    fs = float(fs)
    gradient_sigma = robust_sigma(np.gradient(x)) * fs
    if estimator == NOISE_GRADIENT:
        return _floor_noise(gradient_sigma, x, fs)

    amplitude_sigma = robust_sigma(np.diff(x, 2)) / np.sqrt(6.0)
    sigma = float(amplitude_sigma / np.sqrt(2.0) * fs)

    # Guard, not an estimate. A second difference annihilates any locally
    # linear trend, so on a PIECEWISE-LINEAR signal it is zero almost
    # everywhere and its MAD reports float round-off rather than noise -
    # at which point the threshold admits every downward sample and the
    # detector starts reporting detrend edge artefacts as drops.
    #
    # Any signal with real broadband noise has the two estimators within a
    # small factor of each other: measured across the six shipped spans
    # the ratio second/gradient runs 0.6 to 1.25. A hundredfold gap is not
    # a noisier or quieter recording, it is a signal with no noise in it,
    # so the floor below binds only there and never on real data.
    floor = gradient_sigma * _SMOOTH_SIGNAL_FLOOR_RATIO
    return _floor_noise(max(sigma, floor), x, fs)


def _floor_noise(sigma, x, fs):
    """Never return a noise floor of zero.

    A zero floor makes `slope_sigma` meaningless - the threshold becomes
    0 and the first non-increasing sample after every rise is called a
    drop. Where no noise is measurable, the fallback is a small fraction
    of the signal's own amplitude range per sample, which is not a noise
    estimate and does not pretend to be: it is a guard that keeps the
    comparison well-defined on a signal that has no noise to measure.
    """
    if sigma > 0.0:
        return float(sigma)
    span = float(np.ptp(x))
    if span <= 0.0:
        return 0.0          # genuinely constant; the caller short-circuits
    return float(span * _NOISELESS_FLOOR_FRAC * fs)


def detrend(x, window_samples):
    """Rolling-mean high pass.

    `mode="nearest"` rather than the default so the first and last
    half-window are detrended against the data that is there rather than
    against an implied zero, which would otherwise manufacture an edge
    step big enough to register as a drop.
    """
    x = np.asarray(x, dtype=float).ravel()
    window = max(3, int(round(window_samples)))
    if window >= len(x):
        # A window at or beyond the span's length is a mean subtraction;
        # doing it explicitly avoids uniform_filter1d's edge behaviour
        # dominating the whole result.
        return x - float(x.mean())
    return x - uniform_filter1d(x, size=window, mode="nearest")


def dim_ratio_for_segments(n_samples, segment_samples):
    """dSAX's `floor(dim_ratio * n)` arithmetic, inverted.

    The `+ 0.5` is the same guard `Adapters._sax_common.segment_plan` uses
    against a boundary floor landing one segment short. Done inline rather
    than imported: `Working/` must not depend on `Adapters/` (see
    `dsax._letter`'s note on the same rule), and the exact round-trip
    guarantee `segment_plan` provides is not needed here - nothing
    downstream compares this to a persisted encoding-view artifact.
    """
    n_segments = max(2, int(round(n_samples / float(segment_samples))))
    return (n_segments + 0.5) / float(n_samples)


def merge_up_runs(letters, max_gap):
    """Bridge `U S{1,max_gap} U` into one run of U.

    Whether a lone S between two U runs is one rise with a plateau or two
    rises is genuinely ambiguous, so it is a parameter rather than a
    decision. `max_gap=0` is the identity and is the default, matching the
    bare `U+` regex. A D is never bridged: a fall between two rises is two
    rises by definition, whatever its length.
    """
    max_gap = int(max_gap)
    if max_gap <= 0:
        return letters
    pattern = re.compile(r"U(S{1,%d})(?=U)" % max_gap)
    previous = None
    # Repeated until stable so a chain `U S U S U` collapses fully; one
    # pass leaves the second gap unbridged because the first consumed the
    # U that would have anchored it.
    while previous != letters:
        previous = letters
        letters = pattern.sub(lambda m: "U" * (len(m.group(0))), letters)
    return letters


def up_regions(letters):
    """Every maximal run of U, as `(start_segment, end_segment)` half-open.

    This is the payoff of dSAX rendering its encoding as a string: finding
    every rise is one regex, not a state machine.
    """
    return [(m.start(), m.end()) for m in re.finditer(r"U+", letters)]


def find_drop_onset(derivative, from_idx, slope_threshold, lookahead):
    """First sample at or past `from_idx` whose slope is at or below
    `slope_threshold`, or None within `lookahead` samples.

    Deliberately the FIRST crossing and not the steepest: one UP region
    produces at most one drop candidate, which is what stops a long fall
    generating a string of identifications along its length. The bound is
    what stops a rise at the very end of a span scanning off the data.
    """
    hi = min(len(derivative), from_idx + max(1, int(lookahead)))
    if hi <= from_idx:
        return None
    hits = np.flatnonzero(derivative[from_idx:hi] <= slope_threshold)
    if hits.size == 0:
        return None
    return from_idx + int(hits[0])


def find_trough(derivative, onset, limit, knee_frac=0.05, hysteresis=3):
    """The foot of the STEEP fall - where the slope has recovered to
    `knee_frac` of its steepest, not where the signal is lowest.

    This is the operator's own framing taken seriously: "we are only
    interested in the most vertical drop at the start of the drop". The
    two obvious alternatives both fail, and both failed here before this
    rule replaced them:

      argmin over the search window. On M2_aug the window after a
      sharkfin's onset spans several multiples of a 15-minute rise, which
      is long enough to reach the NEXT cycle's minimum. Measured fall
      durations came back as 344 / 457 / 665 / ... / 1763 s for what is
      visibly the same event shape, the stored snippet swallowed two
      whole cycles, and the overlay showed a train of spikes instead of
      one drop. Nothing raises; the figure is simply wrong.

      a prominence rule on the LEVEL (stop once the signal has climbed
      back a fraction of the depth so far). Correct on M2_aug and wrong
      on Mushroom_260720, where a tiny running depth means any upward
      noise sample ends the walk immediately: median measured depth fell
      from 1.62 mV to 0.31 mV and a third of the real icicles were then
      rejected as too shallow.

    A knee on the SLOPE has neither failure. It is scale-free by
    construction - `knee_frac` is a fraction of this event's own steepest
    slope, so it means the same thing on a 4-second icicle and a
    3-minute sharkfin - and it terminates where the vertical part of the
    fall does, whatever the signal does afterwards. Measured with
    knee_frac=0.05: Mushroom falls at 5-13 s, M2_aug at 124-196 s, with
    no runaway on either.

    `hysteresis` consecutive samples must satisfy the condition, so one
    noisy sample part-way down cannot end the fall.
    """
    hi = min(len(derivative), int(limit))
    if hi <= onset + 2:
        return min(onset, len(derivative) - 1)

    window = derivative[onset:hi]
    steepest = int(np.argmin(window))
    threshold = knee_frac * float(window[steepest])   # negative * fraction

    hysteresis = max(1, int(hysteresis))
    run = 0
    for i in range(steepest + 1, len(window)):
        if window[i] > threshold:
            run += 1
            if run >= hysteresis:
                return onset + i - hysteresis + 1
        else:
            run = 0
    return hi - 1


# -- the detector ----------------------------------------------------------

def detect_drops(x, fs, params):
    """Every spike-drop in `x`.

    `x` is in the recording's native units (volts here); amplitudes on the
    returned events are in mV, matching `motif_report.transform_snippet`'s
    convention so the numbers are comparable to the existing figures.
    """
    started = time.time()
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)

    counts = {
        "samples": int(len(x)),
        "segments": 0,
        "up_regions": 0,
        "candidates": 0,
        "drops_confirmed": 0,
        "rejected_no_slope": 0,
        "rejected_shallow": 0,
        "rejected_duplicate": 0,
    }

    x_detrended = detrend(x, params.detrend_window_s * fs)

    # A span with no variation at all has no trend to encode. dSAX handles
    # it (its `_all_same_cutlines` path) but the quantile cutlines collapse
    # onto each other and the result is meaningless rather than merely
    # empty, so it is short-circuited here and reported as such.
    if len(x_detrended) < 4 or float(np.ptp(x_detrended)) == 0.0:
        counts["degenerate_span"] = True
        return DetectionResult(events=[], counts=counts,
                               diagnostics={"reason": "span is constant",
                                            "elapsed_s": time.time() - started},
                               x_detrended=x_detrended, params=params)

    segment_samples = max(2, int(round(params.segment_seconds * fs)))
    ratio = dim_ratio_for_segments(len(x_detrended), segment_samples)

    np.random.seed(int(params.random_seed))   # no-op in quantile mode; see header
    symbols, details = dsax(
        x_detrended, len(x_detrended), ratio,
        alphabet_size=ALPHABET_SIZE,
        trend_estimator=TREND_ESTIMATOR,
        threshold_mode=THRESHOLD_MODE,
        same_fraction=params.same_fraction,
        return_details=True,
    )
    letters = merge_up_runs(dsax_letters(symbols, ALPHABET_SIZE),
                            params.merge_gap_segments)

    sps = int(details["samples_per_symbol"])
    segment_starts = np.asarray(details["segment_starts"], dtype=int)
    segment_ends = np.asarray(details["segment_ends"], dtype=int)
    counts["segments"] = int(details["n_symbols"])

    # The derivative is taken on the DETRENDED signal so the drift the
    # detrend removed cannot leak back in through the slope. It is kept in
    # per-SAMPLE units here because that is what the sample-by-sample scan
    # compares; the noise sigma is converted to match.
    derivative = np.gradient(x_detrended)
    sigma_slope = slope_noise_sigma(x_detrended, 1.0,
                                    estimator=params.noise_estimator)
    slope_threshold = -float(params.slope_sigma) * sigma_slope

    regions = up_regions(letters)
    counts["up_regions"] = len(regions)

    candidates = []
    for seg_start, seg_end in regions:
        up_start = int(segment_starts[seg_start])
        up_end = int(segment_ends[seg_end - 1])
        up_duration = max(up_end - up_start, sps)
        lookahead = int(round(params.lookahead_mult * up_duration))

        onset = find_drop_onset(derivative, up_end, slope_threshold, lookahead)
        if onset is None:
            counts["rejected_no_slope"] += 1
            continue

        tail = min(len(x_detrended), onset + lookahead)
        if tail <= onset + 1:
            counts["rejected_no_slope"] += 1
            continue

        trough = find_trough(derivative, onset, tail,
                             knee_frac=params.trough_knee_frac)
        depth = float(x_detrended[onset] - x_detrended[trough])
        candidates.append({
            "up_start": up_start, "up_end": up_end, "onset": onset,
            "trough": trough, "depth": depth,
            "slope": float(derivative[onset]),
        })

    counts["candidates"] = len(candidates)
    if not candidates:
        counts["slope_threshold_raw"] = slope_threshold
        return DetectionResult(events=[], counts=counts,
                               diagnostics=_diagnostics(details, sigma_slope,
                                                        slope_threshold, started),
                               x_detrended=x_detrended, params=params)

    # -- depth filter -----------------------------------------------------
    # Relative to the deepest fall in this span, so one setting works
    # across recordings whose drops differ by a factor of four in mV.
    deepest = max(c["depth"] for c in candidates)
    kept = [c for c in candidates if c["depth"] >= params.min_depth_frac * deepest]
    counts["rejected_shallow"] = len(candidates) - len(kept)

    # -- separation filter, deepest wins ----------------------------------
    # Same shape as `family_search.dedupe_matches` / `motif_report.
    # enforce_separation`, with depth in the role distance plays there.
    separation = params.min_separation_s * fs
    if separation > 0:
        survivors = []
        for candidate in sorted(kept, key=lambda c: -c["depth"]):
            if all(abs(candidate["onset"] - other["onset"]) >= separation
                   for other in survivors):
                survivors.append(candidate)
        counts["rejected_duplicate"] = len(kept) - len(survivors)
        kept = survivors
    kept.sort(key=lambda c: c["onset"])

    events = [_build_event(c, x, x_detrended, fs, params, sps) for c in kept]
    counts["drops_confirmed"] = len(events)
    counts["slope_threshold_raw"] = slope_threshold

    return DetectionResult(events=events, counts=counts,
                           diagnostics=_diagnostics(details, sigma_slope,
                                                    slope_threshold, started),
                           x_detrended=x_detrended, params=params)


def _build_event(candidate, x, x_detrended, fs, params, sps):
    onset, trough = candidate["onset"], candidate["trough"]
    fall = max(trough - onset, sps)

    start = max(0, onset - int(round(params.pre_context_mult * fall)))
    end = min(len(x), trough + int(round(params.post_context_mult * fall)))

    window = x[start:end]
    peak_to_peak = float(np.ptp(window)) * 1000.0 if window.size else 0.0

    return DropEvent(
        up_region_start_idx=candidate["up_start"],
        up_region_end_idx=candidate["up_end"],
        onset_idx=onset,
        trough_idx=trough,
        onset_slope_raw=candidate["slope"],
        drop_depth_mv=candidate["depth"] * 1000.0,
        fall_duration_s=(trough - onset) / fs,
        peak_to_peak_mv=peak_to_peak,
        snippet_start_idx=start,
        snippet_end_idx=end,
        detrend_window_s=params.detrend_window_s,
        segment_seconds=params.segment_seconds,
        same_fraction=params.same_fraction,
        slope_sigma=params.slope_sigma,
    )


def _diagnostics(details, sigma_slope, slope_threshold, started):
    """The dSAX-side numbers worth carrying into the manifest.

    `same_fraction_observed` against the requested `same_fraction` is the
    check that the quantile cutlines did what was asked; a large gap means
    the delta distribution has ties (a saturated or dead channel) and the
    encoding is not describing what it appears to.
    """
    return {
        "samples_per_symbol": int(details["samples_per_symbol"]),
        "n_symbols": int(details["n_symbols"]),
        "same_fraction_observed": float(details["same_fraction_observed"]),
        "cutlines_raw_mv": [float(c) * 1000.0 for c in details["cutlines_raw"]],
        "cutlines_degenerate": bool(details["cutlines_degenerate"]),
        "sigma_slope_mv_per_s": float(sigma_slope) * 1000.0,
        "slope_threshold_mv_per_s": float(slope_threshold) * 1000.0,
        "elapsed_s": round(time.time() - started, 3),
    }


def params_as_dict(params):
    """`DetectionParams` -> a JSON-safe dict for the manifest."""
    return {k: (float(v) if isinstance(v, float) else v)
            for k, v in asdict(params).items()}
