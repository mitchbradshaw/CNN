"""
run_casestudy9_v3.py
=====================
The third and final drop_motifs9 case study, before results are summarised
and drop_motifs10 begins.

    python Pipelines/drop_motifs/run_casestudy9_v3.py

Writes `Plots/drop_motifs9_fig2a/example_case_studies_v3/`:

    <window>_01_pipeline.png     per window
    <window>_02_clustering.png   per window
    <window>_03_fall_angle.png   per window
    COMBINED_dendrogram.png      ONE tree over all three windows
    COMBINED_rose.png            ONE rose over all three windows

What changed since v2
---------------------
MOTIFS ARE SELECTED BY TIME, NOT BY `window_index`. This is a correction,
and it is the reason v2 reported only ONE drop in CH2 window 33 where the
operator counted two.

A drop that sits in two overlapping windows is stored once, tagged with
the window whose framing won `passes9`'s best-framed rule - which is often
the NEIGHBOUR. Filtering the store by `window_index == 33` therefore hides
any drop in that time range whose winning copy was attributed to window 32
or 34. Selecting by sample range instead asks the question the figure is
actually asking - "what did the detector find between 825 s and 875 s" -
and returns both of CH2's drops, at 856.0 s and 870.8 s.

Nothing about the detection changed. This was a bug in how the case study
QUERIED the store, and it made the refinement look more destructive than
it is.

ONE COMBINED TREE AND ONE COMBINED ROSE. Per-window trees over ten motifs
say very little; pooling the three windows is the smallest set on which
"do these channels produce the same shapes?" is a real question. The three
windows are one per channel and were chosen to be unalike - a quiet
stretch (CH2), a mixed one (CH1) and a dense regular train (CH4) - so a
tree that mixes them is evidence of shared morphology and one that
separates them is evidence of per-channel character.
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

from Pipelines.drop_motifs import casestudy9, clusterfigs9 as cf9
from Working.Detection.drop_motifs import motifs5

DEFAULT_STORE = os.path.join("Plots", "drop_motifs9_fig2a", "refined_v2",
                             "motifs")
DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs9_fig2a",
                           "example_case_studies_v3")
SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900
WINDOW_S, HOP_S = 50.0, 25.0
DEFAULT_WINDOWS = ((1, 36), (2, 33), (4, 5))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--windows", nargs="*", default=None,
                        metavar="CH:WIN")
    parser.add_argument("--max-families", type=int, default=6)
    args = parser.parse_args(argv)

    wanted = ([tuple(int(v) for v in spec.split(":"))
               for spec in args.windows] if args.windows
              else list(DEFAULT_WINDOWS))

    rows, snippets, manifest = motifs5.load_store(args.store)
    if not rows:
        raise SystemExit(f"no motifs in {args.store}")
    print(f"{len(rows)} motifs from {args.store}")

    print("building the pooled tree (for family colours)...", flush=True)
    pooled = cf9.build_tree(rows, snippets, max_families=8)
    family_of = {r["event_id"]: int(label)
                 for r, label in zip(pooled["keep"], pooled["labels"])}
    print(f"  {pooled['k']} coarse / {pooled['fine_k']} fine families")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    out_dir = _Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    index, combined = {}, []
    for channel, window in wanted:
        catalogue_id = CATALOGUE_ID_BASE + channel
        recording = conn.execute(
            "SELECT * FROM recordings WHERE source_file = ? AND channel = ?",
            (SOURCE_FILE, channel)).fetchone()
        if recording is None:
            print(f"\n! no recording for CH{channel}; skipping")
            continue
        fs = float(recording["fs"])
        start = int(round(window * HOP_S * fs))
        end = int(round(start + WINDOW_S * fs))

        # BY TIME, not by window_index. See the module docstring.
        kept = [r for r in rows
                if int(r["channel"]) == channel
                and start <= int(r["onset_idx"]) < end]
        kept.sort(key=lambda r: int(r["onset_idx"]))
        if not kept:
            print(f"\n! CH{channel} win{window} holds no motifs; skipping")
            continue

        x_channel = np.asarray(np.load(recording["npy_path"], mmap_mode="r"),
                               dtype=float)
        stem = f"CH{channel}_win{window:02d}"
        print(f"\n=== {stem}: {start / fs:.0f}-{end / fs:.0f} s  ->  "
              f"{len(kept)} motifs in this time range ===", flush=True)
        for row in kept:
            print(f"      {int(row['onset_idx']) / fs:7.1f} s  "
                  f"depth {abs(float(row['drop_depth_mv'])):.3f} mV  "
                  f"(stored under window {int(row['window_index'])})")

        replay = casestudy9.replay_window(
            x_channel, fs, start, end, catalogue_id=catalogue_id,
            recording_id=int(recording["id"]),
            source_file=os.path.basename(recording["npy_path"]),
            channel=channel, span_key=f"id{catalogue_id:03d}",
            span_label=f"{SOURCE_FILE} CH{channel}")

        entry = {"channel": channel, "window": window,
                 "seconds": [start / fs, end / fs],
                 "n_raw": len(replay["rows"]), "n_kept": len(kept),
                 "kept": [{"onset_s": int(r["onset_idx"]) / fs,
                           "depth_mv": abs(float(r["drop_depth_mv"])),
                           "stored_window": int(r["window_index"])}
                          for r in kept]}

        path, info = casestudy9.plot_pipeline(
            replay, x_channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs9 + refine9 — {SOURCE_FILE} CH{channel}, "
                  f"{start / fs:.0f}–{end / fs:.0f} s",
            family_of=family_of,
            kept_ids={r["event_id"] for r in kept})
        entry["pipeline"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        if len(kept) >= 3:
            path, info = casestudy9.plot_clustering(
                kept, snippets, out_dir / f"{stem}_02_clustering.png",
                title=f"{stem} — how the clustering measures these "
                      f"{len(kept)} motifs", family_of=family_of)
            entry["clustering"] = {"path": path, **(info or {})}
            print(f"    -> {path}")
        else:
            print(f"    (only {len(kept)} motifs; clustering panel skipped)")

        path, info = casestudy9.plot_fall_angle(
            kept, snippets, out_dir / f"{stem}_03_fall_angle.png",
            title=f"{stem} — how a fall becomes an angle, and where the "
                  "depth is measured")
        entry["fall_angle"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        combined.extend(kept)
        index[stem] = entry

    # -- ONE tree and ONE rose over all three windows ---------------------
    print(f"\n=== COMBINED: {len(combined)} motifs from "
          f"{len(index)} windows ===", flush=True)
    if len(combined) >= 6:
        tree = cf9.build_tree(combined, snippets,
                              max_families=args.max_families)
        if tree is not None:
            print(f"  tree: {tree['k']} coarse / {tree['fine_k']} fine, "
                  f"cophenetic r = {tree['cophenetic']:.3f}")
            path, info = cf9.plot_dendrogram(
                combined, snippets, out_dir / "COMBINED_dendrogram.png",
                title="all three case-study windows pooled — do the three "
                      "channels make the same shapes?", tree=tree)
            index["COMBINED_dendrogram"] = {"path": path, **(info or {})}
            print(f"  -> {path}")

        path, info = cf9.plot_rose(
            combined, snippets, out_dir / "COMBINED_rose.png",
            title="all three case-study windows pooled — fall gradients")
        index["COMBINED_rose"] = {"path": path, **(info or {})}
        print(f"  -> {path}")
        if info and "spearman_rho_depth_vs_angle" in info:
            print(f"  height vs angle: rho = "
                  f"{info['spearman_rho_depth_vs_angle']:+.3f}, "
                  f"n = {info['n']}  ·  control exponent "
                  f"{info.get('duration_vs_depth_exponent', float('nan')):.3f}")
    else:
        print(f"  only {len(combined)} motifs pooled; too few to cluster")

    (out_dir / "case_study_v3_index.json").write_text(
        json.dumps({"windows": index, "store": args.store,
                    "n_combined": len(combined)},
                   indent=2, default=float), encoding="utf-8")
    print(f"\ncase study v3 -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
