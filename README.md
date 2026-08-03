# CNN

Thesis codebase for analysing **mycelium bio-electric time-series signals** —
long, slow, low-amplitude electrical recordings from fungal substrate, sampled
at 1–2 Hz over hundreds of hours.

The central question is whether these recordings contain structure that is
distinguishable from drift and noise: recurring motifs, spikes, regime changes,
and whether "interesting" activity can be detected automatically rather than by
eye.

---

## Repository layout

Four code areas. `Working/`, `Experimentation/` and `HPC/` each use the same
four subfolders, reflecting **pipeline stage** rather than technique:
`Preprocessing` → `Detection` → `Catalogue` → `Comparison`.

| Directory | Purpose |
|---|---|
| [`Working/`](Working/README.md) | Stable, reusable, importable libraries. Other code depends on these. |
| [`Pipelines/`](Pipelines/README.md) | End-to-end workflows composing several `Working/` components. Organised by workflow, not stage. |
| [`Experimentation/`](Experimentation/README.md) | Exploratory and one-off analysis. Not guaranteed to work. Never imported. |
| [`HPC/`](HPC/README.md) | Thin SLURM job scripts that invoke a `Pipelines/` entry point. |
| [`UI/`](UI/README.md) | Panel/HoloViews signal viewer and annotation tool. The only place that imports a UI library. |
| [`DATA/`](DATA/README.md) | Recordings and derived datasets (~2.3 GB, gitignored). |
| [`Results/`](Results/README.md) | Run outputs, by stage. |
| [`Plots/`](Plots/README.md) | Saved figures, by stage (gitignored). |
| `MATRICES/`, `MODELS/` | Feature CSVs and trained models (gitignored). |
| `Reference/matlab/` | Third-party cSAX/pSAX MATLAB implementations, vendored with their licences. |
| `tests/` | Automated tests (`195` currently passing). |

---

## Getting started

### 1. Environment

Python 3.13. There is no lockfile yet — install what the stage you need
requires:

```bash
# core (everything needs these)
pip install numpy scipy pandas matplotlib

# detection
pip install stumpy ruptures kymatio aeon scikit-learn

# catalogue / CNN
pip install torch torchvision scikit-image pillow joblib

# only Working/Catalogue/cnn/cnn_gfg.py needs this
pip install tensorflow

# UI/ — signal viewer and annotation tool (never needed by Working/ or Pipelines/)
pip install panel holoviews datashader bokeh h5py
```

### 2. Data

`DATA/` is gitignored and not distributed with the repo — see
[`DATA/README.md`](DATA/README.md) for the expected layout. At minimum you need
one recording in `DATA/raw/`. Per-channel `.npy` splits and window datasets are
derived from it.

### 3. Run things from the repo root

Stage folders under `Working/` and `Pipelines/` are Python packages, so imports
are fully qualified:

```python
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Catalogue.gramian.gramian_calc import compute_fusion
```

Scripts you execute directly carry a bootstrap that walks up to the directory
containing `Working/`, so no `PYTHONPATH` is needed:

```bash
python tests/test_analysis_modules.py                     # 195 tests, ~1 min
python Pipelines/dataset_build/main.py -h                 # the main CLI
python "Experimentation/Detection experiments/rupture_testing.py"
sbatch HPC/Preprocessing/wm_job.sh                        # on the cluster
```

### 4. A typical session

```bash
# label windows interactively (arrow keys + 1/2/3), writes to DATA/derived/windows/
python Pipelines/dataset_build/main.py -select --timescale=10

# encode labelled windows as GASF/GADF/recurrence/fusion images
python Pipelines/dataset_build/main.py -gram --timescale=10

# compare feature distributions between the two classes
python Pipelines/dataset_build/main.py -freq -entropy -stats

# build a full feature matrix over a recording (resumable; designed for HPC)
python Pipelines/window_matrix_build/build_window_matrix.py --status
```

### 5. Database / annotation UI

Per-channel `.npy` splits and manually-sorted labels also live in a SQLite
database (`DATA/db/annotations.sqlite`, gitignored), queried through plain
functions in [`Working/Preprocessing/database/`](Working/Preprocessing/database)
so both the UI and headless scripts share one API:

```bash
# one-time: extract DATA/raw/*.mat into per-channel .npy + `recordings` rows
python Pipelines/materialize_channels/materialize_channels.py

# import the ~11k manually-sorted 10-minute windows as annotations
python Pipelines/import_labels/import_10min_labels.py

# browse a channel, see existing labels, and add new ones
panel serve UI/app.py --show
```

See [`UI/README.md`](UI/README.md) for the viewer, and the `database`
module's docstrings for the schema (`recordings`, `reviewed_spans`,
`annotations` are populated now; `configs`, `runs`, `detections`,
`encodings`, `motifs` exist for the next phase — algorithm runs, cached
encodings — so it needs no migration).

The **`WindowMatrix`** ([`Working/Preprocessing/window_matrix/matrix_calc.py`](Working/Preprocessing/window_matrix/matrix_calc.py))
is the object most analysis flows through: rows are windows keyed by start
sample index, columns are features added incrementally. Populated matrices in
`MATRICES/` currently carry ~60 columns — CNN scores for four encodings, SAX
symbol strings, six entropies and all 22 Catch22 features.

---

## Techniques and progress

Status is honest: **mature** = quantified and reproducible, **working** = runs
and produces sensible output but not systematically evaluated, **early** =
implemented and demonstrated only.

### Preprocessing

| Technique | Status | Notes |
|---|---|---|
| Windowing / `WindowMatrix` | **mature** | Consecutive and overlapping windows, incremental feature columns, CSV round-trip, checkpoint/resume for long HPC builds |
| Per-channel splitting | **mature** | 16 channels per recording, 4 recordings |
| Interactive labelling | **mature** | **2,183 interesting / 8,138 not-interesting** 10-min windows at fs=1 Hz, plus 135/576 held out as a test split |
| Subcategorisation | **working** | Interesting windows further sorted into clear / average / noisy / vague |

### Detection

| Technique | Status | Notes |
|---|---|---|
| Matrix profiling (stumpy) | **mature** | GPU `gpu_stump` with CPU fallback. Runs completed at 1, 5, 34, 50-minute windows across channels 0, 2, 13. Motif, discord and seeded-chain discovery all working |
| Spike detection — Dehshibi & Adamatzky (2021) | **mature** | Full implementation: histogram slicing, Morse-wavelet ROI detection, analytic-envelope refinement, spike/pseudo-spike classification, and all eight complexity measures (Shannon, Simpson, space-filling, expressiveness, Lempel-Ziv, Kolmogorov, PCI) |
| Spike detection — Adamatzky (2023) | **working** | Simpler neighbourhood-average method with refractory filter |
| Entropy | **mature** | Shannon, sample, approximate, permutation, SVD, spectral — all as window-matrix columns |
| Frequency / STFT | **mature** | Log-spaced frequency binning; per-window power vectors |
| Catch22 (aeon) | **mature** | All 22 features as matrix columns; feature pruning implemented |
| SAX symbolisation | **working** | cSAX (mean-shift) and pSAX (KDE + Lloyd-Max), both per-window and whole-dataset. Python ports of the MATLAB references in `Reference/matlab/` |
| Wavelet scattering (kymatio) | **early** | `Scattering1D`, numpy backend. Implemented with scalogram plotting; not yet swept or fed into classification |
| Change-point detection (ruptures) | **early** | Pelt/Binseg with l2/rbf costs. Demonstrated; penalty selection not yet resolved (no dataset-independent correct value — see the module docstring) |

### Catalogue / Classification

| Technique | Status | Result |
|---|---|---|
| Gramian encoding | **mature** | GASF, GADF, recurrence and RGB fusion images from each window |
| CNN (EfficientNet-B0 transfer) | **working** | Trained per encoding — `GASF_cnn.pth`, `GADF_cnn.pth`, `recurrence_cnn.pth`, `fusion_cnn{,_2,_3}.pth`. Per-encoding accuracy not yet written up here |
| **Catch22 + Balanced RandomForest** | **mature** | **Best quantified classifier.** On the held-out split (135 interesting / 576 not): accuracy **0.878**, balanced accuracy **0.788**, AUC-ROC **0.941**, AUC-PR **0.773**. Interesting-class precision 0.69 / recall 0.64 |
| ↳ threshold optimisation | **mature** | PR sweep moves the operating point to **F1 0.743 at t=0.40** (precision 0.677, recall 0.822) — a large recall gain over the default 0.5 threshold |
| Fusion-prediction CNN | **early** | Predicts which bin the next-sample change falls into. Trained (`fusion_prediction_cnn.pth`); the dataset-build call in the pipeline is currently commented out |
| Hierarchical / dendrogram clustering | **working** | Linkage, silhouette sweeps, cluster browsing, outlier detection. Explored at k=2–8; no settled cluster count |
| KNN + DTW baseline | **mature (negative result)** | accuracy 0.825 but balanced accuracy **0.458** and **F1 = 0.00** on the interesting class — it predicts the majority class. Recorded as a baseline that does not work |

### Comparison

| Technique | Status | Notes |
|---|---|---|
| Per-category distributions | **working** | Feature, frequency and STFT log-power distributions compared between interesting and not-interesting |
| Threshold / PR sweeps | **mature** | Implemented in `aeon_classification/classification.py` |
| CNN scoring CLI | **working** | `Working/Comparison/test_cnn.py` |
| SAX MINDIST comparison | **not started** | Encoders exist; the distance-based comparison does not |
| Cross-method / cross-scale validation | **not started** | Nothing yet compares matrix-profile motifs against change points against CNN scores on the same windows |

---

## Known limitations

- **Class imbalance is ~1:3.7** (2,183 vs 8,138). Every classifier here trades
  recall on the interesting class for overall accuracy. Balanced accuracy and
  AUC-PR are the honest metrics; plain accuracy is not.
- **Comparison is the least-developed stage.** It has one stable module. The
  cross-method validation that would tie the detection techniques together is
  the main outstanding work.
- **Three aeon pipelines fail** (`detect_anomaly`, `clustering_kmeans`,
  `sim_search`) — see `Results/Catalogue/aeon/current/pipeline_summary.txt`.
- **Labels are single-rater and subjective.** "Interesting" was assigned by eye
  through the interactive labeller; there is no inter-rater agreement measure.
- **No dependency lockfile**, and the HPC scripts hardcode one cluster account.

## Two things not to break

1. **`DATA/derived/windows/<scale>_fs<fs>/<encoding>/` is a torchvision
   `ImageFolder` root.** Class indices are alphabetical — `interesting=0`,
   `notinteresting=1` — and that ordering is hardcoded in `apply_cnn.py` and
   baked into every model in `MODELS/`. See [`DATA/README.md`](DATA/README.md).

2. **No analysis logic in `.sh` files.** HPC scripts set up the environment and
   call a pipeline. See [`HPC/README.md`](HPC/README.md).
