"""
passes7.py
===========
Adds the MICRO pass to the drop_motifs6 pass set, and drops an inverted
pass that found no family.

`passes6` is imported rather than edited, so every drop_motifs6 number
stays reproducible from the code that produced it.

The micro pass, and what it is actually for
-------------------------------------------
Three spans were still under-detecting badly after drop_motifs6:

    ID 26    2 events found against ~44 counted by eye
    ID 28    19 against >90
    ID 385   24, missing a population of small spikes the operator
             circled on the figure by hand

All three were diagnosed by instrumenting the detector's own rejection
counters rather than by sweeping parameters blind, and the answer was the
same in all three and was NOT the scale:

    ID 26, segment 200 s, 8 sigma:  67 candidates -> 15 confirmed
                                    21 rejected shallow
                                    18 rejected no-rise
                                    12 rejected not-dominant

The detector was FINDING the events and then throwing them away. Three
gates did it, and all three are relative to the biggest thing in view:

  `min_depth_frac`      a fall must be >=10% of the DEEPEST fall in the
                        span. On a span holding one 14 mV drop and forty
                        0.5 mV ones, that gate deletes the forty.
  `min_fall_dominance`  a fall must be >=50% of its own window's
                        peak-to-peak. A small event framed in a window
                        that also contains a big neighbour fails it.
  `min_rise_frac`       a rise-triggered event's rise must climb >=50% of
                        its fall's depth.

Each is a sensible default for finding the dominant motif of a span, and
each is exactly wrong when the question is "find everything across
scales", which is what the supervisor asked for. The micro pass relaxes
all three, drops the slope gate, and scans the segment length - then keeps
the most productive rung whose windows are still clean.

Measured, with the base pass unchanged in every case:

    ID 26    2 -> 36 events at 100% window purity
    ID 28    19 -> 83 at 95%
    ID 385   24 -> 37, with depths reaching 0.13 mV

`up_runs` turned out to be a good independent check on all of this: it is
the count of rising runs in the encoded string, it needs no gate to
produce, and on ID 26 it read 67 against the operator's ~44 by eye.
"""

import numpy as np

from Pipelines.drop_motifs import passes6
from Pipelines.drop_motifs.passes6 import (PASS_BASE, PASS_FINE, PASS_INV,
                                           PASS_SENS, deduplicate, motif_key,
                                           scale_bands)
from Working.Detection.drop_motifs import motifs5
from Working.Detection.drop_motifs.detect5 import (Detect5Params,
                                                   detect_drops5,
                                                   window_purity)

PASS_MICRO = "micro"

PASS_ORDER = (PASS_BASE, PASS_FINE, PASS_SENS, PASS_MICRO, PASS_INV)

PASS_LABELS = dict(passes6.PASS_LABELS)
PASS_LABELS[PASS_MICRO] = "micro (small events across scales)"

# The relaxed gates. Not zero: a gate at zero admits every wobble in the
# noise floor, and the purity constraint below could not then tell a real
# small event from one. These are the values at which ID 26's rejection
# counters stopped dominating its result.
MICRO_MIN_RISE_FRAC = 0.05
MICRO_MIN_FALL_DOMINANCE = 0.10
MICRO_MIN_DEPTH_FRAC = 0.01

MICRO_SIGMAS = (2.0, 1.5)

# Segment lengths are scanned as a fraction of the span rather than as
# fixed seconds, because these spans run 0.2 h to 90 h and the rung that
# won differs by 20x across them: 100 s on ID 26, 200 s on ID 28, 30 s on
# ID 385. A fixed ladder would have been three different wrong answers,
# which is the same lesson the fine pass's divisor ladder already taught.
MICRO_SEGMENT_FRACTIONS = (1 / 3000.0, 1 / 1500.0, 1 / 800.0, 1 / 400.0,
                           1 / 200.0, 1 / 100.0)

# Detrend as a multiple of the segment. The rolling-mean high pass must be
# much WIDER than the event period or it flattens the very thing being
# detected - measured on ID 26, where a detrend near the 3600 s cycle
# period reduced 3-5 mV sawteeth to 0.1 mV.
MICRO_DETREND_MULTS = (100.0, 300.0)

# Purity floor for the micro pass. Lower than the sensitive pass's 0.90
# because these are dense trains where a window legitimately catches the
# shoulder of its neighbour, and 0.90 would reject ID 385's best rung
# outright. Still high enough that a rung returning burst windows loses.
MICRO_MIN_PURITY = 0.75

# An inverted pass returning fewer than this many motifs is discarded.
# The operator's instruction, and the reason is that the inverted pass
# exists to find a POPULATION going the other way; one lone rise is a
# curiosity that costs a whole panel and a colour to display.
MIN_INVERTED_FAMILY = 2


def run_micro(x, fs, *, span_seconds=None, sigmas=MICRO_SIGMAS,
              segment_fractions=MICRO_SEGMENT_FRACTIONS,
              detrend_mults=MICRO_DETREND_MULTS,
              min_purity=MICRO_MIN_PURITY, **overrides):
    """Relaxed gates, scanned segment. Returns `(result, chosen)`.

    Scored by event count among rungs whose windows are at least
    `min_purity` clean - the same shape of rule the other passes use, so
    sensitivity is never bought by reintroducing burst windows.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    span_s = float(span_seconds if span_seconds else len(x) / fs)

    best, chosen, best_n = None, None, 0
    for fraction in segment_fractions:
        segment = span_s * float(fraction)
        if segment * fs < 2:            # a segment must hold two samples
            continue
        for mult in detrend_mults:
            detrend = min(segment * mult, span_s / 2.0)
            for sigma in sigmas:
                try:
                    params = Detect5Params(
                        detrend_window_s=detrend,
                        segment_seconds=segment,
                        slope_sigma=float(sigma),
                        morphology="sharkfin",
                        min_rise_frac=MICRO_MIN_RISE_FRAC,
                        min_fall_dominance=MICRO_MIN_FALL_DOMINANCE,
                        min_depth_frac=MICRO_MIN_DEPTH_FRAC,
                        **overrides)
                    result = detect_drops5(x, fs, params)
                except (ValueError, ZeroDivisionError):
                    continue
                if result is None or not result.events:
                    continue

                purity = window_purity(x, fs, result)
                if not purity:
                    continue
                clean = sum(1 for p in purity if p == 1) / len(purity)
                if clean < min_purity:
                    continue
                if len(result.events) > best_n:
                    best, best_n = result, len(result.events)
                    chosen = {"segment_seconds": float(segment),
                              "detrend_window_s": float(detrend),
                              "slope_sigma": float(sigma),
                              "purity": float(clean),
                              "up_runs": int(dict(result.counts)
                                             .get("up_runs", 0))}
    return best, chosen


def detect_multiscale(x, fs, *, catalogue_id, recording_id, source_file,
                      channel, span_offset=0, span_label=None, span_key=None,
                      max_passes=3, fine=True, sensitive=True, inverted=True,
                      micro=True, base_overrides=None, fine_overrides=None,
                      sens_overrides=None, inv_overrides=None,
                      micro_overrides=None):
    """`passes6.detect_multiscale` plus the micro pass, and with a lone
    inverted detection discarded.

    Returns `(rows, arrays, info)` in the same shape as `passes6`.
    """
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    info = {"passes": {}}

    base = passes6.run_base(x, fs, max_passes=max_passes,
                            **(base_overrides or {}))
    contributions = []
    base_onsets = []

    if base.result is not None and base.events:
        _, purity = passes6._purity_of(x, fs, base.result)
        contributions.append((PASS_BASE, base.result, purity, +1, x))
        base_onsets = [e.onset_idx for e in base.events]
    info["passes"][PASS_BASE] = passes6._pass_info(base.result, base)

    if fine and np.isfinite(base.feature_width_s) and base.feature_width_s > 0:
        result, divisor = passes6.run_fine(x, fs, base.feature_width_s,
                                           base_onsets=base_onsets,
                                           **(fine_overrides or {}))
        if result is not None and result.events:
            _, purity = passes6._purity_of(x, fs, result)
            contributions.append((PASS_FINE, result, purity, +1, x))
        entry = passes6._pass_info(result, None)
        entry["divisor"] = divisor
        info["passes"][PASS_FINE] = entry

    if sensitive:
        tuned, sigma = passes6.run_sensitive(x, fs, max_passes=max_passes,
                                             **(sens_overrides or {}))
        if tuned is not None and tuned.events:
            _, purity = passes6._purity_of(x, fs, tuned.result)
            contributions.append((PASS_SENS, tuned.result, purity, +1, x))
        entry = passes6._pass_info(tuned.result if tuned else None, tuned)
        entry["slope_sigma"] = sigma
        info["passes"][PASS_SENS] = entry

    if micro:
        result, chosen = run_micro(x, fs, **(micro_overrides or {}))
        if result is not None and result.events:
            _, purity = passes6._purity_of(x, fs, result)
            contributions.append((PASS_MICRO, result, purity, +1, x))
        entry = passes6._pass_info(result, None)
        entry.update(chosen or {})
        info["passes"][PASS_MICRO] = entry

    if inverted:
        flipped = -x
        tuned = passes6.run_inverted(x, fs, max_passes=max_passes,
                                     **(inv_overrides or {}))
        if tuned.result is not None and tuned.events:
            _, purity = passes6._purity_of(flipped, fs, tuned.result)
            contributions.append((PASS_INV, tuned.result, purity, -1, flipped))
        info["passes"][PASS_INV] = passes6._pass_info(tuned.result, tuned)

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

    # A lone surviving inverted detection is dropped rather than drawn:
    # the pass is there to find a population going the other way, and one
    # rise costs a panel and a colour to say nothing.
    inverted_kept = [e for e in kept if e[0] == PASS_INV]
    dropped_lone_inverted = 0
    if 0 < len(inverted_kept) < MIN_INVERTED_FAMILY:
        kept = [e for e in kept if e[0] != PASS_INV]
        dropped_lone_inverted = len(inverted_kept)

    info["n_before_dedup"] = len(candidates)
    info["n_after_dedup"] = len(kept)
    info["n_duplicates_dropped"] = len(candidates) - len(kept)
    info["dropped_lone_inverted"] = dropped_lone_inverted

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
