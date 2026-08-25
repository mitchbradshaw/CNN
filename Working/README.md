# Working/

**Stable, reusable, importable code.** Everything here is a library other parts
of the repo depend on. If you change something in `Working/`, assume something
else breaks — check `Pipelines/` and `Experimentation/` before you do.

Nothing here should execute analysis at import time. Demos belong behind
`if __name__ == "__main__":`.

## The four stages

Every one of `Working/`, `Experimentation/` and `HPC/` uses the same four
subfolders, which reflect **where you are in the analysis**, not which library
or technique you used.

| Stage | What belongs here |
|---|---|
| `Preprocessing/` | Loading, cleaning, windowing, resampling, detrending, smoothing, channel selection, data management |
| `Detection/` | Anything that *finds candidate structure*: matrix profiling, change-point detection, wavelet scattering, spike detection, ratio/SAX discovery, entropy/frequency-based detection |
| `Catalogue/` | Anything that *groups or labels detected structure*: clustering, CNN classification, Gramian/recurrence image encoding used for classification |
| `Comparison/` | Anything that *compares structures or methods*: SAX MINDIST-style comparison, cross-method or cross-scale validation, evaluation/scoring |

## Layout

```
recipes.py         The recipe: {recording_id, span, steps}. Canonical-JSON
                    SHA-256 hashing (Working.recipes.short_hash) — the one
                    identifier for reproducibility, artifact naming, cache
                    lookup, and "what have I already tried".
execution.py       execute_recipe() — headless, runs a recipe's steps through
                    the Adapters/ registry, writes runs/detections. Cluster-safe;
                    see Pipelines/run_recipe/run_recipe.py for the CLI wrapper.
artifacts.py       Plots/ filename convention + explicit-save helper.
encoding_cache.py  Hash-keyed cache under DATA/derived/encodings/.
manifest.py        The single owner of the manifest schema — the version-1 JSON
                    written beside run artifacts (and exported run groups) and
                    read back by the manifest importer. See "The manifest".
database/          SQLite schema + plain-function queries: recordings,
                    annotations, reviewed spans, tag vocabulary, and the
                    run-tracking tables (configs/runs/detections/encodings/
                    motifs/artifacts) — the only DB access point, UI or headless.

Preprocessing/
  manage_data/     load_raw_data, window save/load, interactive window browser
  window_matrix/   WindowMatrix class, feature-column builders, WM plotting
Detection/
  analysis/        Dehshibi spike detection, wavelet, entropy, frequency, stats
  matrix_profiling/ stumpy motif/discord/chain plotting
  wavelet/         kymatio scattering transform + scalogram plots
  rupture/         ruptures change-point detection
  sax/             cSAX / pSAX encoders (+ csax_python, psax_python ports)
  aeon_features/   Catch22 feature extraction
Catalogue/
  gramian/         GASF / GADF / recurrence / fusion image encoding
  cnn/             EEG_CNN model, training, inference, CNN-assisted labeller
  dendrogram/      hierarchical clustering of the window matrix
  labelling/       interactive window labeller + subcategoriser
  aeon_classification/ Catch22 + RandomForest classifier and threshold sweep
Comparison/
  test_cnn.py      inference / accuracy scoring CLI
```

## The seven interchange types

Pipeline blocks are typed: a block may only follow one whose output type it
declares as its input. `Working/types/` defines the seven interchange types —
**Encoding**, **Grouping**, **Model**, **Scores**, **Signal**, **SpanSet**,
**WindowSet**. A step's `output_kind` must be one of these, and a block with an
`input_kind` may only be fed by a producer of that exact type.
`Working/chain_validation.check_step_compatibility` answers "can this output
type feed this block, and if not, why not".

## The manifest

`Working/manifest.py` is the single owner of the manifest schema. A manifest is
the portability payload written beside a run's artifacts (or an exported run
group): a JSON file with `manifest_version`, `code_version`, `created_at` and a
`runs` array. Each run block embeds the exact recipe that ran, its 8-character
`config_hash` (equal to `Working.recipes.short_hash` of the recipe), the
recording's content, the run's status and timings, its detections, and its
artifact paths. Paths are stored forward-slashed so a manifest written on the
Linux cluster reads correctly on a Windows worktree.

## Imports

Stage folders are Python packages, so imports are fully qualified from the repo
root:

```python
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Catalogue.gramian.gramian_calc import compute_fusion
```

Run everything from the repo root. Scripts that are executed directly carry a
repo-root bootstrap that walks up to the directory containing `Working/`.

## Where does new code go?

Ask: *is anything else going to import this?*

- **Yes** → here, in the stage folder matching what it does.
- **No, it's a one-off** → `Experimentation/<Stage> experiments/`.
- **It orchestrates several of these into one analysis** → `Pipelines/`.
