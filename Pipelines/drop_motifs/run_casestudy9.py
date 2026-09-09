"""
run_casestudy9.py
==================
Draw the drop_motifs9 pipeline end to end for one window (or several), for
the report.

    python Pipelines/drop_motifs/run_casestudy9.py
    python Pipelines/drop_motifs/run_casestudy9.py --channel 2 --window 21
    python Pipelines/drop_motifs/run_casestudy9.py --auto 3

Writes `Plots/drop_motifs9_fig2a/example_case_study/`.

Choosing the window
-------------------
`--auto N` picks the N windows that best ILLUSTRATE the pipeline, which is
not the same as the N most interesting windows. The score wants: at least
three pooled shape families present, at least three members in the
smallest of them, a wide spread of drop depths, and enough motifs to make
a distance matrix worth reading. A window with forty near-identical drops
teaches nothing about clustering.

The default is CH2 window 33, which scored top: 17 motifs, all three
families, smallest family 3 members, deepest drop 29x the shallowest.

The families a motif belongs to are the POOLED ones - the labels from
`clusterfigs9.build_tree` over the whole 1736-motif store, the same cut
`ALL_dendrogram.png` draws - so a colour in the case study is the same
family as that colour in the pooled figures. Figure 2's own little tree is
built from this window's motifs alone and will not always agree with the
pooled cut; that disagreement is real and is worth seeing.
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

from Pipelines.drop_motifs import casestudy9, clusterfigs9 as cf9
from Working.Detection.drop_motifs import motifs5

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_STORE = os.path.join("Plots", "drop_motifs9_fig2a", "motifs")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs9_fig2a",
                           "example_case_study")
SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900

# The default, from `--auto`'s own scoring. See the module docstring.
DEFAULT_CHANNEL, DEFAULT_WINDOW = 2, 33


def score_windows(rows, family_of, min_motifs=6):
    """Rank windows by how well they illustrate the pipeline."""
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[(int(row["channel"]), int(row["window_index"]))].append(row)

    scored = []
    for key, members in grouped.items():
        if len(members) < min_motifs:
            continue
        families = collections.Counter(
            family_of[r["event_id"]] for r in members
            if r["event_id"] in family_of)
        if not families:
            continue
        depths = np.array([abs(float(r["drop_depth_mv"])) for r in members])
        spread = float(depths.max() / max(depths.min(), 1e-9))
        scored.append({
            "channel": key[0], "window": key[1],
            "n": len(members), "n_families": len(families),
            "smallest_family": min(families.values()),
            "depth_spread": spread,
            "families": {str(k): v for k, v in sorted(families.items())},
        })
    scored.sort(key=lambda s: (-s["n_families"], -s["smallest_family"],
                               -s["depth_spread"], -s["n"]))
    return scored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--window", type=int, default=None,
                        help="window index within that channel")
    parser.add_argument("--auto", type=int, default=None, metavar="N",
                        help="draw the N best-illustrating windows instead")
    parser.add_argument("--max-families", type=int, default=8)
    args = parser.parse_args(argv)

    rows, snippets, manifest = motifs5.load_store(args.store)
    if not rows:
        raise SystemExit(f"no motifs in {args.store}")
    print(f"{len(rows)} motifs from {args.store}")

    print("building the pooled tree (the same cut ALL_dendrogram.png "
          "draws)...", flush=True)
    tree = cf9.build_tree(rows, snippets, max_families=args.max_families)
    if tree is None:
        raise SystemExit("could not cluster the store")
    family_of = {r["event_id"]: int(label)
                 for r, label in zip(tree["keep"], tree["labels"])}
    print(f"  {tree['k']} families, cophenetic r = {tree['cophenetic']:.3f}")

    ranked = score_windows(rows, family_of)
    if args.auto:
        chosen = [(s["channel"], s["window"]) for s in ranked[:args.auto]]
        print(f"\ntop {len(chosen)} windows by illustration score:")
        for entry in ranked[:args.auto]:
            print(f"  CH{entry['channel']} win{entry['window']:02d}  "
                  f"n={entry['n']:<3d} families={entry['n_families']} "
                  f"smallest={entry['smallest_family']} "
                  f"depth spread={entry['depth_spread']:.0f}x")
    else:
        channel = DEFAULT_CHANNEL if args.channel is None else args.channel
        window = DEFAULT_WINDOW if args.window is None else args.window
        chosen = [(channel, window)]

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    out_dir = _Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = {}
    for channel, window in chosen:
        catalogue_id = CATALOGUE_ID_BASE + channel
        window_rows = [r for r in rows
                       if int(r["channel"]) == channel
                       and int(r["window_index"]) == window]
        if not window_rows:
            print(f"\n! CH{channel} window {window} has no stored motifs; "
                  "skipping")
            continue

        start = int(window_rows[0]["window_start_idx"])
        end = int(window_rows[0]["window_end_idx"])
        recording = conn.execute(
            "SELECT * FROM recordings WHERE id = ?",
            (int(window_rows[0]["recording_id"]),)).fetchone()
        x_channel = np.asarray(np.load(recording["npy_path"], mmap_mode="r"),
                               dtype=float)
        fs = float(recording["fs"])

        stem = f"CH{channel}_win{window:02d}"
        print(f"\n=== {stem}: samples {start}-{end} "
              f"({start / fs:.0f}-{end / fs:.0f} s), "
              f"{len(window_rows)} stored motifs ===", flush=True)

        replay = casestudy9.replay_window(
            x_channel, fs, start, end, catalogue_id=catalogue_id,
            recording_id=int(recording["id"]),
            source_file=os.path.basename(recording["npy_path"]),
            channel=channel, span_key=f"id{catalogue_id:03d}",
            span_label=f"{SOURCE_FILE} CH{channel}")
        print(f"    replayed: {len(replay['rows'])} detections in this "
              f"window before cross-window dedup, "
              f"{len(window_rows)} survived")

        entry = {"channel": channel, "window": window,
                 "samples": [start, end],
                 "seconds": [start / fs, end / fs],
                 "n_detected_in_window": len(replay["rows"]),
                 "n_survived_dedup": len(window_rows)}

        path, info = casestudy9.plot_pipeline(
            replay, x_channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs9 case study — {SOURCE_FILE} CH{channel}, "
                  f"window {window} ({start / fs:.0f}–{end / fs:.0f} s): "
                  "one window, every stage",
            family_of=family_of,
            kept_ids={r["event_id"] for r in window_rows})
        entry["pipeline"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        path, info = casestudy9.plot_clustering(
            window_rows, snippets, out_dir / f"{stem}_02_clustering.png",
            title=f"drop_motifs9 case study — how the clustering measures "
                  f"these {len(window_rows)} motifs",
            family_of=family_of)
        entry["clustering"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        path, info = casestudy9.plot_fall_angle(
            window_rows, snippets, out_dir / f"{stem}_03_fall_angle.png",
            title=f"drop_motifs9 case study — how a fall becomes an angle "
                  f"on the rose")
        entry["fall_angle"] = {"path": path, **(info or {})}
        print(f"    -> {path}")

        index[stem] = entry

    # MERGE rather than overwrite: drawing one window at a time is the
    # normal way to use this, and a plain write would leave the index
    # describing only whichever window was drawn last while the other
    # PNGs sat beside it undocumented.
    index_path = out_dir / "case_study_index.json"
    merged = {}
    if index_path.exists():
        try:
            merged = json.loads(index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            merged = {}
    windows = merged.get("windows", {})
    windows.update(index)
    index_path.write_text(
        json.dumps({"windows": windows, "ranking": ranked[:12]},
                   indent=2, default=float), encoding="utf-8")
    print(f"\ncase study -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
