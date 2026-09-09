"""
store11.py
===========
Read access to a finished drop_motifs store, for a run that detects
nothing. Every figure in drop_motifs11 gets its numbers from here, so that
no two figures can be measuring the same quantity two different ways.

The unit of `max_slope_raw`, settled from the source
-----------------------------------------------------
The brief flagged this and it is a real defect in a conversion already in
circulation. Traced:

    detect5.py:596   derivative = np.gradient(x_detrended) * fs
    detect5.py:769   max_slope_raw = float(derivative[onset:trough + 1].min())

`x_detrended` is in VOLTS - the same function writes
`drop_depth_mv = candidate["depth"] * 1000.0` two lines later - and the
`* fs` is ALREADY APPLIED at line 596. So `max_slope_raw` is volts per
second, and the conversion to millivolts per second is `* 1000` and
nothing else. Multiplying by `fs` again applies the sampling rate twice.

That is not a stylistic preference; it is checkable, and it fails a
physical bound. For a monotone fall of N samples the steepest single
sample cannot be more than about N times the fall's own chord, so
`peakedness = max_slope / mean_slope` is bounded above by N:

    conversion            median peakedness, reishi     rows above the
                                                        N-sample ceiling
    x1000       (V/s)     1.81                          0.2%
    x1000 x fs            17.10                         69%

Reishi's median fall is 6 samples. A peakedness of 17.1 on a 6-sample
monotone fall is arithmetically impossible, and only the 10 Hz corpus
moves between the two columns, which is the signature of a double `fs`.
`MAX_SLOPE_TO_MV_S` is therefore 1000.0, and it is stated in every
manifest.

Other traps this module exists to absorb
-----------------------------------------
  - `t_s` in a snippet is ABSOLUTE seconds in the recording, not time from
    onset. `native_trace` returns time from onset.
  - `onset_idx` / `trough_idx` / `snippet_*_idx` are absolute sample
    indices; the offset into a stored array is `idx - snippet_start_idx`.
  - `reishi_1hz` is a decimated control, not a species. It is excluded by
    default; see `config11.CONTROL_CORPORA`.

No detection, no writes to the store.
"""

import numpy as np

from Pipelines.drop_motifs import config11
from Pipelines.drop_motifs.clusterfigs7 import _waveform_of
from Working.Detection.drop_motifs import motifs5

# Volts per second -> millivolts per second. `fs` is already in the stored
# value; see the module docstring.
MAX_SLOPE_TO_MV_S = 1000.0

MAX_SLOPE_UNIT_NOTE = (
    "max_slope_raw is V/s (detect5.py:596 already multiplies the gradient "
    "by fs); mV/s = max_slope_raw * 1000, with no second fs factor"
)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load(store_dir, species=None, include_control=False, pure_only=False):
    """`(rows, snippets, manifest)` for the species asked for.

    `species=None` means every species in the store - the list is read
    off the store, never written down here. `include_control` puts the
    decimated reishi_1hz rate-control arm back in; it is off by default
    because it would draw the same organism's events twice.
    """
    rows, snippets, manifest = motifs5.load_store(store_dir,
                                                  pure_only=pure_only)
    if not include_control:
        rows = [r for r in rows
                if r.get("corpus") not in config11.CONTROL_CORPORA]
    if species:
        wanted = set(species)
        rows = [r for r in rows if r.get("species") in wanted]
    for row in rows:
        row["onset_s"] = float(row["onset_idx"]) / float(row["fs"])
        row["max_slope_mv_s"] = max_slope_mv_s(row)
        row["mean_slope_mv_s"] = mean_slope_mv_s(row)
    rows.sort(key=lambda r: (str(r.get("species")), int(r["catalogue_id"]),
                             str(r["channel"]), r["onset_s"]))
    return rows, snippets, manifest


def species_in(rows):
    """The species present, in the run's fixed order. Derived, not stated."""
    return config11.order({r.get("species") for r in rows})


def counts_by_species(rows):
    counts = {}
    for row in rows:
        counts[row.get("species")] = counts.get(row.get("species"), 0) + 1
    return counts


def by_species(rows):
    """`{species: [rows]}`, in run order, each already onset-sorted."""
    out = {key: [] for key in species_in(rows)}
    for row in rows:
        out[row.get("species")].append(row)
    return out


def group_key(row):
    """The unit of measurement for anything involving timing.

    One channel of one catalogue span. Inter-event intervals are only
    meaningful inside one, and the three species' intervals differ by two
    orders of magnitude, so nothing about timing may be pooled before it
    has been measured per group.
    """
    return (int(row["catalogue_id"]), str(row["channel"]))


def groups(rows):
    """`{(catalogue_id, channel): [rows]}`, each sorted by onset."""
    out = {}
    for row in rows:
        out.setdefault(group_key(row), []).append(row)
    for members in out.values():
        members.sort(key=lambda r: r["onset_s"])
    return out


# --------------------------------------------------------------------------
# per-event quantities
# --------------------------------------------------------------------------

def max_slope_mv_s(row):
    """The steepest single sample of the fall, in mV/s. See the docstring."""
    return abs(float(row["max_slope_raw"])) * MAX_SLOPE_TO_MV_S


def mean_slope_mv_s(row):
    """The chord: depth over duration. Identically `depth / duration`, so
    it may never be plotted against depth - see the appendix."""
    duration = float(row["fall_duration_s"])
    if duration <= 0:
        return 0.0
    return abs(float(row["drop_depth_mv"])) / duration


def peakedness(row):
    mean = mean_slope_mv_s(row)
    return max_slope_mv_s(row) / mean if mean > 0 else np.nan


def fall_angle_rad(row, reference_mv_s):
    """`arctan(-slope / reference)`, in radians, in the falling quadrant.

    An angle needs a stated reference: `arctan` takes a dimensionless
    argument, and a slope in mV/s has no angle until something says how
    many millivolts equal one second on the page. The reference is passed
    in rather than defaulted, and every figure using it prints it.
    """
    reference = float(reference_mv_s)
    if reference <= 0:
        raise ValueError("reference slope must be positive; it sets how "
                         "many mV equal one second on the page")
    return float(np.arctan(-max_slope_mv_s(row) / reference))


def pooled_reference_mv_s(rows):
    """The pooled median steepest slope, in mV/s. One reference for all."""
    values = np.array([max_slope_mv_s(r) for r in rows], dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    return float(np.median(values)) if values.size else 1.0


# --------------------------------------------------------------------------
# waveforms
# --------------------------------------------------------------------------

def fall(row, snippets, field="detrended_mv"):
    """The event itself, onset to trough, in millivolts.

    Delegates to `clusterfigs7._waveform_of`, which RAISES rather than
    clips when the stored array is shorter than the row's own bounds claim
    - the store defect that put 22 constant vectors into the drop_motifs9
    tree. The drop_motifs10 store has none, and this call is what keeps
    that true rather than assumed.
    """
    return _waveform_of(row, snippets, field=field,
                        orient_rises_as_drops=False)


def native_trace(row, snippets, pre_falls=0.6, post_falls=1.6,
                 field="detrended_mv"):
    """`(t_from_onset_s, mv)` for one event, baseline-shifted to onset.

    Real seconds and real millivolts: this is a crop and an offset, never
    a rescaling, so the drop keeps the proportion it has in the recording.
    The offset removes the resting level so events from different parts of
    a trace can share an axis; it changes no distance and no shape.
    """
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None, None
    values = np.asarray(arrays[field], dtype=float)
    start = int(row["snippet_start_idx"])
    fs = float(row["fs"])
    onset = int(row["onset_idx"]) - start
    if not (0 <= onset < values.size):
        return None, None

    t = (np.arange(values.size) - onset) / fs
    y = values - values[onset]

    duration = abs(float(row["fall_duration_s"])) or (1.0 / fs)
    keep = (t >= -pre_falls * duration) & (t <= post_falls * duration)
    if keep.sum() < 3:
        keep = np.ones(values.size, dtype=bool)
    return t[keep], y[keep]


def normalised_fall(row, snippets, n=200, field="detrended_mv"):
    """The fall, resampled to `n` points and z-normalised.

    Both duration and amplitude are divided out, which is exactly what
    makes "the same shape at two scales" a question with an answer. A
    constant waveform is not a shape and returns `None` rather than the
    all-zero vector that would sit on top of every other all-zero vector.
    """
    wave = fall(row, snippets, field=field)
    if wave is None or np.asarray(wave).size < 2:
        return None
    wave = np.asarray(wave, dtype=float)
    if float(np.ptp(wave)) == 0.0:
        return None
    grid = np.linspace(0.0, 1.0, int(n))
    resampled = np.interp(grid, np.linspace(0.0, 1.0, wave.size), wave)
    sd = float(resampled.std())
    if sd == 0.0:
        return None
    return (resampled - resampled.mean()) / sd


def normalised_block(rows, snippets, n=200, field="detrended_mv"):
    """`(features, kept_rows, dropped)` - every drawable normalised fall."""
    features, kept = [], []
    dropped = {"no_array": 0, "store_mismatch": 0, "constant": 0}
    for row in rows:
        try:
            vector = normalised_fall(row, snippets, n=n, field=field)
        except ValueError:
            dropped["store_mismatch"] += 1
            continue
        except KeyError:
            dropped["no_array"] += 1
            continue
        if vector is None:
            dropped["constant"] += 1
            continue
        features.append(vector)
        kept.append(row)
    if not features:
        return np.empty((0, int(n))), [], dropped
    return np.vstack(features), kept, dropped


# --------------------------------------------------------------------------
# timing - intervals, and the duty cycle they define
# --------------------------------------------------------------------------

def interval_stats(rows):
    """Per-group inter-event interval statistics.

    `{(catalogue_id, channel): {species, n, median_iei_s, cv, median_fall_s,
    duty}}`. `duty` is the group's median fall duration over its own median
    interval: how much of the time between two events the fall itself
    occupies. It is the one measurement that separates "broad" from "long",
    and it must be computed per group because the groups' intervals differ
    by two orders of magnitude.
    """
    out = {}
    for key, members in groups(rows).items():
        if len(members) < 2:
            continue
        onsets = np.array([r["onset_s"] for r in members], dtype=float)
        intervals = np.diff(onsets)
        intervals = intervals[intervals > 0]
        if intervals.size == 0:
            continue
        median_iei = float(np.median(intervals))
        falls = np.array([abs(float(r["fall_duration_s"])) for r in members])
        median_fall = float(np.median(falls))
        out[key] = {
            "species": members[0].get("species"),
            "catalogue_id": key[0],
            "channel": key[1],
            "n": len(members),
            "median_iei_s": median_iei,
            "cv_iei": float(intervals.std(ddof=1) / intervals.mean())
                      if intervals.size > 1 and intervals.mean() > 0 else float("nan"),
            "median_fall_s": median_fall,
            "duty": median_fall / median_iei if median_iei > 0 else float("nan"),
        }
    return out


def duty_by_species(rows):
    """`{species: {duty_median, duty_values, fall_median_s, iei_median_s, n_groups}}`.

    Computed per (catalogue_id, channel) group and then pooled per species,
    as the brief specifies. The spread carried alongside the median is the
    group-level spread, which is the honest one: pooling events would make
    a channel with 700 events outvote fourteen channels with 20.
    """
    stats = interval_stats(rows)
    out = {}
    for entry in stats.values():
        out.setdefault(entry["species"], []).append(entry)
    summary = {}
    for species in config11.order(out):
        entries = out[species]
        duty = np.array([e["duty"] for e in entries], dtype=float)
        duty = duty[np.isfinite(duty)]
        falls = np.array([e["median_fall_s"] for e in entries], dtype=float)
        ieis = np.array([e["median_iei_s"] for e in entries], dtype=float)
        cvs = np.array([e["cv_iei"] for e in entries], dtype=float)
        cvs = cvs[np.isfinite(cvs)]
        summary[species] = {
            "n_groups": len(entries),
            "n_events": int(sum(e["n"] for e in entries)),
            "duty_values": duty,
            "duty_median": float(np.median(duty)) if duty.size else float("nan"),
            "duty_q1": float(np.percentile(duty, 25)) if duty.size else float("nan"),
            "duty_q3": float(np.percentile(duty, 75)) if duty.size else float("nan"),
            "fall_values": falls,
            "fall_median_s": float(np.median(falls)) if falls.size else float("nan"),
            "iei_median_s": float(np.median(ieis)) if ieis.size else float("nan"),
            "cv_iei_median": float(np.median(cvs)) if cvs.size else float("nan"),
        }
    return summary


# --------------------------------------------------------------------------
# ranges, for the panel labels that state what a figure spans
# --------------------------------------------------------------------------

def span_of(rows, field):
    values = np.array([abs(float(r[field])) for r in rows], dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        return (float("nan"), float("nan"))
    return (float(values.min()), float(values.max()))


def orders_of_magnitude(rows, field):
    low, high = span_of(rows, field)
    if not (np.isfinite(low) and np.isfinite(high)) or low <= 0:
        return float("nan")
    return float(np.log10(high / low))


def range_label(rows, field, unit, fmt="{:.3g}"):
    """`0.1-3.8 s` - the sampled events' own extent, for a panel label."""
    low, high = span_of(rows, field)
    if not np.isfinite(low):
        return "range unavailable"
    return f"{fmt.format(low)}-{fmt.format(high)} {unit}"


# --------------------------------------------------------------------------
# aspect - a drop drawn the shape it is in the recording
# --------------------------------------------------------------------------

def aspect_for(rows, cap=6.0, floor=0.4):
    """`(aspect, true_ratio, capped)` - the mV-per-second scale for a panel.

    Reuses `style7.seconds_per_mv`, which puts the median event of the set
    at a readable proportion, rather than deriving a second one here. The
    cap is `style7`'s: beyond about 6:1 a panel is a sliver and shows
    nothing, so the drawn aspect is limited and the TRUE ratio is returned
    for the panel label to state. Capping silently is what makes a figure
    lie about a shape; capping and saying so does not.
    """
    from Pipelines.drop_motifs import style7

    depths = [abs(float(r.get("drop_depth_mv", 0.0))) for r in rows]
    falls = [abs(float(r.get("fall_duration_s", 0.0))) for r in rows]
    aspect = style7.seconds_per_mv(depths, falls)

    depth = np.array(depths, dtype=float)
    fall = np.array(falls, dtype=float)
    good = np.isfinite(depth) & np.isfinite(fall) & (depth > 0) & (fall > 0)
    if not good.any():
        return 1.0, float("nan"), False
    # Height over width as it would be drawn at this aspect.
    ratio = float(aspect * np.median(depth[good]) / np.median(fall[good]))
    drawn = float(np.clip(ratio, floor, cap))
    if drawn == ratio:
        return aspect, ratio, False
    return aspect * drawn / ratio, ratio, True


def aspect_caption(aspect, true_ratio=None, capped=False):
    from Pipelines.drop_motifs import style7

    text = style7.aspect_caption(aspect)
    if capped and true_ratio is not None and np.isfinite(true_ratio):
        text += f"; drawn ratio capped, true {true_ratio:.3g}:1"
    return text
