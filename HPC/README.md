# HPC/

**SLURM submission scripts and cluster-specific setup.** These are deliberately
**thin**: a job script loads modules, activates the conda environment, logs the
node/GPU it got, and then invokes a `Pipelines/` (or `Working/`) entry point.

**No analysis logic lives in a `.sh` file.** If you find yourself writing
`python - <<'PYEOF'`, stop — that code belongs in `Pipelines/`. This exact thing
had happened in `score_job.sh`; its embedded pipeline is now
`Pipelines/cnn_scoring/score_windows.py` and the job script just calls it.

## The four stages

Same four subfolders as `Working/` and `Experimentation/`, filed by what the job
*does*, not what hardware it asks for.

| Script | Stage | Invokes |
|---|---|---|
| `Preprocessing/wm_job.sh` | Preprocessing | `Pipelines/window_matrix_build/build_window_matrix.py` |
| `Preprocessing/sort_fusion_job.sh` | Preprocessing | `Pipelines/fusion_prediction/cnn_prediction.py` |
| `Detection/mp_job.sh` | Detection | `Pipelines/matrix_profile/run_matrix_profile.py` |
| `Catalogue/train_job.sh` | Catalogue | `Working.Catalogue.cnn.cnn_rangapur` (as `-m`) |
| `Catalogue/train_fusion_prediction_job.sh` | Catalogue | `Working.Catalogue.cnn.cnn_fusion_prediction` (as `-m`) |
| `Catalogue/score_job.sh` | Catalogue | `Pipelines/cnn_scoring/score_windows.py` |

## Submitting

All scripts assume **the repo root as working directory** and are submitted by
path from there:

```bash
sbatch HPC/Preprocessing/wm_job.sh
sbatch HPC/Catalogue/train_job.sh
```

`wm_job.sh` resubmits itself until every stage of the window matrix is complete;
cancel the chain with `scancel <job-id>`.

> **`wm_job.sh` can resubmit forever.** It decides whether to requeue by grepping
> `build_window_matrix.py --status` for `"not started"` or an `"N / M"` fraction.
> That script marks a window whose feature function raised with NaN, and treats
> NaN as "not yet computed" — so one reliably-failing window is never finished,
> the status string never says DONE, and the chain requeues until someone
> notices. See `WINDOW_MATRIX_UI_PROMPT.md` §0.2.
>
> Generated window-matrix jobs (below) do not have this behaviour: they resubmit
> on `Pipelines/window_matrix_build/wm_status.py`'s **exit code**, derived from
> the artifact's own per-cell `computed` mask, and they carry a hard chain cap.

## Generated jobs

`Working/hpc/job_export.py` writes job scripts + recipe JSONs for spans too large
to run in the UI. They are **generated into the working tree only** — like the
hand-written scripts, they still have to reach rangpur before `sbatch` can run
them.

| Function | Output directory | Invokes |
|---|---|---|
| `export_mp_job` | `Detection/generated/` | `Pipelines/run_recipe/run_recipe.py --config …` |
| `export_wm_job` | `Preprocessing/generated/` | `Pipelines/run_recipe/run_recipe.py --config … --force` |

Both go through `run_recipe.py` rather than a stage-specific script, so the
cluster run registers its own `runs`/`artifacts` rows and the returned artifact
appears in the UI with no separate import step.

Generated window-matrix jobs take a chain position as `$1` (defaulting to 1) and
pass `--force`, because `execute_recipe` short-circuits on a completed run for
the same recipe and span — without it a resuming job would "reuse" the partial
matrix instead of continuing it. The resume path is baked into the recipe from
the first export, deliberately, so every job in the chain shares one config hash.

## Cluster-specific settings you will need to change

These are hardcoded to one account and cluster and are **not** portable:

- `#SBATCH --chdir=` — currently `/home/s4699158/CNN` in `score_job.sh` and
  `/home/Student/s4699158/CNN` in `wm_job.sh` and `mp_job.sh`. These two paths
  disagree; confirm which is right for your account before submitting.
- `#SBATCH --mail-user=` — `s4699158@rangpur.compute.eait.uq.edu.au`
- `module load cuda/…` — versions vary (12.1 in `train_job.sh`, 12.2 elsewhere)
- `conda activate torch_env` and `source ~/miniconda3/…`
- `#SBATCH --partition=gpu` — **confirmed wrong** (see below), and every
  hand-written script (`mp_job.sh`, `train_job.sh`, `score_job.sh`,
  `train_fusion_prediction_job.sh`, `sort_fusion_job.sh`) still hardcodes it.
  Only the generated window-matrix path (`Working/hpc/job_export.py`) has
  been fixed so far, because that's what this session's actual work needed —
  the hand-written scripts are still broken as checked in. Fix each the same
  way: real partition names below, not a guess.

## Confirmed account constraints (rangpur, s4699158)

Unlike the settings above, these are not "confirm before submitting" guesses —
they were hit and fixed in session (2026-08-31), so treat them as load-bearing:

- **`--partition=gpu` does not exist on this cluster.**
  `sbatch: error: invalid partition specified: gpu` — almost certainly stale
  from before the reconfiguration the login banner warns about ("NOTE: The
  resource allocations and partitions have been reconfigured"). Real
  partitions, from `sinfo -o "%P %a %l %D %G %f"` against the live account:

  | Partition | Nodes | GRES | Notes |
  |---|---|---|---|
  | `cpu` | 4 | none | general CPU work — `Working.config.HPC_CPU_PARTITION` |
  | `largecpu`, `cpu-grind`, `largecpu-grind` | 4–5 | none | other CPU tiers, untested by this session |
  | `a100` | 10 | `gpu:a100:1` each | general GPU work — `Working.config.HPC_GPU_PARTITION` |
  | `a100-test` *(account default)* | 2 | `gpu:a100:1` + shards | `QoS=test`; what a job lands on with **no** `--partition` at all. 2 nodes / 2 total A100s, department-shared — not where a stat-only or production job belongs |
  | `p100`, `p100-grind`, `a100-grind` | 1–10 | `gpu:p100:4` / `gpu:a100:1` | not used by this repo yet |
  | `cosc3500`, `comp3710`, `kaleen`, `cpu10` | — | — | course/project-scoped; likely not usable by this account |

  A CPU-only window-matrix build (no `cnn` stage) now requests
  `--partition=cpu` with **no** `--gres` line — `cpu`'s own GRES is
  `(null)`, so asking it for a GPU is a second wrong constraint on top of a
  first. A CNN-stage build requests `--partition=a100` + `--gres=gpu:a100`.
  If a future `sbatch` ever again says `invalid partition specified`, re-run
  the `sinfo` command above before guessing a replacement — two guesses
  (`gpu` outright, then `--partition=gpu` without `--gres`) both failed
  against the live account before this table was pulled from `sinfo` directly.
- **`--time` cannot exceed 20 minutes on `a100-test`.** This account's
  `QoS=test` (tied to that partition, confirmed via
  `scontrol show partition a100-test`: `MaxTime=UNLIMITED` at the partition
  level, so the ceiling lives in the QOS, not the partition) rejects
  submission outright above that wall-clock
  (`sbatch: error: QOSMaxWallDurationPerJobLimit`). `wm_job.sh`'s hardcoded
  `--time=00:20:00` was already respecting this; `Working/hpc/job_export.py`'s
  generated jobs now do too — `_slurm_time_from_estimate` clamps every
  computed `--time` to `Working.config.HPC_MAX_WALLTIME_MINUTES` (20), so the
  §5 estimate-scaling formula's own 30-minute floor is currently unreachable
  in practice. **Unverified**: whether `cpu` (now the actual partition for
  stat-only WM jobs) carries the same 20-minute ceiling or a different QOS
  entirely — the clamp is kept as a conservative floor rather than assumed
  lifted; raise `HPC_MAX_WALLTIME_MINUTES` only after confirming `cpu`'s own
  QOS (`sacctmgr show qos`) or a longer job actually succeeding there.
- **Do not set `--mem=` at all for the WM template.** Two explicit values
  were both rejected outright with `sbatch: error: Memory specification can
  not be satisfied` on `HPC_CPU_PARTITION` (2026-08-31): `16G` (the
  a100-test-sized default every earlier version of the template carried
  unmodified) and `4G` (a measurement-informed reduction — still wrong).
  Per prior experience with this exact error on this account, and matching
  the official Rangpur guide's own working example (which never sets
  `--mem` either), the fix was to drop the directive entirely and let the
  scheduler assign its own default — not to keep guessing at a number.
  Generated WM scripts (both CPU-only and GPU/CNN) now carry no `--mem=`
  line at all.
- **`conda activate torch_env` doesn't have `aeon`.** Confirmed 2026-08-31
  by an actual run on `HPC_CPU_PARTITION` that got past every scheduling
  problem above and then failed with `No module named 'aeon'`. `torch_env`
  is a GPU/CNN environment (torch + CUDA); this account has a separate
  `aeon-env` for the catch22/entropy stack a stat-only build needs.
  Generated WM scripts now activate `Working.config.HPC_CONDA_ENV_CPU`
  (`aeon-env`) for a CPU-only build and `HPC_CONDA_ENV_GPU` (`torch_env`)
  for a CNN-stage one. Not yet checked whether `aeon-env` also has
  everything `run_recipe.py`'s own imports need beyond `aeon` itself
  (`numpy`/`pandas` etc.) — if a *different* `ModuleNotFoundError` shows up
  next, that's the first thing to check.
- **Generated scripts must use LF line endings, not CRLF.** `sbatch` rejects
  a script outright with `"Batch script contains DOS line breaks"`. On
  Windows (this repo's dev environment), Python's default text-mode file
  write silently turns every `\n` into `\r\n`; `export_job` in
  `Working/hpc/job_export.py` now opens the script file with `newline="\n"`
  to prevent that. If you ever hand-edit a generated `.sh` (or write a new
  hand-written one) from a Windows editor, check its line endings before
  transferring it — this fix only covers files written by `export_job`.

## Where does new code go?

A new job script goes in the stage folder matching its pipeline. If writing it
tempts you to add more than ~5 lines of Python, write a pipeline instead and
call that.
