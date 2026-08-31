"""
run_drop5_report.py
====================
Run the five-stage detector over the sixteen spans, draw a contact sheet
per span, and write the handoff report.

Runs ALONGSIDE `run_drop_report.py`, not instead of it. That script keeps
its presets and keeps writing `Plots/drop_motifs/`; this one writes
`Plots/drop_motifs5/` and touches nothing the shipped figures depend on.
The two can be compared span by span because three of the spans are
common to both.

    python Pipelines/drop_motifs/run_drop5_report.py              # all 16
    python Pipelines/drop_motifs/run_drop5_report.py --spans 1 21 385
    python Pipelines/drop_motifs/run_drop5_report.py --no-figures  # numbers

What is drawn, and why it is drawn that way
-------------------------------------------
A CONTACT SHEET per span: every detected event in its own small panel,
not overlaid. Overlaying is what hid the defect in the first place - a
window holding three spikes looks like a busy family until you put it
beside its neighbours and see that all of them hold three. One panel per
event is the only view that answers "is one window one spike".

RAW millivolts on the y axis, at the operator's request, and absolute
seconds on the x. The detrended trace is drawn faintly underneath because
that is what the detector actually encoded, and a reader comparing the
panel to the detector's verdict should see the same signal the detector
saw. Detrending remains a preprocessing step for dSAX only; nothing in
the figure is time-normalised or amplitude-normalised.

The headline number is the fraction of windows scoring exactly 1 under
`window_purity`, which re-runs the detector's own slope gate inside each
stored window. It is graded with the detector's definition of a fall
rather than a fresh peak-finder, so the metric cannot disagree with the
detector about what an event is.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs.spans5 import SPANS5, load_span
from Working.Detection.drop_motifs import motifs5
from Working.Detection.drop_motifs.autoparams import CONFIDENCE_GATE, autotune
from Working.Detection.drop_motifs.detect5 import params_as_dict, window_purity

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_PLOT_DIR = os.path.join("Plots", "drop_motifs5")

# Panels per contact sheet before it is split across several files. Above
# this a panel is too small to judge, which would defeat the sheet's only
# purpose.
PANELS_PER_SHEET = 24

# Purity at or above which a span passes without qualification, and below
# which it is called a failure rather than a warning. Both are editorial
# and are stated on the report so a reader can move them.
PASS_PURITY = 0.90
FAIL_PURITY = 0.60


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def verdict_for(purity, n_events, annotated_n, confidence):
    """pass / suspect / fail, with the reason, so the operator's feedback
    is a correction to a stated claim rather than free-form grading."""
    reasons = []
    if n_events == 0:
        return "fail", "no events found"

    if annotated_n is not None:
        if n_events == annotated_n:
            reasons.append(f"count matches the annotated {annotated_n}")
        else:
            reasons.append(f"count {n_events} vs annotated {annotated_n}")

    if purity >= PASS_PURITY:
        level = "pass"
        reasons.insert(0, f"{purity:.0%} of windows hold exactly one fall")
    elif purity >= FAIL_PURITY:
        level = "suspect"
        reasons.insert(0, f"only {purity:.0%} of windows hold exactly one "
                          f"fall")
    else:
        level = "fail"
        reasons.insert(0, f"{purity:.0%} of windows hold exactly one fall")

    # A count that disagrees with a human cannot be a clean pass, whatever
    # the windows look like: the windows being individually clean says
    # nothing about whether the right set of events was found.
    if (annotated_n is not None and n_events != annotated_n
            and level == "pass"):
        level = "suspect"

    if confidence < CONFIDENCE_GATE:
        reasons.append(f"weak autocorrelation ({confidence:.2f}) - the "
                       f"scale came from refinement, not from the seed")
    return level, "; ".join(reasons)


def run_span(conn, catalogue_id, spec, max_passes):
    row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                       (spec["recording"],)).fetchone()
    if row is None:
        raise SystemExit(f"no recording {spec['recording']}")
    x, offset = load_span(row, spec["span"])
    fs = float(row["fs"])

    tuned = autotune(x, fs, max_passes=max_passes)
    purity = window_purity(x, fs, tuned.result) if tuned.result else []
    clean = (sum(1 for p in purity if p == 1) / len(purity)) if purity else 0.0

    level, why = verdict_for(clean, len(tuned.events),
                             spec["annotated_n"], tuned.confidence)

    histogram = {}
    for score in purity:
        histogram[str(score)] = histogram.get(str(score), 0) + 1

    # Why a span is impure, distinguished automatically, because "57% clean"
    # does not say which of two very different faults produced it.
    #
    # A window WIDER than the event spacing has failed to find a bracket
    # and fallen back on the `window_cap_mult` backstop, so it necessarily
    # contains a neighbour - the fix is on the boundary rule. A window
    # NARROWER than the spacing that still holds several falls means the
    # detector is splitting one event, and the fix is the segment length or
    # the dedup separation. The two are opposite corrections.
    widths = [e.window_end_idx - e.window_start_idx for e in tuned.events]
    median_window_s = float(np.median(widths) / fs) if widths else 0.0
    interval = tuned.period_s
    window_over_interval = (median_window_s / interval
                            if interval and np.isfinite(interval) and interval > 0
                            else float("nan"))

    diagnosis = None
    if clean < PASS_PURITY:
        if np.isfinite(window_over_interval) and window_over_interval > 1.0:
            diagnosis = (
                f"windows are {window_over_interval:.1f}x the measured event "
                f"spacing, so they must contain neighbours: the UP-run "
                f"bracket found no boundary and fell back on the "
                f"`window_cap_mult` backstop. Look at the boundary rule, "
                f"not the segment length.")
        else:
            diagnosis = (
                f"windows are only {window_over_interval:.2f}x the event "
                f"spacing yet several hold more than one fall, so the "
                f"detector is splitting single events rather than "
                f"over-framing them. Look at `segment_seconds` or the "
                f"dedup separation.")

    rows, arrays = motifs5.rows_and_arrays(
        tuned.result, x, purity,
        catalogue_id=catalogue_id, recording_id=spec["recording"], fs=fs,
        source_file=os.path.basename(row["npy_path"]),
        channel=int(row["channel"]), span_offset=offset,
        span_label=f"ID {catalogue_id}", span_key=f"id{catalogue_id:03d}")

    return dict(
        motif_rows=rows,
        motif_arrays=arrays,
        catalogue_id=catalogue_id,
        annotation_id=spec["annotation"],
        recording_id=spec["recording"],
        span_hours=spec["span"],
        span_offset=offset,
        n_samples=len(x),
        fs=fs,
        note=spec["note"],
        annotated_n=spec["annotated_n"],
        expected_morphology=spec["expect"],
        morphology=tuned.morphology,
        n_events=len(tuned.events),
        purity_histogram=histogram,
        purity_clean_fraction=clean,
        median_window_s=median_window_s,
        window_over_interval=window_over_interval,
        diagnosis=diagnosis,
        acf_period_s=tuned.seed_period_s,
        acf_confidence=tuned.confidence,
        acf_width_s=tuned.seed_width_s,
        refined_width_s=tuned.feature_width_s,
        refined_interval_s=tuned.period_s,
        converged=tuned.converged,
        trace=tuned.trace,
        params=params_as_dict(tuned.params) if tuned.params else {},
        counts=dict(tuned.result.counts) if tuned.result else {},
        diagnostics=dict(tuned.result.diagnostics) if tuned.result else {},
        verdict=level,
        verdict_reason=why,
        events=[dict(onset_idx=e.onset_idx, trough_idx=e.trough_idx,
                     window_start_idx=e.window_start_idx,
                     window_end_idx=e.window_end_idx,
                     trigger=e.trigger,
                     drop_depth_mv=e.drop_depth_mv,
                     fall_duration_s=e.fall_duration_s,
                     fall_dominance=e.fall_dominance)
                for e in tuned.events],
    ), x, tuned, purity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spans", nargs="*", type=int, default=None,
                        help="catalogue IDs; default all sixteen")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--plot-dir", default=DEFAULT_PLOT_DIR)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--no-figures", action="store_true",
                        help="numbers and report only")
    args = parser.parse_args(argv)

    wanted = args.spans or sorted(SPANS5)
    unknown = [s for s in wanted if s not in SPANS5]
    if unknown:
        raise SystemExit(f"unknown catalogue IDs: {unknown}")

    out_dir = _Path(args.plot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(args.db)

    summaries = []
    store_rows, store_arrays, span_data = [], {}, {}
    for catalogue_id in wanted:
        spec = SPANS5[catalogue_id]
        print(f"[{catalogue_id:>3}] {spec['note'][:58]}", flush=True)
        summary, x, tuned, purity = run_span(conn, catalogue_id, spec,
                                             args.max_passes)
        print(f"      {summary['verdict'].upper():8s} "
              f"n={summary['n_events']:<4d} "
              f"purity={summary['purity_clean_fraction']:.2f} "
              f"morph={summary['morphology']}", flush=True)

        store_rows.extend(summary.pop("motif_rows"))
        store_arrays.update(summary.pop("motif_arrays"))
        span_data[catalogue_id] = (x, tuned, summary)

        if not args.no_figures:
            # Imported here, not at module scope: this is a Pipelines
            # script so matplotlib is allowed, but --no-figures should not
            # need it and neither should importing this module to reuse
            # `run_span`.
            from Pipelines.drop_motifs.figures5 import draw_contact_sheets
            summary["figures"] = draw_contact_sheets(
                x, tuned, purity, summary, out_dir,
                panels_per_sheet=PANELS_PER_SHEET)
        summaries.append(summary)

    # The motif library, written before the figures that read it, so a
    # figure can never draw from a store that was not persisted.
    store_dir = out_dir / "motifs"
    motifs5.write_store(str(store_dir), store_rows, store_arrays,
                        manifest_extra={"detector": "detect5",
                                        "spans_run": list(wanted)})
    print(f"\nmotif library -> {store_dir}  "
          f"({len(store_rows)} motifs, "
          f"{sum(r['is_pure'] for r in store_rows)} pure)")

    if not args.no_figures:
        from Pipelines.drop_motifs.figuresets5 import draw_all
        index = draw_all(store_dir, out_dir, span_data, summaries, wanted)
        for summary in summaries:
            entry = index.get(str(summary["catalogue_id"]))
            if entry:
                summary["figure_set"] = entry
        pooled = index.get("ALL")
        if pooled:
            summaries.append({"catalogue_id": "ALL", "pooled": pooled})

    (out_dir / "autoderive_summary.json").write_text(
        json.dumps(summaries, indent=2, default=float), encoding="utf-8")

    from Pipelines.drop_motifs.report5 import write_report
    report_path = write_report(summaries, out_dir)
    print(f"\nreport  -> {report_path}")
    print(f"figures -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
