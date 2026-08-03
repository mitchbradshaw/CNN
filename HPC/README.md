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
