"""
run_drop9_report.py
====================
drop_motifs9: sliding-window drop detection over the five Fig2A channels,
then the pooled figures.

    python Pipelines/drop_motifs/run_drop9_report.py
    python Pipelines/drop_motifs/run_drop9_report.py --window-s 100 --overlap 0.75
    python Pipelines/drop_motifs/run_drop9_report.py --channels 2 3
    python Pipelines/drop_motifs/run_drop9_report.py --no-figures

What is new against drop_motifs8
--------------------------------
DETECTION SLIDES. `passes9.detect_sliding` runs the drop passes over a
50 s window stepped by half its length, so the scale each pass derives is
the scale of 50 s of signal rather than of the whole 20-minute channel.
The same drop found in two overlapping windows is stored once, and the
copy kept is the one framed nearest its window's centre. See `passes9`.

DROPS ONLY. The inverted pass does not run.

THE FIGURES ARE POOLED, NOT PER-CHANNEL. The question this run is for is
about the population across all five channels - which shapes recur, and
whether drop height goes with drop slope - so the three figures are all
pooled and carry channel as a colour rather than as a separate page.

Writes `Plots/drop_motifs9_fig2a/` and touches nothing earlier.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import passes9
from Working.Detection.drop_motifs import motifs5

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_PLOT_DIR = os.path.join("Plots", "drop_motifs9_fig2a")
SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900
STORE_KIND = "drop_motifs9"


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def run_channel(conn, catalogue_id, recording_id, args):
    row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                       (recording_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no recording {recording_id}")
    x = np.asarray(np.load(row["npy_path"], mmap_mode="r"), dtype=float)
    fs = float(row["fs"])
    channel = int(row["channel"])

    started = time.time()
    rows, arrays, info = passes9.detect_sliding(
        x, fs,
        catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=os.path.basename(row["npy_path"]), channel=channel,
        window_s=args.window_s, overlap=args.overlap,
        span_label=f"{SOURCE_FILE} CH{channel}",
        span_key=f"id{catalogue_id:03d}",
        max_passes=args.max_passes, fine=not args.no_fine,
        sensitive=not args.no_sensitive, micro=not args.no_micro)

    pure = sum(int(r["is_pure"]) for r in rows)
    summary = dict(
        catalogue_id=catalogue_id, recording_id=recording_id,
        channel=channel, source_file=SOURCE_FILE, fs=fs,
        n_samples=len(x), span_hours=None, span_offset=0,
        annotated_n=None, expected_morphology=None,
        note=f"{SOURCE_FILE} CH{channel} - sliding window, drops only",
        n_motifs=len(rows), n_pure=int(pure), n_impure=len(rows) - int(pure),
        purity_clean_fraction=(pure / len(rows)) if rows else 0.0,
        seconds=round(time.time() - started, 1),
        **{k: v for k, v in info.items() if k != "per_window"})
    summary["n_windows_detail"] = len(info["per_window"])
    return summary, rows, arrays, x


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", nargs="*", type=int, default=None)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--plot-dir", default=DEFAULT_PLOT_DIR)
    parser.add_argument("--source-file", default=SOURCE_FILE)
    parser.add_argument("--window-s", type=float,
                        default=passes9.DEFAULT_WINDOW_S)
    parser.add_argument("--overlap", type=float,
                        default=passes9.DEFAULT_OVERLAP)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--max-families", type=int, default=8)
    parser.add_argument("--pure-only", action="store_true",
                        help="cluster and rose the pure motifs only")
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-fine", action="store_true")
    parser.add_argument("--no-sensitive", action="store_true")
    parser.add_argument("--no-micro", action="store_true")
    args = parser.parse_args(argv)

    conn = open_db(args.db)
    recordings = conn.execute(
        "SELECT id, channel FROM recordings WHERE source_file = ? "
        "ORDER BY channel", (args.source_file,)).fetchall()
    if not recordings:
        raise SystemExit(f"no recordings for {args.source_file!r}")

    wanted = [(CATALOGUE_ID_BASE + int(r["channel"]), int(r["id"]))
              for r in recordings
              if args.channels is None or int(r["channel"]) in args.channels]
    if not wanted:
        raise SystemExit(f"no channel matched {args.channels}")

    out_dir = _Path(args.plot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries, store_rows, store_arrays = [], [], {}
    for catalogue_id, recording_id in wanted:
        print(f"[id{catalogue_id}] CH{catalogue_id - CATALOGUE_ID_BASE}",
              flush=True)
        summary, rows, arrays, _ = run_channel(conn, catalogue_id,
                                               recording_id, args)
        kept = summary["per_pass_kept"]
        print(f"      {summary['n_windows']} windows of "
              f"{summary['window_s']:g}s @ {summary['overlap']:.0%} overlap"
              f"  ->  {summary['n_before_dedup']} raw, "
              f"{summary['n_duplicates_dropped']} duplicates dropped, "
              f"{summary['n_motifs']} kept ({summary['n_pure']} pure)",
              flush=True)
        print(f"      base={kept.get('base', 0):<4d} "
              f"fine={kept.get('fine', 0):<4d} sens={kept.get('sens', 0):<4d} "
              f"micro={kept.get('micro', 0):<4d}  "
              f"truncated={summary['n_truncated']}  "
              f"{summary['seconds']}s", flush=True)
        store_rows.extend(rows)
        store_arrays.update(arrays)
        summaries.append(summary)

    store_dir = out_dir / "motifs"
    motifs5.write_store(str(store_dir), store_rows, store_arrays,
                        manifest_extra={
                            "kind": STORE_KIND,
                            "detector": "detect5 + passes9 (sliding window, "
                                        "drops only)",
                            "source_file": args.source_file,
                            "window_s": float(args.window_s),
                            "overlap": float(args.overlap),
                            "directions": "drops only",
                            "channels": [c - CATALOGUE_ID_BASE
                                         for c, _ in wanted],
                            "key_format": "id{cat:03d}_r{rec}_{pass}_{onset}",
                            "validated_against_human": False,
                        })
    total_pure = sum(int(r["is_pure"]) for r in store_rows)
    print(f"\nmotif library -> {store_dir}  ({len(store_rows)} motifs, "
          f"{total_pure} pure)")

    index = {}
    if not args.no_figures:
        from Pipelines.drop_motifs import clusterfigs9 as cf9

        rows, snippets, _ = motifs5.load_store(str(store_dir))
        if args.pure_only:
            rows = [r for r in rows if int(r["is_pure"])]
        excluded = len(store_rows) - len(rows)
        print(f"\nfigures over {len(rows)} motifs"
              + (f" ({excluded} impure excluded)" if excluded else ""))

        tree = cf9.build_tree(rows, snippets, max_families=args.max_families)
        if tree is None:
            print("  ! too few motifs to cluster; skipping figures")
        else:
            print(f"  tree: {tree['k']} families, "
                  f"cophenetic r = {tree['cophenetic']:.3f}")

            path, info = cf9.plot_dendrogram(
                rows, snippets, out_dir / "ALL_dendrogram.png",
                title="drop_motifs9 — pooled shape families, all channels",
                tree=tree, excluded=excluded)
            index["dendrogram"] = {"path": path, **(info or {})}
            print(f"  -> {path}")

            path, info = cf9.plot_family_atlas(
                rows, snippets, out_dir / "ALL_families.png",
                title="drop_motifs9 — every motif, grouped by shape family",
                tree=tree)
            index["atlas"] = {"path": path, **(info or {})}
            print(f"  -> {path}")

        path, info = cf9.plot_rose(
            rows, snippets, out_dir / "ALL_rose.png",
            title="drop_motifs9 — fall gradients by channel and drop height")
        index["rose"] = {"path": path, **(info or {})}
        print(f"  -> {path}")
        if info and "spearman_rho_depth_vs_angle" in info:
            print(f"\n  HEIGHT vs SLOPE: Spearman rho = "
                  f"{info['spearman_rho_depth_vs_angle']:+.3f} "
                  f"(95% CI {info['rho_ci95'][0]:+.3f} to "
                  f"{info['rho_ci95'][1]:+.3f}), "
                  f"p = {info['spearman_p']:.2g}, n = {info['n']}")
            print(f"  {info['verdict']}")

    (out_dir / "run_summary.json").write_text(
        json.dumps({"channels": summaries, "figures": index},
                   indent=2, default=float), encoding="utf-8")
    print(f"\nfigures -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
