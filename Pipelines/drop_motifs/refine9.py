"""
refine9.py
===========
Four corrections to drop_motifs9's output, applied as a POST-PROCESSING
pass over a finished motif store. Written for the operator's review of
`example_case_study/`, and intended as the trial run for drop_motifs10.

Why post-processing and not a new detector
------------------------------------------
Every fix below is a statement about a detection that already exists -
where its marks really sit, whether it is a copy of its neighbour, whether
it is big enough to be real. None of them needs the detector re-run, and
all of them can be measured against the existing store, which is what
makes the effect of each one visible rather than asserted. Detection
itself is untouched, so drop_motifs9's counts remain reproducible and this
module's effect is exactly the difference between two stores.

Each event is refined USING ITS OWN STORED SNIPPET, not a re-derived
window. That matters: the passes use different detrend windows, so an
event found by `micro` was decided on a different trace from one found by
`base`, and refining both against one re-derived trace would move marks
onto a signal the detector never saw.

--------------------------------------------------------------------------
1. THE SAME DROP IS ONE DROP  (the operator: "m3 and m4 are referencing
   the same drop", and the same for m6/m7, m8/m9, m10/m11, m13/m14)
--------------------------------------------------------------------------
This is a real bug and it reaches the store: 61 pairs of stored motifs
share a channel AND a trough sample, and 79 more sit within two samples of
each other.

The cause is in `passes6.deduplicate`, which drop_motifs9 inherits through
`passes7.detect_multiscale`:

    tolerance = onset_frac * max(float(fall_s), float(kept_fall))

That is a duration in SECONDS compared against a difference in SAMPLE
INDICES. `passes8` found and fixed exactly this, but the fix lives in
`passes8.deduplicate`, and `passes9` only ever calls it for the
CROSS-WINDOW merge - within a window the unfixed `passes6` rule still
runs. Every recording drop_motifs5-8 was validated on is 1 Hz, where the
two quantities are numerically equal and the bug is invisible. Fig2A is
10 Hz, so the tolerance comes out ten times too small and two detections
one sample apart are not recognised as one event.

Concretely, CH1 window 36: `base` finds onset 9063 -> trough 9069 and
`fine` finds onset 9064 -> trough 9069. Tolerance as computed is
0.5 x 0.6 = 0.3 "samples"; the onsets differ by 1, so both survive.
Multiplied by fs it is 3 samples, and they merge.

`dedup_same_drop` below restores the fs and adds a second test the onset
rule cannot make: TWO DETECTIONS THAT BOTTOM OUT AT THE SAME PLACE ARE ONE
DROP, whatever their onsets. That catches the nested case - `base`
9161 -> 9175 against `fine` 9163 -> 9165 - where a later pass has found a
sub-fall inside an earlier pass's event.

--------------------------------------------------------------------------
2. WHERE THE FALL ACTUALLY STARTS AND ENDS  (the operator, on several
   panels: "the peak is earlier - at the beginning of the identified
   steepest sample")
--------------------------------------------------------------------------
THE ONSET. The detector's onset is where its slope gate first fired, which
on a rounded shoulder is part-way down the fall. The operator's rule is
better and is what a reader means by "the peak": walk back from the
steepest sample while the trace is still descending, and stop at the first
sample that is not. That is the local maximum the fall departs from.

THE TROUGH. The detector's trough is the minimum sample, which on a noisy
floor is wherever the deepest wiggle happens to land. The operator's rule
- "the first point at which the gradient is positive again, above a
threshold, for a period above a threshold" - is implemented literally:
scan forward from the steepest sample for the first run of
`RISE_RUN_SAMPLES` consecutive samples whose gradient is at least
`RISE_SIGMA` times the snippet's own slope noise. The fall ends where the
recovery begins.

Both rules are bounded, and if either fails to find a mark the event keeps
the detector's own. Nothing is invented; a refusal to refine is recorded.

--------------------------------------------------------------------------
3. A MOTIF IS ONE DROP, NOT A TRAIN  (the operator: "the resulting motifs
   extend to include multiple humps")
--------------------------------------------------------------------------
The stored snippet is the detector's window, sized in multiples of the
fall. On a train of rounded humps that window spans several of them, so
the family overlays show a sequence where they should show one event.

After the marks are refined the snippet is RE-CUT around them -
`SNIPPET_PRE_MULT` falls before the onset, `SNIPPET_POST_MULT` after the
trough - so a motif carries its own drop plus enough context to read it
and no more. This only ever shrinks a snippet: the re-cut is clipped to
what was stored, so no sample is invented.

--------------------------------------------------------------------------
4. THE NOISE FLOOR IS A REAL FLOOR  (the operator: known noise floor
   0.1 mV; "the found motif families should only be displaying single drop
   events")
--------------------------------------------------------------------------
`depth_gate` drops any event whose refined depth is at or below
`MIN_DROP_DEPTH_MV`. On the drop_motifs9 store that is 38% of the
population, and it is the population the rounded-hump sequences live in.

A LOW-PASS FILTER WAS CONSIDERED AND NOT USED, deliberately. It would
suppress the same humps, but it would also change every gradient the rose
reports, and the angle measurement is the one quantity in this pipeline
with no independent check on it. The depth gate rejects the same events
without touching a single sample of signal, and keeps the preprocessing at
one step - a detrend - which is worth protecting.

NOTE THE TENSION, because it is not resolvable by tuning: the operator
also reports MISSED drops ("a slight drop between m2 and m3 which is not
recognised"). A depth floor makes shallow misses more likely, not less.
These are the same disagreement seen from two sides, and the honest
position is that 0.1 mV is a claim about the instrument that the figures
should state, not hide.
"""

import numpy as np

from Pipelines.drop_motifs.passes6 import DEDUP_ONSET_FRAC
from Pipelines.drop_motifs.passes7 import PASS_ORDER

# The operator's stated instrument noise floor, in mV. An event at or below
# this is not distinguishable from the baseline and is not reported.
MIN_DROP_DEPTH_MV = 0.1

# "positive again, above a threshold, for a period above a threshold" -
# the two thresholds, in units of the snippet's own slope noise and in
# samples. 0.5 sigma is deliberately lenient: this mark ends a fall, it
# does not decide whether the fall was real, and a strict gate here would
# run the trough far past the actual bottom on a slow recovery.
RISE_SIGMA = 0.5
RISE_RUN_SAMPLES = 3

# How far back the onset walk may go, as a multiple of the detector's own
# fall length. Bounded so a long shallow descent cannot drag the onset to
# the start of the snippet.
ONSET_LOOKBACK_MULT = 2.5

# Context kept either side of the refined marks, in multiples of the
# refined fall. Enough to see the drop depart from and return to baseline;
# not enough to reach the next hump.
SNIPPET_PRE_MULT = 1.2
SNIPPET_POST_MULT = 1.8
MIN_CONTEXT_SAMPLES = 3

# Two detections whose troughs are within this many samples are the same
# drop. Small and absolute: a trough is a point, not an interval, and
# scaling this by the fall would let a long event swallow a short
# neighbour that genuinely bottoms out elsewhere.
TROUGH_TOLERANCE_SAMPLES = 2

_MAD_TO_SIGMA = 1.4826


def slope_sigma(derivative):
    """MAD-based sigma of a derivative, matching the detector's estimator."""
    derivative = np.asarray(derivative, dtype=float)
    finite = derivative[np.isfinite(derivative)]
    if finite.size < 4:
        return 0.0
    mad = np.median(np.abs(finite - np.median(finite)))
    return float(_MAD_TO_SIGMA * mad)


def refine_marks(values, fs, onset, trough, *, rise_sigma=RISE_SIGMA,
                 rise_run=RISE_RUN_SAMPLES,
                 lookback_mult=ONSET_LOOKBACK_MULT):
    """Re-place one event's onset and trough on its own trace.

    Returns `(onset, trough, info)`. `info["onset_moved"]` /
    `["trough_moved"]` record whether each rule fired, so a run can report
    how much of the store it actually changed rather than claiming all of
    it.
    """
    values = np.asarray(values, dtype=float).ravel()
    n = values.size
    onset = int(np.clip(onset, 0, max(n - 1, 0)))
    trough = int(np.clip(trough, 0, max(n - 1, 0)))
    info = {"onset_moved": 0, "trough_moved": 0, "refused": 0}
    if n < 5 or trough <= onset:
        info["refused"] = 1
        return onset, trough, info

    derivative = np.gradient(values) * float(fs)
    sigma = slope_sigma(derivative)
    steepest = onset + int(np.argmin(derivative[onset:trough + 1]))

    # -- the onset: walk back to the top of the fall ----------------------
    limit = max(0, steepest - int(round(lookback_mult * (trough - onset))))
    new_onset = steepest
    while new_onset > limit and derivative[new_onset - 1] < 0.0:
        new_onset -= 1
    # A walk that hits its bound has not found a peak; keep the detector's.
    if new_onset <= limit and derivative[max(new_onset - 1, 0)] < 0.0:
        new_onset = onset
    if new_onset != onset:
        info["onset_moved"] = 1

    # -- the trough: the first sustained recovery -------------------------
    cut = rise_sigma * sigma
    new_trough = trough
    if sigma > 0 and rise_run >= 1:
        for i in range(steepest + 1, n - rise_run + 1):
            if np.all(derivative[i:i + rise_run] >= cut):
                new_trough = i
                break
    if new_trough != trough:
        info["trough_moved"] = 1

    if new_trough <= new_onset:
        info["refused"] = 1
        return onset, trough, info
    return int(new_onset), int(new_trough), info


FIELDS = ("raw_mv", "detrended_mv", "t_s")


def is_nested(store):
    """True for `{event_id: {field: array}}`, false for `{id__field: array}`.

    `motifs5.load_store` hands back the nested form; `rows_and_arrays` and
    `write_store` use the flat one. Both arrive here depending on whether a
    caller is refining a finished store or a fresh detection, and silently
    accepting the wrong one is what made the first run of this module
    refuse all 1736 events without saying why.
    """
    for value in store.values():
        return isinstance(value, dict)
    return True


def flatten_snippets(nested):
    """`{event_id: {field: array}}` -> `{event_id__field: array}`.

    `motifs5.write_store` takes the flat form.
    """
    flat = {}
    for event_id, fields in nested.items():
        for name, values in fields.items():
            flat[f"{event_id}__{name}"] = values
    return flat


def refine_row(row, snippets, *, pre_mult=SNIPPET_PRE_MULT,
               post_mult=SNIPPET_POST_MULT, **kwargs):
    """Refine one store row in place and re-cut its snippet.

    `snippets` is the NESTED form. Returns `(new_fields, info)`, or
    `(None, info)` when the event could not be refined and is left exactly
    as it was.
    """
    event_id = row["event_id"]
    fields = snippets.get(event_id)
    if not fields:
        return None, {"refused": 1, "onset_moved": 0, "trough_moved": 0}
    detrended = fields.get("detrended_mv")
    raw = fields.get("raw_mv")
    t_s = fields.get("t_s")
    if detrended is None or raw is None or t_s is None:
        return None, {"refused": 1, "onset_moved": 0, "trough_moved": 0}

    fs = float(row["fs"])
    start = int(row["snippet_start_idx"])
    local_onset = int(row["onset_idx"]) - start
    local_trough = int(row["trough_idx"]) - start

    onset, trough, info = refine_marks(detrended, fs, local_onset,
                                       local_trough, **kwargs)
    if info["refused"]:
        return None, info

    # -- re-cut, only ever inwards ---------------------------------------
    fall = max(trough - onset, 1)
    lo = max(0, onset - max(int(round(pre_mult * fall)), MIN_CONTEXT_SAMPLES))
    hi = min(len(detrended),
             trough + max(int(round(post_mult * fall)), MIN_CONTEXT_SAMPLES) + 1)
    if hi - lo < 4:
        return None, {**info, "refused": 1}

    new_fields = {
        "detrended_mv": np.asarray(detrended)[lo:hi],
        "raw_mv": np.asarray(raw)[lo:hi],
        "t_s": np.asarray(t_s)[lo:hi],
    }

    values = np.asarray(detrended, dtype=float)
    derivative = np.gradient(values) * fs
    steepest = onset + int(np.argmin(derivative[onset:trough + 1]))
    depth = float(values[onset] - values[trough])

    row["onset_idx"] = int(start + onset)
    row["trough_idx"] = int(start + trough)
    row["snippet_start_idx"] = int(start + lo)
    row["snippet_end_idx"] = int(start + hi)
    row["fall_duration_s"] = float((trough - onset) / fs)
    row["drop_depth_mv"] = depth
    row["onset_slope_raw"] = float(derivative[onset]) / 1000.0
    row["max_slope_raw"] = float(derivative[steepest]) / 1000.0
    row["peak_to_peak_mv"] = float(np.ptp(values[lo:hi]))
    row["pre_context_s"] = float((onset - lo) / fs)
    row["post_context_s"] = float((hi - trough) / fs)
    row["refined"] = 1
    return new_fields, info


def dedup_same_drop(rows, *, onset_frac=DEDUP_ONSET_FRAC,
                    trough_tol=TROUGH_TOLERANCE_SAMPLES):
    """One row per real drop. Returns `(kept, n_dropped, reasons)`.

    Three tests, all within one channel:

      1. ONSET proximity, scaled by the fall AND by fs - the `passes6`
         rule with the sampling rate restored.
      2. TROUGH coincidence - two detections that bottom out at the same
         sample are one drop however their onsets differ. This is the test
         `passes6` never had and the one that catches a later pass's
         sub-fall nested inside an earlier pass's event.
      3. CONTAINMENT - one event's whole onset..trough interval lying
         inside another's.

    Priority is pass order, then the deeper event, so when two descriptions
    of one drop disagree the earlier pass and the fuller excursion win.
    """
    order = {key: i for i, key in enumerate(PASS_ORDER)}
    ranked = sorted(rows, key=lambda r: (order.get(r.get("pass_key"), 99),
                                         -abs(float(r["drop_depth_mv"])),
                                         int(r["onset_idx"])))
    kept, reasons = [], {"onset": 0, "trough": 0, "containment": 0}
    by_channel = {}
    for row in ranked:
        channel = int(row["channel"])
        onset, trough = int(row["onset_idx"]), int(row["trough_idx"])
        fall = float(row.get("fall_duration_s", 0.0))
        fs = float(row["fs"])
        hit = None
        for other in by_channel.get(channel, ()):
            tolerance = max(onset_frac * max(
                fall, float(other.get("fall_duration_s", 0.0))) * fs, 1.0)
            other_on = int(other["onset_idx"])
            other_tr = int(other["trough_idx"])
            if abs(onset - other_on) <= tolerance:
                hit = "onset"
            elif abs(trough - other_tr) <= trough_tol:
                hit = "trough"
            elif (onset >= other_on and trough <= other_tr) or \
                 (other_on >= onset and other_tr <= trough):
                hit = "containment"
            if hit:
                break
        if hit:
            reasons[hit] += 1
            continue
        by_channel.setdefault(channel, []).append(row)
        kept.append(row)

    kept.sort(key=lambda r: (int(r["channel"]), int(r["onset_idx"])))
    return kept, len(rows) - len(kept), reasons


def depth_gate(rows, min_depth_mv=MIN_DROP_DEPTH_MV):
    """Drop events at or below the instrument noise floor."""
    kept = [r for r in rows
            if abs(float(r["drop_depth_mv"])) > float(min_depth_mv)]
    return kept, len(rows) - len(kept)


def refine_store(rows, snippets, *, min_depth_mv=MIN_DROP_DEPTH_MV,
                 refine=True, dedup=True, gate=True, **kwargs):
    """The whole pass. Returns `(rows, snippets, report)`.

    `snippets` may arrive in either form - nested, as `motifs5.load_store`
    returns it, or flat, as `write_store` takes it - and comes back in the
    SAME form it went in.

    Order matters and is: refine the marks, THEN dedup, THEN gate. Refining
    first is what lets the dedup see that two events share a trough - on
    the detector's own marks they often do not - and gating last means the
    depth compared against the floor is the refined one.
    """
    flat_in = not is_nested(snippets)
    if flat_in:
        nested = {}
        for key, values in snippets.items():
            event_id, _, name = key.partition("__")
            nested.setdefault(event_id, {})[name] = values
    else:
        nested = {k: dict(v) for k, v in snippets.items()}

    rows = [dict(r) for r in rows]
    report = {"n_in": len(rows), "onset_moved": 0, "trough_moved": 0,
              "refine_refused": 0}

    if refine:
        for row in rows:
            new_fields, info = refine_row(row, nested, **kwargs)
            report["onset_moved"] += info.get("onset_moved", 0)
            report["trough_moved"] += info.get("trough_moved", 0)
            report["refine_refused"] += info.get("refused", 0)
            if new_fields:
                nested[row["event_id"]] = new_fields
        report["n_after_refine"] = len(rows)

    if dedup:
        rows, n_dropped, reasons = dedup_same_drop(rows)
        report["n_duplicates_dropped"] = int(n_dropped)
        report["duplicate_reasons"] = reasons
    report["n_after_dedup"] = len(rows)

    if gate:
        rows, n_shallow = depth_gate(rows, min_depth_mv)
        report["n_below_noise_floor"] = int(n_shallow)
        report["min_depth_mv"] = float(min_depth_mv)
    report["n_out"] = len(rows)

    keep = {r["event_id"] for r in rows}
    nested = {k: v for k, v in nested.items() if k in keep}
    return rows, (flatten_snippets(nested) if flat_in else nested), report
