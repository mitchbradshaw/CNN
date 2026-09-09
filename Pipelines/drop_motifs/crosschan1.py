"""
crosschan1.py
==============
Task 3. Five electrodes 1.5 mm apart on a shared ground with a common
AI GND reference is the configuration a reviewer attacks first, and the
attack is specific: Task 2 claims the shape families are channel-mixed,
and that claim is worthless if the mixing is one disturbance recorded five
times.

This module either removes that objection or finds the contamination. It
does not decide which - `run_nulls1.py` reports whatever comes out,
including the case where the family result does not survive.

THE MEASUREMENT
---------------
Every cross-channel pair of events whose onsets fall within
`PAIR_WINDOW_S` of each other is cross-correlated over lags of
+-`MAX_LAG_S`, and the peak lag and the correlation at that peak place it
in one of three bins:

    common_mode   |lag| <= 0.2 s and r >= 0.90   one disturbance on a
                                                 shared ground, twice
    propagation   0.2 < |lag| <= 2.0 and r >= 0.70   candidate network event
    independent   everything else                coincidence

THOSE FIVE NUMBERS ARE STATED DEFAULTS, NOT TRUTHS. They are `Thresholds`
fields rather than literals at the comparison site precisely so
`sensitivity_table` can move each of them by +-50% and report whether the
bin counts hold. A conclusion that survives only at 0.90 and dies at 0.85
is a conclusion about 0.90.

THE ALIGNMENT, WHICH IS WHERE THE BUGS LIVE
-------------------------------------------
Store snippets are short (10 to 130 samples) and each carries its own
absolute time axis. Correlating them "over +-5 s" therefore cannot mean
sliding one array along the other from index zero: the two arrays start at
different absolute times, and ignoring that turns a genuine 0 s
coincidence into an apparent lag of however far apart the snippet starts
happen to be.

So both snippets are placed on the ABSOLUTE sample grid, and a candidate
lag shifts one of them along that grid. At each lag the correlation is
computed over the samples where both are defined, and a lag whose overlap
is under `MIN_OVERLAP_SAMPLES` is not a candidate at all - a two-sample
overlap can produce r = 1.0 and would otherwise dominate the peak.

The sign convention is fixed and tested: a POSITIVE lag means the second
event (the higher channel number) happens LATER.

THE CO-OCCURRENCE COUNT NEEDS ITS OWN NULL
------------------------------------------
"These events co-occur" is not a measurement until it is compared against
how often events this dense would co-occur by chance. `rotation_null`
circularly rotates one channel's onset times by a random offset and
recounts, which preserves each channel's event count and its
inter-event structure exactly while destroying the alignment between
channels. A circular rotation rather than a uniform resample because
event density is not uniform over the recording and a resample would null
the density as well as the alignment.
"""

from dataclasses import asdict, dataclass

import numpy as np

# Two events are a candidate pair if their onsets fall within this many
# seconds of each other. Also the half-width of the rotation null's
# coincidence count, so the two numbers cannot drift apart.
PAIR_WINDOW_S = 5.0

# The cross-correlation is searched over +-this. Equal to PAIR_WINDOW_S by
# intent: a peak outside the pairing window would describe an alignment
# between events that were never paired.
MAX_LAG_S = 5.0

# A candidate lag needs at least this many jointly-defined samples before
# its correlation is believed. At 10 Hz this is 1 s of overlap.
MIN_OVERLAP_SAMPLES = 10

BINS = ("common_mode", "propagation", "independent")

ROTATION_TRIALS = 1000
ROTATION_SEED = 20260902


@dataclass(frozen=True)
class Thresholds:
    """The four numbers that define the bins. Defaults are the stated
    ones; `sensitivity_table` varies them."""
    common_lag_s: float = 0.2
    common_r: float = 0.90
    propagation_lag_s: float = 2.0
    propagation_r: float = 0.70


DEFAULT_THRESHOLDS = Thresholds()


def classify(lag_s, r, thresholds=DEFAULT_THRESHOLDS):
    """Which bin a `(lag, correlation)` falls in.

    Order matters: common_mode is tested first, so a zero-lag pair that
    also satisfies the propagation rule is called common_mode. That is the
    conservative direction - the whole point of the bin is to REMOVE
    suspect pairs from the propagation count, so an ambiguous pair must
    fall on the suspect side.
    """
    if lag_s is None or r is None or not np.isfinite(lag_s) or not np.isfinite(r):
        return "independent"
    lag = abs(float(lag_s))
    if lag <= thresholds.common_lag_s and r >= thresholds.common_r:
        return "common_mode"
    if lag <= thresholds.propagation_lag_s and r >= thresholds.propagation_r:
        return "propagation"
    return "independent"


def _detrended(row, snippets, field="detrended_mv"):
    """`(values, start_index)` with a linear trend removed.

    The stored `detrended_mv` has already had a rolling-median baseline
    taken out over the DETECTION window, not over the snippet, so a short
    snippet can still carry a residual ramp. A residual ramp shared by two
    channels correlates at r near 1 at every lag, which would fill the
    common-mode bin with baseline drift. Removing a straight line per
    snippet is the cheapest defence and it cannot invent structure.
    """
    fields = snippets.get(row["event_id"])
    if not fields:
        return None, None
    values = np.asarray(fields.get(field), dtype=float).ravel()
    if values.size < 3 or not np.all(np.isfinite(values)):
        return None, None
    index = np.arange(values.size, dtype=float)
    slope, intercept = np.polyfit(index, values, 1)
    return values - (slope * index + intercept), int(row["snippet_start_idx"])


def peak_lag_correlation(values_a, start_a, values_b, start_b, fs, *,
                         max_lag_s=MAX_LAG_S,
                         min_overlap=MIN_OVERLAP_SAMPLES):
    """`(peak_lag_s, r_at_peak, n_overlap)` for two snippets on the
    absolute sample grid.

    A positive lag means `b` happens later than `a`.
    """
    fs = float(fs)
    max_lag = int(round(float(max_lag_s) * fs))
    best = (None, -np.inf, 0)

    for lag in range(-max_lag, max_lag + 1):
        # `lag` is how much LATER b is than a, so testing that hypothesis
        # means sliding b BACK by `lag` and asking whether it then lines
        # up: shifted b occupies [start_b - lag, ...). Sliding it forward
        # instead is the sign error `test_measured_lag_recovers_the_
        # injected_one` exists to catch, and it does not change any bin
        # (the rules use |lag|), so nothing else would have reported it.
        offset = start_b - lag
        lo = max(start_a, offset)
        hi = min(start_a + values_a.size, offset + values_b.size)
        n = hi - lo
        if n < min_overlap:
            continue
        piece_a = values_a[lo - start_a:hi - start_a]
        piece_b = values_b[lo - offset:hi - offset]
        sd_a, sd_b = piece_a.std(), piece_b.std()
        if sd_a == 0.0 or sd_b == 0.0:
            continue
        r = float(np.mean((piece_a - piece_a.mean()) * (piece_b - piece_b.mean()))
                  / (sd_a * sd_b))
        if r > best[1]:
            best = (lag / fs, r, n)

    if best[0] is None:
        return None, None, 0
    return float(best[0]), float(best[1]), int(best[2])


def cross_channel_pairs(rows, snippets, *, thresholds=DEFAULT_THRESHOLDS,
                        pair_window_s=PAIR_WINDOW_S, max_lag_s=MAX_LAG_S,
                        min_overlap=MIN_OVERLAP_SAMPLES, field="detrended_mv"):
    """Every cross-channel pair inside the window, measured and binned.

    Same-channel pairs are never built: two detections on one electrode
    cannot be one disturbance recorded twice, and including them would
    inflate the co-occurrence count that is the headline of this task.
    """
    prepared = []
    for row in rows:
        values, start = _detrended(row, snippets, field=field)
        if values is None:
            continue
        prepared.append((row, values, start))
    prepared.sort(key=lambda item: int(item[0]["onset_idx"]))

    pairs = []
    for i, (row_a, values_a, start_a) in enumerate(prepared):
        fs = float(row_a["fs"])
        window = int(round(float(pair_window_s) * fs))
        onset_a = int(row_a["onset_idx"])
        for row_b, values_b, start_b in prepared[i + 1:]:
            onset_b = int(row_b["onset_idx"])
            if onset_b - onset_a > window:
                break                       # sorted, so no later one is closer
            if int(row_a["channel"]) == int(row_b["channel"]):
                continue
            lag, r, n_overlap = peak_lag_correlation(
                values_a, start_a, values_b, start_b, fs,
                max_lag_s=max_lag_s, min_overlap=min_overlap)
            # Orient the pair by channel number so the sign of the lag has
            # a fixed meaning across the whole table.
            if int(row_a["channel"]) > int(row_b["channel"]):
                lag = None if lag is None else -lag
                low, high = row_b, row_a
            else:
                low, high = row_a, row_b
            pairs.append({
                "event_a": low["event_id"], "event_b": high["event_id"],
                "channel_a": int(low["channel"]),
                "channel_b": int(high["channel"]),
                "onset_a_s": int(low["onset_idx"]) / fs,
                "onset_b_s": int(high["onset_idx"]) / fs,
                "onset_delta_s": (int(high["onset_idx"])
                                  - int(low["onset_idx"])) / fs,
                "depth_a_mv": abs(float(low["drop_depth_mv"])),
                "depth_b_mv": abs(float(high["drop_depth_mv"])),
                "peak_lag_s": lag,
                "peak_r": r,
                "n_overlap": n_overlap,
                "bin": classify(lag, r, thresholds),
            })
    return pairs


def bin_counts(pairs):
    counts = {name: 0 for name in BINS}
    for pair in pairs:
        counts[pair["bin"]] = counts.get(pair["bin"], 0) + 1
    return counts


def rebin(pairs, thresholds):
    """Re-classify an already-measured pair list under new thresholds.

    The measurement (peak lag, correlation at peak) does not depend on the
    thresholds at all - only the bin does. Recomputing the cross-
    correlations once per sensitivity row costs twelve full passes over
    every pair and every lag for no new information, which is what the
    first version of `sensitivity_table` did and why it took minutes
    instead of milliseconds.
    """
    return [{**pair, "bin": classify(pair["peak_lag_s"], pair["peak_r"],
                                     thresholds)}
            for pair in pairs]


def sensitivity_table(pairs, *, factors=(0.5, 1.0, 1.5)):
    """Bin counts with each threshold moved to +-50% of its stated value,
    one threshold at a time.

    One at a time rather than a full grid, because the question is "which
    of these four numbers is the conclusion resting on", and a full grid
    answers a different and less useful question at 81 times the cost.
    `common_r` and `propagation_r` are clipped to 0.99: a correlation
    threshold of 1.35 is not a sensitivity, it is an empty bin.
    """
    base = DEFAULT_THRESHOLDS
    table = []
    for name in ("common_lag_s", "common_r", "propagation_lag_s",
                 "propagation_r"):
        for factor in factors:
            value = getattr(base, name) * factor
            if name.endswith("_r"):
                value = min(value, 0.99)
            thresholds = Thresholds(**{**asdict(base), name: value})
            counts = bin_counts(rebin(pairs, thresholds))
            table.append({"varied": name, "factor": float(factor),
                          "value": float(value),
                          "counts": counts,
                          "n_pairs": len(pairs)})
    stable = {}
    for name in ("common_lag_s", "common_r", "propagation_lag_s",
                 "propagation_r"):
        rows_for = [row for row in table if row["varied"] == name]
        common = [row["counts"]["common_mode"] for row in rows_for]
        propagation = [row["counts"]["propagation"] for row in rows_for]
        stable[name] = {
            "common_mode_range": [int(min(common)), int(max(common))],
            "propagation_range": [int(min(propagation)),
                                  int(max(propagation))],
        }
    return table, stable


# ---------------------------------------------------------------------------
# the co-occurrence null
# ---------------------------------------------------------------------------

def coincidence_count(onsets_by_channel, window):
    """Cross-channel onset pairs within `window` SAMPLES.

    Counts pairs, not events: an onset coinciding with three others on
    three other channels contributes three. That matches what
    `cross_channel_pairs` builds, so the observed count and the null count
    are the same quantity.
    """
    channels = sorted(onsets_by_channel)
    total = 0
    for i, channel_a in enumerate(channels):
        a = np.sort(np.asarray(onsets_by_channel[channel_a]))
        for channel_b in channels[i + 1:]:
            b = np.sort(np.asarray(onsets_by_channel[channel_b]))
            if not a.size or not b.size:
                continue
            left = np.searchsorted(b, a - window, side="left")
            right = np.searchsorted(b, a + window, side="right")
            total += int((right - left).sum())
    return total


def rotation_null(rows, n_samples, *, trials=ROTATION_TRIALS,
                  seed=ROTATION_SEED, pair_window_s=PAIR_WINDOW_S,
                  rotate_channel=None):
    """Observed cross-channel coincidences against a rotation null.

    Each trial rotates every channel but the first by its own random
    circular offset, so no two channels keep their relative alignment
    while each keeps its own event count and inter-event spacing exactly.
    Rotating one channel only (`rotate_channel`) is offered because it is
    the more conservative null - it destroys less - and the report gives
    both if they disagree.
    """
    fs = float(rows[0]["fs"])
    window = int(round(float(pair_window_s) * fs))
    onsets = {}
    for row in rows:
        onsets.setdefault(int(row["channel"]), []).append(int(row["onset_idx"]))
    onsets = {c: np.asarray(sorted(v)) for c, v in onsets.items()}

    observed = coincidence_count(onsets, window)
    channels = sorted(onsets)
    rotated_channels = ([int(rotate_channel)] if rotate_channel is not None
                        else channels[1:])

    rng = np.random.default_rng(int(seed))
    null = np.empty(int(trials), dtype=float)
    offsets = []
    for trial in range(int(trials)):
        shifted = dict(onsets)
        trial_offsets = {}
        for channel in rotated_channels:
            offset = int(rng.integers(0, int(n_samples)))
            trial_offsets[channel] = offset
            shifted[channel] = np.sort((onsets[channel] + offset)
                                       % int(n_samples))
        offsets.append(trial_offsets)
        null[trial] = coincidence_count(shifted, window)

    n_ge = int((null >= observed).sum())
    return {
        "observed_coincidences": int(observed),
        "pair_window_s": float(pair_window_s),
        "n_trials": int(trials),
        "seed": int(seed),
        "rotated_channels": [int(c) for c in rotated_channels],
        "null_median": float(np.median(null)),
        "null_q1": float(np.percentile(null, 25)),
        "null_q3": float(np.percentile(null, 75)),
        "null_min": float(null.min()),
        "null_max": float(null.max()),
        "p": float((1 + n_ge) / (1 + int(trials))),
        "ratio_observed_over_null_median": (
            float(observed / np.median(null)) if np.median(null) > 0 else None),
        "null": null.tolist(),
        "first_five_offsets": offsets[:5],
    }


def common_mode_event_ids(pairs):
    """Every event that took part in at least one common_mode pair.

    Set-valued rather than pair-valued because Task 2's table is rebuilt
    with these events REMOVED, and an event is suspect if any of its
    pairings is.
    """
    suspect = set()
    for pair in pairs:
        if pair["bin"] == "common_mode":
            suspect.add(pair["event_a"])
            suspect.add(pair["event_b"])
    return suspect
