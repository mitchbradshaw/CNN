"""
floors2.py
===========
Round 2, Tasks D and E: a per-channel noise floor, and why two channels
fail the noise null.

TASK D - THE GLOBAL 0.1 mV FLOOR IS A CHANNEL-DEPENDENT FILTER
----------------------------------------------------------------
Round one made the damage visible: the global gate removes 77% of CH2's
events and 13% of CH1's, and it collapses the per-channel median-depth
spread from 9.2x to 1.83x. That is not a noise floor behaving like a noise
floor. A floor at one absolute voltage across five electrodes with
different noise is a filter whose severity is set by how quiet each
electrode happens to be, so the paper's amplitude comparison is being made
on whatever population the filter left behind - and the channel that
differed most is the one it emptied.

THE MULTIPLIER, AND WHY IT IS THIS ONE. The detector already has an
estimator of a channel's own noise: `refine9.slope_sigma`, a MAD-based
sigma of the derivative, which is what the slope gate is measured in. A
per-channel depth floor is derived from it as

    floor_c = MULTIPLIER * sigma_slope_c / fs

`sigma_slope_c / fs` converts a slope noise in mV/s into the depth one
sample of pure noise would produce, so the quantity being compared to a
drop depth is a depth. MULTIPLIER = 3.0 is the conventional
three-sigma detection threshold and is NOT tuned: it was fixed before the
per-channel numbers were computed, and the run reports what each channel's
floor comes out at rather than choosing a multiplier that produces a
convenient one. `CALIBRATION` below records the alternative multipliers so
a reader can see the sensitivity rather than take 3.0 on trust.

This is reported as a SENSITIVITY RESULT and is not adopted as the
headline store. The global floor is the operator's stated instrument
figure; replacing it is a decision about the instrument, not about an
analysis, and it is not this round's to make.

TASK E - CH2 AND CH4 DO NOT EXCEED THE AAFT NULL
-------------------------------------------------
CH2 (p = 0.95) and CH4 (p = 0.80). A reviewer will ask whether that means
"indistinguishable from coloured noise" or "too few events to tell", and
those are different findings. The distinguishing quantities:

  SNR PROXY. Median drop depth relative to that channel's own slope-noise
  sigma. A channel whose events are large relative to its noise and still
  fails the null is failing for a real reason; one whose events sit at the
  noise is failing because there is nothing to see.

  POWER. The AAFT null for that channel is 100 draws with a known median
  and spread. The power the test HAD is the fraction of that null a real
  effect of a given size would have exceeded - computed here as the
  observed count's position in the null and the count that WOULD have been
  needed for p < 0.05, so "how many more events would it have taken" is a
  number rather than a shrug.
"""

import numpy as np

MULTIPLIER = 3.0
CALIBRATION = (2.0, 2.5, 3.0, 4.0, 5.0)
GLOBAL_FLOOR_MV = 0.1

_MAD_TO_SIGMA = 1.4826


def slope_sigma(values, fs):
    """MAD-based sigma of the derivative, in mV/s.

    The detector's own estimator, restated here rather than imported so
    this module does not depend on which `refine9` is on the path - the
    pinned snapshot and the working tree hold different ones.
    """
    values = np.asarray(values, dtype=float).ravel()
    if values.size < 5:
        return 0.0
    derivative = np.gradient(values) * float(fs)
    finite = derivative[np.isfinite(derivative)]
    if finite.size < 4:
        return 0.0
    mad = np.median(np.abs(finite - np.median(finite)))
    return float(_MAD_TO_SIGMA * mad)


def channel_noise(rows, snippets, *, field="detrended_mv"):
    """Per-channel slope noise, pooled over that channel's own snippets.

    Pooled by taking the MEDIAN of the per-event sigmas rather than
    concatenating the snippets: concatenation would put a step
    discontinuity at every join, and the derivative of a step is exactly
    the thing this is trying to measure the absence of.
    """
    per_channel = {}
    for row in rows:
        arrays = snippets.get(row["event_id"])
        if arrays is None:
            continue
        sigma = slope_sigma(arrays[field], float(row["fs"]))
        if sigma > 0:
            per_channel.setdefault(int(row["channel"]), []).append(sigma)

    return {channel: {
        "n_snippets": len(values),
        "median_slope_sigma_mv_per_s": float(np.median(values)),
        "q1": float(np.percentile(values, 25)),
        "q3": float(np.percentile(values, 75)),
    } for channel, values in sorted(per_channel.items())}


def per_channel_floors(noise, fs=10.0, multiplier=MULTIPLIER):
    """`{channel: floor_mv}` from each channel's own slope noise."""
    return {channel: float(multiplier * entry["median_slope_sigma_mv_per_s"]
                           / float(fs))
            for channel, entry in noise.items()}


def apply_floor(rows, floors=None, global_floor=GLOBAL_FLOOR_MV):
    """Keep rows above their floor. `floors=None` applies the global one."""
    kept = []
    for row in rows:
        depth = abs(float(row["drop_depth_mv"]))
        floor = (global_floor if floors is None
                 else floors.get(int(row["channel"]), global_floor))
        if depth > floor:
            kept.append(row)
    return kept


def describe(rows, label):
    """Per-channel n and median depth, plus the spread across channels."""
    by_channel = {}
    for row in rows:
        by_channel.setdefault(int(row["channel"]), []).append(
            abs(float(row["drop_depth_mv"])))

    per_channel = {channel: {
        "n": len(depths),
        "median_depth_mv": float(np.median(depths)),
    } for channel, depths in sorted(by_channel.items())}

    medians = [e["median_depth_mv"] for e in per_channel.values()
               if e["n"] > 0]
    spread = (max(medians) / min(medians)
              if medians and min(medians) > 0 else float("nan"))
    return {"label": label, "n_total": len(rows),
            "per_channel": per_channel,
            "amplitude_spread": float(spread)}


# ---------------------------------------------------------------------------
# Task E
# ---------------------------------------------------------------------------

def power_note(channel, summary, noise_sigma, median_depth, n_events,
               fs=10.0, alpha=0.05):
    """Did this channel fail the null for lack of signal or lack of events?

    `summary` is the round-one AAFT entry for this channel out of
    `nulls_v1/NULL_surrogate.json` - `observed`, `p`, `null_median`,
    `null_q1`, `null_q3`, `null_min`, `null_max`. It is read rather than
    recomputed: the surrogate grid is read-only input to this round.

    THE 95TH PERCENTILE IS ESTIMATED, NOT READ. Round one wrote the null's
    quartiles and extremes but not its 100 draws, so the threshold a
    channel would have had to clear is reconstructed from the IQR as
    `median + 1.645 * IQR / 1.349`, which is the normal-approximation
    relation between the two. That approximation is stated in the output
    and sanity-checked against `null_max`; it is used for ONE purpose - to
    put a number on "how many more events would it have taken" - and no
    verdict below turns on its third digit.
    """
    median = float(summary["null_median"])
    q1, q3 = float(summary["null_q1"]), float(summary["null_q3"])
    observed = float(summary["observed"])
    p = float(summary["p"])

    sigma = (q3 - q1) / 1.349 if q3 > q1 else 0.0
    needed = median + 1.645 * sigma
    needed = min(needed, float(summary.get("null_max", needed)))

    # The SNR proxy: the channel's median event depth in units of the depth
    # one sample of its own slope noise would produce.
    noise_depth = noise_sigma / float(fs)
    snr = float(median_depth / noise_depth) if noise_depth > 0 else float("nan")

    if p <= alpha:
        verdict = "exceeds the null"
        gloss = "not one of the two failing channels"
    elif observed < median:
        verdict = "indistinguishable from coloured noise"
        gloss = (f"the detector finds FEWER events in this channel "
                 f"({observed:.0f}) than in surrogates with its own "
                 f"spectrum (median {median:.1f}). More events would not "
                 f"help: the count is on the wrong side of the null, so "
                 f"this is a statement about the electrode and not about "
                 f"the sample size. Its events are {snr:.1f}x its own "
                 f"one-sample slope noise.")
    elif observed >= needed * 0.85:
        verdict = "too few events to tell"
        gloss = (f"the count ({observed:.0f}) is above the null median "
                 f"({median:.1f}) and close to the threshold it would have "
                 f"had to clear (~{needed:.1f}), so the test had no room "
                 f"to resolve it. Its events are {snr:.1f}x its own "
                 f"one-sample slope noise.")
    else:
        verdict = "indistinguishable from coloured noise"
        gloss = (f"the count ({observed:.0f}) sits inside the null "
                 f"(median {median:.1f}, ~95th pct {needed:.1f}) rather "
                 f"than near its edge. Its events are {snr:.1f}x its own "
                 f"one-sample slope noise.")

    return {
        "channel": int(channel),
        "observed_detections_round1": observed,
        "n_events_corrected_store": int(n_events),
        "n_null": int(summary.get("n_null", 0)),
        "null_median": median,
        "null_q1": q1, "null_q3": q3,
        "null_min": float(summary.get("null_min", float("nan"))),
        "null_max": float(summary.get("null_max", float("nan"))),
        "p": p,
        "alpha": float(alpha),
        "estimated_threshold_for_alpha": float(needed),
        "threshold_method": ("median + 1.645 * IQR / 1.349, capped at "
                             "null_max; the grid stored quartiles, not "
                             "draws"),
        "shortfall": float(needed - observed),
        "median_depth_mv": float(median_depth),
        "slope_sigma_mv_per_s": float(noise_sigma),
        "one_sample_noise_depth_mv": float(noise_depth),
        "snr_proxy_depth_over_noise": snr,
        "verdict": verdict,
        "gloss": gloss,
    }
