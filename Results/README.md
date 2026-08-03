# Results/

**Run outputs**, organised by the same four stages as `Working/`.

```
Detection/matrix_profile/    .npz matrix profiles from Pipelines/matrix_profile/
Catalogue/aeon/current/      aeon pipeline outputs (.pkl/.txt/.csv)
Catalogue/aeon/v1/           earlier aeon run, superseded by current/
```

These moved here because they were previously sitting *inside code directories*
(`matrix_profiling/results/`, `aeon_analysis/test_out{,_v1}/`), which made the
code tree hard to read. They are tracked in git.

## Outputs that deliberately did NOT move here

Three output directories stayed at the repo root, because they are hardcoded in
too many places for the churn to be worth it — most critically
`WindowMatrix.save_window()` writes to `MATRICES/` directly:

| Dir | Contents | Why it stayed |
|---|---|---|
| `MATRICES/` | Window-matrix feature CSVs (21 MB) | Hardcoded in `matrix_calc.py`, every `CSVFILE` constant, and two job scripts |
| `MODELS/` | Trained `.pth` / `.joblib` models (334 MB) | Hardcoded in job scripts and CFG defaults |
| `Plots/` | Saved figures (12 MB) | Written by hand from interactive sessions |

All three are gitignored. `Results/` is not.

## ⚠ Note on repo size

`Results/Detection/matrix_profile/` is **~40 MB of `.npz` already committed to
git history**. Moving it here did not shrink the repository — only a history
rewrite would, which is a separate decision. Think twice before adding more
large binaries here; consider gitignoring new output subfolders instead.

## Where do new outputs go?

Under the stage that produced them, in a folder named for the pipeline that
wrote it. If the output is large or regenerable, add it to `.gitignore` rather
than committing it.
