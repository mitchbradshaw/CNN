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

## Where does new code go?

A new job script goes in the stage folder matching its pipeline. If writing it
tempts you to add more than ~5 lines of Python, write a pipeline instead and
call that.
