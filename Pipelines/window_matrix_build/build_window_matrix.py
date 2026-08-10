"""
build_window_matrix.py
========================
DEPRECATED thin shim over `Working.Preprocessing.window_matrix.build.
build_window_matrix` + `Working.database.window_matrix_store.save_wm`.

This used to be the whole builder: a standalone script with `CH`/
`FILENAME`/`WINSIZE`/`FS`/`STEPFRAC` as module-level constants edited per
job, checkpointing to a `MATRICES/*.csv` file, and deciding what still
needed computing by looking for NaN in the first column of each stage.

That NaN check is WINDOW_MATRIX_UI_PROMPT.md §0.2's bug: `compute_incremental`
also WROTE NaN when a feature function raised, so "not yet computed" and
"computed, and the answer is NaN" were the same value, and a window that
reliably raised (a flat segment with no matching template for sample
entropy, a channel gap, ...) was retried on every resumed job forever. Never
marked done, so `--status` never reported DONE for that stage, so
`HPC/Preprocessing/wm_job.sh` — which decided whether to resubmit by
grepping `--status` output for "not started" or a partial fraction — kept
resubmitting the chain indefinitely. See WINDOW_MATRIX_UI_PROMPT.md §0.2 and
§5 for the full account; the fix lives in the storage format
(`window_matrix_store`'s explicit `computed` boolean mask, distinct from the
values) and in `wm_status.py` (an EXIT CODE derived from that mask, not a
grepped string), not in this script — leaving the old NaN-sentinel logic
here next to the fixed implementation is how the bug comes back, so it has
been deleted rather than patched.

This file now only:
  - parses the same CLI flags real jobs already invoke it with, so nothing
    that calls it breaks;
  - resolves the (recording, geometry) they describe;
  - calls the real builder and the real storage writer;
  - registers a `configs`/`runs`/`artifacts` row the same way a
    `run_recipe.py`/UI run would, so a build kicked off from here is visible
    in the ladder and coverage ribbons exactly like any other run.

Prefer `Pipelines/run_recipe/run_recipe.py` directly (or the UI's Run panel)
for anything new — this script exists for backward compatibility with
existing job scripts/muscle memory only.

Usage
-----
  python Pipelines/window_matrix_build/build_window_matrix.py                # build/resume
  python Pipelines/window_matrix_build/build_window_matrix.py --status       # report and exit
  python Pipelines/window_matrix_build/build_window_matrix.py --reset        # delete the artifact, start fresh
  python Pipelines/window_matrix_build/build_window_matrix.py --timeout 90
  python Pipelines/window_matrix_build/build_window_matrix.py --ch 5 --winsize 60 --fs 1.0
  python Pipelines/window_matrix_build/build_window_matrix.py --no-cnn --no-slow-entropy --no-rf
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
import sys

import numpy as np

from Working.database import queries as q
from Working.database import window_matrix_store as store
from Working.database.matrix_profile_store import compute_data_sha1
from Working.database.runs import get_or_create_config, insert_artifact, insert_run, update_run
from Working.database.schema import init_db
from Working.Preprocessing.window_matrix.build import build_window_matrix as _build_wm
from Working.recipes import make_recipe

# Defaults only now, not the whole job's identity — every one of these is a
# CLI flag (`--ch`/`--winsize`/`--fs`/`--stepfrac`) so a job no longer needs
# a source edit, which is exactly what `HPC/README.md` says a generated job
# must not require.
CH = 2
WINSIZE = 10.0
FS = 1.0
STEPFRAC = 1.0
DEFAULT_TIMEOUT_MIN = 19.0
DEFAULT_CNN_MODEL_DIR = "models"

_DEPRECATION_NOTICE = (
    "[build_window_matrix.py] DEPRECATED: this is a thin compatibility shim. "
    "Prefer `Pipelines/run_recipe/run_recipe.py --config <recipe.json>` "
    "(what `Working.hpc.job_export.export_wm_job` generates) or the UI's Run "
    "panel — WINDOW_MATRIX_UI_PROMPT.md §0.2 / §5."
)


def _resolve_recording(conn, args):
    """This script's own historical `FILENAME = f"M2_concat_fs1_CH{CH}.npy"`
    was a bare file path (`load_raw_data` never touched the DB); the
    `recordings` table `Pipelines.materialize_channels` actually populates
    keys on `source_file` as the ORIGINAL shared .mat basename (e.g.
    `M2_concat_fs1.mat`, no channel in the name) with `channel` as its own
    column — so a per-channel-styled filename's `_CH{ch}` suffix has to be
    stripped before it means anything as a DB lookup. Tries both spellings
    (with and without the suffix) rather than assuming either convention."""
    filename = args.filename or f"M2_concat_fs1_CH{args.ch}.npy"
    stem = os.path.splitext(filename)[0]
    suffix = f"_CH{args.ch}"
    stems = [stem, stem[: -len(suffix)]] if stem.endswith(suffix) else [stem]

    for candidate in stems:
        recording = q.get_recording(conn, f"{candidate}.mat", args.ch) or q.get_recording(conn, candidate, args.ch)
        if recording is not None:
            return recording
    raise SystemExit(
        f"No recording registered for channel {args.ch} matching '{filename}'. "
        "Materialise it first (Pipelines/materialize_channels) or use "
        "run_recipe.py / the UI directly."
    )


def _artifact_path(recording, args):
    stem = os.path.splitext(recording["source_file"])[0]
    name = store.artifact_name(stem, recording["channel"], args.winsize, args.stepfrac)
    return os.path.join(store.DEFAULT_RESULTS_DIR, f"{name}.npz")


def _selected_stages(args):
    stages = ["catch22", "fast_entropy"]
    if not args.no_slow_entropy:
        stages.append("slow_entropy")
    if not args.no_cnn:
        stages.append("cnn")
    if not args.no_rf:
        stages.append("rf")
    return tuple(stages)


def _print_status(path):
    print("\n" + "=" * 56)
    print("  Window Matrix Status")
    print("=" * 56)
    print(f"  Artifact  : {path}")
    if not os.path.isfile(path):
        print("  (no artifact yet — nothing computed)")
        print("=" * 56 + "\n")
        return
    loaded = store.load_wm(path, mmap=True)
    computed = np.asarray(loaded["computed"], dtype=bool)
    columns = [str(c) for c in loaded["columns"]]
    print(f"  Windows   : {computed.shape[0]:,}")
    print(f"  Columns   : {computed.shape[1]}")
    print(f"  Complete  : {bool(loaded['complete'])}")
    for stage, col_fn in store.STAGE_COLUMNS.items():
        cols = [c for c in col_fn() if c in columns]
        if not cols:
            continue
        idx = [columns.index(c) for c in cols]
        sub = computed[:, idx]
        done = int(sub.all(axis=1).sum())
        total = sub.shape[0]
        label = "DONE" if done == total else f"{done:,} / {total:,}"
        print(f"  {stage:<13s}: {label}")
    print("=" * 56 + "\n")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--ch", type=int, default=CH, help=f"Channel (default {CH})")
    p.add_argument("--winsize", type=float, default=WINSIZE, help=f"Window length, minutes (default {WINSIZE})")
    p.add_argument("--fs", type=float, default=None, help="Sample rate override, Hz (default: the recording's own fs)")
    p.add_argument("--stepfrac", type=float, default=STEPFRAC, help=f"Step as a fraction of window (default {STEPFRAC})")
    p.add_argument("--filename", default=None, help="Source .npy filename (default M2_concat_fs1_CH<ch>.npy)")
    p.add_argument("--reset", action="store_true", help="Delete the existing artifact and start fresh")
    p.add_argument("--status", action="store_true", help="Print completion status and exit without computing")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_MIN, metavar="MIN",
                   help=f"Timeout in minutes (default {DEFAULT_TIMEOUT_MIN})")
    p.add_argument("--no-cnn", action="store_true", help="Skip the CNN stage")
    p.add_argument("--no-slow-entropy", action="store_true", help="Skip sample/approximate entropy")
    p.add_argument("--no-rf", action="store_true", help="Skip the random-forest stage")
    p.add_argument("--cnn-model-dir", default=DEFAULT_CNN_MODEL_DIR)
    p.add_argument("--rf-model-path", default="")
    p.add_argument("--db", default=None, help="Database path (default: the repo default)")
    p.add_argument("--print-artifact-path", action="store_true",
                   help="Print ONLY the resolved artifact path to stdout and exit — "
                        "lets a caller (e.g. wm_job.sh, to feed wm_status.py) resolve "
                        "the same deterministic path this script itself computes, "
                        "without re-deriving the naming convention independently.")
    args = p.parse_args()

    print(_DEPRECATION_NOTICE, file=sys.stderr)

    conn = init_db(args.db)
    recording = _resolve_recording(conn, args)
    fs = args.fs if args.fs else recording["fs"]
    artifact_path = _artifact_path(recording, args)

    if args.print_artifact_path:
        print(artifact_path)
        return

    if args.reset and os.path.isfile(artifact_path):
        os.remove(artifact_path)
        print(f"Artifact removed: {artifact_path}")

    if args.status:
        _print_status(artifact_path)
        return

    stages = _selected_stages(args)
    resume_path = artifact_path if os.path.isfile(artifact_path) else None

    x_full = np.load(recording["npy_path"], mmap_mode="r")
    x = np.asarray(x_full)

    built = _build_wm(
        x, fs, args.winsize, step_frac=args.stepfrac, stages=stages,
        span_start=0, timeout_s=(args.timeout * 60.0 if args.timeout else None),
        resume_path=resume_path, cnn_model_dir=args.cnn_model_dir,
        rf_model_path=(args.rf_model_path or None),
    )

    recipe = make_recipe(recording["id"], [
        {"stage": "preprocessing", "algorithm": "window_matrix",
         "params": {
             "window_min": float(args.winsize), "step_frac": float(args.stepfrac),
             "catch22": "catch22" in stages, "fast_entropy": "fast_entropy" in stages,
             "slow_entropy": "slow_entropy" in stages, "cnn": "cnn" in stages,
             "rf": "rf" in stages, "timeout_s": float(args.timeout * 60.0),
             "resume_path": artifact_path.replace(os.sep, "/"),
             "cnn_model_dir": args.cnn_model_dir, "rf_model_path": args.rf_model_path,
             "partial_tail": False,
         }},
    ], span=None)
    config_id, config_hash = get_or_create_config(conn, recipe)
    # Always a NEW run row per invocation (never reused/short-circuited) —
    # this script is invoked once per HPC chain link specifically BECAUSE
    # the previous invocation timed out, so silently treating an earlier
    # "completed" run as done-and-reusable would be exactly the §0.2
    # conflation this shim exists to avoid. `execute_recipe` handles the
    # analogous case with `force=True`; this path never goes through
    # `execute_recipe`, so it simply never consults the reuse check at all.
    run_id = insert_run(conn, config_id, recording["id"], 0, recording["n_samples"], status="running")

    sha1 = compute_data_sha1(recording["npy_path"]) if os.path.isfile(recording["npy_path"]) else ""
    path = store.save_wm(
        built["values"], built["computed"], built["columns"], built["start_idx"],
        m=built["m"], step=built["step"], fs=fs, window_min=args.winsize, step_frac=args.stepfrac,
        span_start=0, span_end=recording["n_samples"], n_samples=recording["n_samples"],
        source_file=recording["source_file"], channel=recording["channel"],
        recording_id=recording["id"], data_sha1=sha1, config_hash=config_hash,
        elapsed_s=built["elapsed_s"],
    )
    insert_artifact(conn, run_id, kind="encoding", path=path)
    # The RUN is genuinely completed (this invocation ran to its declared
    # timeout/finished and produced a valid artifact) even when the ARTIFACT
    # is only partial — that partiality lives in the artifact's own
    # `complete` flag, not in the run's status (WINDOW_MATRIX_UI_PROMPT.md
    # §6.3). Marking the run 'failed' on a timeout would be exactly the
    # thing that makes a resumable build look broken.
    update_run(conn, run_id, status="completed", duration_s=built["elapsed_s"])

    _print_status(path)
    if built["timed_out"]:
        print(f"TIMEOUT — partial artifact saved at {path}. Re-run this command to resume.")
    elif built["cancelled"]:
        print(f"CANCELLED — partial artifact saved at {path}.")
    else:
        print("All requested stages complete." if built["complete"] else
              f"Stopped, but not all cells are computed — re-run to continue: {path}")


if __name__ == "__main__":
    main()
