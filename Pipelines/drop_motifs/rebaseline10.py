"""
rebaseline10.py
================
Task 6. Task 1 changed counts that earlier runs validated, so this module
proves the change is the fix and not drift.

How attribution is done
-----------------------
Not by reasoning about the diff. Every fix in Task 1 has an OFF switch,
and the audit walks a ladder of configurations from "drop_motifs8 exactly"
to "drop_motifs10 exactly", one fix at a time, re-running the detector at
each rung. A span's count moving between two rungs is attributed to the
one fix that separates them; a span's count moving with no rung to pin it
on is a finding and is reported as one.

    rung            what is on
    ---------------------------------------------------------------
    drop8           nothing. inverted pass ON, and NO depth floor.
    +dedup_units    passes6.deduplicate's tolerance x fs (defect 1)
    +fall_bracket   _fall_limit and window_bounds bound on the next
                    FALL as well as the next rise (defects 3, 4)
    +walk_back      the onset moves onto the shoulder before the gates
                    read the depth (defect 4)
    +drops_only     the inverted pass is not run - NOT a defect fix, a
                    deliberate parameterisation change, and it must not
                    be counted as one
    +global_floor   the 0.1 mV floor - also NOT a defect fix. It was
                    introduced by `refine9` for drop_motifs9 and has
                    never been applied to the catalogue before
    +derived_floor  the per-span 3-sigma floor replaces 0.1 mV (defect 6)
                    = drop_motifs10 as run

THE CONTROL RUNG APPLIES NO DEPTH FLOOR, and getting that wrong was
caught by the control itself. The first version of this ladder floored
the control at 0.1 mV on the assumption that drop_motifs8 had, and id10
came back 85 against 86 and id26 37 against 40 with identical
`n_before_dedup` and `n_duplicates_dropped` - detection and merge
identical, so the difference had to be downstream of both. It was: the
0.1 mV gate lives in `refine9.depth_gate`, which drop_motifs9 introduced
for Fig2A and which never ran over the catalogue. The floor is therefore
its own rung, and the catalogue meets a depth floor for the first time in
this run.

The first rung is the control. If it does not reproduce
`Plots/drop_motifs8/run_summary.json` span for span, the ladder is
measuring something other than what it claims and the audit says so
before any other number in it is read.

up_runs, the gate-free bracket
------------------------------
As drop_motifs7 used it. The encoding is permissive, the eye is selective,
and gated detection is conservative, so for any span

    up_runs  >=  what a human counts  >=  what the detector confirms

should hold. It is a bracket rather than a target: a span where detection
EXCEEDS the encoding's own count of rises has found events the encoding
never proposed, which cannot happen without something being wrong.

THE BRACKET HAS TO BE READ AT THE RIGHT SCALE, and the first version of
this audit did not. `up_runs` is a property of ONE encoding, and an
encoding is fixed by a segment length. drop_motifs7's bracket was a
single-scale statement; drop_motifs10 runs four passes whose segment
lengths differ by more than an order of magnitude, and the `micro` pass
in particular scans down to a small fraction of the span. Comparing a
four-pass TOTAL against the BASE pass's up_runs compares a count made at
one scale against an encoding made at another, and it failed on eight of
sixteen spans for exactly that reason and no other.

So the bracket is reported twice, and only the second is a test:

  BASE-PASS BRACKET     base up_runs vs the base pass's own detections.
                        Apples to apples, and this is drop_motifs7's
                        statement unchanged.
  MULTI-SCALE BRACKET   the LARGEST up_runs count over the passes that
                        actually ran, against the four-pass total. This
                        is the gate-free number for a multi-scale
                        detector: the encoding at its most permissive
                        setting still proposed at least as many rises as
                        the detector confirmed events.
"""

import numpy as np

from dataclasses import replace

from Pipelines.drop_motifs import (corpora10, floor10, passes6, passes7,
                                   passes8, spans5)
from Working.Detection.drop_motifs import detect5

# The four counts a human stated. `annotated_n` in `spans5.SPANS5` is the
# catalogue's own prose count; `detected8` is what drop_motifs8 reported
# for the BASE pass, which is the pass those counts were validated
# against. Both are checked.
HUMAN_REFERENCED = {
    1: {"stated": 16, "detected8": 17},
    3: {"stated": 16, "detected8": 16},
    21: {"stated": 14, "detected8": 14},
    385: {"stated": 25, "detected8": 24},
}

# Each rung turns ONE thing on, cumulatively. Order matters and is the
# order Task 1 fixed them in.
RUNGS = (
    ("drop8", dict(dedup_units=False, fall_bracket=False, walk_back=False,
                   drops_only=False, floor="none")),
    ("+dedup_units", dict(dedup_units=True, fall_bracket=False,
                          walk_back=False, drops_only=False, floor="none")),
    ("+fall_bracket", dict(dedup_units=True, fall_bracket=True,
                           walk_back=False, drops_only=False, floor="none")),
    ("+walk_back", dict(dedup_units=True, fall_bracket=True, walk_back=True,
                        drops_only=False, floor="none")),
    ("+drops_only", dict(dedup_units=True, fall_bracket=True, walk_back=True,
                         drops_only=True, floor="none")),
    ("+global_floor", dict(dedup_units=True, fall_bracket=True,
                           walk_back=True, drops_only=True, floor="global")),
    ("+derived_floor", dict(dedup_units=True, fall_bracket=True,
                            walk_back=True, drops_only=True,
                            floor="derived")),
)

FIX_OF_RUNG = {
    "+dedup_units": "defect 1 - dedup tolerance was seconds vs samples",
    "+fall_bracket": "defects 3+4 - trough search and window now bound on "
                     "the next fall",
    "+walk_back": "defect 4 - onset walks back to the shoulder before the "
                  "gates read the depth",
    "+drops_only": "PARAMETERISATION, not a fix - the inverted pass is not "
                   "run on any corpus",
    "+global_floor": "NOT a fix - the 0.1 mV floor reaches the catalogue "
                     "for the first time; refine9 applied it to Fig2A only",
    "+derived_floor": "defect 6 - per-span 3-sigma floor replaces the "
                      "global 0.1 mV",
}


def _overrides(flags):
    """Detector params for one rung."""
    return {"bracket_on_fall_runs": bool(flags["fall_bracket"]),
            "walk_onset_back": bool(flags["walk_back"])}


def run_span_at(x, fs, flags, *, catalogue_id, recording_id, source_file,
                channel, span_offset, span_key):
    """One span at one rung. Returns `(rows, info, floor_mv)`."""
    over = _overrides(flags)
    rows, arrays, info = passes8.detect_multiscale(
        x, fs,
        catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=source_file, channel=channel, span_offset=span_offset,
        span_label=span_key, span_key=span_key,
        max_passes=3, fine=True, sensitive=True, micro=True,
        inverted=not flags["drops_only"],
        dedup_scale_by_fs=flags["dedup_units"],
        base_overrides=over, fine_overrides=over, sens_overrides=over,
        inv_overrides=over, micro_overrides=over)

    floor_mv = floor_for_rung(x, flags)
    kept = ([r for r in rows if abs(float(r["drop_depth_mv"])) > floor_mv]
            if floor_mv > 0 else list(rows))
    return kept, info, floor_mv


def floor_for_rung(x, flags):
    """The depth floor one rung applies. Zero means none at all."""
    rule = flags.get("floor", "none")
    if rule == "derived":
        return floor10.derived_floor_mv(x)
    if rule == "global":
        return floor10.GLOBAL_FLOOR_MV
    return 0.0


def up_runs_of(x, fs, pass_info=None):
    """The encoding's rise count, at the base scale and at the finest one.

    Returns `(base_up_runs, base_fall_runs, base_events, finest_up_runs)`.

    The base numbers are taken from the base pass's own counters, so they
    are the numbers the detector itself saw; `detect5` counts `up_runs`
    before any gate has run. `finest_up_runs` re-encodes at the SMALLEST
    `segment_seconds` any pass reported, which is the most permissive
    encoding the run actually used and therefore the honest ceiling for a
    multi-scale count. See the module docstring.
    """
    result = passes6.run_base(x, fs, max_passes=3).result
    base_up = int(result.counts.get("up_runs", 0))
    base_fall = int(result.counts.get("fall_runs", 0))
    finest_up = base_up

    segments = [float(result.params.segment_seconds)]
    for entry in (pass_info or {}).values():
        seconds = entry.get("segment_seconds") if isinstance(entry, dict) else None
        if seconds:
            segments.append(float(seconds))
    smallest = min(segments)
    if smallest < float(result.params.segment_seconds):
        params = replace(result.params, segment_seconds=smallest)
        try:
            letters, _ = detect5.stage_letters(x, fs, params)
            finest_up = len(detect5.up_runs(letters))
        except (ValueError, ZeroDivisionError):
            pass
    return base_up, base_fall, len(result.events), finest_up


def ladder_for_span(x, fs, *, catalogue_id, recording_id, source_file,
                    channel, span_offset, span_key):
    """Every rung's count for one span, plus the base-pass count at each.

    The base-pass count is carried separately because that is the number
    the four human references were validated against - a total that moves
    because `micro` found more small events is not the same event as a
    base-pass count moving.
    """
    out = []
    for name, flags in RUNGS:
        rows, info, floor_mv = run_span_at(
            x, fs, flags, catalogue_id=catalogue_id,
            recording_id=recording_id, source_file=source_file,
            channel=channel, span_offset=span_offset, span_key=span_key)
        out.append({
            "rung": name,
            "n_motifs": len(rows),
            "n_base": sum(1 for r in rows if r["pass_key"] == passes7.PASS_BASE),
            "n_before_dedup": info.get("n_before_dedup"),
            "n_duplicates_dropped": info.get("n_duplicates_dropped"),
            "base_pass_events": info["passes"].get("base", {}).get("n_events"),
            "depth_floor_mv": floor_mv,
            "per_pass_kept": {k: sum(1 for r in rows if r["pass_key"] == k)
                              for k in passes7.PASS_ORDER},
            "pass_detail": {k: {kk: vv for kk, vv in v.items()
                                if kk in ("n_events", "segment_seconds",
                                          "detrend_window_s", "slope_sigma",
                                          "divisor", "ran")}
                            for k, v in info["passes"].items()},
        })
    return out


def attribute(ladder, field="n_motifs"):
    """`[(rung, delta, named_fix), ...]` for every rung that moved a count."""
    moves = []
    for previous, current in zip(ladder, ladder[1:]):
        delta = int(current[field]) - int(previous[field])
        if delta:
            moves.append({"rung": current["rung"], "delta": delta,
                          "cause": FIX_OF_RUNG[current["rung"]]})
    return moves


def bracket_holds(up_runs, human, detected):
    """encoding >= eye >= gated detection, per drop_motifs7.

    Returns `(holds, rule, which_side_failed)`. The two inequalities fail
    for completely different reasons and lumping them into one boolean
    hides which:

      ENCODING SIDE, `up_runs >= detected`. A failure here means events
        were confirmed that the encoding never proposed, which cannot
        happen without something being wrong.

      EYE SIDE, `annotated >= detected`. A failure here means the detector
        found MORE than the human counted, which on a multi-scale run is
        expected rather than wrong: the catalogue's prose counts cycles of
        a span's dominant motif, and `fine`, `sens` and `micro` exist
        precisely to find the sub-scale events that count leaves out. It
        is the BASE pass that reproduces the human number, and Section 1
        is where that is checked.

    `human` may be None where the catalogue states no count; the bracket
    then collapses to the encoding side, which is still a real test.

    Both arguments must be measured at the SAME scale - see the module
    docstring. Pass the base up_runs with the base detections, or the
    finest up_runs with the multi-scale total; never one of each.
    """
    encoding_ok = bool(up_runs >= detected)
    if human is None:
        return encoding_ok, "up_runs >= detected", (
            None if encoding_ok else "encoding")
    eye_ok = bool(human >= detected)
    failed = None
    if not encoding_ok:
        failed = "encoding"
    elif not eye_ok:
        failed = "eye"
    return (encoding_ok and eye_ok, "up_runs >= annotated >= detected",
            failed)


def load_drop8_baseline(path):
    """drop_motifs8's per-span counts, keyed by catalogue id."""
    import json
    with open(path, encoding="utf-8") as handle:
        summaries = json.load(handle)
    out = {}
    for row in summaries:
        cid = row.get("catalogue_id")
        if cid == "ALL" or cid is None:
            continue
        out[int(cid)] = {
            "n_motifs": int(row["n_motifs"]),
            "base_pass_events": int(row["passes"]["base"]["n_events"]),
            "per_pass_kept": row.get("per_pass_kept", {}),
            "n_before_dedup": row.get("n_before_dedup"),
            "n_duplicates_dropped": row.get("n_duplicates_dropped"),
            "annotated_n": row.get("annotated_n"),
        }
    return out
