# DATA/

Mycelium bio-electric recordings and everything derived from them.
**~2.3 GB, entirely gitignored** — this tree is never committed. Moving files
here is a filesystem operation, not a git one.

## Layout

```
DATA/
  raw/                                    IMMUTABLE source recordings
    M2_concat_fs1.mat                      99 MB
    M2_aug_concat_fs1.mat                 273 MB
    M2_aug_concat_fs2.mat                 498 MB
    M4_aug_concat_fs1.mat                 180 MB

  db/                                      annotation database — NOT regenerable
    annotations.sqlite                     recordings, labels, run/detection tables

  derived/                                everything regenerable from raw/ + code
    channels/<recording>/CH<n>.npy          per-channel splits (16 per recording)
    subsamples/                             cut-down .mat subsamples
    windows/<scale>min_fs<fs>/
      labels/                               session + label index JSON/MAT
      rawdata/{interesting,notinteresting}/       *.npy windows
      rawdata_test/{interesting,notinteresting}/  *.npy held-out windows
      GASF/{interesting,notinteresting}/          *.png
      GADF/{interesting,notinteresting}/          *.png
      recurrence/{interesting,notinteresting}/    *.png
      fusion/{interesting,notinteresting}/        *.png
      subcategories/{clear,average,noisy,vague}/  JSON pointer files
```

### Example real paths

```
DATA/raw/M2_concat_fs1.mat
DATA/derived/channels/M2_concat_fs1/CH2.npy
DATA/derived/subsamples/0.01_percent_M2_concat_fs1.mat
DATA/derived/windows/10min_fs1.0/GASF/interesting/GASF_11214200.png
DATA/derived/windows/10min_fs1.0/rawdata/notinteresting/1743600.npy
DATA/derived/windows/10min_fs1.0/labels/10min_interesting_fs_1.00.mat
```

## Two principles this layout enforces

**1. Source is separated from derived.** Anything under `derived/` can be
regenerated from `raw/` plus code. Anything under `raw/` cannot be regenerated
at all — treat it as read-only. `cut_raw_data()` writes subsamples to
`derived/subsamples/`, never back into `raw/`.

**`db/` is a third category, not a variant of either.** It's not raw (not an
original recording) and — for the `recordings` table, which just mirrors
`derived/channels/`, that's fine — but the `annotations` table holds hours of
manual labelling work that cannot be regenerated from `raw/` + code the way
everything else under `derived/` can. It's gitignored like the rest of
`DATA/` (covered by the blanket `DATA/*` rule already), so back it up
separately if you're not relying on this whole tree being inside a synced
Drive folder to do that for you.

**2. Provenance is legible in the path.** Recording, window scale, sample rate,
encoding and class are directory levels, not substrings fused into a filename.
Only channel number and window start index stay in filenames, because they are
high-cardinality and only meaningful as leaves.

## ⚠ Encoding is the parent, class is the child

`DATA/derived/windows/10min_fs1.0/GASF/` is a **valid torchvision
`ImageFolder` root**, and that is deliberate. `ImageFolder` infers class labels
from the immediate subdirectory names, so:

- `interesting/` -> class **0**
- `notinteresting/` -> class **1**

(alphabetical, which is what `ImageFolder` uses). This ordering is hardcoded in
`Working/Catalogue/cnn/apply_cnn.py` and baked into every trained model in
`MODELS/`. **Do not rename these two directories, and do not add a third class
directory that sorts before `interesting`** — either would silently reinterpret
every existing model's output.

The previous layout fused class and encoding into one flat folder name
(`10min_fs1.0_interesting_GASF/`), which forced `cnn_rangapur.py` to build a
staging directory of symlinks to fake the nested structure. That staging hack
has been removed.

## Filename resolution

`load_raw_data()` still takes a **bare filename** — `"M2_concat_fs1_CH2.npy"`,
`"0.01_percent_M2_concat_fs1.mat"` — and `resolve_data_path()` in
`Working/Preprocessing/manage_data/load_data.py` maps it onto wherever the file
now lives (channel split, source recording, or subsample). You can also pass an
explicit path, which bypasses resolution.

## Naming convention

Recordings use an **uppercase `M<n>_` prefix**: `M2_concat_fs1`,
`M2_aug_concat_fs1`, `M2_aug_concat_fs2`, `M4_aug_concat_fs1`. Two files were
previously lowercase (`m2_aug_concat_fs2`, `m4_aug_concat_fs1`) while
`apply_cnn.py` already referred to them in uppercase — which worked on
case-insensitive Windows and raised `FileNotFoundError` on the Linux HPC.
Keep new recordings uppercase.

## Where does new data go?

- A **new recording** -> `raw/`, uppercase name, then never modify it.
- **Anything a script produced** -> under `derived/`, in a subfolder that makes
  clear what produced it.
- **Model weights, feature CSVs, figures** -> not here. Those live in
  `MODELS/`, `MATRICES/` and `Plots/` at the repo root (see `Results/README.md`).
- **Annotations, run/detection records** -> `db/annotations.sqlite`, via
  `Working/Preprocessing/database/queries.py`. Never written to directly.
