"""
export_wm_scales.py
======================
Headless CLI over `Working.hpc.job_export.export_wm_job` for generating one
resumable SLURM job per (channel, window scale), for a single dataset.

This does not run anything and does not need a cluster connection: it only
writes a recipe JSON + `sbatch` script per (channel, window size) into
`HPC/Preprocessing/generated/` (`HPC/README.md`'s "Generated jobs"), using
the same chained/checkpointing template `wm_job.sh` uses by hand — each job
exits well before its SLURM `--time` limit, saves a resumable partial
artifact via the `computed` mask, and resubmits itself
(`wm_status.py`'s exit code, not a grepped string) until that job's matrix
is complete or the chain cap is reached.

Every (channel, scale) pair gets its OWN flat job/artifact rather than one
SLURM array job across channels: `export_wm_job`'s own docstring flags that
its `fan_out` path derives the resubmit chain's status-check artifact path
from the array's BASE recording only, so per-task resubmission does not
track each fanned-out channel's own completion correctly. Flat jobs sidestep
that known rough edge at the cost of more files, and channels are
independent runs anyway (no ordering constraint between them).

Stages default to `catch22` + `fast_entropy` + `slow_entropy` — the
single-value-per-window statistical/information-theoretic measures.
`cnn` (image-derived embedding) and `rf` (a learned classifier's output) are
excluded on purpose: neither is a statistical measure of the window itself,
and excluding `cnn` also means these jobs are CPU-only and never request a
GPU node.

Usage
-----
    python Pipelines/hpc_export/export_wm_scales.py --dataset M2_aug_concat_fs1 --ch 0
    python Pipelines/hpc_export/export_wm_scales.py --dataset M2_aug_concat_fs1 --ch 0-9 --winsizes 1,3,10,60
    python Pipelines/hpc_export/export_wm_scales.py --dataset M2_concat_fs1 --ch 3,5,7 --winsizes 10 --step-frac 0.5
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse
import os

from Working.config import HPC_REMOTE_REPO_ROOT
from Working.database import queries as q
from Working.database import window_matrix_store as store
from Working.database.schema import init_db
from Working.hpc.job_export import DEFAULT_WM_OUT_DIR, export_wm_job
from Working.Preprocessing.window_matrix.cost import estimate_seconds

# Single-value-per-window STATISTICAL measures only — matches
# `export_wm_job`'s own default. `cnn` and `rf` are deliberately excluded:
# see the module docstring.
STAT_STAGES = ("catch22", "fast_entropy", "slow_entropy")


def _parse_channels(spec):
    """`"0-9"` -> [0..9], `"0,2,5"` -> [0,2,5], `"3"` -> [3]. Comma-separated
    groups of either a single index or an inclusive `lo-hi` range, so both
    forms can be mixed (`"0-3,7,9-11"`)."""
    channels = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            channels.extend(range(int(lo), int(hi) + 1))
        else:
            channels.append(int(part))
    return channels


def _resolve_recording(conn, dataset, ch):
    """`dataset` may be given with or without the trailing `.mat` — both
    spellings are tried, same as `build_window_matrix.py`'s own lookup."""
    stem = dataset[:-4] if dataset.lower().endswith(".mat") else dataset
    recording = q.get_recording(conn, f"{stem}.mat", ch) or q.get_recording(conn, stem, ch)
    if recording is None:
        raise SystemExit(
            f"No recording registered for channel {ch} matching dataset '{dataset}'. "
            "Check Pipelines/materialize_channels has been run for it."
        )
    return recording


def _estimate_for(recording, window_min, step_frac):
    """Best-effort local calibration estimate (seconds), or `None` if this
    machine has never calibrated the window-matrix cost model. `export_wm_job`
    treats `None` the same as an uncalibrated machine always has: floor to
    the minimum SLURM time rather than guessing."""
    fs = recording["fs"]
    m = int(round(window_min * 60 * fs))
    step = max(1, int(round(step_frac * m)))
    n_windows = store.n_windows_for(recording["n_samples"], m, step, partial_tail=False)
    return estimate_seconds(n_windows, m, STAT_STAGES), n_windows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True,
                   help="Source .mat stem to target, e.g. M2_aug_concat_fs1 (with or without .mat)")
    p.add_argument("--ch", required=True,
                   help="Channel index/list/range, e.g. '0', '0,2,5', or '0-9'")
    p.add_argument("--winsizes", default="1,3,10,60",
                   help="Comma-separated window lengths in minutes (default: 1,3,10,60)")
    p.add_argument("--step-frac", type=float, default=1.0,
                   help="Step as a fraction of window length (default 1.0 = non-overlapping)")
    p.add_argument("--db", default=None, help="Database path (default: the repo default)")
    p.add_argument("--out-dir", default=DEFAULT_WM_OUT_DIR)
    args = p.parse_args()

    channels = _parse_channels(args.ch)
    winsizes = [float(w) for w in args.winsizes.split(",") if w.strip()]

    conn = init_db(args.db)
    print(f"dataset={args.dataset}  channels={channels}  winsizes={winsizes}")
    print(f"stages={STAT_STAGES}  step_frac={args.step_frac}\n")

    results = []  # (channel, window_min, result)
    total_est = 0.0
    any_unestimated = False
    for ch in channels:
        recording = _resolve_recording(conn, args.dataset, ch)
        for window_min in winsizes:
            est_seconds, n_windows = _estimate_for(recording, window_min, args.step_frac)
            result = export_wm_job(
                conn, recording["id"], window_min, step_frac=args.step_frac,
                stages=STAT_STAGES, est_seconds=est_seconds, out_dir=args.out_dir,
            )
            results.append((ch, window_min, result))
            if est_seconds is None:
                any_unestimated = True
            else:
                total_est += est_seconds
            est_str = f"{est_seconds:,.0f}s" if est_seconds is not None else "uncalibrated"
            print(f"CH{ch:<3d} WIN{window_min:g}min  n_windows={n_windows:,}  "
                  f"est={est_str}  time={result['slurm_time']}  -> {result['script_path']}")

    conn.close()

    print(f"\n{len(results)} job(s) generated for {len(channels)} channel(s) x {len(winsizes)} scale(s).")
    if any_unestimated:
        print("(some estimates unavailable -> those jobs floor to the minimum SLURM time)")
    else:
        print(f"Sum of local per-job estimates (informational only, not summed across parallel "
              f"jobs): {total_est:,.0f}s (~{total_est / 60:,.1f} min)")

    ch_lo, ch_hi = min(channels), max(channels)
    submit_name = f"submit_{args.dataset}_CH{ch_lo}-{ch_hi}.sh"
    submit_path = os.path.join(args.out_dir, submit_name)
    with open(submit_path, "w", newline="\n") as f:
        f.write("#!/bin/bash\n")
        f.write(f"# Submits all {len(results)} window-matrix jobs generated for dataset="
                f"{args.dataset}, channels {ch_lo}-{ch_hi}, winsizes={winsizes}.\n")
        f.write("# Channels and scales are independent runs -- no ordering requirement between\n")
        f.write("# them, so this just fires every job at once and lets SLURM's own queue/\n")
        f.write("# fair-share decide how many run concurrently. Run from the repo root on the\n")
        f.write(f"# cluster ({HPC_REMOTE_REPO_ROOT}).\n")
        f.write("set -euo pipefail\n\n")
        for ch, window_min, result in results:
            f.write(f"{result['sbatch_command']}\n")

    print(f"\nWrote a batch submit script covering all {len(results)} jobs:\n  {submit_path}")
    print(f"\nOn the cluster, from {HPC_REMOTE_REPO_ROOT}:")
    print(f"  bash {submit_path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
