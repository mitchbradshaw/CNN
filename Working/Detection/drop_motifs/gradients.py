"""
gradients.py
=============
The gradient of each spike's fall, and the circular statistics that turn a
set of gradients into a rose diagram.

What a rose diagram is
----------------------
A rose diagram - equivalently a circular or polar histogram, a wind rose
in meteorology, a strike/dip rose in structural geology - bins a set of
DIRECTIONS and draws each bin as a ray from the centre whose length is the
count in that bin. Here the direction is the angle of a spike's falling
edge and the ray length is how many spikes fall at that steepness, so the
whole population's descent geometry is one picture.

The associated maths is circular statistics: the mean direction is a
`circular_mean` (a vector mean, NOT an arithmetic mean of angles), and how
concentrated the directions are is the `resultant_length` R, from 0 for
"spread evenly" to 1 for "all identical".

The unit trap, which is the whole difficulty
--------------------------------------------
`arctan` takes a dimensionless argument. A slope of -0.73 mV/s has no
angle until something states how many millivolts equal one second ON THE
PAGE. Choosing that reference silently - by writing `arctan(slope)` and
letting the reference default to 1 mV/s unremarked - produces a figure
whose angles are an artefact of a unit choice nobody made deliberately.

So every angle here is `arctan(slope / reference)` with the reference
explicit, reported on the figure, and selectable:

  raw        a stated slope in mV/s (default 1.0). The literal reading:
             45 degrees means "one millivolt per second". Separates the
             two recordings by their absolute steepness, which is a real
             difference and worth showing - Mushroom_260720's falls
             median -4.18 mV/s against M2_aug's -0.73.
  recording  each recording's own median |max slope|. 45 degrees means
             "typical for this recording", so the two roses are directly
             superimposable and what is left is the SPREAD within each.
  pooled     the median over all events pooled. A compromise: one
             reference for everybody, chosen by the data rather than
             stated.
  event      each event's own mean fall slope, making the quantity the
             dimensionless `peakedness` ratio. This is the only mode whose
             angle carries no units at all, and it is the one that answers
             a shape question rather than a scale question.

Which gradient
--------------
Three are measured per event and any can be roseed:

  max_slope    the steepest single sample of the fall. THE default: it is
               what "how vertical is the drop" means, and it is robust to
               where exactly the onset was declared.
  onset_slope  the gradient at the declared onset. Included because it is
               already in the event table, but note it is a poor steepness
               measure on Mushroom_260720 - the onset is the first sample
               past the detection threshold, which on a 2 s segment grid
               can sit one step before the real cliff, so its median
               (-0.088 mV/s) understates the true steepness (-4.18) by a
               factor of fifty.
  mean_slope   depth over fall duration. The average, not the steepest.

Everything is computed from the STORED SNIPPETS, so a rose can be redrawn
from `DATA/derived/drop_motifs/` without re-running detection, exactly
like every other figure in this pipeline.

No plotting library - CLAUDE.md rule 1.
"""

import numpy as np

# Selectable references for the slope-to-angle conversion. Order is the
# CLI's choice order; `raw` is first because it is the default.
SLOPE_SCALES = ("raw", "recording", "pooled", "event")

# Which measured gradient a rose is built on. `peakedness` is the odd one
# out and is handled specially: it is already dimensionless and already
# positive, so it is negated for display (see `rose_data`) to keep every
# rose in the same falling quadrant.
GRADIENT_FIELDS = ("max_slope_mv_s", "onset_slope_mv_s", "mean_slope_mv_s",
                   "peakedness")

# Fields that arrive positive and must be negated to point downward.
_POSITIVE_FIELDS = ("peakedness",)

# Default reference for `raw` mode, in mV/s. Stated, not assumed: at 1.0
# a 45-degree ray means exactly one millivolt per second.
DEFAULT_SLOPE_REF_MV_S = 1.0


# -- per-event gradients ---------------------------------------------------

def fall_gradients(values_mv, fs, onset, trough):
    """Measure one event's fall.

    `values_mv` is the event's snippet in millivolts (the detrended trace
    is the right input - the raw one carries the resting potential, whose
    slow drift would be added to every gradient). `onset` and `trough` are
    offsets INTO that array, not absolute channel indices.

    Returns mV per SECOND, not per sample, so recordings at different
    sampling rates land on the same rose.
    """
    values = np.asarray(values_mv, dtype=float).ravel()
    fs = float(fs)
    onset = int(np.clip(onset, 0, max(len(values) - 1, 0)))
    trough = int(np.clip(trough, 0, max(len(values) - 1, 0)))

    if len(values) < 3:
        return _empty_gradients()

    derivative = np.gradient(values) * fs          # mV per second
    onset_slope = float(derivative[onset])

    if trough > onset:
        span = derivative[onset:trough + 1]
        max_slope = float(span.min())
        mean_slope = float((values[trough] - values[onset]) / ((trough - onset) / fs))
    else:
        # No fall between the two marks - report the onset sample's own
        # gradient for both rather than inventing a range. `peakedness`
        # then comes out at 1.0, which is the honest "no shape measured".
        max_slope = onset_slope
        mean_slope = onset_slope

    # Dimensionless: how much steeper the steepest point is than the fall's
    # own average. 1.0 is a perfectly linear fall; larger is front-loaded.
    peakedness = float(max_slope / mean_slope) if mean_slope != 0.0 else 0.0

    return {
        "onset_slope_mv_s": onset_slope,
        "max_slope_mv_s": max_slope,
        "mean_slope_mv_s": mean_slope,
        "peakedness": peakedness,
    }


def _empty_gradients():
    return {"onset_slope_mv_s": 0.0, "max_slope_mv_s": 0.0,
            "mean_slope_mv_s": 0.0, "peakedness": 0.0}


def event_gradients(events, snippets, field="detrended_mv"):
    """`fall_gradients` for every event in a store, keyed alongside it.

    Each returned dict carries the event's `event_id` and `recording_id`
    so a rose can be split by recording without a second join.
    """
    out = []
    for event in events:
        arrays = snippets[event["event_id"]]
        values = np.asarray(arrays[field], dtype=float)
        start = int(event["snippet_start_idx"])
        gradients = fall_gradients(
            values, float(event["fs"]),
            onset=int(event["onset_idx"]) - start,
            trough=int(event["trough_idx"]) - start,
        )
        gradients.update({
            "event_id": event["event_id"],
            # Carried so a rose can be split by SPAN. Three shipped spans
            # share one recording, so splitting by recording_id would
            # merge them into one lobe and lose the comparison.
            "span_key": event.get("span_key") or f"r{event['recording_id']}",
            "span_label": event.get("span_label") or event["source_file"],
            "recording_id": int(event["recording_id"]),
            "source_file": event["source_file"],
            "cluster_id": int(event.get("cluster_id", -1)),
            "onset_h": float(event["onset_h"]),
            "drop_depth_mv": float(event["drop_depth_mv"]),
            "fall_duration_s": float(event["fall_duration_s"]),
        })
        out.append(gradients)
    return out


# -- slope -> angle --------------------------------------------------------

def slope_angle(slope, reference):
    """`arctan(slope / reference)`, in radians.

    A falling slope is negative, so the angle is negative: the ray points
    down and to the right, tracing the falling edge itself. The result is
    bounded in (-pi/2, 0], which is what lets the rose be drawn as a
    quadrant fan with nothing clipped.

    `reference` must be a positive slope in the same units as `slope`. It
    is not optional and has no default here on purpose - see the module
    docstring.
    """
    reference = float(reference)
    if reference <= 0:
        raise ValueError(
            f"reference slope must be positive, got {reference} - it sets "
            "how many mV equal one second on the page and a non-positive "
            "value flips or collapses every angle")
    return float(np.arctan(np.asarray(slope, dtype=float) / reference))


def slope_angles(slopes, references):
    """Vectorised `slope_angle` with a per-event reference, so `recording`
    and `event` scales (where the reference differs row by row) go through
    the same arithmetic as `raw`."""
    slopes = np.asarray(slopes, dtype=float)
    references = np.asarray(references, dtype=float)
    if np.any(references <= 0):
        raise ValueError("every reference slope must be positive")
    return np.arctan(slopes / references)


def reference_slope(gradients, scale, fixed=DEFAULT_SLOPE_REF_MV_S,
                    field="max_slope_mv_s"):
    """One reference slope per event, per the named scale.

    Always returns an array the same length as `gradients`, even for the
    scales where every entry is identical, so the caller never has to
    branch on which mode it asked for.
    """
    gradients = list(gradients)
    n = len(gradients)
    if n == 0:
        return np.array([], dtype=float)

    if scale == "raw":
        return np.full(n, abs(float(fixed)))

    if scale == "event":
        if field in _POSITIVE_FIELDS:
            raise ValueError(
                f"scale='event' divides by the event's own mean slope, which "
                f"is meaningless for {field!r} - that quantity is already a "
                "ratio. Use scale='pooled' or 'recording' instead.")
        # The event's own mean fall slope: the angle becomes arctan of the
        # dimensionless peakedness ratio.
        return np.array([max(abs(g["mean_slope_mv_s"]), 1e-12)
                         for g in gradients])

    magnitudes = np.array([abs(g[field]) for g in gradients])

    if scale == "pooled":
        median = float(np.median(magnitudes[magnitudes > 0])) \
            if np.any(magnitudes > 0) else 1.0
        return np.full(n, max(median, 1e-12))

    if scale == "recording":
        references = np.empty(n, dtype=float)
        # `.get` rather than `[...]`: gradients built by hand (a test, a
        # notebook) need not carry provenance, and the sensible answer
        # there is one group, not a KeyError.
        recordings = np.array([g.get("recording_id", 0) for g in gradients])
        for recording_id in np.unique(recordings):
            mask = recordings == recording_id
            own = magnitudes[mask]
            own = own[own > 0]
            median = float(np.median(own)) if own.size else 1.0
            references[mask] = max(median, 1e-12)
        return references

    raise ValueError(f"unknown slope scale {scale!r} - must be one of {SLOPE_SCALES}")


def scale_caption(scale, references, fixed=DEFAULT_SLOPE_REF_MV_S,
                  field="max_slope_mv_s"):
    """One line saying what 45 degrees means, for the figure.

    A rose without this is uninterpretable, so it is built here rather
    than written out at each call site where it could drift from the
    reference actually used.
    """
    ratio = field in _POSITIVE_FIELDS
    unit = "" if ratio else " mV/s"
    what = "peakedness" if ratio else "steepest slope"

    if scale == "raw":
        return f"45° = {abs(float(fixed)):g}{unit} (stated reference)"
    if scale == "event":
        return "45° = the event's own mean fall slope (dimensionless ratio)"
    if scale == "pooled":
        value = float(np.median(references)) if references is not None \
            and len(references) else 0.0
        return f"45° = the pooled median {what}, {value:.3g}{unit}"
    if scale == "recording":
        if references is None or not len(references):
            return f"45° = each recording's own median {what}"
        distinct = sorted({round(float(r), 6) for r in references})
        shown = ", ".join(f"{r:.3g}" for r in distinct)
        return f"45° = each recording's own median {what} ({shown}{unit})"
    return ""


# -- circular statistics ---------------------------------------------------

def circular_mean(angles):
    """Mean DIRECTION, as the angle of the summed unit vectors.

    Not the arithmetic mean of the angles, which is wrong whenever the
    data straddles a wrap point: 170 and -170 degrees average
    arithmetically to 0, pointing the exact opposite way from the correct
    answer of 180. On slope angles confined to one quadrant the two happen
    to agree, but the mean-direction arrow on a rose must be right for any
    input it is given, not only the well-behaved one.
    """
    angles = np.asarray(angles, dtype=float).ravel()
    if angles.size == 0:
        return float("nan")
    return float(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()))


def resultant_length(angles):
    """Mean resultant length R, in [0, 1].

    The length of the average unit vector: 1 when every direction is
    identical, ~0 when they are spread evenly round the circle. This is
    the number that says whether a rose's dominant lobe means anything,
    and it belongs on the figure next to the mean direction - a mean
    direction with R = 0.1 is not a finding.
    """
    angles = np.asarray(angles, dtype=float).ravel()
    if angles.size == 0:
        return 0.0
    return float(np.hypot(np.cos(angles).mean(), np.sin(angles).mean()))


def circular_sd_deg(angles):
    """Circular standard deviation in degrees, from R.

    `sqrt(-2 ln R)`, the standard definition. Reported alongside R because
    R is unitless and hard to read, while "the falls are within 4 degrees
    of each other" is not.
    """
    R = resultant_length(angles)
    if R <= 0.0 or R >= 1.0:
        return 0.0 if R >= 1.0 else float("inf")
    return float(np.rad2deg(np.sqrt(-2.0 * np.log(R))))


def uniformity_p(angles, lo, hi):
    """p-value against "uniform over [lo, hi]", by a one-sample KS test.

    NOT a Rayleigh test, deliberately. Rayleigh tests uniformity over the
    FULL circle, and slope angles can only ever occupy one quadrant, so a
    Rayleigh test here is significant by construction and measures nothing
    but the constraint. Testing against uniform over the achievable
    support asks the question actually of interest: given that every fall
    must land in this quadrant, are they clustered within it?
    """
    from scipy.stats import kstest

    angles = np.asarray(angles, dtype=float).ravel()
    if angles.size < 3 or hi <= lo:
        return float("nan")
    scaled = (angles - lo) / (hi - lo)
    return float(kstest(np.clip(scaled, 0.0, 1.0), "uniform").pvalue)


# -- binning ---------------------------------------------------------------

def rose_histogram(angles, n_bins=18, lo=-np.pi / 2, hi=0.0):
    """Bin angles for the rose. Returns `(bin_centres, counts, bin_width)`.

    The upper edge is inclusive so an angle of exactly `hi` - a perfectly
    flat fall, which `slope_angle(0)` returns - lands in the last bin
    instead of falling off the end and disappearing from the figure.
    """
    angles = np.asarray(angles, dtype=float).ravel()
    edges = np.linspace(lo, hi, int(n_bins) + 1)
    width = (hi - lo) / float(n_bins)
    centres = edges[:-1] + width / 2.0
    if angles.size == 0:
        return centres, np.zeros(int(n_bins), dtype=int), width
    counts, _ = np.histogram(np.clip(angles, lo, hi), bins=edges)
    return centres, counts.astype(int), width


# -- the whole measurement, once -------------------------------------------

def rose_data(events, snippets, *, scale="raw", fixed=DEFAULT_SLOPE_REF_MV_S,
              field="max_slope_mv_s", n_bins=18, split_by="span_key"):
    """Everything a rose figure needs, computed once.

    Returns the per-event gradients and angles, the binned counts for the
    pooled set and for each group, and the circular statistics per group -
    so the drawn figure and any quoted number provably describe the same
    measurement.
    """
    gradients = event_gradients(events, snippets)
    if not gradients:
        return {"gradients": [], "angles": np.array([]), "groups": {},
                "scale": scale, "field": field, "caption": "", "n": 0}

    references = reference_slope(gradients, scale, fixed=fixed, field=field)
    slopes = np.array([g[field] for g in gradients])
    # `peakedness` arrives positive; every rose lives in the falling
    # quadrant, so it is negated for display. The stored `slopes_mv_s`
    # below keeps the original sign, so a quoted number is never the
    # display-flipped one.
    display = -np.abs(slopes) if field in _POSITIVE_FIELDS else slopes
    angles = slope_angles(display, references)

    lo, hi = -np.pi / 2, 0.0
    centres, counts, width = rose_histogram(angles, n_bins, lo, hi)

    groups = {}
    keys = [g[split_by] for g in gradients]
    for key in sorted(set(keys)):
        mask = np.array([k == key for k in keys])
        own = angles[mask]
        _, own_counts, _ = rose_histogram(own, n_bins, lo, hi)
        groups[key] = {
            "n": int(mask.sum()),
            "angles": own,
            "counts": own_counts,
            "slopes_mv_s": slopes[mask],
            "source_file": gradients[int(np.argmax(mask))]["source_file"],
            "span_label": gradients[int(np.argmax(mask))]["span_label"],
            "mean_deg": float(np.rad2deg(circular_mean(own))),
            "resultant_length": resultant_length(own),
            "circular_sd_deg": circular_sd_deg(own),
            "uniformity_p": uniformity_p(own, lo, hi),
            "median_slope_mv_s": float(np.median(slopes[mask])),
        }

    return {
        "gradients": gradients,
        "angles": angles,
        "references": references,
        "bin_centres": centres,
        "counts": counts,
        "bin_width": width,
        "lo": lo, "hi": hi,
        "groups": groups,
        "scale": scale,
        "field": field,
        "caption": scale_caption(scale, references, fixed, field),
        "n": len(gradients),
        "mean_deg": float(np.rad2deg(circular_mean(angles))),
        "resultant_length": resultant_length(angles),
        "circular_sd_deg": circular_sd_deg(angles),
        "uniformity_p": uniformity_p(angles, lo, hi),
    }
