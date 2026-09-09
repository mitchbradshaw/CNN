"""
sequences11.py
===============
Task S3.0. A sequence is a run of consecutive events on one channel that
is regular enough to read as a progression rather than as scattered
detections. Section 3's figures all select from what this module writes,
never by hand.

Two steps, and both thresholds are per-group
---------------------------------------------
Step 1, SPLIT. Within each (catalogue_id, channel) group, order by onset
and cut wherever the gap exceeds `GAP_MULTIPLE` (2.0) times that group's
OWN median inter-event interval. Per group, not global: Reishi's median
interval is 2.3 s and Oyster's is 192 s, so one global gap threshold would
either cut every Reishi run into singletons or never cut an Oyster one.
Runs of at least `MIN_RUN` (5) events are kept.

Step 2, GATE ON REGULARITY. A run qualifies on either arm:

  constant gap   coefficient of variation of its intervals <= CV_MAX (0.5)
  constant rate  R-squared of interval against event index >= R2_MIN (0.7)
     of change

The two arms are recorded SEPARATELY and not merged into one count. On
this store the trend arm alone qualifies a handful of runs where the
constant-gap arm qualifies over a hundred, and if ramping sequences really
are that rare it is a finding for Section 3, not something to hide inside
a combined total.

Drift, which is the point of Section 3
---------------------------------------
"Near-constant gap" can still mean systematically wider at the end than at
the start. For every constant-gap run the ratio of its last third's mean
interval to its first third's is recorded, and runs beyond +/-`DRIFT_MARK`
(20%) are marked. That slow widening is exactly the morphing Section 3 is
about, so it is measured rather than assumed absent.

No plotting here; `figures11_s3` draws from `sequences.csv`.
"""

import csv
import os

import numpy as np

from Pipelines.drop_motifs import config11, store11

# Step 1
GAP_MULTIPLE = 2.0        # cut where the gap exceeds this x the group median
MIN_RUN = 5               # events

# Step 2
CV_MAX = 0.5              # constant-gap arm
R2_MIN = 0.7              # constant-rate-of-change arm

# A run whose gap drifts by more than this fraction is marked, so Figure
# S3.1's third panel can be selected by rule rather than by eye.
DRIFT_MARK = 0.20

ARM_CONSTANT = "constant_gap"
ARM_TREND = "trend"

FIELDS = ("sequence_key", "species", "catalogue_id", "channel",
          "start_event_id", "end_event_id", "n", "cv_interval", "r2_trend",
          "drift_ratio", "arm", "arm_constant_gap", "arm_trend",
          "high_drift", "start_onset_s", "end_onset_s", "duration_s",
          "median_interval_s", "group_median_interval_s",
          "median_fall_s", "median_depth_mv")


def _regularity(intervals):
    """`(cv, r2)` for one run's intervals.

    CV uses the sample standard deviation (ddof=1): these are samples of a
    process, not a population, and on a five-event run - four intervals -
    the difference between the two definitions is 15%, which is large
    enough to move runs across a 0.5 threshold.
    """
    intervals = np.asarray(intervals, dtype=float)
    mean = float(intervals.mean()) if intervals.size else 0.0
    if intervals.size < 2 or mean <= 0:
        return float("inf"), 0.0
    cv = float(intervals.std(ddof=1) / mean)
    if float(intervals.std()) == 0.0:
        # A perfectly constant gap has no trend to fit, and R-squared of a
        # flat line is undefined rather than 1. CV already qualifies it.
        return cv, 0.0
    index = np.arange(intervals.size, dtype=float)
    r = float(np.corrcoef(index, intervals)[0, 1])
    return cv, float(r * r)


def _drift(intervals):
    """Last third's mean interval over the first third's.

    1.0 is no drift, above 1 is widening, below 1 is tightening. Thirds
    rather than first-against-last interval because a single interval is
    noise and a third is a measurement.
    """
    intervals = np.asarray(intervals, dtype=float)
    if intervals.size < 2:
        return float("nan")
    third = max(1, intervals.size // 3)
    head = float(intervals[:third].mean())
    tail = float(intervals[-third:].mean())
    return tail / head if head > 0 else float("nan")


def candidates(rows):
    """Step 1 only: every run of >= MIN_RUN consecutive events. """
    out = []
    for key, members in store11.groups(rows).items():
        if len(members) < 2:
            continue
        onsets = np.array([r["onset_s"] for r in members], dtype=float)
        gaps = np.diff(onsets)
        positive = gaps[gaps > 0]
        if positive.size == 0:
            continue
        group_median = float(np.median(positive))
        cuts = np.flatnonzero(gaps > GAP_MULTIPLE * group_median)
        starts = [0] + list(cuts + 1)
        ends = list(cuts + 1) + [len(members)]
        for start, end in zip(starts, ends):
            if end - start < MIN_RUN:
                continue
            out.append((key, group_median, members[start:end]))
    return out


def extract(rows):
    """`(runs, summary)`. `runs` is a list of dicts, one per qualifying run.

    Each run carries its member rows under `rows` for the figures, and
    everything else is a scalar that goes straight into `sequences.csv`.
    """
    runs, rejected = [], 0
    for (catalogue_id, channel), group_median, members in candidates(rows):
        onsets = np.array([r["onset_s"] for r in members], dtype=float)
        intervals = np.diff(onsets)
        cv, r2 = _regularity(intervals)
        constant = bool(cv <= CV_MAX)
        trend = bool(r2 >= R2_MIN)
        if not (constant or trend):
            rejected += 1
            continue
        # Measured on every qualifying run; the manifest reports the
        # distribution over the CONSTANT-GAP runs specifically, because
        # "near-constant but systematically widening" is the case the
        # brief asks about and a trend-arm run is drifting by definition.
        drift = _drift(intervals)
        arm = (ARM_CONSTANT if constant and not trend else
               ARM_TREND if trend and not constant else
               f"{ARM_CONSTANT}+{ARM_TREND}")
        runs.append({
            "sequence_key": f"{members[0]['species']}_id{catalogue_id}"
                            f"_ch{channel}_{int(round(onsets[0]))}s",
            "species": members[0].get("species"),
            "catalogue_id": int(catalogue_id),
            "channel": str(channel),
            "start_event_id": members[0]["event_id"],
            "end_event_id": members[-1]["event_id"],
            "n": len(members),
            "cv_interval": float(cv),
            "r2_trend": float(r2),
            "drift_ratio": float(drift),
            "arm": arm,
            "arm_constant_gap": constant,
            "arm_trend": trend,
            "high_drift": bool(np.isfinite(drift)
                               and abs(drift - 1.0) > DRIFT_MARK),
            "start_onset_s": float(onsets[0]),
            "end_onset_s": float(onsets[-1]),
            "duration_s": float(onsets[-1] - onsets[0]),
            "median_interval_s": float(np.median(intervals)),
            "group_median_interval_s": float(group_median),
            "median_fall_s": float(np.median(
                [abs(float(r["fall_duration_s"])) for r in members])),
            "median_depth_mv": float(np.median(
                [abs(float(r["drop_depth_mv"])) for r in members])),
            "rows": members,
        })

    runs.sort(key=lambda run: (config11.order([run["species"]])[0],
                               -run["n"]))
    return runs, summarise(runs, rejected=rejected,
                           n_candidates=len(candidates(rows)))


def summarise(runs, rejected=0, n_candidates=None):
    """Per-species counts, split by arm, plus the drift distribution.

    The arms are reported separately and the combined total is derived
    from them rather than the other way round, so "how many ramping
    sequences are there" is answerable from the manifest alone.
    """
    species = config11.order({run["species"] for run in runs})
    per_species = {}
    for name in species:
        own = [r for r in runs if r["species"] == name]
        constant_only = [r for r in own if r["arm_constant_gap"] and not r["arm_trend"]]
        trend_only = [r for r in own if r["arm_trend"] and not r["arm_constant_gap"]]
        both = [r for r in own if r["arm_trend"] and r["arm_constant_gap"]]
        drift = np.array([r["drift_ratio"] for r in own
                          if r["arm_constant_gap"]], dtype=float)
        drift = drift[np.isfinite(drift)]
        per_species[name] = {
            "runs": len(own),
            "events": int(sum(r["n"] for r in own)),
            "longest_n": max((r["n"] for r in own), default=0),
            "arm_constant_gap_only": len(constant_only),
            "arm_trend_only": len(trend_only),
            "arm_both": len(both),
            "drift_n": int(drift.size),
            "drift_median": float(np.median(drift)) if drift.size else float("nan"),
            "drift_q1": float(np.percentile(drift, 25)) if drift.size else float("nan"),
            "drift_q3": float(np.percentile(drift, 75)) if drift.size else float("nan"),
            "high_drift_runs": int(sum(1 for r in own if r["high_drift"])),
        }
    return {
        "thresholds": {
            "gap_multiple": GAP_MULTIPLE,
            "min_run_events": MIN_RUN,
            "cv_max": CV_MAX,
            "r2_min": R2_MIN,
            "drift_mark": DRIFT_MARK,
            "cv_definition": "sample sd (ddof=1) / mean",
            "split_scope": "per (catalogue_id, channel), on that group's own "
                           "median inter-event interval",
        },
        "n_candidate_runs": n_candidates,
        "n_rejected_runs": rejected,
        "total_runs": len(runs),
        "total_events": int(sum(r["n"] for r in runs)),
        "arm_constant_gap_total": sum(1 for r in runs if r["arm_constant_gap"]),
        "arm_trend_total": sum(1 for r in runs if r["arm_trend"]),
        "arm_trend_only_total": sum(1 for r in runs
                                    if r["arm_trend"] and not r["arm_constant_gap"]),
        "per_species": per_species,
    }


def write_csv(path, runs):
    """One row per qualifying run. Every figure in Section 3 selects here."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FIELDS))
        writer.writeheader()
        for run in runs:
            writer.writerow({key: run[key] for key in FIELDS})
    return path


# --------------------------------------------------------------------------
# selection - by rule, never by hand
# --------------------------------------------------------------------------

def longest(runs, species, require_constant=False):
    """The longest qualifying run for one species, or `None`."""
    own = [r for r in runs if r["species"] == species]
    if require_constant:
        own = [r for r in own if r["arm_constant_gap"]]
    if not own:
        return None
    return max(own, key=lambda r: (r["n"], -r["cv_interval"]))


def most_drifted(runs, species, min_n=MIN_RUN):
    """The LONGEST run whose gap drifts beyond `DRIFT_MARK`.

    Length first, drift second, and not the other way round: ranking on
    drift magnitude alone picks a six-event run with an extreme ratio,
    and six events cannot show a morph. The rule is "a long run that also
    drifts", which is the case Section 3 is about.
    """
    own = [r for r in runs
           if r["species"] == species and r["high_drift"]
           and r["n"] >= min_n and np.isfinite(r["drift_ratio"])]
    if not own:
        return None
    return max(own, key=lambda r: (r["n"], abs(r["drift_ratio"] - 1.0)))


def clearest(runs, species):
    """The run a species is best represented by: longest, then most regular.

    "Clearest" has to be a rule or Figure S3.2 is a hand-picked gallery.
    Length first because a short run cannot show a morph, CV second
    because among long runs the regular one reads as a progression.
    """
    own = [r for r in runs if r["species"] == species]
    if not own:
        return None
    cutoff = max(r["n"] for r in own) * 0.6
    shortlist = [r for r in own if r["n"] >= cutoff] or own
    return min(shortlist, key=lambda r: (r["cv_interval"], -r["n"]))
