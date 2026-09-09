"""
run_casestudy9_v2.py
=====================
The case study redrawn against the REFINED store, plus a per-window
dendrogram and rose so the effect of each change can be previewed on a
handful of motifs before committing to drop_motifs10.

    python Pipelines/drop_motifs/run_casestudy9_v2.py
    python Pipelines/drop_motifs/run_casestudy9_v2.py --windows 1:36 2:33

Writes `Plots/drop_motifs9_fig2a/example_case_studies_v2/`.

Per window, five figures:

    *_01_pipeline.png     as before, but STEP 4 now marks which detections
                          the refinement dropped, and why
    *_02_clustering.png   portrait, waterfalls side by side
    *_03_fall_angle.png   now showing where the DEPTH is measured from
    *_04_dendrogram.png   this window's own tree, both cuts
    *_05_rose.png         this window's own four-panel rose

WHAT IS DIFFERENT ABOUT THE DETECTIONS
--------------------------------------
The pipeline panel replays the window exactly as drop_motifs9 ran it, then
applies `refine9` to the result, so one figure carries both readings:

  * filled marker  - survived refinement
  * hollow marker  - dropped, with the reason (duplicate / below floor)

That is the point of a v2 preview: the operator asked whether these
corrections do what was intended, and the only honest way to answer is to
show what each one removed rather than to show a clean picture and assert
that the removals were right.

The refinement CANNOT add a detection. Missed drops - the operator's
"slight drop between m2 and m3 which is not recognised" - are untouched
here and stay a drop_motifs10 problem. Measured: that particular miss on
CH1 is 0.172 mV, comfortably ABOVE the 0.1 mV floor, so it is a genuine
sensitivity gap and not something the new gate explains away.
"""

import argparse
import collections
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

from Pipelines.drop_motifs import casestudy9, clusterfigs9 as cf9, refine9
from Working.Detection.drop_motifs import motifs5

DEFAULT_STORE = os.path.join("Plots", "drop_motifs9_fig2a", "refined_v2",
                             "motifs")
DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs9_fig2a",
                           "example_case_studies_v2")
SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900
DEFAULT_WINDOWS = ((1, 36), (2, 33), (4, 5))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--windows", nargs="*", default=None,
                        metavar="CH:WIN", help="e.g. 2:33 4:5")
    parser.add_argument("--max-families", type=int, default=8)
    args = parser.parse_args(argv)

    if args.windows:
        wanted = []
        for spec in args.windows:
            channel, _, window = spec.partition(":")
            wanted.append((int(channel), int(window)))
    else:
        wanted = list(DEFAULT_WINDOWS)

    rows, snippets, manifest = motifs5.load_store(args.store)
    if not rows:
        raise SystemExit(f"no motifs in {args.store}")
    print(f"{len(rows)} motifs from {args.store} "
          f"({manifest.get('kind', '?')})")

    print("building the pooled tree...", flush=True)
    tree = cf9.build_tree(rows, snippets, max_families=args.max_families)
    if tree is None:
        raise SystemExit("could not cluster the store")
    family_of = {r["event_id"]: int(label)
                 for r, label in zip(tree["keep"], tree["labels"])}
    print(f"  {tree['k']} coarse / {tree['fine_k']} fine families, "
          f"cophenetic r = {tree['cophenetic']:.3f}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    out_dir = _Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = {}
    for channel, window in wanted:
        catalogue_id = CATALOGUE_ID_BASE + channel
        kept = [r for r in rows if int(r["channel"]) == channel
                and int(r["window_index"]) == window]
        if not kept:
            print(f"\n! CH{channel} win{window} has no motifs after "
                  "refinement; skipping")
            continue

        recording = conn.execute(
            "SELECT * FROM recordings WHERE id = ?",
            (int(kept[0]["recording_id"]),)).fetchone()
        x_channel = np.asarray(np.load(recording["npy_path"], mmap_mode="r"),
                               dtype=float)
        fs = float(recording["fs"])
        start = int(round(window * 25 * fs))
        end = min(start + int(round(50 * fs)), len(x_channel))

        stem = f"CH{channel}_win{window:02d}"
        print(f"\n=== {stem}: samples {start}-{end} "
              f"({start / fs:.0f}-{end / fs:.0f} s), "
              f"{len(kept)} motifs after refinement ===", flush=True)

        replay = casestudy9.replay_window(
            x_channel, fs, start, end, catalogue_id=catalogue_id,
            recording_id=int(recording["id"]),
            source_file=os.path.basename(recording["npy_path"]),
            channel=channel, span_key=f"id{catalogue_id:03d}",
            span_label=f"{SOURCE_FILE} CH{channel}")
        print(f"    replayed {len(replay['rows'])} raw detections")

        entry = {"channel": channel, "window": window,
                 "samples": [start, end],
                 "n_raw": len(replay["rows"]), "n_refined": len(kept)}

        path, info = casestudy9.plot_pipeline(
            replay, x_channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs9 + refine9 — {SOURCE_FILE} CH{channel}, "
                  f"window {window} ({start / fs:.0f}–{end / fs:.0f} s)",
            family_of=family_of,
            kept_ids={r["event_id"] for r in kept})
        entry["pipeline"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        path, info = casestudy9.plot_clustering(
            kept, snippets, out_dir / f"{stem}_02_clustering.png",
            title=f"how the clustering measures these {len(kept)} refined "
                  "motifs", family_of=family_of)
        entry["clustering"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        path, info = casestudy9.plot_fall_angle(
            kept, snippets, out_dir / f"{stem}_03_fall_angle.png",
            title=f"{stem} — how a fall becomes an angle, and where the "
                  "depth is measured")
        entry["fall_angle"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        # This window's OWN tree and rose - the preview the operator asked
        # for. A window holds tens of motifs, not a thousand, so the two
        # cuts land much shallower and the figures are a sanity check on
        # the pooled pair rather than a substitute for them.
        window_tree = cf9.build_tree(kept, snippets,
                                     max_families=min(5, max(2, len(kept) // 4)))
        if window_tree is not None:
            path, info = cf9.plot_dendrogram(
                kept, snippets, out_dir / f"{stem}_04_dendrogram.png",
                title=f"{stem} — shape families in this window alone",
                tree=window_tree)
            entry["dendrogram"] = {"path": path, **(info or {})}
            print(f"    -> {path}")
        else:
            print(f"    (too few motifs for a window tree)")

        path, info = cf9.plot_rose(
            kept, snippets, out_dir / f"{stem}_05_rose.png",
            title=f"{stem} — fall gradients in this window alone")
        entry["rose"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        index[stem] = entry

    index_path = out_dir / "case_study_v2_index.json"
    merged = {}
    if index_path.exists():
        try:
            merged = json.loads(index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            merged = {}
    windows = merged.get("windows", {})
    windows.update(index)
    index_path.write_text(
        json.dumps({"windows": windows,
                    "store": args.store,
                    "refine": manifest.get("refine_report", {})},
                   indent=2, default=float), encoding="utf-8")
    print(f"\ncase study v2 -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
