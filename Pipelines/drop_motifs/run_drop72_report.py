"""
run_drop72_report.py
=====================
The drop_motifs6 run: multi-scale detection over the sixteen spans, the
corrected figure set, and a handoff report.

    python Pipelines/drop_motifs/run_drop72_report.py
    python Pipelines/drop_motifs/run_drop72_report.py --spans 26 385
    python Pipelines/drop_motifs/run_drop72_report.py --no-figures

drop_motifs7.2 is a FIGURE-ONLY revision of drop_motifs7: the detection
passes are identical and the motif library it writes is the same set. The
only change is how a motif is drawn - its height-to-width ratio is now
measured from the span panel rather than set to a fixed target, and the
dendrogram is an A4 page with the family overlays sitting on the tree at
the cut. Writes `Plots/drop_motifs7.2/` and touches nothing earlier, so the two are comparable span by span
and the earlier figures stay available as the thing being corrected.

What is different from the five run
-----------------------------------
DETECTION is multi-scale. Four passes per span - the derived scale, a
finer one, a relaxed slope gate, and the signal inverted - merged with the
base pass winning any collision. See `passes6`. The base pass is
unchanged, so every count the drop_motifs5 report validated against a
human still reproduces exactly: ID 1 still finds 17, ID 3 sixteen, ID 21
fourteen, ID 385 twenty-four.

FIGURES carry four corrections, all from the operator's review of the
drop_motifs5 set: traces aligned on the flat run before the drop rather
than on one sample; one common window length per set; scale bands and
direction never mixed on one axis; outliers drawn but not allowed to set
the y scale. See `overlays6` and `clusterfigs6`.

THE LIBRARY is keyed by pass as well as by span, recording and onset, so
this run's motifs cannot collide with the five run's and re-running a
pass is idempotent rather than duplicating. See `passes7.motif_key`.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import passes7
from Pipelines.drop_motifs.spans5 import SPANS5, load_span
from Working.Detection.drop_motifs import motifs5

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_PLOT_DIR = os.path.join("Plots", "drop_motifs7.2")

STORE_KIND = "drop_motifs7.2"


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def run_span(conn, catalogue_id, spec, args):
    row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                       (spec["recording"],)).fetchone()
    if row is None:
        raise SystemExit(f"no recording {spec['recording']}")
    x, offset = load_span(row, spec["span"])
    fs = float(row["fs"])

    rows, arrays, info = passes7.detect_multiscale(
        x, fs,
        catalogue_id=catalogue_id, recording_id=spec["recording"],
        source_file=os.path.basename(row["npy_path"]),
        channel=int(row["channel"]), span_offset=offset,
        span_label=f"ID {catalogue_id}", span_key=f"id{catalogue_id:03d}",
        max_passes=args.max_passes,
        fine=not args.no_fine, sensitive=not args.no_sensitive,
        inverted=not args.no_inverted, micro=not args.no_micro)

    pure = sum(int(r["is_pure"]) for r in rows)
    base = info["passes"].get(passes7.PASS_BASE, {})

    summary = dict(
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
        morphology=base.get("morphology"),
        n_motifs=len(rows),
        n_pure=int(pure),
        n_impure=len(rows) - int(pure),
        purity_clean_fraction=(pure / len(rows)) if rows else 0.0,
        passes=info["passes"],
        per_pass_kept=info["per_pass_kept"],
        n_before_dedup=info["n_before_dedup"],
        n_duplicates_dropped=info["n_duplicates_dropped"],
        scale_band_labels=info["scale_band_labels"],
        n_scale_bands=info["n_scale_bands"],
    )
    return summary, rows, arrays, x


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spans", nargs="*", type=int, default=None)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--plot-dir", default=DEFAULT_PLOT_DIR)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-fine", action="store_true")
    parser.add_argument("--no-sensitive", action="store_true")
    parser.add_argument("--no-inverted", action="store_true")
    parser.add_argument("--no-micro", action="store_true")
    args = parser.parse_args(argv)

    wanted = args.spans or sorted(SPANS5)
    unknown = [s for s in wanted if s not in SPANS5]
    if unknown:
        raise SystemExit(f"unknown catalogue IDs: {unknown}")

    out_dir = _Path(args.plot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(args.db)

    summaries, store_rows, store_arrays, span_signal = [], [], {}, {}
    for catalogue_id in wanted:
        spec = SPANS5[catalogue_id]
        print(f"[{catalogue_id:>3}] {spec['note'][:56]}", flush=True)
        summary, rows, arrays, x = run_span(conn, catalogue_id, spec, args)

        kept = summary["per_pass_kept"]
        print(f"      n={summary['n_motifs']:<4d} pure={summary['n_pure']:<4d} "
              f"base={kept.get('base', 0):<3d} fine={kept.get('fine', 0):<3d} "
              f"sens={kept.get('sens', 0):<3d} micro={kept.get('micro', 0):<4d} "
              f"inv={kept.get('inv', 0):<3d}  "
              f"bands={summary['scale_band_labels']}", flush=True)

        store_rows.extend(rows)
        store_arrays.update(arrays)
        span_signal[catalogue_id] = x
        summaries.append(summary)

    store_dir = out_dir / "motifs"
    motifs5.write_store(str(store_dir), store_rows, store_arrays,
                        manifest_extra={
                            "kind": STORE_KIND,
                            "detector": "detect5 + passes7 multi-scale + micro",
                            "spans_run": list(wanted),
                            "passes": list(passes7.PASS_ORDER),
                            "key_format": "id{cat:03d}_r{rec}_{pass}_{onset}",
                            "supersedes": "drop_motifs7",
                        })
    print(f"\nmotif library -> {store_dir}  ({len(store_rows)} motifs, "
          f"{sum(int(r['is_pure']) for r in store_rows)} pure)")

    if not args.no_figures:
        from Pipelines.drop_motifs.figuresets72 import draw_all
        index = draw_all(store_dir, out_dir, summaries, wanted, span_signal)
        for summary in summaries:
            entry = index.get(str(summary["catalogue_id"]))
            if entry:
                summary["figure_set"] = entry
        if index.get("ALL"):
            summaries.append({"catalogue_id": "ALL", "pooled": index["ALL"]})

    (out_dir / "run_summary.json").write_text(
        json.dumps(summaries, indent=2, default=float), encoding="utf-8")

    from Pipelines.drop_motifs.report7 import write_report
    print(f"\nreport  -> {write_report(summaries, out_dir)}")
    print(f"figures -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
