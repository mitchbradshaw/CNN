# Pipelines/

**End-to-end runnable workflows.** Each pipeline composes several `Working/`
components — preprocessing + detection + cataloguing + comparison — into one
analysis. The orchestration logic lives here; the analysis logic does not.

Because a pipeline spans all four stages by definition, `Pipelines/` is **not**
split into the four stage subfolders. It is organised by workflow instead.

## Current pipelines

| Folder | Entry point | What it does | Invoked by |
|---|---|---|---|
| `dataset_build/` | `main.py` | Argparse CLI: scan / save / gramian-encode / label / subcategorise windows, plus frequency, entropy and feature histograms | run by hand |
| `window_matrix_build/` | `build_window_matrix.py` | Builds the full window matrix over a recording — Catch22, entropy, CNN and RF columns — with checkpoint/resume so it survives HPC time limits | `HPC/Preprocessing/wm_job.sh` |
| `cnn_scoring/` | `score_windows.py` | Scores every consecutive window with a trained fusion CNN, writes a WindowMatrix CSV | `HPC/Catalogue/score_job.sh` |
| `fusion_prediction/` | `cnn_prediction.py` | Bins the post-window signal change and builds the `fusion_prediction/` image dataset for the prediction CNN | `HPC/Preprocessing/sort_fusion_job.sh` |
| `matrix_profile/` | `run_matrix_profile.py` | Computes the stumpy matrix profile (GPU `gpu_stump`, CPU fallback) and saves `.npz` to `Results/` | `HPC/Detection/mp_job.sh` |

## Rules

- **Import from `Working/`, don't reimplement.** If a pipeline grows a function
  that another pipeline would want, move it into `Working/` and import it.
- **Every pipeline is runnable from the repo root**, with a repo-root bootstrap
  so `python Pipelines/<name>/<entry>.py` works directly.
- **Take configuration as arguments,** not module-level constants, wherever the
  HPC job scripts need to vary it — that is what keeps `HPC/` thin.

## Where does new code go?

A new pipeline gets its own folder here when it is a *distinct analysis you
would want to re-run*. If you are still figuring out whether it works, it
belongs in `Experimentation/` until it settles.
