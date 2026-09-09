"""
floor10.py
===========
The depth floor, derived per channel and per span instead of asserted once
for everything. drop_motifs10 defect 6.

What was wrong with one number
------------------------------
`refine9.depth_gate` rejects any event shallower than `MIN_DROP_DEPTH_MV`
= 0.1 mV, the operator's stated instrument floor. One number applied to
five Fig2A channels does two things at once, and only one of them is
wanted:

  it removes events below the instrument's resolution - the intent; and

  it removes the DIFFERENCE BETWEEN THE CHANNELS - not the intent, and
    measured: 77% of CH2's motifs fall under 0.1 mV against 13% of CH1's,
    so the per-channel median depth spread collapses from 9.2x before the
    gate to 1.83x after it. The gate deletes exactly the events that made
    the channels differ, and then the channels look alike.

The second effect is worse in drop_motifs10 than it was in 9, because this
run compares CORPORA. A fixed millivolt floor applied across oyster,
Mushroom and reishi is a per-corpus tuning decision made by accident: it
keeps a different fraction of each corpus according to how each was
amplified, and any cross-species difference in what survives it is then
partly an artefact of the number.

The floor used here
-------------------
    floor_mV = FLOOR_SIGMAS * sigma_amplitude(this channel or span)

`sigma_amplitude` is the SAME robust estimator the detector's own slope
gate is built on - `robust_sigma(diff(x, 2)) / sqrt(6)`, from
`detect.slope_noise_sigma`. Using the detector's own noise estimate rather
than a second one matters: `slope_sigma` claims "this many times steeper
than noise alone produces", and a depth floor derived from a different
noise model would be measuring the gap between two opinions about noise.
A second difference annihilates any locally linear trend, so a smooth
event slope contributes nothing to it and the estimate is of broadband
noise rather than of signal - which is what a floor must be built on when
the duty cycle is high, as it is on every span here.

THE MULTIPLIER IS 3.0, and it was not tuned - it was VALIDATED, by
recovering the operator's own number on the operator's own recordings.

Measured `sigma_amplitude` over all sixteen catalogue spans and all five
Fig2A channels:

    corpus                sigma (mV)        3 sigma (mV)
    catalogue, M2_aug     0.0188 - 0.0321   0.056 - 0.096
    Mushroom_260720       0.0054            0.016
    Fig2A, CH0-CH4        0.0017 - 0.0066   0.005 - 0.020

The operator's 0.1 mV was stated for the M2 recordings, and on those the
3-sigma rule independently returns 0.056-0.096 mV. The stated instrument
floor is therefore about 3-4 sigma of the noise in the recordings it was
stated for, which is what makes 3.0 a reading of the operator's own
decision rather than a new one. Under a Gaussian, 3 sigma is a one-in-370
per-sample excursion, and a DROP - a run of consecutive samples descending
monotonically past the slope gate - is far rarer than any single sample.

THE SAME MEASUREMENT IS THE CASE AGAINST THE GLOBAL FLOOR. On Fig2A,
0.1 mV is 15 to 59 sigma of those channels' own noise, and on
Mushroom_260720 it is 18 sigma. A number that is 3 sigma on one corpus and
59 sigma on another is a per-corpus tuning decision made by accident,
which is precisely what this run's one-parameterisation rule forbids - and
it is the whole explanation of why the global floor removes 77% of CH2.

Both stores are kept
--------------------
`Plots/drop_motifs10/` carries the derived-floor store AND the 0.1 mV
global-floor store, so the two are comparable and the choice is auditable
rather than baked in. Nothing downstream is allowed to assume which it is
reading: every row carries `depth_floor_mv` and `floor_rule`.
"""

import numpy as np

from Working.Detection.drop_motifs.detect import robust_sigma

# The operator's stated instrument floor, kept for the comparison store.
GLOBAL_FLOOR_MV = 0.1

# See the module docstring. Not swept.
FLOOR_SIGMAS = 3.0

RULE_GLOBAL = "global_0.1mV"
RULE_DERIVED = f"derived_{FLOOR_SIGMAS:g}x_amplitude_MAD"


def amplitude_sigma_mv(x):
    """Robust per-sample amplitude noise, in millivolts.

    `x` is in the recording's native units (volts), as everything below
    `Working/Detection/` is; the store is in millivolts, so the x1000 is
    here and nowhere else.

    Var(x[i+1] - 2 x[i] + x[i-1]) = 6 sigma^2 under white noise, hence the
    sqrt(6). This is `detect.slope_noise_sigma`'s own `amplitude_sigma`
    line, before it is turned into a slope - kept identical on purpose so
    the depth floor and the slope gate cannot disagree about the noise.
    """
    x = np.asarray(x, dtype=float).ravel()
    if x.size < 3:
        return 0.0
    return float(robust_sigma(np.diff(x, 2)) / np.sqrt(6.0) * 1000.0)


def derived_floor_mv(x, sigmas=FLOOR_SIGMAS):
    """The depth floor for one channel or one span, in millivolts."""
    return float(sigmas) * amplitude_sigma_mv(x)


def floor_for(x, rule=RULE_DERIVED, sigmas=FLOOR_SIGMAS):
    """`(floor_mv, description)` under either rule."""
    if rule == RULE_GLOBAL:
        return GLOBAL_FLOOR_MV, RULE_GLOBAL
    return derived_floor_mv(x, sigmas=sigmas), RULE_DERIVED


def apply_floor(rows, floor_mv, *, rule=RULE_DERIVED, key="drop_depth_mv"):
    """`(kept, rejected)`, and every kept row records the floor it passed.

    The floor is stamped onto the row rather than left in a manifest so
    that a pooled store built from four corpora, each with its own floor,
    can still say per event which number it was measured against.
    """
    kept, rejected = [], []
    for row in rows:
        row = dict(row)
        row["depth_floor_mv"] = float(floor_mv)
        row["floor_rule"] = rule
        (kept if abs(float(row[key])) > float(floor_mv) else rejected
         ).append(row)
    return kept, rejected


def summarise(name, x, rows, *, sigmas=FLOOR_SIGMAS, key="drop_depth_mv"):
    """One row of the floor table: what each rule keeps, side by side."""
    sigma = amplitude_sigma_mv(x)
    derived = float(sigmas) * sigma
    depths = np.asarray([abs(float(r[key])) for r in rows], dtype=float)
    n = int(depths.size)
    return {
        "name": name,
        "n_raw": n,
        "amplitude_sigma_mv": sigma,
        "derived_floor_mv": derived,
        "global_floor_mv": GLOBAL_FLOOR_MV,
        "floor_ratio_derived_over_global": (derived / GLOBAL_FLOOR_MV
                                            if GLOBAL_FLOOR_MV else float("nan")),
        "n_kept_derived": int((depths > derived).sum()),
        "n_kept_global": int((depths > GLOBAL_FLOOR_MV).sum()),
        "median_depth_mv_raw": float(np.median(depths)) if n else float("nan"),
        "median_depth_mv_derived": (float(np.median(depths[depths > derived]))
                                    if (depths > derived).any() else float("nan")),
        "median_depth_mv_global": (
            float(np.median(depths[depths > GLOBAL_FLOOR_MV]))
            if (depths > GLOBAL_FLOOR_MV).any() else float("nan")),
    }


def spread(summaries, field):
    """Deepest / shallowest median across a set of channels or spans.

    The number the global floor collapsed from 9.2x to 1.83x. Reported for
    both rules so the collapse is visible as a property of the RULE rather
    than of the preparation.
    """
    values = [s[field] for s in summaries
              if np.isfinite(s.get(field, float("nan")))]
    if len(values) < 2 or min(values) <= 0:
        return float("nan")
    return float(max(values) / min(values))
