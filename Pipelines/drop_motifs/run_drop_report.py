"""
run_drop_report.py
===================
CLI for spike-drop motif discovery: detect, store, cluster, plot.

Two phases that can be run together or apart, which is the whole point of
the store existing (work order 4.3):

    --detect      read a channel, find drops, write the store. Slow-ish,
                  touches DATA/derived/channels/.
    --replot-from replay a store into figures. Touches no recording and no
                  database at all.

Running with neither does both, which is the usual case.

Examples
--------
    # both recordings at their tuned defaults, store + every figure
    python Pipelines/drop_motifs/run_drop_report.py --export-all

    # detection only, into a scratch store
    python Pipelines/drop_motifs/run_drop_report.py --detect \\
        --out-root DATA/derived/drop_motifs_test

    # re-cut the tree at 6 clusters, no detection, no channel access
    python Pipelines/drop_motifs/run_drop_report.py \\
        --replot-from DATA/derived/drop_motifs/385 \\
        --replot-from DATA/derived/drop_motifs/1 --n-clusters 6

Per-SPAN defaults
-----------------
Presets are keyed by SPAN, not by recording. Three of the shipped spans
sit on M2_aug CH00 alone and want detrend windows a factor of fifteen
apart - a 16-cycle AM sharkfin sequence at 336-346 h, a gentle 14-sharkfin
run at 314.5-316.5 h, and a 100-tooth furrycaterpillar sawtooth at
485.9-488.5 h whose drops are 0.3 mV. Forcing them to share a parameter
set would mean choosing one of their time scales for all three.

`SPAN_PRESETS` holds what each was tuned to and why; `--segment-seconds`
and friends override for a one-off. Every value used lands in that span's
manifest, so a figure can always be traced back to what produced it.

Figures are written twice: once per span, and once over the pooled event
set. The pooled figures carry the cross-dataset claim; the per-span ones
answer "what does THIS recording do", which the pooled dendrogram cannot
show because a 0.3 mV caterpillar and a 90 mV trough spike land at
opposite ends of it.
"""

import argparse
import json
import os
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg
from Working.Detection.drop_motifs import store as ds
from Working.Detection.drop_motifs.detect import (
    NOISE_ESTIMATORS,
    DetectionParams,
    detect_drops,
)
from Working.database.schema import init_db

DEFAULT_OUT_ROOT = os.path.join("DATA", "derived", "drop_motifs")
DEFAULT_PLOT_DIR = os.path.join("Plots", "drop_motifs")

# The cut the shipped figures use, so that running this script with no
# arguments reproduces what is in `Plots/drop_motifs/` rather than
# something adjacent to it.
#
# `cluster.suggest_n_clusters`'s largest-merge-gap heuristic returns 2 on
# the current 42-event set, which is the honest unsupervised answer -
# "fast shallow drops" and "slow deep drops" - but it is one level too
# coarse to be a useful figure: the whole cross-dataset claim lives in
# whether a cluster MIXES the two recordings, and at k=2 both clusters
# mix, so the claim is unfalsifiable by the picture. At k=5 the tree has
# resolved three pure clusters and two mixed ones, which is a statement
# with content. Pass `--n-clusters 0` for the heuristic.
#
# This IS an editorial choice and is flagged as one: the final cut for
# the paper is a human call, and nothing downstream depends on this value
# beyond which figures get drawn.
DEFAULT_N_CLUSTERS = 5


# -- the two recordings, and what each was tuned to ------------------------
#
# Every number here was chosen by sweeping against something checkable and
# the check is named, because a preset with no provenance is a magic
# number. The measured figures each comment quotes are the sweep results;
# there is no `--sweep` flag, the sweeps were run by hand.

SPAN_PRESETS = {
    # ── Mushroom_260720, the whole 4-hour recording ──────────────────────
    "mushroom_icicles": dict(
        recording_id=385, span=None, annotation_id=None,
        label="Mushroom icicles",
        dataset="Mushroom_260720",
        why="Sharp downward pulses on a flat baseline, ~50-100 s end to "
            "end. The only non-M2 recording here.",
        params=dict(
            # 3 minutes: long enough not to eat a ~50-100 s icicle, short
            # enough to flatten the slow wander around 2.4-2.6 h.
            detrend_window_s=180.0,
            # 2 s. The rise before a Mushroom drop is ONE to TWO SAMPLES -
            # a +0.6 mV overshoot before a 12 mV fall. At 3 s and above it
            # averages into the quiescent bin and the event stops being
            # detectable by a rise-then-drop rule: recall against
            # hand-marked icicles falls from 0.96 to 0.80.
            segment_seconds=2.0,
            same_fraction=0.5,
            merge_gap_segments=1,
            # 120 s: the shortest true inter-icicle interval measured is
            # 149 s, so this separates real events and collapses the
            # several UP regions one icicle generates.
            min_separation_s=120.0,
        ),
    ),

    # ── M2_aug CH00, three different spans on ONE recording ──────────────
    # This is why the presets are keyed by span and not by recording: the
    # three below sit on the same channel and want detrend windows a
    # factor of fifteen apart.
    "m2aug_ch00_am16": dict(
        recording_id=1, span=(336.0, 346.0), annotation_id=11266,
        label="M2_aug CH00 AM sharkfin x16",
        dataset="M2_aug CH00",
        why="Annotation 11266: 'amplitude modulation am increasing; "
            "frequency modulation fm decreasing; 16 cycles; 20-70 mV'. The "
            "reference span - the detector returns 16 from 16 here, which "
            "is the one external check available.",
        params=dict(
            # 30 min. Under ~15 min the detrend removes the spike with the
            # drift: at 60 s the residual retains 7 mV of a 63 mV
            # excursion; at 1800 s it retains 40 mV.
            detrend_window_s=1800.0,
            segment_seconds=120.0,
            same_fraction=0.7,
            merge_gap_segments=0,
            # Dedup off: the rise-to-drop mapping is already 1:1 and the
            # closest true spacing is 917 s.
            min_separation_s=0.0,
        ),
    ),
    "m2aug_ch00_sharkfin14": dict(
        recording_id=1, span=(314.53, 316.50), annotation_id=11280,
        label="M2_aug CH00 sharkfin x14",
        dataset="M2_aug CH00",
        why="Annotation 11280: '14x sharkfin sequence'. Small (18 mV) and "
            "gentle - this is the span that exposed the noise-estimator "
            "bug, because its 14 events fill the whole 1.97 h and the "
            "gradient-MAD noise floor ended up steeper than any sample in "
            "it. Returns 13 of the annotated 14.",
        params=dict(
            detrend_window_s=1013.0,
            segment_seconds=20.0,
            same_fraction=0.7,
            merge_gap_segments=0,
            min_separation_s=200.0,
        ),
    ),
    "m2aug_ch00_furrycaterpillar": dict(
        recording_id=1, span=(485.95, 488.52), annotation_id=11271,
        label="M2_aug CH00 furrycaterpillar x100",
        dataset="M2_aug CH00",
        why="Annotation 11271 / catalogue ID 6: 'Regular sequence of 100 "
            "furrycaterpillars; 30 mV rollinghills'. A sawtooth train - "
            "~90 s rise then a ~0.3 mV drop - riding on a slow rolling "
            "hill. Thirty times smaller than any other span here, which is "
            "exactly why it is included.",
        params=dict(
            # 2 min, about 1.3 caterpillar periods: long enough to keep the
            # tooth, short enough to remove the rolling hill under it.
            detrend_window_s=120.0,
            segment_seconds=20.0,
            same_fraction=0.5,
            merge_gap_segments=0,
            # 4 rather than the default 8. NOT a fudge: the drops here are
            # -0.10 to -0.125 mV/s against a noise sigma of 0.016, i.e.
            # genuinely only 6-8 sigma above the sample-level noise. A
            # 0.3 mV event on this electrode is close to the floor, and the
            # honest options are a looser threshold or no detections at
            # all. Recall against the annotated 100 is ~69%, and the
            # measured median inter-onset interval (102 s) matches the
            # annotation's implied period (92 s), so what is found is the
            # right rhythm rather than noise.
            slope_sigma=4.0,
            # 0.02 rather than 0.10: one ~3 mV excursion in this span would
            # otherwise set a 10% floor above the caterpillars themselves.
            min_depth_frac=0.02,
            min_separation_s=40.0,
        ),
    ),

    # ── M2_aug CH01 and CH03: long spike trains on other channels ────────
    "m2aug_ch01_growing": dict(
        recording_id=2, span=(400.0, 460.0), annotation_id=11283,
        label="M2_aug CH01 growing sequence",
        dataset="M2_aug CH01",
        why="Annotation 11283: 'long sequence starting at small scale, then "
            "larger'. 60 hours, ~38 sharkfins with amplitude growing "
            "through the span - the same AM story as am16 over six times "
            "the duration.",
        params=dict(
            detrend_window_s=3600.0,
            segment_seconds=120.0,
            same_fraction=0.7,
            merge_gap_segments=0,
            min_separation_s=600.0,
        ),
    ),
    "m2aug_ch03_troughtrain": dict(
        recording_id=4, span=(405.0, 450.0), annotation_id=11295,
        label="M2_aug CH03 trough spike train",
        dataset="M2_aug CH03",
        why="Annotation 11295: 'spike train of trough spikes'. 45 hours of "
            "flat-bottomed downward pulses - Mushroom's icicle morphology "
            "at a hundred times the duration and ten times the amplitude, "
            "which makes it the natural cross-scale partner for "
            "mushroom_icicles.",
        params=dict(
            detrend_window_s=7200.0,
            segment_seconds=60.0,
            same_fraction=0.7,
            merge_gap_segments=0,
            min_separation_s=600.0,
        ),
    ),
}

# Spans run when `--spans` is not given. Every one of them, in an order
# that puts the two originally-validated spans first so a regression in
# either shows up at the top of the run log.
DEFAULT_SPANS = (
    "mushroom_icicles",
    "m2aug_ch00_am16",
    "m2aug_ch00_sharkfin14",
    "m2aug_ch00_furrycaterpillar",
    "m2aug_ch01_growing",
    "m2aug_ch03_troughtrain",
)


# -- data access -----------------------------------------------------------

def load_span(recording, span_hours=None):
    """The samples to run on, plus where they start in the channel.

    `mmap_mode="r"` then an explicit copy of the slice: the M2_aug channel
    is 2.6M samples and only 36k of them are wanted, so reading the whole
    thing into memory to throw 99% away is avoidable.
    """
    x = np.load(recording["npy_path"], mmap_mode="r")
    fs = float(recording["fs"])
    if span_hours is None:
        return np.asarray(x, dtype=float), 0
    start = int(round(span_hours[0] * 3600.0 * fs))
    end = min(int(round(span_hours[1] * 3600.0 * fs)), len(x))
    if start >= end:
        raise SystemExit(
            f"span {span_hours} is empty in a {len(x)}-sample recording")
    return np.asarray(x[start:end], dtype=float), start


def get_recording(conn, recording_id):
    row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                       (recording_id,)).fetchone()
    if row is None:
        raise SystemExit(f"No recording with id={recording_id}.")
    return row


def annotation_span(conn, annotation_id, fs):
    """The stored annotation, in hours, so the crop is traceable to a
    human verdict rather than to a number typed into a script."""
    row = conn.execute(
        "SELECT start_idx, end_idx, note FROM annotations WHERE id = ?",
        (annotation_id,)).fetchone()
    if row is None:
        return None
    return (row["start_idx"] / fs / 3600.0, row["end_idx"] / fs / 3600.0,
            row["note"])


# -- detection -------------------------------------------------------------

def run_detection(conn, span_key, args):
    preset = SPAN_PRESETS.get(span_key)
    if preset is None:
        raise SystemExit(
            f"No preset for span {span_key!r}. Known spans: "
            f"{', '.join(sorted(SPAN_PRESETS))}. Add one to SPAN_PRESETS "
            "with its reasoning rather than passing bare flags - an "
            "undocumented parameter set is not reproducible.")

    recording_id = preset["recording_id"]
    recording = get_recording(conn, recording_id)
    fs = float(recording["fs"])

    span = preset["span"]
    note = None
    if preset.get("annotation_id") is not None:
        stored = annotation_span(conn, preset["annotation_id"], fs)
        if stored is not None:
            span = (stored[0], stored[1])
            note = stored[2]
            print(f"  span from annotation {preset['annotation_id']}: "
                  f"{span[0]:.2f}-{span[1]:.2f} h  ({note})")
        else:
            print(f"  WARNING: annotation {preset['annotation_id']} not found; "
                  f"falling back to the hardcoded span {preset['span']}")

    values = dict(preset["params"])
    for key in ("detrend_window_s", "segment_seconds", "same_fraction",
                "merge_gap_segments", "slope_sigma", "min_depth_frac",
                "min_separation_s", "lookahead_mult", "trough_knee_frac",
                "pre_context_mult", "post_context_mult", "noise_estimator"):
        override = getattr(args, key, None)
        if override is not None:
            values[key] = override
            print(f"  override: {key} = {override}")
    values["random_seed"] = args.seed
    params = DetectionParams(**values)

    x, offset = load_span(recording, span)
    print(f"  {recording['source_file']} CH{recording['channel']:02d}: "
          f"{len(x)} samples from index {offset} ({len(x) / fs / 3600.0:.2f} h)")

    result = detect_drops(x, fs, params)
    counts = result.counts

    print(f"  segments={counts['segments']}  UP regions={counts['up_regions']}"
          f"  candidates={counts['candidates']}")
    print(f"  rejected: no qualifying slope={counts['rejected_no_slope']}, "
          f"too shallow={counts['rejected_shallow']}, "
          f"duplicate={counts['rejected_duplicate']}")
    print(f"  SAME observed={result.diagnostics.get('same_fraction_observed', 0):.3f} "
          f"(requested {params.same_fraction})  "
          f"slope threshold={result.diagnostics.get('slope_threshold_mv_per_s', 0):.4f} mV/s")

    if result.empty:
        # Loud, not a shrug: an empty result is a finding about the data or
        # the parameters, and it must not be mistakable for "not yet run".
        print("  *** ZERO DROPS FOUND. The store is still written, with "
              "empty=true in the manifest, so this is distinguishable from "
              "a run that never happened. ***")
    else:
        print(f"  {len(result.events)} drop(s) confirmed")

    # Keyed by SPAN, not by recording: three of these spans live on
    # recording 1, and a recording-keyed directory would have them
    # overwrite each other.
    out_dir = os.path.join(args.out_root, span_key)
    paths = ds.write_run(
        out_dir, result, x, fs=fs, recording_id=recording_id,
        source_file=recording["source_file"], channel=recording["channel"],
        span_start_idx=offset,
        span_key=span_key, span_label=preset["label"],
        extra={"preset_label": preset["label"],
               "dataset": preset["dataset"],
               "why": preset.get("why"),
               "annotation_id": preset.get("annotation_id"),
               "annotation_note": note,
               "span_hours": list(span) if span else None},
    )
    print(f"  -> {paths['events']}")
    print(f"  -> {paths['snippets']}")
    print(f"  -> {paths['manifest']}")
    return out_dir


# -- clustering ------------------------------------------------------------

def run_clustering(out_dirs, args, scope="pooled"):
    pooled = ds.load_runs(out_dirs)
    events = pooled["events"]
    if len(events) < 2:
        print(f"\nOnly {len(events)} event(s) pooled - nothing to cluster. "
              "Reported as blocked rather than clustered into one group.")
        return None

    print(f"\nClustering {len(events)} pooled event(s) from "
          f"{len(out_dirs)} recording(s)")
    # 0 means "use the heuristic"; --cut-height overrides either.
    n_clusters = None if (args.cut_height is not None or not args.n_clusters) \
        else args.n_clusters
    result = dc.cluster_events(
        events, pooled["snippets"],
        n_clusters=n_clusters, height=args.cut_height,
        n_samples=args.resample_length, method=args.linkage,
        max_roughness=args.max_roughness,
    )
    print(f"  method={result['method']}  resample={result['resample_length']}  "
          f"cophenetic r={result['cophenetic_r']:.3f}"
          + ("  <- LOW: the tree is describing the linkage more than the data"
             if result["cophenetic_r"] < 0.7 else ""))
    print(f"  {result['n_clusters']} cluster(s)")

    for row in result["composition"]:
        kind = "PURE" if row["pure"] else "MIXED"
        parts = ", ".join(f"{k}: {v}" for k, v in row["composition"].items())
        print(f"    cluster {row['cluster_id']}: n={row['n']:3d}  {kind:5s}  "
              f"[{parts}]  depth {row['median_depth_mv']:.1f} mV  "
              f"fall {row['median_fall_s']:.0f} s")

    rough = result["roughness"]
    print(f"  roughness QC (max {rough['max_ratio']:g}x the cluster mean): "
          f"{rough['excluded_fraction'] * 100:.1f}% flagged as noisy")

    # Write labels back into each recording's own table. Events absent
    # from the mapping keep whatever they had, so a pooled clustering can
    # be written into several stores without disturbing any of them.
    mapping = {e["event_id"]: int(lab)
               for e, lab in zip(events, result["labels"])}
    for out_dir in out_dirs:
        n = ds.assign_clusters(out_dir, mapping)
        print(f"  cluster_id written for {n} row(s) in {out_dir}")

    scope_dir = os.path.join(args.plot_dir, scope)
    summary_path = os.path.join(scope_dir, "cluster_summary.json")
    os.makedirs(scope_dir, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump({
            "n_events": len(events),
            "n_clusters": result["n_clusters"],
            "method": result["method"],
            "linkage_metric": "euclidean on resampled z-normalised vectors",
            "resample_length": result["resample_length"],
            "cophenetic_r": result["cophenetic_r"],
            "composition": result["composition"],
            "roughness": {k: v for k, v in rough.items()
                          if k not in ("ratios", "keep")},
            "stores": list(out_dirs),
        }, fh, indent=2)
    print(f"  -> {summary_path}")
    return result


# -- CLI -------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="Spike-drop motif discovery, storage and figures.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    phase = p.add_argument_group("phases (default: run all three)")
    phase.add_argument("--detect", action="store_true",
                       help="run detection and write the store")
    phase.add_argument("--replot-from", action="append", default=None,
                       metavar="DIR",
                       help="skip detection entirely and read this store "
                            "instead; repeatable, one per recording. Needs no "
                            "recording and no database.")
    phase.add_argument("--no-figures", action="store_true",
                       help="detect and cluster but draw nothing")

    which = p.add_argument_group("what to run on")
    which.add_argument("--spans", default=None,
                       help="comma-separated SPAN_PRESETS keys, or 'all'. "
                            "Default: every span. Keys are spans, not "
                            "recordings, because three of them share one "
                            "channel at very different time scales.")
    which.add_argument("--list-spans", action="store_true",
                       help="print the available spans and what each is, "
                            "then exit")
    which.add_argument("--db", default=None)

    # Every one of these defaults to None so that "not passed" is
    # distinguishable from "passed the same value the preset holds" - only
    # a genuine override is applied, and it is echoed when it is.
    det = p.add_argument_group("detection overrides (default: the preset's)")
    det.add_argument("--detrend-window-s", type=float, default=None)
    det.add_argument("--segment-seconds", type=float, default=None)
    det.add_argument("--same-fraction", type=float, default=None)
    det.add_argument("--merge-gap-segments", type=int, default=None)
    det.add_argument("--slope-sigma", type=float, default=None)
    det.add_argument("--min-depth-frac", type=float, default=None)
    det.add_argument("--min-separation-s", type=float, default=None)
    det.add_argument("--lookahead-mult", type=float, default=None)
    det.add_argument("--trough-knee-frac", type=float, default=None,
                     help="the fall ends once the signal has climbed back "
                          "this fraction of the depth reached")
    det.add_argument("--pre-context-mult", type=float, default=None)
    det.add_argument("--post-context-mult", type=float, default=None)
    det.add_argument("--noise-estimator", default=None,
                     choices=list(NOISE_ESTIMATORS),
                     help="how the slope threshold's noise floor is measured. "
                          "The default measures noise; 'gradient' measures "
                          "the typical slope and collapses on dense spike "
                          "trains - see Working/.../detect.slope_noise_sigma")
    det.add_argument("--seed", type=int, default=20260819,
                     help="recorded in the manifest; quantile-mode dSAX "
                          "consumes no RNG, the clustering step may")

    clu = p.add_argument_group("clustering")
    clu.add_argument("--n-clusters", type=int, default=DEFAULT_N_CLUSTERS,
                     help="fixed cut. The default is the cut the shipped "
                          "figures use, so the plain command reproduces them; "
                          "pass 0 for the largest-merge-gap heuristic instead, "
                          "which returns 2 on the current event set")
    clu.add_argument("--cut-height", type=float, default=None,
                     help="cut by linkage distance instead")
    clu.add_argument("--linkage", default=dc.DEFAULT_LINKAGE,
                     choices=["ward", "average", "complete", "single"])
    clu.add_argument("--resample-length", type=int,
                     default=dc.DEFAULT_RESAMPLE_LENGTH)
    clu.add_argument("--max-roughness", type=float,
                     default=dc.DEFAULT_MAX_ROUGHNESS,
                     help="flag members more than this many times as jagged "
                          "as their cluster's mean shape")

    rose = p.add_argument_group("gradient rose")
    rose.add_argument("--gradient-field", default="max_slope_mv_s",
                      choices=list(dg.GRADIENT_FIELDS),
                      help="which gradient the rose's angle encodes. "
                           "`max_slope_mv_s` is the steepest sample of the "
                           "fall and is the default; `onset_slope_mv_s` is a "
                           "central difference at the declared onset and "
                           "understates steepness badly on short falls")
    rose.add_argument("--slope-ref", type=float,
                      default=dg.DEFAULT_SLOPE_REF_MV_S,
                      help="reference slope in mV/s for the absolute rose: "
                           "the slope drawn at 45 degrees. arctan needs a "
                           "dimensionless argument, so this is not optional "
                           "and is printed on the figure")
    rose.add_argument("--rose-bins", type=int, default=18,
                      help="angular bins across the 90-degree falling "
                           "quadrant (18 = 5 degrees each)")

    fig = p.add_argument_group("figures")
    fig.add_argument("--export-all", action="store_true",
                     help="write every figure, including one overlay per cluster")
    fig.add_argument("--dendrogram-style", default="auto",
                     choices=["auto", "thumbnails", "panels"],
                     help="'thumbnails' embeds every leaf's waveform on the "
                          "tree; 'panels' is the safer side-by-side fallback; "
                          "'auto' picks by leaf count")
    fig.add_argument("--formats", default="png,pdf")
    fig.add_argument("--dpi", type=int, default=200)
    fig.add_argument("--linewidth", type=float, default=1.0)
    fig.add_argument("--font-scale", type=float, default=1.0)
    fig.add_argument("--plot-dir", default=DEFAULT_PLOT_DIR)
    fig.add_argument("--no-per-span", action="store_true",
                     help="draw only the pooled figures, skipping the "
                          "per-span dendrogram/rose/overlays")
    fig.add_argument("--no-pooled", action="store_true",
                     help="draw only the per-span figures, skipping the "
                          "pooled cross-dataset ones")

    p.add_argument("--out-root", default=DEFAULT_OUT_ROOT,
                   help="store root; one subdirectory per recordings.id")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_spans:
        print(f"{'span key':32s} {'rec':>4s} {'dataset':16s} label")
        for key in DEFAULT_SPANS:
            preset = SPAN_PRESETS[key]
            print(f"{key:32s} {preset['recording_id']:>4d} "
                  f"{preset['dataset']:16s} {preset['label']}")
            print(f"{'':32s}      {preset['why']}")
        return 0

    run_detect = args.detect or args.replot_from is None
    if args.replot_from:
        out_dirs = list(args.replot_from)
        run_detect = args.detect
    else:
        out_dirs = []

    if run_detect:
        if args.spans in (None, "all"):
            span_keys = list(DEFAULT_SPANS)
        else:
            span_keys = [v.strip() for v in args.spans.split(",") if v.strip()]
        conn = init_db(args.db)
        try:
            for span_key in span_keys:
                preset = SPAN_PRESETS.get(span_key, {})
                print(f"\n=== detect: {span_key} "
                      f"({preset.get('label', '?')}) ===")
                out_dir = run_detection(conn, span_key, args)
                if out_dir not in out_dirs:
                    out_dirs.append(out_dir)
        finally:
            conn.close()

    if not out_dirs:
        raise SystemExit("Nothing to do: pass --detect or --replot-from.")

    from Pipelines.drop_motifs import figures

    # -- per-span figures ------------------------------------------------
    # Each span clustered on its OWN, so its dendrogram and rose describe
    # that recording rather than its position within the pooled set. This
    # is what makes a per-span dendrogram readable at all: pooled, a
    # 0.3 mV caterpillar and a 90 mV trough spike sit at opposite ends of
    # the tree and neither span's internal structure is visible.
    if not args.no_per_span:
        for out_dir in out_dirs:
            manifest = ds.load_manifest(out_dir)
            key = manifest.get("span_key") or os.path.basename(out_dir)
            print(f"\n=== figures: {key} (own clustering) ===")
            clustering = run_clustering([out_dir], args, scope=key)
            if clustering is None:
                continue
            figures.write_all(clustering, [out_dir], args,
                              out_dir=os.path.join(args.plot_dir, key),
                              scope=key, pooled=False)

    # -- pooled figures --------------------------------------------------
    if not args.no_pooled and len(out_dirs) > 1:
        print(f"\n=== figures: pooled across {len(out_dirs)} span(s) ===")
        clustering = run_clustering(out_dirs, args, scope="pooled")
        if clustering is not None:
            figures.write_all(clustering, out_dirs, args,
                              out_dir=os.path.join(args.plot_dir, "pooled"),
                              scope="pooled", pooled=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
