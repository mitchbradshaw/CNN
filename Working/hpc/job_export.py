"""
job_export.py
===============
Headless HPC job generation for matrix-profile runs
(MATRIX_PROFILE_UI_PROMPT.md §5). Generates a recipe JSON in exactly the
shape `Pipelines/run_recipe/run_recipe.py` reads, plus an `sbatch` script
that invokes it — no SSH, no submission from here. `Working/` must not
import Panel; this module doesn't either.

`export_mp_job` deliberately goes through `run_recipe.py`, not
`Pipelines/matrix_profile/run_matrix_profile.py` directly — the latter has
`CH`/`FILE`/`WINDOW_MIN` as module-level constants that would need editing
per job (exactly what `HPC/README.md` says not to do). Going through
`run_recipe.py` also means the cluster run registers its own
`runs`/`artifacts` rows via `detection.matrix_profile`'s `persist` hook,
so a returned `.npz` slots into the browser with no separate import step.

Two things this module does NOT resolve on its own:

1. **`--chdir`.** `HPC/README.md` records that hand-written job scripts
   disagree (`/home/s4699158/CNN` in `score_job.sh` vs
   `/home/Student/s4699158/CNN` in `wm_job.sh`/`mp_job.sh`). Generated
   scripts use `Working.config.HPC_REMOTE_REPO_ROOT` — confirm that value
   is actually correct for your account before submitting anything it
   produces.
2. **Getting the files to the cluster.** This only writes into the local
   working tree (`HPC/Detection/generated/` by default). The generated
   `.sh`/`.json` pair still needs to reach rangpur the same way the
   hand-written scripts do (git sync, scp, ...) before `sbatch` can run it.
"""

import json
import math
import os

from Working.config import HPC_REMOTE_REPO_ROOT
from Working.database import queries as q
from Working.database.runs import get_or_create_config
from Working.recipes import make_recipe

DEFAULT_OUT_DIR = os.path.join("HPC", "Detection", "generated")
DEFAULT_WM_OUT_DIR = os.path.join("HPC", "Preprocessing", "generated")

_MIN_TIME_MINUTES = 30
_TIME_ROUND_MINUTES = 15
_TIME_SAFETY_FACTOR = 3  # est_seconds is from a DIFFERENT machine than the one the job lands on


def _slurm_time_from_estimate(est_seconds):
    """`--time`, per MATRIX_PROFILE_UI_PROMPT.md §5: `est_seconds * 3`,
    rounded up to the next 15 minutes, floor 30 minutes. `None` (no
    calibration on this machine) also floors to 30 minutes — a
    deliberately conservative default, not a guessed estimate."""
    if est_seconds is None:
        minutes = 0
    else:
        minutes = (est_seconds / 60.0) * _TIME_SAFETY_FACTOR
    rounded = math.ceil(minutes / _TIME_ROUND_MINUTES) * _TIME_ROUND_MINUTES
    minutes = max(_MIN_TIME_MINUTES, rounded)
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}:00"


_SCRIPT_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --chdir={remote_root}
#SBATCH --output={remote_root}/logs/{base_name}_%j.out
#SBATCH --error={remote_root}/logs/{base_name}_%j.err
#SBATCH --time={slurm_time}
#SBATCH --gres=gpu:a100
#SBATCH --cpus-per-task=4

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "========================================"

mkdir -p logs

module load cuda/12.2

source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

python Pipelines/run_recipe/run_recipe.py --config {recipe_repo_path}

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
"""


def export_mp_job(conn, recording_id, window_min, span=None, *,
                   est_seconds=None, backend="auto", out_dir=DEFAULT_OUT_DIR):
    """Generate a recipe JSON + `sbatch` script for a
    `detection.matrix_profile` run of `window_min` minutes over
    `recording_id` (`span=None` means the whole channel).

    Named by config hash (`{base_name}.json` / `.sh`), so re-exporting the
    exact same job overwrites its own prior export rather than
    accumulating a new pair every time.

    Returns `{"script_path", "recipe_path", "sbatch_command", "job_name"}`
    (all paths local/relative — see module docstring for what still needs
    to happen before `sbatch_command` can actually run anywhere).
    """
    recording = q.get_recording_by_id(conn, recording_id)
    if recording is None:
        raise ValueError(f"No recording with id={recording_id}")

    recipe = make_recipe(recording_id, [
        {"stage": "detection", "algorithm": "matrix_profile",
         "params": {"window_min": float(window_min), "backend": backend}},
    ], span=span)
    _config_id, hash8 = get_or_create_config(conn, recipe)

    channel = recording["channel"]
    stem = os.path.splitext(recording["source_file"])[0]
    base_name = f"mp_{stem}_CH{channel}_WIN{window_min:g}min_{hash8}"
    job_name = f"mp_CH{channel}_WIN{window_min:g}min"

    os.makedirs(out_dir, exist_ok=True)
    recipe_path = os.path.join(out_dir, f"{base_name}.json")
    with open(recipe_path, "w") as f:
        json.dump(recipe, f, indent=2)

    # The path baked into the script is REPO-RELATIVE (forward slashes,
    # regardless of the OS this was generated on) -- the job's own
    # `--chdir` puts it at HPC_REMOTE_REPO_ROOT, so a relative path here
    # is what resolves correctly once the generated pair is synced across
    # to the cluster at the same relative location.
    recipe_repo_path = recipe_path.replace(os.sep, "/")
    script_path = os.path.join(out_dir, f"{base_name}.sh")
    script = _SCRIPT_TEMPLATE.format(
        job_name=job_name, remote_root=HPC_REMOTE_REPO_ROOT, base_name=base_name,
        slurm_time=_slurm_time_from_estimate(est_seconds), recipe_repo_path=recipe_repo_path,
    )
    with open(script_path, "w") as f:
        f.write(script)

    return {
        "script_path": script_path, "recipe_path": recipe_path,
        "sbatch_command": f"sbatch {script_path.replace(os.sep, '/')}", "job_name": job_name,
    }


# ===========================================================================
# Window matrix (WINDOW_MATRIX_UI_PROMPT.md §7)
# ===========================================================================
#
# Differs from the matrix-profile template in exactly the ways that follow
# from the window matrix being RESUMABLE and the matrix profile not being:
#
#  - the chain resubmits itself, as `HPC/Preprocessing/wm_job.sh` does;
#  - it resubmits on `wm_status.py`'s EXIT CODE, not by grepping a status
#    string — the grep is what turned one stuck window into an infinite
#    chain (WINDOW_MATRIX_UI_PROMPT.md §0.2);
#  - there is a hard cap on chain length, so even a bug that always reports
#    incomplete terminates;
#  - resuming jobs pass `--force`, because `execute_recipe` short-circuits
#    on a completed run for the same recipe and span and would otherwise
#    "reuse" the partial matrix instead of continuing it;
#  - `--gres=gpu:a100` only when a CNN stage is enabled. A Catch22 +
#    entropy build is CPU-only and should not queue for a GPU node.

_WM_SCRIPT_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --chdir={remote_root}
#SBATCH --output={remote_root}/logs/{base_name}_%j.out
#SBATCH --error={remote_root}/logs/{base_name}_%j.err
#SBATCH --time={slurm_time}
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
{gpu_line}
# Chain position, incremented on each resubmit. Capped at {max_chain} so a
# bug that always reports "incomplete" terminates instead of burning the
# allocation -- the failure mode the hand-written wm_job.sh has today.
CHAIN_INDEX="${{1:-1}}"
MAX_CHAIN={max_chain}

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
echo "Chain        : $CHAIN_INDEX / $MAX_CHAIN"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "========================================"

mkdir -p logs

{module_line}
source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

# --force on every job in the chain: the recipe and span are identical each
# time (the resume path is baked in from the first export, deliberately, so
# the config hash never changes), so without it execute_recipe would reuse
# the previous job's partial run instead of continuing it.
python Pipelines/run_recipe/run_recipe.py --config {recipe_repo_path} --force

echo "========================================"
echo "Run finished : $(date)"

python Pipelines/window_matrix_build/wm_status.py --artifact {artifact_repo_path}
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
    echo ">>> Matrix complete -- chain finished."
elif [ "$STATUS" -ge 3 ]; then
    echo ">>> Could not read the artifact (exit $STATUS) -- stopping the chain."
    exit "$STATUS"
elif [ "$CHAIN_INDEX" -ge "$MAX_CHAIN" ]; then
    echo ">>> Work remains but the chain cap ($MAX_CHAIN) is reached -- stopping."
    echo ">>> Resubmit manually if this is expected: sbatch {script_repo_path} 1"
else
    NEXT=$((CHAIN_INDEX + 1))
    echo ">>> Work remains -- submitting job $NEXT of $MAX_CHAIN ..."
    sbatch {script_repo_path} "$NEXT"
    echo ">>> Submitted. Monitor with: squeue -u $USER"
fi

echo "Finished     : $(date)"
echo "========================================"
"""


def export_wm_job(conn, recording_id, window_min, span=None, *, step_frac=1.0,
                  stages=("catch22", "fast_entropy", "slow_entropy"),
                  est_seconds=None, timeout_s=None, max_chain=12,
                  cnn_model_dir="models", rf_model_path="",
                  out_dir=DEFAULT_WM_OUT_DIR, results_dir=None):
    """Generate a recipe JSON + resubmitting `sbatch` script for a
    `preprocessing.window_matrix` run of `window_min` minutes over
    `recording_id` (`span=None` means the whole channel).

    Named by config hash, so re-exporting the exact same job overwrites its
    own prior export rather than accumulating a new pair every time.

    `timeout_s` defaults to the SLURM wall clock minus a cleanup margin, so
    the builder saves a resumable partial artifact BEFORE SLURM kills the
    job. `wm_job.sh` gets this relationship right by hand today
    (`--time=00:20:00` against `--timeout 19`); deriving it here means it
    cannot drift.

    Returns `{"script_path", "recipe_path", "artifact_path", "sbatch_command",
    "job_name", "slurm_time", "timeout_s"}`. All paths are local/relative —
    see the module docstring for what still has to happen before
    `sbatch_command` can run anywhere.
    """
    # Imported here, not at module scope: `Working/` should not depend on
    # `Adapters/` at import time, and the artifact path is a property of the
    # STORAGE layer anyway — the adapter's `default_artifact_path` is a thin
    # wrapper over this same call.
    from Working.database import window_matrix_store as wm_store

    recording = q.get_recording_by_id(conn, recording_id)
    if recording is None:
        raise ValueError(f"No recording with id={recording_id}")

    slurm_time = _slurm_time_from_estimate(est_seconds)
    if timeout_s is None:
        hours, minutes, _sec = (int(p) for p in slurm_time.split(":"))
        # 5 minutes of cleanup margin: enough for the final npz write plus
        # the status check, and small relative to the 30-minute floor.
        timeout_s = max(60.0, (hours * 3600 + minutes * 60) - 300)

    artifact_path = os.path.join(
        results_dir or wm_store.DEFAULT_RESULTS_DIR,
        wm_store.artifact_name(os.path.splitext(recording["source_file"])[0],
                               recording["channel"], window_min, step_frac) + ".npz",
    )

    params = {
        "window_min": float(window_min),
        "step_frac": float(step_frac),
        "catch22": "catch22" in stages,
        "fast_entropy": "fast_entropy" in stages,
        "slow_entropy": "slow_entropy" in stages,
        "cnn": "cnn" in stages,
        "rf": "rf" in stages,
        "timeout_s": float(timeout_s),
        # Baked in from the FIRST export so every job in the chain hashes to
        # the same recipe -- see the adapter's module docstring.
        "resume_path": artifact_path.replace(os.sep, "/"),
        "cnn_model_dir": cnn_model_dir,
        "rf_model_path": rf_model_path,
    }
    recipe = make_recipe(recording_id, [
        {"stage": "preprocessing", "algorithm": "window_matrix", "params": params},
    ], span=span)
    _config_id, hash8 = get_or_create_config(conn, recipe)

    channel = recording["channel"]
    stem = os.path.splitext(recording["source_file"])[0]
    step_pct = int(round(step_frac * 100))
    base_name = f"wm_{stem}_CH{channel}_WIN{window_min:g}min_STEP{step_pct}pct_{hash8}"
    job_name = f"wm_CH{channel}_WIN{window_min:g}min"

    os.makedirs(out_dir, exist_ok=True)
    recipe_path = os.path.join(out_dir, f"{base_name}.json")
    with open(recipe_path, "w") as f:
        json.dump(recipe, f, indent=2)

    script_path = os.path.join(out_dir, f"{base_name}.sh")
    uses_gpu = "cnn" in stages
    script = _WM_SCRIPT_TEMPLATE.format(
        job_name=job_name, remote_root=HPC_REMOTE_REPO_ROOT, base_name=base_name,
        slurm_time=slurm_time, max_chain=int(max_chain),
        gpu_line=("#SBATCH --gres=gpu:a100\n#SBATCH --partition=gpu" if uses_gpu
                  else "# CPU-only build (no CNN stage) -- no GPU requested."),
        module_line=("module load cuda/12.2\n" if uses_gpu else ""),
        recipe_repo_path=recipe_path.replace(os.sep, "/"),
        script_repo_path=script_path.replace(os.sep, "/"),
        artifact_repo_path=artifact_path.replace(os.sep, "/"),
    )
    with open(script_path, "w") as f:
        f.write(script)

    return {
        "script_path": script_path, "recipe_path": recipe_path,
        "artifact_path": artifact_path,
        "sbatch_command": f"sbatch {script_path.replace(os.sep, '/')}",
        "job_name": job_name, "slurm_time": slurm_time, "timeout_s": timeout_s,
    }
