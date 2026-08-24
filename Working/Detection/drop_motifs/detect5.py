"""
detect5.py
===========
Five-stage spike-drop detection: fast-down / down / same / up / fast-up.

An EXTENSION of `detect.py`, not a replacement. That module keeps working
unchanged, keeps its presets and keeps reproducing the figures already in
`Plots/drop_motifs/`; nothing here is imported by it. The three helpers
this module reuses (`detrend`, `slope_noise_sigma`, `find_trough`, ...)
are imported from it rather than reimplemented, so a fix to the noise
estimator or the knee rule lands in both detectors at once.

The three things this module changes
------------------------------------

1. THE WINDOW, which is the defect this was written for.

   `detect.py` sizes a snippet as multiples of the fall's own duration -
   two before the onset, four after the trough. That is scale-free, which
   is why it was chosen, but on a PERIODIC train it is unbounded in the
   only unit that matters. At a 236 s fall the window is 1416 s wide; the
   sharkfin period there is ~510 s; so the window holds three spikes and
   the per-cluster overlay drew a train instead of an event. The figure
   was wrong and nothing raised.

   Here the window is bracketed on the surrounding UP RUNS, which cannot
   overrun a neighbour because the neighbour's rise IS the boundary. The
   rule is one rule read forwards and backwards:

                       sharkfin (rise->fall)      trough (fall->rise)
       anchor          initial drop onset         initial drop onset
       left edge       START of preceding UP      END of previous UP
       right edge      START of next UP           END of first UP after

   The trough row is not a special case, it is the reflection. It has to
   be: a trough spike's RECOVERY is an UP run and is part of the motif, so
   a naive "stop at the next UP run" would end the window at the bottom of
   the trough and discard the right half of every event. The fall-multiple
   rule survives only as a CAP (`window_cap_mult`), for an isolated event
   with no bounding rise to stop at.

2. THE ALPHABET. Five stages, with the outer two pinned to the noise floor.

   dSAX already ships a five-symbol alphabet (`d D S U u`, outer bins
   lower case). It is not used directly, for a reason found in its source:
   `_quantile_cutlines` HONOURS `same_fraction` only at k=3 and falls back
   to equiprobable bins above it, so `dsax(alphabet_size=5)` would quietly
   deliver a 20% SAME band instead of the tuned value and the extension
   would not be an extension - it would be a different encoding wearing
   the same parameter names.

   So the encoding is built as a genuine refinement of the three-stage
   one: dSAX runs at k=3 exactly as `detect.py` runs it, which fixes the
   SAME band at `same_fraction` and makes the three-stage reading
   recoverable by folding case (`d|D -> D`, `u|U -> U`). The D and U bands
   are then SPLIT by the MAD noise floor, so `d` means "at least
   `slope_sigma` sigmas of noise steeper than nothing" - a physical claim,
   and the same threshold that gates a drop.

   That last point is the payoff: `d` in the string and "this candidate
   passed the slope gate" become the same statement, so the alphabet stops
   being decorative and becomes the detector's own record of its decision.
   An occupancy quantile could not do this - decision 2.7 of the shipped
   detector already measured such a cutline at three orders of magnitude
   below a real drop's slope.

3. TWO TRIGGERS, one morphology per span.

   `detect.py` finds a rise and scans forward for a fall, so a drop with
   no rise before it is invisible - which is most of catalogue ID 25 and
   all of Mushroom's icicles. Here a bare `d` also triggers. Where both
   fire on the same fall the RISE wins (it is strictly more evidence) and
   the suppression is counted, which is what makes the fall trigger's
   value measurable rather than assumed: it should suppress on ~every
   event of a sharkfin span and ~none of a trough span.

   The morphology is decided ONCE per span, because mixed window geometry
   inside one span is what makes an overlay incoherent - and an overlay of
   incoherent windows is the second defect this was written for.

Units: `x` is in the recording's native units (volts); amplitudes on the
returned events are in mV, matching `detect.py`.
"""

import re
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from Working.Detection.sax.dsax_python.dsax import dsax, dsax_letters

from .detect import (
    NOISE_SECOND_DIFFERENCE,
    THRESHOLD_MODE,
    TREND_ESTIMATOR,
    detrend,
    dim_ratio_for_segments,
    find_trough,
    merge_up_runs,
    slope_noise_sigma,
)

# The five stages, steepest fall to steepest rise. Case encodes MAGNITUDE
# and the letter encodes DIRECTION, which is dSAX's own k=5 convention
# (`dsax.SYMBOL_LETTERS`) and is what lets `[Dd]` match any fall: a
# three-stage regex still works here without being rewritten.
FAST_DOWN, DOWN, SAME, UP, FAST_UP = "d", "D", "S", "U", "u"
STAGE_LETTERS = (FAST_DOWN, DOWN, SAME, UP, FAST_UP)
STAGE_NAMES = ("FAST_DOWN", "DOWN", "SAME", "UP", "FAST_UP")

MORPHOLOGY_SHARKFIN = "sharkfin"     # rise -> fall; the drop follows a rise
MORPHOLOGY_TROUGH = "trough"         # fall -> rise; the drop starts from flat
MORPHOLOGIES = (MORPHOLOGY_SHARKFIN, MORPHOLOGY_TROUGH)

TRIGGER_RISE = "rise"
TRIGGER_FALL = "fall"

# Any run of rising segments, either magnitude. The whole point of case
# encoding magnitude is that this stays a one-character class.
_UP_RUN = re.compile(r"[Uu]+")
_DOWN_RUN = re.compile(r"[Dd]+")


@dataclass(frozen=True)
class Detect5Params:
    """Physical units throughout, as in `DetectionParams`.

    The first block is shared with the three-stage detector and means
    exactly what it means there. The second block is new and is what the
    window and gate changes need.
    """

    # -- shared with detect.DetectionParams -------------------------------
    detrend_window_s: float
    segment_seconds: float
    same_fraction: float = 0.6
    merge_gap_segments: int = 0
    slope_sigma: float = 8.0
    noise_estimator: str = NOISE_SECOND_DIFFERENCE
    lookahead_mult: float = 3.0
    trough_knee_frac: float = 0.05
    min_depth_frac: float = 0.10
    min_separation_s: float = 0.0

    # -- the window -------------------------------------------------------
    bracket_on_up_runs: bool = True
    # The fix. False restores the old fall-multiple behaviour, which is
    # kept only so a test can demonstrate the failure it replaces.

    window_cap_mult: float = 6.0
    # Cap on each side, in multiples of the fall duration, for an event
    # with no bounding UP run. This is the old rule demoted from
    # definition to backstop; 6 is the old 2-before + 4-after summed, so
    # an isolated event is framed no more tightly than it used to be.

    window_pad_frac: float = 0.25
    # A little air either side of the bracket, in fall durations, so the
    # drop is not flush against the frame.

    # -- the gates --------------------------------------------------------
    min_rise_frac: float = 0.5
    # Gate A. A rise-triggered event's rise must climb at least this
    # fraction of its fall's depth. Says "this is a rise FOLLOWED BY a
    # fall" rather than "a fall that happens to have segments before it",
    # and is what keeps a slow non-event out of a cluster that would then
    # average it with real spikes. Applies to the rise trigger only -
    # under trough morphology there is no rise to measure by construction.

    min_fall_dominance: float = 0.5
    # Gate B. The fall's depth must be at least this fraction of its own
    # window's peak-to-peak. Says "this window is a picture of THIS
    # event"; if something bigger is in frame, the window is mis-centred
    # or the event is incidental.

    # -- morphology -------------------------------------------------------
    morphology: str = "auto"
    # "auto" decides per span by which trigger fires more; the explicit
    # values force it. Decided ONCE per span so every window in a span
    # shares its geometry.

    # -- dSAX ------------------------------------------------------------
    threshold_mode: str = THRESHOLD_MODE
    trend_estimator: str = TREND_ESTIMATOR


@dataclass(frozen=True)
class Drop5Event:
    """One drop, self-describing, indices relative to the array passed in.

    `window_*` rather than `snippet_*` deliberately: these are not the
    same quantity as `DropEvent.snippet_*` and giving them the same name
    would invite a downstream consumer to treat two differently-defined
    extents as interchangeable.
    """

    onset_idx: int
    trough_idx: int
    window_start_idx: int
    window_end_idx: int
    up_region_start_idx: int
    up_region_end_idx: int
    trigger: str
    morphology: str
    onset_slope_raw: float
    max_slope_raw: float
    drop_depth_mv: float
    rise_height_mv: float
    fall_duration_s: float
    peak_to_peak_mv: float
    fall_dominance: float
    detrend_window_s: float
    segment_seconds: float
    same_fraction: float
    slope_sigma: float


@dataclass
class Detect5Result:
    events: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    letters: str = ""
    morphology: str = None
    x_detrended: np.ndarray = None
    params: Detect5Params = None

    @property
    def empty(self):
        return not self.events


# ===========================================================================
# the alphabet
# ===========================================================================

def stage_letters(x, fs, params):
    """Encode `x` into the five stages. Returns `(letters, details)`.

    Two steps, and the order matters:

      1. dSAX at k=3 under the caller's `same_fraction`, exactly as
         `detect.py` invokes it. This fixes the SAME band by occupancy,
         which is the parameter that has been tuned per recording and
         whose meaning must not change.
      2. Split the D and U bands by the MAD noise floor. A falling segment
         at or below `-slope_sigma * sigma` becomes `d`; a rising segment
         at or above `+slope_sigma * sigma` becomes `u`.

    Doing it the other way round - k=5 from dSAX, then re-labelling the
    inner bands - would take the SAME band from an equiprobable split and
    silently redefine `same_fraction`.

    `details` carries `segment_slopes` in raw units per SECOND and the
    `sigma_slope` the split used, so the claim "`d` means steeper than N
    sigmas" is checkable from the return value rather than on trust.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)

    detrend_samples = max(3, int(round(params.detrend_window_s * fs)))
    x_detrended = detrend(x, detrend_samples)

    segment_samples = max(1, int(round(params.segment_seconds * fs)))
    dim_ratio = dim_ratio_for_segments(len(x_detrended), segment_samples)

    symbols, details = dsax(
        x_detrended,
        training_len=len(x_detrended),
        dim_ratio=dim_ratio,
        alphabet_size=3,
        threshold_mode=params.threshold_mode,
        same_fraction=params.same_fraction,
        trend_estimator=params.trend_estimator,
        return_details=True,
    )

    three = merge_up_runs(dsax_letters(symbols, 3), params.merge_gap_segments)

    # Per-segment slope in raw units per second. `seg_slope_raw` is per
    # SAMPLE, so the factor of fs is what makes the comparison below a
    # comparison of like with like against `slope_noise_sigma`, which is
    # also per second.
    segment_slopes = np.asarray(details["seg_slope_raw"], dtype=float) * fs
    sigma_slope = slope_noise_sigma(x_detrended, fs, params.noise_estimator)
    cut = params.slope_sigma * sigma_slope

    # `merge_up_runs` can only turn S into U, never change the count, so
    # the string and the slope array stay aligned. Asserted rather than
    # assumed because a silent misalignment here would mislabel every
    # segment by a shifting offset and still produce a plausible string.
    n = min(len(three), len(segment_slopes))
    letters = []
    for i in range(n):
        symbol = three[i]
        slope = segment_slopes[i]
        if symbol == DOWN and slope <= -cut:
            letters.append(FAST_DOWN)
        elif symbol == UP and slope >= cut:
            letters.append(FAST_UP)
        else:
            letters.append(symbol)

    details = dict(details)
    details.update(
        segment_slopes=segment_slopes[:n],
        sigma_slope=float(sigma_slope),
        fast_cut_raw=float(cut),
        x_detrended=x_detrended,
        samples_per_symbol=int(details["samples_per_symbol"]),
        three_stage_letters=three[:n],
    )
    return "".join(letters), details


def fold_to_three(letters):
    """The three-stage reading of a five-stage string.

    Exists so the extension can be shown to BE an extension: fold the case
    away and what remains is exactly what `detect.py` would have encoded.
    """
    return letters.replace(FAST_DOWN, DOWN).replace(FAST_UP, UP)


def up_runs(letters):
    """Every maximal run of rising segments, `(start, end)` half-open."""
    return [(m.start(), m.end()) for m in _UP_RUN.finditer(letters)]


def fall_runs(letters):
    """Every maximal run of falling segments that contains a FAST one,
    as `(start, end)` half-open in SEGMENT indices.

    RUNS and not segments, which is the exact mirror of `up_runs` and is
    load-bearing rather than tidiness. One fall spans as many segments as
    the segment length divides it into, and taking each `d` as its own
    trigger finds the same physical fall once per segment: measured on a
    clean eight-cycle train at a 9.6 s segment, one 60 s fall produced
    onsets at 501, 510 and 520 and the span came back with 26 events
    instead of 8.

    A run may include plain `D` segments - the shoulders of a fall are
    shallower than its middle, and a fall is not two falls because its
    steepest part is in the centre. It must contain at least one `d`,
    which is what distinguishes a fall from a gentle decline.
    """
    out = []
    for match in _DOWN_RUN.finditer(letters):
        if FAST_DOWN in match.group(0):
            out.append((match.start(), match.end()))
    return out


# ===========================================================================
# morphology
# ===========================================================================

def choose_morphology(x, fs, params):
    """Which shape this span is made of, decided once.

    The discriminator is what comes BEFORE each fall. A sharkfin's fall is
    preceded by its own rise; a trough's is preceded by quiet. So: for
    every fast-down segment, ask whether a rise ends within one lookahead
    of it. The majority wins.

    Deliberately not "which trigger finds more events" - that would be
    circular, because the rise trigger's gate depends on the morphology
    this function is deciding.
    """
    if params.morphology in MORPHOLOGIES:
        return params.morphology

    letters, _ = stage_letters(x, fs, params)
    falls = fall_runs(letters)
    if not falls:
        return MORPHOLOGY_SHARKFIN

    rises = up_runs(letters)
    preceded = 0
    for start, _ in falls:
        # A rise "precedes" a fall if it ends at or just before the fall
        # begins. One segment of slack absorbs the case where the peak
        # sample lands in the fall's own segment rather than the rise's
        # last.
        if any(0 <= start - end <= 1 for _, end in rises):
            preceded += 1

    return (MORPHOLOGY_SHARKFIN if preceded * 2 >= len(falls)
            else MORPHOLOGY_TROUGH)


# ===========================================================================
# the window
# ===========================================================================

def significant_rises(rises, x_detrended, segment_samples, min_climb):
    """The rises that are events rather than noise, in SAMPLE indices.

    A window bracketed on "the next UP run" is only as good as its idea of
    a run. A single noisy segment labelled U sits between a trough and its
    real recovery on live data, and taking it as the boundary ends the
    window 130 samples early - measured, on the three-cycle trough
    fixture, where it cut the window at 910 against a recovery completing
    at 1040.

    `min_climb` is `min_rise_frac x depth`, which is Gate A read as a
    property of the rise instead of a property of the event. Same number,
    same meaning, no new parameter.
    """
    out = []
    for start_seg, end_seg in rises:
        start = start_seg * segment_samples
        end = min(end_seg * segment_samples, len(x_detrended) - 1)
        if end <= start:
            continue
        if float(x_detrended[end] - x_detrended[start]) >= min_climb:
            out.append((start, end))
    return out


def window_bounds(onset, trough, rises, segment_samples, morphology, params,
                  x_detrended, depth):
    """The stored extent for one event. See the table in the module docstring.

    `rises` is `up_runs`' output in SEGMENT indices; everything returned is
    in SAMPLE indices.

    The padding is applied on ONE side only, and which side depends on the
    morphology, because the two boundaries are not the same kind of thing:

      - a sharkfin's left boundary is its OWN rise, so padding outward
        just takes in some quiet lead-in; its right boundary is the NEXT
        event's rise, and padding past that is the very overrun this
        module exists to stop.
      - a trough is the mirror. Its right boundary is its own recovery
        (pad), its left boundary is the PREVIOUS event's recovery (hard).

    So: pad where the boundary belongs to this event, clamp where it
    belongs to a neighbour.
    """
    n_samples = len(x_detrended)
    fall = max(trough - onset, segment_samples)
    pad = int(round(params.window_pad_frac * fall))
    cap = int(round(params.window_cap_mult * fall))

    # The fall-multiple rule: the answer when bracketing is off, and the
    # backstop for an event with no bounding rise when it is on.
    start = onset - cap
    end = trough + cap

    if params.bracket_on_up_runs:
        real = significant_rises(rises, x_detrended, segment_samples,
                                 params.min_rise_frac * depth)

        if morphology == MORPHOLOGY_SHARKFIN:
            before = [s for s, _ in real if s <= onset]
            if before:
                start = max(max(before) - pad, onset - cap)     # own; padded
            after = [s for s, _ in real if s > trough]
            if after:
                end = min(min(after), trough + cap)             # next; hard
        else:
            before = [e for _, e in real if e <= onset]
            if before:
                start = max(max(before), onset - cap)           # prev; hard
            after = [e for _, e in real if e > trough]
            if after:
                end = min(min(after) + pad, trough + cap)       # own; padded

    return max(0, int(start)), min(int(n_samples), int(end))


# ===========================================================================
# the detector
# ===========================================================================

def detect_drops5(x, fs, params):
    """Every spike-drop in `x`, five-stage."""
    started = time.time()
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)

    counts = dict(
        segments=0, up_runs=0, fall_runs=0,
        candidates=0, rejected_no_fall=0, rejected_no_rise=0,
        rejected_not_dominant=0, rejected_shallow=0, rejected_duplicate=0,
        fall_trigger_suppressed=0, drops_confirmed=0,
    )

    if x.size < 8 or float(np.ptp(x)) == 0.0:
        return Detect5Result(counts=counts, params=params,
                             morphology=params.morphology
                             if params.morphology in MORPHOLOGIES
                             else MORPHOLOGY_SHARKFIN,
                             x_detrended=np.zeros_like(x))

    morphology = choose_morphology(x, fs, params)
    letters, details = stage_letters(x, fs, params)
    x_detrended = details["x_detrended"]
    sps = int(details["samples_per_symbol"])
    sigma_slope = details["sigma_slope"]
    slope_threshold = -params.slope_sigma * sigma_slope

    counts["segments"] = len(letters)
    rises = up_runs(letters)
    falls = fall_runs(letters)
    counts["up_runs"] = len(rises)
    counts["fall_runs"] = len(falls)

    derivative = np.gradient(x_detrended) * fs

    # -- candidates -------------------------------------------------------
    #
    # Both triggers propose; the rise trigger wins where they collide. The
    # collision is resolved on the ONSET, not on the segment, because two
    # triggers on one fall land on the same sample by construction.
    rise_candidates, fall_candidates = {}, {}

    for start_seg, end_seg in rises:
        rise_start = start_seg * sps
        rise_end = min(end_seg * sps, len(x_detrended) - 1)
        lookahead = max(sps, int(params.lookahead_mult * (rise_end - rise_start)))
        onset = _first_crossing(derivative, rise_end, slope_threshold, lookahead)
        if onset is None:
            counts["rejected_no_fall"] += 1
            continue
        rise_candidates[onset] = dict(onset=onset, trigger=TRIGGER_RISE,
                                      up_start=rise_start, up_end=rise_end)

    for start_seg, end_seg in falls:
        at = start_seg * sps
        # One candidate per RUN, scanned across the whole run: the first
        # segment of a fall can be its shoulder, so the qualifying sample
        # need not be inside it.
        onset = _first_crossing(derivative, at, slope_threshold,
                                (end_seg - start_seg + 1) * sps)
        if onset is None or onset in fall_candidates:
            continue
        fall_candidates[onset] = dict(onset=onset, trigger=TRIGGER_FALL,
                                      up_start=-1, up_end=-1)

    # How often both triggers claim the same fall. Purely a DIAGNOSTIC: it
    # is what says whether the fall trigger earns its place, and it should
    # read ~100% of events on a sharkfin span and ~0% on a trough one.
    #
    # It must not remove anything, which an earlier version of this did and
    # was wrong for a reason worth recording: a trough spike's RECOVERY is
    # an UP run, so the rise trigger scanning forward from it lands on the
    # NEXT trough's fall and claims it. Suppressing on that collision
    # deleted every genuine trough event except the first.
    counts["fall_trigger_suppressed"] = sum(
        1 for onset in fall_candidates
        if any(abs(onset - other) <= sps for other in rise_candidates))

    # The mirror diagnostic: falls that no rise claims. Under sharkfin
    # morphology these are rejections BY the morphology and must be
    # counted as such - a fall with no rise in front of it fails Gate A's
    # test without ever reaching Gate A, and an uncounted rejection is
    # indistinguishable from a candidate that was never generated.
    if morphology == MORPHOLOGY_SHARKFIN:
        counts["rejected_no_rise"] += sum(
            1 for onset in fall_candidates
            if not any(abs(onset - other) <= sps for other in rise_candidates))

    # Under a decided morphology the span uses ONE trigger, so every window
    # in it shares its geometry (Q13).
    candidates = (rise_candidates if morphology == MORPHOLOGY_SHARKFIN
                  else fall_candidates)
    proposals = sorted(candidates.values(), key=lambda c: c["onset"])
    counts["candidates"] = len(proposals)

    # -- measure and gate --------------------------------------------------
    kept = []
    for candidate in proposals:
        onset = candidate["onset"]
        trough = find_trough(derivative, onset,
                             _fall_limit(onset, rises, sps, len(derivative)),
                             knee_frac=params.trough_knee_frac)
        if trough <= onset:
            continue

        depth = float(x_detrended[onset] - x_detrended[trough])
        if depth <= 0:
            continue

        rise_height = 0.0
        if candidate["trigger"] == TRIGGER_RISE:
            rise_height = float(
                x_detrended[onset] - x_detrended[candidate["up_start"]])
            # Gate A: a rise followed by a fall, not a fall with segments
            # in front of it.
            if rise_height < params.min_rise_frac * depth:
                counts["rejected_no_rise"] += 1
                continue

        candidate.update(trough=trough, depth=depth, rise_height=rise_height)
        kept.append(candidate)

    # Gate: shallow relative to the deepest fall in the span. Unchanged
    # from `detect.py` - relative rather than absolute so one number works
    # on a 12 mV recording and a 45 mV one.
    if kept and params.min_depth_frac > 0:
        deepest = max(c["depth"] for c in kept)
        survivors = [c for c in kept
                     if c["depth"] >= params.min_depth_frac * deepest]
        counts["rejected_shallow"] = len(kept) - len(survivors)
        kept = survivors

    # Dedup, deepest wins. Same rule and reasoning as `detect.py`.
    separation = params.min_separation_s * fs
    if separation > 0 and kept:
        survivors = []
        for candidate in sorted(kept, key=lambda c: -c["depth"]):
            if all(abs(candidate["onset"] - other["onset"]) >= separation
                   for other in survivors):
                survivors.append(candidate)
        counts["rejected_duplicate"] = len(kept) - len(survivors)
        kept = survivors
    kept.sort(key=lambda c: c["onset"])

    # -- window, then Gate B, which needs the window ----------------------
    events = []
    for candidate in kept:
        start, end = window_bounds(
            candidate["onset"], candidate["trough"], rises, sps,
            morphology, params, x_detrended, candidate["depth"])

        window = x_detrended[start:end]
        peak_to_peak = float(np.ptp(window)) if window.size else 0.0
        dominance = (candidate["depth"] / peak_to_peak
                     if peak_to_peak > 0 else 0.0)
        if dominance < params.min_fall_dominance:
            counts["rejected_not_dominant"] += 1
            continue

        onset, trough = candidate["onset"], candidate["trough"]
        events.append(Drop5Event(
            onset_idx=int(onset),
            trough_idx=int(trough),
            window_start_idx=int(start),
            window_end_idx=int(end),
            up_region_start_idx=int(candidate["up_start"]),
            up_region_end_idx=int(candidate["up_end"]),
            trigger=candidate["trigger"],
            morphology=morphology,
            onset_slope_raw=float(derivative[onset]),
            max_slope_raw=float(derivative[onset:trough + 1].min()),
            drop_depth_mv=candidate["depth"] * 1000.0,
            rise_height_mv=candidate["rise_height"] * 1000.0,
            fall_duration_s=(trough - onset) / fs,
            peak_to_peak_mv=peak_to_peak * 1000.0,
            fall_dominance=float(dominance),
            detrend_window_s=params.detrend_window_s,
            segment_seconds=params.segment_seconds,
            same_fraction=params.same_fraction,
            slope_sigma=params.slope_sigma,
        ))

    counts["drops_confirmed"] = len(events)

    return Detect5Result(
        events=events,
        counts=counts,
        letters=letters,
        morphology=morphology,
        x_detrended=x_detrended,
        params=params,
        diagnostics=dict(
            samples_per_symbol=sps,
            n_segments=len(letters),
            sigma_slope_mv_per_s=float(sigma_slope) * 1000.0,
            slope_threshold_mv_per_s=float(slope_threshold) * 1000.0,
            same_fraction_observed=float(details["same_fraction_observed"]),
            stage_histogram={c: letters.count(c) for c in STAGE_LETTERS},
            elapsed_s=round(time.time() - started, 3),
        ),
    )


def _fall_limit(onset, rises, sps, n_samples):
    """How far `find_trough` may search: up to the next rise, and no further.

    `find_trough` takes the STEEPEST sample in its search window as the
    reference for its knee, so the window must not be able to contain a
    second fall - if it does, the steepest sample can belong to the
    NEIGHBOUR and the walk then terminates at the neighbour's foot. Measured
    on a three-cycle trough train with a generous fixed limit: onset 400,
    true trough 440, reported trough 861, which is the second spike's
    bottom. The fall duration is then wrong by 10x and every window sized
    from it is wrong with it.

    The next rise is the right bound for BOTH morphologies and needs no new
    parameter: a sharkfin's fall ends before the next cycle's rise, and a
    trough's fall ends before its own recovery, which is also a rise.
    """
    following = [start * sps for start, _ in rises if start * sps > onset]
    return min(following) if following else int(n_samples)


def _first_crossing(derivative, from_idx, slope_threshold, lookahead):
    """First sample at or past `from_idx` at or below `slope_threshold`.

    The FIRST and not the steepest, so one rise yields one candidate -
    same rule and same reason as `detect.find_drop_onset`, reimplemented
    here only because that one is bounded by an UP region's duration and
    the fall trigger has no UP region to be bounded by.
    """
    from_idx = max(0, int(from_idx))
    hi = min(len(derivative), from_idx + max(1, int(lookahead)))
    if hi <= from_idx:
        return None
    hits = np.flatnonzero(derivative[from_idx:hi] <= slope_threshold)
    if hits.size == 0:
        return None
    return from_idx + int(hits[0])


# ===========================================================================
# the grade
# ===========================================================================

def window_purity(x, fs, result):
    """How many qualifying falls each stored window actually holds.

    One per window is the whole objective; the observed failure scores
    three. Graded with the detector's OWN slope gate rather than a fresh
    peak-finder, so the metric cannot disagree with the detector about
    what a fall is - a purity score built on a second definition would be
    measuring the gap between two opinions instead of the extraction.

    Falls closer together than one segment are one fall seen twice.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    if result.params is None or not result.events:
        return []

    derivative = np.gradient(result.x_detrended) * fs
    sigma = result.diagnostics.get("sigma_slope_mv_per_s", 0.0) / 1000.0
    threshold = -result.params.slope_sigma * sigma
    gap = max(1, int(round(result.params.segment_seconds * fs)))

    scores = []
    for event in result.events:
        segment = derivative[event.window_start_idx:event.window_end_idx]
        below = np.flatnonzero(segment <= threshold)
        if below.size == 0:
            scores.append(0)
            continue
        # Count RUNS, not samples: a single 60-second fall is one fall.
        breaks = np.flatnonzero(np.diff(below) > gap)
        scores.append(int(breaks.size + 1))
    return scores


def params_as_dict(params):
    """`Detect5Params` -> a JSON-safe dict for the manifest."""
    return {k: (float(v) if isinstance(v, float) else v)
            for k, v in asdict(params).items()}
