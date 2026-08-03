# CNN

Thesis codebase for analysing mycelium bio-electric time-series signals.

## Layout

Four code areas. `Working/`, `Experimentation/` and `HPC/` each use the same
four subfolders, reflecting **pipeline stage** rather than technique:
`Preprocessing` → `Detection` → `Catalogue` → `Comparison`.

| Directory | Purpose |
|---|---|
| [`Working/`](Working/README.md) | Stable, reusable, importable libraries. Other code depends on these. |
| [`Pipelines/`](Pipelines/README.md) | End-to-end workflows composing several `Working/` components. Organised by workflow, not stage. |
| [`Experimentation/`](Experimentation/README.md) | Exploratory and one-off analysis. Not guaranteed to work. Never imported. |
| [`HPC/`](HPC/README.md) | Thin SLURM job scripts that invoke a `Pipelines/` entry point. |
| [`DATA/`](DATA/README.md) | Recordings and derived datasets (~2.3 GB, gitignored). |
| [`Results/`](Results/README.md) | Run outputs, by stage. |
| `Reference/matlab/` | Third-party cSAX/pSAX MATLAB implementations, vendored with their licences. |
| `tests/` | Automated tests. |
| `MATRICES/`, `MODELS/`, `Plots/` | Output dirs that stayed at the root — see [`Results/README.md`](Results/README.md). |

## Running anything

**Run from the repo root.** Stage folders under `Working/` and `Pipelines/` are
Python packages, so imports are fully qualified:

```python
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Catalogue.gramian.gramian_calc import compute_fusion
```

Scripts you execute directly carry a bootstrap that walks up to the directory
containing `Working/` and puts it on `sys.path`, so this works without setting
`PYTHONPATH`:

```bash
python Pipelines/dataset_build/main.py -h
python "Experimentation/Detection experiments/rupture_testing.py"
python tests/test_analysis_modules.py
sbatch HPC/Preprocessing/wm_job.sh
```

## Two things not to break

1. **`DATA/derived/windows/<scale>_fs<fs>/<encoding>/` is a torchvision
   `ImageFolder` root.** Class indices are alphabetical — `interesting=0`,
   `notinteresting=1` — and that ordering is hardcoded in `apply_cnn.py` and
   baked into every model in `MODELS/`. See [`DATA/README.md`](DATA/README.md).

2. **No analysis logic in `.sh` files.** HPC scripts set up the environment and
   call a pipeline. See [`HPC/README.md`](HPC/README.md).
