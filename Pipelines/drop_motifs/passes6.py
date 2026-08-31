"""
passes6.py
===========
Multi-scale detection: run the five-stage detector more than once over the
same span, at different scales and in both directions, and merge what
comes back into one motif set whose rows say which pass found them.

Why more than one pass
----------------------
The drop_motifs5 run detected at ONE derived scale per span, and the
operator's review of it names the same fault four times over:

  ID 8, 24, 34, 35   overlays are unreadable because motifs an order of
                     magnitude apart in duration are drawn on one axis
  ID 26              most spikes missed; the shape is unusual and the
                     falling edge is not what the detector keys on
  ID 28              most spikes missed on a long span with strong
                     low-frequency structure
  ID 385             the supervisor wants the smaller drops AND the
                     smaller events in the other direction, not only the
                     dominant scale

Those are one fault: a single scale, in a single direction, over a signal
that has structure at several of both. Three passes address it:

    base    the derived scale, exactly as drop_motifs5 ran it. Unchanged
            so every previous number stays reproducible.
    fine    the same detector at a fraction of the derived feature width,
            for the smaller events the base pass frames right past.
    inv     the same detector on -x, so a RISING edge is presented to a
            detector that keys on falls. This is the operator's own
            suggestion for ID 26 and the supervisor's for ID 385.

The passes are merged, not concatenated
---------------------------------------
A fine pass re-finds most of what the base pass found, at a tighter
window. Keeping both would double-count every event, and the pooled
dendrogram would then be reporting the same motif twice as a "family".
`deduplicate` keeps the base pass's version of any event two passes both
found, on the rule that the pass whose derived scale matches the event is
the one that framed it correctly.

Scale bands
-----------
Once the passes are merged a span can hold motifs whose fall durations
differ by 50x. Overlaying those is what made ID 24 and ID 34 unreadable.
`scale_bands` splits a span's motifs into octave bands, but only when the
spread actually warrants it - a span whose durations span less than
`MAX_UNSPLIT_RATIO` stays one band, so a well-behaved span is not split
into pieces to no purpose.

Identity, and not double-counting the library
---------------------------------------------
`motif_key` extends drop_motifs5's `id{cat}_r{rec}_{onset}` with the pass
that found the event. Two things follow, both deliberate:

  - a base-pass motif keeps a DIFFERENT key from a fine-pass motif at the
    same onset, so merging two runs of this pipeline can never silently
    overwrite one with the other; and
  - the key is a pure function of (catalogue, recording, pass, onset
    sample), so re-running the same pass over the same span produces the
    same keys and re-importing is idempotent rather than duplicating.
"""

import numpy as np

from Working.Detection.drop_motifs import motifs5
from Working.Detection.drop_motifs.autoparams import autotune, derive_params
from Working.Detection.drop_motifs.detect5 import (Detect5Params,
                                                   detect_drops5,
                                                   window_purity)

PASS_BASE = "base"
PASS_FINE = "fine"
PASS_SENS = "sens"
PASS_INV = "inv"

PASS_ORDER = (PASS_BASE, PASS_FINE, PASS_SENS, PASS_INV)

PASS_LABELS = {
    PASS_BASE: "base scale",
    PASS_FINE: "fine scale",
    PASS_SENS: "relaxed slope gate",
    PASS_INV: "inverted (rising edges)",
}

# The ladder of divisors the fine pass tries against the base feature
# width. It is a ladder rather than one number because measurement said so:
# the divisor that finds the most clean new events is 2 on ID 385, 32 on
# ID 24, and none at all on ID 28, where every finer scale finds FEWER
# events than the base pass. A fixed divisor would have been three
# different wrong answers.
FINE_DIVISORS = (2.0, 4.0, 8.0, 16.0, 32.0)

# The ladder of slope gates the sensitive pass tries, high to low. The
# shipped gate is 8 sigma above the noise; a span whose events are gentle
# rather than sharp is invisible to it. Measured on the two spans the
# operator flagged as under-detecting:
#
#   ID 26   8 sigma -> 2 events; 2 sigma -> 9 events, all windows clean
#   ID 28   8 sigma -> 19 events; 6 sigma -> 22 events, 95% clean
#
# Both were diagnosed as detrend problems and neither was: a stronger
# detrend made ID 28 strictly worse (19 -> 11 -> 2 events). The gate was
# the binding constraint in both cases.
SENSITIVE_SIGMAS = (6.0, 4.0, 3.0, 2.0, 1.5)

# A relaxed pass is only admissible while its windows stay clean. Below
# this the pass is finding burst windows rather than events, which is the
# exact defect the purity metric was introduced to catch - so sensitivity
# is bought only where it does not reintroduce it.
SENSITIVE_MIN_PURITY = 0.90

# Two detections are the same event when their onsets fall within this
# fraction of the longer one's fall duration. A fraction rather than a
# fixed number of samples, because the spans here run from 0.2 to 90
# hours and no constant is right for both.
DEDUP_ONSET_FRAC = 0.5

# A span whose fall durations span less than this ratio is NOT split into
# bands. Below 4x the traces still read as one family on one axis, and
# splitting would cost the comparison the overlay exists to make.
MAX_UNSPLIT_RATIO = 4.0

# A band with fewer members than this is merged into its nearest
# neighbour: a panel with one trace in it is not an overlay.
MIN_BAND_MEMBERS = 3


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def motif_key(catalogue_id, recording_id, pass_key, absolute_onset):
    """The library key. Stable, and unique across passes.

    See the module docstring: the pass sits between the recording and the
    onset so that keys sort into pass-major order within a span, and so
    that the same onset found by two passes yields two distinguishable
    rows rather than one row that depends on load order.
    """
    return (f"id{int(catalogue_id):03d}_r{int(recording_id)}"
            f"_{pass_key}_{int(absolute_onset)}")


# ---------------------------------------------------------------------------
# the passes
# ---------------------------------------------------------------------------

def run_base(x, fs, max_passes=3, **overrides):
    """The drop_motifs5 pass, unchanged."""
    return autotune(x, fs, max_passes=max_passes, **overrides)


def _purity_of(x, fs, result):
    """`(clean_fraction, purity_per_event)` for one detection result."""
    if result is None or not result.events:
        return 0.0, []
    purity = window_purity(x, fs, result)
    if not purity:
        return 0.0, []
    return sum(1 for p in purity if p == 1) / len(purity), purity


def run_fine(x, fs, base_width_s, *, divisors=FINE_DIVISORS,
             base_onsets=(), **overrides):
    """The detector at a fraction of the base width, best rung of a ladder.

    `autotune` is deliberately NOT used. Autotuning would re-derive the
    scale from the same autocorrelation and land back on the base answer,
    which is the whole thing this pass exists to look past. The width is
    forced instead.

    The rung is chosen by how many CLEAN events it finds that the base
    pass did not - not by raw count. A finer scale re-finds the base
    pass's own events at a tighter window, so scoring on the total would
    pick whichever rung happened to re-find the most of what we already
    had. Returns `(result, chosen_divisor)`, or `(None, None)` when no
    rung improves on the base pass, which on ID 28 is the right answer.
    """
    width = float(base_width_s)
    if not np.isfinite(width) or width <= 0:
        return None, None

    base_onsets = np.asarray(list(base_onsets), dtype=float)
    best, best_divisor, best_score = None, None, 0

    for divisor in divisors:
        scaled = width / float(divisor)
        if not np.isfinite(scaled) or scaled <= 0:
            continue
        try:
            params = Detect5Params(**derive_params(scaled, fs, len(x),
                                                   **overrides))
            result = detect_drops5(x, fs, params)
        except (ValueError, ZeroDivisionError):
            continue
        if result is None or not result.events:
            continue

        _, purity = _purity_of(x, fs, result)
        score = 0
        for event, falls in zip(result.events, purity):
            if falls != 1:
                continue
            if base_onsets.size:
                tolerance = DEDUP_ONSET_FRAC * max(event.fall_duration_s, 1.0)
                if np.min(np.abs(base_onsets - event.onset_idx)) <= tolerance:
                    continue
            score += 1

        if score > best_score:
            best, best_divisor, best_score = result, float(divisor), score

    return best, best_divisor


def run_sensitive(x, fs, *, sigmas=SENSITIVE_SIGMAS,
                  min_purity=SENSITIVE_MIN_PURITY, max_passes=3, **overrides):
    """The detector with the slope gate relaxed as far as purity allows.

    Walks the ladder and keeps the MOST sensitive rung whose windows are
    still clean, rather than the first rung that finds more events. The
    two are different on ID 26, where purity dips at 4 and 3 sigma and
    recovers at 2 - taking the first improvement would have stopped at a
    gate that finds fewer events and dirtier windows than the one below it.

    Returns `(tuned, sigma)` or `(None, None)`.
    """
    best, best_sigma = None, None
    for sigma in sigmas:
        try:
            tuned = autotune(x, fs, max_passes=max_passes,
                             slope_sigma=float(sigma), **overrides)
        except (ValueError, ZeroDivisionError):
            continue
        if tuned.result is None or not tuned.events:
            continue
        clean, _ = _purity_of(x, fs, tuned.result)
        if clean >= min_purity:
            best, best_sigma = tuned, float(sigma)
    return best, best_sigma


def run_inverted(x, fs, max_passes=3, **overrides):
    """The detector on `-x`, so a rising edge is presented as a fall.

    The arrays STORED for these motifs are the signal as recorded, never
    the negated copy - a library that holds a sign-flipped waveform and
    calls it the recording is a trap for every later consumer. The row
    carries `signal_sign = -1` instead, and the drawing code negates for
    display where comparing shapes requires it.
    """
    return autotune(-np.asarray(x, dtype=float), fs, max_passes=max_passes,
                    **overrides)


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------

def deduplicate(candidates, *, onset_frac=DEDUP_ONSET_FRAC):
    """Drop later-pass detections of an event an earlier pass already has.

    `candidates` is `[(pass_key, sign, onset_idx, trough_idx,
    fall_duration_s, start_idx, end_idx, payload), ...]` in priority order
    - base first. Returns the kept subset, in order.

    TWO rules, because one of them was not enough and the obvious second
    one was too blunt.

    Rule 1, SAME DIRECTION - onset proximity scaled by fall duration. Two
    passes finding the same event land within a fraction of its own length
    of each other. Scaled rather than fixed because the spans here run
    0.2 h to 90 h.

    Rule 2, OPPOSITE DIRECTION - the inverted pass's event peaks where a
    kept drop begins. On a sharkfin the rise and the fall are one physical
    excursion: the rise tops out exactly at the onset of the fall. So an
    inverted detection whose own trough (in inverted space, the peak of
    the rise) coincides with a kept event's onset is that event's leading
    edge, not a new event. Catalogue ID 1 without this rule reported 17
    drops plus 16 "rises" that were the leading edges of those same 17
    drops - 33 motifs describing 17 events.

    Window containment was tried for rule 2 first and rejected by
    measurement: it is true of a sharkfin's rising edge, but ALSO true of
    a genuine upward spike that happens to sit inside a wide quiet window,
    and on ID 385 it deleted 15 of the 17 opposite-direction events the
    supervisor asked for. Peak-meets-onset separates the two because it
    describes what actually makes them one excursion rather than merely
    where they happen to fall.
    """
    kept = []
    for entry in candidates:
        _, sign, onset, trough, fall_s, _, _, _ = entry
        onset, trough, sign = float(onset), float(trough), int(sign)
        duplicate = False

        for _, kept_sign, kept_onset, _, kept_fall, _, _, _ in kept:
            tolerance = onset_frac * max(float(fall_s), float(kept_fall))
            if int(kept_sign) == sign:
                if abs(onset - float(kept_onset)) <= tolerance:
                    duplicate = True
                    break
            elif abs(trough - float(kept_onset)) <= tolerance:
                duplicate = True
                break

        if not duplicate:
            kept.append(entry)
    return kept


# ---------------------------------------------------------------------------
# scale bands
# ---------------------------------------------------------------------------

def scale_bands(durations, *, max_unsplit_ratio=MAX_UNSPLIT_RATIO,
                min_members=MIN_BAND_MEMBERS):
    """Split motifs into octave bands by fall duration.

    Returns `(band_index_per_motif, band_labels)`. A single band is
    returned - and every motif assigned to it - when the durations span
    less than `max_unsplit_ratio`, because splitting a coherent set costs
    the comparison the overlay is for.

    Octaves rather than a clustering: an octave boundary is a stated,
    reproducible rule that a reader can check against the axis, whereas a
    k-means on durations moves its own boundaries when one motif is added.
    """
    durations = np.asarray(durations, dtype=float)
    n = durations.size
    if n == 0:
        return np.zeros(0, dtype=int), []

    valid = np.isfinite(durations) & (durations > 0)
    if valid.sum() < 2:
        return np.zeros(n, dtype=int), ["all scales"]

    low, high = durations[valid].min(), durations[valid].max()
    if high / low < float(max_unsplit_ratio):
        return np.zeros(n, dtype=int), [_band_label(low, high)]

    octave = np.full(n, np.nan)
    octave[valid] = np.floor(np.log2(durations[valid] / low))
    present = sorted({int(o) for o in octave[valid]})

    # Merge sparse octaves into their nearest populated neighbour, so a
    # band never holds fewer than `min_members`. Walked upwards, because
    # the fine end is where a stray single detection lands.
    counts = {o: int((octave == o).sum()) for o in present}
    merged = {}
    anchor = present[0]
    for value in present:
        if counts[value] < min_members and value != anchor:
            merged[value] = merged.get(anchor, anchor)
        else:
            merged[value] = value
            anchor = value
    # A leading sparse band has no earlier neighbour; fold it forwards.
    if counts[present[0]] < min_members and len(present) > 1:
        target = merged[present[1]]
        for value, mapped in list(merged.items()):
            if mapped == present[0]:
                merged[value] = target

    order = sorted({merged[o] for o in present})
    index = {value: i for i, value in enumerate(order)}

    bands = np.zeros(n, dtype=int)
    for i, value in enumerate(octave):
        bands[i] = index[merged[int(value)]] if np.isfinite(value) else 0

    labels = []
    for band in range(len(order)):
        members = durations[(bands == band) & valid]
        labels.append(_band_label(members.min(), members.max())
                      if members.size else "empty")
    return bands, labels


def _band_label(low, high):
    """`"4-17 s"`, or `"12 s"` when a band holds one duration."""
    if not np.isfinite(low) or not np.isfinite(high):
        return "unmeasured"
    if high - low < 0.5:
        return f"{low:.0f} s" if low >= 1 else f"{low:.2g} s"
    return f"{_fmt(low)}-{_fmt(high)} s"


def _fmt(value):
    return f"{value:.0f}" if value >= 1 else f"{value:.2g}"


# ---------------------------------------------------------------------------
# the whole thing, for one span
# ---------------------------------------------------------------------------

def detect_multiscale(x, fs, *, catalogue_id, recording_id, source_file,
                      channel, span_offset=0, span_label=None, span_key=None,
                      max_passes=3, fine=True, sensitive=True, inverted=True,
                      base_overrides=None, fine_overrides=None,
                      sens_overrides=None, inv_overrides=None):
    """Run every enabled pass over one span and return one merged set.

    Returns `(rows, arrays, info)`. `rows` and `arrays` are in exactly the
    shape `motifs5.write_store` takes and `cluster.py` / `gradients.py`
    already read, with three columns added: `pass_key`, `signal_sign` and
    `scale_band`.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    info = {"passes": {}}

    base = run_base(x, fs, max_passes=max_passes, **(base_overrides or {}))
    contributions = []

    base_onsets = []
    if base.result is not None and base.events:
        _, purity = _purity_of(x, fs, base.result)
        contributions.append((PASS_BASE, base.result, purity, +1, x))
        base_onsets = [e.onset_idx for e in base.events]
    info["passes"][PASS_BASE] = _pass_info(base.result, base)

    if fine and np.isfinite(base.feature_width_s) and base.feature_width_s > 0:
        result, divisor = run_fine(x, fs, base.feature_width_s,
                                   base_onsets=base_onsets,
                                   **(fine_overrides or {}))
        if result is not None and result.events:
            _, purity = _purity_of(x, fs, result)
            contributions.append((PASS_FINE, result, purity, +1, x))
        entry = _pass_info(result, None)
        entry["divisor"] = divisor
        info["passes"][PASS_FINE] = entry

    if sensitive:
        tuned, sigma = run_sensitive(x, fs, max_passes=max_passes,
                                     **(sens_overrides or {}))
        if tuned is not None and tuned.events:
            _, purity = _purity_of(x, fs, tuned.result)
            contributions.append((PASS_SENS, tuned.result, purity, +1, x))
        entry = _pass_info(tuned.result if tuned else None, tuned)
        entry["slope_sigma"] = sigma
        info["passes"][PASS_SENS] = entry

    if inverted:
        flipped = -x
        tuned = run_inverted(x, fs, max_passes=max_passes,
                             **(inv_overrides or {}))
        if tuned.result is not None and tuned.events:
            _, purity = _purity_of(flipped, fs, tuned.result)
            contributions.append((PASS_INV, tuned.result, purity, -1, flipped))
        info["passes"][PASS_INV] = _pass_info(tuned.result, tuned)

    # -- one row per detection, then dedup across passes -------------------
    candidates = []
    for pass_key, result, purity, sign, signal in contributions:
        rows, arrays = motifs5.rows_and_arrays(
            result, signal, purity,
            catalogue_id=catalogue_id, recording_id=recording_id, fs=fs,
            source_file=source_file, channel=channel, span_offset=span_offset,
            span_label=span_label, span_key=span_key)
        for row in rows:
            candidates.append((pass_key, sign, row["onset_idx"],
                               row["trough_idx"], row["fall_duration_s"],
                               row["snippet_start_idx"],
                               row["snippet_end_idx"],
                               (row, arrays, sign)))

    kept = deduplicate(candidates)
    info["n_before_dedup"] = len(candidates)
    info["n_after_dedup"] = len(kept)
    info["n_duplicates_dropped"] = len(candidates) - len(kept)

    out_rows, out_arrays = [], {}
    for pass_key, _, _, _, _, _, _, (row, arrays, sign) in kept:
        old_key = row["event_id"]
        new_key = motif_key(catalogue_id, recording_id, pass_key,
                            row["onset_idx"])
        row = dict(row)
        row["event_id"] = new_key
        row["snippet_key"] = new_key
        row["pass_key"] = pass_key
        row["signal_sign"] = int(sign)
        row["scale_band"] = 0
        out_rows.append(row)
        for field in ("raw_mv", "detrended_mv", "t_s"):
            source = arrays.get(f"{old_key}__{field}")
            if source is not None:
                # The inverted pass detected on -x and its arrays were
                # built from -x. Negate the amplitude columns back so the
                # store holds the signal AS RECORDED; `signal_sign` is
                # what tells a consumer which way the event went. `t_s` is
                # a time axis and is never touched.
                if sign < 0 and field != "t_s":
                    source = -np.asarray(source, dtype=float)
                out_arrays[f"{new_key}__{field}"] = source

    bands, labels = scale_bands([r["fall_duration_s"] for r in out_rows])
    for row, band in zip(out_rows, bands):
        row["scale_band"] = int(band)
    info["scale_band_labels"] = labels
    info["n_scale_bands"] = len(labels)
    info["per_pass_kept"] = {
        key: sum(1 for r in out_rows if r["pass_key"] == key)
        for key in PASS_ORDER
    }

    return out_rows, out_arrays, info


def _pass_info(result, tuned):
    if result is None:
        return {"n_events": 0, "ran": False}
    out = {"ran": True, "n_events": len(result.events),
           "morphology": result.morphology}
    if result.params is not None:
        out["segment_seconds"] = float(result.params.segment_seconds)
        out["detrend_window_s"] = float(result.params.detrend_window_s)
    if tuned is not None:
        out["feature_width_s"] = float(tuned.feature_width_s)
        out["confidence"] = float(tuned.confidence)
    return out
