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

from Working.config import CLUSTER_ROUTING_CEILING_S, HPC_REMOTE_REPO_ROOT
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


class _Span:
    """Lightweight stand-in for a signal array so an adapter's `estimate`
    can be evaluated for a span without materialising the array. Only `len`
    (and `shape`/`size`) are guaranteed -- the two estimators this module
    knows about need no more than the span length and `fs`."""

    def __init__(self, n):
        self._n = int(n)
        self.shape = (self._n,)
        self.size = self._n

    def __len__(self):
        return self._n


def estimate_recipe_seconds(recipe, n_samples, fs):
    """Sum of per-step runtime estimates for a recipe over a span of
    `n_samples` at `fs`, multiplied by fan-out width (PRD "Cluster routing").

    A step whose adapter declares no `estimate` contributes zero -- "Blocks
    without an estimator count as free". An estimator that returns `None`
    (uncalibrated on this machine) also contributes zero, matching the cost
    modules' never-guess contract; callers that need to distinguish "unknown"
    from "cheap" should use `route_recipe`, which reports the former.
    """
    from Adapters.registry import get_adapter

    total = 0.0
    for step in recipe["steps"]:
        spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
        est = spec.estimate
        if est is None:
            continue
        value = est(_Span(n_samples), None, fs, **step["params"])
        if value is not None:
            total += float(value)
    fan = recipe.get("fan_out")
    if fan:
        total *= len(fan["targets"])
    return total


def route_recipe(recipe, n_samples, fs, ceiling_s=CLUSTER_ROUTING_CEILING_S):
    """Where a recipe should run: `'cluster'` | `'local'` | `'unknown'`.

    `'cluster'` when the summed per-step estimate (times fan-out width)
    exceeds `ceiling_s`. `'unknown'` when any step's estimator is present but
    uncalibrated (returns `None`) -- the sum is then a lower bound, and
    routing on it could send a long job to the local path. Otherwise
    `'local'`.

    The value is a headless string a run surface reads to promote "export
    cluster job" to the primary action (PRD "Cluster routing") -- not a UI
    behaviour buried in a widget callback.
    """
    from Adapters.registry import get_adapter

    total = 0.0
    any_unknown = False
    for step in recipe["steps"]:
        spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
        est = spec.estimate
        if est is None:
            continue
        value = est(_Span(n_samples), None, fs, **step["params"])
        if value is None:
            any_unknown = True
        else:
            total += float(value)
    fan = recipe.get("fan_out")
    if fan:
        total *= len(fan["targets"])
    if any_unknown:
        # Even the known part exceeding the ceiling is enough to be certain.
        return "cluster" if total > ceiling_s else "unknown"
    return "cluster" if total > ceiling_s else "local"


_SCRIPT_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --chdir={remote_root}
#SBATCH --output={remote_root}/logs/{base_name}_%j.out
#SBATCH --error={remote_root}/logs/{base_name}_%j.err
#SBATCH --time={slurm_time}
#SBATCH --gres=gpu:a100
#SBATCH --cpus-per-task=4
{array_line}

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

{run_command}

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
"""


def _materialize_snippet(recipe_repo_path, per_target_repo_path):
    """Bash snippet that materialises this array task's per-target recipe
    from the fan-out list baked into the recipe JSON, then runs it.

    The per-target recipe is written by `Working.run_groups.materialize_target`
    (the same function `fan_out_recipe` uses locally), so the cluster path and
    the local path cannot drift on what a task index means.
    """
    return (
        "# Materialise this array task's per-target recipe from the fan-out\n"
        "# list baked into the recipe JSON.\n"
        f"python - {recipe_repo_path} \"$SLURM_ARRAY_TASK_ID\" {per_target_repo_path} <<'PY'\n"
        "import json, sys\n"
        "from Working.run_groups import materialize_target\n"
        "recipe_path, task_id, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
        "with open(recipe_path) as f:\n"
        "    recipe = json.load(f)\n"
        "with open(out_path, \"w\") as f:\n"
        "    json.dump(materialize_target(recipe, task_id), f)\n"
        "PY\n"
    )


def export_job(recipe, *, out_dir, base_name, job_name, est_seconds=None,
               slurm_time=None, resumable=False, max_chain=12, uses_gpu=True,
               artifact_repo_path=None, timeout_s=None):
    """Write a recipe JSON + `sbatch` script for an arbitrary recipe.

    This is the single generic exporter both `export_mp_job` and
    `export_wm_job` now wrap. If `recipe` carries a `fan_out` scope, it
    exports a SINGLE SLURM array job whose task index selects its target from
    the recipe's baked-in list (via `Working.run_groups.materialize_target`).

    `resumable=True` uses the window-matrix chain template (resubmits on an
    incomplete build) and requires `artifact_repo_path`; `uses_gpu` toggles
    the GPU directive/module for that template.

    Returns `{"script_path", "recipe_path", "artifact_path", "sbatch_command",
    "job_name", "slurm_time", "timeout_s"}`.
    """
    if slurm_time is None:
        slurm_time = _slurm_time_from_estimate(est_seconds)

    os.makedirs(out_dir, exist_ok=True)
    recipe_path = os.path.join(out_dir, f"{base_name}.json")
    with open(recipe_path, "w") as f:
        json.dump(recipe, f, indent=2)

    # The paths baked into the script are REPO-RELATIVE (forward slashes,
    # regardless of the OS this was generated on) -- the job's own `--chdir`
    # puts it at HPC_REMOTE_REPO_ROOT, so a relative path here is what
    # resolves correctly once the generated pair is synced across to the
    # cluster at the same relative location.
    recipe_repo_path = recipe_path.replace(os.sep, "/")
    script_path = os.path.join(out_dir, f"{base_name}.sh")
    script_repo_path = script_path.replace(os.sep, "/")

    fan = recipe.get("fan_out")
    n_targets = len(fan["targets"]) if fan else 0
    array_line = f"#SBATCH --array=0-{n_targets - 1}" if fan else ""
    # The per-target recipe each array task writes sits next to the shared
    # fan-out recipe, named by task index so parallel tasks never collide.
    per_target_repo_path = os.path.join(
        out_dir, f"{base_name}_task$SLURM_ARRAY_TASK_ID.json",
    ).replace(os.sep, "/")

    if resumable:
        materialize = _materialize_snippet(recipe_repo_path, per_target_repo_path) if fan else ""
        run_command = (
            materialize
            + f"python Pipelines/run_recipe/run_recipe.py --config "
              f"{per_target_repo_path if fan else recipe_repo_path} --force"
        )
        resubmit_line = (
            f"sbatch --array=$SLURM_ARRAY_TASK_ID {script_repo_path} \"$NEXT\""
            if fan else f"sbatch {script_repo_path} \"$NEXT\""
        )
        manual_resubmit_line = (
            f"sbatch --array=$SLURM_ARRAY_TASK_ID {script_repo_path} 1"
            if fan else f"sbatch {script_repo_path} 1"
        )
        script = _WM_SCRIPT_TEMPLATE.format(
            job_name=job_name, remote_root=HPC_REMOTE_REPO_ROOT, base_name=base_name,
            slurm_time=slurm_time, max_chain=int(max_chain),
            gpu_line=("#SBATCH --gres=gpu:a100\n#SBATCH --partition=gpu" if uses_gpu
                      else "# CPU-only build (no CNN stage) -- no GPU requested."),
            module_line=("module load cuda/12.2\n" if uses_gpu else ""),
            artifact_repo_path=artifact_repo_path,
            array_line=array_line,
            run_command=run_command,
            resubmit_line=resubmit_line,
            manual_resubmit_line=manual_resubmit_line,
        )
    else:
        materialize = _materialize_snippet(recipe_repo_path, per_target_repo_path) if fan else ""
        run_command = (
            materialize
            + f"python Pipelines/run_recipe/run_recipe.py --config "
              f"{per_target_repo_path if fan else recipe_repo_path}"
        )
        script = _SCRIPT_TEMPLATE.format(
            job_name=job_name, remote_root=HPC_REMOTE_REPO_ROOT, base_name=base_name,
            slurm_time=slurm_time, array_line=array_line, run_command=run_command,
        )
    with open(script_path, "w") as f:
        f.write(script)

    return {
        "script_path": script_path, "recipe_path": recipe_path,
        "artifact_path": artifact_repo_path,
        "sbatch_command": f"sbatch {script_repo_path}",
        "job_name": job_name, "slurm_time": slurm_time, "timeout_s": timeout_s,
    }


def export_mp_job(conn, recording_id, window_min, span=None, *,
                   est_seconds=None, backend="auto", out_dir=DEFAULT_OUT_DIR,
                   fan_out=None):
    """Generate a recipe JSON + `sbatch` script for a
    `detection.matrix_profile` run of `window_min` minutes over
    `recording_id` (`span=None` means the whole channel).

    `fan_out` is an optional `{"kind": "channels"|"bands", "targets": [...]}`
    scope; when present the recipe is exported as a SINGLE SLURM array job
    whose task index selects its target from the baked-in list.

    Named by config hash (`{base_name}.json` / `.sh`), so re-exporting the
    exact same job overwrites its own prior export rather than
    accumulating a new pair every time.

    Returns `{"script_path", "recipe_path", "sbatch_command", "job_name",
    "slurm_time", "timeout_s", "artifact_path"}` (all paths
    local/relative — see module docstring for what still needs to happen
    before `sbatch_command` can actually run anywhere).
    """
    recording = q.get_recording_by_id(conn, recording_id)
    if recording is None:
        raise ValueError(f"No recording with id={recording_id}")

    recipe = make_recipe(recording_id, [
        {"stage": "detection", "algorithm": "matrix_profile",
         "params": {"window_min": float(window_min), "backend": backend}},
    ], span=span, fan_out=fan_out)
    _config_id, hash8 = get_or_create_config(conn, recipe)

    channel = recording["channel"]
    stem = os.path.splitext(recording["source_file"])[0]
    base_name = f"mp_{stem}_CH{channel}_WIN{window_min:g}min_{hash8}"
    job_name = f"mp_CH{channel}_WIN{window_min:g}min"

    return export_job(
        recipe, out_dir=out_dir, base_name=base_name, job_name=job_name,
        est_seconds=est_seconds, resumable=False, uses_gpu=True,
    )


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
{array_line}
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
{run_command}

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
    echo ">>> Resubmit manually if this is expected: {manual_resubmit_line}"
else
    NEXT=$((CHAIN_INDEX + 1))
    echo ">>> Work remains -- submitting job $NEXT of $MAX_CHAIN ..."
    {resubmit_line}
    echo ">>> Submitted. Monitor with: squeue -u $USER"
fi

echo "Finished     : $(date)"
echo "========================================"
"""


def export_wm_job(conn, recording_id, window_min, span=None, *, step_frac=1.0,
                  stages=("catch22", "fast_entropy", "slow_entropy"),
                  est_seconds=None, timeout_s=None, max_chain=12,
                  cnn_model_dir="models", rf_model_path="",
                  out_dir=DEFAULT_WM_OUT_DIR, results_dir=None, fan_out=None):
    """Generate a recipe JSON + resubmitting `sbatch` script for a
    `preprocessing.window_matrix` run of `window_min` minutes over
    `recording_id` (`span=None` means the whole channel).

    `fan_out` is an optional `{"kind": "channels"|"bands", "targets": [...]}`
    scope; when present the recipe is exported as a SINGLE SLURM array job
    whose task index selects its target from the baked-in list. NOTE: the
    chain script's `wm_status --artifact` path is derived from the BASE
    recording, so a multi-target fan-out should be verified against each
    target's actual artifact path before submission.

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
    ], span=span, fan_out=fan_out)
    _config_id, hash8 = get_or_create_config(conn, recipe)

    channel = recording["channel"]
    stem = os.path.splitext(recording["source_file"])[0]
    step_pct = int(round(step_frac * 100))
    base_name = f"wm_{stem}_CH{channel}_WIN{window_min:g}min_STEP{step_pct}pct_{hash8}"
    job_name = f"wm_CH{channel}_WIN{window_min:g}min"

    return export_job(
        recipe, out_dir=out_dir, base_name=base_name, job_name=job_name,
        est_seconds=est_seconds, slurm_time=slurm_time, resumable=True,
        max_chain=max_chain, uses_gpu="cnn" in stages,
        artifact_repo_path=artifact_path.replace(os.sep, "/"),
        timeout_s=timeout_s,
    )
